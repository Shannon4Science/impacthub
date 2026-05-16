"""Resume-based advisor recommendation workflow."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import sqlite_vec
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import (
    DASHSCOPE_API_KEY,
    DASHSCOPE_BASE_URL,
    DASHSCOPE_EMBEDDING_DIMENSIONS,
    DASHSCOPE_EMBEDDING_MODEL,
    LLM_API_BASE,
    LLM_API_KEY,
    LLM_FALLBACK_MODEL,
    MINERU_PATH,
)
from app.database import async_session
from app.models import (
    Advisor,
    AdvisorCollege,
    AdvisorEmbeddingMetadata,
    AdvisorSchool,
    Paper,
    RecommendationSession,
)

logger = logging.getLogger(__name__)

MAX_RESUME_CHARS = 20000
MAX_ADVISOR_SOURCE_CHARS = 6000


class RecommendationError(RuntimeError):
    """Expected recommendation workflow failure."""


class RecommendationNotFoundError(RecommendationError):
    """Requested recommendation resource does not exist."""


class RecommendationStateError(RecommendationError):
    """Requested recommendation operation is invalid for current session state."""


RESUME_JSON_SCHEMA: dict[str, Any] = {
    "education": [],
    "research_interests": [],
    "projects": [],
    "publications": [],
    "skills": [],
    "honors": [],
}


def _as_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict):
                joined = " ".join(str(v).strip() for v in item.values() if str(v).strip())
                if joined:
                    out.append(joined)
        return out
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _compact_json(value: Any, max_chars: int = 5000) -> str:
    return json.dumps(value or {}, ensure_ascii=False, indent=2)[:max_chars]


def _normalize_resume_info(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(RESUME_JSON_SCHEMA)
    normalized.update({k: v for k, v in data.items() if k in normalized})
    normalized["education"] = normalized["education"] if isinstance(normalized["education"], list) else []
    normalized["projects"] = normalized["projects"] if isinstance(normalized["projects"], list) else []
    normalized["publications"] = _as_str_list(normalized["publications"])
    normalized["research_interests"] = _as_str_list(normalized["research_interests"])
    normalized["skills"] = _as_str_list(normalized["skills"])
    normalized["honors"] = _as_str_list(normalized["honors"])
    return normalized


def _parse_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise RecommendationError("LLM 未返回合法 JSON") from None
        try:
            parsed = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as exc:
            raise RecommendationError("LLM 未返回合法 JSON") from exc
    if not isinstance(parsed, dict):
        raise RecommendationError("LLM 返回 JSON 不是对象")
    return parsed


async def _set_session(
    db: AsyncSession,
    session_id: str,
    *,
    status: str | None = None,
    progress: int | None = None,
    message: str | None = None,
    error: str | None = None,
    resume_text: str | None = None,
    resume_summary_json: dict[str, Any] | None = None,
    result_json: dict[str, Any] | None = None,
) -> None:
    session = await db.get(RecommendationSession, session_id)
    if not session:
        raise RecommendationError(f"推荐任务不存在：{session_id}")
    if status is not None:
        session.status = status
    if progress is not None:
        session.progress = progress
    if message is not None:
        session.message = message[:300]
    if error is not None:
        session.error = error
    if resume_text is not None:
        session.resume_text = resume_text
    if resume_summary_json is not None:
        session.resume_summary_json = resume_summary_json
    if result_json is not None:
        session.result_json = result_json
    await db.commit()


async def parse_resume_with_mineru(pdf_path: Path, output_dir: Path) -> str:
    """Parse a PDF resume with MinerU and return the generated Markdown text."""
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [MINERU_PATH, "-p", str(pdf_path), "-o", str(output_dir), "-b", "pipeline"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RecommendationError(f"找不到 MinerU 命令：{MINERU_PATH}") from exc

    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        detail = (stderr or stdout).decode("utf-8", errors="ignore").strip()
        raise RecommendationError(f"MinerU 解析失败：{detail[:500]}")

    md_files = sorted(
        output_dir.rglob("*.md"),
        key=lambda p: p.stat().st_size if p.exists() else 0,
        reverse=True,
    )
    if not md_files:
        raise RecommendationError("MinerU 未生成 Markdown 文件")
    markdown_text = md_files[0].read_text(encoding="utf-8", errors="ignore").strip()
    if not markdown_text:
        raise RecommendationError("MinerU 生成的 Markdown 为空")
    return markdown_text


async def extract_resume_info(markdown_text: str) -> dict[str, Any]:
    """Convert resume Markdown into structured JSON with the configured LLM."""
    if not LLM_API_BASE or not LLM_API_KEY:
        raise RecommendationError("缺少 LLM_API_BASE 或 LLM_API_KEY，无法结构化简历")

    prompt = f"""你是保研导师推荐系统的信息抽取器。请把下面的简历 Markdown 抽取成一个合法 JSON 对象。

硬性规则：
1. 只输出 JSON 对象本身，第一字符必须是 {{，最后字符必须是 }}。
2. 不要输出 ```、markdown、解释、前后缀文本。
3. 所有字符串值必须是单行字符串；原文里的换行、项目符号、制表符都改成一个空格。
4. 字符串里的英文双引号改成中文引号，避免破坏 JSON。
5. 缺失信息用空数组 [] 或空字符串 ""，不要输出 null。

字段固定为：education, research_interests, projects, publications, skills, honors。
education 数组元素：{{"school":"","major":"","degree":"","gpa":""}}
projects 数组元素：{{"name":"","description":"","tech_stack":[],"achievements":""}}

简历 Markdown：
{markdown_text[:MAX_RESUME_CHARS]}
"""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{LLM_API_BASE.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": LLM_FALLBACK_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            },
        )
    if resp.status_code != 200:
        raise RecommendationError(f"LLM 简历抽取失败：HTTP {resp.status_code} {resp.text[:300]}")
    content = resp.json()["choices"][0]["message"].get("content", "")
    parsed = _parse_json_object(content)
    return _normalize_resume_info(parsed)


async def generate_embedding(text: str) -> list[float]:
    """Generate a 1024-d embedding through DashScope OpenAI-compatible API."""
    if not DASHSCOPE_API_KEY:
        raise RecommendationError("缺少 DASHSCOPE_API_KEY，无法生成向量")
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        raise RecommendationError("向量化文本为空")
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{DASHSCOPE_BASE_URL}/embeddings",
            headers={"Authorization": f"Bearer {DASHSCOPE_API_KEY}"},
            json={
                "model": DASHSCOPE_EMBEDDING_MODEL,
                "input": cleaned,
                "dimensions": DASHSCOPE_EMBEDDING_DIMENSIONS,
                "encoding_format": "float",
            },
        )
    if resp.status_code != 200:
        raise RecommendationError(f"Embedding 生成失败：HTTP {resp.status_code} {resp.text[:300]}")
    data = resp.json()
    embedding = data.get("data", [{}])[0].get("embedding")
    if not isinstance(embedding, list) or len(embedding) != DASHSCOPE_EMBEDDING_DIMENSIONS:
        raise RecommendationError("Embedding 返回维度不符合配置")
    return [float(x) for x in embedding]


def build_resume_embedding_text(resume_info: dict[str, Any], requirements: str) -> str:
    project_lines: list[str] = []
    for p in resume_info.get("projects", []):
        if not isinstance(p, dict):
            continue
        project_lines.append(
            " ".join(
                str(x)
                for x in [
                    p.get("name", ""),
                    p.get("description", ""),
                    " ".join(_as_str_list(p.get("tech_stack"))),
                    p.get("achievements", ""),
                ]
                if str(x).strip()
            )
        )
    education_lines = []
    for edu in resume_info.get("education", []):
        if isinstance(edu, dict):
            education_lines.append(" ".join(str(v) for v in edu.values() if str(v).strip()))
    return "\n".join(
        part
        for part in [
            f"用户要求：{requirements.strip()}",
            "教育背景：" + "；".join(education_lines),
            "研究兴趣：" + "；".join(_as_str_list(resume_info.get("research_interests"))),
            "项目经历：" + "；".join(project_lines),
            "论文成果：" + "；".join(_as_str_list(resume_info.get("publications"))),
            "技能：" + "；".join(_as_str_list(resume_info.get("skills"))),
            "荣誉：" + "；".join(_as_str_list(resume_info.get("honors"))),
        ]
        if part.strip("：").strip()
    )


def build_advisor_embedding_text(advisor: Advisor, school: AdvisorSchool, college: AdvisorCollege) -> str:
    parts = [
        f"导师：{advisor.name}",
        f"学校：{school.name}",
        f"学院：{college.name}",
        f"职称：{advisor.title}",
        "研究方向：" + "；".join(_as_str_list(advisor.research_areas)),
        "简介：" + (advisor.bio or ""),
        "荣誉：" + "；".join(_as_str_list(advisor.honors)),
        "招生信息：" + (advisor.recruiting_intent or ""),
    ]
    return "\n".join(p for p in parts if p.strip("：").strip())[:MAX_ADVISOR_SOURCE_CHARS]


def _source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tokenize_terms(text: str) -> list[str]:
    terms: list[str] = []
    for item in re.findall(r"[A-Za-z][A-Za-z0-9_+\-]{1,}|[\u4e00-\u9fff]{2,}", text):
        normalized = item.strip().lower()
        if normalized and normalized not in terms:
            terms.append(normalized)
    return terms


def _resume_terms(resume_info: dict[str, Any], requirements: str) -> list[str]:
    parts = [requirements]
    parts.extend(_as_str_list(resume_info.get("research_interests")))
    parts.extend(_as_str_list(resume_info.get("skills")))
    parts.extend(_as_str_list(resume_info.get("publications")))
    for project in resume_info.get("projects", []):
        if isinstance(project, dict):
            parts.extend(str(project.get(k, "")) for k in ("name", "description", "achievements"))
            parts.extend(_as_str_list(project.get("tech_stack")))
    return _tokenize_terms(" ".join(parts))


def _matched_keywords(resume_info: dict[str, Any], requirements: str, advisor: Advisor) -> list[str]:
    resume_terms = _resume_terms(resume_info, requirements)
    advisor_terms = _tokenize_terms(" ".join(_as_str_list(advisor.research_areas)) + " " + (advisor.bio or ""))
    matches: list[str] = []
    for term in resume_terms:
        if len(term) < 2:
            continue
        if any(term == at or term in at or at in term for at in advisor_terms):
            matches.append(term)
        if len(matches) >= 8:
            break
    return matches


def _advisor_payload(
    advisor: Advisor,
    school: AdvisorSchool,
    college: AdvisorCollege,
) -> dict[str, Any]:
    return {
        "id": advisor.id,
        "name": advisor.name,
        "title": advisor.title,
        "school_id": advisor.school_id,
        "school_name": school.name,
        "college_id": advisor.college_id,
        "college_name": college.name,
        "is_doctoral_supervisor": advisor.is_doctoral_supervisor,
        "is_master_supervisor": advisor.is_master_supervisor,
        "research_areas": _as_str_list(advisor.research_areas),
        "homepage_url": advisor.homepage_url,
        "photo_url": advisor.photo_url,
        "h_index": advisor.h_index,
        "citation_count": advisor.citation_count,
        "accepts_recommended": advisor.accepts_recommended,
        "recruitment_summary_status": advisor.recruitment_summary_status,
    }


def _recruitment_summary_text(value: dict[str, Any] | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    summary = str(value.get("summary") or "").strip()
    if summary:
        parts.append(f"摘要：{summary}")
    status = str(value.get("recruitment_status") or "").strip()
    if status:
        parts.append(f"状态：{status}")
    for key, label in [
        ("positions", "招生对象"),
        ("directions", "招生方向"),
        ("requirements", "要求"),
        ("application_methods", "申请方式"),
    ]:
        items = value.get(key)
        if isinstance(items, list) and items:
            parts.append(f"{label}：{_compact_json(items, 1200)}")
    limitations = _as_str_list(value.get("limitations"))
    if limitations:
        parts.append("限制：" + "；".join(limitations[:3]))
    return "\n".join(parts)[:4000]


async def _representative_papers(db: AsyncSession, advisor: Advisor) -> list[dict[str, Any]]:
    if not advisor.impacthub_user_id:
        return []
    rows = (
        await db.execute(
            select(Paper)
            .where(Paper.user_id == advisor.impacthub_user_id)
            .order_by(Paper.citation_count.desc(), Paper.year.desc())
            .limit(3)
        )
    ).scalars().all()
    return [
        {
            "title": p.title,
            "year": p.year,
            "venue": p.venue,
            "citation_count": p.citation_count,
        }
        for p in rows
    ]


def _build_cover_letter_prompt(
    *,
    resume_info: dict[str, Any],
    requirements: str,
    advisor: Advisor,
    school: AdvisorSchool,
    college: AdvisorCollege,
    representative_papers: list[dict[str, Any]],
) -> str:
    recruitment_text = _recruitment_summary_text(advisor.recruitment_summary_json)
    papers_text = _compact_json(representative_papers, 2500) if representative_papers else "无已关联代表论文"
    advisor_info = {
        "name": advisor.name,
        "title": advisor.title,
        "school": school.name,
        "college": college.name,
        "research_areas": _as_str_list(advisor.research_areas),
        "bio": advisor.bio[:1500] if advisor.bio else "",
        "honors": _as_str_list(advisor.honors),
        "recruiting_intent": advisor.recruiting_intent,
        "recruitment_summary": recruitment_text,
        "representative_papers": representative_papers,
    }
    return f"""你是一位申请研究生的学生，需要给导师写一封中文套磁信正文。

硬性规则：
1. 只输出邮件正文，不要标题、解释、Markdown 代码块。
2. 正文总长度严格控制在 300 到 450 个中文字符，最多 4 段，不写署名和日期。
3. 第一行用「{advisor.name}老师：」开头。
4. 结构必须自然覆盖：自我介绍、研究兴趣匹配、相关经历、未来规划、礼貌结尾。
5. 必须从学生简历里挑最相关的经历/技能，不要泛泛夸导师。
6. 只能使用下面给出的导师信息，不能编造论文、项目、招生名额、联系方式。
7. 如果代表论文为“无已关联代表论文”，不要写“我阅读了您的某篇论文”，改为具体提及研究方向或主页简介中的研究主题。
8. 语气真诚、谦逊但不卑微。

学生补充要求：
{requirements.strip() or "无"}

学生简历结构化信息：
{_compact_json(resume_info, 7000)}

导师信息：
{_compact_json(advisor_info, 7000)}

代表论文：
{papers_text}

请直接生成套磁信正文："""


async def generate_cover_letter(
    db: AsyncSession,
    *,
    session_id: str,
    advisor_id: int,
) -> dict[str, Any]:
    """Generate an editable advisor outreach letter from a completed recommendation session."""
    if not LLM_API_BASE or not LLM_API_KEY:
        raise RecommendationError("缺少 LLM_API_BASE 或 LLM_API_KEY，无法生成套磁信")

    session = await db.get(RecommendationSession, session_id)
    if not session:
        raise RecommendationNotFoundError("推荐任务不存在")
    if session.status != "completed":
        raise RecommendationStateError("推荐任务尚未完成，不能生成套磁信")
    if not session.resume_summary_json:
        raise RecommendationStateError("推荐任务缺少简历结构化信息")

    result_json = session.result_json or {}
    recommended_ids: set[int] = set()
    for item in result_json.get("recommendations", []):
        if not isinstance(item, dict):
            continue
        advisor_payload = item.get("advisor")
        if not isinstance(advisor_payload, dict):
            continue
        payload_id = advisor_payload.get("id")
        if payload_id is not None:
            recommended_ids.add(int(payload_id))
    if advisor_id not in recommended_ids:
        raise RecommendationStateError("该导师不在本次推荐结果中")

    row = (
        await db.execute(
            select(Advisor, AdvisorSchool, AdvisorCollege)
            .join(AdvisorSchool, AdvisorSchool.id == Advisor.school_id)
            .join(AdvisorCollege, AdvisorCollege.id == Advisor.college_id)
            .where(Advisor.id == advisor_id)
        )
    ).first()
    if not row:
        raise RecommendationNotFoundError("导师不存在")
    advisor, school, college = row

    papers = await _representative_papers(db, advisor)
    prompt = _build_cover_letter_prompt(
        resume_info=session.resume_summary_json,
        requirements=session.requirements,
        advisor=advisor,
        school=school,
        college=college,
        representative_papers=papers,
    )
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{LLM_API_BASE.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": LLM_FALLBACK_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
            },
        )
    if resp.status_code != 200:
        raise RecommendationError(f"LLM 套磁信生成失败：HTTP {resp.status_code} {resp.text[:300]}")
    try:
        content = resp.json()["choices"][0]["message"].get("content", "").strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RecommendationError("LLM 套磁信响应结构不符合 OpenAI Chat Completions 格式") from exc
    if not content:
        raise RecommendationError("LLM 套磁信生成结果为空")
    if "```" in content:
        raise RecommendationError("LLM 返回了 Markdown 代码块，拒绝作为套磁信正文")
    return {
        "content": content,
        "advisor_name": advisor.name,
        "generated_at": datetime.now(timezone.utc),
    }


async def _advisor_rows(
    db: AsyncSession,
    *,
    school_id: int | None,
    college_id: int | None,
) -> list[tuple[Advisor, AdvisorSchool, AdvisorCollege]]:
    stmt = (
        select(Advisor, AdvisorSchool, AdvisorCollege)
        .join(AdvisorSchool, AdvisorSchool.id == Advisor.school_id)
        .join(AdvisorCollege, AdvisorCollege.id == Advisor.college_id)
        .where(Advisor.research_areas.is_not(None))
    )
    if school_id:
        stmt = stmt.where(Advisor.school_id == school_id)
    if college_id:
        stmt = stmt.where(Advisor.college_id == college_id)
    rows = list((await db.execute(stmt)).all())
    return [(a, s, c) for a, s, c in rows if _as_str_list(a.research_areas)]


async def ensure_advisor_embeddings(
    db: AsyncSession,
    *,
    school_id: int | None = None,
    college_id: int | None = None,
) -> int:
    """Generate or refresh advisor embeddings for the current recommendation scope."""
    rows = await _advisor_rows(db, school_id=school_id, college_id=college_id)
    if not rows:
        raise RecommendationError("筛选范围内没有带研究方向的导师")
    generated = 0
    for advisor, school, college in rows:
        source_text = build_advisor_embedding_text(advisor, school, college)
        digest = _source_hash(source_text)
        existing = await db.get(AdvisorEmbeddingMetadata, advisor.id)
        if (
            existing
            and existing.source_hash == digest
            and existing.model == DASHSCOPE_EMBEDDING_MODEL
            and existing.dimensions == DASHSCOPE_EMBEDDING_DIMENSIONS
            and await _advisor_vector_exists(db, advisor.id)
        ):
            continue
        embedding = await generate_embedding(source_text)
        await _upsert_advisor_vector(db, advisor.id, embedding)
        if existing:
            existing.source_hash = digest
            existing.source_text = source_text
            existing.model = DASHSCOPE_EMBEDDING_MODEL
            existing.dimensions = DASHSCOPE_EMBEDDING_DIMENSIONS
        else:
            db.add(
                AdvisorEmbeddingMetadata(
                    advisor_id=advisor.id,
                    source_hash=digest,
                    source_text=source_text,
                    model=DASHSCOPE_EMBEDDING_MODEL,
                    dimensions=DASHSCOPE_EMBEDDING_DIMENSIONS,
                )
            )
        generated += 1
        await db.commit()
    return generated


async def _advisor_vector_exists(db: AsyncSession, advisor_id: int) -> bool:
    row = (
        await db.execute(
            text("SELECT rowid FROM advisor_embedding_vec WHERE rowid = :advisor_id"),
            {"advisor_id": advisor_id},
        )
    ).first()
    return row is not None


async def _upsert_advisor_vector(db: AsyncSession, advisor_id: int, embedding: list[float]) -> None:
    await db.execute(
        text("DELETE FROM advisor_embedding_vec WHERE rowid = :advisor_id"),
        {"advisor_id": advisor_id},
    )
    await db.execute(
        text("INSERT INTO advisor_embedding_vec(rowid, embedding) VALUES (:advisor_id, :embedding)"),
        {
            "advisor_id": advisor_id,
            "embedding": sqlite_vec.serialize_float32(embedding),
        },
    )


async def _count_vector_candidates(
    db: AsyncSession,
    *,
    school_id: int | None,
    college_id: int | None,
) -> int:
    clauses = []
    params: dict[str, Any] = {}
    if school_id:
        clauses.append("a.school_id = :school_id")
        params["school_id"] = school_id
    if college_id:
        clauses.append("a.college_id = :college_id")
        params["college_id"] = college_id
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    count = (
        await db.execute(
            text(
                f"""
                SELECT COUNT(*)
                FROM advisor_embedding_vec v
                JOIN advisors a ON a.id = v.rowid
                {where}
                """
            ),
            params,
        )
    ).scalar_one()
    return int(count)


async def _count_all_vectors(db: AsyncSession) -> int:
    count = (await db.execute(text("SELECT COUNT(*) FROM advisor_embedding_vec"))).scalar_one()
    return int(count)


async def _query_vector_matches(
    db: AsyncSession,
    *,
    resume_embedding: list[float],
    top_n: int,
    search_k: int,
    school_id: int | None,
    college_id: int | None,
) -> list[tuple[int, float]]:
    clauses = ["v.embedding MATCH :embedding", "v.k = :search_k"]
    params: dict[str, Any] = {
        "embedding": sqlite_vec.serialize_float32(resume_embedding),
        "search_k": search_k,
        "limit": top_n,
    }
    if school_id:
        clauses.append("a.school_id = :school_id")
        params["school_id"] = school_id
    if college_id:
        clauses.append("a.college_id = :college_id")
        params["college_id"] = college_id

    rows = (
        await db.execute(
            text(
                f"""
                SELECT v.rowid AS advisor_id, v.distance AS distance
                FROM advisor_embedding_vec v
                JOIN advisors a ON a.id = v.rowid
                WHERE {' AND '.join(clauses)}
                ORDER BY v.distance ASC
                LIMIT :limit
                """
            ),
            params,
        )
    ).all()
    return [(int(row.advisor_id), float(row.distance)) for row in rows]


async def recommend_advisors(
    db: AsyncSession,
    *,
    resume_info: dict[str, Any],
    requirements: str,
    top_n: int,
    school_id: int | None,
    college_id: int | None,
    ensure_embeddings: bool = True,
) -> list[dict[str, Any]]:
    if ensure_embeddings:
        await ensure_advisor_embeddings(db, school_id=school_id, college_id=college_id)
    resume_embedding = await generate_embedding(build_resume_embedding_text(resume_info, requirements))

    candidate_count = await _count_vector_candidates(db, school_id=school_id, college_id=college_id)
    if candidate_count == 0:
        raise RecommendationError("筛选范围内没有可用导师向量")
    total_vector_count = await _count_all_vectors(db)
    search_k = total_vector_count if school_id or college_id else min(candidate_count, top_n)
    vector_matches = await _query_vector_matches(
        db,
        resume_embedding=resume_embedding,
        top_n=top_n,
        search_k=search_k,
        school_id=school_id,
        college_id=college_id,
    )
    if not vector_matches:
        raise RecommendationError("sqlite-vec 未返回推荐结果")

    advisor_ids = [advisor_id for advisor_id, _distance in vector_matches]
    stmt = (
        select(Advisor, AdvisorSchool, AdvisorCollege)
        .join(AdvisorSchool, AdvisorSchool.id == Advisor.school_id)
        .join(AdvisorCollege, AdvisorCollege.id == Advisor.college_id)
        .where(Advisor.id.in_(advisor_ids))
    )
    advisor_rows = {
        advisor.id: (advisor, school, college)
        for advisor, school, college in (await db.execute(stmt)).all()
    }

    scored: list[dict[str, Any]] = []
    for advisor_id, distance in vector_matches:
        row = advisor_rows.get(advisor_id)
        if not row:
            continue
        advisor, school, college = row
        raw_cosine = 1.0 - distance
        display_similarity = max(0.0, min(1.0, raw_cosine))
        keywords = _matched_keywords(resume_info, requirements, advisor)
        if keywords:
            explanation = (
                f"简历和需求中的「{'、'.join(keywords[:3])}」与导师研究方向重合，"
                f"向量匹配度为 {display_similarity:.0%}。"
            )
        else:
            explanation = f"整体语义向量匹配度为 {display_similarity:.0%}，建议查看导师主页确认细分方向。"
        scored.append(
            {
                "advisor": _advisor_payload(advisor, school, college),
                "similarity": round(display_similarity, 4),
                "raw_cosine": round(raw_cosine, 6),
                "matched_keywords": keywords,
                "explanation": explanation,
            }
        )

    return scored


async def process_recommendation_session(session_id: str, pdf_path: str) -> None:
    """Background job entry point."""
    async with async_session() as db:
        try:
            session = await db.get(RecommendationSession, session_id)
            if not session:
                raise RecommendationError(f"推荐任务不存在：{session_id}")

            base_dir = Path(pdf_path).resolve().parent
            await _set_session(db, session_id, status="parsing", progress=15, message="正在解析 PDF")
            markdown = await parse_resume_with_mineru(Path(pdf_path), base_dir / "mineru")

            await _set_session(
                db,
                session_id,
                status="extracting",
                progress=35,
                message="正在抽取简历关键信息",
                resume_text=markdown,
            )
            resume_info = await extract_resume_info(markdown)

            await _set_session(
                db,
                session_id,
                status="embedding",
                progress=55,
                message="正在生成简历与导师向量",
                resume_summary_json=resume_info,
            )
            generated_count = await ensure_advisor_embeddings(
                db,
                school_id=session.school_id,
                college_id=session.college_id,
            )

            await _set_session(
                db,
                session_id,
                status="recommending",
                progress=78,
                message=f"正在匹配导师，已补齐 {generated_count} 个导师向量",
            )
            recommendations = await recommend_advisors(
                db,
                resume_info=resume_info,
                requirements=session.requirements,
                top_n=session.top_n,
                school_id=session.school_id,
                college_id=session.college_id,
                ensure_embeddings=False,
            )
            result = {
                "recommendations": recommendations,
                "resume_summary": resume_info,
            }
            await _set_session(
                db,
                session_id,
                status="completed",
                progress=100,
                message="推荐完成",
                result_json=result,
            )
        except Exception as exc:
            logger.exception("Recommendation session %s failed", session_id)
            async with async_session() as fail_db:
                await _set_session(
                    fail_db,
                    session_id,
                    status="failed",
                    progress=100,
                    message="推荐失败",
                    error=str(exc),
                )
            raise
