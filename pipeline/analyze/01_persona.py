"""Stage 1 — compute persona (12-class MBTI-style code) for each linked User.

Uses LLM via `app.services.persona_service.compute_persona`. Independent of
other LLM tabs — depends only on the user's papers/repos/HF.

Usage:
    cd pipeline
    python analyze/01_persona.py --school SJTU --concurrency 10
    python analyze/01_persona.py --school all
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
    from app.services.persona_service import compute_persona  # noqa: E402
    await run_per_user_stage(
        "persona", args.school, compute_persona,
        concurrency=args.concurrency, max_users=args.max,
    )


if __name__ == "__main__":
    asyncio.run(main())
