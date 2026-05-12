# pipeline/ — data ingestion & analysis

Two layers, two orchestrators, one shared DB (`backend/data/impacthub.db`).
The frontend (`../frontend/`) only reads. The backend (`../backend/`) serves
the read API and owns the ORM models; this directory only produces data.

Every numbered file under `crawl/` or `analyze/` corresponds to **one
information type**. Run any single one as `python <layer>/<NN_name>.py`, or run
the layer end-to-end via `<layer>/run_all.py` which resumes from wherever
the DB currently sits.

```
pipeline/
├── _common.py                   shared: CSAI_KEYWORDS, ELITE_SCHOOLS, setup_logging,
│                                ss_get, refresh_portfolio, run_per_user_stage,
│                                sys.path bootstrap
├── crawl/                       ┌──── 信息爬取层 ────┐  raw external data → DB
│   ├── run_all.py               │   orchestrator + completeness check
│   ├── 01_schools.py            │   import 双一流 high schools (seed JSON)
│   ├── 02_colleges.py           │   school homepage → college list (LLM)
│   ├── 03_advisor_stubs.py      │   college 师资 page → advisor stubs (LLM)
│   ├── 04_advisor_details.py    │   advisor homepage → bio / research_areas (LLM)
│   ├── 05_ss_match.py           │   Sonnet sub-agent → SS authorId JSON
│   ├── 06_user_portfolios.py    │   SS JSON → User + papers / GitHub / HF / snapshots
│   ├── seed_scholars.py         │   (parallel path) bulk-import seed leaderboard users
│   ├── mentions.py              │   (parallel path) bulk-import advisor 公众号 mentions
│   └── README.md                │   detailed per-script LLM/agent map
│                                └──────────────────────┘
├── analyze/                     ┌──── 整合分析层 ────┐  LLM-derived per-User tabs
│   ├── run_all.py               │   orchestrator + completeness check
│   ├── 01_persona.py            │   12-class MBTI-style code        (independent)
│   ├── 02_career.py             │   education + position timeline    (independent)
│   ├── 03_capability.py         │   multi-direction role profile     (independent)
│   ├── 04_buzz.py               │   web/social mention heat          (independent)
│   ├── 05_trajectory.py         │   research trajectory analysis     (needs buzz)
│   ├── 06_ai_summary.py         │   overall summary + tags           (needs buzz + trajectory)
│   └── enrich_honors.py         │   (parallel path) honor tags for seed scholars
│                                └──────────────────────┘
├── prompts/                     Sonnet sub-agent prompt templates (copy-paste starters)
├── data/                        seed JSON inputs (advisor_schools_211.json)
└── ops/advance.sh               watchdog — cron relaunches dead jobs every 10 min
```

---

## Quick start

```bash
cd pipeline

# Where am I right now?
python crawl/run_all.py   --check
python analyze/run_all.py --check

# Top-up the crawl layer (idempotent; complete stages auto-skip)
python crawl/run_all.py

# Stage 5 is agent-driven — dump the input JSONs:
python crawl/05_ss_match.py --prep --school all
#   then in an interactive Claude Code session, spawn one Sonnet sub-agent per
#   school using prompts/lookup_ss_id.md.  Each writes /tmp/ss_results_<short>.json.
python crawl/05_ss_match.py --check --school all   # verify coverage

# After the agent step, run stage 6 + the analyze layer
python crawl/run_all.py --only 6
python analyze/run_all.py --schools all --concurrency 10
```

---

## Layer 1 — 信息爬取 (crawl), 6 stages

| # | Stage | Script | Reads | Writes | LLM / Agent |
|---|-------|--------|-------|--------|-------------|
| 1 | schools          | `crawl/01_schools.py` | `data/advisor_schools_211.json` | `advisor_schools` | — |
| 2 | colleges         | `crawl/02_colleges.py` | school homepages | `advisor_colleges` | LLM (`advisor_crawler_service`) |
| 3 | advisor stubs    | `crawl/03_advisor_stubs.py [--school-id N]` | college 师资 pages | `advisors` (`crawl_status=stub`) | LLM (same) |
| 4 | advisor details  | `crawl/04_advisor_details.py [--school <X>] [--tier 985]` | each advisor's `homepage_url` | `advisors.bio` / `.research_areas` / `.email` / `.photo_url` | LLM (same) |
| 5 | SS match         | `crawl/05_ss_match.py --prep \| --check` | `advisors` (unlinked) | `/tmp/ss_results_<short>.json` | **Sonnet sub-agent** (`prompts/lookup_ss_id.md`) |
| 6 | user portfolios  | `crawl/06_user_portfolios.py --input /tmp/ss_results_<X>.json` | the stage-5 JSON | `users`, `papers`, `github_repos`, `hf_items`, `data_snapshots`, `researcher_personas`; sets `advisors.impacthub_user_id` | — (just API pulls) |

See `crawl/README.md` for LLM call-site details and the Sonnet agent escape hatches.

---

## Layer 2 — 整合分析 (analyze), 6 stages

Each stage refreshes one tab of the per-User academic profile.

| # | Stage | Script | Service called | Inputs | Depends on |
|---|-------|--------|----------------|--------|-----------|
| 1 | persona    | `analyze/01_persona.py` | `persona_service.compute_persona` | papers / repos / HF | — |
| 2 | career     | `analyze/02_career.py` | `career_service.refresh_career` | name + bio + LLM web search | — |
| 3 | capability | `analyze/03_capability.py` | `capability_service.refresh_capability` | papers + NotableCitation + CitationAnalysis | — |
| 4 | buzz       | `analyze/04_buzz.py` | `buzz_service.refresh_buzz` | name → Perplexity-style web search | — |
| 5 | trajectory | `analyze/05_trajectory.py` | `trajectory_service.refresh_trajectory` | papers + BuzzSnapshot + (any prior) AISummary | **buzz** |
| 6 | ai_summary | `analyze/06_ai_summary.py` | `ai_summary_service.refresh_ai_summary` | papers + repos + HF + BuzzSnapshot + ResearchTrajectory + notable citations | **buzz + trajectory** |

```
persona / career / capability / buzz   ← independent leaves
                                  ↓
                          trajectory   ← uses buzz
                                  ↓
                         ai_summary   ← uses buzz + trajectory
```

`analyze/run_all.py` walks them in this order. Per-stage `--concurrency 10`
parallelizes across Users (each user's tabs stay sequential).

---

## Resume + validation

Both `run_all.py` orchestrators are **idempotent**:

1. Each stage has an SQL probe defining `(expected, done)`.
2. Before running, log `BEFORE done/expected (pct%)`.
3. If `done == expected`, skip with "✓ already complete".
4. Otherwise invoke the stage script, re-probe.
5. Final state table summarizes every stage.
6. `--strict` exits non-zero on any residual gap (cron-friendly).

`--check` runs the probes and prints the table without crawling.

---

## SS matching strategy

Semantic Scholar's public API rate-limits hard from shared IPs.  We use Sonnet
sub-agents (WebSearch + WebFetch) — higher hit rate (SJTU 90%, average ~25%)
and bypasses the limit. Template is `prompts/lookup_ss_id.md`.

Key prompt hygiene: tell the agent to **strip 博导/教授 suffixes before
computing pinyin**, otherwise it searches "茅兵博导" literally and misses.

---

## Ops — watchdog + cron

`ops/advance.sh` is an idempotent watchdog. Each tick:
1. One sqlite3 query returns remaining work for all jobs.
2. Any job whose process is dead AND has remaining > 0 → relaunch from the
   correct cwd.
3. Logs decisions to `/tmp/advance_watchdog.log`.

Install:
```bash
chmod +x pipeline/ops/advance.sh
(crontab -l 2>/dev/null | grep -v advance.sh; \
 echo "*/10 * * * * /mnt/dhwfile/raise/user/linhonglin/impacthub/pipeline/ops/advance.sh >/dev/null 2>&1") \
  | crontab -
```

Currently watched: Fudan/USTC stage-4 detail crawl + SJTU/ZJU `analyze/run_all`.
Extend `start_detail` / `start_enrich` + `read_remaining` SQL to add jobs.

---

## Conventions

- Every script imports `pipeline._common` first.  That import (a) inserts
  `../backend` onto `sys.path`, (b) exposes `CSAI_KEYWORDS`, `ELITE_NAMES`,
  `SCHOOL_ALIAS`, `setup_logging`, `ss_get`, `refresh_portfolio`,
  `run_per_user_stage`, `add_school_args`, `resolve_schools`.
- All DB writes are async via `app.database.async_session()`.
- LLM calls use `app.config.LLM_API_BASE` / `LLM_API_KEY` (OpenAI-compatible).
- Outbound HTTP honors `app.config.OUTBOUND_PROXY` if set.
- Sonnet sub-agents are spawned interactively in Claude Code via the `Agent`
  tool — there's no headless runner. Prompts under `prompts/` are copy-paste
  starters.

---

## CS/AI scope filter

`pipeline/_common.py::CSAI_KEYWORDS` (`计算机 / 人工智能 / 软件 / 信息 / AI /
智能 / 数据 / 网络空间`) is the single source of truth. The frontend
(`../frontend/src/pages/AdvisorPage.tsx`) restricts the visible directory to
**清北华五** (7 schools) and these college keywords. Pipeline writes everything;
the frontend does the filtering.
