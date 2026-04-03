"""Paper deduplication: normalize titles and merge duplicate entries."""

import re
from typing import Sequence

from app.models import Paper


def _is_arxiv_venue(venue: str) -> bool:
    """True if venue is arXiv (preprint). Prefer formal venue over arXiv."""
    if not venue:
        return False
    return "arxiv" in venue.lower()


def normalize_title(title: str) -> str:
    """Normalize paper title for deduplication.
    Handles case, punctuation, whitespace, trailing period."""
    if not title:
        return ""
    s = title.lower().strip().rstrip(".")
    s = re.sub(r"[\s\-_:]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def deduplicate_papers(papers: Sequence[Paper]) -> list[Paper]:
    """Deduplicate papers by normalized title. Keep the 'best' version for display
    (prefer formal venue over arXiv), and SUM citation_count across all versions."""
    # Group by normalized title: {key: (best_paper, total_citations, all_papers)}
    groups: dict[str, tuple[Paper, int, list[Paper]]] = {}

    for p in papers:
        key = normalize_title(p.title)
        if not key:
            continue
        if key not in groups:
            groups[key] = (p, p.citation_count or 0, [p])
            continue

        best, total, all_papers = groups[key]
        total += p.citation_count or 0
        all_papers.append(p)

        p_arxiv = _is_arxiv_venue(p.venue or "")
        best_arxiv = _is_arxiv_venue(best.venue or "")
        # Prefer formal venue over arXiv for display
        if p_arxiv and not best_arxiv:
            groups[key] = (best, total, all_papers)
        elif not p_arxiv and best_arxiv:
            groups[key] = (p, total, all_papers)
        elif (p.citation_count or 0) > (best.citation_count or 0):
            groups[key] = (p, total, all_papers)
        elif (p.citation_count or 0) == (best.citation_count or 0):
            p_is_ss = not (p.semantic_scholar_id or "").startswith("dblp:")
            best_is_ss = not (best.semantic_scholar_id or "").startswith("dblp:")
            if p_is_ss and not best_is_ss:
                groups[key] = (p, total, all_papers)
            else:
                groups[key] = (best, total, all_papers)
        else:
            groups[key] = (best, total, all_papers)

    result = []
    for best, total, _ in groups.values():
        best.citation_count = total
        result.append(best)
    return result
