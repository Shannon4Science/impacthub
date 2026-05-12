"""整合分析层 — orchestrator with resume + completeness validation.

Each stage corresponds to one LLM-derived tab on the per-advisor academic
profile page. Order is load-bearing: ai_summary reads buzz + trajectory, and
trajectory reads buzz, so 4 → 5 → 6 must stay sequential. The other three
(persona / career / capability) are independent and can be re-ordered freely.

Stages:
    1. persona    — 12-class MBTI-style code
    2. career     — education + position timeline
    3. capability — multi-direction role profile
    4. buzz       — web / social mention heat
    5. trajectory — research trajectory analysis      (needs buzz)
    6. ai_summary — overall summary + tags             (needs buzz + trajectory)

Usage:
    cd pipeline
    python analyze/run_all.py --check
    python analyze/run_all.py --schools SJTU,ZJU
    python analyze/run_all.py --schools all --only 4
"""
import argparse
import asyncio
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline._common import (  # noqa: E402
    ELITE_NAMES, csai_like_sql, resolve_schools, setup_logging,
)

from sqlalchemy import text  # noqa: E402
from app.database import async_session, init_db  # noqa: E402

PIPELINE_DIR = Path(__file__).resolve().parent.parent
log = setup_logging("/tmp/pipeline_analyze.log")


@dataclass
class StageState:
    label: str
    expected: int
    done: int
    @property
    def gap(self) -> int: return self.expected - self.done
    @property
    def complete(self) -> bool: return self.expected > 0 and self.done >= self.expected


async def _linked_user_count(schools: list[str]) -> int:
    csai = csai_like_sql("c.name")
    schools_csv = ",".join(f"'{s}'" for s in schools)
    async with async_session() as db:
        return (await db.execute(text(
            f"SELECT COUNT(*) FROM advisors a JOIN advisor_colleges c ON c.id=a.college_id "
            f"JOIN advisor_schools s ON s.id=a.school_id "
            f"WHERE s.name IN ({schools_csv}) AND {csai} "
            f"AND a.impacthub_user_id IS NOT NULL AND a.impacthub_user_id != 0"
        ))).scalar() or 0


def _make_probe(tab_table: str):
    async def probe(schools: list[str]) -> StageState:
        csai = csai_like_sql("c.name")
        schools_csv = ",".join(f"'{s}'" for s in schools)
        async with async_session() as db:
            expected = await _linked_user_count(schools)
            done_q = text(f"""
                SELECT COUNT(DISTINCT t.user_id)
                  FROM {tab_table} t
                  JOIN advisors a         ON a.impacthub_user_id = t.user_id
                  JOIN advisor_colleges c ON c.id = a.college_id
                  JOIN advisor_schools s  ON s.id = a.school_id
                 WHERE s.name IN ({schools_csv}) AND {csai}
            """)
            done = (await db.execute(done_q)).scalar() or 0
        return StageState(tab_table, expected, done)
    return probe


# (stage_id, label, probe_factory, script)
STAGES: list[tuple[int, str, Callable[[list[str]], Awaitable[StageState]], str]] = [
    (1, "persona",    _make_probe("researcher_personas"),    "01_persona.py"),
    (2, "career",     _make_probe("career_histories"),       "02_career.py"),
    (3, "capability", _make_probe("capability_profiles"),    "03_capability.py"),
    (4, "buzz",       _make_probe("buzz_snapshots"),         "04_buzz.py"),
    (5, "trajectory", _make_probe("research_trajectories"),  "05_trajectory.py"),
    (6, "ai_summary", _make_probe("ai_summaries"),           "06_ai_summary.py"),
]


def fmt_state(st: StageState) -> str:
    pct = (st.done / st.expected * 100) if st.expected else 0.0
    return f"{st.label:<12} {st.done:>4}/{st.expected:<4} ({pct:5.1f}%)"


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--schools", default="all",
                        help="short names (SJTU/ZJU/...) comma-separated, or 'all'")
    parser.add_argument("--skip", default="", help="stage ids to skip, e.g. '1,2'")
    parser.add_argument("--only", default="", help="stage ids to run exclusively")
    parser.add_argument("--check", action="store_true", help="probe state and exit; do not enrich")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero if any stage still has a gap")
    parser.add_argument("--concurrency", type=int, default=10,
                        help="parallel users per stage (each user's tabs stay sequential)")
    args = parser.parse_args()

    await init_db()
    schools = resolve_schools(args.schools)
    skip = {int(s) for s in args.skip.split(",") if s.strip()}
    only = {int(s) for s in args.only.split(",") if s.strip()}

    log.info("Schools: %s", schools)
    n_linked = await _linked_user_count(schools)
    log.info("Linked users in scope: %d", n_linked)
    log.info("")

    final_gaps: list[StageState] = []
    for stage_id, label, probe, script in STAGES:
        if only and stage_id not in only:
            continue
        if stage_id in skip:
            log.info("Stage %d (%s) — explicit --skip", stage_id, label)
            continue

        before = await probe(schools)
        log.info("Stage %d 🔍 BEFORE %s", stage_id, fmt_state(before))
        if args.check:
            final_gaps.append(before)
            continue
        if before.complete:
            log.info("    ✓ already complete, skipping")
            continue

        cmd = ["python", f"analyze/{script}",
               "--school", ",".join(schools), "--concurrency", str(args.concurrency)]
        log.info("    $ %s", " ".join(cmd))
        rc = subprocess.call(cmd, cwd=PIPELINE_DIR)
        after = await probe(schools)
        log.info("Stage %d %s AFTER  %s%s",
                 stage_id, "✓" if after.complete else "⚠",
                 fmt_state(after),
                 "" if rc == 0 else f"  (cmd rc={rc})")
        if not after.complete:
            final_gaps.append(after)

    log.info("")
    log.info("=" * 60)
    log.info("Final analyze-layer state (linked users in scope = %d):", n_linked)
    for stage_id, label, probe, _ in STAGES:
        log.info("  %s", fmt_state(await probe(schools)))

    incomplete = [s for s in final_gaps if not s.complete]
    if args.strict and incomplete and not args.check:
        log.error("Incomplete stages: %s", ", ".join(s.label for s in incomplete))
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())
