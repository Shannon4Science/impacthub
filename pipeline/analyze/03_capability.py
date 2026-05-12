"""Stage 3 — multi-direction capability profile (originator / extender / follower etc.).

Uses LLM via `app.services.capability_service.refresh_capability`.
Reads Paper / NotableCitation / CitationAnalysis — independent of buzz / trajectory.

Usage:
    cd pipeline
    python analyze/03_capability.py --school SJTU
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
    from app.services.capability_service import refresh_capability  # noqa: E402
    await run_per_user_stage(
        "capability", args.school, refresh_capability,
        concurrency=args.concurrency, max_users=args.max,
    )


if __name__ == "__main__":
    asyncio.run(main())
