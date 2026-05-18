"""Career history service: LLM + web search collects education + positions.

Mirrors buzz_service pattern: primary path uses Responses API with
web_search_preview tool; falls back to Chat Completions (no search, uses
only LLM knowledge) on the lightweight fallback model.
"""

import json
import logging
import re
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LLM_API_BASE, LLM_API_KEY, LLM_BUZZ_MODEL, LLM_FALLBACK_MODEL
from app.models import User, CareerHistory

logger = logging.getLogger(__name__)


def _parse_json(text: str) -> dict | None:
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        s = s.rsplit("```", 1)[0]
    try:
        return json.loads(s.strip())
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", s)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return None


def _build_prompt(user: User) -> str:
    name = user.name or user.github_username or "研究者"
    identity = [f"- 姓名：{name}"]
    if user.bio:
        identity.append(f"- 当前简介：{user.bio}")
    if user.scholar_id:
        identity.append(f"- Semantic Scholar: https://www.semanticscholar.org/author/{user.scholar_id}")
    if user.github_username:
        identity.append(f"- GitHub: https://github.com/{user.github_username}")
    if user.hf_username:
        identity.append(f"- HuggingFace: https://huggingface.co/{user.hf_username}")
    if user.homepage:
        identity.append(f"- 个人主页: {user.homepage}")
    identity_block = "\n".join(identity)

    return f"""你是一个科研人员简历整理助手。请搜索以下研究者的**教育经历与职业经历**，输出结构化时间线。

研究对象：
{identity_block}

### 检索要求
1. **优先查权威来源**：个人主页、所在机构官网、Google Scholar、LinkedIn、Wikipedia、DBLP 履历页。
2. 如有个人主页，请**务必首先访问**，其它来源作为补充/核实。
3. 时间线按时间顺序排列（从早到晚）。
4. 对于**教育经历**：覆盖本科/硕士/博士（如可查到）；type="education"。
5. 对于**职业经历**：覆盖博后、讲师/助理教授/副教授/教授、研究员/资深研究员、创业者等；type="position"。
6. 只收录能在权威来源中验证的条目，**不要猜测**；查不到就不写。
7. 对于 PhD 阶段，尽可能填 advisor（导师姓名）。

### 输出格式（严格 JSON，不要 markdown 代码块、不要任何其他文字）

{{
  "timeline": [
    {{
      "start_year": 2014,
      "end_year": 2018,
      "type": "education",
      "role": "B.S. in Computer Science",
      "institution": "Tsinghua University",
      "advisor": "",
      "note": ""
    }},
    {{
      "start_year": 2018,
      "end_year": 2023,
      "type": "education",
      "role": "Ph.D. in Computer Science",
      "institution": "Stanford University",
      "advisor": "Christopher Manning",
      "note": ""
    }},
    {{
      "start_year": 2023,
      "end_year": null,
      "type": "position",
      "role": "Research Scientist",
      "institution": "OpenAI",
      "advisor": "",
      "note": "Working on post-training alignment."
    }}
  ],
  "current": "Research Scientist at OpenAI",
  "sources": [
    {{"title": "Personal homepage", "url": "https://..."}},
    {{"title": "LinkedIn", "url": "https://..."}}
  ]
}}

### 字段约束
- `start_year` / `end_year`：整数年份；`end_year` 为 `null` 表示至今
- `type`：必须是 `"education"` 或 `"position"`
- `role`：**英文原称**（"Ph.D. Student"、"Postdoctoral Researcher"、"Research Scientist"、"Associate Professor"），不要翻译
- `institution`：机构英文名（"Stanford University"），不要翻译
- `advisor`：导师全名，查不到留空字符串
- `note`：可选的一两句补充说明，英文或中文皆可，查无可留空
- `current`：一句话总结当前职位（"Research Scientist at OpenAI" 这样）
- `sources`：2-6 条可验证的来源链接

只输出 JSON。"""


async def _query_llm_with_search(client: httpx.AsyncClient, prompt: str) -> tuple[str | None, list[dict]]:
    """Primary: Responses API + web_search_preview. Fallback: Chat Completions (no search)."""
    # ── Responses API ──
    try:
        resp = await client.post(
            f"{LLM_API_BASE}/responses",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                # gpt-5-mini supports web_search_preview and runs ~3× faster than
                # gpt-5 for this structured-extraction task (career timeline).
                "model": "gpt-5-mini",
                "tools": [{"type": "web_search_preview"}],
                "input": prompt,
                "max_output_tokens": 16000,
            },
            timeout=300,
        )
        if resp.status_code == 200:
            data = resp.json()
            text = ""
            sources: list[dict] = []
            seen: set[str] = set()
            for item in data.get("output", []):
                if item.get("type") == "message":
                    for c in item.get("content", []):
                        if c.get("type") == "output_text":
                            text = c.get("text", "")
                            for ann in c.get("annotations", []):
                                if ann.get("type") == "url_citation":
                                    url = (ann.get("url") or "").strip()
                                    title = (ann.get("title") or "").strip() or url
                                    if url and url not in seen:
                                        seen.add(url)
                                        sources.append({"title": title, "url": url})
            if text:
                return text, sources[:10]
    except Exception as e:
        logger.info("Career Responses API failed (%s), falling back", e)

    # ── Fallback: Chat Completions on mini model ──
    try:
        resp = await client.post(
            f"{LLM_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": LLM_FALLBACK_MODEL,
                "messages": [{"role": "user", "content": prompt + "\n\n再次强调：只输出 JSON。"}],
                "max_completion_tokens": 4000,
            },
            timeout=180,
        )
        if resp.status_code != 200:
            logger.warning("Career Chat API returned %d: %s", resp.status_code, resp.text[:200])
            return None, []
        data = resp.json()
        return data["choices"][0]["message"].get("content", ""), []
    except Exception as e:
        logger.warning("Career Chat API failed: %s", e)
        return None, []


def _sanitize_step(step: dict) -> dict:
    return {
        "start_year": int(step["start_year"]) if isinstance(step.get("start_year"), (int, float, str)) and str(step.get("start_year")).lstrip("-").isdigit() else None,
        "end_year": int(step["end_year"]) if isinstance(step.get("end_year"), (int, float, str)) and str(step.get("end_year")).lstrip("-").isdigit() else None,
        "type": step.get("type") if step.get("type") in ("education", "position") else "position",
        "role": str(step.get("role", ""))[:120],
        "institution": str(step.get("institution", ""))[:120],
        "advisor": str(step.get("advisor", ""))[:80],
        "note": str(step.get("note", ""))[:240],
    }


async def refresh_career(db: AsyncSession, user: User) -> CareerHistory | None:
    """Fetch career via LLM web search, upsert to DB."""
    name = user.name or user.github_username
    if not name:
        return None

    prompt = _build_prompt(user)

    async with httpx.AsyncClient(timeout=310) as client:
        content, verified_sources = await _query_llm_with_search(client, prompt)

    if not content:
        logger.warning("Career: LLM returned no content for user %d", user.id)
        return None

    parsed = _parse_json(content)
    if not parsed or not isinstance(parsed, dict):
        logger.warning(
            "Career: JSON parse failed for user %d (content len=%d): %s ... %s",
            user.id, len(content), content[:200], content[-100:] if len(content) > 200 else "",
        )
        return None

    timeline = parsed.get("timeline") or []
    if not isinstance(timeline, list):
        timeline = []
    timeline = [_sanitize_step(s) for s in timeline if isinstance(s, dict)]
    # Sort by start_year asc, None → 0
    timeline.sort(key=lambda s: (s.get("start_year") or 0, s.get("end_year") or 9999))

    current = str(parsed.get("current", ""))[:300]

    # Prefer LLM-listed sources; if none, use verified_sources from web_search annotations
    raw_sources = parsed.get("sources") or []
    if not isinstance(raw_sources, list) or not raw_sources:
        sources = verified_sources
    else:
        sources = []
        seen_urls: set[str] = set()
        for s in raw_sources:
            if not isinstance(s, dict):
                continue
            url = str(s.get("url", "")).strip()
            title = str(s.get("title", "")).strip() or url
            if url and url not in seen_urls:
                seen_urls.add(url)
                sources.append({"title": title, "url": url})
        # supplement with verified_sources if we have room
        for vs in verified_sources:
            if vs["url"] not in seen_urls and len(sources) < 10:
                seen_urls.add(vs["url"])
                sources.append(vs)

    # Upsert
    existing = (await db.execute(
        select(CareerHistory).where(CareerHistory.user_id == user.id)
    )).scalars().first()

    if existing:
        existing.timeline_json = timeline
        existing.current = current
        existing.sources = sources[:10]
        existing.refreshed_at = datetime.utcnow()
        row = existing
    else:
        row = CareerHistory(
            user_id=user.id,
            timeline_json=timeline,
            current=current,
            sources=sources[:10],
            refreshed_at=datetime.utcnow(),
        )
        db.add(row)

    await db.flush()
    logger.info("Career refreshed for user %d: %d steps, %d sources", user.id, len(timeline), len(sources))
    return row
