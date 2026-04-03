"""DBLP API client: supplements paper data with DBLP information,
including venue normalization and additional publications."""

import logging
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import OUTBOUND_PROXY
from app.models import Paper, User
from app.data.ccf_venues import lookup_ccf_rank
from app.utils.paper_dedup import normalize_title, _is_arxiv_venue

logger = logging.getLogger(__name__)

DBLP_API = "https://dblp.org/search/publ/api"
DBLP_AUTHOR_API = "https://dblp.org/search/author/api"


async def fetch_dblp_papers_for_user(db: AsyncSession, user: User) -> list[Paper]:
    """Search DBLP for papers by user's name and cross-reference with existing papers.
    If the paper already exists (matched by title), updates dblp_key.
    If it's new, adds it to the database."""
    name = user.name
    if not name:
        return []

    async with httpx.AsyncClient(timeout=20, proxy=OUTBOUND_PROXY) as client:
        all_hits: list[dict] = []
        try:
            resp = await client.get(
                DBLP_API,
                params={"q": name, "format": "json", "h": 100},
            )
            if resp.status_code != 200:
                logger.warning("DBLP search failed: %s", resp.status_code)
                return []

            result = resp.json().get("result", {})
            hits_wrapper = result.get("hits", {})
            all_hits = hits_wrapper.get("hit", [])
        except Exception:
            logger.exception("DBLP API call failed")
            return []

    existing_titles: dict[str, Paper] = {}
    existing_papers = (
        await db.execute(select(Paper).where(Paper.user_id == user.id))
    ).scalars().all()
    for p in existing_papers:
        key = normalize_title(p.title)
        if not key:
            continue
        if key not in existing_titles:
            existing_titles[key] = p
        else:
            # Keep the better one: formal venue over arXiv, then citations, then SS over DBLP
            other = existing_titles[key]
            p_arxiv = _is_arxiv_venue(p.venue or "")
            o_arxiv = _is_arxiv_venue(other.venue or "")
            if p_arxiv and not o_arxiv:
                continue  # keep other (formal)
            if not p_arxiv and o_arxiv:
                existing_titles[key] = p
            elif p.citation_count > other.citation_count:
                existing_titles[key] = p
            elif p.citation_count == other.citation_count:
                p_ss = not (p.semantic_scholar_id or "").startswith("dblp:")
                o_ss = not (other.semantic_scholar_id or "").startswith("dblp:")
                if p_ss and not o_ss:
                    existing_titles[key] = p

    name_parts = set(name.lower().split())
    new_papers: list[Paper] = []

    for hit in all_hits:
        info = hit.get("info", {})
        title = (info.get("title") or "").rstrip(".")
        if not title:
            continue

        # Verify the user is actually an author
        authors_raw = info.get("authors", {}).get("author", [])
        if isinstance(authors_raw, dict):
            authors_raw = [authors_raw]
        author_names = [a.get("text", "") if isinstance(a, dict) else str(a) for a in authors_raw]

        is_author = False
        for an in author_names:
            an_parts = set(an.lower().split())
            if name_parts & an_parts and len(name_parts & an_parts) >= min(2, len(name_parts)):
                is_author = True
                break
        if not is_author:
            continue

        venue = info.get("venue", "")
        if isinstance(venue, list):
            venue = venue[0] if venue else ""
        year = int(info.get("year", 0) or 0)
        dblp_key = info.get("key", "")
        url = info.get("ee", "") or info.get("url", "")

        ccf = lookup_ccf_rank(venue)
        ccf_rank = ccf[0] if ccf else ""
        ccf_category = ccf[1] if ccf else ""

        title_norm = normalize_title(title)
        if title_norm in existing_titles:
            paper = existing_titles[title_norm]
            if not paper.dblp_key:
                paper.dblp_key = dblp_key
            if not paper.ccf_rank and ccf_rank:
                paper.ccf_rank = ccf_rank
                paper.ccf_category = ccf_category
        else:
            paper = Paper(
                user_id=user.id,
                semantic_scholar_id=f"dblp:{dblp_key}" if dblp_key else f"dblp:unknown:{title_norm[:50]}",
                title=title,
                year=year,
                venue=venue,
                citation_count=0,
                authors_json=author_names,
                url=url,
                ccf_rank=ccf_rank,
                ccf_category=ccf_category,
                dblp_key=dblp_key,
            )
            db.add(paper)
            existing_titles[title_norm] = paper
            new_papers.append(paper)

    if new_papers:
        await db.commit()
        logger.info("Added %d new papers from DBLP for user %d", len(new_papers), user.id)

    return new_papers
