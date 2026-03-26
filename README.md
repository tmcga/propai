<div align="center">

# PropAI

### The open-source deal intelligence platform for real estate investment

**Screen deals in seconds · Underwrite with AI · Track your pipeline · Generate institutional memos**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React 18](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![Claude](https://img.shields.io/badge/Powered%20by-Claude-orange)](https://anthropic.com)
[![Tests](https://img.shields.io/badge/Tests-95%20passing-brightgreen)](#testing)
[![CI](https://github.com/tmcga/propai/actions/workflows/ci.yml/badge.svg)](https://github.com/tmcga/propai/actions)

</div>

---

PropAI is a self-hostable platform that replaces spreadsheets and $5K/year SaaS tools with an AI-native workflow for real estate investment analysis.

Describe a deal in plain English. Get back a full pro forma, IRR analysis, market intelligence from 4 free data sources, and an institutional-quality investment memo — in under 60 seconds.

```
"24-unit apartment in Austin TX at $4.8M. Rents average $2,000/mo.
 70% LTV at 6.75%, 5-year hold, exit at a 5.5 cap."
```

**What you get back:** 5-year pro forma · IRR, NPV, equity multiple · Sensitivity tables · Market intelligence · AI investment memo · Deal screening verdict · Due diligence red flags

---

## Features

### Financial Engine
Pro forma modeling, full returns suite (IRR, NPV, cap rate, cash-on-cash, DSCR, GRM, equity multiple), 5x5 sensitivity tables, LP/GP equity waterfall with promote tiers, and support for fixed, IO, and IO-then-amortizing loan structures. Pure Python — no numpy, no pandas.

### Deal Intelligence
Persistent deals with version history, document ingestion (upload OMs, T-12s, rent rolls — AI extracts the numbers), side-by-side deal comparison, and portfolio management. All backed by PostgreSQL.

### Market Intelligence
Live data from Census Bureau, FRED, HUD, and Zillow — all free APIs. Composite market scoring, tailwinds/headwinds analysis, and suggested rent growth rates. Fetched in parallel with graceful degradation.

### AI Agents
6 Claude-powered agents: natural language deal parser, investment memo generator, deal screener (go/no-go), due diligence analyst, document parser, and LP communications writer. All with retry logic and error handling.

### Asset Classes
SFR · Small Multifamily · Multifamily · Office · Retail · Mixed-Use · Industrial · Self-Storage · STR · Ground-Up Development

---

## Quick Start

```bash
git clone https://github.com/tmcga/propai.git
cd propai
cp .env.example .env
# Add your ANTHROPIC_API_KEY (free at console.anthropic.com)
docker-compose up
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| API Docs | http://localhost:8000/docs |

> Works without API keys for underwriting and financial modeling. Keys unlock AI agents and live market data.

For local development without Docker:

```bash
# Backend
cd backend && python -m venv venv && source venv/bin/activate
pip install -r requirements.txt && uvicorn main:app --reload

# Frontend
cd frontend && npm install && npm run dev
```

---

## API

Full Swagger docs at `/docs` when running.

```bash
# Stateless (works without database)
POST /api/underwrite              # Full pro forma + sensitivity
POST /api/ai/analyze              # Plain English → underwriting + memo
GET  /api/market/metro/{metro}    # Market report (Census + FRED + HUD + Zillow)

# Deal persistence (requires PostgreSQL)
POST /api/deals                   # Create deal (structured, NL, or quick)
POST /api/deals/{id}/underwrite   # Run and save results
POST /api/deals/{id}/documents    # Upload documents
POST /api/deals/compare           # Side-by-side comparison
```

---

## Roadmap

| Phase | Status |
|---|---|
| Financial Engine | Done |
| Market Data Integrations | Done |
| AI Agents (6 agents) | Done |
| Deal Persistence Layer | Done |
| Frontend | In Progress |
| Development Pro Forma | Planned |
| Comp Analysis | Planned |
| Portfolio Dashboard | Planned |

See [open issues](https://github.com/tmcga/propai/issues) for what needs work.

---

## For Developers

See [CLAUDE.md](CLAUDE.md) for the full technical guide — architecture, design decisions, how modules connect, and where to start contributing.

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

**Quick orientation:**
- `backend/engine/financial/` — the math (pure Python, zero deps, well-tested)
- `backend/agents/` — AI agents (Claude-powered, each self-contained)
- `backend/api/` — FastAPI routes (stateless + persistent)
- `backend/db/` — PostgreSQL persistence (SQLAlchemy 2.0 async)
- `frontend/src/` — React 18 + Vite + Tailwind
- `prompts/` — 9 agent system prompts covering the full investment lifecycle

**Testing:** `cd backend && pytest tests/ -v` — 95 tests.

---

## Data Sources

All free: [Census Bureau](https://api.census.gov) · [FRED](https://fred.stlouisfed.org) · [HUD](https://www.huduser.gov/hudapi/public) · [Zillow Research](https://www.zillow.com/research/data/)

---

## License

[MIT](LICENSE) — use it, fork it, build on it.

**Disclaimer:** PropAI is for informational and educational purposes. It is not financial, investment, legal, or tax advice.
