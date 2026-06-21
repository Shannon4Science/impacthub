from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


class NormalizationError(ValueError):
    pass


@dataclass(frozen=True)
class NoteSummary:
    note_id: str
    url: str
    title: str
    content: str
    note_type: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class CommentPage:
    comments: list[dict[str, Any]]
    next_cursor: str
    next_index: int
    next_page_area: str


SEARCH_ITEMS_PATHS = (
    "data.items",
    "data.notes",
    "data.note_list",
    "data.list",
    "data.data.items",
    "data.data.notes",
    "data.data.note_list",
    "data.data.list",
)

COMMENT_LIST_PATHS = (
    "data.comments",
    "data.comment_list",
    "data.list",
    "data.items",
    "data.data.comments",
    "data.data.comment_list",
    "data.data.list",
    "data.data.items",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_search_page(payload: dict[str, Any]) -> tuple[list[NoteSummary], str, str]:
    items = _first_list(payload, SEARCH_ITEMS_PATHS)
    summaries = []
    for item in items:
        if not isinstance(item, dict):
            continue
        model_type = _as_str(item.get("model_type"))
        if model_type and model_type != "note":
            continue
        summaries.append(parse_search_item(item))
    search_id = str(
        _pick(
            payload,
            (
                "data.search_id",
                "data.searchId",
                "data.data.search_id",
                "data.data.searchId",
                "search_id",
                "searchId",
            ),
            "",
        )
        or ""
    )
    search_session_id = str(
        _pick(
            payload,
            (
                "data.search_session_id",
                "data.data.search_session_id",
                "search_session_id",
                "data.sessionId",
                "data.data.sessionId",
                "sessionId",
            ),
            "",
        )
        or ""
    )
    return summaries, search_id, search_session_id


def parse_search_item(item: dict[str, Any]) -> NoteSummary:
    card = _pick(item, ("note_card", "note", "card", "data"), item)
    if not isinstance(card, dict):
        card = item

    note_id = _as_str(
        _pick(
            item,
            (
                "note_id",
                "noteId",
                "note_id_str",
                "id",
                "note_card.note_id",
                "note_card.noteId",
                "note_card.id",
                "note.id",
                "card.note_id",
                "card.id",
            ),
        )
    )
    if not note_id:
        raise NormalizationError(f"Search item has no note id. keys={sorted(item.keys())}")

    url = _as_str(
        _pick(
            item,
            (
                "url",
                "share_url",
                "web_url",
                "note_card.url",
                "note_card.share_url",
                "note.share_url",
                "card.share_url",
            ),
            "",
        )
    )
    if not url:
        url = f"https://www.xiaohongshu.com/explore/{note_id}"

    title = _as_str(
        _pick(
            card,
            ("title", "display_title", "displayTitle", "desc", "description", "content"),
            "",
        )
    )
    content = _as_str(_pick(card, ("desc", "description", "content", "text"), ""))
    note_type = _as_str(_pick(item, ("type", "note_type", "note_card.type", "note.type"), ""))
    return NoteSummary(
        note_id=note_id,
        url=url,
        title=title,
        content=content,
        note_type=note_type,
        raw=item,
    )


def normalize_raw_note(
    *,
    summary: NoteSummary,
    query: str,
    detail_payload: dict[str, Any] | None,
    comments: list[dict[str, Any]],
) -> dict[str, Any]:
    detail = _detail_object(detail_payload or summary.raw)
    search_detail = _detail_object(summary.raw)

    def pick(paths: tuple[str, ...], default: Any = None) -> Any:
        return _pick(detail, paths, _pick(search_detail, paths, default))

    title = _as_str(
        pick(
            (
                "title",
                "display_title",
                "displayTitle",
                "note_card.title",
                "note_card.display_title",
                "share_info.title",
                "note.title",
            ),
            summary.title,
        )
    )
    content = _as_str(
        pick(
            (
                "desc",
                "description",
                "content",
                "text",
                "note_card.desc",
                "note_card.content",
                "share_info.content",
                "note.desc",
                "note.content",
            ),
            summary.content,
        )
    )
    author_name = _as_str(
        pick(
            (
                "user.nickname",
                "user.nick_name",
                "user.name",
                "author.nickname",
                "author.nick_name",
                "note_card.user.nickname",
                "note_card.user.nick_name",
                "note.user.nickname",
                "note.user.nick_name",
            ),
            "",
        )
    )

    likes = _as_int(
        pick(
            (
                "liked_count",
                "like_count",
                "likes",
                "interact_info.liked_count",
                "interact_info.like_count",
                "note_card.interact_info.liked_count",
                "note_card.liked_count",
                "note.liked_count",
                "note.like_count",
            ),
            0,
        )
    )
    comment_count = _as_int(
        pick(
            (
                "comment_count",
                "comments_count",
                "interact_info.comment_count",
                "note_card.interact_info.comment_count",
                "note_card.comments_count",
                "note.comments_count",
                "note.comment_count",
            ),
            len(comments),
        )
    )
    published_at = _normalize_datetime_value(
        pick(
            (
                "published_at",
                "publish_time",
                "publish_time_str",
                "created_at",
                "time",
                "timestamp",
                "note_card.time",
                "note_card.timestamp",
                "note.time",
                "note.timestamp",
            ),
            "",
        )
    )

    return {
        "source": "xiaohongshu",
        "note_id": summary.note_id,
        "url": summary.url,
        "query": query,
        "title": title,
        "content": content,
        "author_name": author_name,
        "likes": likes,
        "comment_count": comment_count,
        "published_at": published_at or None,
        "comments": comments,
        "collected_at": utc_now_iso(),
        "note_type": summary.note_type,
        "raw_search_item": summary.raw,
        "raw_detail": detail_payload,
    }


def parse_comment_page(payload: dict[str, Any]) -> CommentPage:
    raw_comments = _first_list(payload, COMMENT_LIST_PATHS)
    comments = []
    for comment in raw_comments:
        if not isinstance(comment, dict):
            continue
        normalized = normalize_comment(comment)
        if normalized:
            comments.append(normalized)
    next_cursor = _comment_cursor(
        _as_str(
            _pick(payload, ("data.cursor", "data.next_cursor", "data.data.cursor", "data.data.next_cursor"), "")
        )
    )
    next_index = _as_int(_pick(payload, ("data.index", "data.next_index", "data.data.index"), 0))
    next_page_area = _as_str(
        _pick(payload, ("data.pageArea", "data.page_area", "data.data.pageArea"), "UNFOLDED")
    )
    return CommentPage(
        comments=comments,
        next_cursor=next_cursor,
        next_index=next_index,
        next_page_area=next_page_area or "UNFOLDED",
    )


def _comment_cursor(value: str) -> str:
    if not value.startswith("{"):
        return value
    cursor_data = json.loads(value)
    if not isinstance(cursor_data, dict):
        raise NormalizationError("Comment cursor JSON must be an object")
    cursor = _as_str(cursor_data.get("cursor"))
    if not cursor:
        return ""
    return value


def normalize_comment(comment: dict[str, Any]) -> dict[str, Any] | None:
    text = _as_str(
        _pick(
            comment,
            (
                "text",
                "content",
                "desc",
                "comment",
                "content.text",
                "content.content",
            ),
            "",
        )
    )
    if not text:
        return None
    return {
        "comment_id": _as_str(_pick(comment, ("comment_id", "id", "commentId"), "")),
        "text": text,
        "likes": _as_int(_pick(comment, ("likes", "like_count", "liked_count"), 0)),
        "published_at": _as_str(_pick(comment, ("published_at", "publish_time", "time", "created_at"), ""))
        or None,
        "raw": comment,
    }


def is_video_note(summary: NoteSummary) -> bool:
    text = f"{summary.note_type} {summary.raw}".lower()
    return "video" in text or "视频" in text


def _detail_object(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    obj = _pick(
        payload,
        (
            "data.data.0.note_list.0",  # web_v2_feed_v2 backend
            "data.data.note",
            "data.data.note_card",
            "data.data.0",
            "data.data.items.0",
            "data.data.notes.0",
            "data.data.list.0",
            "data.note_list.0",
            "data.items.0",
            "data.notes.0",
            "data.list.0",
            "data.0",
            "data.data",
            "data.note",
            "data.note_card",
            "data",
            "note",
            "note_card",
            "card",
        ),
        payload,
    )
    if not isinstance(obj, dict):
        raise NormalizationError("Detail payload does not contain an object")
    return obj


def _first_list(obj: dict[str, Any], paths: tuple[str, ...]) -> list[Any]:
    for path in paths:
        value = _dig(obj, path)
        if isinstance(value, list):
            return value
    raise NormalizationError(f"None of these list paths exist: {', '.join(paths)}")


def _pick(obj: Any, paths: tuple[str, ...], default: Any = None) -> Any:
    for path in paths:
        value = _dig(obj, path)
        if value not in (None, "", []):
            return value
    return default


def _dig(obj: Any, path: str) -> Any:
    current = obj
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        else:
            return None
    return current


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_int(value: Any) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).replace(",", "").strip()
    if text.endswith("万"):
        return int(float(text[:-1]) * 10000)
    return int(float(text))


def _normalize_datetime_value(value: Any) -> str:
    text = _as_str(value)
    if not text:
        return ""
    if text.isdigit():
        timestamp = float(text)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return text
    return text
