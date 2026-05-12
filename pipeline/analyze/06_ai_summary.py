"""Stage 6 — overall AI summary + tags (depends on stages 4 buzz + 5 trajectory).

Uses LLM via `app.services.ai_summary_service.refresh_ai_summary`. Reads
BuzzSnapshot + ResearchTrajectory + papers + repos + HF + notable citations.

Usage:
    cd pipeline
    python analyze/06_ai_summary.py --school SJTU
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
    from app.services.ai_summary_service import refresh_ai_summary  # noqa: E402
    await run_per_user_stage(
        "ai_summary", args.school, refresh_ai_summary,
        concurrency=args.concurrency, max_users=args.max,
    )


if __name__ == "__main__":
    asyncio.run(main())
