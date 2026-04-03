"""Semantic Scholar API client for fetching author papers and citation data."""

import asyncio
import logging
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import SEMANTIC_SCHOLAR_API, OUTBOUND_PROXY
from app.models import Paper, User
from app.data.ccf_venues import lookup_ccf_rank

logger = logging.getLogger(__name__)

AUTHOR_FIELDS = "authorId,name,paperCount,citationCount,hIndex,url"
PAPER_FIELDS = "paperId,title,year,venue,citationCount,authors,url,externalIds"

MAX_PAPERS_PER_REQUEST = 500
MAX_RETRIES = 3
RETRY_BASE_DELAY = 5  # seconds, doubles each retry


async def _find_author_id(client: httpx.AsyncClient, scholar_id: str) -> str | None:
    """Resolve a Semantic Scholar author ID from a Scholar ID or name query."""
    if scholar_id.isdigit() or len(scholar_id) > 20:
        return scholar_id
    resp = await client.get(
        f"{SEMANTIC_SCHOLAR_API}/author/search",
        params={"query": scholar_id, "fields": AUTHOR_FIELDS, "limit": 1},
    )
    if resp.status_code != 200:
        logger.warning("Author search failed: %s", resp.text)
        return None
    data = resp.json().get("data", [])
    return data[0]["authorId"] if data else None


async def fetch_papers_for_user(db: AsyncSession, user: User) -> list[Paper]:
    """Fetch all papers for a user from Semantic Scholar and upsert into DB."""
    if not user.scholar_id:
        return []

    async with httpx.AsyncClient(timeout=30, proxy=OUTBOUND_PROXY) as client:
        author_id = await _find_author_id(client, user.scholar_id)
        if not author_id:
            logger.warning("Could not resolve author ID for %s", user.scholar_id)
            return []

        if not user.name or not user.avatar_url:
            info_resp = await client.get(
                f"{SEMANTIC_SCHOLAR_API}/author/{author_id}",
                params={"fields": AUTHOR_FIELDS},
            )
            if info_resp.status_code == 200:
                info = info_resp.json()
                if not user.name:
                    user.name = info.get("name", "")

        all_papers_raw: list[dict] = []
        offset = 0
        while True:
            resp = None
            for attempt in range(MAX_RETRIES):
                resp = await client.get(
                    f"{SEMANTIC_SCHOLAR_API}/author/{author_id}/papers",
                    params={"fields": PAPER_FIELDS, "limit": MAX_PAPERS_PER_REQUEST, "offset": offset},
                )
                if resp.status_code == 429:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning("S2 rate limited at offset %d, retrying in %ds (attempt %d/%d)", offset, delay, attempt + 1, MAX_RETRIES)
                    await asyncio.sleep(delay)
                    continue
                break
            if resp is None or resp.status_code != 200:
                logger.warning("Papers fetch failed at offset %d: %s", offset, resp.text[:200] if resp else "no response")
                break
            body = resp.json()
            batch = body.get("data", [])
            all_papers_raw.extend(batch)
            if len(batch) < MAX_PAPERS_PER_REQUEST:
                break
            offset += MAX_PAPERS_PER_REQUEST
            await asyncio.sleep(1.0)  # Avoid rate limits between pages

        existing = {
            p.semantic_scholar_id: p
            for p in (await db.execute(select(Paper).where(Paper.user_id == user.id))).scalars().all()
        }

        result: list[Paper] = []
        for raw in all_papers_raw:
            pid = raw.get("paperId")
            if not pid:
                continue
            authors = [a.get("name", "") for a in (raw.get("authors") or [])]
            venue = raw.get("venue", "") or ""
            ccf = lookup_ccf_rank(venue)
            ccf_rank = ccf[0] if ccf else ""
            ccf_category = ccf[1] if ccf else ""

            if pid in existing:
                paper = existing[pid]
                paper.citation_count = raw.get("citationCount", 0) or 0
                paper.title = raw.get("title", paper.title)
                paper.venue = venue
                paper.year = raw.get("year", 0) or 0
                paper.authors_json = authors
                paper.url = raw.get("url", "") or ""
                paper.ccf_rank = ccf_rank
                paper.ccf_category = ccf_category
                paper.updated_at = datetime.utcnow()
            else:
                paper = Paper(
                    user_id=user.id,
                    semantic_scholar_id=pid,
                    title=raw.get("title", ""),
                    year=raw.get("year", 0) or 0,
                    venue=venue,
                    citation_count=raw.get("citationCount", 0) or 0,
                    authors_json=authors,
                    url=raw.get("url", "") or "",
                    ccf_rank=ccf_rank,
                    ccf_category=ccf_category,
                )
                db.add(paper)
            result.append(paper)

        await db.commit()
        logger.info("Synced %d papers for user %d", len(result), user.id)
        return result
