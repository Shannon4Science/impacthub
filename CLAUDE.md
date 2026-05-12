# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is ImpactHub

A unified research impact dashboard that aggregates academic papers (Semantic Scholar), GitHub repos, and Hugging Face models into one portfolio. Users enter a Semantic Scholar ID and the system auto-discovers linked GitHub/HF accounts, computes citation metrics, tracks growth over time, and provides AI-powered summaries and grant application tools.

## Development Commands

### Backend (Python FastAPI)
```bash
cd backend
pip install -r requirements.txt
cp ../.env.example .env   # first time only; fill in API keys
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

### Frontend (React + Vite)
```bash
cd frontend
npm install
npm run dev     # dev server with HMR, proxies /api → localhost:8001
npm run build   # production build → frontend/dist/
npm run lint    # ESLint
```

### Combined proxy server
```bash
python serve.py 19487   # serves frontend dist/ + proxies /api to backend
```

## Architecture

**Backend** (`backend/app/`): Async-first FastAPI with SQLAlchemy + aiosqlite (SQLite WAL mode). Three-layer structure:
- **Routers** (`routers/`): Thin endpoint handlers — profile, citations, growth, milestones, buzz, ai_summary, reports, data, stats
- **Services** (`services/`): All business logic lives here. Key services: `scholar_service` (Semantic Scholar API with rate-limit retry), `github_service`, `hf_service`, `citation_service`, `honor_service` (LLM-based honor tag detection), `buzz_service` (Perplexity API), `research_basis_service` (grant report generation)
- **Models** (`models.py`): 13 SQLAlchemy ORM tables. Core entity is `User`; papers/repos/HF items link via `user_id` FK with cascade deletes

**Frontend** (`frontend/src/`): React 18 + TypeScript + Tailwind CSS 4 + Recharts. Four pages: SetupPage (onboarding), ProfilePage (main dashboard), MilestonePage, UsersPage. API client in `lib/api.ts`.

**Scheduler**: cron triggers `pipeline/crawl/refresh_all.py` every 6h to refresh User portfolios (papers / DBLP / CCF / GitHub / HF / snapshots). The 10-min watchdog at `pipeline/ops/advance.sh` relaunches stalled crawl/analyze jobs. See `pipeline/README.md`.

**Database**: SQLite at `backend/data/impacthub.db`. Created automatically on first run. Migrations handled inline in `database.py`.

## Key Patterns

- All backend I/O is async (`AsyncSession`, `httpx.AsyncClient`). Do not introduce synchronous DB calls or blocking HTTP requests.
- External API calls (Semantic Scholar, GitHub, HF, Perplexity) go through `httpx.AsyncClient` with optional `OUTBOUND_PROXY` for restricted networks.
- Long-running operations (citation analysis, honor enrichment) use FastAPI `BackgroundTasks`, not inline request handling.
- Pydantic v2 schemas in `schemas.py` for all request/response types.
- Frontend dev server proxies `/api` to backend (configured in `vite.config.ts`).
- CORS is open (`allow_origins=["*"]`) — this is a self-hosted research tool.

## Configuration

Environment variables live in `backend/.env` (see `.env.example`):
- `LLM_API_BASE` / `LLM_API_KEY`: OpenAI-compatible endpoint for AI summary, buzz, honor detection, and grant report generation
- `LLM_BUZZ_MODEL`: Model name for LLM features (default: `gpt-5`)
- `OUTBOUND_PROXY`: HTTP proxy for all external API calls
- `GITHUB_TOKEN`: GitHub PAT for higher rate limits
