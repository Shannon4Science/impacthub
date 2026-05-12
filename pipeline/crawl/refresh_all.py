"""Periodic refresh — pull papers/DBLP/CCF/GitHub/HF + snapshot + milestones
for every existing User in DB.

Replaces what `backend/app/tasks/scheduler.py` used to do in-process. Hooked
into cron via `ops/advance.sh` (or its own crontab line, e.g.
``0 */6 * * * cd .../pipeline && python crawl/refresh_all.py``).

Differs from `06_user_portfolios.py`:
  - `06_user_portfolios.py` consumes the SS-match JSON to create *new* Users.
  - `refresh_all.py` iterates *existing* Users and re-pulls their data.

Usage:
    cd pipeline
    python crawl/refresh_all.py                     # all users
    python crawl/refresh_all.py --advisors-only     # only advisor-linked Users
    python crawl/refresh_all.py --concurrency 8
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline._common import refresh_portfolio, setup_logging  # noqa: E402

from sqlalchemy import select  # noqa: E402
from app.database import async_session, init_db  # noqa: E402
from app.models import User, Advisor  # noqa: E402

log = setup_logging("/tmp/pipeline_refresh_all.log")


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--advisors-only", action="store_true",
                   help="only refresh Users linked to an Advisor (skip seed leaderboard users)")
    p.add_argument("--concurrency", type=int, default=5,
                   help="parallel users (the SS API rate-limits hard; 5 is sane)")
    p.add_argument("--max", type=int, default=0, help="cap total users")
    args = p.parse_args()

    await init_db()

    async with async_session() as db:
        if args.advisors_only:
            stmt = (select(User.id, User.name)
                    .join(Advisor, Advisor.impacthub_user_id == User.id)
                    .order_by(User.id))
        else:
            stmt = select(User.id, User.name).order_by(User.id)
        if args.max > 0:
            stmt = stmt.limit(args.max)
        rows = (await db.execute(stmt)).all()

    log.info("Refreshing %d users (advisors_only=%s, concurrency=%d)",
             len(rows), args.advisors_only, args.concurrency)

    sem = asyncio.Semaphore(args.concurrency)
    ok = fail = 0
    t0 = time.time()

    async def work(idx: int, uid: int, name: str):
        nonlocal ok, fail
        async with sem:
            log.info("[%d/%d] User %d (%s)", idx, len(rows), uid, name)
            if await refresh_portfolio(uid):
                ok += 1
            else:
                fail += 1

    await asyncio.gather(*[work(i, uid, n) for i, (uid, n) in enumerate(rows, 1)])
    log.info("DONE in %.0fs — ok=%d fail=%d", time.time() - t0, ok, fail)


if __name__ == "__main__":
    asyncio.run(main())
