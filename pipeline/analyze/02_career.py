"""Stage 2 — pull career timeline (education + positions) for each linked User.

Uses LLM with web search via `app.services.career_service.refresh_career`.
Independent of other LLM tabs.

Usage:
    cd pipeline
    python analyze/02_career.py --school SJTU --concurrency 10
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
    from app.services.career_service import refresh_career  # noqa: E402
    await run_per_user_stage(
        "career", args.school, refresh_career,
        concurrency=args.concurrency, max_users=args.max,
    )


if __name__ == "__main__":
    asyncio.run(main())
