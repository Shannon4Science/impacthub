from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

from .jsonl import append_jsonl, read_seen_keys
from .normalize import (
    NormalizationError,
    NoteSummary,
    is_video_note,
    normalize_raw_note,
    parse_comment_page,
    parse_search_page,
    utc_now_iso,
)
from .settings import DEFAULT_CONFIG_PATH, load_settings
from .target import aliases_from_config, normalize_aliases
from .tikhub import TikHubClient, TikHubError


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl Xiaohongshu notes via TikHub.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--advisor-name", required=True)
    parser.add_argument("--school-name", required=True)
    parser.add_argument("--advisor-alias", action="append", default=[])
    parser.add_argument("--query", action="append", help="Override configured query templates.")
    parser.add_argument("--pages", type=int)
    parser.add_argument("--max-notes", type=int)
    parser.add_argument("--max-comments", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--detail-kind", choices=("auto", "image", "video", "none"))
    parser.add_argument("--no-comments", action="store_true")
    parser.add_argument("--no-supplemental", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = load_settings(args.config)
    advisor_aliases = normalize_aliases(aliases_from_config(settings.data) + args.advisor_alias)
    query_plan = _build_query_plan(settings.data, args)
    output_path = args.output or settings.path("crawler.output_raw_jsonl", "data/raw/xhs_notes.jsonl")
    pages = args.pages or int(settings.get("search.pages", 1))
    max_notes = args.max_notes or int(settings.get("crawler.max_notes_per_query", 10))
    max_comments = (
        args.max_comments
        if args.max_comments is not None
        else int(settings.get("crawler.max_comments_per_note", 0))
    )
    detail_kind = args.detail_kind or str(settings.get("crawler.detail_kind", "auto"))
    if not bool(settings.get("crawler.fetch_detail", True)):
        detail_kind = "none"
    fetch_comments = bool(settings.get("crawler.fetch_comments", True)) and not args.no_comments
    delay_seconds = float(settings.get("crawler.request_delay_seconds", 3))
    search_backend = str(settings.get("crawler.search_backend", "app"))
    comment_backend = str(settings.get("crawler.comment_backend", "app"))
    detail_backend = str(settings.get("crawler.detail_backend", "app_v2"))
    error_log_path = settings.path("crawler.error_log_jsonl", "data/logs/crawler_errors.jsonl")
    continue_on_error = bool(settings.get("crawler.continue_on_error", True))

    if args.dry_run:
        if advisor_aliases:
            print("Advisor aliases:")
            for alias in advisor_aliases:
                print(f"- {alias}")
        print("Primary queries:")
        for query in query_plan["primary"]:
            print(f"- {query}")
        supplemental_queries = [] if args.no_supplemental else query_plan["supplemental"]
        if supplemental_queries:
            threshold = supplemental_trigger_min_notes(settings.data)
            print(f"Supplemental queries: run only when primary writes fewer than {threshold} new notes")
            for query in supplemental_queries:
                print(f"- {query}")
        print(f"Output: {output_path}")
        return

    api_key = settings.require_env("api.token_env")
    seen = read_seen_keys(output_path, settings.get("dedup.keys", ["note_id", "url"]))

    with TikHubClient(
        api_key=api_key,
        base_url=str(settings.get("api.base_url", "https://api.tikhub.io")),
        timeout_seconds=float(settings.get("api.timeout_seconds", 30)),
        qps=float(settings.get("api.qps", 10)),
        retry_attempts=int(settings.get("api.retry_attempts", 3)),
        retry_base_sleep_seconds=float(settings.get("api.retry_base_sleep_seconds", 1)),
        retry_max_sleep_seconds=float(settings.get("api.retry_max_sleep_seconds", 8)),
    ) as client:
        total_written = 0
        primary_written = 0
        for query in query_plan["primary"]:
            written_for_query = crawl_query(
                client=client,
                settings=settings.data,
                query=query,
                pages=pages,
                max_notes=max_notes,
                max_comments=max_comments,
                detail_kind=detail_kind,
                fetch_comments=fetch_comments,
                search_backend=search_backend,
                comment_backend=comment_backend,
                detail_backend=detail_backend,
                delay_seconds=delay_seconds,
                output_path=output_path,
                error_log_path=error_log_path,
                continue_on_error=continue_on_error,
                seen=seen,
            )
            primary_written += written_for_query
            print(f"{query}: wrote {written_for_query} records")
        total_written += primary_written

        if (
            not args.no_supplemental
            and should_run_supplemental(settings.data, primary_written=primary_written)
            and query_plan["supplemental"]
        ):
            print(
                "Primary stage wrote "
                f"{primary_written} records; running supplemental queries."
            )
            for query in query_plan["supplemental"]:
                written_for_query = crawl_query(
                    client=client,
                    settings=settings.data,
                    query=query,
                    pages=pages,
                    max_notes=max_notes,
                    max_comments=max_comments,
                    detail_kind=detail_kind,
                    fetch_comments=fetch_comments,
                    search_backend=search_backend,
                    comment_backend=comment_backend,
                    detail_backend=detail_backend,
                    delay_seconds=delay_seconds,
                    output_path=output_path,
                    error_log_path=error_log_path,
                    continue_on_error=continue_on_error,
                    seen=seen,
                )
                total_written += written_for_query
                print(f"{query}: wrote {written_for_query} records")

    print(f"Done. wrote {total_written} records to {output_path}")


def crawl_query(
    *,
    client: TikHubClient,
    settings: dict[str, Any],
    query: str,
    pages: int,
    max_notes: int,
    max_comments: int,
    detail_kind: str,
    fetch_comments: bool,
    search_backend: str,
    comment_backend: str,
    detail_backend: str,
    delay_seconds: float,
    output_path: Path,
    error_log_path: Path | None,
    continue_on_error: bool,
    seen: set[str],
) -> int:
    search_id: str | None = None
    search_session_id: str | None = None
    written = 0

    for page in range(1, pages + 1):
        try:
            payload = search_notes(
                client=client,
                settings=settings,
                backend=search_backend,
                query=query,
                page=page,
                search_id=search_id,
                search_session_id=search_session_id,
            )
            summaries, next_search_id, next_search_session_id = parse_search_page(payload)
        except (TikHubError, NormalizationError) as exc:
            _log_crawl_error(
                error_log_path,
                stage="search",
                query=query,
                page=page,
                error=exc,
            )
            if continue_on_error:
                return written
            raise
        if page == 1:
            search_id = next_search_id or None
            search_session_id = next_search_session_id or None
        if page > 1 and (not search_id or not search_session_id):
            error = NormalizationError("TikHub search pagination did not return search_id/search_session_id")
            _log_crawl_error(
                error_log_path,
                stage="search_pagination",
                query=query,
                page=page,
                error=error,
            )
            if continue_on_error:
                return written
            raise error

        for summary in summaries:
            if written >= max_notes:
                return written
            keys = {f"note_id:{summary.note_id}", f"url:{summary.url}"}
            if keys & seen:
                continue

            record_errors: list[dict[str, Any]] = []
            try:
                detail_payload = fetch_detail(client, summary, detail_kind, detail_backend)
            except TikHubError as exc:
                detail_payload = None
                record_errors.append(_error_record("detail", exc))
                _log_crawl_error(
                    error_log_path,
                    stage="detail",
                    query=query,
                    note_id=summary.note_id,
                    error=exc,
                )
                if not continue_on_error:
                    raise
            if delay_seconds > 0:
                time.sleep(delay_seconds)

            comments: list[dict[str, Any]] = []
            if fetch_comments:
                try:
                    comments = fetch_note_comments(
                        client=client,
                        note_id=summary.note_id,
                        max_comments=max_comments,
                        sort_strategy=str(_config(settings, "crawler.comment_sort_strategy", "latest_v2")),
                        backend=comment_backend,
                        delay_seconds=delay_seconds,
                    )
                except (TikHubError, NormalizationError) as exc:
                    record_errors.append(_error_record("comments", exc))
                    _log_crawl_error(
                        error_log_path,
                        stage="comments",
                        query=query,
                        note_id=summary.note_id,
                        error=exc,
                    )
                    if not continue_on_error:
                        raise

            try:
                record = normalize_raw_note(
                    summary=summary,
                    query=query,
                    detail_payload=detail_payload,
                    comments=comments,
                )
            except NormalizationError as exc:
                record_errors.append(_error_record("normalize_detail", exc))
                _log_crawl_error(
                    error_log_path,
                    stage="normalize_detail",
                    query=query,
                    note_id=summary.note_id,
                    error=exc,
                )
                if not continue_on_error:
                    raise
                record = normalize_raw_note(
                    summary=summary,
                    query=query,
                    detail_payload=None,
                    comments=comments,
                )
            if record_errors:
                record["crawl_errors"] = record_errors
            append_jsonl(output_path, [record])
            seen.update(keys)
            written += 1
            print(f"  wrote note {summary.note_id}")

    return written


def search_notes(
    *,
    client: TikHubClient,
    settings: dict[str, Any],
    backend: str,
    query: str,
    page: int,
    search_id: str | None,
    search_session_id: str | None,
) -> dict[str, Any]:
    if backend == "app":
        return client.search_notes_app(
            keyword=query,
            page=page,
            sort_type=str(_config(settings, "search.sort_type", "general")),
            filter_note_type=str(_config(settings, "search.note_type", "不限")),
            filter_note_time=str(_config(settings, "search.time_filter", "不限")),
            search_id=search_id,
            session_id=search_session_id,
        )
    if backend != "app_v2":
        raise ValueError(f"Unsupported crawler.search_backend: {backend}")
    return client.search_notes(
        keyword=query,
        page=page,
        sort_type=str(_config(settings, "search.sort_type", "general")),
        note_type=str(_config(settings, "search.note_type", "不限")),
        time_filter=str(_config(settings, "search.time_filter", "不限")),
        source=str(_config(settings, "search.source", "explore_feed")),
        ai_mode=int(_config(settings, "search.ai_mode", 0)),
        search_id=search_id,
        search_session_id=search_session_id,
    )


def fetch_detail(
    client: TikHubClient,
    summary: NoteSummary,
    detail_kind: str,
    detail_backend: str,
) -> dict[str, Any] | None:
    if detail_kind == "none":
        return None
    if detail_backend == "web_v2_feed_v2":
        return client.get(
            "/api/v1/xiaohongshu/web_v2/fetch_feed_notes_v2",
            {"note_id": summary.note_id},
        )
    if detail_backend == "app":
        return client.get(
            "/api/v1/xiaohongshu/app/get_note_info",
            {"note_id": summary.note_id},
        )
    if detail_backend != "app_v2":
        raise ValueError(f"Unsupported crawler.detail_backend: {detail_backend}")
    if detail_kind == "video" or (detail_kind == "auto" and is_video_note(summary)):
        return client.get_video_note_detail(note_id=summary.note_id)
    return client.get_image_note_detail(note_id=summary.note_id)


def fetch_note_comments(
    *,
    client: TikHubClient,
    note_id: str,
    max_comments: int,
    sort_strategy: str,
    backend: str,
    delay_seconds: float,
) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    cursor = ""
    index = 0
    page_area = "UNFOLDED"

    while len(comments) < max_comments:
        if backend == "app":
            payload = client.get_note_comments_app(
                note_id=note_id,
                start=cursor,
                sort_strategy=int(sort_strategy),
            )
        elif backend == "app_v2":
            payload = client.get_note_comments(
                note_id=note_id,
                cursor=cursor,
                index=index,
                page_area=page_area,
                sort_strategy=sort_strategy,
            )
        else:
            raise ValueError(f"Unsupported crawler.comment_backend: {backend}")
        page = parse_comment_page(payload)
        if not page.comments:
            break
        comments.extend(page.comments)
        if len(comments) >= max_comments:
            break
        if not page.next_cursor:
            break
        cursor = page.next_cursor
        index = page.next_index
        page_area = page.next_page_area
        if delay_seconds > 0:
            time.sleep(delay_seconds)

    return comments[:max_comments]


def _build_query_plan(config: dict[str, Any], args: argparse.Namespace) -> dict[str, list[str]]:
    if args.query:
        return {"primary": args.query, "supplemental": []}
    return render_query_plan(
        config,
        advisor_name=args.advisor_name,
        school_name=args.school_name,
        advisor_aliases=normalize_aliases(aliases_from_config(config) + args.advisor_alias),
    )


def render_query_plan(
    config: dict[str, Any],
    *,
    advisor_name: str,
    school_name: str,
    advisor_aliases: list[str] | None = None,
) -> dict[str, list[str]]:
    search = config.get("search", {})
    if not isinstance(search, dict):
        raise ValueError("search config must be an object")
    configured_queries = search.get("queries")
    if configured_queries:
        if not isinstance(configured_queries, list):
            raise ValueError("search.queries must be a list")
        return {"primary": [str(query) for query in configured_queries], "supplemental": []}
    primary_templates = search.get("primary_query_templates") or search.get("query_templates")
    if not primary_templates:
        raise ValueError(
            "search.primary_query_templates is required when --query is not provided"
        )
    seen: set[str] = set()
    primary = _render_templates(
        primary_templates,
        advisor_name=advisor_name,
        school_name=school_name,
        advisor_aliases=advisor_aliases or [],
        seen=seen,
    )
    if not primary:
        raise ValueError("search.primary_query_templates rendered no queries")
    supplemental = _render_templates(
        search.get("supplemental_query_templates") or [],
        advisor_name=advisor_name,
        school_name=school_name,
        advisor_aliases=advisor_aliases or [],
        seen=seen,
    )
    return {"primary": primary, "supplemental": supplemental}


def render_query_templates(
    config: dict[str, Any],
    *,
    advisor_name: str,
    school_name: str,
    advisor_aliases: list[str] | None = None,
    include_supplemental: bool = False,
) -> list[str]:
    plan = render_query_plan(
        config,
        advisor_name=advisor_name,
        school_name=school_name,
        advisor_aliases=advisor_aliases,
    )
    queries = list(plan["primary"])
    if include_supplemental:
        queries.extend(plan["supplemental"])
    return queries


def supplemental_trigger_min_notes(config: dict[str, Any]) -> int:
    value = _config(config, "search.supplemental_trigger_min_new_notes", 10)
    return max(0, int(value))


def should_run_supplemental(config: dict[str, Any], *, primary_written: int) -> bool:
    threshold = supplemental_trigger_min_notes(config)
    return threshold > 0 and primary_written < threshold


def _render_templates(
    templates: Any,
    *,
    advisor_name: str,
    school_name: str,
    advisor_aliases: list[str],
    seen: set[str],
) -> list[str]:
    if not isinstance(templates, list):
        raise ValueError("search query templates must be a list")
    rendered: list[str] = []
    aliases = normalize_aliases(advisor_aliases)
    for template in templates:
        template_value = str(template)
        if "{alias}" in template_value:
            for alias in aliases:
                query = template_value.format(
                    advisor_name=advisor_name,
                    school_name=school_name,
                    alias=alias,
                ).strip()
                if query and query not in seen:
                    rendered.append(query)
                    seen.add(query)
            continue
        query = template_value.format(advisor_name=advisor_name, school_name=school_name).strip()
        if query and query not in seen:
            rendered.append(query)
            seen.add(query)
    return rendered


def _config(config: dict[str, Any], dotted_key: str, default: Any) -> Any:
    current: Any = config
    for key in dotted_key.split("."):
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _log_crawl_error(
    path: Path | None,
    *,
    stage: str,
    query: str,
    error: BaseException,
    page: int | None = None,
    note_id: str | None = None,
) -> None:
    if not path:
        return
    append_jsonl(
        path,
        [
            {
                "time": utc_now_iso(),
                "stage": stage,
                "query": query,
                "page": page,
                "note_id": note_id,
                "error": _error_record(stage, error),
            }
        ],
    )


def _error_record(stage: str, error: BaseException) -> dict[str, Any]:
    if isinstance(error, TikHubError):
        data = error.to_dict()
    else:
        data = {
            "message": str(error),
            "path": "",
            "status_code": None,
            "code": None,
            "request_id": "",
            "retriable": False,
            "response_text": "",
        }
    data["stage"] = stage
    data["type"] = type(error).__name__
    return data


if __name__ == "__main__":
    main()
