"""Site-wide statistics and page view tracking."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, Paper, GithubRepo, HFItem, PageView

router = APIRouter()


@router.post("/track")
async def track_visit(request: Request, db: AsyncSession = Depends(get_db)):
    """Record a page view."""
    body = await request.json()
    pv = PageView(
        path=body.get("path", "/"),
        ip=request.headers.get("x-forwarded-for", request.client.host if request.client else ""),
        user_agent=request.headers.get("user-agent", "")[:500],
    )
    db.add(pv)
    await db.commit()
    return {"ok": True}


@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Return site-wide statistics for the homepage."""
    total_profiles = (await db.execute(select(func.count(User.id)))).scalar() or 0
    total_papers = (await db.execute(select(func.count(Paper.id)))).scalar() or 0
    total_citations = (await db.execute(select(func.coalesce(func.sum(Paper.citation_count), 0)))).scalar() or 0
    total_repos = (await db.execute(select(func.count(GithubRepo.id)))).scalar() or 0
    total_stars = (await db.execute(select(func.coalesce(func.sum(GithubRepo.stars), 0)))).scalar() or 0
    total_hf_items = (await db.execute(select(func.count(HFItem.id)))).scalar() or 0

    # Page views
    total_views = (await db.execute(select(func.count(PageView.id)))).scalar() or 0
    # Unique visitors (by IP) in last 7 days
    week_ago = datetime.utcnow() - timedelta(days=7)
    weekly_visitors = (await db.execute(
        select(func.count(distinct(PageView.ip))).where(PageView.created_at >= week_ago)
    )).scalar() or 0

    return {
        "total_profiles": total_profiles,
        "total_papers": total_papers,
        "total_citations": total_citations,
        "total_repos": total_repos,
        "total_stars": total_stars,
        "total_hf_items": total_hf_items,
        "total_views": total_views,
        "weekly_visitors": weekly_visitors,
    }
