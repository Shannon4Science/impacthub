"""Shared FastAPI dependencies."""

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User


async def resolve_user(
    identifier: str,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve a user by numeric ID, scholar_id, or github_username."""
    user = None
    if identifier.isdigit():
        user = await db.get(User, int(identifier))
        if not user:
            user = (
                await db.execute(
                    select(User).where(User.scholar_id == identifier)
                )
            ).scalars().first()
    else:
        user = (
            await db.execute(
                select(User).where(User.scholar_id == identifier)
            )
        ).scalars().first()
        if not user:
            user = (
                await db.execute(
                    select(User).where(User.github_username == identifier)
                )
            ).scalars().first()
    if not user:
        raise HTTPException(404, "User not found")
    return user
