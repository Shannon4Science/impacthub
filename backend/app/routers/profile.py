"""Profile CRUD and data query endpoints."""

import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, Paper, GithubRepo, HFItem
from app.schemas import (
    UserCreate, UserOut, UserUpdate, DiscoveryStatus,
    ProfileFull, PaperOut, RepoOut, HFItemOut, StatsOut, TimelineEntry,
)
from pydantic import BaseModel as BaseModel
from app.services import scholar_service, github_service, hf_service, milestone_service
from app.services import dblp_service, snapshot_service, ccf_recompute_service
from app.services.discover_service import discover_from_github, discover_from_scholar
from app.utils.paper_dedup import deduplicate_papers
from app.deps import resolve_user
from app.config import SEMANTIC_SCHOLAR_API, OUTBOUND_PROXY

logger = logging.getLogger(__name__)
router = APIRouter()

# Simple in-memory cache for author domain lookups (avoids SS API rate limits)
_domain_cache: dict[str, str] = {}


async def _full_refresh(user_id: int):
    """Background task: pull data from all sources for a user."""
    from app.database import async_session
    async with async_session() as db:
        user = await db.get(User, user_id)
        if not user:
            return
        await scholar_service.fetch_papers_for_user(db, user)
        await dblp_service.fetch_dblp_papers_for_user(db, user)
        await ccf_recompute_service.recompute_ccf_for_user(db, user)
        await github_service.fetch_repos_for_user(db, user)
        await hf_service.fetch_hf_items_for_user(db, user)
        await milestone_service.check_milestones(db, user)
        await snapshot_service.record_daily_snapshot(db, user)
        await db.commit()


@router.get("/scholar-search")
async def search_scholars(
    q: str = Query(..., min_length=2),
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=50),
):
    """Proxy Semantic Scholar author search with domain info from top papers."""
    import asyncio
    from collections import Counter

    # Fetch a generous batch from SS to allow sorting by citations
    fetch_limit = max(offset + limit, 30)  # always fetch at least 30
    async with httpx.AsyncClient(timeout=15, proxy=OUTBOUND_PROXY) as client:
        resp = await client.get(
            f"{SEMANTIC_SCHOLAR_API}/author/search",
            params={
                "query": q,
                "fields": "name,paperCount,citationCount,hIndex,affiliations",
                "limit": fetch_limit,
            },
        )
        if resp.status_code != 200:
            logger.warning("Scholar search failed: %s", resp.status_code)
            return {"results": [], "total": 0, "offset": offset, "has_more": False}
        data = resp.json().get("data", [])
        total = resp.json().get("total", len(data))

        async def _get_domain(author_id: str) -> str:
            """Fetch top papers to determine primary research domain."""
            # Check cache first
            cached = _domain_cache.get(author_id)
            if cached is not None:
                return cached
            try:
                r = await client.get(
                    f"{SEMANTIC_SCHOLAR_API}/author/{author_id}/papers",
                    params={"fields": "s2FieldsOfStudy", "limit": 5},
                )
                if r.status_code != 200:
                    return ""
                papers = r.json().get("data", [])
                fields: list[str] = []
                for p in papers:
                    for f in (p.get("s2FieldsOfStudy") or []):
                        cat = f.get("category", "")
                        if cat:
                            fields.append(cat)
                domain = Counter(fields).most_common(1)[0][0] if fields else ""
                _domain_cache[author_id] = domain
                return domain
            except Exception:
                pass
            return ""

        # Keep SS relevance order, paginate
        page_data = data[offset:offset + limit]

        # Fetch domains in parallel only for current page
        domains = await asyncio.gather(*[_get_domain(c["authorId"]) for c in page_data])

        results = []
        for c, domain in zip(page_data, domains):
            results.append({
                "authorId": c.get("authorId", ""),
                "name": c.get("name", ""),
                "paperCount": c.get("paperCount", 0),
                "citationCount": c.get("citationCount", 0),
                "hIndex": c.get("hIndex", 0),
                "affiliations": c.get("affiliations") or [],
                "domain": domain,
            })

        has_more = (offset + limit) < len(data) or len(data) >= fetch_limit
        return {"results": results, "total": total, "offset": offset, "has_more": has_more}


@router.get("/github-search")
async def search_github_repos(q: str = Query(..., min_length=2)):
    """Proxy GitHub repo search."""
    headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
    from app.config import GITHUB_TOKEN
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    try:
        async with httpx.AsyncClient(timeout=10, proxy=OUTBOUND_PROXY) as client:
            resp = await client.get(
                f"https://api.github.com/search/repositories",
                params={"q": q, "per_page": 8, "sort": "stars", "order": "desc"},
                headers=headers,
            )
            if resp.status_code != 200:
                return {"results": []}
            items = resp.json().get("items", [])
            return {"results": [
                {
                    "full_name": r.get("full_name", ""),
                    "description": (r.get("description") or "")[:120],
                    "stars": r.get("stargazers_count", 0),
                    "language": r.get("language") or "",
                }
                for r in items
            ]}
    except Exception:
        return {"results": []}


@router.get("/hf-search")
async def search_hf_items(
    q: str = Query(..., min_length=2),
    type: str = Query("model"),
):
    """Proxy HuggingFace model/dataset search."""
    api_path = "models" if type == "model" else "datasets"
    try:
        async with httpx.AsyncClient(timeout=10, proxy=OUTBOUND_PROXY) as client:
            resp = await client.get(
                f"https://huggingface.co/api/{api_path}",
                params=[
                    ("search", q), ("sort", "downloads"), ("direction", "-1"), ("limit", "8"),
                    ("expand[]", "downloadsAllTime"), ("expand[]", "downloads"), ("expand[]", "likes"),
                ],
            )
            if resp.status_code != 200:
                return {"results": []}
            items = resp.json()
            return {"results": [
                {
                    "id": r.get("id", ""),
                    "downloads": r.get("downloadsAllTime", r.get("downloads", 0)),
                    "likes": r.get("likes", 0),
                }
                for r in items[:8]
            ]}
    except Exception:
        return {"results": []}


@router.get("/profiles")
async def list_profiles(db: AsyncSession = Depends(get_db)):
    users = (await db.execute(select(User).order_by(User.created_at.asc()))).scalars().all()
    result = []
    for u in users:
        papers = (await db.execute(select(Paper).where(Paper.user_id == u.id))).scalars().all()
        repos = (await db.execute(select(GithubRepo).where(GithubRepo.user_id == u.id))).scalars().all()
        hf_items_db = (await db.execute(select(HFItem).where(HFItem.user_id == u.id))).scalars().all()
        result.append({
            **UserOut.model_validate(u).model_dump(),
            "paper_count": len(papers),
            "total_citations": sum(p.citation_count for p in papers),
            "repo_count": len(repos),
            "total_stars": sum(r.stars for r in repos),
            "hf_count": len(hf_items_db),
            "total_downloads": sum(h.downloads for h in hf_items_db),
        })
    return result


async def _check_id_conflict(
    db: AsyncSession,
    field_name: str,
    value: str,
    exclude_user_id: int | None = None,
) -> User | None:
    """Return the existing user that already owns *value* for *field_name*, or None."""
    if not value:
        return None
    col = getattr(User, field_name)
    stmt = select(User).where(col == value)
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    return (await db.execute(stmt)).scalars().first()


@router.post("/profile", response_model=DiscoveryStatus)
async def create_profile(
    data: UserCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    if not data.scholar_id:
        raise HTTPException(400, "Semantic Scholar ID 不能为空")

    existing = (await db.execute(
        select(User).where(User.scholar_id == data.scholar_id)
    )).scalars().first()

    if existing:
        background_tasks.add_task(_full_refresh, existing.id)
        return DiscoveryStatus(
            user=UserOut.model_validate(existing),
            scholar_found=True,
            scholar_confidence="high",
            hf_found=bool(existing.hf_username),
            hf_confidence="high" if existing.hf_username else "",
            github_found=bool(existing.github_username),
            github_confidence="high" if existing.github_username else "",
            message="已有档案，正在后台刷新数据",
        )

    # Check user-supplied IDs for conflicts
    if data.github_username:
        conflict = await _check_id_conflict(db, "github_username", data.github_username)
        if conflict:
            raise HTTPException(
                409,
                f"GitHub 用户名 {data.github_username} 已被 {conflict.name or conflict.scholar_id} 使用",
            )
    if data.hf_username:
        conflict = await _check_id_conflict(db, "hf_username", data.hf_username)
        if conflict:
            raise HTTPException(
                409,
                f"HuggingFace 用户名 {data.hf_username} 已被 {conflict.name or conflict.scholar_id} 使用",
            )

    # Auto-discover accounts from Scholar ID
    discovery = await discover_from_scholar(data.scholar_id)
    if discovery.errors:
        raise HTTPException(400, discovery.errors[0])

    github_username = data.github_username or discovery.github_username
    hf_username = data.hf_username or discovery.hf_username

    # Skip auto-discovered IDs that are already registered to another user
    if github_username and not data.github_username:
        if await _check_id_conflict(db, "github_username", github_username):
            logger.info("Auto-discovered github_username %s already registered, skipping", github_username)
            github_username = ""
    if hf_username and not data.hf_username:
        if await _check_id_conflict(db, "hf_username", hf_username):
            logger.info("Auto-discovered hf_username %s already registered, skipping", hf_username)
            hf_username = ""

    user = User(
        scholar_id=data.scholar_id,
        github_username=github_username,
        name=discovery.name,
        avatar_url=discovery.avatar_url,
        bio=discovery.bio,
        hf_username=hf_username,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    background_tasks.add_task(_full_refresh, user.id)

    # Build discovery message
    parts = []
    if github_username:
        parts.append("GitHub")
    if hf_username:
        parts.append("Hugging Face")

    if parts:
        msg = f"已自动关联 {' 和 '.join(parts)}"
    else:
        msg = "未能自动发现其他平台账号，可稍后手动关联"

    missing = []
    if not github_username:
        missing.append("GitHub")
    if not hf_username:
        missing.append("Hugging Face")
    if missing:
        msg += f"。{'、'.join(missing)} 未找到"

    logger.info(
        "Created user %d: scholar=%s, github=%s, hf=%s",
        user.id, data.scholar_id, github_username, hf_username,
    )

    return DiscoveryStatus(
        user=UserOut.model_validate(user),
        scholar_found=True,
        scholar_confidence="manual",
        hf_found=bool(hf_username),
        hf_confidence=discovery.hf_confidence if hf_username else "",
        github_found=bool(github_username),
        github_confidence="high" if github_username == discovery.github_username and github_username else "",
        message=msg,
    )


@router.patch("/profile/{identifier}", response_model=UserOut)
async def update_profile(
    background_tasks: BackgroundTasks,
    data: UserUpdate,
    user: User = Depends(resolve_user),
    db: AsyncSession = Depends(get_db),
):
    # Duplicate checks (exclude self)
    for field, label in [
        ("scholar_id", "Scholar ID"),
        ("github_username", "GitHub 用户名"),
        ("hf_username", "HuggingFace 用户名"),
    ]:
        new_val = getattr(data, field, None)
        if new_val is not None and new_val != getattr(user, field):
            conflict = await _check_id_conflict(db, field, new_val, exclude_user_id=user.id)
            if conflict:
                raise HTTPException(
                    409,
                    f"{label} {new_val} 已被 {conflict.name or conflict.scholar_id} 使用",
                )

    if data.scholar_id is not None:
        user.scholar_id = data.scholar_id
    if data.github_username is not None:
        user.github_username = data.github_username
    if data.hf_username is not None:
        user.hf_username = data.hf_username
    if data.twitter_username is not None:
        user.twitter_username = data.twitter_username
    if data.homepage is not None:
        user.homepage = data.homepage
    if data.feishu_webhook is not None:
        user.feishu_webhook = data.feishu_webhook

    await db.commit()
    await db.refresh(user)
    background_tasks.add_task(_full_refresh, user.id)
    return user


# ---------- Manual add repo / HF item ----------

class AddRepoRequest(BaseModel):
    repo_full_name: str  # e.g. "owner/repo"

class AddHFItemRequest(BaseModel):
    item_id: str  # e.g. "owner/model-name"
    item_type: str = "model"  # "model" or "dataset"


@router.post("/profile/{identifier}/repos")
async def add_repo_manual(
    body: AddRepoRequest,
    user: User = Depends(resolve_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually add a GitHub repo by owner/name. Fetches latest stats from GitHub API."""
    repo_name = body.repo_full_name.strip().strip("/")
    if "/" not in repo_name:
        raise HTTPException(400, "格式应为 owner/repo，如 pytorch/pytorch")

    # Check if already exists
    existing = (await db.execute(
        select(GithubRepo).where(GithubRepo.user_id == user.id, GithubRepo.repo_name == repo_name)
    )).scalars().first()
    if existing:
        raise HTTPException(409, f"仓库 {repo_name} 已存在")

    # Fetch repo info from GitHub
    async with httpx.AsyncClient(timeout=15, proxy=OUTBOUND_PROXY) as client:
        headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
        from app.config import GITHUB_TOKEN
        if GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
        resp = await client.get(f"https://api.github.com/repos/{repo_name}", headers=headers)
        if resp.status_code == 404:
            raise HTTPException(404, f"GitHub 仓库 {repo_name} 不存在")
        if resp.status_code != 200:
            raise HTTPException(502, "GitHub API 请求失败")
        raw = resp.json()

    created = None
    if raw.get("created_at"):
        try:
            created = datetime.fromisoformat(raw["created_at"].replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    repo = GithubRepo(
        user_id=user.id,
        repo_name=raw.get("full_name", repo_name),
        description=raw.get("description", "") or "",
        stars=raw.get("stargazers_count", 0),
        forks=raw.get("forks_count", 0),
        language=raw.get("language", "") or "",
        url=raw.get("html_url", ""),
        created_at_remote=created,
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)
    return RepoOut.model_validate(repo)


@router.post("/profile/{identifier}/hf-items")
async def add_hf_item_manual(
    body: AddHFItemRequest,
    user: User = Depends(resolve_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually add a HuggingFace model or dataset by ID."""
    item_id = body.item_id.strip().strip("/")
    item_type = body.item_type.strip().lower()
    if item_type not in ("model", "dataset"):
        raise HTTPException(400, "item_type 必须为 model 或 dataset")

    existing = (await db.execute(
        select(HFItem).where(HFItem.user_id == user.id, HFItem.item_id == item_id)
    )).scalars().first()
    if existing:
        raise HTTPException(409, f"项目 {item_id} 已存在")

    # Fetch info from HuggingFace
    api_path = "models" if item_type == "model" else "datasets"
    async with httpx.AsyncClient(timeout=15, proxy=OUTBOUND_PROXY) as client:
        resp = await client.get(
                f"https://huggingface.co/api/{api_path}/{item_id}",
                params=[("expand[]", "downloadsAllTime"), ("expand[]", "downloads"), ("expand[]", "likes")],
            )
        if resp.status_code == 404:
            raise HTTPException(404, f"HuggingFace {item_type} {item_id} 不存在")
        if resp.status_code != 200:
            raise HTTPException(502, "HuggingFace API 请求失败")
        raw = resp.json()

    hf_item = HFItem(
        user_id=user.id,
        item_id=item_id,
        item_type=item_type,
        name=raw.get("id", item_id),
        downloads=raw.get("downloadsAllTime") or raw.get("downloads", 0),
        likes=raw.get("likes", 0),
        url=f"https://huggingface.co/{item_id}" if item_type == "model" else f"https://huggingface.co/datasets/{item_id}",
    )
    db.add(hf_item)
    await db.commit()
    await db.refresh(hf_item)
    return HFItemOut.model_validate(hf_item)


@router.delete("/profile/{identifier}/repos/{repo_id}")
async def delete_repo(
    repo_id: int,
    user: User = Depends(resolve_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a GitHub repo from the user's profile."""
    repo = await db.get(GithubRepo, repo_id)
    if not repo or repo.user_id != user.id:
        raise HTTPException(404, "仓库不存在")
    await db.delete(repo)
    await db.commit()
    return {"ok": True}


@router.delete("/profile/{identifier}/hf-items/{item_id}")
async def delete_hf_item(
    item_id: int,
    user: User = Depends(resolve_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a HuggingFace item from the user's profile."""
    item = await db.get(HFItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(404, "项目不存在")
    await db.delete(item)
    await db.commit()
    return {"ok": True}


@router.get("/profile/{identifier}", response_model=ProfileFull)
async def get_profile(
    user: User = Depends(resolve_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = user.id

    papers_raw = (await db.execute(
        select(Paper).where(Paper.user_id == user_id).order_by(Paper.citation_count.desc())
    )).scalars().all()
    papers = deduplicate_papers(papers_raw)
    papers.sort(key=lambda p: p.citation_count, reverse=True)

    repos = (await db.execute(
        select(GithubRepo).where(GithubRepo.user_id == user_id).order_by(GithubRepo.stars.desc())
    )).scalars().all()

    hf_items = (await db.execute(
        select(HFItem).where(HFItem.user_id == user_id).order_by(HFItem.downloads.desc())
    )).scalars().all()

    papers_out = [
        PaperOut(
            id=p.id, semantic_scholar_id=p.semantic_scholar_id,
            title=p.title, year=p.year, venue=p.venue,
            citation_count=p.citation_count,
            authors=p.authors_json if isinstance(p.authors_json, list) else [],
            url=p.url,
            ccf_rank=p.ccf_rank or "",
            ccf_category=p.ccf_category or "",
            updated_at=p.updated_at,
        ) for p in papers
    ]

    return ProfileFull(
        user=UserOut.model_validate(user),
        papers=papers_out,
        repos=[RepoOut.model_validate(r) for r in repos],
        hf_items=[HFItemOut.model_validate(h) for h in hf_items],
    )


@router.get("/profile/{identifier}/stats", response_model=StatsOut)
async def get_stats(
    user: User = Depends(resolve_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = user.id

    papers_raw = (await db.execute(
        select(Paper).where(Paper.user_id == user_id).order_by(Paper.citation_count.desc())
    )).scalars().all()
    papers = deduplicate_papers(papers_raw)
    repos = (await db.execute(select(GithubRepo).where(GithubRepo.user_id == user_id))).scalars().all()
    hf_items = (await db.execute(select(HFItem).where(HFItem.user_id == user_id))).scalars().all()

    citation_counts = sorted([p.citation_count for p in papers], reverse=True)
    h_index = 0
    for i, c in enumerate(citation_counts):
        if c >= i + 1:
            h_index = i + 1
        else:
            break

    return StatsOut(
        total_citations=sum(p.citation_count for p in papers),
        total_stars=sum(r.stars for r in repos),
        total_forks=sum(r.forks for r in repos),
        total_downloads=sum(h.downloads for h in hf_items),
        total_hf_likes=sum(h.likes for h in hf_items),
        paper_count=len(papers),
        repo_count=len(repos),
        hf_count=len(hf_items),
        h_index=h_index,
        ccf_a_count=sum(1 for p in papers if (p.ccf_rank or "") == "A"),
        ccf_b_count=sum(1 for p in papers if (p.ccf_rank or "") == "B"),
        ccf_c_count=sum(1 for p in papers if (p.ccf_rank or "") == "C"),
    )


@router.get("/profile/{identifier}/timeline", response_model=list[TimelineEntry])
async def get_timeline(
    user: User = Depends(resolve_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = user.id
    entries: list[TimelineEntry] = []

    papers_raw = (await db.execute(select(Paper).where(Paper.user_id == user_id))).scalars().all()
    papers = deduplicate_papers(papers_raw)
    for p in papers:
        entries.append(TimelineEntry(
            date=f"{p.year}-01-01" if p.year else "1970-01-01",
            type="paper", title=p.title,
            detail=f"{p.venue} | {p.citation_count} citations", url=p.url,
        ))

    repos = (await db.execute(select(GithubRepo).where(GithubRepo.user_id == user_id))).scalars().all()
    for r in repos:
        d = r.created_at_remote.strftime("%Y-%m-%d") if r.created_at_remote else "2020-01-01"
        entries.append(TimelineEntry(
            date=d, type="repo", title=r.repo_name,
            detail=f"{r.language} | {r.stars} stars", url=r.url,
        ))

    hf_items = (await db.execute(select(HFItem).where(HFItem.user_id == user_id))).scalars().all()
    for h in hf_items:
        entries.append(TimelineEntry(
            date=h.updated_at.strftime("%Y-%m-%d") if h.updated_at else "2020-01-01",
            type=f"hf_{h.item_type}", title=h.name,
            detail=f"{h.downloads} downloads | {h.likes} likes", url=h.url,
        ))

    entries.sort(key=lambda e: e.date, reverse=True)
    return entries
