"""GitHub API client for fetching user repositories."""

import logging
import re
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import GITHUB_API, GITHUB_TOKEN, OUTBOUND_PROXY
from app.models import GithubRepo, User

logger = logging.getLogger(__name__)


async def _fetch_pinned_repos(client: httpx.AsyncClient, username: str, headers: dict) -> list[dict]:
    """Fetch pinned repos by scraping the GitHub profile page, then get details via REST API.
    Only returns repos if the user has manually pinned them (not GitHub's auto 'Popular repositories')."""
    pinned: list[dict] = []
    try:
        resp = await client.get(
            f"https://github.com/{username}",
            headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0"},
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return []

        # Check if the section is truly "Pinned" (manually set) vs "Popular repositories" (auto)
        pinned_section = re.search(r'js-pinned-items-reorder-container">\s*<h2[^>]*>\s*(\w+)', resp.text, re.DOTALL)
        if not pinned_section or pinned_section.group(1) != "Pinned":
            logger.debug("User %s has no manual pins (found: %s)", username, pinned_section.group(1) if pinned_section else "none")
            return []

        # Extract repo names from pinned section: <span class="repo">reponame</span>
        repo_names = re.findall(r'class="repo"[^>]*>([^<]+)<', resp.text)
        if not repo_names:
            return []

        # Also extract the owner from the href — pinned repos link to /owner/repo
        # Pattern: pinned-item-list ... href="/owner/repo"
        full_names = re.findall(
            r'<a[^>]*href="/([^/]+/[^/"]+)"[^>]*class="[^"]*text-bold[^"]*"',
            resp.text,
        )
        if not full_names:
            # Fallback: assume all pinned are under the user
            full_names = [f"{username}/{name.strip()}" for name in repo_names]

        for full_name in full_names:
            full_name = full_name.strip()
            try:
                detail = await client.get(
                    f"{GITHUB_API}/repos/{full_name}",
                    headers=headers,
                )
                if detail.status_code != 200:
                    continue
                d = detail.json()
                if d.get("fork"):
                    continue
                pinned.append(d)
            except Exception:
                continue

    except Exception:
        logger.debug("Failed to fetch pinned repos for %s", username)
    return pinned


async def fetch_repos_for_user(db: AsyncSession, user: User) -> list[GithubRepo]:
    """Fetch all public repos + pinned repos for a GitHub user and upsert into DB."""
    if not user.github_username:
        return []

    headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    all_repos_raw: list[dict] = []
    seen_names: set[str] = set()
    page = 1

    async with httpx.AsyncClient(timeout=30, headers=headers, proxy=OUTBOUND_PROXY) as client:
        if not user.avatar_url:
            uresp = await client.get(f"{GITHUB_API}/users/{user.github_username}")
            if uresp.status_code == 200:
                udata = uresp.json()
                if not user.avatar_url:
                    user.avatar_url = udata.get("avatar_url", "")
                if not user.name:
                    user.name = udata.get("name", "") or user.github_username
                if not user.bio:
                    user.bio = udata.get("bio", "") or ""

        # Fetch pinned repos first (may include non-owned repos)
        pinned = await _fetch_pinned_repos(client, user.github_username, headers)
        pinned_names: set[str] = set()
        for raw in pinned:
            name = raw["full_name"]
            pinned_names.add(name)
            if name not in seen_names:
                seen_names.add(name)
                all_repos_raw.append(raw)

        # Fetch owned repos
        while True:
            resp = await client.get(
                f"{GITHUB_API}/users/{user.github_username}/repos",
                params={"per_page": 100, "page": page, "sort": "updated", "type": "owner"},
            )
            if resp.status_code != 200:
                logger.warning("GitHub repos fetch failed page %d: %s", page, resp.text)
                break
            batch = resp.json()
            if not batch:
                break
            for raw in batch:
                name = raw.get("full_name", "")
                if name not in seen_names:
                    seen_names.add(name)
                    all_repos_raw.append(raw)
            if len(batch) < 100:
                break
            page += 1

    existing = {
        r.repo_name: r
        for r in (await db.execute(select(GithubRepo).where(GithubRepo.user_id == user.id))).scalars().all()
    }

    result: list[GithubRepo] = []
    for raw in all_repos_raw:
        if raw.get("fork"):
            continue
        name = raw.get("full_name", "")
        created = None
        if raw.get("created_at"):
            try:
                created = datetime.fromisoformat(raw["created_at"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        if name in existing:
            repo = existing[name]
            repo.stars = raw.get("stargazers_count", 0)
            repo.forks = raw.get("forks_count", 0)
            repo.description = raw.get("description", "") or ""
            repo.language = raw.get("language", "") or ""
            repo.url = raw.get("html_url", "")
            repo.is_pinned = name in pinned_names
            repo.updated_at = datetime.utcnow()
        else:
            repo = GithubRepo(
                user_id=user.id,
                repo_name=name,
                description=raw.get("description", "") or "",
                stars=raw.get("stargazers_count", 0),
                forks=raw.get("forks_count", 0),
                language=raw.get("language", "") or "",
                url=raw.get("html_url", ""),
                is_pinned=name in pinned_names,
                created_at_remote=created,
            )
            db.add(repo)
        result.append(repo)

    await db.commit()
    logger.info("Synced %d repos (incl. pinned) for user %d", len(result), user.id)
    return result
