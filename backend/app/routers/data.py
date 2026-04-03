"""Manual data refresh endpoint."""

from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.deps import resolve_user

router = APIRouter()


@router.post("/refresh/{identifier}")
async def refresh_user_data(
    background_tasks: BackgroundTasks,
    user: User = Depends(resolve_user),
):
    from app.routers.profile import _full_refresh
    background_tasks.add_task(_full_refresh, user.id)
    return {"status": "refresh_started", "user_id": user.id}
