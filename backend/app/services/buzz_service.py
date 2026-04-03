"""Web buzz service: uses Perplexity sonar to gauge researcher's external online presence.

Searches for:
1. The researcher's name as a person (are people discussing them?)
2. Their top papers' titles (are people sharing/discussing the work?)

Returns a structured snapshot with a heat label, narrative summary, and sources.
"""

import json
import logging
import re
from datetime import datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import User, BuzzSnapshot
from app.config import OUTBOUND_PROXY, LLM_API_BASE, LLM_API_KEY, LLM_BUZZ_MODEL

logger = logging.getLogger(__name__)

BUZZ_MODEL = LLM_BUZZ_MODEL

def _classify_heat(content: str) -> str:
    """Derive heat label from the structured tag in section 7."""
    # Look for the explicit heat tag: 【当前热度】极高/较高/一般/较低/极低
    m = re.search(r"【当前热度】\s*(极高|较高|一般|较低|极低)", content)
    if m:
        return {"极高": "very_hot", "较高": "hot", "一般": "medium", "较低": "cold", "极低": "very_cold"}[m.group(1)]
    # Fallback: keyword matching in section 7
    section7 = re.search(r"##\s*7[.\s].*?(?=##\s*8|\Z)", content, re.DOTALL)
    if not section7:
        return "medium"
    text = section7.group(0).lower()
    if any(k in text for k in ["上升", "持续增长", "快速扩散", "高热度", "热度较高", "峰值"]):
        return "hot"
    if any(k in text for k in ["回落", "降温", "显著下降", "冷门", "几乎没有", "讨论很少"]):
        return "cold"
    return "medium"


def _extract_sources(content: str) -> list[dict]:
    """Extract markdown links [title](url) from the response text."""
    pattern = r"\[([^\]]+)\]\((https?://[^)]+)\)"
    matches = re.findall(pattern, content)
    seen = set()
    sources = []
    for title, url in matches:
        if url not in seen:
            seen.add(url)
            sources.append({"title": title.strip(), "url": url.strip()})
    return sources[:10]


def _extract_topics(content: str) -> list[str]:
    """Extract topic names from '### 主题 N：<name>' headings in the structured output."""
    matches = re.findall(r"###\s*主题\s*\d+[：:]\s*(.+)", content)
    topics = [m.strip() for m in matches if m.strip()]
    # Fallback: grab bolded short phrases outside of heading lines
    if not topics:
        for line in content.splitlines():
            if line.startswith("#"):
                continue
            for m in re.findall(r"\*\*([^*]{3,20})\*\*", line):
                if m.strip() not in topics:
                    topics.append(m.strip())
                if len(topics) >= 8:
                    break
    return topics[:8]


async def _query_llm(client: httpx.AsyncClient, prompt: str) -> tuple[str | None, list[dict]]:
    """Send a query to the LLM and return (text, verified_sources).

    Tries the Responses API first (supports web_search_preview tool for GPT-5, etc.),
    then falls back to Chat Completions API for other models.
    """
    # ── Try Responses API (supports web search tool) ──
    try:
        resp = await client.post(
            f"{LLM_API_BASE}/responses",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": BUZZ_MODEL,
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
                                    url = ann.get("url", "").strip()
                                    title = ann.get("title", "").strip() or url
                                    if url and url not in seen:
                                        seen.add(url)
                                        sources.append({"title": title, "url": url})
            if text:
                logger.info("Responses API success: %d chars, %d sources", len(text), len(sources))
                return text, sources[:20]
        else:
            logger.info("Responses API returned %d, falling back to chat completions", resp.status_code)
    except Exception as e:
        logger.info("Responses API failed (%s), falling back to chat completions", e)

    # ── Fallback: Chat Completions API ──
    try:
        resp = await client.post(
            f"{LLM_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": BUZZ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_completion_tokens": 16000,
            },
            timeout=300,
        )
        if resp.status_code != 200:
            logger.warning("Chat API returned %d: %s", resp.status_code, resp.text[:200])
            return None, []
        data = resp.json()
        message = data["choices"][0]["message"]
        content = message.get("content") or ""

        # Extract annotations if present
        annotations = message.get("annotations") or []
        if annotations:
            seen_urls: set[str] = set()
            srcs: list[dict] = []
            for ann in annotations:
                if ann.get("type") == "url_citation":
                    uc = ann.get("url_citation", {})
                    url = uc.get("url", "").strip()
                    title = uc.get("title", "").strip() or url
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        srcs.append({"title": title, "url": url})
            if srcs:
                logger.info("Using %d verified URLs from chat annotations", len(srcs))
                return content, srcs[:20]

        # Perplexity citations fallback
        perplexity_citations: list[str] = data.get("citations") or []
        if perplexity_citations:
            srcs = [{"title": f"来源 {i+1}", "url": u} for i, u in enumerate(perplexity_citations)]
            return content, srcs[:20]

        return content, []
    except Exception as e:
        logger.warning("Chat API query failed: %s", e)
        return None, []


async def refresh_buzz(db: AsyncSession, user: User) -> BuzzSnapshot | None:
    """Query LLM search API and update the buzz snapshot for a user."""
    name = user.name or user.github_username
    if not name:
        return None

    # Build researcher identity block to avoid searching wrong person
    identity_lines = [f"- 姓名：{name}"]
    if user.github_username:
        identity_lines.append(f"- GitHub：https://github.com/{user.github_username}")
    if user.scholar_id:
        identity_lines.append(f"- Semantic Scholar：https://www.semanticscholar.org/author/{user.scholar_id}")
    if user.hf_username:
        identity_lines.append(f"- Hugging Face：https://huggingface.co/{user.hf_username}")
    if user.bio:
        identity_lines.append(f"- 个人简介：{user.bio}")
    if user.homepage:
        identity_lines.append(f"- 个人主页：{user.homepage}")
    identity_block = "\n".join(identity_lines)

    # Build homepage-aware prompt section
    if user.homepage:
        homepage_instruction = f"""
### 个人主页信息
该研究者有个人主页：{user.homepage}
请先访问该主页，从中获取研究者的详细背景信息（如所属机构、研究方向、代表作品、近期动态、发布的博文等），并将这些信息纳入后续分析的上下文中，以提升搜索精度和分析深度。但这只作为辅助信息，不要过度依赖。请依然按照后续的检索范围和信息渠道进行检索。
"""
    else:
        homepage_instruction = ""

    prompt = f"""
请你充当一名"AI/ML 研究者舆情与社区讨论分析助手"，围绕 AI/ML 研究者「{name}」进行近 2 年的网络讨论调研，并尽可能补充更早但仍持续影响当前讨论的重要事件。

### 研究对象身份信息（请以此为准，避免搜索同名人物）
{identity_block}
{homepage_instruction}
### 任务目标
请搜索并总结：围绕该研究者，互联网用户最近在讨论什么、哪些平台最活跃、哪些论文/项目/观点/事件引发了最多讨论，以及这些讨论整体呈现出怎样的舆论结构。

---

### 检索范围
请优先检索过去 **2 年** 的内容；若近 2 年信息较少，可适当补充更早但仍被反复引用的重要讨论。

---

### 信息渠道（请尽量覆盖，不要只依赖新闻）
请按下列渠道尽可能全面检索，并在总结中区分来源类型：

#### 1. 社交媒体与社区讨论
- Twitter / X
- Reddit（如 r/MachineLearning、r/LocalLLaMA、r/singularity、相关子版块）
- Hacker News
- Hugging Face 社区（模型页、讨论区、帖子、Spaces 相关讨论）
- GitHub（Issues、Discussions、Release notes、PR 讨论）
- LessWrong / EA Forum（如相关）
- Discord / Slack 公开整理页或公开转述页面（如能检索到）
- YouTube 评论区 / 播客评论 / 视频讨论（如访谈、演讲、论文解读）
- Bilibili、知乎、微信公众号、中文技术社区（若该研究者在中文圈有传播）

#### 2. 学术传播与研究热度
- arXiv 论文页面与相关讨论
- Semantic Scholar / Google Scholar 上高传播作品线索
- Papers with Code
- OpenReview（如适用）
- 专题解读博客、论文速读文章、研究综述帖

#### 3. 媒体与博客
- 技术博客（个人博客、机构博客、Substack、Medium）
- 科技媒体与行业媒体报道
- 播客、访谈、会议演讲摘要
- 实验室官网、个人主页更新、公开声明

#### 4. 项目与产品生态
- 相关开源项目主页
- 模型发布页 / Demo 页 / Benchmark 页面
- 相关产品集成、二创项目、复现项目、对比评测文章

---

### 分析要求
请特别关注以下问题：

1. **大家在讨论什么**
   - 是在讨论其论文、模型、开源项目、创业动态、技术观点、争议言论，还是职业变动？
   - 请提炼出 3–8 个主要讨论主题。

2. **哪些平台最活跃**
   - 哪些平台上的讨论最频繁、最集中、最有代表性？
   - 不要求精确统计全部数量，但请根据可见证据判断活跃平台。

3. **哪些作品或话题最受关注**
   - 哪些论文、模型、项目、演讲、推文、采访、争议事件被讨论最多？
   - 如果能判断，请说明"为什么它引发讨论"。

4. **讨论倾向与舆论特征**
   - 讨论是偏正面、偏质疑、偏技术分析、偏行业八卦，还是呈现明显分裂？
   - 请区分"学术认可""工程关注""社区热议""争议传播"这几类影响力。

5. **时间脉络**
   - 如果讨论有明显阶段变化，请按时间顺序简述：
     - 最早由什么事件引爆
     - 后续在哪些平台扩散
     - 最近讨论是否降温/持续/转向

6. **证据质量控制**
   - 优先使用原始来源、公开帖子、项目主页、论文页、主流技术社区页面。
   - 避免将单一转载、低质量聚合站、无来源营销文作为核心证据。
   - 若同一事件有多个来源，请优先引用原始出处和高质量二手分析。

---

### 输出格式要求
请严格按照以下 Markdown 结构输出：

# {name} 近期网络讨论分析

## 1. 一句话结论
用 2–4 句话概括：
- 这个研究者近期主要因为什么被讨论
- 最活跃的平台有哪些
- 最受关注的作品/事件是什么

## 2. 研究对象背景（简要）
- 领域：
- 代表身份/机构：
- 近期被高频提及的原因：

## 3. 主要讨论主题
请列出 3–8 个主题，每个主题使用以下格式：

### 主题 N：<主题名称>
- **讨论内容**：
- **为何受到关注**：
- **活跃平台**：
- **代表性作品/事件**：
- **讨论倾向**：正面 / 中性 / 质疑 / 分裂
- **代表来源**：
  - [来源标题](URL)
  - [来源标题](URL)

## 4. 平台活跃度对比
请按平台汇总，建议使用表格：

| 平台 | 活跃度 | 讨论类型 | 代表话题 | 备注 |
|------|--------|----------|----------|------|

活跃度请用：高 / 中 / 低

## 5. 最受关注的作品 / 论文 / 项目 / 事件
请用表格汇总：

| 名称 | 类型 | 讨论焦点 | 热度来源平台 | 代表来源 |
|------|------|----------|--------------|----------|

类型可选：论文 / 模型 / 项目 / 推文 / 演讲 / 采访 / 新闻事件 / 争议事件

## 6. 时间线
按时间顺序列出重要节点：

- **YYYY-MM**：事件 / 发布 / 引爆点
  - 讨论扩散情况：
  - 代表来源：
    - [来源标题](URL)

## 7. 舆论特征总结
从以下角度总结：
- **学术圈怎么看**
- **工程/开发者社区怎么看**
- **社交媒体怎么传播**
- **是否存在争议点或评价分歧**
- **当前热度是在上升、平稳还是回落**

最后必须单独一行输出热度标签，格式严格为（五选一，不要加其他文字）：
【当前热度】极高
【当前热度】较高
【当前热度】一般
【当前热度】较低
【当前热度】极低

判断标准：
- 极高：近 2 年内多个平台持续高频讨论，话题数量多、传播极广，有重大事件引爆全网关注
- 较高：多平台有活跃讨论，话题较多、有一定传播力，但未达到全网级热度
- 一般：有一定讨论但不算密集，可能集中在少数平台或少数话题
- 较低：讨论较少，仅在个别平台有零星提及
- 极低：几乎无公开讨论，搜索结果极少

## 8. 高可信来源清单
请列出 8–20 条最有代表性的来源，按类别分组：
- 原始来源
- 社区讨论
- 技术解读
- 新闻 / 媒体

格式统一为：
- [标题](URL) —— 1 句话说明其价值

## 9. 信息缺口与不确定性
请明确说明：
- 哪些结论证据较强
- 哪些只是局部样本观察
- 哪些平台数据不足或无法完全验证

---

### 额外要求
- 请使用 **中文** 输出。
- 必须使用 **Markdown 链接格式** 引用来源。
- 尽量引用**具体帖子、具体页面、具体文章**，避免只给平台首页。
- 如果同名人物较多，请先判别是否为正确的 AI/ML 研究者，再开始总结。
- 如果该研究者近期公开讨论很少，请明确写出"近 2 年讨论有限"，并说明仍能观察到的主要传播渠道。
- 不要只罗列链接，必须进行归纳、比较和判断。
- 若有代表性论文或项目，请结合标题和主题一起说明，而不是只写名字。
"""

    # Note: sonar doesn't need the outbound proxy since it goes to our internal API
    async with httpx.AsyncClient(timeout=120) as client:
        content, verified_sources = await _query_llm(client, prompt)

    if not content:
        return None

    # Use verified sources from search API when available; fall back to markdown link extraction
    sources = verified_sources if verified_sources else _extract_sources(content)
    topics = _extract_topics(content)
    heat = _classify_heat(content)

    # Upsert BuzzSnapshot
    existing = (await db.execute(
        select(BuzzSnapshot).where(BuzzSnapshot.user_id == user.id)
    )).scalars().first()

    if existing:
        existing.heat_label = heat
        existing.summary = content
        existing.sources = sources
        existing.topics = topics
        existing.refreshed_at = datetime.utcnow()
        snapshot = existing
    else:
        snapshot = BuzzSnapshot(
            user_id=user.id,
            heat_label=heat,
            summary=content,
            sources=sources,
            topics=topics,
            refreshed_at=datetime.utcnow(),
        )
        db.add(snapshot)

    await db.flush()

    logger.info(
        "Buzz refreshed for user %d (%s): heat=%s, sources=%d, topics=%d",
        user.id, name, heat, len(sources), len(topics),
    )
    return snapshot
