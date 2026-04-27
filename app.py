import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from base64 import b64encode

# ── Config ────────────────────────────────────────────────────────────────────
EPC_EMAIL = "newsunny3156@gmail.com"
EPC_KEY   = "de307eacaa9d463ed78c2525e3a17e450b42e79f"
EPC_API   = "https://epc.opendatacommunities.org/api/v1/domestic/search"
LR_SPARQL = "https://landregistry.data.gov.uk/landregistry/query"

st.set_page_config(
    page_title="UK Property Lookup",
    page_icon="🏠",
    layout="wide",
)

# ── Styling ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .block-container { padding-top: 2rem; max-width: 960px; }
    .metric-card {
        background: #f8f9fa; border-radius: 10px;
        padding: 1rem 1.2rem; text-align: center;
    }
    .metric-card .label { font-size: 12px; color: #666; margin-bottom: 4px; }
    .metric-card .value { font-size: 22px; font-weight: 600; color: #111; }
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
    "D": "#ffffbf", "E": "#fecc5c", "F": "#fd8d3c", "G": "#d7191c",
}
EPC_TEXT = {"A":"white","B":"white","C":"white","D":"#333","E":"#333","F":"white","G":"white"}

# ── Helpers ───────────────────────────────────────────────────────────────────
def clean_postcode(pc: str) -> str:
    return pc.strip().upper().replace("  ", " ")

def fmt_price(p) -> str:
    try:
        return f"£{int(float(p)):,}"
    except:
        return str(p)

def fetch_epc(postcode: str, number: str) -> dict | None:
    params = {"postcode": postcode, "size": 50}
    if number:
        params["address"] = number
    token = b64encode(f"{EPC_EMAIL}:{EPC_KEY}".encode()).decode()
    try:
        r = requests.get(EPC_API, params=params,
                         headers={"Accept": "application/json",
                                  "Authorization": f"Basic {token}"},
                         timeout=10)
        r.raise_for_status()
        data = r.json()
        rows = data.get("rows", [])
        return rows[0] if rows else None
    except Exception as e:
        st.warning(f"EPC API error: {e}")
        return None

def run_sparql(query: str) -> list[dict]:
    try:
        r = requests.get(LR_SPARQL,
                         params={"query": query, "output": "json"},
                         headers={"Accept": "application/sparql-results+json"},
                         timeout=15)
        r.raise_for_status()
        bindings = r.json()["results"]["bindings"]
        return [{k: v["value"] for k, v in b.items()} for b in bindings]
    except Exception as e:
        st.warning(f"Land Registry error: {e}")
        return []

def fetch_history(postcode: str, number: str) -> list[dict]:
    num_filter = f'FILTER(CONTAINS(LCASE(STR(?paon)), LCASE("{number}")))' if number else ""
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
    cutoff = (datetime.now() - timedelta(days=5*365)).strftime("%Y-%m-%d")
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

TYPE_MAP = {"D":"Detached","S":"Semi-detached","T":"Terraced","F":"Flat","O":"Other"}

def parse_type(uri: str) -> str:
    key = uri.split("/")[-1] if uri else ""
    return TYPE_MAP.get(key[:1].upper(), key)

def rows_to_df(rows: list[dict]) -> pd.DataFrame:
    records = []
    for r in rows:
        addr = " ".join(filter(None, [r.get("saon",""), r.get("paon",""), r.get("street","")]))
        records.append({
            "Date": r.get("date","")[:10],
            "Price": fmt_price(r.get("price",0)),
            "Price (£)": int(float(r.get("price",0))) if r.get("price") else 0,
            "Address": addr,
            "Type": parse_type(r.get("type","")),
        })
    return pd.DataFrame(records)

# ── UI ────────────────────────────────────────────────────────────────────────
st.title("🏠 UK Property Research")
st.caption("EPC energy ratings · Land Registry price paid · Area sales")

with st.form("search_form"):
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        postcode_in = st.text_input("Postcode", placeholder="e.g. SM6 9LD")
    with col2:
        number_in = st.text_input("House number / name", placeholder="e.g. 2")
    with col3:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        submitted = st.form_submit_button("Search", use_container_width=True, type="primary")

if submitted:
    postcode = clean_postcode(postcode_in)
    number   = number_in.strip()

    if not postcode:
        st.error("Please enter a postcode.")
        st.stop()

    # ── EPC ──────────────────────────────────────────────────────────────────
    st.subheader("Energy Performance Certificate")
    with st.spinner("Fetching EPC data…"):
        epc = fetch_epc(postcode, number)

    if epc:
        rating  = (epc.get("current-energy-rating") or "?").upper()
        score   = epc.get("current-energy-efficiency", "—")
        pot_r   = (epc.get("potential-energy-rating") or "—").upper()
        pot_s   = epc.get("potential-energy-efficiency", "—")
        floor   = epc.get("total-floor-area", "—")
        ptype   = epc.get("property-type", "—")
        bform   = epc.get("built-form", "—")
        tenure  = epc.get("tenure", "—")
        idate   = epc.get("lodgement-date") or epc.get("inspection-date", "—")
        addr    = ", ".join(filter(None, [epc.get("address1",""), epc.get("address2",""), epc.get("address3","")]))

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
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Current score", f"{score}/100")
            c2.metric("Potential", f"{pot_r} ({pot_s})")
            c3.metric("Floor area", f"{floor} m²")
            c4.metric("Tenure", tenure)
            st.caption(f"**{addr}** · {ptype} · {bform} · Inspected: {idate}")
    else:
        st.info("No EPC certificate found for this address. The property may not have been assessed since 2008, or may be a very new build.")

    st.divider()

    # ── History ───────────────────────────────────────────────────────────────
    st.subheader(f"Price paid history — {number+' ' if number else ''}{postcode}")
    with st.spinner("Fetching transaction history…"):
        hist_rows = fetch_history(postcode, number)

    if hist_rows:
        df_hist = rows_to_df(hist_rows)
        st.dataframe(
            df_hist[["Date","Price","Address","Type"]],
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("No transaction history found. Land Registry records sales from 1995 onwards.")

    st.divider()

    # ── Area sales ────────────────────────────────────────────────────────────
    st.subheader(f"Area sales — {postcode} (last 5 years)")
    with st.spinner("Fetching area sales…"):
        area_rows = fetch_area(postcode)

    if area_rows:
        df_area = rows_to_df(area_rows)
        prices  = df_area["Price (£)"].dropna()

        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Total sales", len(prices))
        c2.metric("Average", fmt_price(prices.mean()))
        c3.metric("Median",  fmt_price(prices.median()))
        c4.metric("Range",   f"{fmt_price(prices.min())} – {fmt_price(prices.max())}")

        if len(df_area) >= 3:
            chart_df = df_area[["Date","Price (£)"]].copy()
            chart_df["Date"] = pd.to_datetime(chart_df["Date"], errors="coerce")
            chart_df = chart_df.dropna().sort_values("Date").set_index("Date")
            st.line_chart(chart_df, y="Price (£)", use_container_width=True, height=220)

        st.dataframe(
            df_area[["Date","Price","Address","Type"]],
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("No sales found in this postcode in the last 5 years.")
