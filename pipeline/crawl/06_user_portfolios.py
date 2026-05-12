"""Build ImpactHub User profiles for advisors with known SS authorIds.

Reads /tmp/ss_results_<batch>.json — agent-produced mapping of
{advisor_id, name, scholar_id, confidence}.

For each entry with a non-empty scholar_id:
  1. Skip if Advisor.impacthub_user_id is already set
  2. discover_from_scholar(scholar_id) → name/avatar/github/hf
  3. Create User row (or reuse if scholar_id collides)
  4. Trigger portfolio refresh (papers/dblp/ccf/github/hf/milestones/snapshots/persona)
  5. UPDATE Advisor.semantic_scholar_id + impacthub_user_id

Usage:
    cd pipeline
    python crawl/06_user_portfolios.py --input /tmp/ss_results_sjtu.json
    python crawl/06_user_portfolios.py --input /tmp/ss_results_sjtu.json --dry-run
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline._common import setup_logging, refresh_portfolio  # noqa: E402  (also adds backend/ to sys.path)

from sqlalchemy import select  # noqa: E402
from app.database import async_session, init_db  # noqa: E402
from app.models import User, Advisor  # noqa: E402

LOG_PATH = Path("/tmp/build_advisor_profiles.log")
log = setup_logging(LOG_PATH)


async def discover_and_link(advisor_id: int, scholar_id: str) -> str:
    """Run discover_from_scholar → create User → link advisor. Returns status."""
    from app.services.discover_service import discover_from_scholar
    res = await discover_from_scholar(scholar_id)
    if res.errors:
        return f"discover_fail: {res.errors[0]}"

    async with async_session() as db:
        advisor = await db.get(Advisor, advisor_id)
        if not advisor:
            return "advisor_missing"

        existing = (await db.execute(select(User).where(User.scholar_id == scholar_id))).scalars().first()
        if existing:
            uid = existing.id
            log.info("    reuse existing User id=%d", uid)
        else:
            user = User(
                name=res.name or advisor.name,
                avatar_url=res.avatar_url or "",
                bio=res.bio or advisor.bio or "",
                scholar_id=scholar_id,
                github_username=res.github_username or "",
                hf_username=res.hf_username or "",
                honor_tags=advisor.honors,
                research_direction="",
                seed_tier="",
                visible=False,
            )
            db.add(user)
            await db.flush()
            uid = user.id
            log.info("    ✓ created User id=%d (%s)", uid, user.name)

        advisor.impacthub_user_id = uid
        advisor.semantic_scholar_id = scholar_id
        await db.commit()
        return f"linked:{uid}"


async def process_entry(entry: dict, dry: bool) -> tuple[str, dict]:
    aid = entry.get("advisor_id")
    sid = entry.get("scholar_id") or ""
    name = entry.get("name", "?")
    if not aid or not sid:
        return "no_scholar_id", entry
    log.info("[advisor=%d] %s — SS=%s (%s)", aid, name, sid, entry.get("confidence", "?"))
    async with async_session() as db:
        a = await db.get(Advisor, aid)
        if a is None:
            return "advisor_missing", entry
        if a.impacthub_user_id and not dry:
            log.info("    already linked → User %d, skip", a.impacthub_user_id)
            return "already_linked", entry
    if dry:
        return "dry", entry

    status = await discover_and_link(aid, sid)
    if not status.startswith("linked:"):
        return status, entry
    uid = int(status.split(":")[1])
    ok = await refresh_portfolio(uid)
    return ("portfolio_ok" if ok else "portfolio_fail"), entry


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, help="JSON file produced by SS lookup agent")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--min-confidence", choices=["high", "medium", "low"], default="medium")
    args = p.parse_args()

    await init_db()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    conf_rank = {"high": 3, "medium": 2, "low": 1, "none": 0, "": 0}
    cutoff = conf_rank[args.min_confidence]
    work = [r for r in data if conf_rank.get(r.get("confidence", "none"), 0) >= cutoff and r.get("scholar_id")]
    log.info("input=%s total=%d eligible=%d (min_conf=%s)", args.input, len(data), len(work), args.min_confidence)

    counts: dict[str, int] = {}
    t0 = time.time()
    for i, entry in enumerate(work, 1):
        log.info("---- %d/%d ----", i, len(work))
        try:
            status, _ = await process_entry(entry, args.dry_run)
        except Exception as e:
            log.exception("crashed: %s", e)
            status = "crash"
        counts[status] = counts.get(status, 0) + 1
        await asyncio.sleep(1.0)

    log.info("DONE in %.0fs", time.time() - t0)
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        log.info("  %s: %d", k, v)


if __name__ == "__main__":
    asyncio.run(main())
