from copy import deepcopy
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..models import Advisor, AdvisorMention


async def import_xhs_recruitment_summary(
    db: AsyncSession,
    advisor_id: int,
    xhs_summary_json: dict,
    xhs_candidates_jsonl: list[dict],
) -> int:
    """
    从XHS爬虫输出导入招生信息
    1. 将候选帖子导入AdvisorMention表
    2. 将摘要JSON存入Advisor.recruitment_summary_json
    """
    advisor = await db.get(Advisor, advisor_id)
    if not advisor:
        raise ValueError(f"Advisor {advisor_id} not found")

    candidates_by_note_id = {
        str(candidate.get("note_id") or ""): candidate
        for candidate in xhs_candidates_jsonl
        if candidate.get("note_id")
    }
    summary_snapshot = _with_self_contained_evidence(xhs_summary_json, candidates_by_note_id)

    # 1. 导入原始帖子到AdvisorMention
    inserted = 0
    for candidate in xhs_candidates_jsonl:
        external_id = str(candidate.get("note_id") or "").strip()
        url = candidate.get("url", "")
        existing = None
        if external_id:
            stmt = select(AdvisorMention).where(
                AdvisorMention.advisor_id == advisor_id,
                AdvisorMention.source == "xiaohongshu",
                AdvisorMention.external_id == external_id,
            )
            existing = (await db.execute(stmt)).scalar_one_or_none()
            if not existing and url:
                legacy_stmt = select(AdvisorMention).where(
                    AdvisorMention.advisor_id == advisor_id,
                    AdvisorMention.source == "xiaohongshu",
                    AdvisorMention.url == url,
                )
                existing = (await db.execute(legacy_stmt)).scalar_one_or_none()
        elif url:
            stmt = select(AdvisorMention).where(
                AdvisorMention.advisor_id == advisor_id,
                AdvisorMention.source == "xiaohongshu",
                AdvisorMention.external_id == "",
                AdvisorMention.url == url,
            )
            existing = (await db.execute(stmt)).scalar_one_or_none()
        else:
            existing = None
        if existing:
            if external_id and not existing.external_id:
                existing.external_id = external_id
            existing.mention_type = "recruitment"
            continue

        # 解析发布时间
        published_at = None
        raw_published_at = candidate.get("published_at")
        if raw_published_at:
            try:
                if isinstance(raw_published_at, str):
                    published_at = datetime.fromisoformat(raw_published_at.replace("Z", "+00:00"))
                elif isinstance(raw_published_at, (int, float)):
                    published_at = datetime.fromtimestamp(raw_published_at, tz=timezone.utc)
            except (ValueError, OSError):
                pass

        mention = AdvisorMention(
            advisor_id=advisor_id,
            source="xiaohongshu",
            external_id=external_id,
            mention_type="recruitment",
            source_account=candidate.get("author_name", ""),
            title=candidate.get("title", ""),
            url=url,
            snippet=candidate.get("content", "")[:2000],
            likes=candidate.get("likes", 0),
            comments=candidate.get("comment_count", 0),
            tags=candidate.get("matched_keywords", []),
            published_at=published_at,
        )
        db.add(mention)
        inserted += 1

    # 2. 更新Advisor的招生摘要
    advisor.recruitment_summary_json = summary_snapshot
    advisor.recruitment_summary_status = summary_snapshot.get("recruitment_status", "")
    advisor.recruitment_summary_refreshed_at = datetime.now(timezone.utc)

    await db.commit()
    return inserted


async def get_recruitment_summary(db: AsyncSession, advisor_id: int) -> dict | None:
    """获取招生摘要（带缓存逻辑）"""
    advisor = await db.get(Advisor, advisor_id)
    if not advisor or not advisor.recruitment_summary_json:
        return None

    # 检查缓存是否过期（30天）
    cache_status = "fresh"
    if advisor.recruitment_summary_refreshed_at:
        # 确保refreshed_at有时区信息
        refreshed_at = advisor.recruitment_summary_refreshed_at
        if refreshed_at.tzinfo is None:
            refreshed_at = refreshed_at.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - refreshed_at
        if age.days > 30:
            cache_status = "stale"

    # 字段映射：将XHS爬虫的字段名映射到前端API的字段名
    summary_json = advisor.recruitment_summary_json

    # 转换 positions -> targets，并规范化字段结构
    targets = []
    for pos in summary_json.get("positions", []):
        target = {
            "type": pos.get("type", ""),
            "details": [pos.get("detail", "")] if pos.get("detail") else [],  # detail -> details (数组)
            "source_note_ids": pos.get("source_note_ids", []),
            "time_sensitivity": pos.get("time_sensitivity", "unknown"),
        }
        targets.append(target)

    # 转换 directions -> research_directions，并规范化字段结构
    research_directions = []
    for dir_item in summary_json.get("directions", []):
        direction = {
            "direction": dir_item.get("direction", ""),
            "details": [dir_item.get("detail", "")] if dir_item.get("detail") else dir_item.get("details", []),
            "source_note_ids": dir_item.get("source_note_ids", []),
        }
        research_directions.append(direction)

    # 处理 evidence_posts。新摘要应自带 content；旧摘要兼容从 AdvisorMention 回填。
    evidence_posts_raw = summary_json.get("source_posts", []) or summary_json.get("evidence_posts", [])
    evidence_posts = []

    # 旧摘要在迁移前没有把正文快照写进 summary_json，这里只为旧数据兼容回填。
    note_ids = [
        post.get("note_id")
        for post in evidence_posts_raw
        if post.get("note_id") and not post.get("content")
    ]

    # 批量查询 AdvisorMention 获取完整 snippet
    mention_map = {}
    if note_ids:
        stmt = select(AdvisorMention).where(
            AdvisorMention.advisor_id == advisor_id,
            AdvisorMention.external_id.in_(note_ids),
        )
        result = await db.execute(stmt)
        mentions = result.scalars().all()
        for mention in mentions:
            mention_map[mention.external_id] = mention.snippet or ""
        missing_note_ids = [note_id for note_id in note_ids if note_id not in mention_map]
        if missing_note_ids:
            legacy_stmt = select(AdvisorMention).where(
                AdvisorMention.advisor_id == advisor_id,
                AdvisorMention.url.in_(
                    [f"https://www.xiaohongshu.com/explore/{nid}" for nid in missing_note_ids]
                ),
            )
            legacy_mentions = (await db.execute(legacy_stmt)).scalars().all()
            for mention in legacy_mentions:
                if mention.url:
                    mention_map[mention.url.split("/")[-1]] = mention.snippet or ""

    # 组装 evidence_posts，补充 content 字段
    for post in evidence_posts_raw:
        note_id = post.get("note_id", "")
        evidence_post = {
            "note_id": note_id,
            "title": post.get("title", ""),
            "url": post.get("url", ""),
            "published_at": post.get("published_at"),
            "relation_to_target": post.get("relation_to_target", ""),
            "time_sensitivity": post.get("time_sensitivity", ""),
            "content": post.get("content") or mention_map.get(note_id, ""),
        }
        evidence_posts.append(evidence_post)

    return {
        "recruitment_status": summary_json.get("recruitment_status", ""),
        "summary": summary_json.get("summary", ""),
        "latest_post_published_at": summary_json.get("latest_recruitment_post_published_at"),
        "targets": targets,
        "research_directions": research_directions,
        "requirements": summary_json.get("requirements", []),
        "application_methods": summary_json.get("application_methods", []),
        "timeline": summary_json.get("timeline", []),
        "evidence_posts": evidence_posts,
        "missing_information": summary_json.get("limitations", []),  # limitations包含missing_information
        "limitations": summary_json.get("limitations", []),
        "cache_status": cache_status,
        "refreshed_at": advisor.recruitment_summary_refreshed_at.isoformat() if advisor.recruitment_summary_refreshed_at else None,
    }


def _with_self_contained_evidence(
    summary_json: dict,
    candidates_by_note_id: dict[str, dict],
) -> dict:
    summary = deepcopy(summary_json)
    source_posts = summary.get("source_posts")
    if not isinstance(source_posts, list):
        return summary
    enriched_posts = []
    for post in source_posts:
        if not isinstance(post, dict):
            continue
        enriched = dict(post)
        note_id = str(enriched.get("note_id") or "")
        candidate = candidates_by_note_id.get(note_id)
        if candidate:
            enriched["content"] = candidate.get("content", "")
            enriched["author_name"] = candidate.get("author_name", "")
        enriched_posts.append(enriched)
    summary["source_posts"] = enriched_posts
    return summary
