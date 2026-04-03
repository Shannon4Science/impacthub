"""Hugging Face API client for fetching user models and datasets."""

import logging
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import HUGGINGFACE_API, OUTBOUND_PROXY
from app.models import HFItem, User

logger = logging.getLogger(__name__)


async def _fetch_hf_items(
    client: httpx.AsyncClient,
    username: str,
    item_type: str,
) -> list[dict]:
    """Fetch models or datasets for a HF user."""
    resp = await client.get(
        f"{HUGGINGFACE_API}/{item_type}s",
        params=[
            ("author", username),
            ("limit", "500"),
            ("expand[]", "downloadsAllTime"),
            ("expand[]", "downloads"),
            ("expand[]", "likes"),
        ],
    )
    if resp.status_code != 200:
        logger.warning("HF %s fetch failed: %s", item_type, resp.text)
        return []
    return resp.json()


async def fetch_hf_items_for_user(db: AsyncSession, user: User) -> list[HFItem]:
    """Fetch all models and datasets for an HF user and upsert into DB."""
    if not user.hf_username:
        return []

    async with httpx.AsyncClient(timeout=30, proxy=OUTBOUND_PROXY) as client:
        models_raw = await _fetch_hf_items(client, user.hf_username, "model")
        datasets_raw = await _fetch_hf_items(client, user.hf_username, "dataset")

    existing = {
        item.item_id: item
        for item in (await db.execute(select(HFItem).where(HFItem.user_id == user.id))).scalars().all()
    }

    result: list[HFItem] = []

    for raw in models_raw:
        mid = raw.get("id", "")
        dl = raw.get("downloadsAllTime") or raw.get("downloads", 0) or 0
        if mid in existing:
            item = existing[mid]
            item.downloads = dl
            item.likes = raw.get("likes", 0) or 0
            item.updated_at = datetime.utcnow()
        else:
            item = HFItem(
                user_id=user.id,
                item_id=mid,
                item_type="model",
                name=mid.split("/")[-1] if "/" in mid else mid,
                downloads=dl,
                likes=raw.get("likes", 0) or 0,
                url=f"https://huggingface.co/{mid}",
            )
            db.add(item)
        result.append(item)

    for raw in datasets_raw:
        did = raw.get("id", "")
        dl = raw.get("downloadsAllTime") or raw.get("downloads", 0) or 0
        if did in existing:
            item = existing[did]
            item.downloads = dl
            item.likes = raw.get("likes", 0) or 0
            item.updated_at = datetime.utcnow()
        else:
            item = HFItem(
                user_id=user.id,
                item_id=did,
                item_type="dataset",
                name=did.split("/")[-1] if "/" in did else did,
                downloads=dl,
                likes=raw.get("likes", 0) or 0,
                url=f"https://huggingface.co/datasets/{did}",
            )
            db.add(item)
        result.append(item)

    await db.commit()
    logger.info("Synced %d HF items for user %d", len(result), user.id)
    return result
