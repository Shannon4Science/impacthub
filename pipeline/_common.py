"""Shared helpers for the pipeline modules.

Every pipeline entry point imports this first so:
  1. ``backend/`` is on ``sys.path`` (so ``from app.X import Y`` works)
  2. ``CSAI_KEYWORDS`` / ``ELITE_SCHOOLS`` are defined in exactly one place
  3. ``setup_logging``, ``ss_get``, ``refresh_portfolio`` are reused, not retyped.

Usage::

    from pipeline._common import (
        CSAI_KEYWORDS, ELITE_SCHOOLS, setup_logging,
        ss_get, refresh_portfolio,
    )
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PIPELINE_ROOT.parent
BACKEND_DIR = REPO_ROOT / "backend"

# Idempotent path injection — safe even if pipeline modules import each other.
_backend_str = str(BACKEND_DIR)
if _backend_str not in sys.path:
    sys.path.insert(0, _backend_str)


CSAI_KEYWORDS: tuple[str, ...] = (
    "计算机", "人工智能", "软件", "信息", "AI", "智能", "数据", "网络空间",
)

# Canonical record per elite school: Chinese name → (short_names, english_tokens).
# Use ELITE_NAMES for "is this one of the 7", SCHOOL_EN[cn] for SS-affiliation tokens.
ELITE_SCHOOLS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "清华大学":          (("清华", "THU"),       ("Tsinghua",)),
    "北京大学":          (("北大", "PKU"),       ("Peking", "Beijing")),
    "复旦大学":          (("复旦", "FDU"),       ("Fudan",)),
    "上海交通大学":      (("上交", "SJTU"),      ("Shanghai Jiao Tong", "SJTU")),
    "中国科学技术大学":  (("中科大", "USTC"),    ("Science and Technology of China", "USTC")),
    "浙江大学":          (("浙大", "ZJU"),       ("Zhejiang",)),
    "南京大学":          (("南大", "NJU"),       ("Nanjing",)),
}
ELITE_NAMES: tuple[str, ...] = tuple(ELITE_SCHOOLS.keys())
# alias → canonical (e.g. "SJTU" → "上海交通大学")
SCHOOL_ALIAS: dict[str, str] = {**{cn: cn for cn in ELITE_SCHOOLS}}
for cn, (shorts, _) in ELITE_SCHOOLS.items():
    for s in shorts:
        SCHOOL_ALIAS[s] = cn
SCHOOL_EN: dict[str, tuple[str, ...]] = {cn: en for cn, (_, en) in ELITE_SCHOOLS.items()}


def csai_like_sql(col: str) -> str:
    """Return a SQL ``(col LIKE '%a%' OR col LIKE '%b%' ...)`` snippet for CSAI keywords."""
    return "(" + " OR ".join(f"{col} LIKE '%{k}%'" for k in CSAI_KEYWORDS) + ")"


def setup_logging(log_path: str | Path) -> logging.Logger:
    """Logger that writes both to a file and stdout. Returns the root logger."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(str(log_path), encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger()


# ───────────────────────── HTTP retry helpers ─────────────────────────

import httpx  # noqa: E402  (after sys.path adjustment)


async def ss_get(
    client: httpx.AsyncClient,
    url: str,
    params: dict | None = None,
    max_retries: int = 5,
    timeout: float = 25.0,
) -> httpx.Response | None:
    """GET with exponential backoff on 429/5xx. Used for Semantic Scholar polling."""
    log = logging.getLogger(__name__)
    delay = 2.0
    for attempt in range(max_retries):
        try:
            r = await client.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code in (429,) or r.status_code >= 500:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            return r  # other non-200 — caller decides
        except Exception as exc:  # network glitches
            log.debug("ss_get retry: %s", exc)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
    return None


# ───────────────────────── Per-user stage helper ─────────────────────────

import argparse  # noqa: E402


def add_school_args(parser: argparse.ArgumentParser) -> None:
    """Standard per-user-stage flags: --school / --max / --concurrency."""
    parser.add_argument(
        "--school", default="all",
        help="comma-separated school short names (SJTU/ZJU/...) or full Chinese names; 'all' = elite 7",
    )
    parser.add_argument("--max", type=int, default=0, help="cap users (0 = no cap)")
    parser.add_argument(
        "--concurrency", type=int, default=10,
        help="users processed in parallel (each user's work stays sequential)",
    )


def resolve_schools(arg: str) -> list[str]:
    raw = [s.strip() for s in arg.split(",") if s.strip()]
    if "all" in raw:
        return list(ELITE_NAMES)
    return [SCHOOL_ALIAS.get(s, s) for s in raw]


async def run_per_user_stage(
    label: str,
    school_arg: str,
    fn,
    *,
    concurrency: int = 10,
    max_users: int = 0,
    require_field: str | None = None,
) -> dict[str, int]:
    """Apply ``fn(db, user)`` to every advisor-linked User in the given schools.

    ``require_field`` (optional) — only process Users whose attribute is truthy
    (e.g. ``"github_username"`` for the GitHub-pull stage).
    Returns a {status: count} histogram.  Status values: ok, noop, err:<Type>,
    skipped.
    """
    from sqlalchemy import select  # noqa: E402
    from app.database import async_session, init_db  # noqa: E402
    from app.models import User, Advisor, AdvisorSchool  # noqa: E402

    log = logging.getLogger()
    await init_db()

    schools = resolve_schools(school_arg)
    log.info("[%s] schools=%s concurrency=%d", label, schools, concurrency)

    async with async_session() as db:
        stmt = (select(User.id, User.name, Advisor.name, AdvisorSchool.name)
                .join(Advisor, Advisor.impacthub_user_id == User.id)
                .join(AdvisorSchool, Advisor.school_id == AdvisorSchool.id)
                .where(AdvisorSchool.name.in_(schools))
                .order_by(AdvisorSchool.id, User.id))
        if max_users > 0:
            stmt = stmt.limit(max_users)
        rows = (await db.execute(stmt)).all()

    log.info("[%s] %d candidate users", label, len(rows))

    counts: dict[str, int] = {}
    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def work(idx: int, uid: int, uname: str, aname: str, school: str):
        nonlocal done
        async with sem:
            log.info("[%s] [%d/%d] %s @ %s → User %d", label, idx, len(rows), aname, school, uid)
            try:
                async with async_session() as db:
                    user = await db.get(User, uid)
                    if user is None:
                        status = "user_missing"
                    elif require_field and not getattr(user, require_field, None):
                        status = "skipped"
                    else:
                        ret = await fn(db, user)
                        await db.commit()
                        status = "ok" if ret is not None else "noop"
            except Exception as exc:
                log.warning("[%s] user=%d failed: %s", label, uid, exc)
                status = f"err:{type(exc).__name__}"
            counts[status] = counts.get(status, 0) + 1
            done += 1

    await asyncio.gather(*[work(i, *r) for i, r in enumerate(rows, 1)])
    log.info("[%s] DONE %s", label, counts)
    return counts


# ───────────────────────── Portfolio refresh ─────────────────────────


async def refresh_portfolio(user_id: int) -> bool:
    """Pull papers/DBLP/CCF/GitHub/HF + record snapshots + compute persona.

    Returns True if the refresh completed without an exception. Equivalent to the
    ``trigger_refresh`` step that ``seed_scholars`` runs after creating a user.
    Centralized here so build_profiles / seed_scholars / match_ss_python don't
    each carry their own copy.
    """
    # Late imports keep the module light when the caller only wants logging.
    from app.database import async_session  # noqa: E402
    from app.models import User  # noqa: E402
    from app.services import (  # noqa: E402
        scholar_service, dblp_service, ccf_recompute_service,
        github_service, hf_service, milestone_service,
        snapshot_service, persona_service,
    )
    log = logging.getLogger(__name__)
    async with async_session() as db:
        user = await db.get(User, user_id)
        if not user:
            return False
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
            return True
        except Exception as exc:
            log.warning("refresh_portfolio user=%d failed: %s", user_id, exc)
            return False
