"""Citation analysis service: fetches citing papers from Semantic Scholar,
then batch-resolves author h-index to identify notable scholars."""

import asyncio
import logging
from datetime import datetime

import httpx
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import SEMANTIC_SCHOLAR_API, OUTBOUND_PROXY
from app.database import async_session
from app.models import Paper, User, NotableCitation, CitationAnalysis

logger = logging.getLogger(__name__)

CITATION_FIELDS = "title,year,venue,citationCount,isInfluential,contexts,intents,authors"
AUTHOR_BATCH_FIELDS = "name,hIndex,citationCount,paperCount"
MAX_CITATIONS_PER_PAPER = 500
AUTHOR_BATCH_SIZE = 400
REQUEST_DELAY = 1.1
CONCURRENT_PAPERS = 1  # Sequential to avoid S2 rate limits

H_INDEX_TOP = 50
H_INDEX_NOTABLE = 25

_analyzing_users: set[int] = set()
_analysis_progress: dict[int, tuple[int, int]] = {}  # user_id -> (done, total)


def classify_scholar(h_index: int) -> str | None:
    if h_index >= H_INDEX_TOP:
        return "top"
    if h_index >= H_INDEX_NOTABLE:
        return "notable"
    return None


def is_analyzing(user_id: int) -> bool:
    return user_id in _analyzing_users


def get_progress(user_id: int) -> tuple[int, int]:
    """Return (analyzed_count, total_count) for a running analysis."""
    return _analysis_progress.get(user_id, (0, 0))


async def analyze_citations_for_user(user_id: int):
    if user_id in _analyzing_users:
        logger.info("Citation analysis already running for user %d", user_id)
        return
    _analyzing_users.add(user_id)
    try:
        async with async_session() as db:
            user = await db.get(User, user_id)
            if not user or not user.scholar_id:
                return

            papers = (
                await db.execute(
                    select(Paper)
                    .where(Paper.user_id == user_id)
                    .order_by(Paper.citation_count.desc())
                )
            ).scalars().all()

            if not papers:
                return

            # Skip papers already analyzed (incremental)
            analyzed_paper_ids = set(
                row[0] for row in (
                    await db.execute(
                        select(CitationAnalysis.paper_id)
                        .where(CitationAnalysis.user_id == user_id)
                    )
                ).all()
            )
            pending_papers = [p for p in papers if p.id not in analyzed_paper_ids]

            logger.info(
                "Citation analysis for user %d: %d total papers, %d already analyzed, %d to analyze",
                user_id, len(papers), len(analyzed_paper_ids), len(pending_papers),
            )

            if not pending_papers:
                logger.info("All papers already analyzed for user %d", user_id)
                # Still run honor enrichment
                from app.services.honor_service import enrich_honors_for_user
                await enrich_honors_for_user(user_id)
                return

            # User's own author names for self-citation filtering
            user_author_names = set()
            for p in papers:
                if p.authors_json:
                    for name in p.authors_json:
                        if isinstance(name, str):
                            user_author_names.add(name.lower().strip())

            # Use semaphore for concurrent paper analysis
            sem = asyncio.Semaphore(CONCURRENT_PAPERS)
            analyzed_count = 0
            total_pending = len(pending_papers)
            _analysis_progress[user_id] = (0, total_pending)

            async def _analyze_one(paper: Paper):
                nonlocal analyzed_count
                async with sem:
                    try:
                        async with httpx.AsyncClient(timeout=30, proxy=OUTBOUND_PROXY) as client:
                            await _analyze_paper(db, client, user_id, paper, user_author_names)
                        await db.commit()
                        analyzed_count += 1
                        _analysis_progress[user_id] = (analyzed_count, total_pending)
                        if analyzed_count % 20 == 0:
                            logger.info("Progress: %d/%d papers analyzed for user %d", analyzed_count, len(pending_papers), user_id)
                    except Exception:
                        logger.exception("Error analyzing paper %s", paper.semantic_scholar_id)
                        await db.rollback()

            # Run concurrently in batches
            batch_size = 20
            for i in range(0, len(pending_papers), batch_size):
                batch = pending_papers[i:i + batch_size]
                await asyncio.gather(*[_analyze_one(p) for p in batch])
                await db.commit()

            await db.commit()
            logger.info("Citation analysis complete for user %d (%d papers analyzed)", user_id, analyzed_count)

            # Automatically run honor enrichment after citation analysis
            from app.services.honor_service import enrich_honors_for_user
            logger.info("Auto-triggering honor enrichment for user %d", user_id)
            await enrich_honors_for_user(user_id)
    except Exception:
        logger.exception("Citation analysis failed for user %d", user_id)
    finally:
        _analyzing_users.discard(user_id)
        _analysis_progress.pop(user_id, None)


async def _analyze_paper(
    db: AsyncSession,
    client: httpx.AsyncClient,
    user_id: int,
    paper: Paper,
    user_author_names: set[str],
):
    ss_id = paper.semantic_scholar_id

    # Step 1: Fetch citing papers
    all_citations: list[dict] = []
    offset = 0
    while offset < MAX_CITATIONS_PER_PAPER:
        resp = None
        for attempt in range(3):
            resp = await client.get(
                f"{SEMANTIC_SCHOLAR_API}/paper/{ss_id}/citations",
                params={"fields": CITATION_FIELDS, "limit": 500, "offset": offset},
            )
            if resp.status_code == 429:
                delay = 5 * (2 ** attempt)
                logger.warning("Rate limited on citations for %s, waiting %ds", ss_id, delay)
                await asyncio.sleep(delay)
                continue
            break
        if resp is None or resp.status_code != 200:
            logger.warning("Citations fetch failed for %s: %s", ss_id, resp.status_code if resp else "no response")
            break
        body = resp.json()
        batch = body.get("data", [])
        all_citations.extend(batch)
        if len(batch) < 500 or body.get("next") is None:
            break
        offset += 500
        await asyncio.sleep(REQUEST_DELAY)

    # Step 2: Collect unique author IDs
    author_id_map: dict[str, dict] = {}  # authorId -> {name, citing_papers: [...]}
    citation_meta: dict[str, dict] = {}  # paperId -> citation metadata

    for item in all_citations:
        cp = item.get("citingPaper", {})
        if not cp or not cp.get("paperId"):
            continue

        cp_id = cp["paperId"]
        citation_meta[cp_id] = {
            "title": cp.get("title", "") or "",
            "year": cp.get("year", 0) or 0,
            "venue": cp.get("venue", "") or "",
            "is_influential": item.get("isInfluential", False),
            "contexts": item.get("contexts") or [],
            "intents": item.get("intents") or [],
        }

        for author in cp.get("authors") or []:
            aid = author.get("authorId")
            aname = author.get("name", "")
            if not aid or not aname:
                continue
            # Skip self-citations
            if aname.lower().strip() in user_author_names:
                continue

            if aid not in author_id_map:
                author_id_map[aid] = {"name": aname, "citing_papers": []}
            author_id_map[aid]["citing_papers"].append(cp_id)

    if not author_id_map:
        # Save empty analysis
        await _save_analysis(db, user_id, paper, len(all_citations), 0, 0, 0)
        logger.info("Paper '%s': %d citations, no external authors", paper.title[:50], len(all_citations))
        return

    # Step 3: Batch fetch author details (h-index)
    author_ids = list(author_id_map.keys())
    author_details: dict[str, dict] = {}

    for i in range(0, len(author_ids), AUTHOR_BATCH_SIZE):
        batch_ids = author_ids[i:i + AUTHOR_BATCH_SIZE]
        for attempt in range(3):
            try:
                resp = await client.post(
                    f"{SEMANTIC_SCHOLAR_API}/author/batch",
                    params={"fields": AUTHOR_BATCH_FIELDS},
                    json={"ids": batch_ids},
                )
                if resp.status_code == 429:
                    delay = 5 * (2 ** attempt)
                    logger.warning("Author batch rate limited, waiting %ds (attempt %d)", delay, attempt + 1)
                    await asyncio.sleep(delay)
                    continue
                if resp.status_code == 200:
                    for ad in resp.json():
                        if ad and ad.get("authorId"):
                            author_details[ad["authorId"]] = ad
                else:
                    logger.warning("Author batch failed: %s", resp.status_code)
                break
            except Exception:
                logger.exception("Author batch request failed")
                break
        await asyncio.sleep(REQUEST_DELAY)

    # Step 4: Identify notable scholars and save
    await db.execute(delete(NotableCitation).where(NotableCitation.paper_id == paper.id))

    top_count = 0
    notable_count = 0
    influential_count = sum(1 for m in citation_meta.values() if m.get("is_influential"))

    for aid, info in author_id_map.items():
        details = author_details.get(aid, {})
        h_index = details.get("hIndex") or 0
        level = classify_scholar(h_index)
        if not level:
            continue

        # Pick the most important citing paper for this author
        best_cp_id = info["citing_papers"][0]
        meta = citation_meta.get(best_cp_id, {})

        if level == "top":
            top_count += 1
        else:
            notable_count += 1

        nc = NotableCitation(
            user_id=user_id,
            paper_id=paper.id,
            citing_paper_ss_id=best_cp_id,
            citing_paper_title=meta.get("title", ""),
            citing_paper_year=meta.get("year", 0),
            citing_paper_venue=meta.get("venue", ""),
            author_name=details.get("name") or info["name"],
            author_ss_id=aid,
            author_h_index=h_index,
            author_citation_count=details.get("citationCount", 0) or 0,
            author_paper_count=details.get("paperCount", 0) or 0,
            scholar_level=level,
            is_influential=meta.get("is_influential", False),
            contexts_json=(meta.get("contexts") or [])[:3],
            intents_json=meta.get("intents") or [],
        )
        db.add(nc)

    await _save_analysis(db, user_id, paper, len(all_citations), influential_count, top_count, notable_count)
    await db.flush()
    logger.info(
        "Paper '%s': %d citations, %d top, %d notable scholars",
        paper.title[:50], len(all_citations), top_count, notable_count,
    )


async def _save_analysis(
    db: AsyncSession, user_id: int, paper: Paper,
    total: int, influential: int, top: int, notable: int,
):
    await db.execute(delete(CitationAnalysis).where(CitationAnalysis.paper_id == paper.id))
    db.add(CitationAnalysis(
        user_id=user_id,
        paper_id=paper.id,
        total_citing_papers=total,
        influential_count=influential,
        top_scholar_count=top,
        notable_scholar_count=notable,
        analyzed_at=datetime.utcnow(),
    ))
