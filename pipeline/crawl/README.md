# pipeline/crawl/ — 信息爬取层

6 个顺序 stage + 2 条并行旁路（`seed_scholars.py`、`mentions.py`）。每个 stage 都是**幂等**的（按 DB 标志位跳过已完成的行），所以 `run_all.py` 可以反复 resume —— 没干完的接着干，全干完的直接 skip 进下一阶段。

```bash
python crawl/run_all.py            # 自动 resume 所有 stage
python crawl/run_all.py --check    # 只看完整性表，不爬
python crawl/run_all.py --only 4   # 只重跑某阶段
python crawl/run_all.py --strict   # 仍有 gap 时退出码 != 0（cron 报错）
```

`run_all.py` 每个 stage 前后都查 DB 完整性；**未跑满会列出前 5 条缺失样本并继续运行**；最终汇总表 + `--strict` 决定退出码。

---

## Stage 总览

| # | 脚本 | 输入 | 写入 | **LLM** | **Agent** |
|---|------|------|------|--------|----------|
| 1 | `01_schools.py` | `data/advisor_schools_211.json` | `advisor_schools` | — | — |
| 2 | `02_colleges.py` | 每所学校 homepage | `advisor_colleges` | ✅ `advisor_crawler_service` 抽学院列表 | 旁路 |
| 3 | `03_advisor_stubs.py [--school-id N] [--max N]` | 每个学院 师资 页 | `advisors`(stub) | ✅ 同上 service 抽教师列表 (heuristic + LLM 兜底) | 旁路 |
| 4 | `04_advisor_details.py [--school <X>] [--tier 985/211]` | 每位 advisor 的 `homepage_url` | `advisors.bio` / `.research_areas` / `.email` / `.photo_url` | ✅ 同上 service 解析单个老师页 | 旁路 |
| 5 | `05_ss_match.py --prep \| --check` | unlinked CS/AI advisors → `/tmp/ss_match_<short>.json` | `/tmp/ss_results_<short>.json` | — | **必须** — Sonnet sub-agent 反查 SS authorId |
| 6 | `06_user_portfolios.py --input /tmp/ss_results_<X>.json` | stage-5 的 JSON | `users` + `papers` + `github_repos` + `hf_items` + `data_snapshots` + `researcher_personas`；写回 `advisors.impacthub_user_id` | — | — |

旁路：
- `seed_scholars.py` — 一次性导入 `docs/seed_scholars.json` 里 leaderboard seed 用户（走 SS 公开 API + GitHub/HF 自动发现）。**不**走 LLM、**不**走 agent。
- `mentions.py` — 公众号/小红书/知乎 mentions 批量入库。**不**走 LLM。

---

## LLM 调用细节

集中在 `backend/app/services/advisor_crawler_service.py`：

| 何时调 | 入口函数 | 目的 |
|---|---|---|
| Stage 2 | `crawl_school_colleges` → `extract_college_list` | 把学校 homepage HTML 喂给 `gpt-5-mini`，输出 `[{name, url, discipline_category}, ...]` |
| Stage 3 | `crawl_college_advisors` → `extract_advisor_list` | 把学院师资页 HTML 喂给 LLM，输出 `[{name, title, profile_url}, ...]`；启发式抽取在前，LLM 是兜底 |
| Stage 3 | `find_faculty_list_link` | 学院主页不一定是师资页，LLM 找"师资/教师"入口链接 |
| Stage 4 | `crawl_advisor_detail` → `_call_llm` | 把单个老师页面 HTML 喂给 LLM，输出 `{bio, research_areas, email, education, honors}` |

模型：`LLM_FALLBACK_MODEL`（默认 `gpt-5-mini`），endpoint/key 由 `backend/.env` 的 `LLM_API_BASE` / `LLM_API_KEY` 决定。LLM 配额耗尽时 Stage 2/3/4 命中率会断崖式下降但不会 crash —— 启发式回退仍能产出（粗糙）结果，所以爬完后 `--check` 会看到大量 `with_homepage > 0` 但 `bio = ''` 的 stub。

---

## Sonnet sub-agent 旁路

爬虫 service **不**直接调用 Claude Sonnet — 那些都是**人工**通过 Claude Code 的 `Agent` 工具触发的：

| 何时用 | Prompt 模板 | 怎么用 |
|---|---|---|
| **Stage 5 (必须)** SS authorId 反查 | `../prompts/lookup_ss_id.md` | 先 `python 05_ss_match.py --prep --school all` 出输入 JSON；再人工派 Sonnet sub-agent 逐校处理，agent 写 `/tmp/ss_results_<short>.json`；最后 `--check` 验证 |
| Stage 2/3 失败兜底 | `../prompts/discover_faculty.md` | 学校官网被网络封锁 / JS 渲染太复杂时用。agent 写 `/tmp/<school>_advisors.json`，自行 ingest |
| Stage 4 失败兜底 | `../prompts/enrich_stub.md` | stub 有 `homepage_url` 但 service 解析不出 bio 时用。agent 读 `/tmp/<school>_stubs.json` → 写 `/tmp/<school>_enriched.json`，自行 ingest |

Stage 5 是**唯一**强制 agent 的 stage（SS 公开 API 限流严重，2 + WebSearch 的 agent 反而更稳）；其余 agent 是 escape hatch。

---

## Resume 语义 — 每个 stage 怎么定义"已完成"

`run_all.py` 用这 6 个 SQL 探针：

| Stage | "Expected" | "Done" |
|---|---|---|
| 1 schools          | `advisor_schools_211.json` 中的学校数 | DB `advisor_schools` 行数 |
| 2 colleges         | 7 (清北华五) | 7 校中 `colleges_crawled_at IS NOT NULL` |
| 3 advisor_stubs    | 7 校中 CS/AI 学院数 | 其中 `advisors_crawled_at IS NOT NULL` |
| 4 advisor_details  | 7 校 CS/AI advisor 且 `homepage_url != ''` 的数 | 其中 `bio != ''` |
| 5 ss_match         | 7 校 CS/AI advisor 总数 | `/tmp/ss_results_<short>.json` 里 `scholar_id != ''` 的累计数 |
| 6 user_portfolios  | 7 校 CS/AI advisor 总数 | 其中 `impacthub_user_id IS NOT NULL AND != 0` |

CS/AI 学院的关键词在 `pipeline/_common.py::CSAI_KEYWORDS`。

`--strict` 模式下任意 stage 仍有 gap → 退出码 `2` —— cron 据此告警。

---

## 出错怎么办

| 症状 | 排查 |
|---|---|
| Stage 2 后某校 0 colleges | 该校 homepage JS 渲染或学院索引页结构反常；用 `prompts/discover_faculty.md` 派 agent 兜底，或手工 INSERT |
| Stage 3 一直 +0 advisors | service 找不到师资入口；查 `/tmp/advisor_crawl_advisors.log` 看是哪步 LLM 解析失败 |
| Stage 4 大批量 `bio=''` | 多半 LLM endpoint 限流/欠费；查 `/tmp/advisor_detail_csai.log` 是否有 `403`/`429` |
| Stub 名字像"院长寄语"/"团学工作"/"加入我们" | 启发式爬虫把页面段落标题当成了人名 —— 在 `analyze/` 层加 blacklist 清理 |
| Stage 5 `--check` 显示 MISSING | 该校还没跑 Sonnet sub-agent，或 agent 输出文件路径不对 |
| Stage 6 `discover_fail: 作者 X 不存在` | agent 返回的 SS authorId 是同名混淆/已删除；少数情况，可忽略 |
