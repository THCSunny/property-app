import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta

# ── Config ────────────────────────────────────────────────────────────────────
EPC_TOKEN = st.secrets["EPC_TOKEN"]
EPC_API   = "https://api.get-energy-performance-data.communities.gov.uk/api/domestic/search"
LR_SPARQL = "https://landregistry.data.gov.uk/landregistry/query"

st.set_page_config(
    page_title="UK Property Lookup",
    page_icon="🏠",
    layout="wide",
)

st.markdown("""
<style>
    .block-container { padding-top: 2rem; max-width: 960px; }
    .epc-badge {
        display: inline-block; width: 48px; height: 48px;
        border-radius: 50%; line-height: 48px; text-align: center;
        font-size: 22px; font-weight: 700; color: white;
    }
    .stDataFrame { border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

EPC_COLORS = {
    "A": "#1a9641", "B": "#52b153", "C": "#9ecb60",
    "D": "#b0b000", "E": "#fecc5c", "F": "#fd8d3c", "G": "#d7191c",
}
EPC_TEXT = {"A":"white","B":"white","C":"white","D":"white","E":"#333","F":"white","G":"white"}

# ── Helpers ───────────────────────────────────────────────────────────────────
def clean_postcode(pc: str) -> str:
    return pc.strip().upper().replace("  ", " ")

def fmt_price(p) -> str:
    try:
        return f"£{int(float(p)):,}"
    except Exception:
        return str(p)

def epc_auth_header() -> dict:
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {EPC_TOKEN}",
    }

# ── EPC: parse new API response format ───────────────────────────────────────
def parse_epc_record(rec: dict) -> dict:
    """Normalise new camelCase API fields to internal keys."""
    return {
        "current-energy-rating":      (rec.get("currentEnergyEfficiencyBand") or "").upper(),
        "current-energy-efficiency":  rec.get("currentEnergyEfficiencyRating", ""),
        "potential-energy-rating":    (rec.get("potentialEnergyEfficiencyBand") or "").upper(),
        "potential-energy-efficiency": rec.get("potentialEnergyEfficiencyRating", ""),
        "total-floor-area":           rec.get("totalFloorArea", ""),
        "property-type":              rec.get("propertyType", ""),
        "built-form":                 rec.get("builtForm", ""),
        "tenure":                     rec.get("tenure", ""),
        "lodgement-date":             rec.get("registrationDate", ""),
        "address1":                   rec.get("addressLine1", ""),
        "address2":                   rec.get("addressLine2", ""),
        "address3":                   rec.get("addressLine3", ""),
    }

# ── EPC: single property ──────────────────────────────────────────────────────
def fetch_epc(postcode: str, number: str) -> dict | None:
    params = {"postcode": postcode, "page_size": 50}
    if number:
        params["address"] = number
    try:
        r = requests.get(EPC_API, params=params, headers=epc_auth_header(), timeout=10)
        r.raise_for_status()
        records = r.json().get("data", [])
        if not records:
            return None
        # If address filter applied, already filtered; else return first
        return parse_epc_record(records[0])
    except Exception as e:
        st.warning(f"EPC API error: {e}")
        return None

# ── EPC: all records for postcode → lookup dict keyed by house number ─────────
def fetch_all_epc(postcode: str) -> dict:
    try:
        r = requests.get(EPC_API,
                         params={"postcode": postcode, "page_size": 100},
                         headers=epc_auth_header(), timeout=10)
        r.raise_for_status()
        records = r.json().get("data", [])
    except Exception:
        return {}

    lookup: dict = {}
    for rec in records:
        addr1 = (rec.get("addressLine1") or "").strip().upper()
        key = _extract_number_key(addr1)
        if key and key not in lookup:
            lookup[key] = {
                "rating": (rec.get("currentEnergyEfficiencyBand") or "").upper(),
                "area":   rec.get("totalFloorArea", ""),
            }
    return lookup

def _extract_number_key(text: str) -> str:
    for tok in text.split():
        clean = tok.rstrip(",")
        if clean.isdigit() or (len(clean) >= 2 and clean[:-1].isdigit() and clean[-1].isalpha()):
            return clean.lstrip("0") or "0"
    return ""

def paon_to_key(paon: str) -> str:
    return _extract_number_key(paon.strip().upper())

# ── Land Registry ─────────────────────────────────────────────────────────────
def run_sparql(query: str) -> list[dict]:
    try:
        r = requests.get(LR_SPARQL,
                         params={"query": query, "output": "json"},
                         headers={
                             "Accept": "application/sparql-results+json",
                             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                         },
                         timeout=15)
        r.raise_for_status()
        bindings = r.json()["results"]["bindings"]
        return [{k: v["value"] for k, v in b.items()} for b in bindings]
    except Exception as e:
        st.warning(f"Land Registry error: {e}")
        return []

def fetch_history(postcode: str, number: str) -> list[dict]:
    num_filter = (
        f'FILTER(LCASE(REPLACE(STR(?paon), " ", "")) = LCASE(REPLACE("{number}", " ", "")))'
        if number else ""
    )
    q = f"""
PREFIX lrppi: <http://landregistry.data.gov.uk/def/ppi/>
PREFIX lrcommon: <http://landregistry.data.gov.uk/def/common/>
SELECT ?date ?price ?paon ?saon ?street ?type WHERE {{
  ?t lrppi:propertyAddress ?addr ;
     lrppi:pricePaid ?price ;
     lrppi:transactionDate ?date ;
     lrppi:propertyType ?type .
  ?addr lrcommon:postcode "{postcode}" .
  OPTIONAL {{?addr lrcommon:paon ?paon}}
  OPTIONAL {{?addr lrcommon:saon ?saon}}
  OPTIONAL {{?addr lrcommon:street ?street}}
  {num_filter}
}} ORDER BY DESC(?date) LIMIT 30"""
    return run_sparql(q)

def fetch_area(postcode: str) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=5 * 365)).strftime("%Y-%m-%d")
    q = f"""
PREFIX lrppi: <http://landregistry.data.gov.uk/def/ppi/>
PREFIX lrcommon: <http://landregistry.data.gov.uk/def/common/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?date ?price ?paon ?saon ?street ?type WHERE {{
  ?t lrppi:propertyAddress ?addr ;
     lrppi:pricePaid ?price ;
     lrppi:transactionDate ?date ;
     lrppi:propertyType ?type .
  ?addr lrcommon:postcode "{postcode}" .
  OPTIONAL {{?addr lrcommon:paon ?paon}}
  OPTIONAL {{?addr lrcommon:saon ?saon}}
  OPTIONAL {{?addr lrcommon:street ?street}}
  FILTER(?date >= "{cutoff}"^^xsd:date)
}} ORDER BY DESC(?date) LIMIT 100"""
    return run_sparql(q)

TYPE_MAP = {"D": "Detached", "S": "Semi-detached", "T": "Terraced", "F": "Flat", "O": "Other"}

def parse_type(uri: str) -> str:
    key = uri.split("/")[-1] if uri else ""
    return TYPE_MAP.get(key[:1].upper(), key)

def rows_to_df(rows: list[dict], epc_map: dict | None = None) -> pd.DataFrame:
    records = []
    for r in rows:
        paon = r.get("paon", "")
        addr = " ".join(filter(None, [r.get("saon", ""), paon, r.get("street", "")]))
        rec = {
            "Date":      r.get("date", "")[:10],
            "Price":     fmt_price(r.get("price", 0)),
            "Price (£)": int(float(r.get("price", 0))) if r.get("price") else 0,
            "Address":   addr,
            "Type":      parse_type(r.get("type", "")),
        }
        if epc_map is not None:
            key      = paon_to_key(paon) if paon else ""
            epc_info = epc_map.get(key, {})
            rec["EPC"] = epc_info.get("rating") or "—"
            rec["Area (m²)"] = epc_info.get("area") or "—"
        records.append(rec)
    return pd.DataFrame(records)

# ── UI ────────────────────────────────────────────────────────────────────────
st.title("🏠 UK Property Research")
st.caption("EPC energy ratings · Land Registry price paid · Area sales")

with st.form("search_form"):
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        postcode_in = st.text_input("Postcode", placeholder="e.g. SW1 1AA")
    with col2:
        number_in = st.text_input("House number / name", placeholder="e.g. 1")
    with col3:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        submitted = st.form_submit_button("Search", use_container_width=True, type="primary")

if submitted:
    postcode = clean_postcode(postcode_in)
    number   = number_in.strip()

    if not postcode:
        st.error("Please enter a postcode.")
        st.stop()

    # ── EPC ───────────────────────────────────────────────────────────────────
    st.subheader("Energy Performance Certificate")
    with st.spinner("Fetching EPC data…"):
        epc     = fetch_epc(postcode, number)
        epc_map = fetch_all_epc(postcode)

    if epc:
        rating = (epc.get("current-energy-rating") or "?").upper()
        score  = epc.get("current-energy-efficiency", "—")
        pot_r  = (epc.get("potential-energy-rating") or "—").upper()
        pot_s  = epc.get("potential-energy-efficiency", "—")
        floor  = epc.get("total-floor-area", "—")
        ptype  = epc.get("property-type", "—")
        bform  = epc.get("built-form", "—")
        tenure = epc.get("tenure", "—")
        idate  = epc.get("lodgement-date", "—")
        addr   = ", ".join(filter(None, [
            epc.get("address1", ""), epc.get("address2", ""), epc.get("address3", "")
        ]))

        col_badge, col_info = st.columns([1, 4])
        with col_badge:
            bg = EPC_COLORS.get(rating, "#aaa")
            tc = EPC_TEXT.get(rating, "white")
            st.markdown(f"""
            <div style='text-align:center;padding:1rem 0'>
              <div class='epc-badge' style='background:{bg};color:{tc};margin:auto'>{rating}</div>
              <div style='margin-top:8px;font-size:13px;color:#555'>Current rating</div>
            </div>""", unsafe_allow_html=True)
        with col_info:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Current score", f"{score}/100")
            c2.metric("Potential", f"{pot_r} ({pot_s})")
            c3.metric("Floor area", f"{floor} m²")
            c4.metric("Tenure", tenure)
            st.caption(f"**{addr}** · {ptype} · {bform} · Inspected: {idate}")
    else:
        st.info("No EPC certificate found. The property may not have been assessed since 2008.")

    st.divider()

    # ── Price paid history ────────────────────────────────────────────────────
    st.subheader(f"Price paid history — {number+' ' if number else ''}{postcode}")
    with st.spinner("Fetching transaction history…"):
        hist_rows = fetch_history(postcode, number)

    if hist_rows:
        df_hist = rows_to_df(hist_rows)
        st.dataframe(df_hist[["Date", "Price", "Address", "Type"]],
                     use_container_width=True, hide_index=True)
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

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total sales", len(prices))
        c2.metric("Average",     fmt_price(prices.mean()))
        c3.metric("Median",      fmt_price(prices.median()))
        c4.metric("Range",       f"{fmt_price(prices.min())} – {fmt_price(prices.max())}")

        if len(df_area) >= 3:
            chart_df = df_area[["Date", "Price (£)"]].copy()
            chart_df["Date"] = pd.to_datetime(chart_df["Date"], errors="coerce")
            chart_df = chart_df.dropna().sort_values("Date").set_index("Date")
            st.line_chart(chart_df, y="Price (£)", use_container_width=True, height=220)

        st.dataframe(
            df_area[["Date", "Price", "Address", "Type", "EPC", "Area (m²)"]],
            use_container_width=True, hide_index=True,
        )

        matched = (df_area["EPC"] != "—").sum()
        total   = len(df_area)
        if matched < total:
            st.caption(
                f"EPC matched for {matched}/{total} properties. "
                "Unmatched entries have no EPC record or use a non-numeric address."
            )
    else:
        st.info("No sales found in this postcode in the last 5 years.")
