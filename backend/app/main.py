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
from app.routers import profile, data, milestones, citations, growth, reports, buzz, ai_summary, stats
from app.tasks.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_scheduler()
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

ALLOWED_IMAGE_HOSTS = {"avatars.githubusercontent.com", "github.com", "huggingface.co"}


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


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="static")

    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        """Serve the React SPA for all non-API routes."""
        file_path = FRONTEND_DIST / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIST / "index.html")
