"""Run the Xiaohongshu recruitment side path and write results into the main DB.

This is intentionally not a numbered stage: XHS data is supplementary evidence,
not a prerequisite for building the base advisor directory.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import func, select

from pipeline._common import setup_logging

from app.database import async_session, init_db
from app.models import Advisor, AdvisorCollege, AdvisorSchool, XhsCrawlRun
from app.services.recruitment_summary_service import import_xhs_recruitment_summary
from pipeline.crawl.xiaohongshu.crawl import render_query_plan
from pipeline.crawl.xiaohongshu.jsonl import iter_jsonl
from pipeline.crawl.xiaohongshu.pipeline import (
    crawl_queries,
    write_recruitment_summary,
)
from pipeline.crawl.xiaohongshu.settings import DEFAULT_CONFIG_PATH, Settings, load_settings
from pipeline.crawl.xiaohongshu.target import aliases_from_config, normalize_aliases
from pipeline.crawl.xiaohongshu.tikhub import TikHubClient


PIPELINE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = DEFAULT_CONFIG_PATH
OUTPUT_ROOT = PIPELINE_DIR / "data" / "xiaohongshu" / "output"
log = setup_logging("/tmp/pipeline_xhs_recruitment.log")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run XHS recruitment crawl side path.")
    parser.add_argument("--advisor-id", type=int)
    parser.add_argument("--school-name")
    parser.add_argument("--college-name")
    parser.add_argument("--advisor-alias", action="append", default=[])
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--pages", type=int)
    parser.add_argument("--max-notes", type=int)
    parser.add_argument("--max-valid-posts", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    await init_db()
    if args.check:
        await print_check()
        return

    if not any([args.advisor_id, args.school_name, args.college_name]):
        raise ValueError("请先指定 --advisor-id、--school-name 或 --college-name，避免误触发全库抓取")

    settings = load_settings(args.config)
    advisors = await select_advisors(args)
    if not advisors:
        raise RuntimeError("没有找到符合条件的导师")
    if args.advisor_alias and len(advisors) != 1:
        raise ValueError("--advisor-alias 只能和单个导师一起使用")

    configured_aliases = aliases_from_config(settings.data) if len(advisors) == 1 else []
    for advisor, school, college in advisors:
        advisor_aliases = normalize_aliases(configured_aliases + args.advisor_alias)
        if args.dry_run:
            print_dry_run(settings, advisor, school, advisor_aliases)
            continue
        await run_one(settings, advisor, school, college, advisor_aliases, args)


async def select_advisors(args: argparse.Namespace) -> list[tuple[Advisor, AdvisorSchool, AdvisorCollege]]:
    async with async_session() as db:
        stmt = (
            select(Advisor, AdvisorSchool, AdvisorCollege)
            .join(AdvisorSchool, AdvisorSchool.id == Advisor.school_id)
            .join(AdvisorCollege, AdvisorCollege.id == Advisor.college_id)
            .order_by(Advisor.id)
        )
        if args.advisor_id:
            stmt = stmt.where(Advisor.id == args.advisor_id)
        if args.school_name:
            stmt = stmt.where(AdvisorSchool.name == args.school_name)
        if args.college_name:
            stmt = stmt.where(AdvisorCollege.name == args.college_name)
        return list((await db.execute(stmt)).all())


def print_dry_run(
    settings: Settings,
    advisor: Advisor,
    school: AdvisorSchool,
    advisor_aliases: list[str],
) -> None:
    plan = render_query_plan(
        settings.data,
        advisor_name=advisor.name,
        school_name=school.name,
        advisor_aliases=advisor_aliases,
    )
    print(f"Advisor {advisor.id}: {school.name} / {advisor.name}")
    print("Primary queries:")
    for query in plan["primary"]:
        print(f"- {query}")
    if plan["supplemental"]:
        print("Supplemental queries:")
        for query in plan["supplemental"]:
            print(f"- {query}")


async def run_one(
    settings: Settings,
    advisor: Advisor,
    school: AdvisorSchool,
    college: AdvisorCollege,
    advisor_aliases: list[str],
    args: argparse.Namespace,
) -> None:
    query_plan = render_query_plan(
        settings.data,
        advisor_name=advisor.name,
        school_name=school.name,
        advisor_aliases=advisor_aliases,
    )
    search_query = "\n".join(query_plan["primary"])

    async with async_session() as db:
        run = XhsCrawlRun(
            advisor_id=advisor.id,
            status="searching",
            search_query=search_query,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        run_id = run.id

    run_day = datetime.now(timezone.utc).date().isoformat()
    run_dir = OUTPUT_ROOT / run_day / f"advisor_{advisor.id}" / f"run_{run_id}"
    raw_path = run_dir / "raw_notes.jsonl"
    candidates_path = run_dir / "candidates.jsonl"
    summary_path = run_dir / "summary.json"
    errors_path = run_dir / "crawler_errors.jsonl"

    try:
        log.info("XHS run %s: %s / %s / %s", run_id, school.name, college.name, advisor.name)
        with tikhub_client(settings) as crawl_client:
            error_count_before = _jsonl_count(errors_path)
            written = crawl_queries(
                crawl_client,
                settings,
                query_plan["primary"],
                raw_path,
                errors_path,
                args,
            )

        raw_note_count = _jsonl_count(raw_path)
        error_count_after = _jsonl_count(errors_path)
        if (
            written == 0
            and raw_note_count == 0
            and error_count_after > error_count_before
            and bool(settings.get("pipeline.fail_on_zero_primary", True))
        ):
            raise RuntimeError("Primary crawl wrote 0 raw records. Check crawler_errors.jsonl before trusting the report.")

        async with async_session() as db:
            run = await _get_run(db, run_id)
            run.status = "summarizing"
            run.raw_note_count = raw_note_count
            await db.commit()

        summary = write_recruitment_summary(
            settings,
            raw_path,
            candidates_path,
            summary_path,
            advisor_name=advisor.name,
            school_name=school.name,
            advisor_aliases=advisor_aliases,
            max_valid_posts=args.max_valid_posts,
        )
        candidates = list(iter_jsonl(candidates_path)) if candidates_path.exists() else []

        async with async_session() as db:
            inserted = await import_xhs_recruitment_summary(
                db,
                advisor_id=advisor.id,
                xhs_summary_json=summary,
                xhs_candidates_jsonl=candidates,
            )

        async with async_session() as db:
            run = await _get_run(db, run_id)
            run.status = "done"
            run.raw_note_count = raw_note_count
            run.candidate_count = len(candidates)
            run.mentions_inserted = inserted
            run.summary_updated = True
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()
        log.info(
            "XHS run %s done: raw=%d candidates=%d mentions_inserted=%d",
            run_id,
            raw_note_count,
            len(candidates),
            inserted,
        )
    except Exception as exc:
        async with async_session() as db:
            run = await _get_run(db, run_id)
            run.status = "failed"
            run.error = str(exc)
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()
        raise


async def _get_run(db, run_id: int) -> XhsCrawlRun:
    run = await db.get(XhsCrawlRun, run_id)
    if not run:
        raise RuntimeError(f"XHS run {run_id} not found")
    return run


def tikhub_client(settings: Settings) -> TikHubClient:
    return TikHubClient(
        api_key=settings.require_env("api.token_env"),
        base_url=str(settings.get("api.base_url", "https://api.tikhub.io")),
        timeout_seconds=float(settings.get("api.timeout_seconds", 30)),
        qps=float(settings.get("api.qps", 10)),
        retry_attempts=int(settings.get("api.retry_attempts", 3)),
        retry_base_sleep_seconds=float(settings.get("api.retry_base_sleep_seconds", 1)),
        retry_max_sleep_seconds=float(settings.get("api.retry_max_sleep_seconds", 8)),
    )


def _jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for _ in iter_jsonl(path))


async def print_check() -> None:
    async with async_session() as db:
        total = (await db.execute(select(func.count(Advisor.id)))).scalar_one()
        current = (
            await db.execute(
                select(func.count(Advisor.id)).where(Advisor.recruitment_summary_status == "found_current")
            )
        ).scalar_one()
        stale = (
            await db.execute(
                select(func.count(Advisor.id)).where(Advisor.recruitment_summary_status == "found_stale")
            )
        ).scalar_one()
        not_found = (
            await db.execute(
                select(func.count(Advisor.id)).where(Advisor.recruitment_summary_status == "not_found")
            )
        ).scalar_one()

        latest_run_subq = (
            select(
                XhsCrawlRun.advisor_id.label("advisor_id"),
                func.max(XhsCrawlRun.id).label("run_id"),
            )
            .group_by(XhsCrawlRun.advisor_id)
            .subquery()
        )
        latest_runs = (
            await db.execute(
                select(XhsCrawlRun.status)
                .join(latest_run_subq, latest_run_subq.c.run_id == XhsCrawlRun.id)
            )
        ).scalars().all()
        searched = len(latest_runs)
        recent_failed = sum(1 for status in latest_runs if status == "failed")

    print("xiaohongshu recruitment")
    print(f"total advisors:       {total}")
    print(f"found current:        {current}")
    print(f"found stale:          {stale}")
    print(f"explicit not found:   {not_found}")
    print(f"never searched:       {total - searched}")
    print(f"latest run failed:    {recent_failed}")


if __name__ == "__main__":
    asyncio.run(main())
