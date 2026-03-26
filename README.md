<div align="center">

# 🏢 PropAI

### Open-source AI copilot for real estate investment

**Underwrite deals · Model developments · Research markets · Generate institutional memos**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![Claude](https://img.shields.io/badge/Powered%20by-Claude-orange)](https://anthropic.com)
[![Tests](https://img.shields.io/badge/Tests-47%20passing-brightgreen)](#testing)

<br/>

<!-- DEMO GIF — replace with actual screen recording before launch -->
<img src="docs/assets/demo.gif" alt="PropAI demo" width="860" />

<br/>

### [🚀 Live Demo](https://propai.dev) &nbsp;·&nbsp; [📖 Docs](https://docs.propai.dev) &nbsp;·&nbsp; [💬 Discord](https://discord.gg/propai)

</div>

---

## What is PropAI?

PropAI is a full-stack real estate investment intelligence platform that replaces spreadsheets and $5,000/year SaaS tools with an open-source, AI-native workflow.

Type a deal in plain English. Get back a complete underwriting, market analysis, and a PDF investment memo that looks like it came from a top-tier private equity firm — in under 60 seconds.

```
"24-unit apartment in Austin TX at $4.8M. Rents average $2,000/mo.
 70% LTV at 6.75%, 5-year hold, exit at a 5.5 cap."
```

↓

✅ Full 5-year pro forma &nbsp; ✅ IRR, NPV, equity multiple &nbsp; ✅ Sensitivity tables
✅ Market intelligence (Census, FRED, HUD, Zillow) &nbsp; ✅ AI investment memo PDF

---

## Features

### 📊 Financial Engine
- **Pro forma modeling** — year-by-year NOI, debt service, and cash flow projections
- **Full returns suite** — IRR, NPV, cap rate, cash-on-cash, DSCR, GRM, equity multiple
- **Sensitivity analysis** — 5×5 IRR and CoC grids (exit cap rate × rent growth)
- **Equity waterfall** — LP/GP promote structures with multiple IRR hurdles
- **Loan modeling** — fixed rate, interest-only, and IO-then-amortizing structures

### 🗺️ Market Intelligence (all free APIs)
- **Census Bureau** — demographics, income, housing, vacancy, homeownership
- **FRED** — mortgage rates, CPI, unemployment, GDP, 10yr Treasury, housing starts
- **HUD** — Fair Market Rents by bedroom count for every US county
- **Zillow Research** — home value and rent trends, YoY%, 3/5-year CAGRs

### 🤖 AI Agents (powered by Claude)
- **Natural language deal input** — describe a deal in plain English, get a structured `DealInput`
- **Investment memo generator** — 9-section institutional memo with AI-written narrative
- **Assumption validation** — flags aggressive underwriting with plain-English warnings
- **Market synthesis** — composite market score, tailwinds/headwinds, suggested rent growth

### 🏗️ Asset Classes
SFR · Small Multifamily · Multifamily · Office · Retail · Mixed-Use · Industrial · Self-Storage · STR · Ground-Up Development

---

## Quick Start

### Prerequisites

| Tool | Version |
|---|---|
| Docker + Docker Compose | 24+ |
| Python | 3.11+ (for local dev) |
| Node.js | 18+ (for frontend dev) |

### 1. Clone & configure

```bash
git clone https://github.com/your-org/propai.git
cd propai
cp .env.example .env
```

Edit `.env` and add your API keys — all free:

```bash
# Required for AI features
ANTHROPIC_API_KEY=sk-ant-...         # console.anthropic.com (free tier available)

# Optional — enriches market intelligence (all free)
CENSUS_API_KEY=...                   # api.census.gov/data/key_signup.html
FRED_API_KEY=...                     # fred.stlouisfed.org/docs/api/api_key.html
```

> **Note:** PropAI works without any API keys for underwriting and financial modeling.
> API keys unlock the AI memo generator and live market data.

### 2. Run

```bash
docker-compose up
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |

That's it. The full stack is running.

---

## API Reference

The backend is a fully documented FastAPI app. Visit `/docs` for the interactive Swagger UI.

### Underwriting

```bash
# Full underwriting (pro forma + sensitivity tables)
POST /api/underwrite

# Quick metrics only (fast screening)
POST /api/underwrite/quick

# Sample deal
GET  /api/underwrite/sample/result
```

### Market Intelligence

```bash
# Full market report (Census + FRED + HUD + Zillow)
GET /api/market/metro/{metro}?state_fips=48&county_fips=453

# By ZIP code
GET /api/market/zip/78701

# Macro snapshot only (no geo required)
GET /api/market/macro

# Current mortgage rates + 52-week history
GET /api/market/mortgage-rates
```

### AI

```bash
# Full pipeline: plain English → underwriting + memo
POST /api/ai/analyze

# Parse natural language → structured deal
POST /api/ai/parse

# Generate memo from structured deal
POST /api/ai/memo

# Demo memo (no API key needed)
GET  /api/ai/memo/demo
```

### Example: underwrite a deal

```python
import httpx

deal = {
    "name": "The Austin Arms",
    "asset_class": "multifamily",
    "purchase_price": 4_800_000,
    "units": 24,
    "market": "Austin, TX",
    "closing_costs": 0.01,
    "loan": {
        "ltv": 0.70,
        "interest_rate": 0.0675,
        "amortization_years": 30,
        "loan_type": "fixed",
        "origination_fee": 0.01
    },
    "operations": {
        "gross_scheduled_income": 576_000,
        "vacancy_rate": 0.05,
        "credit_loss_rate": 0.01,
        "other_income": 14_400,
        "property_taxes": 72_000,
        "insurance": 18_000,
        "management_fee_pct": 0.05,
        "maintenance_reserves": 36_000,
        "capex_reserves": 24_000,
        "utilities": 12_000,
        "other_expenses": 8_400,
        "rent_growth_rate": 0.03,
        "expense_growth_rate": 0.02
    },
    "exit": {
        "hold_period_years": 5,
        "exit_cap_rate": 0.055,
        "selling_costs_pct": 0.03,
        "discount_rate": 0.08
    }
}

result = httpx.post("http://localhost:8000/api/underwrite", json=deal).json()

print(f"Cap Rate:       {result['metrics']['going_in_cap_rate']:.2%}")
print(f"Levered IRR:    {result['metrics']['levered_irr']:.1%}")
print(f"Equity Multiple:{result['metrics']['equity_multiple']:.2f}x")
print(f"DSCR:           {result['metrics']['dscr_yr1']:.2f}x")
```

### Example: analyze a deal in plain English

```python
result = httpx.post("http://localhost:8000/api/ai/analyze", json={
    "text": "24-unit apartment in Austin TX at $4.8M. Rents $2k/mo. 70% LTV at 6.75%, 5yr hold."
}).json()

# result contains: parsed deal, full underwriting, and complete investment memo
print(result["memo"]["sections"]["executive_summary"])
```

---

## Architecture

```
propai/
├── backend/                    # FastAPI (Python 3.11)
│   ├── main.py                 # App entry point
│   ├── api/
│   │   ├── underwriting.py     # POST /api/underwrite
│   │   ├── market.py           # GET  /api/market/*
│   │   └── ai.py               # POST /api/ai/*
│   ├── engine/
│   │   └── financial/
│   │       ├── models.py       # Pydantic input/output models
│   │       ├── metrics.py      # Cap rate, CoC, DSCR, GRM, debt service
│   │       ├── dcf.py          # IRR (Newton-Raphson), NPV, equity multiple
│   │       ├── proforma.py     # Year-by-year pro forma + sensitivity tables
│   │       └── waterfall.py    # LP/GP equity waterfall
│   ├── data/
│   │   ├── census.py           # US Census Bureau ACS client
│   │   ├── fred.py             # FRED macroeconomic data client
│   │   ├── hud.py              # HUD Fair Market Rents client
│   │   ├── zillow.py           # Zillow Research bulk data client
│   │   └── market_service.py   # Orchestrates all data sources
│   ├── agents/
│   │   ├── memo_agent.py       # Claude-powered investment memo generator
│   │   └── deal_parser.py      # NL → structured DealInput via tool calling
│   └── templates/
│       └── memo.html           # Jinja2 investment memo template
│
├── frontend/                   # React 18 + Vite + Tailwind
│   └── src/
│       ├── components/
│       │   ├── Underwriting/   # Deal input forms
│       │   ├── Dashboard/      # Portfolio view + metrics
│       │   ├── Reports/        # Memo viewer
│       │   └── Charts/         # Financial visualizations
│       └── pages/
│
├── notebooks/                  # Jupyter demos
│   ├── 01_underwriting_demo.ipynb
│   ├── 02_market_analysis.ipynb
│   └── 03_ai_memo_generation.ipynb
│
├── docker-compose.yml
└── .env.example
```

### Design principles

**Financial engine is pure Python, zero dependencies.** The DCF/IRR solver uses Newton-Raphson iteration — no numpy, no pandas, no numpy-financial. This keeps the engine fast, portable, and auditable. Every formula has a docstring explaining the real estate context.

**AI is additive, not load-bearing.** Every feature works without an API key. Claude enhances the output; it doesn't produce the numbers. The financial engine generates the figures; the AI generates the prose.

**Graceful degradation.** Market data fetches run in parallel with `asyncio.gather`. If any single source fails (rate limit, outage, missing key), the others still populate. A partial market report is better than an error.

---

## Development

### Backend (Python)

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

### Frontend (React)

```bash
cd frontend
npm install
npm run dev
```

### Testing

```bash
cd backend
pytest tests/ -v --cov=engine
```

```
47 passed in 0.07s ✓
```

Tests cover: EGI, NOI, cap rate, GRM, DSCR, CoC, debt service (fixed/IO/IO-then-amortizing), loan balance, IRR, NPV, equity multiple, full pro forma generation, sensitivity tables, waterfall distributions, edge cases (all-cash, 1-year hold).

---

## Roadmap

| Phase | Status | What's included |
|---|---|---|
| **1 — Financial Engine** | ✅ Complete | Pro forma, DCF, IRR, sensitivity, waterfall |
| **2 — Market Data** | ✅ Complete | Census, FRED, HUD, Zillow integrations |
| **3 — AI Agents** | ✅ Complete | Memo generator, NL deal parser |
| **4 — Frontend** | 🚧 In Progress | React dashboard, deal forms, report viewer |
| **5 — Development Pro Forma** | 📋 Planned | Ground-up construction, draw schedules |
| **6 — Comp Analysis** | 📋 Planned | Rent and sales comp grids |
| **7 — Portfolio Dashboard** | 📋 Planned | Multi-deal tracking, aggregate metrics |

---

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

**Good first issues:**
- Add a new asset class to the financial engine
- Improve sensitivity table granularity
- Add a new market data source
- Write additional test cases
- Improve the investment memo HTML template

**Bigger projects:**
- React frontend (see `/frontend`)
- Jupyter notebook demos
- Additional LLM provider support (OpenAI, Gemini)
- PDF export via WeasyPrint
- PostgreSQL deal persistence layer

---

## Data Sources

All data sources used by PropAI are free:

| Source | Data | Cost |
|---|---|---|
| [US Census Bureau](https://api.census.gov) | Demographics, income, housing | Free (key required) |
| [FRED](https://fred.stlouisfed.org) | Mortgage rates, CPI, unemployment | Free (key required) |
| [HUD](https://www.huduser.gov/hudapi/public) | Fair Market Rents | Free (no key required) |
| [Zillow Research](https://www.zillow.com/research/data/) | Home values, rent trends | Free (bulk CSV download) |
| [Walk Score](https://www.walkscore.com/professional/api.php) | Walkability scores | Free tier (5k/day) |

---

## Disclaimer

PropAI is for informational and educational purposes only. Nothing in this software constitutes financial, investment, legal, or tax advice. All projections and models are estimates based on user-provided assumptions. Always conduct independent due diligence and consult qualified professionals before making any investment decision.

---

## License

MIT — see [LICENSE](LICENSE). Use it, fork it, build on it.
