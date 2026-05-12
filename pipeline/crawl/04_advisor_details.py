"""Stage 4 — fill bio/research_areas/email/photo for CS/AI advisor stubs.

Selects advisors where:
  - tier filter (school.is_985 etc.)
  - college.name matches a CSAI keyword
  - bio/research_areas empty
  - homepage_url not empty

Processes in school-grouped order so per-host politeness delays kick in.
Idempotent: already-detailed records are skipped by the WHERE clause.

Usage:
    cd pipeline
    python crawl/04_advisor_details.py --tier 985 --max 200
    python crawl/04_advisor_details.py --school 复旦 --max 100
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline._common import CSAI_KEYWORDS, setup_logging  # noqa: E402  (also adds backend/ to sys.path)

from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import joinedload

from app.database import async_session
from app.models import Advisor, AdvisorCollege, AdvisorSchool
from app.services import advisor_crawler_service

LOG_PATH = Path("/tmp/advisor_detail_csai.log")
DELAY_BETWEEN = 3.0
DELAY_AFTER_ERROR = 30.0


async def fetch_targets(tier: str, max_n: int, school_filter: str | None = None) -> list[Advisor]:
    """Return ordered list of advisor stubs to process."""
    async with async_session() as db:
        # Build WHERE on tier
        tier_clauses = {
            "985": AdvisorSchool.is_985 == True,
            "211": and_(AdvisorSchool.is_985 == False, AdvisorSchool.is_211 == True),
            "df": and_(AdvisorSchool.is_985 == False, AdvisorSchool.is_211 == False,
                       AdvisorSchool.is_double_first_class == True),
            "all": AdvisorSchool.id > 0,
        }
        tier_where = tier_clauses.get(tier, tier_clauses["985"])

        kw_or = or_(*[AdvisorCollege.name.like(f"%{k}%") for k in CSAI_KEYWORDS])

        # stub: no bio AND no research_areas; has homepage_url
        stub_where = and_(
            or_(Advisor.bio.is_(None), Advisor.bio == ""),
            or_(Advisor.research_areas.is_(None), func.json_array_length(Advisor.research_areas) == 0),
            Advisor.homepage_url.is_not(None),
            Advisor.homepage_url != "",
        )

        q = (
            select(Advisor)
            .options(joinedload(Advisor.school), joinedload(Advisor.college))
            .join(AdvisorCollege, Advisor.college_id == AdvisorCollege.id)
            .join(AdvisorSchool, Advisor.school_id == AdvisorSchool.id)
            .where(tier_where, kw_or, stub_where)
            .order_by(AdvisorSchool.id, AdvisorCollege.id, Advisor.id)
            .limit(max_n)
        )
        if school_filter:
            q = q.where(AdvisorSchool.name.like(f"%{school_filter}%"))

        result = await db.execute(q)
        return list(result.scalars().unique().all())


async def crawl_one_advisor(advisor: Advisor) -> dict:
    """Crawl one advisor's detail using its own DB session."""
    async with async_session() as db:
        # Re-fetch so the object is attached to this session
        a = await db.get(Advisor, advisor.id)
        if a is None:
            return {"ok": False, "error": "advisor disappeared"}
        try:
            res = await advisor_crawler_service.crawl_advisor_detail(db, a)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        if res.get("ok"):
            await db.commit()
        return res


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", default="985", choices=["985", "211", "df", "all"])
    parser.add_argument("--max", type=int, default=200, help="max advisors to process this run")
    parser.add_argument("--school", help="filter by school name LIKE pattern (e.g. '清华')")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    log = setup_logging(LOG_PATH)

    advisors = await fetch_targets(args.tier, args.max, school_filter=args.school)
    log.info("found %d targets (tier=%s, school=%s)", len(advisors), args.tier, args.school)
    if args.dry_run:
        for a in advisors[:20]:
            log.info("  %s | %s | %s | %s", a.school.name, a.college.name, a.name, a.homepage_url)
        return

    t0 = time.time()
    ok = 0; fail = 0; rate_skip = 0
    last_school_id = None
    consecutive_fail = 0
    for i, a in enumerate(advisors, 1):
        # Bigger pause when switching schools (different host = no need to throttle)
        if a.school_id != last_school_id:
            if last_school_id is not None:
                log.info("--- switching schools, sleeping 5s ---")
                await asyncio.sleep(5)
            last_school_id = a.school_id
            consecutive_fail = 0

        log.info("[%4d/%d] %s / %s / %s", i, len(advisors), a.school.name, a.college.name, a.name)
        res = await crawl_one_advisor(a)
        if res.get("ok"):
            ok += 1; consecutive_fail = 0
            log.info("    ✓ areas=%d", res.get("areas_n", 0))
        else:
            err = res.get("error", "?")
            fail += 1
            log.warning("    ✗ %s", err)
            if any(s in err for s in ("503", "429", "fetch failed", "RemoteProtocolError", "Timeout")):
                rate_skip += 1
                consecutive_fail += 1
                # If rate-limited 5 in a row, skip to next school
                if consecutive_fail >= 5:
                    log.warning("    >>> 5 consecutive rate errors, sleeping %ds", int(DELAY_AFTER_ERROR))
                    await asyncio.sleep(DELAY_AFTER_ERROR)
                    consecutive_fail = 0
        await asyncio.sleep(DELAY_BETWEEN)

    elapsed = time.time() - t0
    log.info("=== done in %.0fs: %d ok, %d fail, %d rate-skipped ===", elapsed, ok, fail, rate_skip)


if __name__ == "__main__":
    asyncio.run(main())
