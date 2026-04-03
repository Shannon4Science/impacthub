"""Milestone query endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Milestone, User
from app.schemas import MilestoneOut
from app.deps import resolve_user

router = APIRouter()


@router.get("/milestones/{identifier}", response_model=list[MilestoneOut])
async def get_milestones(
    user: User = Depends(resolve_user),
    db: AsyncSession = Depends(get_db),
):
    milestones = (
        await db.execute(
            select(Milestone)
            .where(Milestone.user_id == user.id)
            .order_by(Milestone.achieved_at.desc())
        )
    ).scalars().all()

    return [MilestoneOut.model_validate(m) for m in milestones]
