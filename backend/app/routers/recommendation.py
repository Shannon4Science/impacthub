"""Resume-based advisor recommendation API."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DATA_DIR, RECOMMENDATION_TOP_N
from app.database import get_db
from app.models import AdvisorCollege, AdvisorSchool, RecommendationSession
from app.schemas import CoverLetterResponse
from app.services import recommendation_service

router = APIRouter()

UPLOAD_ROOT = DATA_DIR / "recommendation_uploads"


class RecommendationUploadResponse(BaseModel):
    session_id: str
    status: str


class RecommendationStatusResponse(BaseModel):
    session_id: str
    status: str
    progress: int
    message: str
    error: str | None = None


class RecommendationResultResponse(BaseModel):
    session_id: str
    recommendations: list[dict[str, Any]]
    resume_summary: dict[str, Any]


@router.post("/recommendation/upload-resume", response_model=RecommendationUploadResponse)
async def upload_resume_for_recommendation(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    requirements: str = Form(""),
    top_n: int = Form(RECOMMENDATION_TOP_N),
    school_id: int | None = Form(None),
    college_id: int | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    filename = file.filename or "resume.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="只支持 PDF 简历")
    if top_n < 1 or top_n > 10:
        raise HTTPException(status_code=400, detail="top_n 必须在 1 到 10 之间")

    if school_id is not None:
        school = await db.get(AdvisorSchool, school_id)
        if not school:
            raise HTTPException(status_code=404, detail="学校不存在")
    if college_id is not None:
        college = await db.get(AdvisorCollege, college_id)
        if not college:
            raise HTTPException(status_code=404, detail="学院不存在")
        if school_id is not None and college.school_id != school_id:
            raise HTTPException(status_code=400, detail="学院不属于所选学校")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="PDF 文件为空")
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF 文件不能超过 20MB")

    session_id = uuid.uuid4().hex
    session_dir = UPLOAD_ROOT / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = session_dir / "resume.pdf"
    pdf_path.write_bytes(content)

    session = RecommendationSession(
        id=session_id,
        status="queued",
        progress=5,
        message="已上传，等待解析",
        resume_filename=Path(filename).name,
        requirements=requirements.strip(),
        top_n=top_n,
        school_id=school_id,
        college_id=college_id,
    )
    db.add(session)
    await db.commit()

    background_tasks.add_task(
        recommendation_service.process_recommendation_session,
        session_id,
        str(pdf_path),
    )
    return RecommendationUploadResponse(session_id=session_id, status="queued")


@router.get("/recommendation/status/{session_id}", response_model=RecommendationStatusResponse)
async def get_recommendation_status(session_id: str, db: AsyncSession = Depends(get_db)):
    session = await db.get(RecommendationSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="推荐任务不存在")
    return RecommendationStatusResponse(
        session_id=session.id,
        status=session.status,
        progress=session.progress,
        message=session.message,
        error=session.error or None,
    )


@router.get("/recommendation/result/{session_id}", response_model=RecommendationResultResponse)
async def get_recommendation_result(session_id: str, db: AsyncSession = Depends(get_db)):
    session = await db.get(RecommendationSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="推荐任务不存在")
    if session.status != "completed":
        raise HTTPException(status_code=409, detail="推荐任务尚未完成")
    result = session.result_json or {}
    return RecommendationResultResponse(
        session_id=session.id,
        recommendations=result.get("recommendations", []),
        resume_summary=result.get("resume_summary", {}),
    )


@router.post(
    "/recommendation/sessions/{session_id}/advisors/{advisor_id}/cover-letter",
    response_model=CoverLetterResponse,
)
async def generate_cover_letter(
    session_id: str,
    advisor_id: int,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await recommendation_service.generate_cover_letter(
            db,
            session_id=session_id,
            advisor_id=advisor_id,
        )
    except recommendation_service.RecommendationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except recommendation_service.RecommendationStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except recommendation_service.RecommendationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
