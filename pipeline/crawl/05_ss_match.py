"""Stage 5 — reverse-look-up Semantic Scholar authorId for each CS/AI advisor.

This stage cannot run as a pure Python script because the SS public API
rate-limits hard from shared IPs.  Instead it is a **3-part flow**:

  1. ``--prep``  : dump ``/tmp/ss_match_<short>.json`` per school — list of
                   unlinked CS/AI advisors with name + title + college (input
                   for the Sonnet sub-agent).
  2. (manual)    : in an interactive Claude Code session, copy the prompt at
                   ``pipeline/prompts/lookup_ss_id.md`` and spawn one Sonnet
                   sub-agent per school.  Each agent writes
                   ``/tmp/ss_results_<short>.json``.
  3. ``--check`` : verify that every prepped school has a corresponding results
                   file with non-empty scholar_id entries; print coverage.

Stage 6 (``06_user_portfolios.py``) then consumes the results JSON.

Usage:
    cd pipeline
    python crawl/05_ss_match.py --prep --school all       # write input JSONs
    python crawl/05_ss_match.py --check --school all      # report coverage
"""
import argparse
import asyncio
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline._common import (  # noqa: E402
    ELITE_NAMES, SCHOOL_ALIAS, SCHOOL_EN, csai_like_sql, resolve_schools, setup_logging, ss_get,
)

from sqlalchemy import text  # noqa: E402
from app.database import async_session, init_db  # noqa: E402
from app.config import SEMANTIC_SCHOLAR_API, OUTBOUND_PROXY  # noqa: E402
import httpx  # noqa: E402
from pypinyin import lazy_pinyin  # noqa: E402

OUT_DIR = Path("/tmp")
log = setup_logging("/tmp/pipeline_crawl.log")

SS_AUTHOR_FIELDS = (
    "name,affiliations,paperCount,citationCount,hIndex,url,"
    "papers.title,papers.abstract,papers.year,papers.venue"
)
SS_SEARCH_FIELDS = "name,affiliations,paperCount,citationCount,hIndex,url"

TITLE_SUFFIX_RE = re.compile(
    r"(（.*?）|\(.*?\)|博导|硕导|教授|副教授|助理教授|讲师|研究员|副研究员|助理研究员)$"
)

RESEARCH_KEYWORDS = {
    "人工智能": ("artificial intelligence", "ai"),
    "机器学习": ("machine learning",),
    "深度学习": ("deep learning",),
    "计算机视觉": ("computer vision", "vision"),
    "自然语言": ("natural language", "nlp"),
    "语言模型": ("language model", "llm"),
    "大模型": ("large language model", "llm"),
    "数据": ("data", "database", "data mining"),
    "软件": ("software",),
    "网络": ("network", "wireless"),
    "安全": ("security",),
    "图": ("graph",),
    "机器人": ("robot", "robotics"),
    "智能": ("intelligent", "intelligence"),
    "系统": ("system", "systems"),
    "算法": ("algorithm", "algorithms"),
    "脑机": ("brain computer interface", "bci"),
    "脑-机": ("brain computer interface", "bci"),
    "情感计算": ("affective computing", "emotion recognition"),
    "脑电": ("eeg", "electroencephalography"),
    "医学影像": ("medical imaging", "image segmentation"),
    "多模态": ("multimodal",),
    "时空": ("spatiotemporal",),
    "区块链": ("blockchain",),
    "计算系统": ("computer architecture", "systems", "accelerator", "gpu"),
    "芯片": ("chip", "accelerator"),
}

TERM_STOPWORDS = {
    "edu", "https", "http", "www", "html", "htm", "index", "page", "profile",
    "teacher", "faculty", "people", "school", "college", "university",
    "research", "center", "centre", "lab", "laboratory", "group", "team",
    "and", "or", "the", "for", "with", "from", "into", "onto", "based",
    "application", "applications", "study", "studies", "technology",
    "science", "engineering", "department", "institute", "sjtu", "jiao",
    "tong", "jiaotong", "shanghai", "trans",
}

ALLOWED_ENGLISH_TERMS = {
    term
    for terms in RESEARCH_KEYWORDS.values()
    for term in terms
} | {
    "artificial intelligence", "machine learning", "deep learning",
    "computer vision", "natural language processing", "nlp", "llm",
    "large language model", "database", "data mining", "software engineering",
    "cyber security", "network security", "graph neural network", "robotics",
    "brain computer interface", "bci", "eeg", "electroencephalography",
    "affective computing", "emotion recognition", "medical imaging",
    "image segmentation", "multimodal", "spatiotemporal", "blockchain",
    "computer architecture", "accelerator", "gpu", "security",
}

GENERIC_RESEARCH_TERMS = {
    "ai", "data", "intelligent", "intelligence", "system", "systems",
    "algorithm", "algorithms", "network", "networks", "image", "vision",
}


def short_name(cn: str) -> str:
    return next((k for k, v in SCHOOL_ALIAS.items() if v == cn and k != cn), cn).lower()


def _norm_ascii(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _compact_ascii(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _norm_ascii(text))


def _clean_cn_name(name: str) -> str:
    prev = (name or "").strip()
    while True:
        cur = TITLE_SUFFIX_RE.sub("", prev).strip()
        if cur == prev:
            return cur
        prev = cur


def _pinyin_parts(name: str) -> tuple[str, str, list[str]]:
    clean = _clean_cn_name(name)
    syllables = lazy_pinyin(clean)
    if not syllables:
        return "", "", []
    surname = syllables[0]
    given_parts = syllables[1:] or syllables[:1]
    return surname, "".join(given_parts), syllables


def _name_matches(advisor_name: str, ss_name: str) -> bool:
    """Conservative Chinese-name check against SS romanized names.

    For 刘松桦, require both ``liu`` and ``songhua`` in the candidate.  This
    rejects common false positives such as "Li Songhua".
    """
    if not advisor_name or not ss_name:
        return False
    if any("\u4e00" <= ch <= "\u9fff" for ch in ss_name):
        return _clean_cn_name(advisor_name) in ss_name
    surname, given, syllables = _pinyin_parts(advisor_name)
    if not surname or not given:
        return False
    compact = _compact_ascii(ss_name)
    tokens = set(_norm_ascii(ss_name).split())
    if surname not in compact or given not in compact:
        return False
    # For two-character names, token order varies (Jie Tang / Tang Jie).  For
    # safety, do not accept extra full given-name tokens: "Yong-peng Yu" is not
    # a safe match for 俞勇.
    if len(syllables) <= 2:
        extra = {t for t in tokens if t not in {surname, given} and len(t) > 1}
        return surname in tokens and given in tokens and not extra
    # For longer names, compact matching handles Song Hua / Songhua variants.
    return True


def _school_tokens(cn_school: str) -> list[str]:
    tokens = list(SCHOOL_EN.get(cn_school, ()))
    aliases = [k for k, v in SCHOOL_ALIAS.items() if v == cn_school]
    tokens.extend(aliases)
    if cn_school == "上海交通大学":
        tokens.extend(["Shanghai JiaoTong", "Shanghai Jiaotong"])
    if cn_school == "中国科学技术大学":
        tokens.extend(["University of Science and Technology of China"])
    return [_norm_ascii(t) for t in tokens if _norm_ascii(t)]


def _school_matches(cn_school: str, affiliations: list[str]) -> bool:
    hay = " ".join(_norm_ascii(a) for a in affiliations or [])
    if not hay:
        return False
    return any(tok in hay for tok in _school_tokens(cn_school))


def _research_terms(row: dict[str, Any]) -> set[str]:
    raw = " ".join(str(row.get(k) or "") for k in ("college", "title", "bio"))
    areas = row.get("research_areas") or []
    if isinstance(areas, list):
        raw += " " + " ".join(str(x) for x in areas)
    terms: set[str] = set()
    for zh, en_terms in RESEARCH_KEYWORDS.items():
        if zh in raw:
            terms.update(en_terms)
    raw_norm = _norm_ascii(raw)
    for term in ALLOWED_ENGLISH_TERMS:
        if _norm_ascii(term) in raw_norm:
            terms.add(term)
    terms.update(
        w for w in re.findall(r"\b(?:ai|nlp|llm|bci|eeg|cv|gpu)\b", raw.lower())
    )
    return {t for t in terms if len(t) >= 2 and t not in TERM_STOPWORDS}


def _paper_text(author: dict[str, Any]) -> str:
    papers = author.get("papers") or []
    chunks: list[str] = []
    for p in papers[:40]:
        chunks.append(str(p.get("title") or ""))
        chunks.append(str(p.get("abstract") or ""))
        chunks.append(str(p.get("venue") or ""))
    return _norm_ascii(" ".join(chunks))


def _score_candidate(row: dict[str, Any], author: dict[str, Any]) -> tuple[int, list[str]]:
    notes: list[str] = []
    ss_name = author.get("name") or ""
    if not _name_matches(row.get("name") or "", ss_name):
        return 0, [f"name_mismatch:{ss_name}"]

    score = 50
    notes.append(f"name:{ss_name}")

    affiliations = author.get("affiliations") or []
    if _school_matches(row.get("school_cn") or "", affiliations):
        score += 30
        notes.append("school_affiliation")

    h_index = int(author.get("hIndex") or 0)
    paper_count = int(author.get("paperCount") or 0)
    citation_count = int(author.get("citationCount") or 0)
    if h_index >= 5:
        score += 8
    if paper_count >= 10:
        score += 5
    if citation_count >= 100:
        score += 4

    has_school_affiliation = _school_matches(row.get("school_cn") or "", affiliations)
    terms = _research_terms(row)
    papers = _paper_text(author)
    hits = sorted(t for t in terms if _norm_ascii(t) and _norm_ascii(t) in papers)
    strong_hits = [h for h in hits if _norm_ascii(h) not in GENERIC_RESEARCH_TERMS]
    if strong_hits:
        score += min(20, 7 * len(strong_hits))
        notes.append("paper_terms:" + ",".join(strong_hits[:4]))
    elif hits:
        notes.append("generic_paper_terms:" + ",".join(hits[:4]))

    if not affiliations and not strong_hits:
        score -= 20
        notes.append("no_affiliation_or_strong_paper_term")

    # Without an institutional signal, require multiple domain-specific clues.
    # This blocks common-name collisions where the h-index looks plausible but
    # all papers are from a different field.
    if not has_school_affiliation and len(strong_hits) < 2:
        score -= 15
        notes.append("insufficient_domain_evidence")

    return score, notes


def _confidence(score: int) -> str:
    if score >= 85:
        return "high"
    if score >= 72:
        return "medium"
    if score >= 60:
        return "low"
    return "none"


async def _fetch_author(client: httpx.AsyncClient, scholar_id: str) -> dict[str, Any] | None:
    r = await ss_get(
        client,
        f"{SEMANTIC_SCHOLAR_API}/author/{scholar_id}",
        params={"fields": SS_AUTHOR_FIELDS},
        max_retries=4,
        timeout=30,
    )
    if r is None or r.status_code != 200:
        return None
    return r.json()


async def _search_authors(client: httpx.AsyncClient, query: str, limit: int) -> list[dict[str, Any]]:
    r = await ss_get(
        client,
        f"{SEMANTIC_SCHOLAR_API}/author/search",
        params={"query": query, "fields": SS_SEARCH_FIELDS, "limit": limit},
        max_retries=4,
        timeout=30,
    )
    if r is None or r.status_code != 200:
        return []
    return r.json().get("data") or []


def _queries_for(row: dict[str, Any], *, plain_first: bool = False) -> list[str]:
    surname, given, syllables = _pinyin_parts(row.get("name") or "")
    if not surname:
        return []
    given_spaced = " ".join(syllables[1:]) if len(syllables) > 1 else given
    base = [f"{surname} {given}", f"{given} {surname}"]
    if given_spaced and given_spaced != given:
        base.extend([f"{surname} {given_spaced}", f"{given_spaced} {surname}"])
    # School-qualified queries are precise when SS search supports them, but can
    # return zero for newer faculty, so keep plain-name queries too.
    school_terms = SCHOOL_EN.get(row.get("school_cn") or "", ())
    qualified = [f"{q} {school_terms[0]}" for q in base if school_terms]
    seen: set[str] = set()
    out: list[str] = []
    ordered = base + qualified if plain_first else qualified + base
    for q in ordered:
        q = " ".join(q.split())
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out


async def prep(schools: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    csai = csai_like_sql("c.name")
    for cn in schools:
        en = SCHOOL_EN.get(cn, (cn,))[0]
        async with async_session() as db:
            rows = (await db.execute(text(f"""
                SELECT a.id, a.name, a.title, c.name, a.research_areas, a.bio
                  FROM advisors a
                  JOIN advisor_colleges c ON c.id=a.college_id
                  JOIN advisor_schools s  ON s.id=a.school_id
                 WHERE s.name=:school AND {csai}
                   AND (a.impacthub_user_id IS NULL OR a.impacthub_user_id=0)
                 ORDER BY CASE
                   WHEN a.title LIKE '%院士%' THEN 0
                   WHEN a.title LIKE '%教授%' AND a.title NOT LIKE '%副%' AND a.title NOT LIKE '%助理%' THEN 1
                   WHEN a.title LIKE '%研究员%' AND a.title NOT LIKE '%副%' AND a.title NOT LIKE '%助理%' THEN 2
                   WHEN a.title LIKE '%副教授%' THEN 3
                   ELSE 4 END, a.id
            """), {"school": cn})).all()
        records = [
            {
                "advisor_id": r[0], "name": r[1], "title": r[2], "college": r[3],
                "school": en, "school_cn": cn, "research_areas": json.loads(r[4] or "null"),
                "bio": r[5] or "",
            }
            for r in rows
        ]
        out = OUT_DIR / f"ss_match_{short_name(cn)}.json"
        out.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        counts[cn] = len(records)
        log.info("  %s → %s (%d)", cn, out, len(records))
    return counts


async def validate_file(input_path: Path, output_path: Path, *, min_score: int, max_items: int = 0) -> dict[str, int]:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    if max_items:
        data = data[:max_items]
    counts = {"total": len(data), "validated": 0, "rejected": 0, "no_scholar_id": 0}
    validated: list[dict[str, Any]] = []
    kw = {"timeout": 40}
    if OUTBOUND_PROXY:
        kw["proxy"] = OUTBOUND_PROXY
    async with httpx.AsyncClient(**kw) as client:
        for i, row in enumerate(data, 1):
            sid = str(row.get("scholar_id") or "").strip()
            if "/author/" in sid:
                sid = sid.rstrip("/").rsplit("/", 1)[-1]
            if not sid:
                counts["no_scholar_id"] += 1
                continue
            author = await _fetch_author(client, sid)
            if not author:
                counts["rejected"] += 1
                log.info("[%d/%d] %s SS=%s rejected: author_fetch_failed", i, len(data), row.get("name"), sid)
                continue
            score, notes = _score_candidate(row, author)
            if score < min_score:
                counts["rejected"] += 1
                log.info("[%d/%d] %s SS=%s rejected score=%d %s", i, len(data), row.get("name"), sid, score, ";".join(notes))
                continue
            out = dict(row)
            out.update({
                "scholar_id": sid,
                "confidence": _confidence(score),
                "validated": True,
                "validation_score": score,
                "validation_notes": notes,
                "ss_name": author.get("name") or "",
                "ss_affiliations": author.get("affiliations") or [],
                "h_index": author.get("hIndex") or 0,
                "citation_count": author.get("citationCount") or 0,
                "paper_count": author.get("paperCount") or 0,
            })
            counts["validated"] += 1
            validated.append(out)
            log.info("[%d/%d] %s SS=%s validated score=%d", i, len(data), row.get("name"), sid, score)
            await asyncio.sleep(1.0)
    output_path.write_text(json.dumps(validated, ensure_ascii=False, indent=2), encoding="utf-8")
    return counts


async def auto_match_file(
    input_path: Path,
    output_path: Path,
    *,
    min_score: int,
    max_items: int = 0,
    search_limit: int = 5,
    max_queries: int = 0,
    plain_first: bool = False,
    concurrency: int = 1,
) -> dict[str, int]:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    if max_items:
        data = data[:max_items]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path = output_path.with_name(output_path.stem + "_audit.json")
    existing_results: list[dict[str, Any]] = []
    if audit_path.exists():
        try:
            existing_results = json.loads(audit_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing_results = []
    existing_by_id = {
        int(r["advisor_id"]): r
        for r in existing_results
        if str(r.get("advisor_id") or "").isdigit()
    }
    row_order = {
        int(r["advisor_id"]): idx
        for idx, r in enumerate(data)
        if str(r.get("advisor_id") or "").isdigit()
    }
    results_by_id = {
        aid: result
        for aid, result in existing_by_id.items()
        if aid in row_order
    }
    counts = {
        "total": len(data),
        "matched": sum(1 for r in results_by_id.values() if r.get("validated") and r.get("scholar_id")),
        "none": sum(1 for r in results_by_id.values() if not (r.get("validated") and r.get("scholar_id"))),
        "skipped_existing": len(results_by_id),
    }

    def write_progress() -> None:
        results = [
            results_by_id[aid]
            for aid in sorted(results_by_id, key=lambda x: row_order.get(x, 10**9))
        ]
        safe = [r for r in results if r.get("validated") and r.get("scholar_id")]
        output_path.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
        audit_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    kw = {"timeout": 40}
    if OUTBOUND_PROXY:
        kw["proxy"] = OUTBOUND_PROXY

    async def match_one(client: httpx.AsyncClient, i: int, row: dict[str, Any]) -> dict[str, Any]:
        seen: set[str] = set()
        best: tuple[int, dict[str, Any] | None, list[str]] = (0, None, [])
        queries = _queries_for(row, plain_first=plain_first)
        if max_queries:
            queries = queries[:max_queries]
        for q in queries:
            authors = await _search_authors(client, q, search_limit)
            for author in authors:
                aid = str(author.get("authorId") or "")
                if not aid or aid in seen:
                    continue
                seen.add(aid)
                score, notes = _score_candidate(row, author)
                if score > best[0]:
                    best = (score, author, notes)
            if best[0] >= min_score:
                break
            await asyncio.sleep(1.0)

        score, author, notes = best
        out = dict(row)
        if author and score >= min_score:
            out.update({
                "scholar_id": str(author.get("authorId") or ""),
                "confidence": _confidence(score),
                "validated": True,
                "validation_score": score,
                "validation_notes": notes,
                "ss_name": author.get("name") or "",
                "ss_affiliations": author.get("affiliations") or [],
                "h_index": author.get("hIndex") or 0,
                "citation_count": author.get("citationCount") or 0,
                "paper_count": author.get("paperCount") or 0,
            })
            log.info("[%d/%d] %s → SS=%s score=%d", i, len(data), row.get("name"), out["scholar_id"], score)
        else:
            out.update({
                "scholar_id": "",
                "confidence": "none",
                "validated": False,
                "validation_score": score,
                "validation_notes": notes or ["no_safe_candidate"],
            })
            log.info("[%d/%d] %s → no safe match (best=%d)", i, len(data), row.get("name"), score)
        return out

    async with httpx.AsyncClient(**kw) as client:
        queue: asyncio.Queue[tuple[int, dict[str, Any]] | None] = asyncio.Queue()
        for i, row in enumerate(data, 1):
            aid_raw = row.get("advisor_id")
            if str(aid_raw or "").isdigit() and int(aid_raw) in results_by_id:
                continue
            await queue.put((i, row))

        async def worker() -> None:
            while True:
                item = await queue.get()
                if item is None:
                    queue.task_done()
                    return
                i, row = item
                out = await match_one(client, i, row)
                aid_raw = out.get("advisor_id")
                if str(aid_raw or "").isdigit():
                    results_by_id[int(aid_raw)] = out
                if out.get("validated") and out.get("scholar_id"):
                    counts["matched"] += 1
                else:
                    counts["none"] += 1
                write_progress()
                queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(max(1, concurrency))]
        await queue.join()
        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers)
    # Keep only validated matches in the file consumed by stage 6.
    write_progress()
    log.info("audit written: %s", audit_path)
    return counts


async def check(schools: list[str]) -> int:
    """Return how many schools still need agent results (missing/empty files)."""
    csai = csai_like_sql("c.name")
    missing = 0
    log.info(f"{'School':<14} {'unlinked':>9} {'validated':>12} {'in_db_linked':>14}")
    log.info("-" * 56)
    for cn in schools:
        async with async_session() as db:
            n_unlinked = (await db.execute(text(f"""
                SELECT COUNT(*) FROM advisors a
                  JOIN advisor_colleges c ON c.id=a.college_id
                  JOIN advisor_schools s  ON s.id=a.school_id
                 WHERE s.name=:school AND {csai}
                   AND (a.impacthub_user_id IS NULL OR a.impacthub_user_id=0)
            """), {"school": cn})).scalar() or 0
            n_linked = (await db.execute(text(f"""
                SELECT COUNT(*) FROM advisors a
                  JOIN advisor_colleges c ON c.id=a.college_id
                  JOIN advisor_schools s  ON s.id=a.school_id
                 WHERE s.name=:school AND {csai}
                   AND a.impacthub_user_id IS NOT NULL AND a.impacthub_user_id != 0
            """), {"school": cn})).scalar() or 0
        agent_path = OUT_DIR / f"ss_results_validated_{short_name(cn)}.json"
        if not agent_path.exists():
            agent_found = -1
        else:
            data = json.loads(agent_path.read_text(encoding="utf-8"))
            agent_found = sum(1 for r in data if r.get("scholar_id") and r.get("validated") is True)
        if agent_found < 0:
            missing += 1
            agent_cell = "MISSING"
        else:
            agent_cell = str(agent_found)
        log.info(f"{cn:<14} {n_unlinked:>9} {agent_cell:>12} {n_linked:>14}")
    return missing


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--school", default="all", help="comma-separated short names or 'all'")
    parser.add_argument("--prep", action="store_true", help="dump /tmp/ss_match_*.json for the agent")
    parser.add_argument("--check", action="store_true", help="report agent coverage")
    parser.add_argument("--validate-results", action="store_true", help="validate /tmp/ss_results_*.json into /tmp/ss_results_validated_*.json")
    parser.add_argument("--auto-match", action="store_true", help="conservative SS API search; writes /tmp/ss_results_validated_*.json")
    parser.add_argument("--input", help="single input JSON for --validate-results or --auto-match")
    parser.add_argument("--output", help="single output JSON; default is /tmp/ss_results_validated_<short>.json")
    parser.add_argument("--max", type=int, default=0, help="process at most N entries per school/file")
    parser.add_argument("--min-score", type=int, default=82, help="minimum validation score to accept a match")
    parser.add_argument("--search-limit", type=int, default=5, help="SS author-search candidates per query for --auto-match")
    parser.add_argument("--max-queries", type=int, default=0, help="max name-query variants per advisor; 0 means all")
    parser.add_argument("--plain-first", action="store_true", help="try plain romanized names before school-qualified names")
    parser.add_argument("--concurrency", type=int, default=1, help="advisor tasks to keep in flight; SS HTTP calls still use global throttling")
    args = parser.parse_args()

    await init_db()
    schools = resolve_schools(args.school)

    if not any((args.prep, args.check, args.validate_results, args.auto_match)):
        log.info("Nothing to do. Pass --prep, --check, --validate-results, or --auto-match.")
        return

    if args.prep:
        log.info("Dumping SS-match inputs for %d schools…", len(schools))
        await prep(schools)
        log.info("")
        log.info("→ next: spawn one Sonnet sub-agent per school using "
                 "pipeline/prompts/lookup_ss_id.md (each writes /tmp/ss_results_<short>.json)")

    if args.check:
        missing = await check(schools)
        if missing:
            log.warning("Stage 5 incomplete: %d school(s) without agent output yet.", missing)
            sys.exit(2)

    if args.validate_results or args.auto_match:
        jobs: list[tuple[Path, Path]] = []
        if args.input:
            inp = Path(args.input)
            out = Path(args.output) if args.output else inp.with_name(inp.stem.replace("ss_results_", "ss_results_validated_") + ".json")
            jobs.append((inp, out))
        else:
            for cn in schools:
                short = short_name(cn)
                inp = OUT_DIR / (f"ss_match_{short}.json" if args.auto_match else f"ss_results_{short}.json")
                out = OUT_DIR / f"ss_results_validated_{short}.json"
                jobs.append((inp, out))

        for inp, out in jobs:
            if not inp.exists():
                log.warning("skip missing input: %s", inp)
                continue
            if args.auto_match:
                counts = await auto_match_file(
                    inp, out, min_score=args.min_score, max_items=args.max,
                    search_limit=args.search_limit, max_queries=args.max_queries,
                    plain_first=args.plain_first, concurrency=args.concurrency,
                )
            else:
                counts = await validate_file(inp, out, min_score=args.min_score, max_items=args.max)
            log.info("%s → %s %s", inp, out, counts)


if __name__ == "__main__":
    asyncio.run(main())
