"""Pipeline completeness API — mirrors what `pipeline/{crawl,analyze}/run_all.py --check` prints.

One endpoint:
    GET /api/pipeline/status   →   {crawl: [...], analyze: [...]}

Each entry: {id, label, expected, done, missing_examples}.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

router = APIRouter()


CSAI_KEYWORDS = ("计算机", "人工智能", "软件", "信息", "AI", "智能", "数据", "网络空间")
ELITE_SCHOOLS = (
    "清华大学", "北京大学", "复旦大学", "上海交通大学",
    "中国科学技术大学", "浙江大学", "南京大学",
)
SCHOOL_SHORT = {
    "清华大学": "thu", "北京大学": "pku", "复旦大学": "fdu",
    "上海交通大学": "sjtu", "中国科学技术大学": "ustc",
    "浙江大学": "zju", "南京大学": "nju",
}
SEED_JSON = Path(__file__).resolve().parent.parent.parent.parent / "pipeline" / "data" / "advisor_schools_211.json"
SS_RESULTS_DIR = Path("/tmp")


def _csai_like(col: str) -> str:
    return "(" + " OR ".join(f"{col} LIKE '%{k}%'" for k in CSAI_KEYWORDS) + ")"


def _elite_csv() -> str:
    return ",".join(f"'{n}'" for n in ELITE_SCHOOLS)


class StageStatus(BaseModel):
    id: int
    label: str
    description: str
    expected: int
    done: int
    missing_examples: list[str] = []


class PipelineStatusResponse(BaseModel):
    crawl: list[StageStatus]
    analyze: list[StageStatus]


async def _probe_schools(db: AsyncSession) -> StageStatus:
    seed = json.loads(SEED_JSON.read_text(encoding="utf-8"))
    expected = len(seed["schools"])
    done = (await db.execute(text("SELECT COUNT(*) FROM advisor_schools"))).scalar() or 0
    return StageStatus(
        id=1, label="schools", description="双一流高校名单",
        expected=expected, done=done,
    )


async def _probe_colleges(db: AsyncSession) -> StageStatus:
    csv = _elite_csv()
    expected = (await db.execute(text(
        f"SELECT COUNT(*) FROM advisor_schools WHERE name IN ({csv})"
    ))).scalar() or 0
    done = (await db.execute(text(
        f"SELECT COUNT(*) FROM advisor_schools WHERE name IN ({csv}) "
        f"AND colleges_crawled_at IS NOT NULL"
    ))).scalar() or 0
    missing = [r[0] for r in (await db.execute(text(
        f"SELECT name FROM advisor_schools WHERE name IN ({csv}) "
        f"AND colleges_crawled_at IS NULL LIMIT 5"
    ))).all()]
    return StageStatus(
        id=2, label="colleges", description="每校的学院列表 (LLM 解析)",
        expected=expected, done=done, missing_examples=missing,
    )


async def _probe_stubs(db: AsyncSession) -> StageStatus:
    csai = _csai_like("c.name")
    csv = _elite_csv()
    expected = (await db.execute(text(
        f"SELECT COUNT(c.id) FROM advisor_colleges c "
        f"JOIN advisor_schools s ON s.id=c.school_id "
        f"WHERE s.name IN ({csv}) AND {csai}"
    ))).scalar() or 0
    done = (await db.execute(text(
        f"SELECT COUNT(c.id) FROM advisor_colleges c "
        f"JOIN advisor_schools s ON s.id=c.school_id "
        f"WHERE s.name IN ({csv}) AND {csai} AND c.advisors_crawled_at IS NOT NULL"
    ))).scalar() or 0
    missing = [f"{r[0]} / {r[1]}" for r in (await db.execute(text(
        f"SELECT s.short_name, c.name FROM advisor_colleges c "
        f"JOIN advisor_schools s ON s.id=c.school_id "
        f"WHERE s.name IN ({csv}) AND {csai} AND c.advisors_crawled_at IS NULL LIMIT 5"
    ))).all()]
    return StageStatus(
        id=3, label="advisor_stubs", description="每个 CS/AI 学院的师资 stub (LLM)",
        expected=expected, done=done, missing_examples=missing,
    )


async def _probe_details(db: AsyncSession) -> StageStatus:
    csai = _csai_like("c.name")
    csv = _elite_csv()
    base = (
        f"FROM advisors a JOIN advisor_colleges c ON c.id=a.college_id "
        f"JOIN advisor_schools s ON s.id=a.school_id "
        f"WHERE s.name IN ({csv}) AND {csai} AND a.homepage_url != ''"
    )
    expected = (await db.execute(text(f"SELECT COUNT(*) {base}"))).scalar() or 0
    done = (await db.execute(text(
        f"SELECT COUNT(*) {base} AND a.bio != ''"
    ))).scalar() or 0
    missing = [f"{r[0]} / {r[1]}" for r in (await db.execute(text(
        f"SELECT s.short_name, a.name {base} AND (a.bio IS NULL OR a.bio='') LIMIT 5"
    ))).all()]
    return StageStatus(
        id=4, label="advisor_details", description="每位老师的 bio / research_areas (LLM)",
        expected=expected, done=done, missing_examples=missing,
    )


async def _probe_ss_match(db: AsyncSession) -> StageStatus:
    csai = _csai_like("c.name")
    csv = _elite_csv()
    expected = (await db.execute(text(
        f"SELECT COUNT(*) FROM advisors a JOIN advisor_colleges c ON c.id=a.college_id "
        f"JOIN advisor_schools s ON s.id=a.school_id "
        f"WHERE s.name IN ({csv}) AND {csai}"
    ))).scalar() or 0
    done = 0
    missing: list[str] = []
    for cn, short in SCHOOL_SHORT.items():
        path = SS_RESULTS_DIR / f"ss_results_{short}.json"
        if not path.exists():
            missing.append(f"{cn} (无 agent 输出)")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            done += sum(1 for r in data if r.get("scholar_id"))
        except Exception:
            missing.append(f"{cn} (JSON 解析失败)")
    return StageStatus(
        id=5, label="ss_match",
        description="Sonnet sub-agent 反查 Semantic Scholar authorId",
        expected=expected, done=done, missing_examples=missing[:5],
    )


async def _probe_user_portfolios(db: AsyncSession) -> StageStatus:
    csai = _csai_like("c.name")
    csv = _elite_csv()
    base = (
        f"FROM advisors a JOIN advisor_colleges c ON c.id=a.college_id "
        f"JOIN advisor_schools s ON s.id=a.school_id "
        f"WHERE s.name IN ({csv}) AND {csai}"
    )
    expected = (await db.execute(text(f"SELECT COUNT(*) {base}"))).scalar() or 0
    done = (await db.execute(text(
        f"SELECT COUNT(*) {base} AND a.impacthub_user_id IS NOT NULL AND a.impacthub_user_id != 0"
    ))).scalar() or 0
    missing = [f"{r[0]} / {r[1]}" for r in (await db.execute(text(
        f"SELECT s.short_name, a.name {base} "
        f"AND (a.impacthub_user_id IS NULL OR a.impacthub_user_id = 0) LIMIT 5"
    ))).all()]
    return StageStatus(
        id=6, label="user_portfolios",
        description="User + Papers/DBLP/GitHub/HF/快照",
        expected=expected, done=done, missing_examples=missing,
    )


async def _probe_tab(db: AsyncSession, stage_id: int, label: str, description: str, tab_table: str) -> StageStatus:
    csai = _csai_like("c.name")
    csv = _elite_csv()
    expected = (await db.execute(text(
        f"SELECT COUNT(*) FROM advisors a JOIN advisor_colleges c ON c.id=a.college_id "
        f"JOIN advisor_schools s ON s.id=a.school_id "
        f"WHERE s.name IN ({csv}) AND {csai} "
        f"AND a.impacthub_user_id IS NOT NULL AND a.impacthub_user_id != 0"
    ))).scalar() or 0
    done = (await db.execute(text(
        f"SELECT COUNT(DISTINCT t.user_id) FROM {tab_table} t "
        f"JOIN advisors a ON a.impacthub_user_id=t.user_id "
        f"JOIN advisor_colleges c ON c.id=a.college_id "
        f"JOIN advisor_schools s ON s.id=a.school_id "
        f"WHERE s.name IN ({csv}) AND {csai}"
    ))).scalar() or 0
    return StageStatus(id=stage_id, label=label, description=description,
                       expected=expected, done=done)


@router.get("/pipeline/status", response_model=PipelineStatusResponse)
async def get_status(db: AsyncSession = Depends(get_db)):
    crawl = [
        await _probe_schools(db),
        await _probe_colleges(db),
        await _probe_stubs(db),
        await _probe_details(db),
        await _probe_ss_match(db),
        await _probe_user_portfolios(db),
    ]
    analyze = [
        await _probe_tab(db, 1, "persona",    "12-class MBTI-style 学术人格",            "researcher_personas"),
        await _probe_tab(db, 2, "career",     "教育 + 职位时间线 (LLM + web search)",    "career_histories"),
        await _probe_tab(db, 3, "capability", "多方向 originator/extender/follower",     "capability_profiles"),
        await _probe_tab(db, 4, "buzz",       "网络讨论热度 (Perplexity 搜索)",          "buzz_snapshots"),
        await _probe_tab(db, 5, "trajectory", "研究轨迹分析 (依赖 buzz)",                "research_trajectories"),
        await _probe_tab(db, 6, "ai_summary", "整体 AI 摘要 + 标签 (依赖 buzz + trajectory)", "ai_summaries"),
    ]
    return PipelineStatusResponse(crawl=crawl, analyze=analyze)


# ──────────────────── End-to-end demo (SSE stream) ────────────────────

import asyncio  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

# Add repo root so ``from pipeline._common import ...`` works.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.responses import StreamingResponse  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.models import Advisor, AdvisorSchool, AdvisorCollege, User  # noqa: E402


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _run_demo(advisor_id: int, scholar_id: str | None):
    """Async generator: yields SSE-formatted strings as the pipeline progresses."""
    from app.database import async_session  # noqa: E402

    def step_start(step: int, label: str, description: str):
        return _sse({"type": "step_start", "step": step, "label": label,
                     "description": description, "ts": time.time()})

    def step_progress(step: int, message: str, data: dict | None = None):
        payload = {"type": "step_progress", "step": step, "message": message, "ts": time.time()}
        if data is not None:
            payload["data"] = data
        return _sse(payload)

    def step_done(step: int, data: dict, duration: float):
        return _sse({"type": "step_done", "step": step, "data": data,
                     "duration": duration, "ts": time.time()})

    def step_error(step: int, err: str, data: dict | None = None):
        payload = {"type": "step_error", "step": step, "error": err, "ts": time.time()}
        if data is not None:
            payload["data"] = data
        return _sse(payload)

    # ─── Step 1 — resolve advisor ───
    yield step_start(1, "resolve_advisor", "查询导师在 DB 里的当前状态")
    t0 = time.time()
    async with async_session() as db:
        a = await db.get(Advisor, advisor_id)
        if a is None:
            yield step_error(1, f"未找到 advisor_id={advisor_id} 的导师记录")
            return
        school = await db.get(AdvisorSchool, a.school_id)
        college = await db.get(AdvisorCollege, a.college_id)
    advisor_data = {
        "id": a.id, "name": a.name, "title": a.title,
        "school": school.name if school else "?",
        "college": college.name if college else "?",
        "homepage_url": a.homepage_url,
        "bio": (a.bio or "")[:200],
        "research_areas": a.research_areas or [],
        "already_linked": bool(a.impacthub_user_id),
        "existing_user_id": a.impacthub_user_id or None,
    }
    yield step_done(1, advisor_data, time.time() - t0)

    # ─── Step 2 — SS authorId lookup ───
    yield step_start(2, "ss_lookup", "搜 Semantic Scholar 作者 ID (拼音变体 + 姓名形状过滤)")
    t0 = time.time()
    if scholar_id:
        yield step_progress(2, f"使用用户提供的 scholar_id={scholar_id}，跳过自动搜索")
        yield step_done(2, {"scholar_id": scholar_id, "source": "manual"}, time.time() - t0)
    else:
        from pipeline._common import SCHOOL_EN, ss_get  # noqa: E402
        from pypinyin import lazy_pinyin  # noqa: E402
        import httpx  # noqa: E402
        from app.config import SEMANTIC_SCHOLAR_API, OUTBOUND_PROXY  # noqa: E402

        syl = lazy_pinyin(a.name)
        school_tokens = list(SCHOOL_EN.get(school.name, ()))
        if len(syl) >= 2:
            surname = syl[0].capitalize()
            # SS is case-sensitive: "Zhaohui Wu" works, "ZhaoHui Wu" returns 0.
            given_concat = "".join(syl[1:]).capitalize()           # 'Zhaohui'
            given_hyphen = "-".join(s.capitalize() for s in syl[1:])  # 'Zhao-Hui'
            given_spaced = " ".join(s.capitalize() for s in syl[1:])  # 'Zhao Hui'
        else:
            surname = a.name
            given_concat = given_hyphen = given_spaced = ""
        # Query ladder — pinyin-only first (SS treats query as required substring;
        # adding school name shrinks the candidate set, so use it ONLY as a tail
        # fallback in case the canonical form doesn't match). Affiliation filtering
        # happens post-hoc on the returned candidates.
        queries: list[str] = []
        if given_concat:
            queries.append(f"{given_concat} {surname}")             # "Zhaohui Wu"
            queries.append(f"{given_hyphen} {surname}")             # "Zhao-Hui Wu"
            queries.append(f"{given_spaced} {surname}")             # "Zhao Hui Wu"
            queries.append(f"{surname} {given_concat}")             # "Wu Zhaohui"
        queries.append(a.name)                                       # hanzi fallback
        # School-anchored last (low yield but sometimes catches affiliation-tagged authors)
        if given_concat and school_tokens:
            queries.append(f"{given_concat} {surname} {school_tokens[0]}")
        # Dedup, preserve order
        seen: set[str] = set()
        queries = [q for q in queries if not (q in seen or seen.add(q))]

        aff_tokens = {t.lower() for t in school_tokens}
        SEARCH_LIMIT = 50
        yield step_progress(2,
            f"姓名 → 拼音: {a.name}{given_concat} {surname} · 学校英文锚定词: {school_tokens or '无'}",
            {
                "queries_to_try": queries,
                "affiliation_tokens": sorted(aff_tokens),
                "search_limit_per_query": SEARCH_LIMIT,
            },
        )

        # Stage 2a — collect candidates across all queries (dedup by authorId).
        seen_ids: dict[str, dict] = {}
        kw = {"timeout": 30}
        if OUTBOUND_PROXY:
            kw["proxy"] = OUTBOUND_PROXY
        client = httpx.AsyncClient(**kw)
        try:
            for q in queries:
                yield step_progress(2, f"调 SS author search · 查询={q!r} (取前 {SEARCH_LIMIT} 个)")
                r = await ss_get(client, f"{SEMANTIC_SCHOLAR_API}/author/search",
                                 params={"query": q, "fields": "name,paperCount,citationCount,hIndex,affiliations", "limit": SEARCH_LIMIT})
                if r is None:
                    yield step_progress(2, "  ✗ 请求失败 (网络/超时/重试后仍 5xx)")
                    continue
                if r.status_code != 200:
                    yield step_progress(2, f"  ✗ HTTP {r.status_code} 错误: {(r.text or '')[:160]}")
                    continue
                cand = r.json().get("data") or []
                yield step_progress(2, f"  ↩ {len(cand)} 个候选 (累计去重 {len(seen_ids) + len([c for c in cand if c.get('authorId') not in seen_ids])})", {
                    "candidates": [
                        {"id": c.get("authorId"), "name": c.get("name"),
                         "h": c.get("hIndex"), "cit": c.get("citationCount"),
                         "affs": c.get("affiliations") or []}
                        for c in cand[:10]  # only show first 10 inline; full list in step_done
                    ],
                })
                for c in cand:
                    aid_str = c.get("authorId")
                    if not aid_str:
                        continue
                    rec = seen_ids.setdefault(aid_str, {
                        "id": aid_str, "name": c.get("name"),
                        "h": c.get("hIndex") or 0, "cit": c.get("citationCount") or 0,
                        "paper_count": c.get("paperCount") or 0,
                        "affs": c.get("affiliations") or [],
                        "queries": [],
                    })
                    rec["queries"].append(q)
                await asyncio.sleep(1.5)

            yield step_progress(2,
                f"全部查询完成，去重后共 {len(seen_ids)} 个候选 · 取姓名匹配的前 10 个去调 /author/{{id}} 验证存活并补全所属机构",
            )
            # Stage 2b — name-shape pre-filter, then validate top candidates with /author/{id}.
            # IDs that 404 here get marked dead so we won't pick them.
            def _norm(s: str) -> str:
                return "".join(c for c in s.lower() if c.isalnum())
            tgt_surname = _norm(surname)
            tgt_given_set = {_norm(given_concat), _norm(given_spaced), _norm(given_hyphen)} - {""}

            def _name_shape_ok(rec):
                n = _norm(rec.get("name") or "")
                if a.name in (rec.get("name") or ""):
                    return True
                return (tgt_surname in n) and any(g and g in n for g in tgt_given_set)

            shortlist = sorted(
                (r for r in seen_ids.values() if _name_shape_ok(r)),
                key=lambda r: -(r["h"] or 0),
            )[:10]
            yield step_progress(
                2,
                f"  姓名形状预过滤：{len(seen_ids)}{len(shortlist)} 个候选进入详情验证 (姓 {surname!r}, 名 ∈ {sorted(tgt_given_set)})",
            )

            for rec in shortlist:
                r = await ss_get(client, f"{SEMANTIC_SCHOLAR_API}/author/{rec['id']}",
                                 params={"fields": "name,affiliations,paperCount,citationCount,hIndex"})
                if r and r.status_code == 200:
                    detail = r.json()
                    rec["affs"] = detail.get("affiliations") or rec["affs"]
                    rec["paper_count"] = detail.get("paperCount") or rec["paper_count"]
                    rec["dead"] = False
                    yield step_progress(2,
                        f"  ✓ /author/{rec['id']} ({rec['name']}, h={rec['h']}, 引用={rec['cit']}) → 机构: {rec['affs'] or '空'}",
                    )
                elif r and r.status_code == 404:
                    rec["dead"] = True
                    yield step_progress(2, f"  ✗ /author/{rec['id']} ({rec['name']}) 404: 该 ID 已被合并/删除，丢弃")
                else:
                    rec["dead"] = True
                    code = r.status_code if r else "无响应"
                    yield step_progress(2, f"  ⚠ /author/{rec['id']} HTTP {code} (网络/限流，按死 ID 处理)")
                await asyncio.sleep(1.5)
        finally:
            await client.aclose()

        # Stage 2c — final selection from the validated shortlist.
        # Only candidates we've actually validated against /author/{id} are eligible.
        target_given_variants = tgt_given_set

        attempts = []
        for rec in seen_ids.values():
            name_ok = _name_shape_ok(rec)
            affs_str = " ".join(rec.get("affs") or []).lower()
            overlap = sum(1 for t in aff_tokens if t and t in affs_str)
            rec["name_match"] = name_ok
            rec["aff_overlap"] = overlap
            rec["score"] = (overlap, rec["h"], rec["cit"])
            # validated = we either fetched /author/{id} OR the candidate came
            # back with affiliations from the search itself (rare).
            rec["validated"] = rec.get("dead") is False or bool(rec.get("affs"))
            attempts.append(rec)

        name_matched_alive = [r for r in attempts if r["name_match"] and not r.get("dead")]
        yield step_progress(2,
            f"最终筛选：{len(attempts)} 个候选 → {len(name_matched_alive)} 个 "
            f"(姓名匹配 + /author/{{id}} 验证存活)",
        )

        if not name_matched_alive:
            n_alive = sum(1 for r in attempts if not r.get("dead"))
            n_name = sum(1 for r in attempts if r["name_match"])
            yield step_error(
                2,
                f"没有同时满足「姓名匹配」和「/author/{{id}} 存活」的候选 "
                f"(共 {len(attempts)} 候选 / 姓名匹配 {n_name} / 存活 {n_alive})",
                {
                    "queries_tried": queries,
                    "target_surname": surname,
                    "target_given_variants": sorted(target_given_variants),
                    "affiliation_tokens_required": sorted(aff_tokens),
                    "all_candidates_seen": sorted(attempts, key=lambda r: -(r.get("h") or 0))[:30],
                    "hint": "SS 可能没收录该作者，或所有匹配 ID 都被合并/删除。手动到 semanticscholar.org 搜，把 authorId 填到右上输入框重跑",
                },
            )
            return

        # Pick best among (姓名匹配 + alive): rank by (机构命中, h, 引用)
        best = max(name_matched_alive, key=lambda r: r["score"])
        confidence = "high" if best["aff_overlap"] >= 1 else (
            "medium" if best["h"] >= 10 else "low"
        )
        yield step_progress(2,
            f"  → 选中 id={best['id']} {best['name']} (h={best['h']}, 引用={best['cit']},"
            f" 机构={best['affs'] or '空'}, 置信度={confidence})",
        )

        scholar_id = best["id"]
        yield step_done(2, {
            "scholar_id": scholar_id,
            "source": f"pinyin_search ({confidence}-confidence)",
            "confidence": confidence,
            "name": best.get("name"), "h_index": best.get("h"),
            "citation_count": best.get("cit"),
            "affiliations": best.get("affs") or [],
            "queries_tried": queries,
            "candidates_seen": len(attempts),
            "name_matched_count": len(name_matched_alive),
            "all_candidates_seen": sorted(attempts, key=lambda r: -(r.get("h") or 0))[:30],
        }, time.time() - t0)

    # ─── Step 3 — discover_from_scholar (+ 姓名一致性 assert) ───
    yield step_start(3, "discover", "拉 SS 作者主页 + 自动发现 GitHub / HuggingFace 账号 (含姓名一致性校验)")
    t0 = time.time()
    try:
        from app.services.discover_service import discover_from_scholar  # noqa: E402
        res = await discover_from_scholar(scholar_id)
        if res.errors:
            yield step_error(3, "discover 返回错误: " + "; ".join(res.errors))
            return

        # 硬性校验：SS profile 拿到的 name 必须跟导师姓名拼音匹配，否则中止
        # (否则下游会创建一个完全不相关的 User)
        from pypinyin import lazy_pinyin  # noqa: E402

        def _norm(s: str) -> str:
            return "".join(c for c in (s or "").lower() if c.isalnum())

        ss_name_norm = _norm(res.name or "")
        zh_in_ss = any("\u4e00" <= ch <= "\u9fff" for ch in (res.name or ""))
        if zh_in_ss:
            name_match = a.name in (res.name or "")
        else:
            syl = lazy_pinyin(a.name)
            if len(syl) >= 2:
                tgt_surname = _norm(syl[0])
                tgt_given = _norm("".join(syl[1:]))
                name_match = (tgt_surname in ss_name_norm) and (tgt_given in ss_name_norm)
            else:
                name_match = _norm(a.name) in ss_name_norm

        if not name_match:
            yield step_error(
                3,
                f"姓名一致性校验失败 — SS 返回 {res.name!r}，但导师是 {a.name!r}",
                {
                    "advisor_name": a.name,
                    "ss_name": res.name,
                    "scholar_id_used": scholar_id,
                    "hint": "Step 2 选错了人。回 step 2 看候选列表，复制正确的 author ID 填到右上输入框重跑。",
                },
            )
            return
        yield step_progress(3, f"姓名一致性 ✓ SS={res.name!r} 与导师 {a.name!r} 匹配")

        # 自动发现的 GitHub 账号只靠姓名匹配，很容易误关联同名陌生人。
        # 这里再做一次"学校/单位"校验：拉 GH /users/{login}，看 name/bio/company/location
        # 是否包含导师学校的英文关键词；不命中就丢弃。
        gh_unverified = res.github_username
        if gh_unverified:
            yield step_progress(3, f"GitHub 自动发现命中 {gh_unverified!r}，做二次校验 (拉 /users/{gh_unverified} 比对学校关键词)")
            from app.config import GITHUB_TOKEN, GITHUB_API, OUTBOUND_PROXY  # noqa: E402
            import httpx  # noqa: E402
            from pipeline._common import SCHOOL_EN  # noqa: E402
            kw = {"timeout": 15}
            if OUTBOUND_PROXY:
                kw["proxy"] = OUTBOUND_PROXY
            headers = {"Accept": "application/vnd.github+json"}
            if GITHUB_TOKEN:
                headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
            school_keywords = {t.lower() for t in SCHOOL_EN.get(school.name, ())}
            school_keywords.add(school.name)
            verified = False
            gh_profile = {}
            try:
                async with httpx.AsyncClient(**kw) as gh_client:
                    r = await gh_client.get(f"{GITHUB_API}/users/{gh_unverified}", headers=headers)
                    if r.status_code == 200:
                        gh_profile = r.json()
                        blob = " ".join(str(gh_profile.get(k) or "")
                                         for k in ("name", "bio", "company", "location",
                                                   "blog", "twitter_username", "email")).lower()
                        hit_tokens = [t for t in school_keywords if t and t.lower() in blob]
                        verified = bool(hit_tokens)
                        yield step_progress(3, "GH profile 内容:" + " · ".join(
                            f"{k}={v!r}" for k, v in gh_profile.items()
                            if k in ("name", "company", "location", "bio", "blog") and v
                        ) or "(几乎为空)")
                        if verified:
                            yield step_progress(3, f"GH 学校校验 ✓ 命中关键词 {hit_tokens}")
                        else:
                            yield step_progress(3,
                                f"GH 学校校验 ✗ profile 里没有 {sorted(school_keywords)} 任一关键词 → "
                                "丢弃 github_username (避免关联同名陌生人)",
                            )
            except Exception as e:
                yield step_progress(3, f"GH 校验异常 {type(e).__name__}: {e} → 保守起见丢弃 github_username")
                verified = False
            if not verified:
                # 同时清掉可能从 GH profile 取过来的 avatar/bio，否则会污染 User
                if res.avatar_url and gh_profile.get("avatar_url") == res.avatar_url:
                    res.avatar_url = ""
                if res.bio and res.bio == (gh_profile.get("bio") or ""):
                    res.bio = ""
                res.github_username = ""

        discovery_data = {
            "scholar_id": scholar_id,
            "name": res.name, "avatar_url": res.avatar_url, "bio": res.bio,
            "github_username": res.github_username, "hf_username": res.hf_username,
            "name_match": True,
            "github_auto_candidate": gh_unverified or None,
            "github_kept": bool(res.github_username),
        }
        yield step_done(3, discovery_data, time.time() - t0)
    except Exception as e:
        yield step_error(3, f"{type(e).__name__}: {e}")
        return

    # ─── Step 4 — create User (DOES NOT link to advisor yet) ───
    yield step_start(4, "create_user", "新建 User 记录 (advisor.impacthub_user_id 留到最后一步全跑完才写)")
    t0 = time.time()
    try:
        async with async_session() as db:
            existing = (await db.execute(
                select(User).where(User.scholar_id == scholar_id)
            )).scalars().first()
            reused = bool(existing)
            if existing:
                uid = existing.id
            else:
                user = User(
                    name=res.name or a.name,
                    avatar_url=res.avatar_url or "",
                    bio=res.bio or a.bio or "",
                    scholar_id=scholar_id,
                    github_username=res.github_username or "",
                    hf_username=res.hf_username or "",
                    honor_tags=a.honors,
                    visible=False,
                )
                db.add(user)
                await db.flush()
                uid = user.id
            await db.commit()
        yield step_done(4, {
            "user_id": uid, "reused": reused, "name": res.name or a.name,
            "note": "User 已建，但 advisor 尚未绑定 — 等 portfolio + 6 LLM tab 全跑完再写 impacthub_user_id",
        }, time.time() - t0)
    except Exception as e:
        yield step_error(4, f"{type(e).__name__}: {e}")
        return

    # ─── Step 5 — portfolio pull ───
    yield step_start(5, "portfolio", "拉论文 (SS+DBLP) · CCF 评级 · GitHub 仓库 · HuggingFace · 每日快照 · 学术人格")
    t0 = time.time()
    try:
        from pipeline._common import refresh_portfolio  # noqa: E402
        ok = await refresh_portfolio(uid)
        from app.models import Paper, GithubRepo, HFItem, DataSnapshot  # noqa: E402
        async with async_session() as db:
            papers = (await db.execute(select(Paper).where(Paper.user_id == uid))).scalars().all()
            repos = (await db.execute(select(GithubRepo).where(GithubRepo.user_id == uid))).scalars().all()
            hfs = (await db.execute(select(HFItem).where(HFItem.user_id == uid))).scalars().all()
            snaps = (await db.execute(select(DataSnapshot).where(DataSnapshot.user_id == uid))).scalars().all()
        top = sorted(papers, key=lambda p: -p.citation_count)[:3]
        yield step_done(5, {
            "ok": ok,
            "papers": len(papers), "repos": len(repos),
            "hf_items": len(hfs), "snapshots": len(snaps),
            "top_papers": [
                {"title": p.title[:120], "year": p.year, "venue": p.venue, "citations": p.citation_count}
                for p in top
            ],
        }, time.time() - t0)
    except Exception as e:
        yield step_error(5, f"{type(e).__name__}: {e}")
        return

    # ─── Step 6 — 6 LLM tabs ───
    from app.services import (  # noqa: E402
        persona_service, career_service, capability_service,
        buzz_service, trajectory_service, ai_summary_service,
    )
    tabs = [
        (6, "persona",    "学术人格 (12 类 MBTI 风格)",                persona_service.compute_persona),
        (7, "career",     "教育 + 职位时间线 (LLM + 网络搜索)",         career_service.refresh_career),
        (8, "capability", "多方向能力角色 (开创者 / 拓展者 / 跟随者)",  capability_service.refresh_capability),
        (9, "buzz",       "网络讨论热度 (Perplexity 搜索)",            buzz_service.refresh_buzz),
        (10, "trajectory","研究轨迹分析 (依赖 buzz)",                   trajectory_service.refresh_trajectory),
        (11, "ai_summary","整体 AI 摘要 + 标签 (依赖 buzz + trajectory)", ai_summary_service.refresh_ai_summary),
    ]
    for stage_id, label, desc, fn in tabs:
        yield step_start(stage_id, label, desc)
        t0 = time.time()
        try:
            async with async_session() as db:
                user = await db.get(User, uid)
                ret = await fn(db, user)
                await db.commit()
            data = _tab_full_data(label, ret)
            # Sanity check on LLM-text tabs: detect refusal/disclaimer phrases that
            # mean the model didn't actually use web search.
            refusal_warning = _detect_refusal_text(label, data)
            if refusal_warning:
                data["quality_warning"] = refusal_warning
                yield step_progress(stage_id, f"⚠ {refusal_warning}")
            yield step_done(stage_id, data, time.time() - t0)
        except Exception as e:
            yield step_error(stage_id, f"{type(e).__name__}: {e}")

    # ─── Step 12 — finalize: 写 advisor.impacthub_user_id (此前一直留空) ───
    yield step_start(12, "finalize",
                     "全部 tab 跑完，把 advisor.impacthub_user_id 写回，正式标记为 linked")
    t0 = time.time()
    try:
        async with async_session() as db:
            advisor_row = await db.get(Advisor, advisor_id)
            advisor_row.impacthub_user_id = uid
            advisor_row.semantic_scholar_id = scholar_id
            await db.commit()
        yield step_done(12, {
            "advisor_id": advisor_id,
            "impacthub_user_id": uid,
            "scholar_id": scholar_id,
        }, time.time() - t0)
    except Exception as e:
        yield step_error(12, f"绑定失败 {type(e).__name__}: {e}")
        return

    yield _sse({"type": "done", "user_id": uid,
                "profile_url": f"/profile/{uid}", "ts": time.time()})


_REFUSAL_PATTERNS = (
    "无法联网", "无法访问", "无法实时", "无法浏览", "无法打开链接",
    "i cannot access", "i can't access", "i cannot search", "i can't search",
    "我目前无法", "作为大语言模型", "as an ai language model",
    "重要说明（请先阅读）", "重要提示：", "请先阅读",
)


def _detect_refusal_text(label: str, data: dict) -> str | None:
    """Return a warning string if the tab text looks like an LLM refusal/disclaimer."""
    if label not in ("buzz", "ai_summary", "career"):
        return None
    text_fields = []
    if label == "buzz":
        text_fields = [data.get("summary", ""), " ".join(data.get("topics") or [])]
    elif label == "ai_summary":
        text_fields = [data.get("summary", "")]
    elif label == "career":
        text_fields = [data.get("current", "")]
        for s in data.get("timeline") or []:
            text_fields.append(str(s.get("note") or ""))
    blob = " ".join(text_fields).lower()
    hits = [p for p in _REFUSAL_PATTERNS if p.lower() in blob]
    if hits:
        return f"输出包含 LLM 拒答/免责声明（命中: {hits[:3]}）— 表示模型实际没调 web_search，数据不可信"
    return None


def _tab_full_data(label: str, ret) -> dict:
    """Emit the full service-result payload so the frontend can render rich detail."""
    if ret is None:
        return {"ok": False, "note": "service 返回 None (通常因输入不足跳过)"}
    if label == "persona":
        return {
            "ok": True,
            "persona_code": getattr(ret, "persona_code", ""),
            "dimension_scores": getattr(ret, "dimension_scores", {}) or {},
            "raw_metrics": getattr(ret, "raw_metrics", {}) or {},
        }
    if label == "career":
        return {
            "ok": True,
            "timeline": getattr(ret, "timeline_json", []) or [],
            "current": getattr(ret, "current", "") or "",
            "sources": getattr(ret, "sources", []) or [],
        }
    if label == "capability":
        return {
            "ok": True,
            "primary_role": getattr(ret, "primary_role", "") or "",
            "primary_direction": getattr(ret, "primary_direction", "") or "",
            "rationale": getattr(ret, "rationale", "") or "",
            "profiles": getattr(ret, "profiles_json", []) or [],
        }
    if label == "buzz":
        return {
            "ok": True,
            "heat_label": getattr(ret, "heat_label", "") or "",
            "summary": getattr(ret, "summary", "") or "",
            "topics": getattr(ret, "topics", []) or [],
            "sources": getattr(ret, "sources", []) or [],
        }
    if label == "trajectory":
        return {
            "ok": True,
            "trajectory": getattr(ret, "trajectory_json", {}) or {},
        }
    if label == "ai_summary":
        return {
            "ok": True,
            "summary": getattr(ret, "summary", "") or "",
            "tags": getattr(ret, "tags", []) or [],
        }
    return {"ok": True}


class AdvisorSearchHit(BaseModel):
    id: int
    name: str
    title: str
    school: str
    college: str
    already_linked: bool


@router.get("/pipeline/demo/search", response_model=list[AdvisorSearchHit])
async def demo_search(
    q: str = "",
    unlinked_only: bool = False,
    limit: int = 30,
    db: AsyncSession = Depends(get_db),
):
    """Search CS/AI advisors. Empty q returns top-N unlinked-with-bio (good demo
    candidates) ranked by title seniority + bio length. unlinked_only filters out
    already-linked advisors."""
    csai = _csai_like("c.name")
    where = [f"s.name IN ({_elite_csv()})", csai]
    params: dict = {}
    if q.strip():
        where.append("a.name LIKE :q")
        params["q"] = f"%{q.strip()}%"
    if unlinked_only or not q.strip():
        where.append("(a.impacthub_user_id IS NULL OR a.impacthub_user_id = 0)")
    if not q.strip():
        # default view = good demo candidates: must have bio + homepage
        where.append("a.bio != ''")
        where.append("a.homepage_url != ''")

    # title priority: 院士 → 教授 (full) → 研究员 (full) → 副教授 → others
    order = ("""
        CASE
          WHEN a.title LIKE '%院士%' THEN 0
          WHEN a.title LIKE '%教授%' AND a.title NOT LIKE '%副%' AND a.title NOT LIKE '%助理%' THEN 1
          WHEN a.title LIKE '%研究员%' AND a.title NOT LIKE '%副%' AND a.title NOT LIKE '%助理%' THEN 2
          WHEN a.title LIKE '%副教授%' THEN 3
          ELSE 4 END,
        LENGTH(a.bio) DESC,
        a.id
    """)
    rows = (await db.execute(text(f"""
        SELECT a.id, a.name, a.title, s.name, c.name, a.impacthub_user_id
          FROM advisors a JOIN advisor_colleges c ON c.id=a.college_id
          JOIN advisor_schools s ON s.id=a.school_id
         WHERE {' AND '.join(where)}
         ORDER BY {order}
         LIMIT :limit
    """), {**params, "limit": limit})).all()
    return [
        AdvisorSearchHit(
            id=r[0], name=r[1], title=r[2] or "",
            school=r[3], college=r[4],
            already_linked=bool(r[5]),
        ) for r in rows
    ]


@router.get("/pipeline/demo/stream")
async def demo_stream(advisor_id: int, scholar_id: str | None = None):
    """SSE stream of the end-to-end demo for one advisor."""
    async def gen():
        try:
            async for chunk in _run_demo(advisor_id, scholar_id):
                yield chunk
        except Exception as e:
            yield _sse({"type": "fatal", "error": f"{type(e).__name__}: {e}"})
    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
