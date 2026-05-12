"""Batch import seed scholars from docs/seed_scholars.json (or _enriched).

For each scholar:
  1. Search Semantic Scholar by name (filter by affiliation to pick best match)
  2. If not already in DB, create User + trigger discovery
  3. Set honor_tags / research_direction / seed_tier on the User

Usage:
    cd backend
    python -m scripts.seed_import              # uses seed_scholars.json
    python -m scripts.seed_import --enriched   # uses seed_scholars_enriched.json (merges proposed honors)
    python -m scripts.seed_import --limit 5    # only first 5 scholars
    python -m scripts.seed_import --dry-run    # show what would happen, don't write
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline._common import setup_logging  # noqa: E402  (also adds backend/ to sys.path)

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import SEMANTIC_SCHOLAR_API, OUTBOUND_PROXY
from app.database import async_session, init_db
from app.models import User

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
SEED_FILE = ROOT / "docs" / "seed_scholars.json"
ENRICHED_FILE = ROOT / "docs" / "seed_scholars_enriched.json"


async def _get_with_retry(client: httpx.AsyncClient, url: str, params: dict | None = None, max_retries: int = 5) -> httpx.Response | None:
    """GET with backoff on 429/5xx."""
    delay = 2.0
    for attempt in range(max_retries):
        try:
            resp = await client.get(url, params=params, timeout=25)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 429 or resp.status_code >= 500:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            return resp  # other non-200, return as-is
        except Exception as e:
            logger.warning("  request error (%s), retrying in %.1fs", e, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
    return None


async def search_scholar(client: httpx.AsyncClient, name: str, affiliation: str) -> str | None:
    """Find the best-matching Semantic Scholar authorId for a given name+affiliation."""
    try:
        resp = await _get_with_retry(
            client,
            f"{SEMANTIC_SCHOLAR_API}/author/search",
            params={
                "query": name,
                "fields": "name,paperCount,citationCount,hIndex,affiliations",
                "limit": 10,
            },
        )
        if resp is None or resp.status_code != 200:
            logger.warning("  Scholar search %s returned %s", name, resp.status_code if resp else "no-response")
            return None
        candidates = resp.json().get("data", [])
        if not candidates:
            return None

        # Prefer the candidate whose affiliation tokens overlap with ours
        aff_tokens = set(affiliation.lower().replace("/", " ").split())
        # Exclude generic/noisy tokens
        aff_tokens -= {"university", "of", "the", "and", "&"}

        def score(c: dict) -> tuple:
            # Prefer higher citations + affiliation overlap, but cap extreme lopsided matches
            c_affs = " ".join(c.get("affiliations") or []).lower()
            overlap = sum(1 for t in aff_tokens if t and t in c_affs)
            cit = c.get("citationCount") or 0
            h = c.get("hIndex") or 0
            return (overlap, h, cit)

        best = max(candidates, key=score)
        best_overlap = score(best)[0]
        if best_overlap == 0 and candidates:
            # Affiliation didn't match; fall back to highest-h candidate with a warning
            best = max(candidates, key=lambda c: (c.get("hIndex") or 0, c.get("citationCount") or 0))
            logger.warning("  No affiliation match for %s, fallback to top-h: %s", name, best.get("name"))

        return best.get("authorId")
    except Exception as e:
        logger.warning("  Scholar search failed for %s: %s", name, e)
        return None


async def _discover_from_scholar_direct(scholar_id: str, max_retries: int = 3) -> dict:
    """Call discover_from_scholar with retries (since it may hit SS 429)."""
    from app.services.discover_service import discover_from_scholar
    delay = 3.0
    for attempt in range(max_retries):
        result = await discover_from_scholar(scholar_id)
        if not result.errors:
            return {
                "scholar_id": scholar_id,
                "name": result.name,
                "avatar_url": result.avatar_url,
                "bio": result.bio,
                "github_username": result.github_username,
                "hf_username": result.hf_username,
                "errors": [],
            }
        # Retry only on SS lookup failures
        logger.info("  discover error (attempt %d/%d): %s, waiting %.1fs", attempt + 1, max_retries, result.errors[0], delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 30)
    return {"scholar_id": scholar_id, "errors": [f"discover failed after {max_retries} attempts"]}


async def ensure_user(
    db: AsyncSession,
    scholar_id: str,
    discovery: dict,
    meta: dict,
    dry_run: bool = False,
) -> User | None:
    """Create or update user with discovered data + seed metadata."""
    existing = (await db.execute(
        select(User).where(User.scholar_id == scholar_id)
    )).scalars().first()

    honors = meta.get("honors", []) or []
    direction = meta.get("direction", "")
    tier = meta.get("tier", "")

    if existing:
        # Patch metadata only
        if dry_run:
            logger.info("  [DRY] Would update user %d: honors=%s dir=%s tier=%s", existing.id, honors, direction, tier)
            return existing
        existing.honor_tags = honors or existing.honor_tags
        existing.research_direction = direction or existing.research_direction
        existing.seed_tier = tier or existing.seed_tier
        if meta.get("name") and not existing.name:
            existing.name = meta["name"]
        await db.flush()
        logger.info("  Updated existing user id=%d (%s)", existing.id, existing.name)
        return existing

    if dry_run:
        logger.info("  [DRY] Would create user: name=%s scholar=%s honors=%s", discovery.get("name") or meta.get("name"), scholar_id, honors)
        return None

    user = User(
        name=discovery.get("name") or meta.get("name", ""),
        avatar_url=discovery.get("avatar_url", ""),
        bio=discovery.get("bio", ""),
        scholar_id=scholar_id,
        github_username=discovery.get("github_username", ""),
        hf_username=discovery.get("hf_username", ""),
        honor_tags=honors if honors else None,
        research_direction=direction,
        seed_tier=tier,
        visible=True,
    )
    db.add(user)
    await db.flush()
    logger.info("  ✓ Created user id=%d (%s)", user.id, user.name)
    return user


async def trigger_refresh(user_id: int):
    """Background refresh: pull papers/repos/HF for the newly created user."""
    from app.services import (
        scholar_service, dblp_service, ccf_recompute_service,
        github_service, hf_service, milestone_service,
        snapshot_service, persona_service,
    )
    async with async_session() as db:
        user = await db.get(User, user_id)
        if not user:
            return
        try:
            await scholar_service.fetch_papers_for_user(db, user)
            await dblp_service.fetch_dblp_papers_for_user(db, user)
            await ccf_recompute_service.recompute_ccf_for_user(db, user)
            if user.github_username:
                await github_service.fetch_repos_for_user(db, user)
            if user.hf_username:
                await hf_service.fetch_hf_items_for_user(db, user)
            await milestone_service.check_milestones(db, user)
            await snapshot_service.record_daily_snapshot(db, user)
            await persona_service.compute_persona(db, user)
            await db.commit()
        except Exception as e:
            logger.warning("  Refresh failed for user %d: %s", user_id, e)


async def process_scholar(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    meta: dict,
    use_enriched: bool,
    dry_run: bool,
) -> tuple[str, int | None, str]:
    """Process one scholar. Returns (status, user_id, msg)."""
    async with semaphore:
        name = meta["name"]
        cn = meta.get("cn")
        aff = meta.get("affiliation", "")
        display = f"{name}" + (f" ({cn})" if cn else "")
        logger.info("▶ %s — %s [%s/%s]", display, aff, meta.get("direction", "?"), meta.get("tier", "?"))

        # Merge honors: prefer verified, then accept high-confidence proposed
        merged_honors = list(meta.get("honors") or [])
        if use_enriched:
            prop = meta.get("honors_proposed") or {}
            if prop.get("confidence") == "high":
                for h in prop.get("honors") or []:
                    if h not in merged_honors:
                        merged_honors.append(h)
        meta_final = {**meta, "honors": merged_honors}

        # Find Scholar ID
        scholar_id = await search_scholar(client, name, aff)
        if not scholar_id:
            return ("not_found", None, f"no SS author match for {name}")

        # Discover + create
        discovery = await _discover_from_scholar_direct(scholar_id)
        if discovery.get("errors"):
            return ("discover_error", None, f"{name}: {discovery['errors'][0]}")

        async with async_session() as db:
            try:
                user = await ensure_user(db, scholar_id, discovery, meta_final, dry_run=dry_run)
                await db.commit()
            except Exception as e:
                await db.rollback()
                return ("create_error", None, f"{name}: {e}")

        if dry_run or not user:
            return ("dry", None, f"{name}: would create")

        # Refresh in the foreground (serialised via semaphore outside) so we
        # don't dog-pile the Semantic Scholar API
        await trigger_refresh(user.id)
        return ("ok", user.id, f"created {name} + refreshed (user_id={user.id})")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--enriched", action="store_true", help="Use seed_scholars_enriched.json and merge high-conf proposed honors")
    parser.add_argument("--limit", type=int, default=0, help="Only process first N")
    parser.add_argument("--concurrency", type=int, default=1, help="Keep low (1-2) to avoid SS rate limits")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--direction", type=str, default="", help="Only import scholars of this direction")
    args = parser.parse_args()

    await init_db()

    src = ENRICHED_FILE if args.enriched else SEED_FILE
    if not src.exists():
        logger.error("No seed file at %s", src)
        return
    data = json.loads(src.read_text(encoding="utf-8"))
    scholars = data["scholars"]
    if args.direction:
        scholars = [s for s in scholars if s.get("direction") == args.direction]
    if args.limit > 0:
        scholars = scholars[: args.limit]

    logger.info("Importing %d scholars (concurrency=%d, dry=%s, enriched=%s)", len(scholars), args.concurrency, args.dry_run, args.enriched)

    results: dict[str, int] = {}
    semaphore = asyncio.Semaphore(args.concurrency)
    client_kwargs = {"timeout": 30}
    if OUTBOUND_PROXY:
        client_kwargs["proxy"] = OUTBOUND_PROXY

    async with httpx.AsyncClient(**client_kwargs) as client:
        tasks = [process_scholar(client, semaphore, s, args.enriched, args.dry_run) for s in scholars]
        for coro in asyncio.as_completed(tasks):
            status, uid, msg = await coro
            results[status] = results.get(status, 0) + 1
            level = logger.info if status in ("ok", "dry") else logger.warning
            level("  → [%s] %s", status, msg)

    logger.info("=" * 60)
    for status, n in sorted(results.items(), key=lambda x: -x[1]):
        logger.info("  %s: %d", status, n)
    logger.info("Done. Background refreshes may continue for a few minutes.")


if __name__ == "__main__":
    asyncio.run(main())
