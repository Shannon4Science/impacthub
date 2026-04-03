"""Report export endpoints: generates filtered, formatted paper lists for applications."""

from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, Paper, GithubRepo, HFItem, CitationAnalysis, NotableCitation
from app.schemas import ResearchBasisRequest, PaperEvidenceOut, NotableCitationBrief
from app.utils.paper_dedup import deduplicate_papers
from app.deps import resolve_user
from app.services.research_basis_service import (
    GRANT_TYPES, collect_paper_evidence, generate_research_basis, PaperInput,
)

router = APIRouter()


@router.get("/report/{identifier}/papers")
async def export_paper_report(
    year_from: int = Query(default=0, description="起始年份"),
    year_to: int = Query(default=9999, description="结束年份"),
    ccf_rank: str = Query(default="", description="CCF 等级筛选 (A/B/C)，逗号分隔"),
    min_citations: int = Query(default=0, description="最低引用数"),
    first_author: str = Query(default="", description="第一作者名字（模糊匹配）"),
    format: str = Query(default="json", description="输出格式: json / markdown / bibtex"),
    user: User = Depends(resolve_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = user.id

    query = select(Paper).where(Paper.user_id == user_id)
    papers_raw = (await db.execute(query.order_by(Paper.citation_count.desc()))).scalars().all()
    papers = deduplicate_papers(papers_raw)

    ccf_filter = set(r.strip().upper() for r in ccf_rank.split(",") if r.strip()) if ccf_rank else None
    first_author_lower = first_author.lower().strip() if first_author else ""

    filtered = []
    for p in papers:
        if p.year and (p.year < year_from or p.year > year_to):
            continue
        if p.citation_count < min_citations:
            continue
        if ccf_filter and (p.ccf_rank or "").upper() not in ccf_filter:
            continue
        if first_author_lower:
            authors = p.authors_json if isinstance(p.authors_json, list) else []
            if not authors or first_author_lower not in authors[0].lower():
                continue
        filtered.append(p)

    ccf_a = sum(1 for p in filtered if p.ccf_rank == "A")
    ccf_b = sum(1 for p in filtered if p.ccf_rank == "B")
    ccf_c = sum(1 for p in filtered if p.ccf_rank == "C")
    total_cit = sum(p.citation_count for p in filtered)

    if format == "markdown":
        return _export_markdown(user, filtered, ccf_a, ccf_b, ccf_c, total_cit)
    elif format == "bibtex":
        return _export_bibtex(filtered)
    else:
        return {
            "user": user.name,
            "filter": {
                "year_from": year_from, "year_to": year_to,
                "ccf_rank": ccf_rank, "min_citations": min_citations,
            },
            "summary": {
                "total": len(filtered),
                "ccf_a": ccf_a, "ccf_b": ccf_b, "ccf_c": ccf_c,
                "total_citations": total_cit,
            },
            "papers": [
                {
                    "title": p.title,
                    "year": p.year,
                    "venue": p.venue,
                    "ccf_rank": p.ccf_rank,
                    "ccf_category": p.ccf_category,
                    "citation_count": p.citation_count,
                    "authors": p.authors_json if isinstance(p.authors_json, list) else [],
                    "url": p.url,
                }
                for p in filtered
            ],
        }


@router.get("/report/{identifier}/summary")
async def export_full_summary(
    user: User = Depends(resolve_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a comprehensive summary of all assets."""
    user_id = user.id

    papers_raw = (await db.execute(
        select(Paper).where(Paper.user_id == user_id).order_by(Paper.citation_count.desc())
    )).scalars().all()
    papers = deduplicate_papers(papers_raw)
    repos = (await db.execute(
        select(GithubRepo).where(GithubRepo.user_id == user_id).order_by(GithubRepo.stars.desc())
    )).scalars().all()
    hf_items = (await db.execute(
        select(HFItem).where(HFItem.user_id == user_id).order_by(HFItem.downloads.desc())
    )).scalars().all()

    total_cit = sum(p.citation_count for p in papers)
    ccf_a = [p for p in papers if p.ccf_rank == "A"]
    ccf_b = [p for p in papers if p.ccf_rank == "B"]
    total_stars = sum(r.stars for r in repos)
    total_downloads = sum(h.downloads for h in hf_items)

    # h-index
    cits = sorted([p.citation_count for p in papers], reverse=True)
    h_index = 0
    for i, c in enumerate(cits):
        if c >= i + 1:
            h_index = i + 1
        else:
            break

    # Top cited paper
    top_paper = papers[0] if papers else None
    top_repo = repos[0] if repos else None

    return {
        "user": {
            "name": user.name,
            "github": user.github_username,
            "scholar_id": user.scholar_id,
            "hf": user.hf_username,
        },
        "academic": {
            "paper_count": len(papers),
            "total_citations": total_cit,
            "h_index": h_index,
            "ccf_a_count": len(ccf_a),
            "ccf_b_count": len(ccf_b),
            "top_cited_paper": {
                "title": top_paper.title,
                "citations": top_paper.citation_count,
                "venue": top_paper.venue,
                "ccf_rank": top_paper.ccf_rank,
            } if top_paper else None,
            "ccf_a_papers": [
                {"title": p.title, "venue": p.venue, "year": p.year, "citations": p.citation_count}
                for p in ccf_a
            ],
        },
        "engineering": {
            "repo_count": len(repos),
            "total_stars": total_stars,
            "total_forks": sum(r.forks for r in repos),
            "top_repo": {
                "name": top_repo.repo_name,
                "stars": top_repo.stars,
                "language": top_repo.language,
            } if top_repo else None,
        },
        "data_models": {
            "hf_count": len(hf_items),
            "total_downloads": total_downloads,
            "total_likes": sum(h.likes for h in hf_items),
            "models": sum(1 for h in hf_items if h.item_type == "model"),
            "datasets": sum(1 for h in hf_items if h.item_type == "dataset"),
        },
        "generated_at": datetime.utcnow().isoformat(),
    }


def _export_markdown(user, papers, ccf_a, ccf_b, ccf_c, total_cit):
    lines = [
        f"# {user.name} 论文成果",
        "",
        f"**共 {len(papers)} 篇论文** | 总引用 {total_cit:,} | "
        f"CCF-A: {ccf_a} | CCF-B: {ccf_b} | CCF-C: {ccf_c}",
        "",
        "---",
        "",
    ]

    for i, p in enumerate(papers, 1):
        authors = p.authors_json if isinstance(p.authors_json, list) else []
        author_str = ", ".join(authors[:5])
        if len(authors) > 5:
            author_str += f" 等 {len(authors)} 人"

        ccf_tag = f" **[CCF-{p.ccf_rank}]**" if p.ccf_rank else ""
        lines.append(f"{i}. **{p.title}**{ccf_tag}")
        lines.append(f"   {author_str}")
        lines.append(f"   *{p.venue}*, {p.year} | 被引 {p.citation_count}")
        lines.append("")

    content = "\n".join(lines)
    buf = BytesIO(content.encode("utf-8"))
    return StreamingResponse(
        buf,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={user.name}-papers.md"},
    )


def _export_bibtex(papers):
    lines = []
    for p in papers:
        authors = p.authors_json if isinstance(p.authors_json, list) else []
        key = f"{(authors[0].split()[-1] if authors else 'unknown').lower()}{p.year}{p.title.split()[0].lower()}"
        lines.append(f"@article{{{key},")
        lines.append(f"  title = {{{p.title}}},")
        lines.append(f"  author = {{{' and '.join(authors)}}},")
        lines.append(f"  year = {{{p.year}}},")
        if p.venue:
            lines.append(f"  journal = {{{p.venue}}},")
        if p.url:
            lines.append(f"  url = {{{p.url}}},")
        lines.append("}")
        lines.append("")

    content = "\n".join(lines)
    buf = BytesIO(content.encode("utf-8"))
    return StreamingResponse(
        buf,
        media_type="application/x-bibtex; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=papers.bib"},
    )


# ---------- Grant types list ----------

@router.get("/report/grant-types")
async def list_grant_types():
    """Return available grant types for research-basis export."""
    return [
        {"key": k, "name": v["name"], "tone": v["tone"], "desc": v["desc"], "group": v.get("group", "nsfc")}
        for k, v in GRANT_TYPES.items()
    ]


# ---------- Paper evidence preview ----------

@router.get("/report/{identifier}/paper-evidence/{paper_id}")
async def get_paper_evidence(
    paper_id: int,
    user: User = Depends(resolve_user),
    db: AsyncSession = Depends(get_db),
):
    """Return citation analysis + notable scholar data for a single paper."""
    paper = await db.get(Paper, paper_id)
    if not paper or paper.user_id != user.id:
        from fastapi import HTTPException
        raise HTTPException(404, "论文不存在")

    ca = (await db.execute(
        select(CitationAnalysis).where(CitationAnalysis.paper_id == paper_id)
    )).scalars().first()

    ncs = (await db.execute(
        select(NotableCitation)
        .where(NotableCitation.paper_id == paper_id, NotableCitation.user_id == user.id)
        .order_by(NotableCitation.author_h_index.desc())
    )).scalars().all()

    # Build brief notable citations — honor-tagged first
    honored = [nc for nc in ncs if nc.honor_tags]
    rest = [nc for nc in ncs if not nc.honor_tags]
    sorted_ncs = (honored + rest)[:10]

    nc_briefs = []
    for nc in sorted_ncs:
        contexts = nc.contexts_json if isinstance(nc.contexts_json, list) else []
        snippet = (contexts[0][:100] + "...") if contexts and len(contexts[0]) > 100 else (contexts[0] if contexts else "")
        nc_briefs.append(NotableCitationBrief(
            author_name=nc.author_name,
            author_h_index=nc.author_h_index,
            honor_tags=nc.honor_tags if isinstance(nc.honor_tags, list) else [],
            citing_paper_title=nc.citing_paper_title,
            citing_paper_venue=nc.citing_paper_venue,
            citing_paper_year=nc.citing_paper_year,
            context_snippet=snippet,
        ))

    authors = paper.authors_json if isinstance(paper.authors_json, list) else []

    return PaperEvidenceOut(
        paper_id=paper.id,
        title=paper.title,
        venue=paper.venue,
        year=paper.year,
        citation_count=paper.citation_count,
        ccf_rank=paper.ccf_rank or "",
        authors=authors,
        total_citing_papers=ca.total_citing_papers if ca else 0,
        influential_count=ca.influential_count if ca else 0,
        top_scholar_count=ca.top_scholar_count if ca else 0,
        notable_scholar_count=ca.notable_scholar_count if ca else 0,
        notable_citations=nc_briefs,
    )


# ---------- Research basis generation ----------

@router.post("/report/{identifier}/research-basis")
async def generate_research_basis_endpoint(
    body: ResearchBasisRequest,
    format: str = Query(default="json"),
    user: User = Depends(resolve_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate '研究基础与可行性分析' Markdown."""
    paper_inputs = [
        PaperInput(
            paper_id=p.paper_id,
            scientific_question=p.scientific_question,
            innovation_summary=p.innovation_summary,
            relevance=p.relevance,
            linked_repo_ids=p.linked_repo_ids,
            linked_hf_item_ids=p.linked_hf_item_ids,
        )
        for p in body.papers
    ]

    markdown = await generate_research_basis(
        db, user.id, body.grant_type, body.project_title, paper_inputs
    )

    if format == "markdown":
        buf = BytesIO(markdown.encode("utf-8"))
        return StreamingResponse(
            buf,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=research-basis-{user.name}.md"},
        )

    return {"markdown": markdown}
