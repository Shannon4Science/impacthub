"""Conversational advisor recommendation — tool-calling agent.

The LLM is given a set of tools (search_advisors / lookup_advisor /
get_advisor_mentions / find_colleges / web_search) and decides on its own
which to call and when. The server runs an agent loop:

  LLM → (optional) tool call(s) → server executes → LLM sees result →
  ... until LLM produces a final assistant message with no more tool calls.

Compared to the previous criteria-driven pipeline, this:
  * Handles entity queries naturally ("戴国浩老师怎么样")
  * Combines multi-step reasoning ("先查这个人，然后找同方向的同事")
  * Falls back to web search when DB doesn't have the info
"""

import asyncio
import json
import logging
import re
from typing import Any

import httpx
from sqlalchemy import or_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LLM_API_BASE, LLM_API_KEY, LLM_BUZZ_MODEL, LLM_FALLBACK_MODEL
from app.database import async_session
from app.models import (
    Advisor, AdvisorCollege, AdvisorMention, AdvisorSchool,
)

# gpt-5-mini's tool-calling on this proxy is unreliable (sometimes dumps tool
# arg JSON as plain text content), so we use gpt-5 for the whole agent loop.
# Speed-up comes from running multiple tool calls *in parallel* per turn.
AGENT_MODEL = LLM_BUZZ_MODEL  # gpt-5

logger = logging.getLogger(__name__)


# ──────────────────────────── Tool definitions (OpenAI schema) ────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_advisors",
            "description": (
                "Filter the advisor database by criteria. Use when the user "
                "describes what kind of advisor they want (direction / school "
                "tier / location / personality traits) without naming a specific "
                "person. Returns a list of brief candidate cards."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "direction_keywords": {
                        "type": "array", "items": {"type": "string"},
                        "description": "学院/方向关键词（按学院名 LIKE 匹配）, 如 ['人工智能','计算机','信息']",
                    },
                    "school_tier": {
                        "type": "string", "enum": ["985", "211", "double_first_class", "any"],
                        "description": "学校层次。default: any",
                    },
                    "provinces": {
                        "type": "array", "items": {"type": "string"},
                        "description": "省份，如 ['北京','上海']",
                    },
                    "school_names": {
                        "type": "array", "items": {"type": "string"},
                        "description": "具体学校名（精确匹配），如 ['上海交通大学']",
                    },
                    "must_have_mention": {
                        "type": "boolean",
                        "description": "True 时只返回有公众号/小红书 mention 的导师",
                    },
                    "research_areas": {
                        "type": "array", "items": {"type": "string"},
                        "description": "研究方向关键词（按 advisor.research_areas / advisor.bio 匹配），如 ['具身智能','大模型']",
                    },
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 30},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_advisor",
            "description": (
                "Find a specific advisor by name. Use whenever the user mentions "
                "a particular person ('唐杰怎么样', '戴国浩老师'). Returns full "
                "record including bio, research_areas, education, honors and "
                "embedded mentions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "导师中文姓名（2-4 字）"},
                    "school_name": {
                        "type": "string",
                        "description": "学校全名，用于消歧（同名时必填）",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_advisor_mentions",
            "description": "Pull all 公众号/小红书 mentions for one advisor.",
            "parameters": {
                "type": "object",
                "properties": {"advisor_id": {"type": "integer"}},
                "required": ["advisor_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_colleges",
            "description": (
                "Find colleges in a school by keyword, e.g. ('南京大学', '计算机') "
                "→ list of (id, name, advisor_count). Helpful when answering "
                "'X 大学的 Y 学院有哪些老师'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "school_name": {"type": "string"},
                    "keyword": {"type": "string", "description": "学院名子串"},
                },
                "required": ["school_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Last-resort web search for facts not in the DB (e.g. 某老师最新动态、"
                "某学院招生政策). Use sparingly. Returns short summaries."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
]


# ──────────────────────────── Tool implementations ────────────────────────────

VALID_TIERS = {"985", "211", "double_first_class", "any"}


async def tool_search_advisors(db: AsyncSession, args: dict) -> dict:
    direction_kws = args.get("direction_keywords") or []
    school_tier = args.get("school_tier") or "any"
    provinces = args.get("provinces") or []
    school_names = args.get("school_names") or []
    must_have_mention = bool(args.get("must_have_mention"))
    research_areas = args.get("research_areas") or []
    limit = int(args.get("limit") or 10)
    limit = max(1, min(30, limit))

    stmt = (
        select(Advisor, AdvisorCollege, AdvisorSchool)
        .join(AdvisorCollege, AdvisorCollege.id == Advisor.college_id)
        .join(AdvisorSchool, AdvisorSchool.id == Advisor.school_id)
    )
    if school_tier == "985":
        stmt = stmt.where(AdvisorSchool.is_985 == True)  # noqa: E712
    elif school_tier == "211":
        stmt = stmt.where(AdvisorSchool.is_211 == True)  # noqa: E712
    elif school_tier == "double_first_class":
        stmt = stmt.where(AdvisorSchool.is_double_first_class == True)  # noqa: E712
    if provinces:
        stmt = stmt.where(AdvisorSchool.province.in_(provinces))
    if school_names:
        stmt = stmt.where(AdvisorSchool.name.in_(school_names))
    if direction_kws:
        stmt = stmt.where(or_(*[AdvisorCollege.name.like(f"%{k}%") for k in direction_kws]))

    rows = (await db.execute(stmt.limit(500))).all()

    # Mentions count for ranking
    advisor_ids = [a.id for a, _, _ in rows]
    mentions_by: dict[int, int] = {}
    if advisor_ids:
        mr = (await db.execute(
            select(AdvisorMention.advisor_id, func.count(AdvisorMention.id))
            .where(AdvisorMention.advisor_id.in_(advisor_ids))
            .group_by(AdvisorMention.advisor_id)
        )).all()
        mentions_by = {aid: int(n) for aid, n in mr}

    # Score (research_areas is a SOFT boost, not a hard filter — many advisors
    # are still at stub-level with empty bio/research_areas, and we shouldn't
    # exclude them just because the detail crawl hasn't reached them yet.)
    scored = []
    for a, c, s in rows:
        n_mentions = mentions_by.get(a.id, 0)
        if must_have_mention and n_mentions == 0:
            continue
        score = 0.0
        if s.is_985: score += 20
        elif s.is_211: score += 10
        elif s.is_double_first_class: score += 5
        if direction_kws:
            score += sum(8 for k in direction_kws if k in c.name)
        if research_areas and (a.research_areas or a.bio):
            haystack = " ".join([a.bio or "", " ".join(a.research_areas or [])]).lower()
            hits = sum(1 for k in research_areas if k.lower() in haystack)
            # Strong boost if research_areas match — these candidates are highest quality
            score += hits * 15
        score += min(n_mentions, 5) * 6
        if a.h_index > 0:
            score += min(a.h_index, 50) / 5
        if a.crawl_status == "detailed":
            score += 5
        scored.append((score, a, c, s, n_mentions))
    scored.sort(key=lambda x: -x[0])
    top = scored[:limit]

    return {
        "total_matched": len(scored),
        "returned": len(top),
        "advisors": [
            {
                "advisor_id": a.id, "name": a.name,
                "title": a.title or "",
                "school": s.name, "school_short": s.short_name,
                "is_985": s.is_985, "is_211": s.is_211,
                "province": s.province,
                "college": c.name,
                "research_areas": a.research_areas or [],
                "h_index": a.h_index,
                "honors": a.honors or [],
                "n_mentions": n_mentions,
                "homepage": a.homepage_url or "",
            }
            for _, a, c, s, n_mentions in top
        ],
    }


async def tool_lookup_advisor(db: AsyncSession, args: dict) -> dict:
    name = (args.get("name") or "").strip()
    school_name = (args.get("school_name") or "").strip()
    if not name:
        return {"error": "name is required"}

    stmt = select(Advisor, AdvisorCollege, AdvisorSchool) \
        .join(AdvisorCollege, AdvisorCollege.id == Advisor.college_id) \
        .join(AdvisorSchool, AdvisorSchool.id == Advisor.school_id) \
        .where(Advisor.name == name)
    if school_name:
        stmt = stmt.where(AdvisorSchool.name == school_name)
    rows = (await db.execute(stmt)).all()

    if len(rows) == 0:
        # Fallback: maybe there's an unlinked mention with this name (advisor not yet crawled)
        pending = (await db.execute(
            select(AdvisorMention)
            .where(
                AdvisorMention.advisor_id == 0,
                AdvisorMention.pending_advisor_name == name,
                *(AdvisorMention.pending_school_name == school_name,) if school_name else (),
            )
            .limit(10)
        )).scalars().all()
        if pending:
            return {
                "found": False,
                "reason": "advisor not yet in DB but has unlinked mentions",
                "pending_mentions": [
                    {
                        "title": m.title, "url": m.url, "snippet": m.snippet,
                        "source": m.source, "source_account": m.source_account,
                        "tags": m.tags or [], "sentiment": m.sentiment,
                        "pending_school": m.pending_school_name,
                    }
                    for m in pending
                ],
            }
        return {"found": False, "reason": "no advisor with this name"}
    if len(rows) > 1 and not school_name:
        return {
            "found": False, "ambiguous": True,
            "candidates": [
                {"advisor_id": a.id, "name": a.name, "school": s.name, "college": c.name}
                for a, c, s in rows
            ],
        }
    a, c, s = rows[0]
    # Pull mentions
    ms = (await db.execute(
        select(AdvisorMention).where(AdvisorMention.advisor_id == a.id)
    )).scalars().all()
    return {
        "found": True,
        "advisor": {
            "advisor_id": a.id, "name": a.name, "title": a.title or "",
            "school": s.name, "school_short": s.short_name, "province": s.province,
            "is_985": s.is_985, "is_211": s.is_211,
            "college": c.name, "discipline": c.discipline_category,
            "homepage": a.homepage_url or "",
            "email": a.email or "", "office": a.office or "",
            "research_areas": a.research_areas or [],
            "bio": a.bio or "",
            "education": a.education or [],
            "honors": a.honors or [],
            "is_doctoral_supervisor": a.is_doctoral_supervisor,
            "h_index": a.h_index,
            "recruiting_intent": a.recruiting_intent or "",
            "crawl_status": a.crawl_status,
        },
        "mentions": [
            {
                "title": m.title, "url": m.url, "snippet": m.snippet,
                "source": m.source, "source_account": m.source_account,
                "tags": m.tags or [], "sentiment": m.sentiment,
                "published_at": m.published_at.isoformat() if m.published_at else None,
            }
            for m in ms
        ],
    }


async def tool_get_advisor_mentions(db: AsyncSession, args: dict) -> dict:
    aid = args.get("advisor_id")
    if not isinstance(aid, int):
        return {"error": "advisor_id must be an integer"}
    ms = (await db.execute(
        select(AdvisorMention).where(AdvisorMention.advisor_id == aid)
    )).scalars().all()
    return {
        "advisor_id": aid, "count": len(ms),
        "mentions": [
            {
                "title": m.title, "url": m.url, "snippet": m.snippet,
                "source": m.source, "source_account": m.source_account,
                "tags": m.tags or [], "sentiment": m.sentiment,
                "published_at": m.published_at.isoformat() if m.published_at else None,
            }
            for m in ms
        ],
    }


async def tool_find_colleges(db: AsyncSession, args: dict) -> dict:
    sn = (args.get("school_name") or "").strip()
    kw = (args.get("keyword") or "").strip()
    if not sn:
        return {"error": "school_name required"}
    school = (await db.execute(
        select(AdvisorSchool).where(
            or_(AdvisorSchool.name == sn, AdvisorSchool.short_name == sn)
        )
    )).scalars().first()
    if not school:
        return {"error": f"school '{sn}' not found in DB"}
    stmt = select(AdvisorCollege).where(AdvisorCollege.school_id == school.id)
    if kw:
        stmt = stmt.where(AdvisorCollege.name.like(f"%{kw}%"))
    cs = (await db.execute(stmt)).scalars().all()
    return {
        "school": school.name, "school_id": school.id,
        "colleges": [
            {"college_id": c.id, "name": c.name, "discipline": c.discipline_category,
             "advisor_count": c.advisor_count or 0, "homepage": c.homepage_url}
            for c in cs
        ],
    }


async def tool_web_search(client: httpx.AsyncClient, args: dict) -> dict:
    """Use the LLM provider's Responses API with web_search_preview tool."""
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "query required"}
    try:
        resp = await client.post(
            f"{LLM_API_BASE}/responses",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": LLM_BUZZ_MODEL,
                "tools": [{"type": "web_search_preview"}],
                "input": f"请基于联网搜索，简洁回答：{query}\n要求：3-5 句中文，并列出 2-3 条来源 URL。",
                "max_output_tokens": 4000,
            },
            timeout=240,
        )
        if resp.status_code != 200:
            return {"error": f"web_search HTTP {resp.status_code}"}
        data = resp.json()
        text = ""
        sources: list[str] = []
        for item in data.get("output", []):
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") == "output_text":
                        text = c.get("text", "")
                        for ann in c.get("annotations", []):
                            if ann.get("type") == "url_citation":
                                u = ann.get("url", "")
                                if u and u not in sources:
                                    sources.append(u)
        return {"summary": text[:2000], "sources": sources[:5]}
    except Exception as e:
        return {"error": f"web_search failed: {e}"}


# ──────────────────────────── Agent loop ────────────────────────────

SYSTEM_PROMPT = """你是 ImpactHub 保研顾问助手。基于工具回答问题，**严禁瞎编**。

### 数据库
ImpactHub 收录中国 147 所双一流（含全部 985/211）的导师，约 3700 位老师入库。
导师字段：姓名/职称/学院/学校/research_areas/bio/email/office/honors/education/h_index/招生意愿/主页 URL。
公众号 mentions：鹿鸣观山海、保研论坛、鸡哥保研、保研er、强基保研之家（共 ~30 条）。

### 工具规则（强制 + 高效）
**尽量在一轮里把所有 tool 一次发出来并行执行**，不要一个接一个串行（每轮 LLM 等待 15-30s，串行很慢）。

**关键：意图识别**（必须严格遵守）

1. **特定老师查询**（"X 老师怎么样"/"介绍下 X"/"X 是谁"）→ 只调 `lookup_advisor(X)`，**绝对不要**再调 `search_advisors` 推荐"相似老师"。回复也只围绕这一位。

2. **新一类老师查询**（"找做大模型的"/"推荐 985 老师"）→ 调 `search_advisors`，不要 lookup 单人。

3. **基于已推荐池的 refine / follow-up**（最常见，必须识别！）：
   用户在已经看到推荐后追问"能推实习的吗 / 不太 push 的呢 / 筛个适合保研的 / 这些里你最推荐谁"等 → **绝不要重新调 `search_advisors`**！直接从对话历史里之前推过的老师中筛选/重排回答。
   - 看上一条 assistant 消息里列出的老师姓名，**保持同一批人**
   - 在已知信息基础上重新讲讲为什么 X 适合"推实习" / "氛围宽松"
   - 如果之前的列表里**确实没有**符合新条件的，再考虑调一次 search 补充，但首先要承认"上次推荐里这批人不太符合，需要扩展搜索"

4. **明确要"还有谁/再推几个"** → 这时才调 search 找新的

具体工具：
- `lookup_advisor(name)` — 自带 mentions，**不用**再调 get_advisor_mentions
- `search_advisors`：
  - 优先把 `direction_keywords` 和 `research_areas` 都填上
  - **不要默认带 must_have_mention=true** — 库里 mentions 量小
  - 第一次返回 0 → 用更宽松条件重试（去掉 must_have_mention / 放宽 keywords）
- `find_colleges` — 用户问"X 校的 Y 学院"
- `web_search` — DB 之外的内容
- 如果用户描述一类老师且 search 拿到 1-2 个高匹配 → 同一轮里并行 `lookup_advisor` 拿详情

### 引用规则（极重要）
**每个事实末尾标来源标签**，且来源标签必须对应**真正调用过的工具**：
- `[主页]` — 来自 `lookup_advisor` 返回的 advisor.bio / research_areas / honors / education / homepage 等字段
- `[公众号: 账号名]` — 来自 mentions 字段，账号名用 source_account
- `[联网]` — 来自 `web_search` 返回的 summary / sources

**严禁**：
- 没调 `web_search` 不能写 `[联网]`
- 不能编造 URL（如 BYR BBS / 导师评价网等）
- 不能给"通用建议"+`[联网]` 标签 — 这是幻觉
- 编造来源比"暂无数据"更糟糕

### 回复风格
- 中文，3-8 句话
- 列推荐时按顺序：姓名 + 学校/学院 + 1-2 句方向匹配理由 + 公众号摘抄原句（如有）
- 工具确实没数据 → 直接说"库里目前覆盖到的是 X，更多老师待扩充"，主动追问省份/层次/具体细分方向
- 关键引用（公众号原文 / 老师主页）文末 markdown 链接列出：`参考：[标题](URL)`
- 老师的公众号摘抄优先**放原句**不要总结
"""


def _parse_tool_args(raw: str) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return {}


async def _dispatch_tool(
    db: AsyncSession, client: httpx.AsyncClient, name: str, args: dict
) -> dict:
    if name == "search_advisors":
        return await tool_search_advisors(db, args)
    if name == "lookup_advisor":
        return await tool_lookup_advisor(db, args)
    if name == "get_advisor_mentions":
        return await tool_get_advisor_mentions(db, args)
    if name == "find_colleges":
        return await tool_find_colleges(db, args)
    if name == "web_search":
        return await tool_web_search(client, args)
    return {"error": f"unknown tool: {name}"}


MAX_AGENT_TURNS = 5


async def _stream_llm_chat(
    client: httpx.AsyncClient,
    chat_msgs: list[dict],
    model: str,
    *,
    with_tools: bool,
    max_tokens: int,
    reasoning_effort: str = "minimal",
):
    """Stream a chat completion. Yields delta dicts:
        {"content": str}                # text token chunk
        {"tool_call_chunk": {"index", "id", "name", "args_chunk"}}
    Plus a final {"done": message_dict} where message_dict has the full
    assembled assistant message (content + tool_calls).
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": chat_msgs,
        "max_completion_tokens": max_tokens,
        "stream": True,
        # gpt-5 reasoning controls — minimal / low / medium / high.
        # minimal: skip reasoning entirely → 5-10× faster for simple tool routing.
        "reasoning_effort": reasoning_effort,
    }
    if with_tools:
        payload["tools"] = TOOLS
        payload["tool_choice"] = "auto"

    accumulated_content: list[str] = []
    # tool_calls accumulator: index -> partial dict
    tool_partials: dict[int, dict] = {}

    try:
        async with client.stream(
            "POST",
            f"{LLM_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json=payload,
            timeout=300,
        ) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode(errors="replace")
                logger.warning("Stream LLM HTTP %d: %s", resp.status_code, body[:200])
                yield {"done": None}
                return
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    parsed = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = parsed.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                # Text content chunk
                if "content" in delta and delta["content"]:
                    accumulated_content.append(delta["content"])
                    yield {"content": delta["content"]}
                # Tool call chunks (each call's args streamed in pieces)
                for tc_chunk in delta.get("tool_calls") or []:
                    idx = tc_chunk.get("index", 0)
                    bucket = tool_partials.setdefault(idx, {"id": "", "function": {"name": "", "arguments": ""}})
                    if "id" in tc_chunk and tc_chunk["id"]:
                        bucket["id"] = tc_chunk["id"]
                    fn = tc_chunk.get("function") or {}
                    if fn.get("name"):
                        bucket["function"]["name"] = fn["name"]
                    if fn.get("arguments"):
                        bucket["function"]["arguments"] += fn["arguments"]
                    yield {"tool_call_chunk": {
                        "index": idx,
                        "name": bucket["function"]["name"],
                        # Don't yield partial args to save bandwidth — we yield once on done
                    }}
    except Exception as e:
        logger.warning("Stream LLM call failed: %s", e)
        yield {"done": None}
        return

    # Assemble final message
    content = "".join(accumulated_content)
    tool_calls = []
    for idx in sorted(tool_partials.keys()):
        bucket = tool_partials[idx]
        if bucket["function"]["name"]:
            tool_calls.append({
                "id": bucket["id"] or f"call_{idx}",
                "type": "function",
                "function": bucket["function"],
            })
    final = {"role": "assistant", "content": content}
    if tool_calls:
        final["tool_calls"] = tool_calls
    yield {"done": final}


async def _call_llm_chat(
    client: httpx.AsyncClient,
    chat_msgs: list[dict],
    model: str,
    *,
    with_tools: bool = True,
    max_tokens: int = 6000,
    reasoning_effort: str = "minimal",
) -> dict | None:
    payload: dict[str, Any] = {
        "model": model,
        "messages": chat_msgs,
        "max_completion_tokens": max_tokens,
        "reasoning_effort": reasoning_effort,
    }
    if with_tools:
        payload["tools"] = TOOLS
        payload["tool_choice"] = "auto"
    try:
        resp = await client.post(
            f"{LLM_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json=payload,
            timeout=240,
        )
    except Exception as e:
        logger.warning("LLM call failed (%s): %s", model, e)
        return None
    if resp.status_code != 200:
        logger.warning("LLM HTTP %d (%s): %s", resp.status_code, model, resp.text[:200])
        return None
    return resp.json()["choices"][0]["message"]


async def _exec_one_tool(
    tc: dict,
    name: str,
    args: dict,
    client: httpx.AsyncClient,
) -> dict:
    """Run one tool with its own DB session so multiple tools can execute in parallel."""
    async with async_session() as db:
        try:
            return await _dispatch_tool(db, client, name, args)
        except Exception as e:
            return {"error": f"tool exec failed: {e}"}


async def chat_turn(db: AsyncSession, messages: list[dict]) -> dict:
    """One user message → up to MAX_AGENT_TURNS LLM/tool round-trips → final reply.

    Returns:
      {
        "reply": str,
        "recommendations": [advisor_card, ...],   # collected from tool results
        "advisor_profiles": [full profile, ...],   # from lookup_advisor
        "tool_trace": [{"name", "args", "result_summary"}, ...],
      }
    """
    chat_msgs: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in messages:
        chat_msgs.append({"role": m["role"], "content": m["content"]})

    recommendations: list[dict] = []
    advisor_profiles: list[dict] = []
    tool_trace: list[dict] = []

    async with httpx.AsyncClient() as client:
        for turn in range(MAX_AGENT_TURNS):
            # On the last turn, force a tool-less final reply
            is_last_turn = turn == MAX_AGENT_TURNS - 1
            # Tighter token budget on intermediate tool-calling turns reduces
            # reasoning time without affecting tool-call structure (which is
            # only a few hundred output tokens). Final reply gets full budget.
            tok_budget = 6000 if is_last_turn else 2500
            msg = await _call_llm_chat(
                client, chat_msgs, AGENT_MODEL,
                with_tools=not is_last_turn, max_tokens=tok_budget,
            )
            if msg is None:
                return {
                    "reply": "LLM 服务暂时不可用，再试一次？",
                    "recommendations": recommendations,
                    "advisor_profiles": advisor_profiles,
                    "tool_trace": tool_trace,
                }

            tool_calls = msg.get("tool_calls") or []
            content = msg.get("content") or ""

            assistant_msg = {"role": "assistant", "content": content}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            chat_msgs.append(assistant_msg)

            if not tool_calls:
                return {
                    "reply": content.strip(),
                    "recommendations": recommendations,
                    "advisor_profiles": advisor_profiles,
                    "tool_trace": tool_trace,
                }

            # Execute all tool calls IN PARALLEL — each gets its own DB session
            parsed_calls = []
            for tc in tool_calls:
                fn = tc.get("function") or {}
                tname = fn.get("name", "")
                targs = _parse_tool_args(fn.get("arguments") or "")
                tcall_id = tc.get("id", "")
                parsed_calls.append((tcall_id, tname, targs, tc))

            results = await asyncio.gather(*[
                _exec_one_tool(tc, tname, targs, client)
                for (_, tname, targs, tc) in parsed_calls
            ])

            for (tcall_id, tname, targs, _), tresult in zip(parsed_calls, results):
                tool_trace.append({
                    "name": tname, "args": targs,
                    "result_summary": _summarize_result(tname, tresult),
                })

                if tname == "search_advisors":
                    for a in tresult.get("advisors", []):
                        if not any(r.get("advisor_id") == a.get("advisor_id") for r in recommendations):
                            recommendations.append(a)
                elif tname == "lookup_advisor" and tresult.get("found"):
                    if not any(p.get("advisor_id") == tresult["advisor"]["advisor_id"] for p in advisor_profiles):
                        advisor_profiles.append({
                            **tresult["advisor"],
                            "mentions": tresult.get("mentions", []),
                        })

                payload = json.dumps(tresult, ensure_ascii=False)
                if len(payload) > 12000:
                    payload = payload[:12000] + "...<truncated>"
                chat_msgs.append({
                    "role": "tool",
                    "tool_call_id": tcall_id,
                    "content": payload,
                })

        # Hit MAX_AGENT_TURNS without final tool-less reply — force one
        final_msg = await _call_llm_chat(
            client, chat_msgs, AGENT_MODEL, with_tools=False, max_tokens=4000,
        )
        return {
            "reply": (final_msg["content"].strip() if final_msg and final_msg.get("content")
                      else "查到这些信息了，但我思考有点超时。基于上面工具结果，建议你先看 recommendations。"),
            "recommendations": recommendations,
            "advisor_profiles": advisor_profiles,
            "tool_trace": tool_trace,
        }


async def chat_turn_stream(messages: list[dict]):
    """Streaming variant of `chat_turn`. Yields event dicts:
      {"type": "thinking"}                          # turn start
      {"type": "tool_start", "name", "args"}        # tool dispatched
      {"type": "tool_end",   "name", "summary",     # tool finished
                              "recommendation"?, "advisor_profile"?}
      {"type": "delta",  "content": "..."}          # final reply text token
      {"type": "done", "recommendations":[...], "advisor_profiles":[...]}
    """
    chat_msgs: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in messages:
        chat_msgs.append({"role": m["role"], "content": m["content"]})

    recommendations: list[dict] = []
    advisor_profiles: list[dict] = []
    tool_trace: list[dict] = []

    async with httpx.AsyncClient() as client:
        for turn in range(MAX_AGENT_TURNS):
            is_last_turn = turn == MAX_AGENT_TURNS - 1
            # gpt-5 is a reasoning model that needs ample budget — too low and
            # reasoning eats all tokens, leaving 0 for content/tool_calls.
            tok_budget = 6000

            yield {"type": "thinking"}

            assembled_msg = None
            async for ev in _stream_llm_chat(
                client, chat_msgs, AGENT_MODEL,
                with_tools=not is_last_turn, max_tokens=tok_budget,
            ):
                if "content" in ev:
                    yield {"type": "delta", "content": ev["content"]}
                elif "done" in ev:
                    assembled_msg = ev["done"]

            if assembled_msg is None:
                yield {"type": "done", "recommendations": recommendations,
                       "advisor_profiles": advisor_profiles, "error": "LLM stream failed"}
                return

            tool_calls = assembled_msg.get("tool_calls") or []
            content = assembled_msg.get("content") or ""
            chat_msgs.append(assembled_msg)

            if not tool_calls:
                # If content is empty, retry once with no tools forcing free-form reply
                if not content.strip():
                    logger.info("Empty final reply, retrying with no-tools forcing")
                    retry_msg = await _call_llm_chat(
                        client, chat_msgs[:-1] + [{
                            "role": "user",
                            "content": "请基于上面工具检索到的内容，给我一个最终的中文回复（3-6 句话，每个事实标[来源]）。",
                        }],
                        AGENT_MODEL, with_tools=False, max_tokens=6000,
                    )
                    if retry_msg and retry_msg.get("content"):
                        # Stream the retry content as delta tokens for UX consistency
                        for ch in retry_msg["content"]:
                            yield {"type": "delta", "content": ch}
                yield {"type": "done",
                       "recommendations": recommendations,
                       "advisor_profiles": advisor_profiles,
                       "tool_trace": tool_trace}
                return

            # Parallel tool execution
            parsed = []
            for tc in tool_calls:
                fn = tc.get("function") or {}
                tname = fn.get("name", "")
                targs = _parse_tool_args(fn.get("arguments") or "")
                tcall_id = tc.get("id", "")
                parsed.append((tcall_id, tname, targs, tc))
                yield {"type": "tool_start", "name": tname, "args": targs}

            results = await asyncio.gather(*[
                _exec_one_tool(tc, tname, targs, client)
                for (_, tname, targs, tc) in parsed
            ])

            for (tcall_id, tname, targs, _), tresult in zip(parsed, results):
                summary = _summarize_result(tname, tresult)
                tool_trace.append({"name": tname, "args": targs, "result_summary": summary})

                tool_end_event = {"type": "tool_end", "name": tname, "summary": summary}
                if tname == "search_advisors":
                    new_advisors = []
                    for a in tresult.get("advisors", []):
                        if not any(r.get("advisor_id") == a.get("advisor_id") for r in recommendations):
                            recommendations.append(a)
                            new_advisors.append(a)
                    tool_end_event["new_advisors_count"] = len(new_advisors)
                elif tname == "lookup_advisor" and tresult.get("found"):
                    profile = {**tresult["advisor"], "mentions": tresult.get("mentions", [])}
                    if not any(p.get("advisor_id") == profile["advisor_id"] for p in advisor_profiles):
                        advisor_profiles.append(profile)
                        tool_end_event["advisor_profile"] = profile
                yield tool_end_event

                payload = json.dumps(tresult, ensure_ascii=False)
                if len(payload) > 12000:
                    payload = payload[:12000] + "...<truncated>"
                chat_msgs.append({
                    "role": "tool",
                    "tool_call_id": tcall_id,
                    "content": payload,
                })

        # Reached max turns — force a final reply
        yield {"type": "thinking"}
        async for ev in _stream_llm_chat(
            client, chat_msgs, AGENT_MODEL,
            with_tools=False, max_tokens=4000,
        ):
            if "content" in ev:
                yield {"type": "delta", "content": ev["content"]}
        yield {"type": "done",
               "recommendations": recommendations,
               "advisor_profiles": advisor_profiles,
               "tool_trace": tool_trace}


def _summarize_result(name: str, result: dict) -> str:
    if "error" in result:
        return f"error: {result['error']}"
    if name == "search_advisors":
        return f"matched={result.get('total_matched', 0)}, returned={result.get('returned', 0)}"
    if name == "lookup_advisor":
        if result.get("found"):
            a = result["advisor"]
            return f"found {a['name']} @ {a['school']} ({a['college']}), mentions={len(result.get('mentions', []))}"
        return "not found" + (f" (ambiguous: {len(result.get('candidates', []))})" if result.get("ambiguous") else "")
    if name == "get_advisor_mentions":
        return f"count={result.get('count', 0)}"
    if name == "find_colleges":
        return f"{len(result.get('colleges', []))} colleges"
    if name == "web_search":
        return f"summary len={len(result.get('summary', ''))}, sources={len(result.get('sources', []))}"
    return "ok"
