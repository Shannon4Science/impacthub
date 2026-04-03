"""Buzz API endpoints."""

from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, BuzzSnapshot
from app.services import buzz_service
from app.deps import resolve_user

router = APIRouter()


class BuzzOut(BaseModel):
    user_id: int
    heat_label: str
    summary: str
    sources: list[dict]
    topics: list[str]
    refreshed_at: str | None

    model_config = {"from_attributes": True}


@router.get("/buzz/{identifier}", response_model=BuzzOut | None)
async def get_buzz(
    user: User = Depends(resolve_user),
    db: AsyncSession = Depends(get_db),
):
    snapshot = (await db.execute(
        select(BuzzSnapshot).where(BuzzSnapshot.user_id == user.id)
    )).scalars().first()
    if not snapshot:
        return None
    return BuzzOut(
        user_id=snapshot.user_id,
        heat_label=snapshot.heat_label,
        summary=snapshot.summary,
        sources=snapshot.sources or [],
        topics=snapshot.topics or [],
        refreshed_at=snapshot.refreshed_at.isoformat() if snapshot.refreshed_at else None,
    )


@router.post("/buzz/{identifier}/refresh")
async def refresh_buzz(
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
        await buzz_service.refresh_buzz(db, user)
        await db.commit()
