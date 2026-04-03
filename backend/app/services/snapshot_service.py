"""Snapshot service: records daily metric snapshots for growth tracking."""

import logging
from datetime import date, timedelta

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DataSnapshot, Paper, GithubRepo, HFItem, User

logger = logging.getLogger(__name__)


async def record_daily_snapshot(db: AsyncSession, user: User):
    """Record current metric values as today's snapshot. Skips if already recorded."""
    today = date.today()

    existing = (
        await db.execute(
            select(DataSnapshot)
            .where(DataSnapshot.user_id == user.id, DataSnapshot.snapshot_date == today)
            .limit(1)
        )
    ).scalars().first()

    if existing:
        return

    papers = (await db.execute(select(Paper).where(Paper.user_id == user.id))).scalars().all()
    repos = (await db.execute(select(GithubRepo).where(GithubRepo.user_id == user.id))).scalars().all()
    hf_items = (await db.execute(select(HFItem).where(HFItem.user_id == user.id))).scalars().all()

    total_citations = sum(p.citation_count for p in papers)
    total_stars = sum(r.stars for r in repos)
    total_forks = sum(r.forks for r in repos)
    total_downloads = sum(h.downloads for h in hf_items)
    total_hf_likes = sum(h.likes for h in hf_items)
    paper_count = len(papers)
    h_index = _calc_h_index([p.citation_count for p in papers])

    ccf_a_count = sum(1 for p in papers if p.ccf_rank == "A")
    ccf_b_count = sum(1 for p in papers if p.ccf_rank == "B")

    metrics = {
        "total_citations": total_citations,
        "total_stars": total_stars,
        "total_forks": total_forks,
        "total_downloads": total_downloads,
        "total_hf_likes": total_hf_likes,
        "paper_count": paper_count,
        "h_index": h_index,
        "ccf_a_count": ccf_a_count,
        "ccf_b_count": ccf_b_count,
    }

    for key, value in metrics.items():
        db.add(DataSnapshot(
            user_id=user.id,
            metric_type=key,
            metric_key="__total__",
            value=float(value),
            snapshot_date=today,
        ))

    await db.commit()
    logger.info("Recorded daily snapshot for user %d: %s", user.id, metrics)


async def get_growth_data(db: AsyncSession, user_id: int, days: int = 30) -> dict:
    """Get growth data for the past N days."""
    since = date.today() - timedelta(days=days)

    rows = (
        await db.execute(
            select(DataSnapshot)
            .where(
                DataSnapshot.user_id == user_id,
                DataSnapshot.metric_key == "__total__",
                DataSnapshot.snapshot_date >= since,
            )
            .order_by(DataSnapshot.snapshot_date)
        )
    ).scalars().all()

    series: dict[str, list[dict]] = {}
    for r in rows:
        if r.metric_type not in series:
            series[r.metric_type] = []
        series[r.metric_type].append({
            "date": r.snapshot_date.isoformat(),
            "value": r.value,
        })

    # Calculate daily deltas (today vs yesterday)
    yesterday = date.today() - timedelta(days=1)
    today_rows = [r for r in rows if r.snapshot_date == date.today()]
    yesterday_rows = [r for r in rows if r.snapshot_date == yesterday]

    today_map = {r.metric_type: r.value for r in today_rows}
    yesterday_map = {r.metric_type: r.value for r in yesterday_rows}

    daily_delta = {}
    for k in today_map:
        if k in yesterday_map:
            daily_delta[k] = today_map[k] - yesterday_map[k]

    return {"series": series, "daily_delta": daily_delta}


def _calc_h_index(citations: list[int]) -> int:
    sorted_c = sorted(citations, reverse=True)
    h = 0
    for i, c in enumerate(sorted_c):
        if c >= i + 1:
            h = i + 1
        else:
            break
    return h
