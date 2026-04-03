# ImpactHub

A cross-platform research impact dashboard that aggregates data from Semantic Scholar, GitHub, and Hugging Face into a unified personal profile with milestone tracking.

## Quick Start

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

### Frontend (development)

```bash
cd frontend
npm install
npm run dev -- --port 5173
```

Then open http://localhost:5173.

### Frontend (production build)

```bash
cd frontend
npm run build
# Serve the dist/ folder with any static file server
```

## Architecture

- **Backend**: Python FastAPI + SQLite + APScheduler
- **Frontend**: React + TypeScript + Tailwind CSS + Recharts
- **Data Sources**: Semantic Scholar API, GitHub API, Hugging Face API

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/profiles` | List all profiles |
| POST | `/api/profile` | Create or update profile |
| GET | `/api/profile/{id}` | Get full profile with papers/repos/HF items |
| GET | `/api/profile/{id}/stats` | Aggregated statistics |
| GET | `/api/profile/{id}/timeline` | Cross-platform timeline |
| GET | `/api/milestones/{id}` | Milestone achievements |
| POST | `/api/refresh/{id}` | Trigger manual data refresh |

## Configuration

Copy `.env.example` to `backend/.env` and fill in your values:

| Variable | Description | Required |
|----------|-------------|----------|
| `LLM_API_BASE` | OpenAI-compatible endpoint for AI summaries | Yes |
| `LLM_API_KEY` | API key for the LLM provider | Yes |
| `LLM_BUZZ_MODEL` | Model name for buzz generation (default: `gpt-4o`) | No |
| `OUTBOUND_PROXY` | HTTP proxy for outbound API calls (restricted networks) | No |
| `GITHUB_TOKEN` | GitHub personal access token for higher rate limits | No |

The scheduler automatically refreshes data every 6 hours.
