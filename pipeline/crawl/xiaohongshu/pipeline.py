from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from openai import OpenAI

from .crawl import crawl_query, render_query_plan
from .jsonl import iter_jsonl, read_seen_keys
from .recruitment import (
    empty_summary,
    select_recruitment_posts,
    summarize_recruitment_posts,
    write_json,
    write_jsonl,
)
from .settings import DEFAULT_CONFIG_PATH, Settings, load_settings
from .target import aliases_from_config, normalize_aliases
from .tikhub import TikHubClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Run XHS public recruitment-post crawl and summary pipeline.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--advisor-name", required=True)
    parser.add_argument("--school-name", required=True)
    parser.add_argument("--advisor-alias", action="append", default=[])
    parser.add_argument("--pages", type=int)
    parser.add_argument("--max-notes", type=int)
    parser.add_argument("--max-valid-posts", type=int)
    parser.add_argument("--run-dir", type=Path, help="Write this run's outputs under the given directory.")
    parser.add_argument(
        "--shared-output",
        action="store_true",
        help="Use the legacy shared data/raw and data/processed paths.",
    )
    args = parser.parse_args()

    settings = load_settings(args.config)
    advisor_aliases = normalize_aliases(aliases_from_config(settings.data) + args.advisor_alias)
    paths = resolve_pipeline_paths(settings, args, advisor_aliases)
    query_plan = render_query_plan(
        settings.data,
        advisor_name=args.advisor_name,
        school_name=args.school_name,
        advisor_aliases=advisor_aliases,
    )

    print(f"Pipeline output directory: {paths['run_dir']}")
    with tikhub_client(settings) as crawl_client:
        primary_error_count_before = jsonl_line_count(paths["errors"])
        primary_written = crawl_queries(
            crawl_client,
            settings,
            query_plan["primary"],
            paths["raw"],
            paths["errors"],
            args,
        )
        primary_error_count_after = jsonl_line_count(paths["errors"])
        primary_had_errors = primary_error_count_after > primary_error_count_before
        if primary_written == 0 and primary_had_errors and not has_jsonl_records(paths["raw"]):
            fail_on_zero_primary = bool(_config(settings.data, "pipeline.fail_on_zero_primary", True))
            if fail_on_zero_primary:
                raise RuntimeError(
                    "Primary crawl wrote 0 raw records. Check crawler_errors.jsonl before trusting the report."
                )

        summary = write_recruitment_summary(
            settings,
            paths["raw"],
            paths["candidates"],
            paths["summary"],
            advisor_name=args.advisor_name,
            school_name=args.school_name,
            advisor_aliases=advisor_aliases,
            max_valid_posts=args.max_valid_posts,
        )
        print(
            "Recruitment summary selected "
            f"{summary.get('source_post_count', 0)} posts; "
            f"LLM calls: {summary.get('llm_call_count', 0)}"
        )


def resolve_pipeline_paths(
    settings: Settings,
    args: argparse.Namespace,
    advisor_aliases: list[str],
) -> dict[str, Path]:
    if args.shared_output:
        return {
            "run_dir": settings.root,
            "raw": settings.path("crawler.output_raw_jsonl", "data/raw/xhs_notes.jsonl"),
            "candidates": settings.path(
                "recruitment.output_candidates_jsonl",
                "data/processed/xhs_recruitment_candidates.jsonl",
            ),
            "summary": settings.path(
                "recruitment.output_summary_json",
                "data/processed/xhs_recruitment_summary.json",
            ),
            "errors": settings.path("crawler.error_log_jsonl", "data/logs/crawler_errors.jsonl"),
        }
    run_dir = args.run_dir or Path("data/runs") / run_slug(
        school_name=args.school_name,
        advisor_name=args.advisor_name,
        advisor_aliases=advisor_aliases,
    )
    if not run_dir.is_absolute():
        run_dir = settings.root / run_dir
    return {
        "run_dir": run_dir,
        "raw": run_dir / "raw" / "xhs_notes.jsonl",
        "candidates": run_dir / "processed" / "xhs_recruitment_candidates.jsonl",
        "summary": run_dir / "processed" / "xhs_recruitment_summary.json",
        "errors": run_dir / "logs" / "crawler_errors.jsonl",
    }


def run_slug(*, school_name: str, advisor_name: str, advisor_aliases: list[str]) -> str:
    base = f"{school_name}_{advisor_name}"
    if advisor_aliases:
        base = f"{base}_{'_'.join(advisor_aliases)}"
    slug = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", base, flags=re.UNICODE).strip("_.")
    return slug or "advisor"


def has_jsonl_records(path: Path) -> bool:
    if not path.exists():
        return False
    for _record in iter_jsonl(path):
        return True
    return False


def jsonl_line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


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


def llm_client_from_settings(settings: Settings) -> Anthropic | OpenAI:
    provider = str(settings.get("llm.provider", "openai")).lower()
    if provider == "anthropic":
        return Anthropic(
            api_key=settings.require_env("llm.api_key_env"),
            base_url=str(settings.get("llm.base_url", "https://api.anthropic.com")),
            timeout=float(settings.get("llm.timeout_seconds", 360)),
            max_retries=int(settings.get("llm.max_retries", 0)),
        )
    if provider != "openai":
        raise ValueError(f"Unsupported llm.provider: {provider}")
    return OpenAI(
        api_key=settings.require_env("llm.api_key_env"),
        base_url=str(settings.get("llm.base_url", "https://api.deepseek.com")),
        timeout=float(settings.get("llm.timeout_seconds", 90)),
        max_retries=int(settings.get("llm.max_retries", 0)),
    )


def crawl_queries(
    client: TikHubClient,
    settings: Settings,
    queries: list[str],
    output_path: Path,
    error_log_path: Path,
    args: argparse.Namespace,
) -> int:
    seen = read_seen_keys(output_path, settings.get("dedup.keys", ["note_id", "url"]))
    total = 0
    detail_kind = str(settings.get("crawler.detail_kind", "auto"))
    if not bool(settings.get("crawler.fetch_detail", True)):
        detail_kind = "none"
    for query in queries:
        written = crawl_query(
            client=client,
            settings=settings.data,
            query=query,
            pages=args.pages if args.pages is not None else int(settings.get("search.pages", 1)),
            max_notes=(
                args.max_notes
                if args.max_notes is not None
                else int(settings.get("crawler.max_notes_per_query", 8))
            ),
            max_comments=int(settings.get("crawler.max_comments_per_note", 0)),
            detail_kind=detail_kind,
            fetch_comments=bool(settings.get("crawler.fetch_comments", False))
            and int(settings.get("crawler.max_comments_per_note", 0)) > 0,
            search_backend=str(settings.get("crawler.search_backend", "app")),
            comment_backend=str(settings.get("crawler.comment_backend", "app")),
            detail_backend=str(settings.get("crawler.detail_backend", "app_v2")),
            delay_seconds=float(settings.get("crawler.request_delay_seconds", 3)),
            output_path=output_path,
            error_log_path=error_log_path,
            continue_on_error=bool(settings.get("crawler.continue_on_error", True)),
            seen=seen,
        )
        total += written
        print(f"{query}: wrote {written} raw records")
    return total


def write_recruitment_summary(
    settings: Settings,
    raw_path: Path,
    candidates_path: Path,
    summary_path: Path,
    *,
    advisor_name: str,
    school_name: str,
    advisor_aliases: list[str],
    max_valid_posts: int | None,
) -> dict[str, Any]:
    max_posts = (
        max_valid_posts
        if max_valid_posts is not None
        else int(settings.get("recruitment.max_posts_for_summary", 12))
    )
    max_posts = min(max_posts, 4)
    candidates = select_recruitment_posts(
        settings=settings.data,
        raw_path=raw_path,
        advisor_name=advisor_name,
        school_name=school_name,
        advisor_aliases=advisor_aliases,
        max_posts=max_posts,
    )
    write_jsonl(candidates_path, candidates)
    if candidates:
        summary = summarize_recruitment_posts(
            client=llm_client_from_settings(settings),
            settings=settings.data,
            candidates=candidates,
            advisor_name=advisor_name,
            school_name=school_name,
            advisor_aliases=advisor_aliases,
        )
    else:
        summary = empty_summary(
            advisor_name=advisor_name,
            school_name=school_name,
            advisor_aliases=advisor_aliases,
        )
    write_json(summary_path, summary)
    print(f"wrote {len(candidates)} recruitment candidates to {candidates_path}")
    print(f"wrote recruitment summary to {summary_path}")
    return summary


def _config(config: dict[str, Any], dotted_key: str, default: Any) -> Any:
    current: Any = config
    for key in dotted_key.split("."):
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


if __name__ == "__main__":
    main()
