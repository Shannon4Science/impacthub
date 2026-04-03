"""Honor enrichment service.

For each unique notable-citation author, queries gpt-4o-mini-search-preview
(or compatible search LLM) to determine if the scholar holds any of:
  IEEE Fellow / ACM Fellow / ACL Fellow
  中国科学院院士 / 中国工程院院士 / 其他国家院士
  图灵奖 / 诺贝尔奖

Results are stored in NotableCitation.honor_tags (JSON list).
  - NULL  → not yet enriched
  - []    → enriched, no honors found
  - [...]  → enriched, has honors
"""

import asyncio
import json
import logging
import re

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LLM_API_BASE, LLM_API_KEY, LLM_BUZZ_MODEL
from app.database import async_session
from app.models import NotableCitation

logger = logging.getLogger(__name__)

BATCH_SIZE = 15          # authors per LLM call
REQUEST_DELAY = 2.0      # seconds between batches

_enriching_users: set[int] = set()


def is_enriching(user_id: int) -> bool:
    return user_id in _enriching_users


HONOR_CATEGORIES = [
    "IEEE Fellow", "ACM Fellow", "ACL Fellow",
    "中国科学院院士", "中国工程院院士", "其他国家院士",
    "图灵奖", "诺贝尔奖",
]

PROMPT_TEMPLATE = """\
你是一个学术荣誉核实助手。以下是 {n} 位 AI/ML 领域学者的姓名和 h-index，\
请分别搜索每位学者是否持有以下任一荣誉称号：
{honors}

学者列表：
{scholars}

请逐一搜索每位学者的个人主页、所在机构官网、IEEE 官网、中国科学院/工程院官网等可信来源，\
确认其是否具有上述荣誉称号。

**严格**以如下 JSON 数组格式输出（不要输出任何其他文字）：
[
  {{"name": "姓名1", "honor_tags": ["IEEE Fellow"]}},
  {{"name": "姓名2", "honor_tags": []}},
  ...
]

若未找到任何上述荣誉，该学者的 honor_tags 输出空数组 []。\
若 honor_tags 中含 "Fellowship"（如 Google Fellowship），请排除，只保留学术/院士称号。
"""


def _extract_json(text: str) -> list[dict]:
    """Robustly extract the first JSON array from the LLM response."""
    # Try direct parse first
    try:
        return json.loads(text.strip())
    except Exception:
        pass
    # Find first [...] block
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return []


def _normalize_tags(raw_tags: list) -> list[str]:
    """Keep only recognized honor strings, deduplicated."""
    known = {h.lower(): h for h in HONOR_CATEGORIES}
    result: list[str] = []
    for t in raw_tags:
        t_str = str(t).strip()
        # exact match (case-insensitive)
        key = t_str.lower()
        if key in known:
            result.append(known[key])
            continue
        # substring match
        for cat in HONOR_CATEGORIES:
            if cat.lower() in key or key in cat.lower():
                if cat not in result:
                    result.append(cat)
                break
    return result


async def _query_honors(
    client: httpx.AsyncClient,
    authors: list[dict],  # [{name, h_index, ss_id}]
) -> dict[str, list[str]]:
    """Query LLM for honor tags for a batch of authors.
    Returns {author_ss_id: [honor_tags]}.
    """
    scholars_block = "\n".join(
        f"{i+1}. 姓名：{a['name']}，h-index：{a['h_index']}"
        for i, a in enumerate(authors)
    )
    prompt = PROMPT_TEMPLATE.format(
        n=len(authors),
        honors="、".join(HONOR_CATEGORIES),
        scholars=scholars_block,
    )

    try:
        # Try Responses API first (supports web search for verification)
        try:
            resp = await client.post(
                f"{LLM_API_BASE}/responses",
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                json={
                    "model": LLM_BUZZ_MODEL,
                    "tools": [{"type": "web_search_preview"}],
                    "input": prompt,
                    "max_output_tokens": 4000,
                },
                timeout=180,
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("output", []):
                    if item.get("type") == "message":
                        for c in item.get("content", []):
                            if c.get("type") == "output_text":
                                content = c.get("text", "")
                                records = _extract_json(content)
                                if records:
                                    logger.info("Honor query via Responses API: got %d records", len(records))
                                    # Map back
                                    result: dict[str, list[str]] = {}
                                    for idx, rec in enumerate(records):
                                        if idx >= len(authors):
                                            break
                                        ss_id = authors[idx]["ss_id"]
                                        tags = _normalize_tags(rec.get("honor_tags") or [])
                                        result[ss_id] = tags
                                    for a in authors:
                                        if a["ss_id"] not in result:
                                            result[a["ss_id"]] = []
                                    return result
            else:
                logger.info("Honor Responses API returned %d, falling back", resp.status_code)
        except Exception as e:
            logger.info("Honor Responses API failed (%s), falling back", e)

        # Fallback: Chat Completions API
        resp = await client.post(
            f"{LLM_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": LLM_BUZZ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_completion_tokens": 4000,
            },
            timeout=120,
        )
        if resp.status_code != 200:
            logger.warning("Honor API returned %d: %s", resp.status_code, resp.text[:200])
            return {}
        content = resp.json()["choices"][0]["message"]["content"]
        records = _extract_json(content)
    except Exception as e:
        logger.warning("Honor query failed: %s", e)
        return {}

    # Map back by position (LLM returns results in same order)
    result: dict[str, list[str]] = {}
    for i, rec in enumerate(records):
        if i >= len(authors):
            break
        ss_id = authors[i]["ss_id"]
        tags = _normalize_tags(rec.get("honor_tags") or [])
        result[ss_id] = tags

    # Fill in empty for authors LLM skipped
    for a in authors:
        if a["ss_id"] not in result:
            result[a["ss_id"]] = []

    return result


async def enrich_honors_for_user(user_id: int) -> int:
    """Enrich honor_tags for all un-enriched notable citations of a user.
    Returns the number of authors with any honor found.
    """
    if user_id in _enriching_users:
        logger.info("Honor enrichment already running for user %d", user_id)
        return 0
    _enriching_users.add(user_id)
    honor_count = 0

    try:
        async with async_session() as db:
            # Collect unique unenriched authors (honor_tags IS NULL)
            rows = (await db.execute(
                select(
                    NotableCitation.author_ss_id,
                    NotableCitation.author_name,
                    NotableCitation.author_h_index,
                ).where(
                    NotableCitation.user_id == user_id,
                    NotableCitation.honor_tags.is_(None),
                ).distinct()
            )).all()

            if not rows:
                logger.info("No unenriched authors for user %d", user_id)
                return 0

            unique_authors = [
                {"ss_id": r.author_ss_id, "name": r.author_name, "h_index": r.author_h_index}
                for r in rows
            ]
            logger.info(
                "Honor enrichment: %d unique authors to process for user %d",
                len(unique_authors), user_id,
            )

            async with httpx.AsyncClient(timeout=90) as client:
                for i in range(0, len(unique_authors), BATCH_SIZE):
                    batch = unique_authors[i: i + BATCH_SIZE]
                    tag_map = await _query_honors(client, batch)

                    # Update all NotableCitation rows for these authors
                    for ss_id, tags in tag_map.items():
                        await db.execute(
                            update(NotableCitation)
                            .where(
                                NotableCitation.user_id == user_id,
                                NotableCitation.author_ss_id == ss_id,
                            )
                            .values(honor_tags=tags)
                        )
                        if tags:
                            honor_count += 1
                            logger.info("  %s → %s", ss_id, tags)

                    await db.commit()

                    if i + BATCH_SIZE < len(unique_authors):
                        await asyncio.sleep(REQUEST_DELAY)

        logger.info(
            "Honor enrichment complete for user %d: %d/%d authors have honors",
            user_id, honor_count, len(unique_authors),
        )
    except Exception:
        logger.exception("Honor enrichment failed for user %d", user_id)
    finally:
        _enriching_users.discard(user_id)

    return honor_count
