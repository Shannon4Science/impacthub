"""APScheduler background task that periodically refreshes data for all users."""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.config import REFRESH_INTERVAL_HOURS
from app.database import async_session
from app.models import User
from app.services import scholar_service, github_service, hf_service, milestone_service
from app.services import dblp_service, snapshot_service, ccf_recompute_service

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def refresh_all_users():
    """Pull fresh data from all sources for every registered user."""
    logger.info("Scheduled refresh starting...")
    async with async_session() as db:
        users = (await db.execute(select(User))).scalars().all()
        for user in users:
            try:
                await scholar_service.fetch_papers_for_user(db, user)
                await dblp_service.fetch_dblp_papers_for_user(db, user)
                await ccf_recompute_service.recompute_ccf_for_user(db, user)
                await github_service.fetch_repos_for_user(db, user)
                await hf_service.fetch_hf_items_for_user(db, user)
                await milestone_service.check_milestones(db, user)
                await snapshot_service.record_daily_snapshot(db, user)
                await db.commit()
                logger.info("Refreshed user %d (%s)", user.id, user.name)
            except Exception:
                logger.exception("Error refreshing user %d", user.id)
    logger.info("Scheduled refresh complete.")


def start_scheduler():
    scheduler.add_job(
        refresh_all_users,
        "interval",
        hours=REFRESH_INTERVAL_HOURS,
        id="refresh_all",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started: refresh every %dh", REFRESH_INTERVAL_HOURS)
