from __future__ import annotations

import argparse
import json
import re
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from openai import OpenAI

from .jsonl import iter_jsonl
from .normalize import utc_now_iso
from .settings import DEFAULT_CONFIG_PATH, load_settings
from .target import alias_in_text, aliases_from_config, normalize_aliases


DEFAULT_RECRUITMENT_KEYWORDS = (
    "招生",
    "招收",
    "招募",
    "申请",
    "套磁",
    "博士",
    "硕士",
    "直博",
    "推免",
    "RA",
    "科研助理",
    "实习生",
    "intern",
    "internship",
)

DEFAULT_REQUIRED_RECRUITMENT_KEYWORDS = (
    "招生",
    "招收",
    "招募",
    "RA",
    "科研助理",
    "实习生",
    "intern",
    "internship",
)

DEFAULT_EXCLUDED_POST_KEYWORDS = (
    "怎么样",
    "避雷",
    "求问",
    "求求",
    "吐槽",
    "曝光",
    "818",
    "八一八",
    "质疑",
    "致zhi",
    "快跑",
    "评价",
    "口碑",
)

SYSTEM_PROMPT = """你是一个谨慎的招生信息整理助手。

Persona:
- 只整理公开小红书主贴标题和正文里的招生事实。
- 标题也是事实来源；不要因为正文截断就忽略标题里明示的招生对象。
- 不评价导师、学生体验或课题组氛围。
- 不使用评论、搜索词或外部常识补事实。
- 如果正文被截断，就基于可见文本给出你的判断，并在相应字段说明低置信度或截断。

Answer template:
只输出一个 JSON 对象，不要 Markdown。字段如下：
{
  "recruitment_status": "found_current | found_stale | found_unclear | not_found",
  "summary": "120-220字中文概况，说明招生对象、研究方向、申请方式/联系方式、时效性和主要缺口",
  "latest_recruitment_post_published_at": "string|null",
  "positions": [{"type": "博士|硕士|保研/推免|直博|RA|科研助理|实习生|其他|未说明", "detail": "string", "source_note_ids": ["string"], "time_sensitivity": "current|possibly_stale|unknown"}],
  "directions": [{"direction": "string", "details": ["string"], "source_note_ids": ["string"], "confidence": 0.0}],
  "requirements": [{"requirement": "string", "source_note_ids": ["string"]}],
  "application_methods": [{"method": "string", "source_note_ids": ["string"], "is_primary": true}],
  "timeline": [{"time": "string", "detail": "string", "source_note_ids": ["string"]}],
  "source_posts": [{"note_id": "string", "title": "string", "url": "string", "published_at": "string|null", "relation_to_target": "explicit|alias|lab_member|uncertain", "time_sensitivity": "current|possibly_stale|unknown", "extracted_facts": ["string"]}],
  "limitations": ["string"]
}

填写要求：
- summary 中提到的岗位、方向、申请方式、来源帖，必须同步进入对应数组。
- 数组对象必须使用模板里的字段；如果没有事实就用空数组，不要输出 {"reason": "..."} 这类对象。
- source_note_ids 只使用输入 posts 中的 note_id。
- directions 字段要求：
  * 固定输出3-5个研究方向，不管输入多少条帖子
  * 粒度由"区分度"决定：如果学生对方向A感兴趣但对方向B不感兴趣，则A和B应分开列出
  * 表述标准：用"领域+问题"格式，如"机器人导航"、"三维场景生成"
  * 避免过于宽泛（"人工智能"）或过于具体（论文标题级别）
  * 长度控制在8-15个字
  * 数量控制：
    - 如果帖子内容高度一致 → 输出2-3个方向
    - 如果帖子跨越多个领域 → 输出4-5个方向
    - 绝对不超过5个
  * 每个方向必须包含：direction（方向名称）、details（1-2句话具体说明，可选）、source_note_ids（支撑帖子ID列表）"""

RECRUITMENT_SUMMARY_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
    "required": [
        "recruitment_status",
        "summary",
        "latest_recruitment_post_published_at",
        "directions",
        "positions",
        "requirements",
        "application_methods",
        "timeline",
        "source_posts",
        "limitations",
    ],
    "properties": {
        "recruitment_status": {
            "type": "string",
            "enum": ["found_current", "found_stale", "found_unclear", "not_found"],
        },
        "summary": {"type": "string"},
        "latest_recruitment_post_published_at": {"type": ["string", "null"]},
        "directions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["direction", "details", "source_note_ids"],
                "additionalProperties": True,
                "properties": {
                    "direction": {"type": "string"},
                    "details": {"type": "array", "items": {"type": "string"}},
                    "source_note_ids": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                },
            },
        },
        "positions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["type", "detail", "source_note_ids"],
                "additionalProperties": True,
                "properties": {
                    "type": {"type": "string"},
                    "detail": {"type": "string"},
                    "source_note_ids": {"type": "array", "items": {"type": "string"}},
                    "time_sensitivity": {"type": "string"},
                },
            },
        },
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["requirement", "source_note_ids"],
                "additionalProperties": True,
                "properties": {
                    "requirement": {"type": "string"},
                    "source_note_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "application_methods": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["method", "source_note_ids"],
                "additionalProperties": True,
                "properties": {
                    "method": {"type": "string"},
                    "source_note_ids": {"type": "array", "items": {"type": "string"}},
                    "is_primary": {"type": "boolean"},
                },
            },
        },
        "timeline": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["time", "detail", "source_note_ids"],
                "additionalProperties": True,
                "properties": {
                    "time": {"type": "string"},
                    "detail": {"type": "string"},
                    "source_note_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "source_posts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["note_id", "title", "url", "published_at", "relation_to_target", "time_sensitivity"],
                "additionalProperties": True,
                "properties": {
                    "note_id": {"type": "string"},
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "published_at": {"type": ["string", "null"]},
                    "relation_to_target": {"type": "string"},
                    "time_sensitivity": {"type": "string"},
                    "extracted_facts": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize public XHS recruitment posts in one LLM call.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--advisor-name", required=True)
    parser.add_argument("--school-name", required=True)
    parser.add_argument("--advisor-alias", action="append", default=[])
    parser.add_argument("--input", type=Path)
    parser.add_argument("--candidates-output", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-posts", type=int)
    args = parser.parse_args()

    settings = load_settings(args.config)
    advisor_aliases = normalize_aliases(aliases_from_config(settings.data) + args.advisor_alias)
    input_path = args.input or settings.path("crawler.output_raw_jsonl", "data/raw/xhs_notes.jsonl")
    candidates_path = args.candidates_output or settings.path(
        "recruitment.output_candidates_jsonl",
        "data/processed/xhs_recruitment_candidates.jsonl",
    )
    output_path = args.output or settings.path(
        "recruitment.output_summary_json",
        "data/processed/xhs_recruitment_summary.json",
    )
    configured_max_posts = args.max_posts or int(_config(settings.data, "recruitment.max_posts_for_summary", 4))
    max_posts = min(configured_max_posts, 4)

    candidates = select_recruitment_posts(
        settings=settings.data,
        raw_path=input_path,
        advisor_name=args.advisor_name,
        school_name=args.school_name,
        advisor_aliases=advisor_aliases,
        max_posts=max_posts,
    )
    write_jsonl(candidates_path, candidates)
    if candidates:
        provider = str(settings.get("llm.provider", "openai")).lower()
        if provider == "anthropic":
            client = Anthropic(
                api_key=settings.require_env("llm.api_key_env"),
                base_url=str(settings.get("llm.base_url", "https://api.anthropic.com")),
                timeout=float(settings.get("llm.timeout_seconds", 360)),
                max_retries=int(settings.get("llm.max_retries", 0)),
            )
        else:
            client = OpenAI(
                api_key=settings.require_env("llm.api_key_env"),
                base_url=str(settings.get("llm.base_url", "https://api.deepseek.com")),
                timeout=float(settings.get("llm.timeout_seconds", 90)),
                max_retries=int(settings.get("llm.max_retries", 0)),
            )
        summary = summarize_recruitment_posts(
            client=client,
            settings=settings.data,
            candidates=candidates,
            advisor_name=args.advisor_name,
            school_name=args.school_name,
            advisor_aliases=advisor_aliases,
        )
    else:
        summary = empty_summary(
            advisor_name=args.advisor_name,
            school_name=args.school_name,
            advisor_aliases=advisor_aliases,
        )
    write_json(output_path, summary)
    print(f"wrote {len(candidates)} recruitment candidates to {candidates_path}")
    print(f"wrote recruitment summary to {output_path}")


def select_recruitment_posts(
    *,
    settings: dict[str, Any],
    raw_path: Path,
    advisor_name: str,
    school_name: str,
    advisor_aliases: list[str],
    max_posts: int,
) -> list[dict[str, Any]]:
    if not raw_path.exists():
        return []
    keywords = recruitment_keywords(settings)
    required_keywords = required_recruitment_keywords(settings)
    excluded_keywords = excluded_post_keywords(settings)
    candidates = []
    for raw_note in iter_jsonl(raw_path):
        candidate = build_candidate(
            raw_note=raw_note,
            advisor_name=advisor_name,
            school_name=school_name,
            advisor_aliases=advisor_aliases,
            keywords=keywords,
            required_keywords=required_keywords,
            excluded_keywords=excluded_keywords,
            recent_days=int(_config(settings, "recruitment.recent_days", 365)),
            stale_days=int(_config(settings, "recruitment.stale_days", 730)),
        )
        if candidate:
            candidates.append(candidate)
    candidates.sort(
        key=lambda item: (
            date_sort_key(item.get("published_at")),
            int(item.get("selection_score") or 0),
        ),
        reverse=True,
    )
    return candidates[: max(0, max_posts)]


def build_candidate(
    *,
    raw_note: dict[str, Any],
    advisor_name: str,
    school_name: str,
    advisor_aliases: list[str],
    keywords: list[str],
    required_keywords: list[str],
    excluded_keywords: list[str],
    recent_days: int,
    stale_days: int,
) -> dict[str, Any] | None:
    text = main_post_text(raw_note)
    excluded_hits = matched_keywords(text, excluded_keywords)
    if excluded_hits:
        return None
    keyword_hits = matched_keywords(text, keywords)
    required_hits = matched_keywords(text, required_keywords)
    if not required_hits:
        return None

    target_match_type, alias_hits = target_match(
        raw_note=raw_note,
        advisor_name=advisor_name,
        school_name=school_name,
        advisor_aliases=advisor_aliases,
    )
    if not target_match_type:
        return None

    raw_published_at = raw_note.get("published_at")
    published_dt = parse_datetime(raw_published_at)
    published_at = format_datetime(published_dt) if published_dt else raw_published_at
    date_status, days_old = date_freshness(published_dt, recent_days=recent_days, stale_days=stale_days)
    score = selection_score(
        target_match_type=target_match_type,
        keyword_count=len(keyword_hits),
        date_status=date_status,
        likes=int(raw_note.get("likes") or 0),
    )
    return {
        "source": "xiaohongshu",
        "note_id": str(raw_note.get("note_id", "")),
        "url": str(raw_note.get("url", "")),
        "query": str(raw_note.get("query", "")),
        "title": str(raw_note.get("title", "")),
        "content": str(raw_note.get("content", "")),
        "author_name": str(raw_note.get("author_name", "")),
        "likes": int(raw_note.get("likes") or 0),
        "comment_count": int(raw_note.get("comment_count") or 0),
        "published_at": published_at,
        "raw_published_at": raw_published_at,
        "collected_at": raw_note.get("collected_at"),
        "matched_keywords": keyword_hits,
        "required_keyword_hits": required_hits,
        "target_match_type": target_match_type,
        "matched_aliases": alias_hits,
        "date_status": date_status,
        "days_old": days_old,
        "selection_score": score,
        "note_type": raw_note.get("note_type", ""),
    }


def summarize_recruitment_posts(
    *,
    client: Anthropic | OpenAI,
    settings: dict[str, Any],
    candidates: list[dict[str, Any]],
    advisor_name: str,
    school_name: str,
    advisor_aliases: list[str],
) -> dict[str, Any]:
    payload = {
        "target": {
            "advisor_name": advisor_name,
            "school_name": school_name,
            "aliases": advisor_aliases,
        },
        "scope": "public_xiaohongshu_main_posts_only_no_comments",
        "instruction": (
            "下面 posts 已经过规则过滤并按发布时间倒序截取最多4条。"
            "请直接按照 system message 的 answer template 汇总。"
            "内容判断交给你；程序不会再用规则补方向、补岗位或改写summary。"
        ),
        "posts": [
            {
                "note_id": item.get("note_id", ""),
                "title": item.get("title", ""),
                "content": item.get("content", ""),
                "author_name": item.get("author_name", ""),
                "url": item.get("url", ""),
                "query": item.get("query", ""),
                "published_at": item.get("published_at"),
                "date_status": item.get("date_status", ""),
                "matched_keywords": item.get("matched_keywords", []),
                "target_match_type": item.get("target_match_type", ""),
            }
            for item in candidates[:4]
        ],
    }
    provider = str(_config(settings, "llm.provider", "openai")).lower()
    model = str(_config(settings, "llm.model", "deepseek-v4-pro"))
    temperature = float(_config(settings, "llm.temperature", 0))
    timeout_seconds = float(_config(settings, "llm.timeout_seconds", 90))
    max_tokens = _config(settings, "llm.max_tokens", None)

    parsed = call_recruitment_summary_llm(
        client=client,
        provider=provider,
        model=model,
        temperature=temperature,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
        payload=payload,
        settings=settings,
    )
    return finalize_summary(
        parsed,
        advisor_name=advisor_name,
        school_name=school_name,
        advisor_aliases=advisor_aliases,
        candidates=candidates,
        llm_model=str(_config(settings, "llm.model", "deepseek-v4-pro")),
    )


def call_recruitment_summary_llm(
    *,
    client: Anthropic | OpenAI,
    provider: str,
    model: str,
    temperature: float,
    timeout_seconds: float,
    max_tokens: Any,
    payload: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    if provider == "anthropic":
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": int(max_tokens) if max_tokens is not None else 8000,
            "temperature": temperature,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            "tools": [
                {
                    "name": "write_recruitment_summary",
                    "description": "Return the structured Xiaohongshu recruitment summary.",
                    "input_schema": RECRUITMENT_SUMMARY_TOOL_SCHEMA,
                }
            ],
            "tool_choice": {"type": "tool", "name": "write_recruitment_summary"},
        }
        response = call_anthropic_with_alarm(client, timeout_seconds=timeout_seconds, kwargs=kwargs)
        parsed = parse_anthropic_summary_response(response)
    else:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "stream": False,
            "temperature": temperature,
            "timeout": timeout_seconds,
            "response_format": {"type": "json_object"},
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = int(max_tokens)
        reasoning_effort = _config(settings, "llm.reasoning_effort", None)
        if reasoning_effort:
            kwargs["reasoning_effort"] = str(reasoning_effort)
        if bool(_config(settings, "llm.thinking", False)):
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

        response = call_llm_with_alarm(client, timeout_seconds=timeout_seconds, kwargs=kwargs)
        content = response.choices[0].message.content

        if not content:
            raise ValueError("LLM returned empty recruitment summary")
        try:
            parsed = json.loads(extract_json_object(content))
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM returned invalid recruitment summary JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("LLM recruitment summary must be a JSON object")
    return parsed


def parse_anthropic_summary_response(response: Any) -> dict[str, Any]:
    text_parts = []
    for block in getattr(response, "content", []) or []:
        block_type = getattr(block, "type", None)
        if block_type == "tool_use":
            tool_input = getattr(block, "input", None)
            if isinstance(tool_input, dict):
                return tool_input
        text = getattr(block, "text", None)
        if text:
            text_parts.append(str(text))

    content = "\n".join(text_parts).strip()
    if not content:
        raise ValueError("LLM returned empty recruitment summary")
    try:
        parsed = json.loads(extract_json_object(content))
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned invalid recruitment summary JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("LLM recruitment summary must be a JSON object")
    return parsed


def extract_json_object(content: str) -> str:
    """Return the first JSON object from an LLM response."""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
    if text.startswith("{") and text.endswith("}"):
        return text

    start = text.find("{")
    if start < 0:
        raise json.JSONDecodeError("No JSON object found", content, 0)

    in_string = False
    escaped = False
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    raise json.JSONDecodeError("Unterminated JSON object", content, start)


def call_llm_with_alarm(client: OpenAI, *, timeout_seconds: float, kwargs: dict[str, Any]) -> Any:
    def _handle_timeout(_signum: int, _frame: Any) -> None:
        raise TimeoutError(f"LLM request exceeded {timeout_seconds:.0f}s")

    previous = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, max(1.0, timeout_seconds))
    try:
        return client.chat.completions.create(**kwargs)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def call_anthropic_with_alarm(client: Anthropic, *, timeout_seconds: float, kwargs: dict[str, Any]) -> Any:
    def _handle_timeout(_signum: int, _frame: Any) -> None:
        raise TimeoutError(f"Anthropic request exceeded {timeout_seconds:.0f}s")

    previous = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, max(1.0, timeout_seconds))
    try:
        return client.messages.create(**kwargs)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def finalize_summary(
    summary: dict[str, Any],
    *,
    advisor_name: str,
    school_name: str,
    advisor_aliases: list[str],
    candidates: list[dict[str, Any]],
    llm_model: str,
) -> dict[str, Any]:
    summary["advisor_name"] = advisor_name
    summary["school_name"] = school_name
    summary["advisor_aliases"] = advisor_aliases
    summary["source"] = "xiaohongshu"
    summary["source_scope"] = "main_posts_only_no_comments"
    summary["source_post_count"] = len(candidates)
    summary["source_note_ids"] = [str(item.get("note_id", "")) for item in candidates if item.get("note_id")]
    summary["generated_at"] = utc_now_iso()
    summary["llm_call_count"] = 1
    summary["llm_model"] = llm_model
    summary["safety_policy"] = "recruitment_facts_only_no_subjective_advisor_evaluation"
    normalize_structured_summary_fields(summary, candidates)
    summary["summary"] = str(summary.get("summary") or "")

    limitations = summary.get("limitations")
    if not isinstance(limitations, list):
        limitations = []
    required_limitation = "仅基于公开小红书主贴标题和正文；未使用评论区；不构成对导师或课题组的评价。"
    if required_limitation not in limitations:
        limitations.append(required_limitation)
    summary["limitations"] = limitations
    return summary


def normalize_structured_summary_fields(summary: dict[str, Any], candidates: list[dict[str, Any]]) -> None:
    summary["positions"] = normalize_object_list(summary.get("positions"))
    summary["directions"] = normalize_object_list(summary.get("directions"))
    summary["requirements"] = normalize_object_list(summary.get("requirements"))
    summary["application_methods"] = normalize_object_list(summary.get("application_methods"))
    summary["timeline"] = normalize_object_list(summary.get("timeline"))
    summary["source_posts"] = normalize_object_list(summary.get("source_posts"))

    summary["positions"] = normalize_position_items(summary.get("positions"))

    if not isinstance(summary.get("directions"), list):
        summary["directions"] = []

    if not isinstance(summary.get("requirements"), list):
        summary["requirements"] = []

    if not isinstance(summary.get("application_methods"), list):
        summary["application_methods"] = []

    if not isinstance(summary.get("timeline"), list):
        summary["timeline"] = []

    if not isinstance(summary.get("source_posts"), list):
        summary["source_posts"] = []
    if not summary["source_posts"]:
        summary["source_posts"] = source_post_metadata(candidates)

    if not summary.get("latest_recruitment_post_published_at"):
        summary["latest_recruitment_post_published_at"] = latest_published_at(candidates)


def normalize_object_list(value: Any) -> list[dict[str, Any]] | Any:
    if not isinstance(value, list):
        return value
    normalized = []
    for item in value:
        if not isinstance(item, dict):
            continue
        if len(item) == 1 and isinstance(item.get("reason"), str):
            try:
                parsed = json.loads(extract_json_object(item["reason"]))
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                normalized.append(parsed)
                continue
        normalized.append(item)
    return normalized


def normalize_position_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized.append(dict(item))
    return normalized


def source_post_metadata(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "note_id": str(item.get("note_id", "")),
            "title": str(item.get("title", "")),
            "url": str(item.get("url", "")),
            "published_at": item.get("published_at"),
            "relation_to_target": display_relation(str(item.get("target_match_type", ""))),
            "time_sensitivity": display_time_sensitivity(str(item.get("date_status", ""))),
            "extracted_facts": [],
        }
        for item in candidates
    ]


def display_relation(value: str) -> str:
    return {
        "explicit_advisor": "explicit",
        "alias_with_context": "alias",
        "lab_member_post": "lab_member",
    }.get(value, "uncertain")


def display_time_sensitivity(value: str) -> str:
    return {
        "recent": "current",
        "older": "possibly_stale",
        "stale": "possibly_stale",
    }.get(value, "unknown")


def empty_summary(*, advisor_name: str, school_name: str, advisor_aliases: list[str]) -> dict[str, Any]:
    return {
        "advisor_name": advisor_name,
        "school_name": school_name,
        "advisor_aliases": advisor_aliases,
        "source": "xiaohongshu",
        "source_scope": "main_posts_only_no_comments",
        "recruitment_status": "not_found",
        "summary": "未在本次抓取到的公开小红书主贴中发现可整理的招生信息。",
        "latest_recruitment_post_published_at": None,
        "directions": [],
        "positions": [],
        "requirements": [],
        "application_methods": [],
        "timeline": [],
        "source_posts": [],
        "limitations": ["仅基于公开小红书主贴标题和正文；未使用评论区；不构成对导师或课题组的评价。"],
        "source_post_count": 0,
        "source_note_ids": [],
        "generated_at": utc_now_iso(),
        "llm_call_count": 0,
        "safety_policy": "recruitment_facts_only_no_subjective_advisor_evaluation",
    }


def latest_published_at(candidates: list[dict[str, Any]]) -> str | None:
    values = [str(item.get("published_at")) for item in candidates if item.get("published_at")]
    return max(values) if values else None


def date_sort_key(value: Any) -> float:
    parsed = parse_datetime(value)
    return parsed.timestamp() if parsed else 0.0


def recruitment_keywords(settings: dict[str, Any]) -> list[str]:
    configured = _config(settings, "recruitment.keywords", None)
    if isinstance(configured, list) and configured:
        return [str(item) for item in configured if str(item).strip()]
    return list(DEFAULT_RECRUITMENT_KEYWORDS)


def required_recruitment_keywords(settings: dict[str, Any]) -> list[str]:
    configured = _config(settings, "recruitment.required_keywords", None)
    if isinstance(configured, list) and configured:
        return [str(item) for item in configured if str(item).strip()]
    return list(DEFAULT_REQUIRED_RECRUITMENT_KEYWORDS)


def excluded_post_keywords(settings: dict[str, Any]) -> list[str]:
    configured = _config(settings, "recruitment.excluded_keywords", None)
    if isinstance(configured, list):
        return [str(item) for item in configured if str(item).strip()]
    return list(DEFAULT_EXCLUDED_POST_KEYWORDS)


def main_post_text(raw_note: dict[str, Any]) -> str:
    parts = [
        str(raw_note.get("title", "")),
        str(raw_note.get("content", "")),
        str(raw_note.get("author_name", "")),
    ]
    return "\n".join(part for part in parts if part)


def matched_keywords(text: str, keywords: list[str]) -> list[str]:
    hits = []
    for keyword in keywords:
        if keyword_in_text(keyword, text):
            hits.append(keyword)
    return hits


def keyword_in_text(keyword: str, text: str) -> bool:
    if not keyword:
        return False
    if keyword.isascii() and keyword.replace("_", "").isalnum():
        return re.search(rf"(?<![A-Za-z0-9_]){re.escape(keyword)}(?![A-Za-z0-9_])", text, re.IGNORECASE) is not None
    return keyword.casefold() in text.casefold()


def target_match(
    *,
    raw_note: dict[str, Any],
    advisor_name: str,
    school_name: str,
    advisor_aliases: list[str],
) -> tuple[str, list[str]]:
    text = main_post_text(raw_note)
    aliases = normalize_aliases(advisor_aliases)
    alias_hits = [alias for alias in aliases if alias_in_text(alias, text)]

    # 1. 导师全名直接出现
    if advisor_name and advisor_name in text:
        return "explicit_advisor", alias_hits

    # 2. 别名出现且有招生上下文
    if alias_hits and has_recruitment_context(text, school_name):
        return "alias_with_context", alias_hits

    # 3. 课题组成员代发：学校名 + 招生关键词 + 课题组关联词
    if school_name and school_name in text:
        if has_lab_affiliation_signal(text, advisor_name, aliases):
            return "lab_member_post", []

    return "", alias_hits


def has_recruitment_context(text: str, school_name: str) -> bool:
    if school_name and school_name in text:
        return True
    context_keywords = ("课题组", "实验室", "导师", "老师", "教授", "招生", "招募", "博士", "硕士", "RA", "实习生")
    return any(keyword_in_text(keyword, text) for keyword in context_keywords)


def has_lab_affiliation_signal(text: str, advisor_name: str, advisor_aliases: list[str]) -> bool:
    """
    检测帖子是否为课题组成员代发招生信息
    规则：
    1. 包含"课题组"/"实验室"/"Lab"等关键词
    2. 包含"招生"/"招收"/"招募"等招生关键词
    3. 提到导师姓名、导师姓氏称谓、或手工配置的目标别名/实验室名
    """
    # 注意：这里的Lab要作为独立词匹配，避免误匹配"Laboratory"等
    lab_keywords = ("课题组", "实验室", "研究组", "研究室")
    recruitment_keywords = ("招生", "招收", "招募", "助理教授招生", "博士招生", "硕士招生", "RA招募")

    # 检查是否包含Lab（作为独立词或词组的一部分）
    has_lab_word = any(keyword_in_text(keyword, text) for keyword in lab_keywords)
    # 检查是否包含"Lab"（英文实验室名称，如RethinkLab）
    has_lab_english = "Lab" in text or "lab" in text.lower()
    has_lab = has_lab_word or has_lab_english

    has_recruitment = any(keyword_in_text(keyword, text) for keyword in recruitment_keywords)

    # 基本条件：有实验室关键词 + 有招生关键词
    if not (has_lab and has_recruitment):
        return False

    if advisor_name:
        advisor_surname = advisor_name[0] if len(advisor_name) > 0 else ""
        if advisor_surname and any(
            pattern in text
            for pattern in [
                f"{advisor_surname}老师",
                f"{advisor_surname}教授",
                f"{advisor_surname}课题组",
                f"{advisor_name}",
            ]
        ):
            return True

    return any(alias_in_text(alias, text) for alias in advisor_aliases)


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return timestamp_to_datetime(float(value))
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return timestamp_to_datetime(float(text))
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def timestamp_to_datetime(value: float) -> datetime | None:
    if value <= 0:
        return None
    if value > 10_000_000_000:
        value = value / 1000
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def date_freshness(
    published_at: datetime | None,
    *,
    recent_days: int,
    stale_days: int,
) -> tuple[str, int | None]:
    if published_at is None:
        return "unknown_date", None
    now = datetime.now(timezone.utc)
    days_old = max(0, int((now - published_at).total_seconds() // 86400))
    if days_old <= recent_days:
        return "recent", days_old
    if days_old <= stale_days:
        return "older", days_old
    return "stale", days_old


def format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def selection_score(*, target_match_type: str, keyword_count: int, date_status: str, likes: int) -> int:
    target_scores = {
        "explicit_advisor": 50,
        "alias_with_context": 40,
        "lab_member_post": 35,  # 课题组成员代发，优先级略低于别名但高于无关帖子
    }
    date_scores = {
        "recent": 30,
        "older": 15,
        "unknown_date": 8,
        "stale": 0,
    }
    return (
        target_scores.get(target_match_type, 0)
        + min(keyword_count, 5) * 6
        + date_scores.get(date_status, 0)
        + min(likes, 100) // 20
    )


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record, ensure_ascii=False, separators=(",", ":")) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def write_json(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def _config(config: dict[str, Any], dotted_key: str, default: Any) -> Any:
    current: Any = config
    for key in dotted_key.split("."):
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


if __name__ == "__main__":
    main()
