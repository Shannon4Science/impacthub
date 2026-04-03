"""Milestone detection: checks current metrics against thresholds and records new milestones."""

import logging
from datetime import datetime

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import MILESTONE_THRESHOLDS
from app.models import Milestone, Paper, GithubRepo, HFItem, User

logger = logging.getLogger(__name__)


async def _get_existing_milestones(db: AsyncSession, user_id: int) -> set[tuple[str, str, int]]:
    rows = (await db.execute(select(Milestone).where(Milestone.user_id == user_id))).scalars().all()
    return {(m.metric_type, m.metric_key, m.threshold) for m in rows}


_pending_notifications: list[tuple] = []


async def _record(db: AsyncSession, user_id: int, metric_type: str, key: str, threshold: int, value: int):
    ms = Milestone(
        user_id=user_id,
        metric_type=metric_type,
        metric_key=key,
        threshold=threshold,
        achieved_value=value,
        achieved_at=datetime.utcnow(),
    )
    db.add(ms)
    _pending_notifications.append((user_id, ms))
    logger.info("New milestone: user=%d %s/%s crossed %d (value=%d)", user_id, metric_type, key, threshold, value)


async def check_milestones(db: AsyncSession, user: User) -> list[Milestone]:
    """Detect newly crossed milestones for a user. Returns list of new milestones."""
    existing = await _get_existing_milestones(db, user.id)
    new_milestones: list[Milestone] = []

    total_citations = 0
    papers = (await db.execute(select(Paper).where(Paper.user_id == user.id))).scalars().all()
    for p in papers:
        total_citations += p.citation_count
        for t in MILESTONE_THRESHOLDS.get("citations", []):
            if p.citation_count >= t and ("citations", p.title, t) not in existing:
                await _record(db, user.id, "citations", p.title, t, p.citation_count)
                existing.add(("citations", p.title, t))

    for t in MILESTONE_THRESHOLDS.get("citations", []):
        if total_citations >= t and ("citations", "__total__", t) not in existing:
            await _record(db, user.id, "citations", "__total__", t, total_citations)
            existing.add(("citations", "__total__", t))

    total_stars = 0
    repos = (await db.execute(select(GithubRepo).where(GithubRepo.user_id == user.id))).scalars().all()
    for r in repos:
        total_stars += r.stars
        for t in MILESTONE_THRESHOLDS.get("stars", []):
            if r.stars >= t and ("stars", r.repo_name, t) not in existing:
                await _record(db, user.id, "stars", r.repo_name, t, r.stars)
                existing.add(("stars", r.repo_name, t))

    for t in MILESTONE_THRESHOLDS.get("stars", []):
        if total_stars >= t and ("stars", "__total__", t) not in existing:
            await _record(db, user.id, "stars", "__total__", t, total_stars)
            existing.add(("stars", "__total__", t))

    total_downloads = 0
    hf_items = (await db.execute(select(HFItem).where(HFItem.user_id == user.id))).scalars().all()
    for h in hf_items:
        total_downloads += h.downloads
        for t in MILESTONE_THRESHOLDS.get("downloads", []):
            if h.downloads >= t and ("downloads", h.item_id, t) not in existing:
                await _record(db, user.id, "downloads", h.item_id, t, h.downloads)
                existing.add(("downloads", h.item_id, t))
        for t in MILESTONE_THRESHOLDS.get("hf_likes", []):
            if h.likes >= t and ("hf_likes", h.item_id, t) not in existing:
                await _record(db, user.id, "hf_likes", h.item_id, t, h.likes)
                existing.add(("hf_likes", h.item_id, t))

    for t in MILESTONE_THRESHOLDS.get("downloads", []):
        if total_downloads >= t and ("downloads", "__total__", t) not in existing:
            await _record(db, user.id, "downloads", "__total__", t, total_downloads)
            existing.add(("downloads", "__total__", t))

    await db.commit()

    # Send notifications for new milestones
    if _pending_notifications:
        from app.services.notification_service import send_milestone_notification
        for uid, ms in _pending_notifications:
            try:
                await send_milestone_notification(user, ms)
            except Exception:
                logger.exception("Failed to send notification for milestone")
        _pending_notifications.clear()

    return new_milestones
