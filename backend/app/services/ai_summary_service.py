"""AI Summary service: generates a short researcher summary and tags using LLM."""

import json
import logging
from datetime import datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models import User, Paper, GithubRepo, HFItem, AISummary, BuzzSnapshot, NotableCitation
from app.config import LLM_API_BASE, LLM_API_KEY, LLM_BUZZ_MODEL
from app.utils.paper_dedup import deduplicate_papers

logger = logging.getLogger(__name__)


async def _collect_user_context(db: AsyncSession, user: User) -> str:
    """Gather user data from DB to build the LLM prompt context."""
    uid = user.id

    # Papers (top 10 by citations)
    papers_raw = (await db.execute(
        select(Paper).where(Paper.user_id == uid).order_by(Paper.citation_count.desc())
    )).scalars().all()
    papers = deduplicate_papers(papers_raw)
    papers.sort(key=lambda p: p.citation_count, reverse=True)

    total_citations = sum(p.citation_count for p in papers)
    ccf_a = sum(1 for p in papers if (p.ccf_rank or "") == "A")
    ccf_b = sum(1 for p in papers if (p.ccf_rank or "") == "B")

    # h-index
    cits = sorted([p.citation_count for p in papers], reverse=True)
    h_index = 0
    for i, c in enumerate(cits):
        if c >= i + 1:
            h_index = i + 1
        else:
            break

    # Repos (top 5 by stars)
    repos = (await db.execute(
        select(GithubRepo).where(GithubRepo.user_id == uid).order_by(GithubRepo.stars.desc()).limit(5)
    )).scalars().all()
    total_stars = sum(r.stars for r in repos)

    # HF items (top 5 by downloads)
    hf_items = (await db.execute(
        select(HFItem).where(HFItem.user_id == uid).order_by(HFItem.downloads.desc()).limit(5)
    )).scalars().all()
    total_downloads = sum(h.downloads for h in hf_items)

    # Notable citations count
    notable_count = (await db.execute(
        select(func.count()).select_from(NotableCitation).where(NotableCitation.user_id == uid)
    )).scalar() or 0

    # Buzz snapshot
    buzz = (await db.execute(
        select(BuzzSnapshot).where(BuzzSnapshot.user_id == uid)
    )).scalars().first()

    # Build context text
    lines = []
    lines.append(f"研究者：{user.name or user.github_username}")
    if user.bio:
        lines.append(f"简介：{user.bio}")
    lines.append("")

    lines.append(f"学术指标：共 {len(papers)} 篇论文，总引用 {total_citations}，h-index {h_index}")
    if ccf_a or ccf_b:
        lines.append(f"CCF-A 论文 {ccf_a} 篇，CCF-B 论文 {ccf_b} 篇")
    if notable_count:
        lines.append(f"被 {notable_count} 位知名/顶级学者引用")
    lines.append("")

    if papers[:10]:
        lines.append("代表论文（按引用排序）：")
        for p in papers[:10]:
            ccf_tag = f" [CCF-{p.ccf_rank}]" if p.ccf_rank else ""
            lines.append(f"  - {p.title} ({p.venue}, {p.year}) 引用:{p.citation_count}{ccf_tag}")
        lines.append("")

    if repos:
        lines.append(f"GitHub：总 Stars {total_stars}")
        for r in repos:
            lines.append(f"  - {r.repo_name}: {r.stars} stars, {r.language or 'N/A'}")
        lines.append("")

    if hf_items:
        lines.append(f"Hugging Face：总下载 {total_downloads}")
        for h in hf_items:
            lines.append(f"  - {h.name} ({h.item_type}): {h.downloads} downloads, {h.likes} likes")
        lines.append("")

    if buzz and buzz.heat_label:
        lines.append(f"网络讨论热度：{buzz.heat_label}")
        if buzz.topics:
            lines.append(f"讨论话题：{', '.join(buzz.topics[:5])}")
        lines.append("")

    return "\n".join(lines)


async def refresh_ai_summary(db: AsyncSession, user: User) -> AISummary | None:
    """Generate AI summary and tags for a user, upsert to DB."""
    context = await _collect_user_context(db, user)
    if not context.strip():
        return None

    prompt = f"""你是一个科研影响力分析助手。请根据以下研究者的数据，完成两个任务：

1. **总结**：用 2-3 句中文概括这位研究者的主要研究方向、核心贡献和影响力特点。语言要精炼、有洞察力，避免堆砌数字。
2. **头衔标签**：给出 3-5 个有趣、有个性的"头衔/称号"，而不是干巴巴的研究方向。头衔应该像绰号一样生动有趣，能体现研究者的特色和成就。
   - 好的例子："开源狂魔"、"引用收割机"、"Benchmark 制造者"、"数据炼金术师"、"多模态探索家"、"Star 破万俱乐部"、"CCF-A 常客"、"顶会收割机"
   - 不好的例子（太无聊）："数据驱动"、"数学推理"、"合成检测"——这些是研究方向，不是头衔
   - 每个头衔 3-7 个字，中英文混用也可以

研究者数据：
{context}

请严格按照以下 JSON 格式输出，不要输出其他内容：
{{"summary": "2-3句总结文字", "tags": ["头衔1", "头衔2", "头衔3"]}}"""

    content = None
    async with httpx.AsyncClient(timeout=120) as client:
        # Try Responses API first (for gpt-5 etc.)
        try:
            resp = await client.post(
                f"{LLM_API_BASE}/responses",
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                json={
                    "model": LLM_BUZZ_MODEL,
                    "input": prompt,
                    "max_output_tokens": 2000,
                },
                timeout=120,
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("output", []):
                    if item.get("type") == "message":
                        for c in item.get("content", []):
                            if c.get("type") == "output_text":
                                content = c.get("text", "")
                if content:
                    logger.info("AI Summary: Responses API success, %d chars", len(content))
            else:
                logger.info("AI Summary: Responses API returned %d, trying chat completions", resp.status_code)
        except Exception as e:
            logger.info("AI Summary: Responses API failed (%s), trying chat completions", e)

        # Fallback: Chat Completions API
        if not content:
            try:
                resp = await client.post(
                    f"{LLM_API_BASE}/chat/completions",
                    headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                    json={
                        "model": LLM_BUZZ_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_completion_tokens": 2000,
                    },
                    timeout=120,
                )
                if resp.status_code != 200:
                    logger.warning("AI Summary: Chat API returned %d: %s", resp.status_code, resp.text[:200])
                    return None
                data = resp.json()
                content = data["choices"][0]["message"].get("content", "")
            except Exception as e:
                logger.warning("AI Summary: Chat API call failed: %s", e)
                return None

    if not content:
        logger.warning("AI Summary: No content returned from LLM")
        return None

    # Parse JSON from response
    try:
        # Try to extract JSON from possible markdown code block
        text = content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        result = json.loads(text.strip())
        summary = result.get("summary", "")
        tags = result.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        tags = [str(t) for t in tags[:5]]
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning("Failed to parse AI summary JSON: %s, content: %s", e, content[:200])
        return None

    if not summary:
        return None

    # Upsert
    existing = (await db.execute(
        select(AISummary).where(AISummary.user_id == user.id)
    )).scalars().first()

    if existing:
        existing.summary = summary
        existing.tags = tags
        existing.refreshed_at = datetime.utcnow()
        ai_summary = existing
    else:
        ai_summary = AISummary(
            user_id=user.id,
            summary=summary,
            tags=tags,
            refreshed_at=datetime.utcnow(),
        )
        db.add(ai_summary)

    await db.flush()
    logger.info("AI Summary refreshed for user %d: %d chars, %d tags", user.id, len(summary), len(tags))
    return ai_summary
