from __future__ import annotations

import re
from typing import Any


TARGET_CONTEXT_KEYWORDS = (
    "老师",
    "导师",
    "教授",
    "课题组",
    "实验室",
    "组里",
    "组会",
    "招生",
    "保研",
    "直博",
    "考研",
    "面试",
    "申请",
    "方向",
    "推免",
    "博士",
    "硕士",
)


def normalize_aliases(values: list[str] | tuple[str, ...] | None) -> list[str]:
    if not values:
        return []
    aliases: list[str] = []
    seen: set[str] = set()
    for value in values:
        alias = str(value).strip()
        if not alias:
            continue
        key = alias.casefold()
        if key in seen:
            continue
        aliases.append(alias)
        seen.add(key)
    return aliases


def aliases_from_config(config: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    target = config.get("target", {})
    if isinstance(target, dict) and isinstance(target.get("aliases"), list):
        aliases.extend(str(value) for value in target["aliases"])
    extraction = config.get("extraction", {})
    if isinstance(extraction, dict) and isinstance(extraction.get("advisor_aliases"), list):
        aliases.extend(str(value) for value in extraction["advisor_aliases"])
    return normalize_aliases(aliases)


def note_text(
    raw_note: dict[str, Any],
    *,
    max_comments: int | None = None,
    include_query: bool = True,
) -> str:
    parts = [
        str(raw_note.get("title", "")),
        str(raw_note.get("content", "")),
    ]
    if include_query:
        parts.append(str(raw_note.get("query", "")))
    comments = raw_note.get("comments", [])
    if isinstance(comments, list):
        selected_comments = comments if max_comments is None else comments[:max_comments]
        parts.extend(str(comment.get("text", "")) for comment in selected_comments if isinstance(comment, dict))
    return "\n".join(part for part in parts if part)


def has_explicit_target(raw_note: dict[str, Any], advisor_name: str) -> bool:
    return bool(advisor_name and advisor_name in note_text(raw_note, include_query=False))


def matched_aliases(raw_note: dict[str, Any], aliases: list[str]) -> list[str]:
    text = note_text(raw_note, include_query=False)
    return [alias for alias in aliases if alias_in_text(alias, text)]


def alias_in_text(alias: str, text: str) -> bool:
    if not alias:
        return False
    if alias.isascii() and alias.replace("_", "").isalnum():
        return re.search(rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])", text, re.IGNORECASE) is not None
    return alias in text


def has_target_context(raw_note: dict[str, Any], school_name: str) -> bool:
    text = note_text(raw_note, include_query=False)
    if school_name and school_name in text:
        return True
    return any(keyword in text for keyword in TARGET_CONTEXT_KEYWORDS)


def prefilter_raw_note(
    raw_note: dict[str, Any],
    *,
    advisor_name: str,
    school_name: str,
    advisor_aliases: list[str],
) -> dict[str, Any]:
    aliases = normalize_aliases(advisor_aliases)
    alias_hits = matched_aliases(raw_note, aliases)
    query = str(raw_note.get("query", ""))

    if has_explicit_target(raw_note, advisor_name):
        return {
            "should_extract": True,
            "reason": "explicit_target",
            "matched_aliases": [],
        }
    if alias_hits and has_target_context(raw_note, school_name):
        return {
            "should_extract": True,
            "reason": "alias_with_context",
            "matched_aliases": alias_hits,
        }
    if query and (advisor_name in query or any(alias_in_text(alias, query) for alias in aliases)):
        if has_target_context(raw_note, school_name):
            return {
                "should_extract": True,
                "reason": "query_target_with_context",
                "matched_aliases": alias_hits,
            }

    return {
        "should_extract": False,
        "reason": "no_target_signal",
        "matched_aliases": alias_hits,
    }
