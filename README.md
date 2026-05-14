# 🏠 UK Property Research Tool

A Streamlit web app that aggregates UK property data into a single interface — no manual searching across multiple websites required.

## Features

- **EPC Certificate** — Current energy rating (A–G), efficiency score, floor area, property type, tenure, and potential rating after improvements
- **Price Paid History** — Full transaction history for a specific address from the Land Registry (1995 to present), with exact house number matching
- **Area Sales (Last 5 Years)** — All recorded sales within the same postcode, including summary statistics (average, median, price range) and a price trend chart
- **EPC enrichment on area sales** — Each transaction in the area table is automatically matched with its EPC rating and floor area where available

## Data Sources

| Source | Data provided | Authentication |
|---|---|---|
| [EPC Open Data Communities](https://epc.opendatacommunities.org) | Energy ratings, floor area | API key required (free) |
| [HM Land Registry SPARQL](https://landregistry.data.gov.uk) | Price paid transactions | None (open) |

## Getting Started

### Prerequisites

- Python 3.10+
- A free EPC API key from [epc.opendatacommunities.org](https://epc.opendatacommunities.org)

### Local Installation

```bash
git clone https://github.com/THCSunny/property-app.git
cd property-app
pip install -r requirements.txt
```

Create a `.streamlit/secrets.toml` file:

```toml
EPC_EMAIL = "your-email@example.com"
EPC_KEY = "your-api-key"
```

Run the app:

```bash
streamlit run app.py
```

## Deploying to Streamlit Cloud

1. Fork or clone this repository to your GitHub account
2. Go to [share.streamlit.io](https://share.streamlit.io) and connect your GitHub account
3. Select this repository and set the main file path to `app.py`
4. Under **Settings → Secrets**, add your EPC credentials:

```toml
EPC_EMAIL = "your-email@example.com"
EPC_KEY = "your-api-key"
```

5. Click **Deploy**

## Usage

1. Enter a UK postcode (e.g. `SM6 9LD`)
2. Optionally enter a house number or name (e.g. `2`) to filter results to a specific property
3. Click **Search**

Results are displayed across three sections: EPC certificate, price paid history, and area sales.

## Notes

- EPC records only exist for properties assessed since 2008 (sold, rented, or voluntarily inspected)
- Land Registry records sales from 1995 onwards; some new builds or unregistered transfers may not appear
- EPC matching in the area sales table is based on house number; properties with non-numeric addresses (e.g. flat names) may show `—`
- Land Registry SPARQL requests require a browser-style `User-Agent` header to avoid 403 errors

## Requirements

```
streamlit>=1.35.0
requests>=2.31.0
pandas>=2.0.0
```

## License

This project uses open government data licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
