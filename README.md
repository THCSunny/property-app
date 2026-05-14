# 🏠 UK Property Research Tool

A Streamlit web app that aggregates UK property data into a single interface — no manual searching across multiple websites required.

## Features

### Energy Performance Certificate (EPC)
- Current energy rating (A–G) with colour-coded badge
- Efficiency score, potential rating, and floor area
- CO₂ emissions (current and potential) and estimated annual saving
- Construction details — walls, roof, floor, windows, heating, hot water — each with a colour-coded efficiency rating
- Running costs breakdown (heating, hot water, lighting) — current vs potential
- Energy consumption in kWh/m², compared against UK average
- Government-recommended improvement measures with typical savings and indicative costs

### Price Paid History
- Full transaction history for a specific address from the Land Registry (1995 to present)
- Exact house number matching to avoid partial matches

### Area Sales (Last 5 Years)
- All recorded sales within the same postcode
- Summary statistics: total sales, average, median, and price range
- Price trend chart
- EPC rating and floor area matched to each transaction where available

## Data Sources

| Source | Data provided | Authentication |
|---|---|---|
| [Get Energy Performance Data](https://get-energy-performance-data.communities.gov.uk) | EPC ratings, floor area, construction details, running costs, improvements | Bearer token (free) |
| [HM Land Registry SPARQL](https://landregistry.data.gov.uk) | Price paid transactions | None (open) |

## Deployment

### Streamlit Cloud (recommended)

1. Fork this repository to your GitHub account
2. Go to [share.streamlit.io](https://share.streamlit.io) and connect your GitHub account
3. Select this repository, set the main file path to `app.py`, and click **Deploy**
4. Under **Settings → Secrets**, add your EPC bearer token:

```toml
EPC_TOKEN = "your-bearer-token"
```

### Local installation

```bash
git clone https://github.com/THCSunny/property-app.git
cd property-app
pip install -r requirements.txt
```

Create `.streamlit/secrets.toml`:

```toml
EPC_TOKEN = "your-bearer-token"
```

Run:

```bash
streamlit run app.py
```

## Getting an EPC API Token

Register at [get-energy-performance-data.communities.gov.uk](https://get-energy-performance-data.communities.gov.uk) using a GOV.UK One Login account. Once registered, your bearer token is available in your account settings.

## Usage

1. Enter a UK postcode (e.g. `SM6 9LD`)
2. Enter a house number or name (e.g. `2`) to filter results to a specific property
3. Click **Search**

Results appear across four sections: EPC certificate, price paid history, and area sales.

## Notes

- EPC records only exist for properties assessed since 2008 (sold, rented, or voluntarily inspected)
- Land Registry records sales from 1995 onwards; some new builds or unregistered transfers may not appear
- EPC matching in the area sales table is based on house number; properties with non-numeric addresses may show `—`
- Land Registry SPARQL requests require a browser-style `User-Agent` header to avoid 403 errors

## Requirements

```
streamlit>=1.35.0
requests>=2.31.0
pandas>=2.0.0
```

## License

This project uses open government data licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
