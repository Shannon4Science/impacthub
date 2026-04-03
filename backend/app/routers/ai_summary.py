"""AI Summary API endpoints."""

from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, AISummary
from app.services import ai_summary_service
from app.deps import resolve_user

router = APIRouter()


class AISummaryOut(BaseModel):
    user_id: int
    summary: str
    tags: list[str]
    refreshed_at: str | None

    model_config = {"from_attributes": True}


@router.get("/ai-summary/{identifier}", response_model=AISummaryOut | None)
async def get_ai_summary(
    user: User = Depends(resolve_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(AISummary).where(AISummary.user_id == user.id)
    )).scalars().first()
    if not row:
        return None
    return AISummaryOut(
        user_id=row.user_id,
        summary=row.summary,
        tags=row.tags or [],
        refreshed_at=row.refreshed_at.isoformat() if row.refreshed_at else None,
    )


@router.post("/ai-summary/{identifier}/refresh")
async def refresh_ai_summary(
    background_tasks: BackgroundTasks,
    user: User = Depends(resolve_user),
):
    background_tasks.add_task(_do_refresh, user.id)
    return {"status": "refreshing"}


async def _do_refresh(user_id: int):
    from app.database import async_session
    async with async_session() as db:
        user = await db.get(User, user_id)
        if not user:
            return
        await ai_summary_service.refresh_ai_summary(db, user)
        await db.commit()
