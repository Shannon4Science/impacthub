"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response

from app.database import init_db
from app.routers import profile, data, milestones, citations, growth, reports, buzz, ai_summary, stats, trajectory, persona, rankings, career, annual_poem, capability, recruit, advisor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
BACKEND_STATIC = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Periodic data refresh is now in pipeline/crawl/refresh_all.py + cron;
    # see ops/advance.sh and pipeline/README.md.
    await init_db()
    yield


app = FastAPI(title="ImpactHub", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(profile.router, prefix="/api", tags=["profile"])
app.include_router(data.router, prefix="/api", tags=["data"])
app.include_router(milestones.router, prefix="/api", tags=["milestones"])
app.include_router(citations.router, prefix="/api", tags=["citations"])
app.include_router(growth.router, prefix="/api", tags=["growth"])
app.include_router(reports.router, prefix="/api", tags=["reports"])
app.include_router(buzz.router, prefix="/api", tags=["buzz"])
app.include_router(ai_summary.router, prefix="/api", tags=["ai_summary"])
app.include_router(stats.router, prefix="/api", tags=["stats"])
app.include_router(trajectory.router, prefix="/api", tags=["trajectory"])
app.include_router(persona.router, prefix="/api", tags=["persona"])
app.include_router(rankings.router, prefix="/api", tags=["rankings"])
app.include_router(career.router, prefix="/api", tags=["career"])
app.include_router(annual_poem.router, prefix="/api", tags=["annual_poem"])
app.include_router(capability.router, prefix="/api", tags=["capability"])
app.include_router(recruit.router, prefix="/api", tags=["recruit"])
app.include_router(advisor.router, prefix="/api", tags=["advisor"])

ALLOWED_IMAGE_HOSTS = {"avatars.githubusercontent.com", "github.com", "huggingface.co"}

DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "docs"

# Whitelist of doc files the page can request
DOC_FILES = {
    "system": "system_overview.md",
}


@app.get("/api/docs/{slug}")
async def get_doc(slug: str):
    """Serve a markdown doc from docs/ dir."""
    filename = DOC_FILES.get(slug)
    if not filename:
        return Response(status_code=404, content="Unknown doc slug")
    path = DOCS_DIR / filename
    if not path.exists():
        return Response(status_code=404, content="Doc not found on server")
    content = path.read_text(encoding="utf-8")
    return {"slug": slug, "filename": filename, "content": content}


@app.get("/api/proxy/image")
async def proxy_image(url: str = Query(...)):
    """Proxy external images to avoid CORS issues in html2canvas."""
    parsed = urlparse(url)
    if parsed.hostname not in ALLOWED_IMAGE_HOSTS:
        return Response(status_code=403, content="Host not allowed")
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            return Response(status_code=resp.status_code)
        content_type = resp.headers.get("content-type", "image/png")
        return Response(
            content=resp.content,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )


if BACKEND_STATIC.exists():
    app.mount("/static", StaticFiles(directory=BACKEND_STATIC), name="backend_static")

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="static")

    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        """Serve the React SPA for all non-API routes."""
        file_path = FRONTEND_DIST / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIST / "index.html")
