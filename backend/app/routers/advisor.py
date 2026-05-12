"""Advisor (导师推荐) API: schools, colleges, advisors directory."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime

from app.database import async_session, get_db
from app.models import AdvisorSchool, AdvisorCollege, Advisor, AdvisorMention
from app.services import advisor_crawler_service, advisor_chat_service

router = APIRouter()


# ─────── Schemas ───────

class SchoolBrief(BaseModel):
    id: int
    name: str
    short_name: str
    english_name: str
    city: str
    province: str
    school_type: str
    is_985: bool
    is_211: bool
    is_double_first_class: bool
    homepage_url: str
    college_count: int
    advisor_count: int

    model_config = {"from_attributes": True}


class CollegeBrief(BaseModel):
    id: int
    school_id: int
    name: str
    discipline_category: str
    homepage_url: str
    advisor_count: int

    model_config = {"from_attributes": True}


class AdvisorBrief(BaseModel):
    id: int
    school_id: int
    college_id: int
    name: str
    title: str
    is_doctoral_supervisor: bool
    research_areas: list[str] | None
    homepage_url: str
    photo_url: str
    h_index: int
    citation_count: int
    bio: str = ""
    email: str = ""
    impacthub_user_id: int | None = None

    model_config = {"from_attributes": True}


class MentionIn(BaseModel):
    """Single mention payload. Either advisor_id, OR (advisor_name + school_name)
    for fuzzy lookup during bulk import."""
    advisor_id: int | None = None
    advisor_name: str | None = None
    school_name: str | None = None
    source: str
    source_account: str = ""
    title: str = ""
    url: str = ""
    snippet: str = ""
    cover_url: str = ""
    likes: int = 0
    reads: int = 0
    comments: int = 0
    sentiment: str = ""
    tags: list[str] | None = None
    published_at: str | None = None  # ISO 8601


class MentionOut(BaseModel):
    id: int
    advisor_id: int
    source: str
    source_account: str
    title: str
    url: str
    snippet: str
    cover_url: str
    likes: int
    reads: int
    comments: int
    sentiment: str
    tags: list[str] | None
    published_at: str | None
    created_at: str

    model_config = {"from_attributes": True}


class SchoolDirectoryStats(BaseModel):
    total_schools: int
    schools_985: int
    schools_211: int
    total_colleges: int
    total_advisors: int
    by_province: dict[str, int]
    by_school_type: dict[str, int]


# ─────── Endpoints ───────

@router.get("/advisor/stats", response_model=SchoolDirectoryStats)
async def get_directory_stats(db: AsyncSession = Depends(get_db)):
    schools = (await db.execute(select(AdvisorSchool))).scalars().all()
    college_count = (await db.execute(select(func.count(AdvisorCollege.id)))).scalar() or 0
    advisor_count = (await db.execute(select(func.count(Advisor.id)))).scalar() or 0

    by_province: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for s in schools:
        if s.province:
            by_province[s.province] = by_province.get(s.province, 0) + 1
        if s.school_type:
            by_type[s.school_type] = by_type.get(s.school_type, 0) + 1

    return SchoolDirectoryStats(
        total_schools=len(schools),
        schools_985=sum(1 for s in schools if s.is_985),
        schools_211=sum(1 for s in schools if s.is_211),
        total_colleges=college_count,
        total_advisors=advisor_count,
        by_province=by_province,
        by_school_type=by_type,
    )


@router.get("/advisor/schools", response_model=list[SchoolBrief])
async def list_schools(
    province: str | None = None,
    school_type: str | None = None,
    tier: str | None = Query(None, description="985 / 211"),
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AdvisorSchool)
    if province:
        stmt = stmt.where(AdvisorSchool.province == province)
    if school_type:
        stmt = stmt.where(AdvisorSchool.school_type == school_type)
    if tier == "985":
        stmt = stmt.where(AdvisorSchool.is_985 == True)  # noqa: E712
    elif tier == "211":
        stmt = stmt.where(AdvisorSchool.is_211 == True)  # noqa: E712
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(
            AdvisorSchool.name.like(like),
            AdvisorSchool.short_name.like(like),
            AdvisorSchool.english_name.like(like),
            AdvisorSchool.city.like(like),
        ))
    schools = (await db.execute(stmt)).scalars().all()

    # Compute college / advisor counts in batch
    sids = [s.id for s in schools]
    college_counts: dict[int, int] = {}
    if sids:
        rows = (await db.execute(
            select(AdvisorCollege.school_id, func.count(AdvisorCollege.id))
            .where(AdvisorCollege.school_id.in_(sids))
            .group_by(AdvisorCollege.school_id)
        )).all()
        college_counts = {sid: int(c) for sid, c in rows}
    # advisor_count is denormalized on AdvisorSchool

    out = []
    for s in schools:
        out.append(SchoolBrief(
            id=s.id, name=s.name, short_name=s.short_name, english_name=s.english_name,
            city=s.city, province=s.province, school_type=s.school_type,
            is_985=s.is_985, is_211=s.is_211, is_double_first_class=s.is_double_first_class,
            homepage_url=s.homepage_url,
            college_count=college_counts.get(s.id, 0),
            advisor_count=s.advisor_count or 0,
        ))
    # Sort: 985 first, then by advisor_count desc, then by name
    out.sort(key=lambda x: (not x.is_985, -x.advisor_count, x.name))
    return out


@router.get("/advisor/schools/{school_id}")
async def get_school(school_id: int, db: AsyncSession = Depends(get_db)):
    school = await db.get(AdvisorSchool, school_id)
    if not school:
        raise HTTPException(404, "School not found")
    colleges = (await db.execute(
        select(AdvisorCollege).where(AdvisorCollege.school_id == school_id)
    )).scalars().all()
    return {
        "school": SchoolBrief(
            id=school.id, name=school.name, short_name=school.short_name,
            english_name=school.english_name, city=school.city, province=school.province,
            school_type=school.school_type,
            is_985=school.is_985, is_211=school.is_211,
            is_double_first_class=school.is_double_first_class,
            homepage_url=school.homepage_url,
            college_count=len(colleges),
            advisor_count=school.advisor_count or 0,
        ),
        "colleges_crawled_at": school.colleges_crawled_at.isoformat() if school.colleges_crawled_at else None,
        "advisors_crawled_at": school.advisors_crawled_at.isoformat() if school.advisors_crawled_at else None,
        "colleges": [
            CollegeBrief(
                id=c.id, school_id=c.school_id, name=c.name,
                discipline_category=c.discipline_category, homepage_url=c.homepage_url,
                advisor_count=c.advisor_count or 0,
            )
            for c in colleges
        ],
    }


@router.post("/advisor/schools/{school_id}/crawl")
async def crawl_school(
    school_id: int,
    background_tasks: BackgroundTasks,
    fetch_advisors: bool = Query(False, description="If true, also crawl advisor stubs per college"),
    db: AsyncSession = Depends(get_db),
):
    school = await db.get(AdvisorSchool, school_id)
    if not school:
        raise HTTPException(404, "School not found")
    background_tasks.add_task(_do_crawl_school, school_id, fetch_advisors)
    return {"status": "crawling", "school_id": school_id, "fetch_advisors": fetch_advisors}


async def _do_crawl_school(school_id: int, fetch_advisors: bool):
    async with async_session() as db:
        school = await db.get(AdvisorSchool, school_id)
        if not school:
            return
        result = await advisor_crawler_service.crawl_school_colleges(
            db, school, fetch_advisors=fetch_advisors,
        )
        await db.commit()
        import logging
        logging.getLogger(__name__).info("Crawl school %s done: %s", school.name, result)


@router.post("/advisor/colleges/{college_id}/crawl-advisors")
async def crawl_college(
    college_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    college = await db.get(AdvisorCollege, college_id)
    if not college:
        raise HTTPException(404, "College not found")
    background_tasks.add_task(_do_crawl_college, college_id)
    return {"status": "crawling", "college_id": college_id}


async def _do_crawl_college(college_id: int):
    async with async_session() as db:
        college = await db.get(AdvisorCollege, college_id)
        if not college:
            return
        await advisor_crawler_service.crawl_college_advisors(db, college)
        await db.commit()


@router.get("/advisor/colleges/{college_id}/advisors", response_model=list[AdvisorBrief])
async def list_advisors_in_college(college_id: int, db: AsyncSession = Depends(get_db)):
    advisors = (await db.execute(
        select(Advisor).where(Advisor.college_id == college_id)
    )).scalars().all()
    return [
        AdvisorBrief(
            id=a.id, school_id=a.school_id, college_id=a.college_id,
            name=a.name, title=a.title,
            is_doctoral_supervisor=a.is_doctoral_supervisor,
            research_areas=a.research_areas,
            homepage_url=a.homepage_url, photo_url=a.photo_url,
            h_index=a.h_index, citation_count=a.citation_count,
            bio=a.bio, email=a.email,
            impacthub_user_id=a.impacthub_user_id,
        )
        for a in advisors
    ]


# ─────── Mentions (公众号 / 小红书 / 等舆情) ───────

def _resolve_advisor_id(db: AsyncSession, payload: MentionIn) -> int | None:
    """Sync helper for body-level lookup. Returns None on miss."""
    return None  # placeholder — actual logic below uses db.execute


async def _find_advisor(
    db: AsyncSession, advisor_id: int | None, name: str | None, school_name: str | None
) -> Advisor | None:
    if advisor_id:
        return await db.get(Advisor, advisor_id)
    if not name:
        return None
    stmt = select(Advisor).where(Advisor.name == name)
    if school_name:
        stmt = stmt.join(AdvisorSchool, AdvisorSchool.id == Advisor.school_id).where(
            AdvisorSchool.name == school_name
        )
    rows = (await db.execute(stmt)).scalars().all()
    if len(rows) == 1:
        return rows[0]
    # On ambiguity (multiple Zhang Wei across schools), require school_name
    return None


def _serialize_mention(m: AdvisorMention) -> MentionOut:
    return MentionOut(
        id=m.id, advisor_id=m.advisor_id, source=m.source,
        source_account=m.source_account, title=m.title, url=m.url,
        snippet=m.snippet, cover_url=m.cover_url,
        likes=m.likes, reads=m.reads, comments=m.comments,
        sentiment=m.sentiment, tags=m.tags,
        published_at=m.published_at.isoformat() if m.published_at else None,
        created_at=m.created_at.isoformat(),
    )


@router.get("/advisor/advisors/{advisor_id}/mentions", response_model=list[MentionOut])
async def list_advisor_mentions(advisor_id: int, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(AdvisorMention)
        .where(AdvisorMention.advisor_id == advisor_id)
        .order_by(AdvisorMention.published_at.desc().nulls_last(), AdvisorMention.id.desc())
    )).scalars().all()
    return [_serialize_mention(m) for m in rows]


class MentionFeedItem(BaseModel):
    """A mention with advisor/college/school context for the feed view.

    For unlinked mentions (advisor not yet crawled), advisor_id=0 and the
    advisor/school fields fall back to pending_* values; college fields are empty.
    """
    id: int
    source: str
    source_account: str
    title: str
    url: str
    snippet: str
    cover_url: str
    likes: int
    reads: int
    comments: int
    sentiment: str
    tags: list[str] | None
    published_at: str | None
    # Always populated (linked → from joined advisor; unlinked → from pending_*)
    advisor_id: int          # 0 if unlinked
    advisor_name: str
    advisor_title: str
    advisor_homepage: str
    college_id: int          # 0 if unlinked
    college_name: str
    school_id: int           # 0 if unlinked
    school_name: str
    school_short: str
    school_province: str
    is_985: bool
    is_211: bool
    is_linked: bool          # convenience for frontend


class MentionFeedFacets(BaseModel):
    sources: dict[str, int]
    accounts: dict[str, int]
    sentiments: dict[str, int]


class MentionFeedResponse(BaseModel):
    items: list[MentionFeedItem]
    total: int
    offset: int
    limit: int
    facets: MentionFeedFacets


@router.get("/advisor/mentions/feed", response_model=MentionFeedResponse)
async def mentions_feed(
    q: str | None = Query(None, description="搜索 (匹配 title/snippet/advisor_name/account)"),
    source: str | None = Query(None, description="wechat/xiaohongshu/zhihu/forum"),
    account: str | None = Query(None),
    sentiment: str | None = Query(None),
    school_id: int | None = None,
    advisor_id: int | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    M, A, C, S = AdvisorMention, Advisor, AdvisorCollege, AdvisorSchool
    # LEFT-OUTER joins so unlinked mentions (advisor_id=0) are also returned;
    # advisor/school fields then fall back to M.pending_* values.
    base = (
        select(M, A, C, S)
        .outerjoin(A, A.id == M.advisor_id)
        .outerjoin(C, C.id == A.college_id)
        .outerjoin(S, S.id == A.school_id)
    )

    if source:
        base = base.where(M.source == source)
    if account:
        base = base.where(M.source_account == account)
    if sentiment:
        base = base.where(M.sentiment == sentiment)
    if school_id:
        base = base.where(S.id == school_id)
    if advisor_id:
        base = base.where(M.advisor_id == advisor_id)
    if q:
        from sqlalchemy import or_
        like = f"%{q}%"
        base = base.where(or_(
            M.title.like(like),
            M.snippet.like(like),
            M.source_account.like(like),
            M.pending_advisor_name.like(like),
            M.pending_school_name.like(like),
            A.name.like(like),
            S.name.like(like),
            S.short_name.like(like),
        ))

    total_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(total_stmt)).scalar() or 0

    paginated = base.order_by(
        M.published_at.desc().nulls_last(), M.id.desc()
    ).offset(offset).limit(limit)
    rows = (await db.execute(paginated)).all()

    items = []
    for m, a, c, s in rows:
        is_linked = a is not None and m.advisor_id != 0
        items.append(MentionFeedItem(
            id=m.id, source=m.source, source_account=m.source_account,
            title=m.title, url=m.url, snippet=m.snippet, cover_url=m.cover_url,
            likes=m.likes, reads=m.reads, comments=m.comments,
            sentiment=m.sentiment, tags=m.tags,
            published_at=m.published_at.isoformat() if m.published_at else None,
            advisor_id=a.id if is_linked else 0,
            advisor_name=(a.name if is_linked else m.pending_advisor_name) or "",
            advisor_title=(a.title if is_linked else "") or "",
            advisor_homepage=(a.homepage_url if is_linked else "") or "",
            college_id=c.id if (is_linked and c) else 0,
            college_name=(c.name if (is_linked and c) else "") or "",
            school_id=s.id if (is_linked and s) else 0,
            school_name=(s.name if (is_linked and s) else m.pending_school_name) or "",
            school_short=(s.short_name or s.name) if (is_linked and s) else (m.pending_school_name or ""),
            school_province=(s.province if (is_linked and s) else "") or "",
            is_985=bool(s.is_985) if (is_linked and s) else False,
            is_211=bool(s.is_211) if (is_linked and s) else False,
            is_linked=is_linked,
        ))

    # Facets across the *unfiltered* set so user can see what's available
    src_rows = (await db.execute(
        select(M.source, func.count(M.id)).group_by(M.source)
    )).all()
    acc_rows = (await db.execute(
        select(M.source_account, func.count(M.id))
        .where(M.source_account != "")
        .group_by(M.source_account)
    )).all()
    sent_rows = (await db.execute(
        select(M.sentiment, func.count(M.id))
        .where(M.sentiment != "")
        .group_by(M.sentiment)
    )).all()

    return MentionFeedResponse(
        items=items, total=total, offset=offset, limit=limit,
        facets=MentionFeedFacets(
            sources={k: int(v) for k, v in src_rows if k},
            accounts={k: int(v) for k, v in acc_rows if k},
            sentiments={k: int(v) for k, v in sent_rows if k},
        ),
    )


@router.post("/advisor/mentions", response_model=MentionOut)
async def add_mention(payload: MentionIn, db: AsyncSession = Depends(get_db)):
    advisor = await _find_advisor(db, payload.advisor_id, payload.advisor_name, payload.school_name)
    if not advisor:
        raise HTTPException(404, "Advisor not found (provide advisor_id or unambiguous advisor_name+school_name)")
    pub = None
    if payload.published_at:
        try:
            pub = datetime.fromisoformat(payload.published_at.replace("Z", "+00:00"))
        except ValueError:
            pub = None
    mention = AdvisorMention(
        advisor_id=advisor.id,
        source=payload.source[:30],
        source_account=payload.source_account[:120],
        title=payload.title,
        url=payload.url[:500],
        snippet=payload.snippet,
        cover_url=payload.cover_url[:500],
        likes=payload.likes, reads=payload.reads, comments=payload.comments,
        sentiment=payload.sentiment[:20],
        tags=payload.tags,
        published_at=pub,
    )
    db.add(mention)
    await db.commit()
    await db.refresh(mention)
    return _serialize_mention(mention)


class BulkMentionsResult(BaseModel):
    inserted: int
    skipped_no_advisor: int
    examples_skipped: list[str]


# ─────── Conversational recommendation ───────

class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


@router.post("/advisor/chat")
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    if not req.messages:
        raise HTTPException(400, "messages cannot be empty")
    history = [{"role": m.role, "content": m.content} for m in req.messages]
    return await advisor_chat_service.chat_turn(db, history)


@router.post("/advisor/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE streaming version: emits tool_start/tool_end + delta tokens + done."""
    if not req.messages:
        raise HTTPException(400, "messages cannot be empty")
    history = [{"role": m.role, "content": m.content} for m in req.messages]

    from fastapi.responses import StreamingResponse
    import json as _json

    async def gen():
        try:
            async for ev in advisor_chat_service.chat_turn_stream(history):
                yield f"data: {_json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:
            err = {"type": "done", "error": str(e), "recommendations": [], "advisor_profiles": []}
            yield f"data: {_json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


class PendingMentionItem(BaseModel):
    id: int
    pending_advisor_name: str
    pending_school_name: str
    source: str
    source_account: str
    title: str
    url: str
    snippet: str
    sentiment: str
    tags: list[str] | None
    published_at: str | None


class PendingMentionsResponse(BaseModel):
    items: list[PendingMentionItem]
    total: int
    by_school: dict[str, int]


@router.get("/advisor/mentions/pending", response_model=PendingMentionsResponse)
async def list_pending_mentions(
    school: str | None = Query(None, description="Filter by pending_school_name"),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Mentions that haven't been linked to a real Advisor row yet (advisor not
    crawled). They'll auto-link the moment the matching advisor enters DB."""
    stmt = select(AdvisorMention).where(AdvisorMention.advisor_id == 0)
    if school:
        stmt = stmt.where(AdvisorMention.pending_school_name == school)
    rows = (await db.execute(
        stmt.order_by(AdvisorMention.published_at.desc().nulls_last(), AdvisorMention.id.desc()).limit(limit)
    )).scalars().all()
    total = (await db.execute(
        select(func.count(AdvisorMention.id)).where(AdvisorMention.advisor_id == 0)
    )).scalar() or 0
    by_school_rows = (await db.execute(
        select(AdvisorMention.pending_school_name, func.count(AdvisorMention.id))
        .where(AdvisorMention.advisor_id == 0)
        .group_by(AdvisorMention.pending_school_name)
    )).all()
    return PendingMentionsResponse(
        items=[
            PendingMentionItem(
                id=m.id,
                pending_advisor_name=m.pending_advisor_name,
                pending_school_name=m.pending_school_name,
                source=m.source, source_account=m.source_account,
                title=m.title, url=m.url, snippet=m.snippet,
                sentiment=m.sentiment, tags=m.tags,
                published_at=m.published_at.isoformat() if m.published_at else None,
            )
            for m in rows
        ],
        total=total,
        by_school={k: int(v) for k, v in by_school_rows if k},
    )


@router.post("/advisor/mentions/bulk", response_model=BulkMentionsResult)
async def bulk_add_mentions(payload: list[MentionIn], db: AsyncSession = Depends(get_db)):
    inserted = 0
    skipped: list[str] = []
    for p in payload:
        advisor = await _find_advisor(db, p.advisor_id, p.advisor_name, p.school_name)
        if not advisor:
            if len(skipped) < 5:
                skipped.append(f"{p.advisor_name}@{p.school_name}")
            continue
        pub = None
        if p.published_at:
            try:
                pub = datetime.fromisoformat(p.published_at.replace("Z", "+00:00"))
            except ValueError:
                pub = None
        db.add(AdvisorMention(
            advisor_id=advisor.id,
            source=p.source[:30], source_account=p.source_account[:120],
            title=p.title, url=p.url[:500], snippet=p.snippet,
            cover_url=p.cover_url[:500],
            likes=p.likes, reads=p.reads, comments=p.comments,
            sentiment=p.sentiment[:20], tags=p.tags,
            published_at=pub,
        ))
        inserted += 1
    await db.commit()
    return BulkMentionsResult(
        inserted=inserted,
        skipped_no_advisor=len(payload) - inserted,
        examples_skipped=skipped,
    )
