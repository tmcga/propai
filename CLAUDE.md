# CLAUDE.md

Technical guide for contributors working on PropAI.

## Project Overview

PropAI is a real estate investment intelligence platform. FastAPI backend (Python 3.11+), React 18 frontend (TypeScript), PostgreSQL 16, Redis 7. All orchestrated via Docker Compose.

## Commands

```bash
# Backend
cd backend
pip install -r requirements.txt          # Install deps
uvicorn main:app --reload                # Run dev server
pytest tests/ -v                         # Run all 95 tests
ruff check . && ruff format --check .    # Lint + format check

# Frontend
cd frontend
npm install                              # Install deps
npm run dev                              # Run dev server
npm run typecheck                        # TypeScript check
npm run lint                             # Biome lint
npm run build                            # Production build

# Full stack
docker-compose up                        # Start everything
```

## Architecture

### Backend modules

**`engine/financial/`** — Pure Python financial engine. Zero external dependencies. This is the core of PropAI.
- `models.py` — Pydantic models: `DealInput`, `UnderwritingResult`, `ReturnMetrics`, `SensitivityTable`, `WaterfallResult`
- `metrics.py` — Cap rate, CoC, DSCR, GRM, debt service, break-even occupancy
- `dcf.py` — IRR (Newton-Raphson solver), NPV, equity multiple. `Callable` type annotations for sensitivity functions.
- `proforma.py` — `ProFormaEngine` generates year-by-year pro forma + sensitivity tables
- `waterfall.py` — `WaterfallEngine` computes LP/GP distributions through promote tiers

**`agents/`** — Claude-powered AI agents. Each is self-contained with its own system prompt, Pydantic output schema, and error handling.
- All agents use `AsyncAnthropic` client with `tenacity` retry (3 attempts, exponential backoff)
- All agents handle `json.JSONDecodeError` gracefully with fallback responses
- Model names are currently hardcoded (e.g., `claude-sonnet-4-6`). These should eventually be env-configurable.

**`data/`** — External market data clients. All use `httpx` async. All degrade gracefully if keys are missing or APIs are down.
- `market_service.py` orchestrates all sources in parallel via `asyncio.gather`
- Zillow data is fetched as bulk CSV and cached locally

**`db/`** — PostgreSQL persistence layer (SQLAlchemy 2.0 async).
- Uses `Uuid` and `JSON` types (cross-platform: works on both PostgreSQL and SQLite for tests)
- Lazy initialization — app starts without a database; stateless endpoints work; deal endpoints return 503
- 5 tables: `deals`, `deal_versions` (full DealInput snapshots as JSON), `documents`, `analysis_results`, `portfolios`

**`api/`** — FastAPI routers.
- Stateless endpoints (`underwriting.py`, `ai.py`, `market.py`, `analysis.py`) — no database needed
- Persistent endpoints (`deals.py`) — require PostgreSQL. Wraps the same engines with persistence.
- `deals.py` uses discriminated union for deal creation (3 modes: structured, NL, quick)

**`services/storage.py`** — Document file storage. `LocalStorage` for dev, `StorageBackend` protocol for S3. Path traversal protection via `_safe_path()`. Singleton instance.

### Frontend

React 18 + Vite + Tailwind + React Query. TypeScript throughout. Biome for linting/formatting.

- `src/pages/` — 5 page components (Dashboard, Underwrite, Results, Market, Memo)
- `src/components/` — Layout, Charts, Reports, Dashboard, Underwriting
- `src/lib/api.ts` — Axios client with all API methods
- `src/lib/utils.ts` — Formatting helpers (currency, percent, number)

### Key files to know

| File | What it does | When you'll touch it |
|---|---|---|
| `backend/engine/financial/models.py` | All Pydantic models | Adding fields to deals |
| `backend/api/deals.py` | Deal CRUD (largest file, ~900 lines) | Adding deal features |
| `backend/db/models.py` | SQLAlchemy models | Schema changes |
| `backend/main.py` | App entry, auth, rate limiting, CORS | Auth or middleware changes |
| `backend/config.py` | Centralized settings (Pydantic Settings) | New env vars |
| `frontend/src/lib/api.ts` | All API client methods | Adding API calls |

## Design Decisions

**Full snapshots for deal versions.** Each `deal_versions` row stores the complete `DealInput` as JSON (~2KB). Not diffs. Any version can be fed directly to `ProFormaEngine` with no reconstruction. Trade-off: slightly more storage for much simpler code.

**Single `analysis_results` table.** All result types (underwriting, memo, screen verdict, DD report) go in one table with a `result_type` discriminator and `result_data` JSON column. Avoids 6 separate tables that all have the same shape.

**Lazy DB initialization.** The database engine is created in the app lifespan, not at module import time. This means `from main import app` works even without asyncpg installed (needed for tests). If DB is unavailable, stateless endpoints work; deal endpoints return 503.

**AI is additive.** The financial engine works with zero API keys. Claude enhances output but doesn't produce the numbers. This means the core product is always available.

## Testing

Tests use `pytest` + `pytest-asyncio`. DB integration tests use SQLite in-memory (no PostgreSQL needed).

```
tests/
├── test_financial_engine.py  # 47 tests — metrics, DCF, pro forma, waterfall
├── test_api.py               # 10 tests — HTTP endpoints via TestClient
├── test_agents.py            # 7 tests — mocked AI responses
├── test_deals.py             # 21 tests — DB models + helpers (SQLite)
├── test_storage.py           # 10 tests — file storage + path traversal
└── conftest.py               # Shared sample_deal fixture
```

## Code Style

- **Backend:** Ruff for linting and formatting. Mypy strict on `engine/` only.
- **Frontend:** Biome for linting and formatting (replaced ESLint). TypeScript strict.
- Imports: absolute (`from engine.financial.models import DealInput`), not relative.
- No `print()` in production code — use `logging.getLogger(__name__)`.

## Known Issues

See [GitHub Issues](https://github.com/tmcga/propai/issues). Key ones:
- #3 — API key auth compare_digest bug
- #4 — Waterfall LP IRR double-counts equity percentage
- #14 — No Alembic migration system yet (schema managed via `create_all`)

## Adding a New Agent

1. Create `backend/agents/your_agent.py`
2. Define output dataclass(es)
3. Use `AsyncAnthropic` client with `@retry` decorator from tenacity
4. Handle `json.JSONDecodeError` with a graceful fallback
5. Add an API endpoint in `backend/api/analysis.py` or `backend/api/deals.py`
6. Add tests with mocked AI responses in `tests/test_agents.py`

Pattern to follow: `backend/agents/deal_screener.py` (2-pass: math + AI)

## Adding a New API Endpoint

1. Add route to the appropriate router in `backend/api/`
2. If it needs persistence, add it to `deals.py` and use `Depends(get_db)`
3. If it's stateless, add it to the relevant router
4. Use typed Pydantic models for request/response (not `dict`)
5. Add tests in `tests/test_api.py`

## Prompts Directory

`prompts/` contains 9 Claude system prompts for different RE roles. Most are NOT wired into the API — they're standalone references. Wiring one up is a good contribution:

- `acquisition_analyst.md` — deal screening
- `underwriting_analyst.md` — deep financial modeling
- `market_analyst.md` — comp analysis
- `capital_stack_advisor.md` — debt structuring (213 lines of domain knowledge)
- `asset_manager.md` — monthly NOI tracking, capex decisions
- `disposition_analyst.md` — exit strategy, broker selection
- `development_analyst.md` — ground-up pro formas
- `due_diligence_analyst.md` — red flag detection
- `lp_relations.md` — investor communications
