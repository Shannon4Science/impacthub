"""Stage 3 — crawl advisor stubs for every college whose `advisors_crawled_at` is NULL.

Usage:
    cd pipeline
    python crawl/03_advisor_stubs.py [--school-id N] [--max N]
"""

import argparse
import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline._common import setup_logging  # noqa: E402  (also adds backend/ to sys.path)

from sqlalchemy import func, select, update  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.database import async_session  # noqa: E402
from app.models import AdvisorSchool, AdvisorCollege, Advisor  # noqa: E402
from app.services import advisor_crawler_service  # noqa: E402

LOG_PATH = Path("/tmp/advisor_crawl_advisors.log")


async def update_school_count(db: AsyncSession, school_id: int):
    n = (await db.execute(
        select(func.count(Advisor.id)).where(Advisor.school_id == school_id)
    )).scalar() or 0
    await db.execute(
        update(AdvisorSchool).where(AdvisorSchool.id == school_id)
        .values(advisor_count=n, advisors_crawled_at=datetime.utcnow())
    )


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--school-id", type=int, help="Limit to one school")
    parser.add_argument("--max", type=int, default=0, help="Stop after N colleges (0 = no limit)")
    args = parser.parse_args()

    log = setup_logging(LOG_PATH)

    async with async_session() as db:
        stmt = select(AdvisorCollege).where(
            AdvisorCollege.homepage_url != "",
            AdvisorCollege.advisors_crawled_at.is_(None),
        ).order_by(AdvisorCollege.school_id, AdvisorCollege.id)
        if args.school_id:
            stmt = stmt.where(AdvisorCollege.school_id == args.school_id)
        if args.max:
            stmt = stmt.limit(args.max)
        colleges = (await db.execute(stmt)).scalars().all()

    log.info("Advisor crawl: %d colleges queued (cap=%s)", len(colleges), args.max or "none")
    if not colleges:
        log.info("Nothing to do.")
        return

    successes = 0
    skipped = 0
    failures = 0
    t0 = time.time()
    last_school_id = None

    for i, c in enumerate(colleges, 1):
        elapsed = time.time() - t0
        log.info(
            "[%4d/%4d] college=%s (school=%d) | elapsed %.0fs",
            i, len(colleges), c.name, c.school_id, elapsed,
        )
        try:
            async with async_session() as db:
                college = await db.get(AdvisorCollege, c.id)
                result = await advisor_crawler_service.crawl_college_advisors(db, college)
                # Mark crawled regardless of result so we don't infinite-retry.
                college.advisors_crawled_at = datetime.utcnow()
                # If school changed since last iteration, update prior school's denorm count
                if last_school_id is not None and last_school_id != c.school_id:
                    await update_school_count(db, last_school_id)
                last_school_id = c.school_id
                await db.commit()
                added = result.get("advisors_added", 0)
                if added > 0:
                    successes += 1
                    log.info("  → +%d advisors", added)
                else:
                    skipped += 1
                    log.info("  → 0 advisors (page may not be a faculty list)")
        except Exception as e:
            failures += 1
            log.exception("  → CRASHED: %s", e)

    # Final school count update
    if last_school_id is not None:
        async with async_session() as db:
            await update_school_count(db, last_school_id)
            await db.commit()

    elapsed = time.time() - t0
    log.info(
        "DONE in %.0fs. ok=%d empty=%d crashed=%d",
        elapsed, successes, skipped, failures,
    )


if __name__ == "__main__":
    asyncio.run(main())
