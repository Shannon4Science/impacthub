"""Stage 4 — web/social mentions ("network discussion heat") for each linked User.

Uses Perplexity-style search via `app.services.buzz_service.refresh_buzz`.
Must run before stage 5/6 — both trajectory and ai_summary read BuzzSnapshot.

Usage:
    cd pipeline
    python analyze/04_buzz.py --school SJTU
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline._common import (  # noqa: E402
    add_school_args, run_per_user_stage, setup_logging,
)

setup_logging("/tmp/pipeline_analyze.log")


async def main():
    parser = argparse.ArgumentParser()
    add_school_args(parser)
    args = parser.parse_args()
    from app.services.buzz_service import refresh_buzz  # noqa: E402
    await run_per_user_stage(
        "buzz", args.school, refresh_buzz,
        concurrency=args.concurrency, max_users=args.max,
    )


if __name__ == "__main__":
    asyncio.run(main())
