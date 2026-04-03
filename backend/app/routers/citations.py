"""Citation analysis endpoints."""

from fastapi import APIRouter, Depends, BackgroundTasks, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, Paper, NotableCitation, CitationAnalysis
from app.schemas import CitationOverview, NotableCitationOut, CitationAnalysisOut
from app.services.citation_service import analyze_citations_for_user, is_analyzing, get_progress
from app.services.honor_service import enrich_honors_for_user, is_enriching
from app.deps import resolve_user

router = APIRouter()

OVERVIEW_SCHOLAR_LIMIT = 20  # scholars returned in overview (first page)
OVERVIEW_PAPER_LIMIT = 10    # paper analyses returned in overview (first page)


@router.post("/citations/{identifier}/analyze")
async def trigger_citation_analysis(
    background_tasks: BackgroundTasks,
    user: User = Depends(resolve_user),
):
    user_id = user.id
    if is_analyzing(user_id):
        return {"status": "already_analyzing", "user_id": user_id}

    background_tasks.add_task(analyze_citations_for_user, user_id)
    return {"status": "analysis_started", "user_id": user_id}


@router.post("/citations/{identifier}/enrich-honors")
async def trigger_honor_enrichment(
    background_tasks: BackgroundTasks,
    user: User = Depends(resolve_user),
):
    """Query LLM to identify IEEE Fellow / 院士 among notable citations."""
    user_id = user.id
    if is_enriching(user_id):
        return {"status": "already_enriching", "user_id": user_id}

    background_tasks.add_task(enrich_honors_for_user, user_id)
    return {"status": "enrichment_started", "user_id": user_id}


@router.get("/citations/{identifier}/papers")
async def get_paper_analyses_paginated(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(resolve_user),
    db: AsyncSession = Depends(get_db),
):
    """Paginated endpoint for loading more paper analyses."""
    user_id = user.id

    rows = (
        await db.execute(
            select(CitationAnalysis, Paper.title, Paper.citation_count)
            .join(Paper, CitationAnalysis.paper_id == Paper.id)
            .where(CitationAnalysis.user_id == user_id)
            .order_by(Paper.citation_count.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()

    items = [
        CitationAnalysisOut(
            paper_id=a.paper_id,
            paper_title=title,
            paper_citation_count=cc,
            total_citing_papers=a.total_citing_papers,
            influential_count=a.influential_count,
            top_scholar_count=a.top_scholar_count,
            notable_scholar_count=a.notable_scholar_count,
            analyzed_at=a.analyzed_at,
        ).model_dump()
        for a, title, cc in rows
    ]
    return {"items": items, "offset": offset, "limit": limit}


@router.get("/citations/{identifier}/scholars")
async def get_scholars_paginated(
    level: str = Query(default="top", description="top or notable"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(resolve_user),
    db: AsyncSession = Depends(get_db),
):
    """Paginated endpoint for loading more top/notable scholars."""
    user_id = user.id

    rows = (
        await db.execute(
            select(NotableCitation, Paper.title)
            .join(Paper, NotableCitation.paper_id == Paper.id)
            .where(NotableCitation.user_id == user_id, NotableCitation.scholar_level == level)
            .order_by(NotableCitation.author_h_index.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()

    items = [_to_citation_out(nc, ptitle) for nc, ptitle in rows]
    return {"items": [item.model_dump() for item in items], "offset": offset, "limit": limit}


@router.get("/citations/{identifier}", response_model=CitationOverview)
async def get_citation_overview(
    user: User = Depends(resolve_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = user.id

    # Get first page of analyses (ordered by citation count desc)
    analyses_rows = (
        await db.execute(
            select(CitationAnalysis, Paper.title, Paper.citation_count)
            .join(Paper, CitationAnalysis.paper_id == Paper.id)
            .where(CitationAnalysis.user_id == user_id)
            .order_by(Paper.citation_count.desc())
            .limit(OVERVIEW_PAPER_LIMIT)
        )
    ).all()

    paper_analyses = [
        CitationAnalysisOut(
            paper_id=a.paper_id,
            paper_title=title,
            paper_citation_count=cc,
            total_citing_papers=a.total_citing_papers,
            influential_count=a.influential_count,
            top_scholar_count=a.top_scholar_count,
            notable_scholar_count=a.notable_scholar_count,
            analyzed_at=a.analyzed_at,
        )
        for a, title, cc in analyses_rows
    ]

    # Total counts (fast COUNT queries)
    top_total_result = await db.execute(
        select(func.count()).select_from(NotableCitation)
        .where(NotableCitation.user_id == user_id, NotableCitation.scholar_level == "top")
    )
    top_scholar_total = top_total_result.scalar() or 0

    notable_total_result = await db.execute(
        select(func.count()).select_from(NotableCitation)
        .where(NotableCitation.user_id == user_id, NotableCitation.scholar_level == "notable")
    )
    notable_scholar_total = notable_total_result.scalar() or 0

    # Get first page of top scholars (h-index >= 50)
    top_rows = (
        await db.execute(
            select(NotableCitation, Paper.title)
            .join(Paper, NotableCitation.paper_id == Paper.id)
            .where(NotableCitation.user_id == user_id, NotableCitation.scholar_level == "top")
            .order_by(NotableCitation.author_h_index.desc())
            .limit(OVERVIEW_SCHOLAR_LIMIT)
        )
    ).all()

    top_scholars = [_to_citation_out(nc, ptitle) for nc, ptitle in top_rows]

    # Get first page of notable scholars (h-index >= 25)
    notable_rows = (
        await db.execute(
            select(NotableCitation, Paper.title)
            .join(Paper, NotableCitation.paper_id == Paper.id)
            .where(NotableCitation.user_id == user_id, NotableCitation.scholar_level == "notable")
            .order_by(NotableCitation.author_h_index.desc())
            .limit(OVERVIEW_SCHOLAR_LIMIT)
        )
    ).all()

    notable_scholars = [_to_citation_out(nc, ptitle) for nc, ptitle in notable_rows]

    # Unique notable scholar count
    unique_count_result = await db.execute(
        select(func.count(func.distinct(NotableCitation.author_ss_id)))
        .where(NotableCitation.user_id == user_id)
    )
    unique_notable = unique_count_result.scalar() or 0

    # Honor scholar count: unique authors that have at least one honor tag
    honor_count_result = await db.execute(
        select(func.count(func.distinct(NotableCitation.author_ss_id)))
        .where(
            NotableCitation.user_id == user_id,
            NotableCitation.honor_tags.isnot(None),
            NotableCitation.honor_tags != "[]",
        )
    )
    honor_scholar_count = honor_count_result.scalar() or 0

    # Check if enrichment has been run (any author has honor_tags != NULL)
    honor_enriched_result = await db.execute(
        select(func.count()).select_from(NotableCitation).where(
            NotableCitation.user_id == user_id,
            NotableCitation.honor_tags.isnot(None),
        ).limit(1)
    )
    honor_enriched = (honor_enriched_result.scalar() or 0) > 0

    # Total papers for user
    total_papers_result = await db.execute(
        select(func.count()).select_from(Paper).where(Paper.user_id == user_id)
    )
    total_papers = total_papers_result.scalar() or 0

    # Total paper analyses count
    paper_analyses_total_result = await db.execute(
        select(func.count()).select_from(CitationAnalysis)
        .where(CitationAnalysis.user_id == user_id)
    )
    paper_analyses_total = paper_analyses_total_result.scalar() or 0

    # Progress for active analysis (include already-analyzed papers)
    run_done, run_total = get_progress(user_id)
    already_done = paper_analyses_total - run_done  # papers analyzed before this run
    analysis_done = already_done + run_done if run_total > 0 else 0
    analysis_total = already_done + run_total if run_total > 0 else 0

    return CitationOverview(
        total_papers_analyzed=paper_analyses_total,
        total_papers=total_papers,
        analysis_done=analysis_done,
        analysis_total=analysis_total,
        total_notable_scholars=len(top_scholars) + len(notable_scholars),
        unique_notable_scholars=unique_notable,
        top_scholar_total=top_scholar_total,
        notable_scholar_total=notable_scholar_total,
        top_scholars=top_scholars,
        notable_scholars=notable_scholars,
        paper_analyses=paper_analyses,
        paper_analyses_total=paper_analyses_total,
        is_analyzing=is_analyzing(user_id),
        honor_scholar_count=honor_scholar_count,
        honor_is_enriching=is_enriching(user_id),
        honor_enriched=honor_enriched,
    )


def _to_citation_out(nc: NotableCitation, paper_title: str) -> NotableCitationOut:
    return NotableCitationOut(
        id=nc.id,
        paper_id=nc.paper_id,
        paper_title=paper_title,
        citing_paper_title=nc.citing_paper_title,
        citing_paper_year=nc.citing_paper_year,
        citing_paper_venue=nc.citing_paper_venue,
        author_name=nc.author_name,
        author_ss_id=nc.author_ss_id,
        author_h_index=nc.author_h_index,
        author_citation_count=nc.author_citation_count,
        author_paper_count=nc.author_paper_count,
        scholar_level=nc.scholar_level,
        is_influential=nc.is_influential,
        contexts=nc.contexts_json if isinstance(nc.contexts_json, list) else [],
        intents=nc.intents_json if isinstance(nc.intents_json, list) else [],
        honor_tags=nc.honor_tags if isinstance(nc.honor_tags, list) else [],
    )
