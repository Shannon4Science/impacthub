"""Stage 5 — reverse-look-up Semantic Scholar authorId for each CS/AI advisor.

This stage cannot run as a pure Python script because the SS public API
rate-limits hard from shared IPs.  Instead it is a **3-part flow**:

  1. ``--prep``  : dump ``/tmp/ss_match_<short>.json`` per school — list of
                   unlinked CS/AI advisors with name + title + college (input
                   for the Sonnet sub-agent).
  2. (manual)    : in an interactive Claude Code session, copy the prompt at
                   ``pipeline/prompts/lookup_ss_id.md`` and spawn one Sonnet
                   sub-agent per school.  Each agent writes
                   ``/tmp/ss_results_<short>.json``.
  3. ``--check`` : verify that every prepped school has a corresponding results
                   file with non-empty scholar_id entries; print coverage.

Stage 6 (``06_user_portfolios.py``) then consumes the results JSON.

Usage:
    cd pipeline
    python crawl/05_ss_match.py --prep --school all       # write input JSONs
    python crawl/05_ss_match.py --check --school all      # report coverage
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline._common import (  # noqa: E402
    ELITE_NAMES, SCHOOL_ALIAS, SCHOOL_EN, csai_like_sql, resolve_schools, setup_logging,
)

from sqlalchemy import text  # noqa: E402
from app.database import async_session, init_db  # noqa: E402

OUT_DIR = Path("/tmp")
log = setup_logging("/tmp/pipeline_crawl.log")


def short_name(cn: str) -> str:
    return next((k for k, v in SCHOOL_ALIAS.items() if v == cn and k != cn), cn).lower()


async def prep(schools: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    csai = csai_like_sql("c.name")
    for cn in schools:
        en = SCHOOL_EN.get(cn, (cn,))[0]
        async with async_session() as db:
            rows = (await db.execute(text(f"""
                SELECT a.id, a.name, a.title, c.name
                  FROM advisors a
                  JOIN advisor_colleges c ON c.id=a.college_id
                  JOIN advisor_schools s  ON s.id=a.school_id
                 WHERE s.name=:school AND {csai}
                   AND (a.impacthub_user_id IS NULL OR a.impacthub_user_id=0)
                 ORDER BY CASE
                   WHEN a.title LIKE '%院士%' THEN 0
                   WHEN a.title LIKE '%教授%' AND a.title NOT LIKE '%副%' AND a.title NOT LIKE '%助理%' THEN 1
                   WHEN a.title LIKE '%研究员%' AND a.title NOT LIKE '%副%' AND a.title NOT LIKE '%助理%' THEN 2
                   WHEN a.title LIKE '%副教授%' THEN 3
                   ELSE 4 END, a.id
            """), {"school": cn})).all()
        records = [{"advisor_id": r[0], "name": r[1], "title": r[2], "college": r[3], "school": en} for r in rows]
        out = OUT_DIR / f"ss_match_{short_name(cn)}.json"
        out.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        counts[cn] = len(records)
        log.info("  %s → %s (%d)", cn, out, len(records))
    return counts


async def check(schools: list[str]) -> int:
    """Return how many schools still need agent results (missing/empty files)."""
    csai = csai_like_sql("c.name")
    missing = 0
    log.info(f"{'School':<14} {'unlinked':>9} {'agent_found':>12} {'in_db_linked':>14}")
    log.info("-" * 56)
    for cn in schools:
        async with async_session() as db:
            n_unlinked = (await db.execute(text(f"""
                SELECT COUNT(*) FROM advisors a
                  JOIN advisor_colleges c ON c.id=a.college_id
                  JOIN advisor_schools s  ON s.id=a.school_id
                 WHERE s.name=:school AND {csai}
                   AND (a.impacthub_user_id IS NULL OR a.impacthub_user_id=0)
            """), {"school": cn})).scalar() or 0
            n_linked = (await db.execute(text(f"""
                SELECT COUNT(*) FROM advisors a
                  JOIN advisor_colleges c ON c.id=a.college_id
                  JOIN advisor_schools s  ON s.id=a.school_id
                 WHERE s.name=:school AND {csai}
                   AND a.impacthub_user_id IS NOT NULL AND a.impacthub_user_id != 0
            """), {"school": cn})).scalar() or 0
        agent_path = OUT_DIR / f"ss_results_{short_name(cn)}.json"
        if not agent_path.exists():
            agent_found = -1
        else:
            data = json.loads(agent_path.read_text(encoding="utf-8"))
            agent_found = sum(1 for r in data if r.get("scholar_id"))
        if agent_found < 0:
            missing += 1
            agent_cell = "MISSING"
        else:
            agent_cell = str(agent_found)
        log.info(f"{cn:<14} {n_unlinked:>9} {agent_cell:>12} {n_linked:>14}")
    return missing


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--school", default="all", help="comma-separated short names or 'all'")
    parser.add_argument("--prep", action="store_true", help="dump /tmp/ss_match_*.json for the agent")
    parser.add_argument("--check", action="store_true", help="report agent coverage")
    args = parser.parse_args()

    await init_db()
    schools = resolve_schools(args.school)

    if not args.prep and not args.check:
        log.info("Nothing to do. Pass --prep or --check. (Stage 5 is agent-driven; see prompts/lookup_ss_id.md)")
        return

    if args.prep:
        log.info("Dumping SS-match inputs for %d schools…", len(schools))
        await prep(schools)
        log.info("")
        log.info("→ next: spawn one Sonnet sub-agent per school using "
                 "pipeline/prompts/lookup_ss_id.md (each writes /tmp/ss_results_<short>.json)")

    if args.check:
        missing = await check(schools)
        if missing:
            log.warning("Stage 5 incomplete: %d school(s) without agent output yet.", missing)
            sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())
