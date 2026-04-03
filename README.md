<p align="center">
  <img src="frontend/public/logo.svg" width="120" alt="ImpactHub Logo" />
</p>

<h1 align="center">ImpactHub</h1>

<p align="center">
  <b>Unified Research Impact Dashboard</b><br/>
  Aggregate your academic papers, GitHub repos, and Hugging Face models into one portfolio.
</p>

<p align="center">
  <b>English</b> | <a href="README.zh.md">中文</a>
</p>

<p align="center">
  <a href="#features">Features</a> &bull;
  <a href="#quick-start">Quick Start</a> &bull;
  <a href="#configuration">Configuration</a> &bull;
  <a href="#architecture">Architecture</a>
</p>

---

## Features

### Cross-Platform Profile

One profile that unifies your presence across **Semantic Scholar**, **GitHub**, and **Hugging Face**. Enter your Scholar ID — the system auto-discovers your linked GitHub and HF accounts.

### Citation Intelligence

- H-index auto-computation and CCF-A/B/C venue classification
- Identifies **top scholars** (h-index ≥ 50) and **notable scholars** (h-index ≥ 25) who cite your work
- LLM-powered honor tag enrichment — detects IEEE Fellow, ACM Fellow, 院士 among your citers
- Per-paper citation drill-down with context snippets

### Growth Tracking

- Daily metric snapshots: citations, h-index, stars, forks, downloads, likes
- Interactive trend charts with 30/60/90/365-day windows
- Milestone system: automatic achievements when you hit thresholds (100 citations, 1K stars, etc.)

### Web Buzz Monitoring

- Perplexity-powered web search to gauge your research visibility
- Heat level classification (hot / medium / cold) with source links

### AI-Powered Summary

- LLM-generated researcher bio capturing your research identity
- Auto-generated research tags from your publication topics

### Grant Application Tools

- **Research Basis Generator** for NSFC, Changjiang, Wanren, and other Chinese grant types
- Tone-adaptive formatting: "potential + feasibility" for youth grants vs. "originality + leadership" for senior grants
- Paper selection UI with evidence preview (citation analysis + notable scholars + linked repos)

### Smart Export

- Paper list export: Markdown, BibTeX, JSON
- Filter by year, CCF rank, citation count, first-author
- Comprehensive CV-style summary JSON

### Auto Refresh

- Background scheduler refreshes all data every 6 hours
- Manual refresh on demand via API

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- An OpenAI-compatible API key (for AI summary & buzz features)

### 1. Backend

```bash
cd backend
pip install -r requirements.txt

# Create .env from template
cp ../.env.example .env
# Edit .env and fill in your API key

python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

### 2. Frontend

```bash
cd frontend
npm install

# Development
npm run dev

# Production build (served by backend)
npm run build
```

### 3. One-Command Serve (optional)

```bash
# Serves frontend dist/ + proxies /api to backend
python serve.py 19487
```

Open `http://localhost:19487` and enter your Semantic Scholar ID to get started.

---

## Configuration

Copy `.env.example` to `backend/.env`:

| Variable | Description | Required |
|----------|-------------|----------|
| `LLM_API_BASE` | OpenAI-compatible API endpoint | Yes |
| `LLM_API_KEY` | API key for the LLM provider | Yes |
| `LLM_BUZZ_MODEL` | Model for buzz & summary generation (default: `gpt-5`) | No |
| `OUTBOUND_PROXY` | HTTP proxy for outbound API calls | No |
| `GITHUB_TOKEN` | GitHub PAT for higher rate limits | No |

---

## Architecture

```
impacthub/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry + static file serving
│   │   ├── config.py            # Environment & constants
│   │   ├── models.py            # SQLAlchemy ORM
│   │   ├── schemas.py           # Pydantic schemas
│   │   ├── routers/
│   │   │   ├── profile.py       # Profile CRUD & account linking
│   │   │   ├── stats.py         # Aggregated statistics
│   │   │   ├── citations.py     # Citation analysis & scholar classification
│   │   │   ├── growth.py        # Growth snapshots & trends
│   │   │   ├── milestones.py    # Achievement tracking
│   │   │   ├── buzz.py          # Web presence monitoring
│   │   │   ├── ai_summary.py    # LLM-generated bios & tags
│   │   │   ├── reports.py       # Grant research basis generator
│   │   │   └── data.py          # Export endpoints
│   │   ├── services/            # Business logic per domain
│   │   └── tasks/
│   │       └── scheduler.py     # APScheduler (6h refresh cycle)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/               # Setup, Profile, Milestone, Users
│   │   ├── components/          # Charts, cards, modals, exporters
│   │   └── lib/                 # API client, utils, venue data
│   └── package.json
└── serve.py                     # Simple dev proxy server
```

**Tech Stack**: FastAPI + SQLAlchemy + aiosqlite | React 19 + Tailwind CSS 4 + Recharts | Semantic Scholar + GitHub + Hugging Face APIs

---

## License

MIT
