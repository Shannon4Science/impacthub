"""Stage 4 — fill bio/research_areas/email/photo for CS/AI advisor stubs.

Selects advisors where:
  - tier filter (school.is_985 etc.)
  - college.name matches a CSAI keyword
  - bio is empty, or previous crawl status is not detailed
  - homepage_url not empty, or a known source-page adapter can provide details

Processes in school-grouped order so per-host politeness delays kick in.
Idempotent: already-detailed records are skipped by the WHERE clause.

Usage:
    cd pipeline
    python crawl/04_advisor_details.py --tier 985 --max 200
    python crawl/04_advisor_details.py --school 复旦 --max 100
    python crawl/04_advisor_details.py --school 浙江大学 --college 计算机科学与技术学院 --max 5

When --college is explicitly provided, it is treated as a manual target list
and bypasses the default CSAI keyword filter.
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline._common import CSAI_KEYWORDS, setup_logging  # noqa: E402  (also adds backend/ to sys.path)

from sqlalchemy import select, and_, or_
from sqlalchemy.orm import joinedload

from app.database import async_session
from app.models import Advisor, AdvisorCollege, AdvisorSchool
from app.services import advisor_crawler_service

LOG_PATH = Path("/tmp/advisor_detail_csai.log")
DELAY_BETWEEN = 3.0
DELAY_AFTER_ERROR = 30.0


async def fetch_targets(
    tier: str,
    max_n: int,
    school_filter: str | None = None,
    college_filter: str | None = None,
) -> list[Advisor]:
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

        detail_source_where = or_(
            and_(
                Advisor.homepage_url.is_not(None),
                Advisor.homepage_url != "",
            ),
            Advisor.source_url.like("%icsr.zju.edu.cn/jsdw/list.htm%"),
            Advisor.source_url.like("%icsr.zju.edu.cn/jzjr/list.htm%"),
        )

        # incomplete detail: missing bio or not yet marked detailed; has a detail source.
        # Some old faculty pages do not publish research areas, so an empty
        # research_areas array alone must not make a finished row loop forever.
        stub_where = and_(
            or_(Advisor.crawl_status.is_(None), Advisor.crawl_status != "failed"),
            or_(
                Advisor.bio.is_(None),
                Advisor.bio == "",
                Advisor.crawl_status != "detailed",
            ),
            detail_source_where,
        )

        where_clauses = [tier_where, stub_where]
        if school_filter:
            where_clauses.append(AdvisorSchool.name.like(f"%{school_filter}%"))
        if college_filter:
            college_names = [name.strip() for name in college_filter.split(",") if name.strip()]
            if college_names:
                where_clauses.append(or_(*[AdvisorCollege.name.like(f"%{name}%") for name in college_names]))
            else:
                where_clauses.append(or_(*[AdvisorCollege.name.like(f"%{k}%") for k in CSAI_KEYWORDS]))
        else:
            where_clauses.append(or_(*[AdvisorCollege.name.like(f"%{k}%") for k in CSAI_KEYWORDS]))

        q = (
            select(Advisor)
            .options(joinedload(Advisor.school), joinedload(Advisor.college))
            .join(AdvisorCollege, Advisor.college_id == AdvisorCollege.id)
            .join(AdvisorSchool, Advisor.school_id == AdvisorSchool.id)
            .where(*where_clauses)
            .order_by(AdvisorSchool.id, AdvisorCollege.id, Advisor.id)
            .limit(max_n)
        )

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
    parser.add_argument("--college", help="filter by college name LIKE pattern; comma-separated patterns allowed")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--concurrency", type=int, default=1, help="parallel advisor detail jobs (default: 1)")
    args = parser.parse_args()

    log = setup_logging(LOG_PATH)

    advisors = await fetch_targets(
        args.tier,
        args.max,
        school_filter=args.school,
        college_filter=args.college,
    )
    log.info(
        "found %d targets (tier=%s, school=%s, college=%s)",
        len(advisors),
        args.tier,
        args.school,
        args.college,
    )
    if args.dry_run:
        for a in advisors[:20]:
            log.info("  %s | %s | %s | %s", a.school.name, a.college.name, a.name, a.homepage_url)
        return

    t0 = time.time()
    ok = 0
    fail = 0
    rate_skip = 0
    counter_lock = asyncio.Lock()

    async def process_one(i: int, a: Advisor) -> bool:
        nonlocal ok, fail, rate_skip
        log.info("[%4d/%d] %s / %s / %s", i, len(advisors), a.school.name, a.college.name, a.name)
        try:
            res = await crawl_one_advisor(a)
        except Exception as e:
            res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        rate_limited = False
        async with counter_lock:
            if res.get("ok"):
                ok += 1
                status = "detailed" if res.get("bio_present") else "partial"
                log.info("    ✓ %s areas=%d", status, res.get("areas_n", 0))
            else:
                err = res.get("error", "?")
                fail += 1
                log.warning("    ✗ %s", err)
                if any(s in err for s in ("503", "429", "fetch failed", "RemoteProtocolError", "Timeout")):
                    rate_skip += 1
                    rate_limited = True
        await asyncio.sleep(DELAY_BETWEEN)
        return rate_limited

    concurrency = max(1, args.concurrency)
    if concurrency == 1:
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

            rate_limited = await process_one(i, a)
            if rate_limited:
                consecutive_fail += 1
                # If rate-limited 5 in a row, pause before continuing.
                if consecutive_fail >= 5:
                    log.warning("    >>> 5 consecutive rate errors, sleeping %ds", int(DELAY_AFTER_ERROR))
                    await asyncio.sleep(DELAY_AFTER_ERROR)
                    consecutive_fail = 0
            else:
                consecutive_fail = 0
    else:
        sem = asyncio.Semaphore(concurrency)

        async def bounded_process(i: int, a: Advisor) -> None:
            async with sem:
                await process_one(i, a)

        await asyncio.gather(
            *(bounded_process(i, a) for i, a in enumerate(advisors, 1))
        )

    elapsed = time.time() - t0
    log.info("=== done in %.0fs: %d ok, %d fail, %d rate-skipped ===", elapsed, ok, fail, rate_skip)


if __name__ == "__main__":
    asyncio.run(main())
