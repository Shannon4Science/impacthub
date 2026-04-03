"""Recompute CCF rank for all papers based on current venue.
Run after scholar/DBLP sync so CCF list changes take effect."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Paper, User
from app.data.ccf_venues import lookup_ccf_rank

logger = logging.getLogger(__name__)


async def recompute_ccf_for_user(db: AsyncSession, user: User) -> int:
    """Re-apply CCF lookup to all papers for a user. Returns count of updated papers."""
    papers = (
        await db.execute(select(Paper).where(Paper.user_id == user.id))
    ).scalars().all()

    updated = 0
    for p in papers:
        ccf = lookup_ccf_rank(p.venue or "")
        new_rank = ccf[0] if ccf else ""
        new_cat = ccf[1] if ccf else ""
        if (p.ccf_rank or "") != new_rank or (p.ccf_category or "") != new_cat:
            p.ccf_rank = new_rank
            p.ccf_category = new_cat
            updated += 1

    if updated:
        logger.info("Recomputed CCF for %d papers (user %d)", updated, user.id)
    return updated
