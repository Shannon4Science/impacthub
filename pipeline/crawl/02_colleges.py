"""Stage 2 — crawl the college list for every school whose `colleges_crawled_at` is NULL.

Usage:
    cd pipeline
    python crawl/02_colleges.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline._common import setup_logging  # noqa: E402  (also adds backend/ to sys.path)

from sqlalchemy import select  # noqa: E402

from app.database import async_session  # noqa: E402
from app.models import AdvisorSchool  # noqa: E402
from app.services import advisor_crawler_service  # noqa: E402

LOG_PATH = Path("/tmp/advisor_crawl_colleges.log")


async def main():
    log = setup_logging(LOG_PATH)

    # Load all schools that haven't been crawled yet
    async with async_session() as db:
        schools = (await db.execute(
            select(AdvisorSchool).where(
                AdvisorSchool.homepage_url != "",
                AdvisorSchool.colleges_crawled_at.is_(None),
            ).order_by(AdvisorSchool.is_985.desc(), AdvisorSchool.is_211.desc())
        )).scalars().all()

    total = len(schools)
    log.info("Starting batch crawl: %d schools to process", total)
    if not total:
        log.info("Nothing to do. All schools already crawled.")
        return

    successes = 0
    failures: list[tuple[str, list[str]]] = []
    skipped: list[str] = []
    t0 = time.time()

    for i, s in enumerate(schools, 1):
        elapsed = time.time() - t0
        log.info(
            "[%3d/%3d] %-20s (%s) | elapsed %.0fs",
            i, total, s.name, s.homepage_url, elapsed,
        )
        try:
            async with async_session() as db:
                school = await db.get(AdvisorSchool, s.id)
                result = await advisor_crawler_service.crawl_school_colleges(
                    db, school, fetch_advisors=False,
                )
                await db.commit()
                if result["colleges_added"] == 0:
                    failures.append((s.name, result.get("errors", [])))
                    log.warning("  → 0 colleges added: %s", result.get("errors"))
                else:
                    successes += 1
                    log.info(
                        "  → +%d colleges (%s errors)",
                        result["colleges_added"], len(result.get("errors", [])),
                    )
        except Exception as e:
            log.exception("  → CRASHED: %s", e)
            failures.append((s.name, [str(e)]))

    elapsed = time.time() - t0
    log.info(
        "DONE in %.0fs. success=%d failure=%d skipped=%d",
        elapsed, successes, len(failures), len(skipped),
    )
    if failures:
        log.info("Failures:")
        for name, errs in failures[:30]:
            log.info("  %s: %s", name, errs)


if __name__ == "__main__":
    asyncio.run(main())
