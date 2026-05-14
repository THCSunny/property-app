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
def _exact_match(rec: dict, number: str) -> bool:
    """Check if a search result exactly matches the house number."""
    if not number:
        return True
    addr1 = (rec.get("addressLine1") or "").strip().upper()
    key = _num_key(addr1)
    return key == (number.strip().upper().lstrip("0") or "0")

def fetch_epc(postcode, number):
    params = {"postcode": postcode, "page_size": 100}
    try:
        r = requests.get(EPC_API, params=params, headers=epc_auth(), timeout=10)
        r.raise_for_status()
        records = r.json().get("data", [])
        if not records: return None
        # Exact match on house number
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

def fetch_all_epc(postcode):
    try:
        r = requests.get(EPC_API, params={"postcode":postcode,"page_size":100}, headers=epc_auth(), timeout=10)
        r.raise_for_status()
        records = r.json().get("data",[])
    except: return {}
    lookup = {}
    for rec in records:
        addr1 = (rec.get("addressLine1") or "").strip().upper()
        key = _num_key(addr1)
        if key and key not in lookup:
            # Fetch full certificate for floor area
            area = ""
            cert_num = rec.get("certificateNumber")
            if cert_num:
                try:
                    r2 = requests.get(EPC_CERT_API,
                                      params={"certificate_number": cert_num},
                                      headers=epc_auth(), timeout=8)
                    if r2.ok:
                        area = str(r2.json().get("data", {}).get("total_floor_area", "") or "")
                except: pass
            lookup[key] = {
                "rating": (rec.get("currentEnergyEfficiencyBand") or "").upper(),
                "area": area,
            }
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
        dwelling = d.get("dwelling_type","")

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

        # Badge + headline
        col_badge, col_info = st.columns([1,4])
        with col_badge:
            bg=EPC_COLORS.get(rating,"#aaa"); tc=EPC_TEXT.get(rating,"white")
            st.markdown(f"""<div style='text-align:center;padding:1rem 0'>
              <div class='epc-badge' style='background:{bg};color:{tc};margin:auto'>{rating}</div>
              <div style='margin-top:6px;font-size:12px;color:#666'>Current rating</div>
            </div>""", unsafe_allow_html=True)
        with col_info:
            m1,m2,m3,m4,m5 = st.columns(5)
            m1.metric("Current score", f"{score}/100" if score else "—")
            m2.metric("Potential", f"{pot_r} ({pot_s})" if pot_s else pot_r)
            m3.metric("Floor area", f"{floor} m²" if floor else "—")
            m4.metric("Tenure", tenure)
            m5.metric("CO₂ now / potential", f"{co2_cur} / {co2_pot} t" if co2_cur else "—")
            st.caption(f"**{addr1}** · {dwelling or ptype} · {built} · Inspected: {idate}")

        # Property details tabs
        tab1, tab2, tab3, tab4 = st.tabs(["🏗 Property details", "💷 Running costs", "⚡ Energy use", "🔧 Improvements"])

        with tab1:
            r1,r2,r3,r4 = st.columns(4)
            r1.metric("Property type", ptype)
            r2.metric("Built form", built)
            r3.metric("Tenure", tenure)
            r4.metric("Floor area", f"{floor} m²" if floor else "—")

            walls   = d.get("walls",[{}])[0]
            roof    = d.get("roofs",[{}])[0]
            floor_d = d.get("floors",[{}])[0]
            window  = d.get("window",{})
            heating = d.get("main_heating",[{}])[0]
            hotwater= d.get("hot_water",{})

            st.markdown("**Construction & systems**")
            rows = [
                ("Walls",    walls.get("description","—"),    star(walls.get("energy_efficiency_rating",0))),
                ("Roof",     roof.get("description","—"),     star(roof.get("energy_efficiency_rating",0))),
                ("Floor",    floor_d.get("description","—"),  star(floor_d.get("energy_efficiency_rating",0))),
                ("Windows",  window.get("description","—"),   star(window.get("energy_efficiency_rating",0))),
                ("Heating",  heating.get("description","—"),  star(heating.get("energy_efficiency_rating",0))),
                ("Hot water",hotwater.get("description","—"), star(hotwater.get("energy_efficiency_rating",0))),
            ]
            df_const = pd.DataFrame(rows, columns=["Element","Description","Efficiency"])
            st.dataframe(df_const, use_container_width=True, hide_index=True)

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
            e1,e2,e3,e4 = st.columns(4)
            e1.metric("Energy use now", f"{energy_cur} kWh/m²" if energy_cur else "—")
            e2.metric("Energy use potential", f"{energy_pot} kWh/m²" if energy_pot else "—")
            e3.metric("CO₂ now", f"{co2_cur} tonnes" if co2_cur else "—")
            e4.metric("CO₂ potential", f"{co2_pot} tonnes" if co2_pot else "—")
            avg = d.get("energy_rating_average","")
            if avg:
                st.info(f"UK average energy score: **{avg}/100** — this property scores **{score}/100**")

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
        prices  = df_area["Price (£)"].dropna()

        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Total sales", len(prices))
        c2.metric("Average",  fmt_price(prices.mean()))
        c3.metric("Median",   fmt_price(prices.median()))
        c4.metric("Range",    f"{fmt_price(prices.min())} – {fmt_price(prices.max())}")

        if len(df_area) >= 3:
            chart_df = df_area[["Date","Price (£)"]].copy()
            chart_df["Date"] = pd.to_datetime(chart_df["Date"], errors="coerce")
            chart_df = chart_df.dropna().sort_values("Date").set_index("Date")
            st.line_chart(chart_df, y="Price (£)", use_container_width=True, height=220)

        # Add Area column from epc_map
        df_area["Area (m²)"] = df_area.apply(
            lambda row: epc_map.get(paon_to_key(row["Address"].split()[0]) if row["Address"] else "", {}).get("area", "—") or "—",
            axis=1
        )
        st.dataframe(df_area[["Date","Price","Address","Type","EPC","Area (m²)"]], use_container_width=True, hide_index=True)

        matched = (df_area["EPC"] != "—").sum()
        if matched < len(df_area):
            st.caption(f"EPC matched for {matched}/{len(df_area)} properties.")
    else:
        st.info("No sales found in this postcode in the last 5 years.")
