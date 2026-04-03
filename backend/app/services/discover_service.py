"""Auto-discovery service: given a GitHub username, automatically find the
user's Semantic Scholar and Hugging Face accounts."""

import difflib
import logging
import re
from dataclasses import dataclass, field

import httpx

from app.config import SEMANTIC_SCHOLAR_API, GITHUB_API, GITHUB_TOKEN, HUGGINGFACE_API, OUTBOUND_PROXY

logger = logging.getLogger(__name__)

SS_SEARCH_FIELDS = "name,paperCount,citationCount,hIndex,affiliations"

# Stop words excluded when building keyword sets from GitHub repos
_STOP_WORDS = frozenset({
    "the", "a", "an", "of", "for", "and", "or", "in", "on", "to", "with",
    "is", "are", "was", "were", "be", "been", "my", "our", "this", "that",
    "it", "its", "from", "by", "at", "as", "into", "code", "codes", "paper",
    "demo", "simple", "based", "using", "via", "new", "build", "personal",
    "webpage", "website", "page", "repo", "repository", "awesome", "collection",
    "list", "implementation", "official", "pytorch", "tensorflow",
})


@dataclass
class DiscoveryResult:
    github_username: str = ""
    name: str = ""
    avatar_url: str = ""
    bio: str = ""
    company: str = ""
    location: str = ""
    scholar_id: str = ""
    scholar_confidence: str = ""
    hf_username: str = ""
    hf_confidence: str = ""
    github_keywords: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)


async def discover_from_scholar(scholar_id: str) -> DiscoveryResult:
    """Given a Semantic Scholar author ID, fetch profile and try to discover GitHub & HF."""
    result = DiscoveryResult(scholar_id=scholar_id, scholar_confidence="manual")

    async with httpx.AsyncClient(timeout=20, proxy=OUTBOUND_PROXY) as client:
        # Fetch SS author info
        resp = await client.get(
            f"{SEMANTIC_SCHOLAR_API}/author/{scholar_id}",
            params={"fields": "name,paperCount,citationCount,hIndex,affiliations,url,externalIds"},
        )
        if resp.status_code != 200:
            result.errors.append(f"Semantic Scholar 作者 {scholar_id} 不存在")
            return result

        data = resp.json()
        result.name = data.get("name", "")

        # Try to get avatar from DBLP or other sources — skip for now
        # Use first affiliation as bio
        affiliations = data.get("affiliations") or []
        if affiliations:
            result.bio = affiliations[0]

        # Try to find GitHub username
        # Strategy: check externalIds, then search GitHub by name
        ext_ids = data.get("externalIds") or {}
        # SS doesn't provide GitHub directly, so we search
        await _discover_github_from_name(client, result)
        await _discover_hf(client, result)

    return result


async def _discover_github_from_name(client: httpx.AsyncClient, result: DiscoveryResult):
    """Try to find GitHub account by searching with the author's name."""
    name = result.name
    if not name:
        return

    gh_headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        gh_headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    try:
        resp = await client.get(
            f"{GITHUB_API}/search/users",
            params={"q": f"{name} in:name", "per_page": 5},
            headers=gh_headers,
        )
        if resp.status_code != 200:
            return

        items = resp.json().get("items", [])
        name_lower = name.lower().strip()
        name_parts = set(name_lower.split())

        for item in items:
            login = item.get("login", "")
            # Fetch full profile for the name field
            uresp = await client.get(f"{GITHUB_API}/users/{login}", headers=gh_headers)
            if uresp.status_code != 200:
                continue
            udata = uresp.json()
            gh_name = (udata.get("name") or "").lower().strip()
            gh_parts = set(gh_name.split())

            # Require name overlap
            overlap = name_parts & gh_parts
            if len(overlap) >= 2 or (len(name_parts) == 1 and name_parts == gh_parts):
                result.github_username = login
                result.avatar_url = udata.get("avatar_url", "")
                if not result.bio:
                    result.bio = udata.get("bio", "") or ""
                logger.info("Discovered GitHub '%s' for scholar '%s'", login, name)
                return
    except Exception:
        logger.debug("GitHub discovery failed for name '%s'", name)


async def discover_from_github(github_username: str) -> DiscoveryResult:
    """Given a GitHub username, resolve name/avatar then search other platforms."""
    result = DiscoveryResult(github_username=github_username)

    async with httpx.AsyncClient(timeout=20, proxy=OUTBOUND_PROXY) as client:
        gh_headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
        if GITHUB_TOKEN:
            gh_headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

        resp = await client.get(f"{GITHUB_API}/users/{github_username}", headers=gh_headers)
        if resp.status_code != 200:
            result.errors.append(f"GitHub 用户 {github_username} 不存在")
            return result

        gh = resp.json()
        result.name = gh.get("name") or github_username
        result.avatar_url = gh.get("avatar_url", "")
        result.bio = gh.get("bio", "") or ""
        result.company = gh.get("company", "") or ""
        result.location = gh.get("location", "") or ""

        # Fetch GitHub repos to build keyword set for cross-validation
        result.github_keywords = await _fetch_github_keywords(
            client, github_username, gh_headers,
        )

        await _discover_scholar(client, result)
        await _discover_hf(client, result)

    return result


# --------------- GitHub Keyword Extraction ---------------

def _tokenize(text: str) -> set[str]:
    """Split text into lowercase keyword tokens, removing stop words."""
    words = re.findall(r"[a-zA-Z]{3,}", text.lower())
    return {w for w in words if w not in _STOP_WORDS}


async def _fetch_github_keywords(
    client: httpx.AsyncClient, username: str, gh_headers: dict,
) -> set[str]:
    """Fetch user's GitHub repos and extract keywords from names + descriptions."""
    keywords: set[str] = set()
    try:
        resp = await client.get(
            f"{GITHUB_API}/users/{username}/repos",
            params={"sort": "stars", "per_page": 20},
            headers=gh_headers,
        )
        if resp.status_code != 200:
            return keywords
        for repo in resp.json():
            if repo.get("fork"):
                continue
            name = repo.get("name", "")
            desc = repo.get("description", "") or ""
            # Split repo name by separators (-, _, camelCase)
            name_parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
            name_parts = re.sub(r"[-_]", " ", name_parts)
            keywords |= _tokenize(name_parts)
            keywords |= _tokenize(desc)
    except Exception:
        logger.debug("Failed to fetch GitHub repos for %s", username)
    return keywords


def _compute_repo_paper_overlap(repo_keywords: set[str], paper_titles: list[str]) -> int:
    """Count how many repo keywords appear in paper titles. Returns overlap score."""
    if not repo_keywords or not paper_titles:
        return 0
    # Build a set of all words across paper titles
    title_words: set[str] = set()
    for title in paper_titles:
        title_words |= _tokenize(title)
    # Count keyword overlaps (each matching keyword counts once)
    overlap = repo_keywords & title_words
    return len(overlap)


# --------------- Semantic Scholar Discovery ---------------

def _build_search_queries(result: DiscoveryResult) -> list[str]:
    """Generate multiple search queries from GitHub profile info."""
    queries: list[str] = []
    name = (result.name or "").strip()
    username = result.github_username.strip()

    if name and name.lower() != username.lower():
        queries.append(name)

    # If name is a single word, try "name + username" (e.g. "Andrej" + "karpathy")
    if name and " " not in name and name.lower() != username.lower():
        queries.append(f"{name} {username}")

    # Try username alone (many researchers use last name as GitHub username)
    if username and username not in [q.lower() for q in queries]:
        queries.append(username)

    return queries


def _abbrev_match(full: str, candidate: str) -> bool:
    """Check if candidate is an abbreviation of full name.
    e.g. 'A.' matches 'Andrej', 'A. K.' matches 'Andrej Karpathy'."""
    candidate = candidate.rstrip(".")
    if len(candidate) <= 2 and full.lower().startswith(candidate.lower()):
        return True
    return False


def _name_matches(cname_parts: list[str], query_parts: list[str], username: str) -> int:
    """Return a name-match score (0 = no match). Handles abbreviations."""
    cset = [p.rstrip(".").lower() for p in cname_parts]
    qset = [p.rstrip(".").lower() for p in query_parts]
    uname = username.lower()

    exact_matches = 0
    abbrev_matches = 0

    for qp in qset:
        for cp in cset:
            if cp == qp:
                exact_matches += 1
                break
            elif _abbrev_match(qp, cp) or _abbrev_match(cp, qp):
                abbrev_matches += 1
                break

    # Also check if username matches any part of candidate name
    username_in_cname = uname in cset or any(
        cp.startswith(uname) or uname.startswith(cp) for cp in cset if len(cp) > 2
    )

    total_matched = exact_matches + abbrev_matches
    if total_matched == 0 and not username_in_cname:
        return 0

    score = exact_matches * 3 + abbrev_matches * 2
    if username_in_cname:
        score += 3
    return score


def _score_candidate(candidate: dict, result: DiscoveryResult, query: str) -> int:
    """Score a Semantic Scholar candidate based on how well it matches."""
    score = 0
    cname = (candidate.get("name") or "").strip()
    cname_parts = cname.split()
    query_parts = query.strip().split()
    username_lower = result.github_username.lower().strip()

    name_score = _name_matches(cname_parts, query_parts, username_lower)
    if name_score == 0:
        return -1
    score += name_score

    # Citation/paper count is a tiebreaker only — capped to avoid overriding name specificity
    pc = candidate.get("paperCount", 0) or 0
    cc = candidate.get("citationCount", 0) or 0
    if pc > 20:
        score += 2
    elif pc > 5:
        score += 1
    if cc > 1000:
        score += 2
    elif cc > 100:
        score += 1

    affiliations = candidate.get("affiliations") or []
    bio_lower = result.bio.lower() if result.bio else ""
    name_lower = result.name.lower().strip()
    company_lower = result.company.lower() if result.company else ""
    location_lower = result.location.lower() if result.location else ""
    combined_text = f"{bio_lower} {name_lower} {username_lower} {company_lower} {location_lower}"
    for aff in affiliations:
        if not aff:
            continue
        aff_words = [w for w in aff.lower().split() if len(w) > 3]
        if any(w in combined_text for w in aff_words):
            score += 5

    return score


async def _search_scholar_once(
    client: httpx.AsyncClient, query: str, result: DiscoveryResult,
) -> list[tuple[dict, int]]:
    """Run one Semantic Scholar author search and return scored candidates."""
    scored: list[tuple[dict, int]] = []
    try:
        resp = await client.get(
            f"{SEMANTIC_SCHOLAR_API}/author/search",
            params={"query": query, "fields": SS_SEARCH_FIELDS, "limit": 50},
        )
        if resp.status_code != 200:
            return scored

        candidates = resp.json().get("data", [])
        for c in candidates:
            sc = _score_candidate(c, result, query)
            if sc > 0:
                scored.append((c, sc))

    except Exception:
        logger.debug("Scholar search failed for query '%s'", query)
    return scored


async def _fetch_candidate_papers(
    client: httpx.AsyncClient, author_id: str,
) -> list[str]:
    """Fetch top paper titles for a candidate (sorted by citation count)."""
    try:
        resp = await client.get(
            f"{SEMANTIC_SCHOLAR_API}/author/{author_id}/papers",
            params={
                "fields": "title,citationCount",
                "limit": 20,
            },
        )
        if resp.status_code != 200:
            return []
        papers = resp.json().get("data", [])
        return [p.get("title", "") for p in papers if p.get("title")]
    except Exception:
        return []


async def _discover_scholar(client: httpx.AsyncClient, result: DiscoveryResult):
    """Try multiple search strategies to find the Semantic Scholar profile.

    Two-phase approach:
    1. Search SS and score candidates by name/affiliation/metrics.
    2. For top candidates, cross-validate by comparing their paper titles
       with keywords extracted from the user's GitHub repositories.
    """
    queries = _build_search_queries(result)
    if not queries:
        return

    # Phase 1: collect all scored candidates across queries (dedup by authorId)
    seen_ids: set[str] = set()
    all_candidates: list[tuple[dict, int]] = []

    for q in queries:
        scored = await _search_scholar_once(client, q, result)
        for c, sc in scored:
            aid = c.get("authorId", "")
            if aid and aid not in seen_ids:
                seen_ids.add(aid)
                all_candidates.append((c, sc))

    if not all_candidates:
        return

    # Sort by initial score descending
    all_candidates.sort(key=lambda x: x[1], reverse=True)

    # Phase 2: cross-validate top candidates with GitHub repo keywords
    repo_kw = result.github_keywords
    top_n = min(5, len(all_candidates))
    final_best = None
    final_score = -1

    for c, base_score in all_candidates[:top_n]:
        bonus = 0
        if repo_kw:
            titles = await _fetch_candidate_papers(client, c["authorId"])
            overlap = _compute_repo_paper_overlap(repo_kw, titles)
            if overlap >= 5:
                bonus = 10
            elif overlap >= 3:
                bonus = 7
            elif overlap >= 1:
                bonus = 4
            logger.debug(
                "Candidate %s (%s): base=%d, overlap=%d, bonus=%d",
                c["authorId"], c.get("name"), base_score, overlap, bonus,
            )
        total = base_score + bonus
        if total > final_score:
            final_score = total
            final_best = c

    # Also consider remaining candidates (without cross-validation) if they beat top_n
    for c, base_score in all_candidates[top_n:]:
        if base_score > final_score:
            final_score = base_score
            final_best = c

    if final_best and final_score >= 3:
        # Final gate: the winner's name must be reasonably similar to what we searched.
        # This prevents a high-citation "Wu" from beating the actual "Lijun Wu".
        winner_name = (final_best.get("name") or "").strip().lower()
        full_name_lower = result.name.strip().lower()
        username_lower = result.github_username.lower()

        # Compute similarity between candidate name and GitHub full name
        name_sim = difflib.SequenceMatcher(None, winner_name, full_name_lower).ratio()
        # Also check if candidate name words overlap with the GitHub full name
        winner_words = set(re.findall(r"[a-zA-Z]{2,}", winner_name))
        query_words = set(re.findall(r"[a-zA-Z]{2,}", full_name_lower))
        username_words = set(re.findall(r"[a-zA-Z]{2,}", username_lower))
        name_word_overlap = len(winner_words & (query_words | username_words))

        # Require: either decent string similarity (>=0.5) OR at least 2 words overlap
        if name_sim < 0.5 and name_word_overlap < 2:
            logger.info(
                "Rejected Scholar candidate %s ('%s') for '%s': sim=%.2f, word_overlap=%d (too dissimilar)",
                final_best["authorId"], final_best.get("name"), result.name, name_sim, name_word_overlap,
            )
            return
        result.scholar_id = final_best["authorId"]
        result.scholar_confidence = "high" if final_score >= 8 else "medium"
        logger.info(
            "Discovered Scholar ID %s for '%s' (score=%d, name=%s)",
            result.scholar_id, result.name, final_score,
            final_best.get("name"),
        )


# --------------- Hugging Face Discovery ---------------

async def _discover_hf(client: httpx.AsyncClient, result: DiscoveryResult):
    """Try to find Hugging Face account: same username first, then by name."""
    # Try 1: Same username as GitHub
    try:
        resp = await client.get(f"{HUGGINGFACE_API}/users/{result.github_username}/overview")
        if resp.status_code == 200:
            hf_data = resp.json()
            hf_fullname = (hf_data.get("fullname") or "").lower().strip()
            name_lower = result.name.lower().strip()
            if (
                hf_fullname == name_lower
                or name_lower in hf_fullname
                or hf_fullname in name_lower
                or result.github_username.lower() == hf_data.get("user", "").lower()
            ):
                result.hf_username = hf_data.get("user", result.github_username)
                result.hf_confidence = "high"
                logger.info("Discovered HF user '%s' (same username)", result.hf_username)
                return
    except Exception:
        logger.debug("HF same-username check failed")

    # Try 2: Search HF by full name
    name = result.name or ""
    username = result.github_username
    search_queries = [name]
    if " " not in name and name.lower() != username.lower():
        search_queries.append(f"{name} {username}")

    for sq in search_queries:
        try:
            resp = await client.get(
                f"https://huggingface.co/api/users",
                params={"search": sq, "limit": 5},
            )
            if resp.status_code == 200:
                users = resp.json()
                sq_lower = sq.lower().strip()
                for u in users:
                    hf_name = (u.get("fullname") or "").lower().strip()
                    hf_user = (u.get("user") or "").lower()
                    if hf_name == sq_lower or hf_user == username.lower():
                        result.hf_username = u.get("user", "")
                        result.hf_confidence = "medium"
                        logger.info("Discovered HF user '%s' (name search '%s')", result.hf_username, sq)
                        return
        except Exception:
            logger.debug("HF search failed for '%s'", sq)
