"""信息爬取层 — orchestrator with per-stage resume + completeness validation.

For each stage:
  1. Compute (expected, done) before running.
  2. If done == expected, skip the stage (idempotent fast-path).
  3. Otherwise run the stage script.
  4. Re-check; if the gap is still non-zero, log the first few missing rows.

Exits non-zero when any stage finishes with a non-empty gap so cron / shell
chains can react.  Underlying stage scripts are themselves idempotent (skip
already-crawled rows by DB flag), so this orchestrator is safely re-runnable.

Stages:
    1. schools           — import 双一流 high-school list (JSON → DB).         no LLM
    2. colleges          — for each school, ask LLM to extract its college list. LLM
    3. advisor_stubs     — for each college, ask LLM to extract faculty stubs.   LLM
    4. advisor_details   — fetch homepage + LLM-parse bio / research_areas.       LLM
    5. ss_match          — Sonnet sub-agent reverse-looks-up SS authorIds.        agent
    6. user_portfolios   — create User + pull papers/DBLP/CCF/GitHub/HF/snapshots. no LLM

Usage:
    cd pipeline
    python crawl/run_all.py                # resume all stages
    python crawl/run_all.py --only 4       # rerun stage 4 only
    python crawl/run_all.py --check        # report state, do not crawl
    python crawl/run_all.py --strict       # also error on partial schools/colleges
"""
import argparse
import asyncio
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Awaitable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline._common import (  # noqa: E402
    CSAI_KEYWORDS, ELITE_NAMES, csai_like_sql, setup_logging,
)

from sqlalchemy import text  # noqa: E402
from app.database import async_session, init_db  # noqa: E402

PIPELINE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PIPELINE_DIR / "data"
log = setup_logging("/tmp/pipeline_crawl.log")


# ──────────────────────────── per-stage probes ────────────────────────────

@dataclass
class StageState:
    label: str
    expected: int
    done: int
    examples_missing: list[str]   # up to 5 representative missing identifiers

    @property
    def gap(self) -> int:
        return self.expected - self.done

    @property
    def complete(self) -> bool:
        return self.expected > 0 and self.done >= self.expected


async def probe_schools() -> StageState:
    seed = json.loads((DATA_DIR / "advisor_schools_211.json").read_text(encoding="utf-8"))
    expected = len(seed["schools"])
    async with async_session() as db:
        n = (await db.execute(text("SELECT COUNT(*) FROM advisor_schools"))).scalar() or 0
        names_db = {r[0] for r in (await db.execute(text("SELECT name FROM advisor_schools"))).all()}
    missing = [s["name"] for s in seed["schools"] if s["name"] not in names_db][:5]
    return StageState("schools", expected, n, missing)


async def probe_colleges() -> StageState:
    """Expected = every elite school has colleges_crawled_at set."""
    elite_csv = ",".join(f"'{n}'" for n in ELITE_NAMES)
    async with async_session() as db:
        expected = (await db.execute(text(
            f"SELECT COUNT(*) FROM advisor_schools WHERE name IN ({elite_csv})"
        ))).scalar() or 0
        done = (await db.execute(text(
            f"SELECT COUNT(*) FROM advisor_schools WHERE name IN ({elite_csv}) "
            f"AND colleges_crawled_at IS NOT NULL"
        ))).scalar() or 0
        missing = [r[0] for r in (await db.execute(text(
            f"SELECT name FROM advisor_schools WHERE name IN ({elite_csv}) "
            f"AND colleges_crawled_at IS NULL LIMIT 5"
        ))).all()]
    return StageState("colleges", expected, done, missing)


async def probe_advisor_stubs() -> StageState:
    """Expected = every CS/AI college (in elite schools) has advisors_crawled_at set."""
    csai = csai_like_sql("c.name")
    elite_csv = ",".join(f"'{n}'" for n in ELITE_NAMES)
    async with async_session() as db:
        expected = (await db.execute(text(
            f"SELECT COUNT(c.id) FROM advisor_colleges c JOIN advisor_schools s ON s.id=c.school_id "
            f"WHERE s.name IN ({elite_csv}) AND {csai}"
        ))).scalar() or 0
        done = (await db.execute(text(
            f"SELECT COUNT(c.id) FROM advisor_colleges c JOIN advisor_schools s ON s.id=c.school_id "
            f"WHERE s.name IN ({elite_csv}) AND {csai} AND c.advisors_crawled_at IS NOT NULL"
        ))).scalar() or 0
        missing = [f"{r[0]} / {r[1]}" for r in (await db.execute(text(
            f"SELECT s.short_name, c.name FROM advisor_colleges c "
            f"JOIN advisor_schools s ON s.id=c.school_id "
            f"WHERE s.name IN ({elite_csv}) AND {csai} AND c.advisors_crawled_at IS NULL LIMIT 5"
        ))).all()]
    return StageState("advisor_stubs", expected, done, missing)


async def probe_advisor_details() -> StageState:
    """Expected = every CS/AI advisor (elite) with homepage_url has bio."""
    csai = csai_like_sql("c.name")
    elite_csv = ",".join(f"'{n}'" for n in ELITE_NAMES)
    async with async_session() as db:
        base = (
            f"FROM advisors a JOIN advisor_colleges c ON c.id=a.college_id "
            f"JOIN advisor_schools s ON s.id=a.school_id "
            f"WHERE s.name IN ({elite_csv}) AND {csai} AND a.homepage_url != ''"
        )
        expected = (await db.execute(text(f"SELECT COUNT(*) {base}"))).scalar() or 0
        done = (await db.execute(text(
            f"SELECT COUNT(*) {base} AND a.bio != ''"
        ))).scalar() or 0
        missing = [f"{r[0]} / {r[1]}" for r in (await db.execute(text(
            f"SELECT s.short_name, a.name {base} AND (a.bio IS NULL OR a.bio='') LIMIT 5"
        ))).all()]
    return StageState("advisor_details", expected, done, missing)


async def probe_ss_match() -> StageState:
    """Expected = every CS/AI advisor (elite) has a scholar_id from the agent step.
    Done = JSON file exists for each elite school with at least 1 scholar_id."""
    import json as _json
    csai = csai_like_sql("c.name")
    elite_csv = ",".join(f"'{n}'" for n in ELITE_NAMES)
    async with async_session() as db:
        expected = (await db.execute(text(
            f"SELECT COUNT(*) FROM advisors a JOIN advisor_colleges c ON c.id=a.college_id "
            f"JOIN advisor_schools s ON s.id=a.school_id "
            f"WHERE s.name IN ({elite_csv}) AND {csai}"
        ))).scalar() or 0
    done = 0
    missing: list[str] = []
    from pipeline._common import SCHOOL_ALIAS
    for cn in ELITE_NAMES:
        short = next((k for k, v in SCHOOL_ALIAS.items() if v == cn and k != cn), cn).lower()
        path = Path(f"/tmp/ss_results_{short}.json")
        if not path.exists():
            missing.append(f"{cn} (no agent output)")
            continue
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
            done += sum(1 for r in data if r.get("scholar_id"))
        except Exception:
            missing.append(f"{cn} (corrupt JSON)")
    return StageState("ss_match", expected, done, missing[:5])


async def probe_user_portfolios() -> StageState:
    """Expected = elite CS/AI advisors. Done = those with impacthub_user_id linked."""
    csai = csai_like_sql("c.name")
    elite_csv = ",".join(f"'{n}'" for n in ELITE_NAMES)
    async with async_session() as db:
        base = (
            f"FROM advisors a JOIN advisor_colleges c ON c.id=a.college_id "
            f"JOIN advisor_schools s ON s.id=a.school_id "
            f"WHERE s.name IN ({elite_csv}) AND {csai}"
        )
        expected = (await db.execute(text(f"SELECT COUNT(*) {base}"))).scalar() or 0
        done = (await db.execute(text(
            f"SELECT COUNT(*) {base} AND a.impacthub_user_id IS NOT NULL AND a.impacthub_user_id != 0"
        ))).scalar() or 0
        missing = [f"{r[0]} / {r[1]}" for r in (await db.execute(text(
            f"SELECT s.short_name, a.name {base} "
            f"AND (a.impacthub_user_id IS NULL OR a.impacthub_user_id = 0) LIMIT 5"
        ))).all()]
    return StageState("user_portfolios", expected, done, missing)


# stage 5 is agent-driven; the orchestrator only runs the JSON-prep + coverage check.
# stage 6 needs one input JSON per school — orchestrator iterates ELITE_NAMES.
def _stage6_cmds() -> list[list[str]]:
    from pipeline._common import SCHOOL_ALIAS
    cmds = []
    for cn in ELITE_NAMES:
        short = next((k for k, v in SCHOOL_ALIAS.items() if v == cn and k != cn), cn).lower()
        inp = Path(f"/tmp/ss_results_{short}.json")
        if inp.exists():
            cmds.append(["python", "crawl/06_user_portfolios.py", "--input", str(inp)])
    return cmds


# (stage_id, label, probe, command-or-callable)
STAGES: list[tuple[int, str, Callable[[], Awaitable[StageState]], list]] = [
    (1, "schools",         probe_schools,         [["python", "crawl/01_schools.py"]]),
    (2, "colleges",        probe_colleges,        [["python", "crawl/02_colleges.py"]]),
    (3, "advisor_stubs",   probe_advisor_stubs,   [["python", "crawl/03_advisor_stubs.py"]]),
    (4, "advisor_details", probe_advisor_details, [["python", "crawl/04_advisor_details.py", "--tier", "985"]]),
    (5, "ss_match",        probe_ss_match,        [["python", "crawl/05_ss_match.py", "--prep", "--school", "all"]]),
    (6, "user_portfolios", probe_user_portfolios, _stage6_cmds),
]


def fmt_state(st: StageState) -> str:
    pct = (st.done / st.expected * 100) if st.expected else 0.0
    return f"{st.label:<16} {st.done:>5}/{st.expected:<5} ({pct:5.1f}%)"


# ──────────────────────────── orchestration ────────────────────────────


def _resolve_cmds(spec) -> list[list[str]]:
    return spec() if callable(spec) else spec


def run_stage_cmds(stage_id: int, label: str, spec) -> int:
    cmds = _resolve_cmds(spec)
    if not cmds:
        log.info("Stage %d (%s): no commands to run (nothing prepared yet)", stage_id, label)
        return 0
    log.info("=" * 72)
    log.info("Running stage %d (%s): %d command(s)", stage_id, label, len(cmds))
    log.info("=" * 72)
    worst = 0
    for cmd in cmds:
        log.info("  $ %s", " ".join(cmd))
        rc = subprocess.call(cmd, cwd=PIPELINE_DIR)
        worst = max(worst, rc)
    return worst


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip", default="", help="comma-separated stage ids to skip")
    parser.add_argument("--only", default="", help="comma-separated stage ids to run exclusively")
    parser.add_argument("--check", action="store_true", help="probe state and exit; do not crawl")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero if any stage finishes with a gap (default: log & continue)")
    args = parser.parse_args()

    await init_db()
    skip = {int(s) for s in args.skip.split(",") if s.strip()}
    only = {int(s) for s in args.only.split(",") if s.strip()}

    log.info("CS/AI scope keywords: %s", " | ".join(CSAI_KEYWORDS))
    log.info("Elite schools:       %s", "  ".join(ELITE_NAMES))
    log.info("")

    final_gaps: list[StageState] = []
    for stage_id, label, probe, cmd in STAGES:
        if only and stage_id not in only:
            continue
        if stage_id in skip:
            log.info("Stage %d (%s) — explicit --skip, ignoring", stage_id, label)
            continue

        before = await probe()
        log.info("Stage %d %s — BEFORE %s", stage_id, "🔍", fmt_state(before))
        if args.check:
            if not before.complete and before.examples_missing:
                log.info("    missing: %s", "; ".join(before.examples_missing))
            final_gaps.append(before)
            continue

        if before.complete:
            log.info("    ✓ already complete, skipping")
            continue

        rc = run_stage_cmds(stage_id, label, cmd)
        after = await probe()
        log.info("Stage %d %s — AFTER  %s%s",
                 stage_id, "✓" if after.complete else "⚠",
                 fmt_state(after),
                 "" if rc == 0 else f"  (cmd rc={rc})")
        if not after.complete:
            if after.examples_missing:
                log.warning("    still missing %d: %s",
                            after.gap, "; ".join(after.examples_missing))
            final_gaps.append(after)

    log.info("")
    log.info("=" * 72)
    log.info("Final crawl-layer state:")
    for stage_id, label, probe, _ in STAGES:
        st = await probe()
        log.info("  %s", fmt_state(st))

    incomplete = [s for s in final_gaps if not s.complete]
    if args.strict and incomplete and not args.check:
        log.error("Incomplete stages: %s", ", ".join(s.label for s in incomplete))
        sys.exit(2)
    if incomplete and not args.check:
        log.warning("Run again to make further progress; pass --strict to fail on residual gap.")


if __name__ == "__main__":
    asyncio.run(main())
