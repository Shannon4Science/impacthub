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

    # ─── Step 2 — gpt-5-mini + web_search 查 SS / GS / GitHub / HF，并完成 SS 存活 + 姓名一致性校验 ───
    yield step_start(2, "external_ids",
                     "调 gpt-5-mini + web_search 跨平台找学术账号 (SS / GS / GitHub / HF)，并对 SS ID 做存活 + 姓名一致性 assert")
    t0 = time.time()

    # 容器变量 — 后续 step 3/4 会用
    gs_id = ""
    gh_user = ""
    hf_user = ""
    llm_evidence = ""
    ss_detail: dict = {}

    if scholar_id:
        yield step_progress(2, f"使用用户提供的 scholar_id={scholar_id}，跳过自动搜索")
        yield step_done(2, {"scholar_id": scholar_id, "source": "manual"}, time.time() - t0)
    else:
        import httpx  # noqa: E402
        import re as _re2
        from app.config import LLM_API_BASE, LLM_API_KEY  # noqa: E402

        bio_short = (a.bio or "").replace("\n", " ")[:600]
        areas = ", ".join(a.research_areas or []) or "（无）"
        llm_prompt = f"""你是学术信息检索助手。给定一位中国高校教师的中文档案，请用 web_search 工具到以下 4 个平台逐一找他/她的账号，并通过实际访问对应页面**核对学校/研究方向是否匹配**：

1. Semantic Scholar — 形如 https://www.semanticscholar.org/author/<NAME>/<NUMERIC_ID>，取 URL 末尾的纯数字 ID
2. Google Scholar — 形如 https://scholar.google.com/citations?user=<ID>&hl=en，取 user 参数
3. GitHub — 形如 https://github.com/<USERNAME>，取 username
4. Hugging Face — 形如 https://huggingface.co/<USERNAME>，取 username

### 老师信息
- 中文姓名：{a.name}
- 学校：{school.name}
- 学院：{college.name}
- 个人主页：{a.homepage_url or '（无）'}
- 研究方向：{areas}
- bio（前 600 字）：{bio_short}

### 核对规则（非常重要）
- 同名学者非常多。必须通过候选页面里出现的**学校名 / 研究方向 / 合作者 / 论文题目**与上面的信息匹配才算确认。
- 找不到、或验证不通过 → 对应字段返回 null。
- **禁止**为了凑数返回猜测的 ID。
- **禁止**输出任何免责声明 / 解释模型限制 / "请先阅读" 之类铺垫。

### 输出格式
**只**输出一段 JSON，不要任何其他文字：
{{"semantic_scholar_id":"...","google_scholar_id":"...","github_username":"...","hf_username":"...","evidence":"（一句话说明你是如何核对的）"}}
找不到的字段填 null。"""

        try:
            async with httpx.AsyncClient(timeout=300) as llm_client:
                resp = await llm_client.post(
                    f"{LLM_API_BASE}/responses",
                    headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                    json={
                        "model": "gpt-5-mini",
                        "tools": [{"type": "web_search_preview"}],
                        "input": llm_prompt,
                        # gpt-5-mini 多次 web_search 会把 reasoning 算进 token 预算；
                        # 16000 给足空间不至于 incomplete。
                        "max_output_tokens": 16000,
                    },
                )
            if resp.status_code != 200:
                yield step_error(2, f"LLM HTTP {resp.status_code}: {(resp.text or '')[:200]}")
                return
            data = resp.json()
            text = ""
            n_searches = 0
            for it in data.get("output", []):
                if it.get("type") == "web_search_call":
                    n_searches += 1
                elif it.get("type") == "message":
                    for c in it.get("content", []):
                        if c.get("type") == "output_text":
                            text = c.get("text", "")
            usage = data.get("usage") or {}
            yield step_progress(2,
                f"  LLM 调了 {n_searches} 次 web_search, 返回 {len(text)} 字, "
                f"token: input={usage.get('input_tokens')} output={usage.get('output_tokens')}, "
                f"status={data.get('status')}",
            )

            m = _re2.search(r"\{[\s\S]*\}", text or "")
            if not m:
                yield step_error(2,
                    f"LLM 输出里没有 JSON (status={data.get('status')!r}, "
                    f"output_tokens={usage.get('output_tokens')})",
                    {
                        "raw_text": (text or "")[:1000],
                        "status": data.get("status"),
                        "incomplete_details": data.get("incomplete_details"),
                        "n_web_searches": n_searches,
                        "hint": "通常是 max_output_tokens 不够或者 model 直接返回空 — 加大 budget 或手填 SS authorId 重跑",
                    },
                )
                return
            try:
                parsed = json.loads(m.group(0))
            except Exception as e:
                yield step_error(2, f"JSON 解析失败 {type(e).__name__}: {e}", {"raw_text": (text or "")[:1000]})
                return

            scholar_id = (parsed.get("semantic_scholar_id") or "").strip() or ""
            gs_id = (parsed.get("google_scholar_id") or "").strip() or ""
            gh_user = (parsed.get("github_username") or "").strip() or ""
            hf_user = (parsed.get("hf_username") or "").strip() or ""
            llm_evidence = (parsed.get("evidence") or "").strip()
            # 兼容 LLM 误把整段 URL 塞进 ID 字段
            if "/author/" in scholar_id:
                scholar_id = scholar_id.rstrip("/").rsplit("/", 1)[-1]
            if "user=" in gs_id:
                m2 = _re2.search(r"user=([^&]+)", gs_id)
                if m2: gs_id = m2.group(1)

            yield step_progress(2, f"  LLM 解析: SS={scholar_id!r}, GS={gs_id!r}, GitHub={gh_user!r}, HF={hf_user!r}")
            yield step_progress(2, f"  evidence: {llm_evidence}")

            # SS ID 验证：如果 LLM 给了，调 /author/{id} 确认存活
            ss_detail = {}
            if scholar_id:
                from pipeline._common import ss_get  # noqa: E402
                from app.config import SEMANTIC_SCHOLAR_API, OUTBOUND_PROXY  # noqa: E402
                kw = {"timeout": 30}
                if OUTBOUND_PROXY:
                    kw["proxy"] = OUTBOUND_PROXY
                async with httpx.AsyncClient(**kw) as ss_client:
                    r = await ss_get(ss_client, f"{SEMANTIC_SCHOLAR_API}/author/{scholar_id}",
                                     params={"fields": "name,affiliations,paperCount,citationCount,hIndex"})
                if r is None or r.status_code != 200:
                    yield step_progress(2,
                        f"  ⚠ LLM 返回的 SS ID={scholar_id} 在 /author/{{id}} 验证失败 (HTTP {r.status_code if r else '无响应'}) → 丢弃 SS ID",
                    )
                    scholar_id = ""
                else:
                    ss_detail = r.json()
                    yield step_progress(2,
                        f"  SS /author/{scholar_id} ✓ name={ss_detail.get('name')!r} h={ss_detail.get('hIndex')} 引用={ss_detail.get('citationCount')} 机构={ss_detail.get('affiliations') or '空'}"
                    )
                    # 姓名一致性 assert：SS 返回的 name 必须跟导师姓名对上 (拼音或 hanzi)
                    from pypinyin import lazy_pinyin as _lp  # noqa: E402
                    _ss_name = ss_detail.get("name") or ""
                    _ss_norm = "".join(c for c in _ss_name.lower() if c.isalnum())
                    if any("\u4e00" <= ch <= "\u9fff" for ch in _ss_name):
                        _name_match = a.name in _ss_name
                    else:
                        _syl = _lp(a.name)
                        if len(_syl) >= 2:
                            _norm_s = "".join(c for c in _syl[0].lower() if c.isalnum())
                            _norm_g = "".join(c for c in "".join(_syl[1:]).lower() if c.isalnum())
                            _name_match = (_norm_s in _ss_norm) and (_norm_g in _ss_norm)
                        else:
                            _norm_a = "".join(c for c in a.name.lower() if c.isalnum())
                            _name_match = _norm_a in _ss_norm
                    if not _name_match:
                        yield step_error(2,
                            f"姓名一致性 assert 失败 — SS 返回 {_ss_name!r}，但导师是 {a.name!r}",
                            {"advisor_name": a.name, "ss_name": _ss_name,
                             "scholar_id_returned": scholar_id, "evidence": llm_evidence,
                             "hint": "LLM 给的 SS ID 不对。手填一个正确的 SS authorId 重跑"},
                        )
                        return
                    yield step_progress(2, f"  姓名一致性 ✓ {_ss_name!r} ≈ {a.name!r}")

            # 至少要有一个平台 ID 才能继续 — 否则后续 step 全是无源之水
            if not (scholar_id or gs_id or gh_user or hf_user):
                yield step_error(2,
                    "LLM 一个平台账号都没找到 — 这位老师在 SS / GS / GitHub / HF 都没收录？",
                    {"evidence": llm_evidence, "n_web_searches": n_searches,
                     "hint": "可能 LLM 没搜对方向。手动填一个 SS authorId 重跑，或检查导师 bio 是否足够具体"},
                )
                return

            if not scholar_id:
                yield step_progress(2,
                    "⚠ 没找到 Semantic Scholar 收录 — step 5 不会从 SS 拉论文（DBLP 仍会试），part of LLM tabs 会 skip"
                )

            yield step_done(2, {
                "scholar_id": scholar_id or None,
                "source": "llm_web_search (gpt-5-mini)",
                "confidence": "high" if scholar_id else "medium-no-ss",
                "name": ss_detail.get("name") if scholar_id else None,
                "h_index": ss_detail.get("hIndex") if scholar_id else None,
                "citation_count": ss_detail.get("citationCount") if scholar_id else None,
                "affiliations": ss_detail.get("affiliations") or [],
                "google_scholar_id": gs_id or None,
                "github_username": gh_user or None,
                "hf_username": hf_user or None,
                "llm_evidence": llm_evidence,
                "n_web_searches": n_searches,
            }, time.time() - t0)
        except Exception as e:
            yield step_error(2, f"LLM 调用失败 {type(e).__name__}: {e}")
            return

    # ss_name: 供 step 4 用；step 2 已经做过 SS 名字一致性 assert
    ss_name = (ss_detail.get("name") if scholar_id and ss_detail else a.name)

    # ─── Step 3 — create User (DOES NOT link to advisor yet) ───
    yield step_start(3, "create_user", "新建 User 记录 (advisor.impacthub_user_id 留到最后一步全跑完才写)")
    t0 = time.time()
    try:
        async with async_session() as db:
            # 复用条件：scholar_id 非空且匹配现有 User
            existing = None
            if scholar_id:
                existing = (await db.execute(
                    select(User).where(User.scholar_id == scholar_id)
                )).scalars().first()
            reused = bool(existing)
            if existing:
                uid = existing.id
            else:
                user = User(
                    name=ss_name or a.name,
                    avatar_url="",
                    bio=a.bio or "",
                    scholar_id=scholar_id,
                    github_username=gh_user or "",
                    hf_username=hf_user or "",
                    homepage=a.homepage_url or "",
                    honor_tags=a.honors,
                    visible=False,
                )
                db.add(user)
                await db.flush()
                uid = user.id
            await db.commit()
        yield step_done(3, {
            "user_id": uid, "reused": reused, "name": ss_name or a.name,
            "github_username": gh_user or "",
            "hf_username": hf_user or "",
            "note": "User 已建，但 advisor 尚未绑定 — 等 portfolio + 6 LLM tab 全跑完再写 impacthub_user_id",
        }, time.time() - t0)
    except Exception as e:
        yield step_error(3, f"{type(e).__name__}: {e}")
        return

    # ─── Step 4 — portfolio pull ───
    yield step_start(4, "portfolio", "拉论文 (SS+DBLP) · CCF 评级 · GitHub 仓库 · HuggingFace · 每日快照 · 学术人格")
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
        yield step_done(4, {
            "ok": ok,
            "papers": len(papers), "repos": len(repos),
            "hf_items": len(hfs), "snapshots": len(snaps),
            "top_papers": [
                {"title": p.title[:120], "year": p.year, "venue": p.venue, "citations": p.citation_count}
                for p in top
            ],
        }, time.time() - t0)
    except Exception as e:
        yield step_error(4, f"{type(e).__name__}: {e}")
        return

    # ─── Step 5-8 — LLM tabs，按依赖顺序分 4 组 ───
    #   5  career               履历                          (LLM + web search)
    #   6  buzz                 网络讨论热度                   (LLM + web search)
    #   7  research_analysis    capability + trajectory      (一次 LLM 调用同时产出)
    #   8  portrait             persona + ai_summary          (一次 LLM 调用同时产出)
    from app.services import (  # noqa: E402
        career_service, buzz_service,
    )
    # For combined stages, the sub_calls list is metadata only — execution goes
    # through COMBINED_DISPATCH which issues a single LLM call producing both
    # sub-outputs and persists to both tables.
    COMBINED_DISPATCH = {
        "research_analysis": _run_research_analysis_combined,
        "portrait":          _run_portrait_combined,
    }
    tabs: list[tuple[int, str, str, list[tuple[str, callable | None]]]] = [
        (5, "career", "教育 + 职位时间线 (LLM + 网络搜索)",
            [("career", career_service.refresh_career)]),
        (6, "buzz", "网络讨论热度 (Perplexity 搜索)",
            [("buzz", buzz_service.refresh_buzz)]),
        (7, "research_analysis", "能力角色 + 研究轨迹 (一次 LLM 调用同时产出)",
            [("capability", None), ("trajectory", None)]),
        (8, "portrait", "学术人格 + 整体 AI 摘要 + 标签 (一次 LLM 调用同时产出)",
            [("persona", None), ("ai_summary", None)]),
    ]

    async def _run_one_sub(sub_label, fn):
        sub_t0 = time.time()
        try:
            async with async_session() as db:
                user = await db.get(User, uid)
                ret = await fn(db, user)
                await db.commit()
            data = _tab_full_data(sub_label, ret)
            refusal = _detect_refusal_text(sub_label, data)
            if refusal:
                data["quality_warning"] = refusal
            return {"label": sub_label, "ok": ret is not None,
                    "data": data, "duration": time.time() - sub_t0}
        except Exception as exc:
            return {"label": sub_label, "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "duration": time.time() - sub_t0}

    for stage_id, label, desc, sub_calls in tabs:
        yield step_start(stage_id, label, desc)
        t0 = time.time()
        if label in COMBINED_DISPATCH:
            sub_labels = [s[0] for s in sub_calls]
            yield step_progress(stage_id, f"开始 · 一次 LLM 调用同时产出 {sub_labels}")
            combined_t0 = time.time()
            try:
                combined_result = await COMBINED_DISPATCH[label](uid)
                combined_duration = time.time() - combined_t0
                sub_steps = []
                for sub_label, _ in sub_calls:
                    sub_raw = combined_result.get(sub_label) or {}
                    # Reshape per-sub data to match what frontend StepData expects
                    if sub_label == "trajectory":
                        sub_data = {"ok": True, "trajectory": sub_raw}
                    else:
                        sub_data = {"ok": True, **sub_raw}
                    sub_steps.append({
                        "label": sub_label, "ok": True,
                        "data": sub_data, "duration": combined_duration,
                    })
                    yield step_progress(stage_id, f"  ✓ {sub_label} 写入 DB")
                data = {"sub_steps": sub_steps, "ok": True, "combined": True}
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
                yield step_progress(stage_id, f"  ✗ 合并 LLM 调用失败: {err}")
                data = {
                    "sub_steps": [
                        {"label": sl, "ok": False, "error": err,
                         "duration": time.time() - combined_t0}
                        for sl, _ in sub_calls
                    ],
                    "ok": False, "combined": True,
                }
        else:
            sub_label, fn = sub_calls[0]
            yield step_progress(stage_id, f"开始 · {sub_label}")
            result = await _run_one_sub(sub_label, fn)
            if not result["ok"] and "error" in result:
                yield step_progress(stage_id, f"  ✗ {sub_label} 失败: {result['error']}")
            if result["data"].get("quality_warning"):
                yield step_progress(stage_id, f"  ⚠ {result['data']['quality_warning']}")
            # Flatten the single sub into the step's top-level data
            data = result["data"]
            data["sub_steps"] = [result]
        yield step_done(stage_id, data, time.time() - t0)

    # ─── Step 9 — finalize: 写 advisor.impacthub_user_id (此前一直留空) ───
    yield step_start(9, "finalize",
                     "全部 tab 跑完，把 advisor.impacthub_user_id 写回，正式标记为 linked")
    t0 = time.time()
    try:
        async with async_session() as db:
            advisor_row = await db.get(Advisor, advisor_id)
            advisor_row.impacthub_user_id = uid
            advisor_row.semantic_scholar_id = scholar_id
            await db.commit()
        yield step_done(9, {
            "advisor_id": advisor_id,
            "impacthub_user_id": uid,
            "scholar_id": scholar_id,
        }, time.time() - t0)
    except Exception as e:
        yield step_error(9, f"绑定失败 {type(e).__name__}: {e}")
        return

    yield _sse({"type": "done", "user_id": uid,
                "profile_url": f"/profile/{uid}", "ts": time.time()})


# ──────────────────── Combined-prompt LLM helpers ────────────────────
# Step 7 (capability + trajectory) and step 8 (persona + ai_summary) used to be
# two separate gpt-5 calls run in parallel. The pair is conceptually one
# analysis ("research analysis" / "overall portrait"), so we ask the model for
# both outputs in one prompt — fewer LLM calls, more coherent outputs, and the
# two sub-results stay consistent with each other.


def _build_paper_context(papers, top_n: int = 30) -> str:
    if not papers:
        return "（无论文）"
    top = sorted(papers, key=lambda p: -(p.citation_count or 0))[:top_n]
    lines = []
    for p in top:
        try:
            n_authors = len(p.authors_json) if isinstance(p.authors_json, list) else 1
        except Exception:
            n_authors = 1
        lines.append(f"- [{p.citation_count or 0:>4} cite] {p.title[:140]} ({p.venue or '?'}, {p.year}, {n_authors} 作者)")
    return "\n".join(lines)


async def _run_research_analysis_combined(uid: int) -> dict:
    """One gpt-5 call → capability + trajectory. Persists to both tables."""
    import httpx  # noqa: E402
    from sqlalchemy import select as _sa_select  # noqa: E402
    from app.config import LLM_API_BASE, LLM_API_KEY, LLM_BUZZ_MODEL  # noqa: E402
    from app.models import (  # noqa: E402
        Paper, BuzzSnapshot, CapabilityProfile, ResearchTrajectory, User,
    )
    from app.database import async_session  # noqa: E402
    from datetime import datetime as _dt

    async with async_session() as db:
        user = await db.get(User, uid)
        papers = (await db.execute(_sa_select(Paper).where(Paper.user_id == uid))).scalars().all()
        buzz = (await db.execute(_sa_select(BuzzSnapshot).where(BuzzSnapshot.user_id == uid))).scalars().first()

    buzz_block = ""
    if buzz:
        buzz_block = f"### 网络讨论热度 (来自 step 6 buzz)\n热度：{buzz.heat_label}\n话题：{', '.join(buzz.topics or [])}\n摘要：{(buzz.summary or '')[:600]}"

    prompt = f"""你是学术分析助手。基于下面这位研究者的论文 + 网络讨论，**一次性**输出两份分析：
1. **capability** — 多方向能力角色 (开创者 / 早期跟进者 / 拓展者 / 跟随者)
2. **trajectory** — 研究轨迹 (主线 + 若干分支)

### 研究者
- 姓名：{user.name if user else ''}
- bio：{(user.bio if user else '')[:400]}

### 代表作 (按引用排序，前 30)
{_build_paper_context(papers)}

{buzz_block}

### 输出格式
**只**输出 JSON，不要 markdown、推理、免责声明：
{{
  "capability": {{
    "primary_role": "<originator|early_adopter|extender|follower>",
    "primary_direction": "<中文方向>",
    "rationale": "<≤80 字>",
    "profiles": [
      {{
        "direction_en": "...", "direction_zh": "...",
        "weight": 0.5, "role": "<同上>", "score": 0.8,
        "achievements": "<≤80 字>",
        "representative_works": [
          {{"title": "...", "year": 2020, "citing_count": 100}}
        ]
      }}
    ]
  }},
  "trajectory": {{
    "root": {{"summary": "<研究主线一段总述>", "label": "<≤20 字主线 label>"}},
    "branches": [
      {{"label": "<分支 label>", "summary": "<≤120 字>", "years": "<2015-2020>",
        "key_papers": ["<论文标题>"]}}
    ]
  }}
}}
要求：profiles 给 2-5 个方向；branches 给 2-4 个分支；weight 加起来约等于 1.0。"""

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{LLM_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": LLM_BUZZ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_completion_tokens": 16000,
            },
        )
    if resp.status_code != 200:
        raise RuntimeError(f"LLM HTTP {resp.status_code}: {resp.text[:200]}")
    content = resp.json()["choices"][0]["message"].get("content") or ""
    import re as _re3
    m = _re3.search(r"\{[\s\S]*\}", content)
    if not m:
        raise RuntimeError(f"LLM 输出无 JSON: {content[:400]!r}")
    parsed = json.loads(m.group(0))

    cap_payload = parsed.get("capability") or {}
    traj_payload = parsed.get("trajectory") or {}

    # UPSERT both tables
    async with async_session() as db:
        # capability
        c_existing = (await db.execute(
            _sa_select(CapabilityProfile).where(CapabilityProfile.user_id == uid)
        )).scalars().first()
        if c_existing:
            c_existing.primary_role = cap_payload.get("primary_role") or ""
            c_existing.primary_direction = cap_payload.get("primary_direction") or ""
            c_existing.rationale = (cap_payload.get("rationale") or "")[:300]
            c_existing.profiles_json = cap_payload.get("profiles") or []
            c_existing.refreshed_at = _dt.utcnow()
        else:
            db.add(CapabilityProfile(
                user_id=uid,
                primary_role=cap_payload.get("primary_role") or "",
                primary_direction=cap_payload.get("primary_direction") or "",
                rationale=(cap_payload.get("rationale") or "")[:300],
                profiles_json=cap_payload.get("profiles") or [],
                refreshed_at=_dt.utcnow(),
            ))
        # trajectory
        t_existing = (await db.execute(
            _sa_select(ResearchTrajectory).where(ResearchTrajectory.user_id == uid)
        )).scalars().first()
        if t_existing:
            t_existing.trajectory_json = traj_payload
            t_existing.refreshed_at = _dt.utcnow()
        else:
            db.add(ResearchTrajectory(
                user_id=uid, trajectory_json=traj_payload, refreshed_at=_dt.utcnow(),
            ))
        await db.commit()

    return {"capability": cap_payload, "trajectory": traj_payload}


async def _run_portrait_combined(uid: int) -> dict:
    """One gpt-5 call → persona + ai_summary. Persists to both tables."""
    import httpx  # noqa: E402
    from sqlalchemy import select as _sa_select, func as _sa_func  # noqa: E402
    from app.config import LLM_API_BASE, LLM_API_KEY, LLM_BUZZ_MODEL  # noqa: E402
    from app.models import (  # noqa: E402
        Paper, GithubRepo, HFItem, BuzzSnapshot, ResearchTrajectory,
        ResearcherPersona, AISummary, User,
    )
    from app.database import async_session  # noqa: E402
    from app.services.persona_service import VALID_CODES, PERSONAS  # noqa: E402
    from datetime import datetime as _dt

    async with async_session() as db:
        user = await db.get(User, uid)
        papers = (await db.execute(_sa_select(Paper).where(Paper.user_id == uid))).scalars().all()
        n_repos = (await db.execute(
            _sa_select(_sa_func.count(GithubRepo.id)).where(GithubRepo.user_id == uid)
        )).scalar() or 0
        n_hf = (await db.execute(
            _sa_select(_sa_func.count(HFItem.id)).where(HFItem.user_id == uid)
        )).scalar() or 0
        buzz = (await db.execute(_sa_select(BuzzSnapshot).where(BuzzSnapshot.user_id == uid))).scalars().first()
        traj = (await db.execute(_sa_select(ResearchTrajectory).where(ResearchTrajectory.user_id == uid))).scalars().first()

    total_cit = sum(p.citation_count or 0 for p in papers)
    paper_count = len(papers)
    sorted_cit = sorted([p.citation_count or 0 for p in papers], reverse=True)
    h_index = sum(1 for i, c in enumerate(sorted_cit) if c >= i + 1)

    persona_legend = "\n".join(
        f"- {code}：{p['name_zh']} ({p['name_en']}) — {p['description']}"
        for code, p in PERSONAS.items()
    )
    traj_block = ""
    if traj and traj.trajectory_json:
        root = (traj.trajectory_json or {}).get("root") or {}
        traj_block = f"### 研究轨迹 (来自 step 7)\n主线: {root.get('summary', '')[:300]}"
    buzz_block = ""
    if buzz:
        buzz_block = f"### 网络讨论 (来自 step 6)\n热度: {buzz.heat_label} · 话题: {', '.join(buzz.topics or [])} · 摘要: {(buzz.summary or '')[:300]}"

    prompt = f"""你是学术画像生成助手。基于这位研究者的数据，**一次性**输出两份画像：
1. **persona** — 12 类 MBTI 风格学术人格 (从下方代号里选一个)
2. **ai_summary** — 整体一句话摘要 + 标签

### 研究者
- 姓名：{user.name if user else ''}
- bio：{(user.bio if user else '')[:300]}
- 论文：{paper_count} 篇 · 总引用 {total_cit} · h-index ≈ {h_index}
- GitHub 仓库：{n_repos} · HuggingFace items：{n_hf}

### 12 类 persona 代号
{persona_legend}

{traj_block}

{buzz_block}

### 输出格式
**只**输出 JSON：
{{
  "persona": {{
    "persona_code": "<上面 12 个代号之一>",
    "reason": "<选择理由 ≤ 200 字>",
    "dimension_scores": {{
      "output_depth": 0.7,
      "ecosystem": 0.3,
      "seniority": 0.9,
      "collaboration": 0.8
    }}
  }},
  "ai_summary": {{
    "summary": "<整体摘要 ≤ 200 字>",
    "tags": ["<≤ 8 字标签>", "..."]
  }}
}}
tags 给 3-6 个；dimension_scores 4 个键都填 0-1 之间。"""

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{LLM_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": LLM_BUZZ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_completion_tokens": 8000,
            },
        )
    if resp.status_code != 200:
        raise RuntimeError(f"LLM HTTP {resp.status_code}: {resp.text[:200]}")
    content = resp.json()["choices"][0]["message"].get("content") or ""
    import re as _re3
    m = _re3.search(r"\{[\s\S]*\}", content)
    if not m:
        raise RuntimeError(f"LLM 输出无 JSON: {content[:400]!r}")
    parsed = json.loads(m.group(0))

    persona_payload = parsed.get("persona") or {}
    summary_payload = parsed.get("ai_summary") or {}
    code = (persona_payload.get("persona_code") or "").strip().upper()
    if code not in VALID_CODES:
        code = "MONK"
    scores = persona_payload.get("dimension_scores") or {}
    safe_scores = {
        k: max(0.0, min(1.0, float(scores.get(k, 0.5))))
        for k in ("output_depth", "ecosystem", "seniority", "collaboration")
    }

    async with async_session() as db:
        p_existing = (await db.execute(
            _sa_select(ResearcherPersona).where(ResearcherPersona.user_id == uid)
        )).scalars().first()
        if p_existing:
            p_existing.persona_code = code
            p_existing.dimension_scores = safe_scores
            p_existing.raw_metrics = {"llm_reason": (persona_payload.get("reason") or "")[:300]}
            p_existing.refreshed_at = _dt.utcnow()
        else:
            db.add(ResearcherPersona(
                user_id=uid, persona_code=code,
                dimension_scores=safe_scores,
                raw_metrics={"llm_reason": (persona_payload.get("reason") or "")[:300]},
                refreshed_at=_dt.utcnow(),
            ))
        s_existing = (await db.execute(
            _sa_select(AISummary).where(AISummary.user_id == uid)
        )).scalars().first()
        if s_existing:
            s_existing.summary = (summary_payload.get("summary") or "")[:600]
            s_existing.tags = summary_payload.get("tags") or []
            s_existing.refreshed_at = _dt.utcnow()
        else:
            db.add(AISummary(
                user_id=uid,
                summary=(summary_payload.get("summary") or "")[:600],
                tags=summary_payload.get("tags") or [],
                refreshed_at=_dt.utcnow(),
            ))
        await db.commit()

    return {
        "persona": {
            "persona_code": code, "dimension_scores": safe_scores,
            "raw_metrics": {"llm_reason": (persona_payload.get("reason") or "")[:300]},
        },
        "ai_summary": {
            "summary": (summary_payload.get("summary") or "")[:600],
            "tags": summary_payload.get("tags") or [],
        },
    }


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
