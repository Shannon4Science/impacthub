"""One-shot end-to-end demo: run a single advisor through the entire pipeline
and print each stage's outcome.

Usage:
    cd pipeline
    python demo_one.py --advisor-id 83
    python demo_one.py --name 张钹 --school 清华
    python demo_one.py --advisor-id 83 --scholar-id 1810462    # skip SS lookup

Stages run:
    1. Resolve advisor + show current row
    2. SS authorId lookup (Python pinyin search, or skipped if --scholar-id given)
    3. discover_from_scholar  →  fetch name/avatar + auto-discover GitHub/HF
    4. Create User + link advisor.impacthub_user_id
    5. Portfolio pull: papers / DBLP / CCF / GitHub / HF / snapshots / persona
    6. Run 6 LLM tabs: persona → career → capability → buzz → trajectory → ai_summary
    7. Print profile URL  →  /profile/<user_id>
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline._common import (  # noqa: E402
    SCHOOL_ALIAS, SCHOOL_EN, refresh_portfolio, setup_logging, ss_get,
)

import httpx  # noqa: E402
from pypinyin import lazy_pinyin  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.config import SEMANTIC_SCHOLAR_API, OUTBOUND_PROXY  # noqa: E402
from app.database import async_session, init_db  # noqa: E402
from app.models import User, Advisor, AdvisorSchool, AdvisorCollege  # noqa: E402
from app.services.discover_service import discover_from_scholar  # noqa: E402

log = setup_logging("/tmp/pipeline_demo_one.log")


def section(title: str):
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


def kv(label: str, value):
    print(f"  {label:<22} {value}")


def _pinyin_variants(name: str) -> list[str]:
    syl = lazy_pinyin(name)
    if len(syl) < 2:
        return [name]
    surname = syl[0].capitalize()
    given = "".join(s.capitalize() for s in syl[1:])
    return [f"{given} {surname}", f"{surname} {given}", name]


async def step1_resolve_advisor(args) -> Advisor:
    section("Step 1 — Resolve advisor")
    async with async_session() as db:
        if args.advisor_id:
            a = await db.get(Advisor, args.advisor_id)
        else:
            cn_name = SCHOOL_ALIAS.get(args.school, args.school)
            stmt = (select(Advisor).join(AdvisorSchool, Advisor.school_id == AdvisorSchool.id)
                    .where(Advisor.name == args.name, AdvisorSchool.name == cn_name))
            a = (await db.execute(stmt)).scalars().first()
        if not a:
            print(f"  ✗ advisor not found")
            sys.exit(1)
        await db.refresh(a, ["school", "college"])

    kv("advisor.id", a.id)
    kv("name", f"{a.name} ({a.title or '—'})")
    kv("school / college", f"{a.school.name} / {a.college.name}")
    kv("homepage_url", a.homepage_url or "—")
    kv("bio (truncated)", (a.bio or "—").replace("\n", " ")[:100])
    kv("research_areas", a.research_areas or "—")
    kv("already linked?", "YES (User %d)" % a.impacthub_user_id if a.impacthub_user_id else "no")
    return a


async def step2_ss_lookup(advisor: Advisor, override_id: str | None) -> str | None:
    section("Step 2 — Semantic Scholar authorId lookup")
    if override_id:
        kv("scholar_id (manual)", override_id)
        return override_id

    school_en = SCHOOL_EN.get(advisor.school.name, (advisor.school.name,))
    aff_tokens = {t.lower() for t in school_en}

    async def _score(c):
        affs = " ".join(c.get("affiliations") or []).lower()
        overlap = sum(1 for t in aff_tokens if t and t in affs)
        return (overlap, c.get("hIndex") or 0, c.get("citationCount") or 0)

    best = None
    client_kw = {"timeout": 30}
    if OUTBOUND_PROXY:
        client_kw["proxy"] = OUTBOUND_PROXY
    async with httpx.AsyncClient(**client_kw) as client:
        for q in _pinyin_variants(advisor.name):
            kv("query", q)
            r = await ss_get(client, f"{SEMANTIC_SCHOLAR_API}/author/search",
                             params={"query": q, "fields": "name,paperCount,citationCount,hIndex,affiliations", "limit": 10})
            if r is None or r.status_code != 200:
                continue
            cand = r.json().get("data") or []
            if not cand:
                continue
            for c in cand:
                s = await _score(c)
                if s[0] >= 1 and (best is None or s > best[1]):
                    best = (c, s)
            await asyncio.sleep(2)

    if not best:
        print("  ✗ no SS match — supply --scholar-id manually")
        return None
    c, s = best
    kv("→ scholar_id", c["authorId"])
    kv("→ name", c["name"])
    kv("→ affiliations", ", ".join(c.get("affiliations") or []) or "—")
    kv("→ h-index / citations", f"{c.get('hIndex')} / {c.get('citationCount')}")
    return c["authorId"]


async def step3_discover(scholar_id: str) -> dict:
    section("Step 3 — Discover (SS profile + GitHub/HF auto-discovery)")
    res = await discover_from_scholar(scholar_id)
    if res.errors:
        print(f"  ✗ discover errors: {res.errors}")
        sys.exit(1)
    kv("SS name", res.name or "—")
    kv("avatar_url", (res.avatar_url or "—")[:80])
    kv("bio", (res.bio or "—")[:80])
    kv("github_username", res.github_username or "—")
    kv("hf_username", res.hf_username or "—")
    return res


async def step4_create_user(advisor: Advisor, scholar_id: str, discovery) -> int:
    section("Step 4 — Create User + link advisor")
    async with async_session() as db:
        existing = (await db.execute(select(User).where(User.scholar_id == scholar_id))).scalars().first()
        if existing:
            uid = existing.id
            kv("reuse existing", f"User id={uid} ({existing.name})")
        else:
            user = User(
                name=discovery.name or advisor.name,
                avatar_url=discovery.avatar_url or "",
                bio=discovery.bio or advisor.bio or "",
                scholar_id=scholar_id,
                github_username=discovery.github_username or "",
                hf_username=discovery.hf_username or "",
                honor_tags=advisor.honors,
                visible=False,
            )
            db.add(user)
            await db.flush()
            uid = user.id
            kv("✓ created", f"User id={uid} ({user.name})")
        a = await db.get(Advisor, advisor.id)
        a.impacthub_user_id = uid
        a.semantic_scholar_id = scholar_id
        await db.commit()
        kv("advisor.impacthub_user_id", uid)
    return uid


async def step5_portfolio(user_id: int):
    section("Step 5 — Portfolio pull (papers / DBLP / CCF / GitHub / HF / snapshots / persona)")
    t0 = time.time()
    ok = await refresh_portfolio(user_id)
    kv("status", "✓ ok" if ok else "✗ failed")
    kv("elapsed", f"{time.time() - t0:.1f}s")

    from app.models import Paper, GithubRepo, HFItem, DataSnapshot  # noqa: E402
    async with async_session() as db:
        n_papers = (await db.execute(select(Paper).where(Paper.user_id == user_id))).scalars().all()
        n_repos = (await db.execute(select(GithubRepo).where(GithubRepo.user_id == user_id))).scalars().all()
        n_hf = (await db.execute(select(HFItem).where(HFItem.user_id == user_id))).scalars().all()
        n_snap = (await db.execute(select(DataSnapshot).where(DataSnapshot.user_id == user_id))).scalars().all()
    kv("papers", len(n_papers))
    kv("github repos", len(n_repos))
    kv("hf items", len(n_hf))
    kv("snapshots written", len(n_snap))
    if n_papers:
        top = sorted(n_papers, key=lambda p: -p.citation_count)[:3]
        for p in top:
            print(f"    · [{p.citation_count:>4} cite] {p.title[:70]} ({p.venue or '?'}, {p.year})")


async def step6_tabs(user_id: int):
    section("Step 6 — 6 LLM tabs (persona → career → capability → buzz → trajectory → ai_summary)")
    from app.services import (  # noqa: E402
        persona_service, career_service, capability_service,
        buzz_service, trajectory_service, ai_summary_service,
    )
    steps = [
        ("persona",    persona_service.compute_persona),
        ("career",     career_service.refresh_career),
        ("capability", capability_service.refresh_capability),
        ("buzz",       buzz_service.refresh_buzz),
        ("trajectory", trajectory_service.refresh_trajectory),
        ("ai_summary", ai_summary_service.refresh_ai_summary),
    ]
    for name, fn in steps:
        t0 = time.time()
        try:
            async with async_session() as db:
                user = await db.get(User, user_id)
                ret = await fn(db, user)
                await db.commit()
            kv(name, f"✓ ok ({time.time()-t0:.1f}s)" if ret is not None else f"noop ({time.time()-t0:.1f}s)")
        except Exception as exc:
            kv(name, f"✗ {type(exc).__name__}: {exc}")


async def step7_summary(user_id: int):
    section("Step 7 — Final profile")
    from app.models import (  # noqa: E402
        ResearcherPersona, CareerHistory, CapabilityProfile,
        BuzzSnapshot, ResearchTrajectory, AISummary,
    )
    async with async_session() as db:
        for label, Model in [
            ("persona",    ResearcherPersona),
            ("career",     CareerHistory),
            ("capability", CapabilityProfile),
            ("buzz",       BuzzSnapshot),
            ("trajectory", ResearchTrajectory),
            ("ai_summary", AISummary),
        ]:
            row = (await db.execute(select(Model).where(Model.user_id == user_id))).scalars().first()
            kv(label, "✓" if row else "—")
    print()
    print(f"  → 学术档案 URL:  http://localhost:19487/profile/{user_id}")


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--advisor-id", type=int)
    p.add_argument("--name")
    p.add_argument("--school", help="short or full Chinese name (used with --name)")
    p.add_argument("--scholar-id", help="skip SS lookup, use this authorId directly")
    args = p.parse_args()
    if not args.advisor_id and not (args.name and args.school):
        p.error("provide --advisor-id, or --name with --school")

    await init_db()
    advisor = await step1_resolve_advisor(args)
    scholar_id = await step2_ss_lookup(advisor, args.scholar_id)
    if not scholar_id:
        return
    discovery = await step3_discover(scholar_id)
    uid = await step4_create_user(advisor, scholar_id, discovery)
    await step5_portfolio(uid)
    await step6_tabs(uid)
    await step7_summary(uid)


if __name__ == "__main__":
    asyncio.run(main())
