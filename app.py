import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta

# ── Config ────────────────────────────────────────────────────────────────────
EPC_TOKEN = st.secrets["EPC_TOKEN"]
EPC_API      = "https://api.get-energy-performance-data.communities.gov.uk/api/domestic/search"
EPC_CERT_API = "https://api.get-energy-performance-data.communities.gov.uk/api/certificate"
LR_SPARQL    = "https://landregistry.data.gov.uk/landregistry/query"

st.set_page_config(page_title="UK Property Lookup", page_icon="🏠", layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 2rem; max-width: 1000px; }
    .epc-badge {
        display:inline-block;width:52px;height:52px;border-radius:50%;
        line-height:52px;text-align:center;font-size:24px;font-weight:700;
    }
    .detail-box {
        background:#f8f9fa;border-radius:8px;padding:10px 14px;
        font-size:13px;margin-bottom:6px;
    }
    .detail-box .label { color:#888;font-size:11px;margin-bottom:2px; }
    .detail-box .val   { font-weight:600;color:#111; }
    .improve-row {
        border-left:3px solid #52b153;padding:8px 12px;
        margin-bottom:8px;background:#f6fdf6;border-radius:0 6px 6px 0;
    }
</style>
""", unsafe_allow_html=True)

EPC_COLORS = {"A":"#1a9641","B":"#52b153","C":"#9ecb60","D":"#b0b000","E":"#fecc5c","F":"#fd8d3c","G":"#d7191c"}
EPC_TEXT   = {"A":"white","B":"white","C":"white","D":"white","E":"#333","F":"white","G":"white"}

TENURE_MAP    = {1:"Owner-occupied", 2:"Rented (social)", 3:"Rented (private)", 4:"Unknown"}
BUILT_FORM_MAP= {1:"Detached",2:"Semi-detached",3:"End-terrace",4:"Mid-terrace",5:"Enclosed end-terrace",6:"Enclosed mid-terrace"}
PROP_TYPE_MAP = {0:"House",1:"Flat",2:"Maisonette",3:"Park home",4:"Bungalow"}

def clean_postcode(pc): return pc.strip().upper().replace("  "," ")
def fmt_price(p):
    try: return f"£{int(float(p)):,}"
    except: return str(p)
def epc_auth(): return {"Accept":"application/json","Authorization":f"Bearer {EPC_TOKEN}"}
def star(n):
    n = int(n) if str(n).isdigit() else 0
    return "★"*n + "☆"*(5-n)

# ── EPC fetch ─────────────────────────────────────────────────────────────────
def _norm_num(s: str) -> str:
    """Normalise a number string for comparison."""
    return (s or "").strip().upper().lstrip("0") or "0"

def _rec_numbers(rec: dict):
    """Return set of candidate number keys from a search result record."""
    nums = set()
    for field in ("addressLine1", "addressLine2", "addressLine3", "addressLine4"):
        val = (rec.get(field) or "").strip().upper()
        k = _num_key(val)
        if k:
            nums.add(k)
    return nums

def _exact_match(rec: dict, number: str) -> bool:
    """Check if a search result exactly matches the house number."""
    if not number:
        return True
    target = _norm_num(number)
    return target in _rec_numbers(rec)

@st.cache_data(ttl=3600)
def fetch_epc(postcode, number):
    params = {"postcode": postcode, "page_size": 100}
    try:
        r = requests.get(EPC_API, params=params, headers=epc_auth(), timeout=10)
        r.raise_for_status()
        records = r.json().get("data", [])
        if not records: return None
        # Exact match on house number across all address lines
        if number:
            matched = [rec for rec in records if _exact_match(rec, number)]
            if matched:
                records = matched
        cert_num = records[0].get("certificateNumber")
        if cert_num:
            r2 = requests.get(EPC_CERT_API, params={"certificate_number": cert_num}, headers=epc_auth(), timeout=10)
            if r2.ok:
                d = r2.json().get("data", {})
                d["_search"] = records[0]
                return d
        return {"_search": records[0]}
    except Exception as e:
        st.warning(f"EPC API error: {e}")
        return None

@st.cache_data(ttl=3600)  # Cache for 1 hour per postcode
def fetch_all_epc(postcode):
    try:
        r = requests.get(EPC_API, params={"postcode":postcode,"page_size":100}, headers=epc_auth(), timeout=10)
        r.raise_for_status()
        records = r.json().get("data",[])
    except: return {}
    # Store all entries per key, then pick the one with largest floor area
    # This handles cases where a house has multiple EPC records (e.g. subdivided units)
    raw: dict = {}
    for rec in records:
        candidate_keys = _rec_numbers(rec)
        if not candidate_keys:
            continue
        area_val = ""
        cert_num = rec.get("certificateNumber")
        if cert_num:
            try:
                r2 = requests.get(EPC_CERT_API,
                                  params={"certificate_number": cert_num},
                                  headers=epc_auth(), timeout=8)
                if r2.ok:
                    area_val = str(r2.json().get("data", {}).get("total_floor_area", "") or "")
            except: pass
        entry = {
            "rating": (rec.get("currentEnergyEfficiencyBand") or "").upper(),
            "area": area_val,
        }
        for key in candidate_keys:
            if key not in raw:
                raw[key] = []
            raw[key].append(entry)

    # For each key, pick the record with the largest floor area
    lookup = {}
    for key, entries in raw.items():
        def area_num(e):
            try: return float(e["area"])
            except: return 0
        lookup[key] = max(entries, key=area_num)
    return lookup

def _num_key(text):
    for tok in text.split():
        c = tok.rstrip(",")
        if c.isdigit() or (len(c)>=2 and c[:-1].isdigit() and c[-1].isalpha()):
            return c.lstrip("0") or "0"
    return ""

def paon_to_key(paon): return _num_key(paon.strip().upper())

# ── Land Registry ─────────────────────────────────────────────────────────────
def run_sparql(query):
    try:
        r = requests.get(LR_SPARQL, params={"query":query,"output":"json"},
                         headers={"Accept":"application/sparql-results+json",
                                  "User-Agent":"Mozilla/5.0 Chrome/120.0.0.0"},
                         timeout=15)
        r.raise_for_status()
        return [{k:v["value"] for k,v in b.items()} for b in r.json()["results"]["bindings"]]
    except Exception as e:
        st.warning(f"Land Registry error: {e}"); return []

def fetch_history(postcode, number):
    nf = f'FILTER(LCASE(REPLACE(STR(?paon)," ",""))=LCASE(REPLACE("{number}"," ","")))' if number else ""
    return run_sparql(f"""
PREFIX lrppi: <http://landregistry.data.gov.uk/def/ppi/>
PREFIX lrcommon: <http://landregistry.data.gov.uk/def/common/>
SELECT ?date ?price ?paon ?saon ?street ?type WHERE {{
  ?t lrppi:propertyAddress ?addr ; lrppi:pricePaid ?price ;
     lrppi:transactionDate ?date ; lrppi:propertyType ?type .
  ?addr lrcommon:postcode "{postcode}" .
  OPTIONAL {{?addr lrcommon:paon ?paon}} OPTIONAL {{?addr lrcommon:saon ?saon}}
  OPTIONAL {{?addr lrcommon:street ?street}} {nf}
}} ORDER BY DESC(?date) LIMIT 30""")

def fetch_area(postcode):
    cutoff = (datetime.now()-timedelta(days=5*365)).strftime("%Y-%m-%d")
    return run_sparql(f"""
PREFIX lrppi: <http://landregistry.data.gov.uk/def/ppi/>
PREFIX lrcommon: <http://landregistry.data.gov.uk/def/common/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?date ?price ?paon ?saon ?street ?type WHERE {{
  ?t lrppi:propertyAddress ?addr ; lrppi:pricePaid ?price ;
     lrppi:transactionDate ?date ; lrppi:propertyType ?type .
  ?addr lrcommon:postcode "{postcode}" .
  OPTIONAL {{?addr lrcommon:paon ?paon}} OPTIONAL {{?addr lrcommon:saon ?saon}}
  OPTIONAL {{?addr lrcommon:street ?street}}
  FILTER(?date >= "{cutoff}"^^xsd:date)
}} ORDER BY DESC(?date) LIMIT 100""")

TYPE_MAP = {"D":"Detached","S":"Semi-detached","T":"Terraced","F":"Flat","O":"Other"}
def parse_type(uri):
    k = uri.split("/")[-1] if uri else ""
    return TYPE_MAP.get(k[:1].upper(), k)

def rows_to_df(rows, epc_map=None):
    recs=[]
    for r in rows:
        paon=r.get("paon","")
        addr=" ".join(filter(None,[r.get("saon",""),paon,r.get("street","")]))
        rec={"Date":r.get("date","")[:10],"Price":fmt_price(r.get("price",0)),
             "Price (£)":int(float(r.get("price",0))) if r.get("price") else 0,
             "Address":addr,"Type":parse_type(r.get("type",""))}
        if epc_map is not None:
            key=paon_to_key(paon) if paon else ""
            info=epc_map.get(key,{})
            rec["EPC"]=info.get("rating") or "—"
        recs.append(rec)
    return pd.DataFrame(recs)

# ── UI ────────────────────────────────────────────────────────────────────────
st.title("🏠 UK Property Research")
st.caption("EPC energy ratings · Land Registry price paid · Area sales")

with st.form("search_form"):
    c1,c2,c3=st.columns([2,2,1])
    with c1: postcode_in=st.text_input("Postcode",placeholder="e.g. M5 5EG")
    with c2: number_in=st.text_input("House number / name",placeholder="e.g. 39")
    with c3:
        st.markdown("<div style='height:28px'></div>",unsafe_allow_html=True)
        submitted=st.form_submit_button("Search",use_container_width=True,type="primary")

if submitted:
    postcode=clean_postcode(postcode_in)
    number=number_in.strip()
    if not postcode: st.error("Please enter a postcode."); st.stop()

    # ── EPC ───────────────────────────────────────────────────────────────────
    st.subheader("Energy Performance Certificate")
    with st.spinner("Fetching EPC data…"):
        epc     = fetch_epc(postcode, number)
        epc_map = fetch_all_epc(postcode)

    if epc:
        d  = epc
        sr = epc.get("_search", {})

        rating   = (d.get("current_energy_efficiency_band") or sr.get("currentEnergyEfficiencyBand") or "?").upper()
        pot_r    = (d.get("potential_energy_efficiency_band") or "—").upper()
        score    = d.get("energy_rating_current", "")
        pot_s    = d.get("energy_rating_potential", "")
        floor    = d.get("total_floor_area", "")
        tenure   = TENURE_MAP.get(d.get("tenure"), str(d.get("tenure","—")))
        built    = BUILT_FORM_MAP.get(d.get("built_form"), str(d.get("built_form","—")))
        ptype    = PROP_TYPE_MAP.get(d.get("property_type"), str(d.get("property_type","—")))
        idate    = d.get("inspection_date") or d.get("registration_date") or sr.get("registrationDate","—")
        addr1    = d.get("address_line_1") or sr.get("addressLine1","")
        # dwelling_type may be a dict with 'value' key
        dwelling_raw = d.get("dwelling_type","")
        if isinstance(dwelling_raw, dict):
            dwelling = dwelling_raw.get("value", "")
        else:
            dwelling = str(dwelling_raw) if dwelling_raw else ""

        co2_cur  = d.get("co2_emissions_current","")
        co2_pot  = d.get("co2_emissions_potential","")
        energy_cur  = d.get("energy_consumption_current","")
        energy_pot  = d.get("energy_consumption_potential","")
        heat_cost   = (d.get("heating_cost_current") or {}).get("value","")
        water_cost  = (d.get("hot_water_cost_current") or {}).get("value","")
        light_cost  = (d.get("lighting_cost_current") or {}).get("value","")
        heat_pot    = (d.get("heating_cost_potential") or {}).get("value","")
        water_pot   = (d.get("hot_water_cost_potential") or {}).get("value","")
        light_pot   = (d.get("lighting_cost_potential") or {}).get("value","")

        # ── Hero card ─────────────────────────────────────────────────────────
        bg = EPC_COLORS.get(rating, "#aaa")
        tc = EPC_TEXT.get(rating, "white")
        total_cur = sum(x for x in [heat_cost, water_cost, light_cost] if x != "")
        total_pot = sum(x for x in [heat_pot, water_pot, light_pot] if x != "")
        saving_str = f"£{total_cur - total_pot:,}/yr saving possible" if total_cur and total_pot else ""

        st.markdown(f"""
        <div style="border:1px solid #e0e0e0;border-radius:12px;padding:20px 24px;margin-bottom:16px;background:#fafafa">
          <div style="display:flex;align-items:center;gap:20px;margin-bottom:16px">
            <div style="width:64px;height:64px;border-radius:50%;background:{bg};color:{tc};
                        display:flex;align-items:center;justify-content:center;
                        font-size:28px;font-weight:700;flex-shrink:0">{rating}</div>
            <div>
              <div style="font-size:18px;font-weight:600;color:#111">{addr1}</div>
              <div style="font-size:13px;color:#666;margin-top:2px">{dwelling or ptype} &nbsp;·&nbsp; {built} &nbsp;·&nbsp; {tenure} &nbsp;·&nbsp; Inspected: {idate}</div>
            </div>
          </div>
          <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px">
            <div style="background:white;border:1px solid #eee;border-radius:8px;padding:10px;text-align:center">
              <div style="font-size:11px;color:#888;margin-bottom:4px">Current score</div>
              <div style="font-size:20px;font-weight:600">{score or "—"}<span style="font-size:12px;color:#999">/100</span></div>
            </div>
            <div style="background:white;border:1px solid #eee;border-radius:8px;padding:10px;text-align:center">
              <div style="font-size:11px;color:#888;margin-bottom:4px">Potential</div>
              <div style="font-size:20px;font-weight:600">{pot_r} <span style="font-size:14px;color:#555">({pot_s})</span></div>
            </div>
            <div style="background:white;border:1px solid #eee;border-radius:8px;padding:10px;text-align:center">
              <div style="font-size:11px;color:#888;margin-bottom:4px">Floor area</div>
              <div style="font-size:20px;font-weight:600">{floor or "—"}<span style="font-size:12px;color:#999"> m²</span></div>
            </div>
            <div style="background:{"#f0fdf4" if saving_str else "white"};border:1px solid {"#86efac" if saving_str else "#eee"};border-radius:8px;padding:10px;text-align:center">
              <div style="font-size:11px;color:#888;margin-bottom:4px">Annual saving</div>
              <div style="font-size:14px;font-weight:600;color:{"#166534" if saving_str else "#999"}">{saving_str or "—"}</div>
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        # Property details tabs
        tab1, tab2, tab3, tab4 = st.tabs(["🏗 Construction", "💷 Running costs", "⚡ Energy use", "🔧 Improvements"])

        with tab1:
            walls   = d.get("walls",[{}])[0]
            roof    = d.get("roofs",[{}])[0]
            floor_d = d.get("floors",[{}])[0]
            window  = d.get("window",{})
            heating = d.get("main_heating",[{}])[0]
            hotwater= d.get("hot_water",{})

            def get_desc(obj):
                """Extract description string whether it is a str or {value:..} dict."""
                if isinstance(obj, dict):
                    return obj.get("value") or obj.get("description") or "—"
                return str(obj) if obj else "—"

            ELEMENT_ICONS = {"Walls":"🧱","Roof":"🏠","Floor":"⬜","Windows":"🪟","Heating":"🔥","Hot water":"🚿"}
            const_rows = [
                ("Walls",     get_desc(walls.get("description")),    walls.get("energy_efficiency_rating",0)),
                ("Roof",      get_desc(roof.get("description")),     roof.get("energy_efficiency_rating",0)),
                ("Floor",     get_desc(floor_d.get("description")),  floor_d.get("energy_efficiency_rating",0)),
                ("Windows",   get_desc(window.get("description")),   window.get("energy_efficiency_rating",0)),
                ("Heating",   get_desc(heating.get("description")),  heating.get("energy_efficiency_rating",0)),
                ("Hot water", get_desc(hotwater.get("description")), hotwater.get("energy_efficiency_rating",0)),
            ]

            html_rows = ""
            for element, desc, rating_num in const_rows:
                rating_num = int(rating_num) if str(rating_num).isdigit() else 0
                filled = "★" * rating_num
                empty  = "☆" * (5 - rating_num)
                color  = ["#d7191c","#fd8d3c","#fecc5c","#9ecb60","#1a9641"][min(rating_num,4)] if rating_num>0 else "#ccc"
                icon   = ELEMENT_ICONS.get(element,"")
                html_rows += f"""
                <tr>
                  <td style="padding:10px 14px;font-weight:500;white-space:nowrap;color:#333">{icon} {element}</td>
                  <td style="padding:10px 14px;color:#555;font-size:13px">{desc}</td>
                  <td style="padding:10px 14px;white-space:nowrap">
                    <span style="color:{color};font-size:16px;letter-spacing:2px">{filled}</span><span style="color:#ddd;font-size:16px;letter-spacing:2px">{empty}</span>
                    <span style="margin-left:6px;font-size:12px;color:#999">{rating_num}/5</span>
                  </td>
                </tr>"""

            st.markdown(f"""
            <table style="width:100%;border-collapse:collapse;font-size:14px">
              <thead>
                <tr style="border-bottom:2px solid #f0f0f0">
                  <th style="padding:8px 14px;text-align:left;color:#888;font-weight:500;font-size:12px;text-transform:uppercase;letter-spacing:0.05em;width:120px">Element</th>
                  <th style="padding:8px 14px;text-align:left;color:#888;font-weight:500;font-size:12px;text-transform:uppercase;letter-spacing:0.05em">Description</th>
                  <th style="padding:8px 14px;text-align:left;color:#888;font-weight:500;font-size:12px;text-transform:uppercase;letter-spacing:0.05em;width:160px">Efficiency</th>
                </tr>
              </thead>
              <tbody>{html_rows}</tbody>
            </table>
            """, unsafe_allow_html=True)

        with tab2:
            st.markdown("**Current vs potential annual costs**")
            cost_data = {
                "Category": ["Heating","Hot water","Lighting","Total"],
                "Current (£)": [
                    heat_cost, water_cost, light_cost,
                    sum(x for x in [heat_cost,water_cost,light_cost] if x != "")
                ],
                "Potential (£)": [
                    heat_pot, water_pot, light_pot,
                    sum(x for x in [heat_pot,water_pot,light_pot] if x != "")
                ],
            }
            df_cost = pd.DataFrame(cost_data)
            st.dataframe(df_cost, use_container_width=True, hide_index=True)
            if heat_cost and heat_pot:
                total_saving = (
                    (int(heat_cost)+int(water_cost)+int(light_cost)) -
                    (int(heat_pot)+int(water_pot)+int(light_pot))
                )
                st.success(f"Potential annual saving if all improvements made: **£{total_saving:,}**")

        with tab3:
            avg = d.get("energy_rating_average","")
            st.markdown(f"""
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px">
              <div style="background:#f8f9fa;border-radius:8px;padding:14px 16px">
                <div style="font-size:11px;color:#888;margin-bottom:4px;text-transform:uppercase;letter-spacing:0.05em">Energy use now</div>
                <div style="font-size:22px;font-weight:600">{energy_cur or "—"}<span style="font-size:13px;color:#999;margin-left:4px">kWh/m²</span></div>
              </div>
              <div style="background:#f0fdf4;border-radius:8px;padding:14px 16px">
                <div style="font-size:11px;color:#888;margin-bottom:4px;text-transform:uppercase;letter-spacing:0.05em">Potential</div>
                <div style="font-size:22px;font-weight:600;color:#166534">{energy_pot or "—"}<span style="font-size:13px;color:#888;margin-left:4px">kWh/m²</span></div>
              </div>
            </div>
            {"<div style='background:#eff6ff;border-radius:8px;padding:12px 16px;font-size:13px;color:#1e40af'>UK average energy score: <strong>" + str(avg) + "/100</strong> — this property scores <strong>" + str(score) + "/100</strong></div>" if avg else ""}
            """, unsafe_allow_html=True)

        with tab4:
            improvements = d.get("suggested_improvements", [])
            if improvements:
                total_saving = sum(i.get("typical_saving",{}).get("value",0) for i in improvements)
                st.markdown(f"**{len(improvements)} recommended improvements** · Combined typical saving: **£{total_saving:,}/year**")
                for imp in improvements:
                    saving  = imp.get("typical_saving",{}).get("value","")
                    cost    = imp.get("indicative_cost","")
                    new_rating = imp.get("energy_performance_rating","")
                    itype   = imp.get("improvement_type","")
                    st.markdown(f"""<div class='improve-row'>
                        <strong>Improvement {imp.get('sequence','')}: {itype}</strong><br>
                        Typical saving: <strong>£{saving}/year</strong> &nbsp;·&nbsp;
                        Indicative cost: <strong>£{cost}</strong> &nbsp;·&nbsp;
                        New rating after: <strong>{new_rating}/100</strong>
                    </div>""", unsafe_allow_html=True)
            else:
                st.info("No improvement suggestions available.")
    else:
        st.info("No EPC certificate found. The property may not have been assessed since 2008.")

    st.divider()

    # ── Price paid history ────────────────────────────────────────────────────
    st.subheader(f"Price paid history — {number+' ' if number else ''}{postcode}")
    with st.spinner("Fetching transaction history…"):
        hist_rows = fetch_history(postcode, number)

    if hist_rows:
        df_hist = rows_to_df(hist_rows)
        st.dataframe(df_hist[["Date","Price","Address","Type"]], use_container_width=True, hide_index=True)
    else:
        st.info("No transaction history found. Land Registry records sales from 1995 onwards.")

    st.divider()

    # ── Area sales ────────────────────────────────────────────────────────────
    st.subheader(f"Area sales — {postcode} (last 5 years)")
    with st.spinner("Fetching area sales…"):
        area_rows = fetch_area(postcode)

    if area_rows:
        df_area = rows_to_df(area_rows, epc_map=epc_map)

        # EPC + Area matching
        def best_epc_match(address):
            """Match EPC data by house number.
            For normal addresses (e.g. '84 GUY ROAD'), only try the first numeric token.
            For flat addresses (e.g. 'FLAT 1 50 MANOR ROAD'), try both flat number and house number.
            Never fall through to unrelated numbers in the street name."""
            if not address:
                return {}
            tokens = address.upper().split()
            numeric_tokens = []
            for tok in tokens:
                clean = tok.rstrip(",")
                if clean.isdigit() or (len(clean) >= 2 and clean[:-1].isdigit() and clean[-1].isalpha()):
                    numeric_tokens.append(clean.lstrip("0") or "0")

            if not numeric_tokens:
                return {}

            # If starts with non-numeric word (e.g. "FLAT"), it is a flat — try all numeric tokens
            first_word = tokens[0].rstrip(",")
            is_flat = not (first_word.isdigit() or (len(first_word) >= 2 and first_word[:-1].isdigit() and first_word[-1].isalpha()))

            if is_flat:
                for key in numeric_tokens:
                    info = epc_map.get(key, {})
                    if info:
                        return info
                return {}
            else:
                # Normal address — only try the first (house) number, never fall through
                return epc_map.get(numeric_tokens[0], {})

        df_area["Area (m²)"] = df_area["Address"].apply(
            lambda addr: best_epc_match(addr).get("area", "—") or "—"
        )
        df_area["EPC"] = df_area["Address"].apply(
            lambda addr: best_epc_match(addr).get("rating", "—") or "—"
        )

        # £/m² column
        def calc_price_per_m2(row):
            try:
                area = float(row["Area (m²)"])
                price = float(row["Price (£)"])
                if area > 0:
                    return round(price / area)
            except:
                pass
            return None
        df_area["£/m²"] = df_area.apply(calc_price_per_m2, axis=1)

        # Date for charting
        df_area["Date_dt"] = pd.to_datetime(df_area["Date"], errors="coerce")
        df_area["Year"] = df_area["Date_dt"].dt.year

        prices = df_area["Price (£)"].dropna()

        # ── Summary stats ─────────────────────────────────────────────────────
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Total sales", len(prices))
        c2.metric("Average",  fmt_price(prices.mean()))
        c3.metric("Median",   fmt_price(prices.median()))
        c4.metric("Range",    f"{fmt_price(prices.min())} – {fmt_price(prices.max())}")

        # ── Market analysis tabs ──────────────────────────────────────────────
        mkt1, mkt2, mkt3 = st.tabs(["📈 Price trends", "💷 Price per m²", "📊 Sales volume"])

        with mkt1:
            # Summary by type
            type_summary = df_area.groupby("Type")["Price (£)"].agg(
                Count="count", Average="mean", Median="median"
            ).reset_index()
            type_summary["Average"] = type_summary["Average"].apply(fmt_price)
            type_summary["Median"]  = type_summary["Median"].apply(fmt_price)
            st.dataframe(type_summary, use_container_width=True, hide_index=True)

        with mkt2:
            ppm2_data = df_area[df_area["£/m²"].notna()]
            if len(ppm2_data) >= 2:
                avg_ppm2 = round(ppm2_data["£/m²"].mean())
                med_ppm2 = round(ppm2_data["£/m²"].median())
                min_ppm2 = round(ppm2_data["£/m²"].min())
                max_ppm2 = round(ppm2_data["£/m²"].max())

                p1,p2,p3,p4 = st.columns(4)
                p1.metric("Matched properties", len(ppm2_data))
                p2.metric("Average £/m²", f"£{avg_ppm2:,}")
                p3.metric("Median £/m²",  f"£{med_ppm2:,}")
                p4.metric("Range £/m²",   f"£{min_ppm2:,} – £{max_ppm2:,}")

                # By type
                if df_area["Type"].nunique() > 1:
                    st.markdown("**£/m² by property type**")
                    type_ppm2 = ppm2_data.groupby("Type")["£/m²"].agg(
                        Count="count", Average="mean", Median="median"
                    ).reset_index()
                    type_ppm2["Average"] = type_ppm2["Average"].apply(lambda x: f"£{round(x):,}")
                    type_ppm2["Median"]  = type_ppm2["Median"].apply(lambda x: f"£{round(x):,}")
                    st.dataframe(type_ppm2, use_container_width=True, hide_index=True)
            else:
                st.info("Not enough EPC area data to calculate £/m². EPC records need to be available for at least 2 properties.")

        with mkt3:
            if df_area["Year"].notna().sum() > 0:
                # Sales volume by year
                vol_by_year = df_area.groupby("Year").size().reset_index(name="Total Sales")
                vol_by_year["Year"] = vol_by_year["Year"].astype(str)

                if df_area["Type"].nunique() > 1:
                    vol_type = df_area.groupby(["Year","Type"]).size().reset_index(name="Sales")
                    vol_pivot = vol_type.pivot_table(index="Year", columns="Type", values="Sales", fill_value=0).reset_index()
                    vol_pivot["Year"] = vol_pivot["Year"].astype(str)
                    vol_pivot["Total"] = vol_pivot.drop(columns="Year").sum(axis=1)
                    st.dataframe(vol_pivot, use_container_width=True, hide_index=True)
                else:
                    st.dataframe(vol_by_year, use_container_width=True, hide_index=True)

        # ── Full transactions table ───────────────────────────────────────────
        st.markdown("**All transactions**")
        display_cols = ["Date","Price","Address","Type","EPC","Area (m²)","£/m²"]
        df_display = df_area[display_cols].copy()
        df_display["£/m²"] = df_display["£/m²"].apply(lambda x: f"£{int(x):,}" if pd.notna(x) else "—")
        st.dataframe(df_display, use_container_width=True, hide_index=True)

        matched = (df_area["EPC"] != "—").sum()
        if matched < len(df_area):
            st.caption(f"EPC matched for {matched}/{len(df_area)} properties. £/m² only shown where EPC area data is available.")
    else:
        st.info("No sales found in this postcode in the last 5 years.")
