"""Stage 5 — research trajectory analysis (depends on stage 4 buzz).

Uses LLM via `app.services.trajectory_service.refresh_trajectory`. Reads papers
+ BuzzSnapshot + (any prior) AISummary as supplementary signals.

Usage:
    cd pipeline
    python analyze/05_trajectory.py --school SJTU
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
    from app.services.trajectory_service import refresh_trajectory  # noqa: E402
    await run_per_user_stage(
        "trajectory", args.school, refresh_trajectory,
        concurrency=args.concurrency, max_users=args.max,
    )


if __name__ == "__main__":
    asyncio.run(main())
