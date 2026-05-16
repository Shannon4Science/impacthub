# 小红书招生数据接入 Pipeline 方案

## 1. 这份文档要解决什么问题

当前仓库已经具备：

- 导师基础数据 Pipeline：`pipeline/crawl/01_*` 到 `06_*`
- 社交 mentions 存储：`advisor_mentions`
- 招生摘要读取接口：`GET /api/advisor/advisors/{id}/recruitment`
- 小红书招生摘要导入服务：`backend/app/services/recruitment_summary_service.py`
- 导师推荐向量缓存：`advisor_embedding_vec` + `advisor_embedding_metadata`

但小红书 Crawler 仍未正式接入主仓库的 Pipeline。现在需要决定两件事：

1. 小红书采集代码应放在哪里、如何接入现有 Pipeline；
2. 小红书数据写入时，是否应该同步调用 embedding 模型并落库。

本文的目标不是把旧 `xhs_crawler/` 原样搬进来，而是给出一套能长期维护、能逐步演进、且不破坏现有仓库边界的集成方案。

---

## 2. 当前仓库现状

### 2.1 Pipeline 的现有边界

`pipeline/README.md` 将系统分成两层：

- `crawl/`：外部原始数据 → 主库
- `analyze/`：基于主库做派生分析

现有 `crawl/` 主线是 6 个顺序 stage：

1. schools
2. colleges
3. advisor stubs
4. advisor details
5. SS match
6. user portfolios

此外已有两个并行旁路：

- `seed_scholars.py`
- `mentions.py`

这说明仓库当前并不要求所有数据采集能力都塞进主线 stage；只要某项能力不是构建基础导师库的硬前提，就可以作为旁路任务存在。

### 2.2 小红书相关能力已经部分进入主系统

现有代码已经包含：

- `Advisor.recruitment_summary_json`
- `Advisor.recruitment_summary_refreshed_at`
- `Advisor.recruitment_summary_status`
- `recruitment_summary_service.import_xhs_recruitment_summary()`
- `/api/advisor/advisors/{id}/recruitment`
- `advisor_mentions.source = "xiaohongshu"` 的存储路径

也就是说，小红书已经不只是一次性实验产物，而是开始成为正式产品能力的一部分。

### 2.3 当前 embedding 的实际语义

现有导师 embedding 由 `backend/app/services/recommendation_service.py` 生成。当前源文本包含：

- 导师姓名
- 学校
- 学院
- 职称
- 研究方向
- 简介
- 荣誉
- `recruiting_intent`

但**当前没有把 `recruitment_summary_json` 纳入 embedding 源文本**。

这意味着：

- 即使小红书摘要写入成功，现有推荐向量也不会自动变化；
- 当前导师 embedding 的语义是“导师研究画像”，不是“帖子语义索引”。

---

## 3. 第一性原则

### 3.1 采集、归纳、检索是三件事

小红书链路至少包含三类职责：

1. **采集**：把帖子拿回来；
2. **归纳**：从帖子里提炼招生状态、方向、要求；
3. **检索**：为了推荐或搜索生成向量。

这三件事的输入稳定性、失败模式、重算频率都不同，不应绑死在一次请求里。

### 3.2 正式产品能力应进入主仓库，但不能把旧项目边界一并搬入

如果招生摘要要长期展示、刷新、调度，它就属于主系统。

但旧 `xhs_crawler/` 如果带着独立：

- `.git`
- `.env`
- `config.yaml`
- `data/**`
- 独立数据库

一起搬进主仓库，会把主系统重新切碎。应迁移“能力”，不迁移“小项目壳”。

### 3.3 向量只应编码稳定、可解释的语义对象

如果一个向量用于“推荐导师”，它就应该代表导师画像；
如果一个向量用于“搜索帖子”，它就应该代表帖子。

两者不应混成同一个索引。

---

## 4. 方案结论

### 4.1 小红书 Crawler 应并入 `pipeline/crawl/`

推荐结构：

```text
pipeline/crawl/
├── xhs_recruitment.py          # 对外 CLI 入口 / orchestrator
├── xiaohongshu/
│   ├── __init__.py
│   ├── client.py               # 请求、登录态、分页
│   ├── search.py               # 按导师、学校、关键词搜索帖子
│   ├── normalize.py            # 外部响应 -> 内部统一结构
│   ├── filter.py               # 招生候选帖筛选
│   ├── summarize.py            # 候选帖 -> 招生摘要 JSON
│   └── schemas.py              # 内部数据结构
└── README.md
```

### 4.2 它应作为 `crawl/` 的并行旁路，而不是第 7 个主 stage

理由：

- 主线 1–6 的目标是建立导师基础库；
- 小红书属于“补充招生情报”，不是构建基础导师数据的前提；
- 小红书数据源波动大、依赖登录态/风控，不能让其失败阻塞基础库；
- 并非每位导师都能搜到有效帖子，无法自然使用“全量完成”定义主线 stage。

建议把它放在文档中的旁路任务列表里，与 `mentions.py` 并列。

### 4.3 第一版应新增一张很轻的运行记录表，但不提前拆完整数据仓

第一版继续复用现有业务表：

| 数据 | 存储位置 |
|---|---|
| 小红书候选帖 | `advisor_mentions` |
| 招生摘要 | `advisors.recruitment_summary_json` |
| 摘要状态 | `advisors.recruitment_summary_status` |
| 摘要刷新时间 | `advisors.recruitment_summary_refreshed_at` |

但应新增一张**运行记录表**，建议名为 `xhs_crawl_runs`：

```text
xhs_crawl_runs
├── id
├── advisor_id
├── status                # searching / summarizing / done / failed
├── search_query
├── raw_note_count
├── candidate_count
├── mentions_inserted
├── summary_updated
├── error
├── started_at
└── finished_at
```

这不是为了“先把系统设计完整”，而是为了保留最低限度的运行事实：

- 这条摘要是哪一次运行产出的；
- 搜到了多少原始帖子、筛出了多少候选帖；
- 失败发生在搜索、摘要还是入库；
- 哪些导师从未跑过、哪些刚失败、哪些最近刚成功。

没有这张表，后续一旦开始批量刷新，调度、排障、重跑都会变成黑盒。

第一版仍暂不新增：

- `xhs_notes`
- `xhs_raw_payloads`
- `advisor_mention_embeddings`

理由：

- 当前还不需要把帖子原始仓、帖子级向量仓提前做出来；
- 但“运行事实”不是附加优化，而是能否运维这条链路的基础。

但保留本地调试产物：

```text
pipeline/data/xiaohongshu/output/
└── YYYY-MM-DD/
    └── advisor_<id>/
        ├── raw_notes.jsonl
        ├── candidates.jsonl
        └── summary.json
```

该目录应加入 `.gitignore`，仅用于排障与回溯，不作为正式数据源；正式运行状态以 `xhs_crawl_runs` 为准。

### 4.4 抓取时不要直接生成 embedding

推荐的数据流：

```text
抓取原始帖子
→ 归一化 / 去重 / 候选筛选
→ 生成结构化招生摘要
→ 写入主库
→ 若下游需要，再独立刷新 embedding
```

不建议：

```text
抓到帖子
→ 立刻调 embedding
→ 同步写向量
```

原因：

1. 原始帖子噪声大，后续筛选或摘要变化后，向量立刻过期；
2. 采集任务会被 embedding API 的失败、限流、成本放大；
3. 当前导师向量语义是“导师画像”，不是“帖子语义”；
4. 如果未来更换模型，独立重建比追溯采集时状态更简单；
5. embedding 是派生物，应该能由主库中的稳定源字段重建。

---

## 5. 目标数据流

### 5.1 输入

`xhs_recruitment.py` 接收：

- `advisor_id`
- 或学校 / 学院 / 导师过滤条件

最小支持的 CLI：

```bash
python crawl/xhs_recruitment.py --advisor-id 123
python crawl/xhs_recruitment.py --school-name 浙江大学 --college-name 计算机学院
python crawl/xhs_recruitment.py --advisor-id 123 --dry-run
python crawl/xhs_recruitment.py --check
```

### 5.2 原始候选帖结构

内部统一成类似结构：

```json
{
  "note_id": "xxx",
  "url": "https://www.xiaohongshu.com/explore/xxx",
  "title": "...",
  "content": "...",
  "author_name": "...",
  "published_at": "2026-05-16T08:00:00+08:00",
  "likes": 123,
  "comment_count": 8,
  "matched_keywords": ["招生", "保研"]
}
```

### 5.3 摘要结构

沿用现有后端已能消费的字段：

```json
{
  "recruitment_status": "found_current",
  "summary": "...",
  "positions": [],
  "directions": [],
  "requirements": [],
  "application_methods": [],
  "timeline": [],
  "source_posts": [],
  "limitations": []
}
```

### 5.4 入库动作

统一通过 `import_xhs_recruitment_summary()`：

1. 候选帖写入 `advisor_mentions`
2. 候选帖带稳定外部 ID，例如小红书 `note_id`
3. 数据库层做幂等约束，不能只靠应用层查重
4. 招生摘要写入 `advisors`
5. 刷新 `recruitment_summary_refreshed_at`

建议给 `advisor_mentions` 增加：

- `external_id`：存来源平台的稳定内容 ID，例如小红书 `note_id`
- `mention_type`：建议至少区分 `general` / `recruitment`

建议唯一约束优先使用：

```text
(advisor_id, source, external_id)
```

在 `external_id` 缺失的兼容场景下，再用规范化后的 URL 作为兜底幂等键。

原因：

- 同一条小红书笔记可能有多种 URL；
- 仅靠代码先查再写，在并发时会产生重复记录；
- 小红书“招生证据帖”和“普通口碑帖”语义不同，不应只靠 `source = "xiaohongshu"` 混在一起。

### 5.5 招生摘要应尽量自包含

当前后端会先读取 `recruitment_summary_json`，再根据 `source_posts/evidence_posts.note_id` 回查 `advisor_mentions` 补正文。

这说明“展示所需数据”被分散到了两处。第一版建议把摘要接口真正需要展示的证据帖内容直接存进 `recruitment_summary_json` 中，让摘要成为一个自包含快照：

- 摘要 JSON 中保留证据帖的 `note_id`
- 同时保留标题、URL、发布时间、必要正文摘录或正文内容
- `advisor_mentions` 仍保留帖子记录，但不再成为摘要读取的必经依赖

这样即使后续帖子存储策略调整，历史摘要仍可被稳定解释。

---

## 6. 刷新策略

### 6.1 第一版：只做手动触发

第一版只要求：

- 能按导师刷新；
- 能 dry-run；
- 能看当前哪些导师有摘要、哪些没有；
- 能区分：
  - 从未搜索
  - 最近成功
  - 明确无有效结果
  - 最近失败

`--check` 不应只显示“有 / 没有摘要”，而应结合 `xhs_crawl_runs` 给出可运维的状态，例如：

```text
总导师数
有摘要（current）
有摘要（stale）
明确无有效结果
从未搜索
最近失败
```

### 6.2 第二版：再做批量刷新

等单导师链路稳定后，再增加批量规则，例如：

- 摘要为空；
- 摘要超过 30 天；
- 重点导师名单；
- 最近被用户访问过。

不建议第一版就全量扫所有导师。

---

## 7. embedding 的后续接入方式

### 7.1 第一阶段：小红书只服务展示，不影响推荐

第一版先保持当前推荐系统不变：

- `advisor_mentions` 增加小红书来源；
- 导师详情页展示招生摘要；
- `advisor_embedding_vec` 不变。

先验证这条产品链是否稳定、是否有真实价值。

### 7.2 第二阶段：如果确认要影响推荐，再扩导师 embedding 源文本

如果后续要让招生信息影响推荐，应加入的是**结构化后的稳定字段**，不是原始帖子全文。

建议未来将导师 embedding 文本扩展为：

- 当前招生方向
- 招生对象
- 明确要求

来源：

- `directions`
- `positions`
- `requirements`

不建议直接纳入：

- `source_posts`
- 帖子全文
- `timeline`
- `application_methods`
- `recruitment_status`

原因是这些信息要么噪声高，要么更适合展示/过滤，而不是语义匹配。

不必为了推荐额外生成一份“第二摘要”。更简单的做法是：继续只保留一份面向展示的结构化摘要，在 `build_advisor_embedding_text()` 中选择性抽取适合推荐的字段。这样既避免重复产物漂移，也保留推荐侧的独立控制权。

### 7.3 向量刷新方式

现有系统已经有：

- `build_advisor_embedding_text()`
- `source_hash`
- `ensure_advisor_embeddings()`

因此未来推荐做法是：

1. 将招生摘要的关键字段并入 `build_advisor_embedding_text()`
2. 摘要变化后，源文本 hash 自然变化
3. 后续执行 `ensure_advisor_embeddings()` 时自动重建

可以额外补一个精确刷新入口：

```bash
python backend/scripts/generate_advisor_embeddings.py --advisor-id 123
```

但不应把 embedding 生成塞进抓取主流程。

### 7.4 如果未来需要“搜帖子”，应另建帖子级索引

若未来产品需求变成：

- 按语义搜小红书帖子
- 找和某条帖子相似的帖子
- 基于帖子做 RAG

则应新增独立的帖子级 embedding 表，而不是复用导师画像索引。

导师向量回答的是：

> 这个导师适不适合这个学生？

帖子向量回答的是：

> 哪些帖子和这个查询最接近？

这是两个问题，不应混用一个向量空间。

---

## 8. 第一版明确不做什么

第一版不做：

1. 不把旧 `xhs_crawler/` 原样搬进主仓库；
2. 不把小红书任务并入 `crawl/run_all.py` 主线；
3. 不提前拆 `xhs_notes` / `xhs_raw_payloads` / 帖子级向量表；
4. 不做全量定时刷新；
5. 不在抓取时同步生成 embedding；
6. 不让原始帖子直接进入导师推荐向量；
7. 不做帖子级向量检索。

---

## 9. 第一版验收标准

一次成功任务后，应满足：

1. `advisor_mentions` 中新增 `source = "xiaohongshu"` 的记录；
2. `advisors.recruitment_summary_json` 非空；
3. `/api/advisor/advisors/{id}/recruitment` 返回正确结构；
4. 重复执行相同任务，不重复插入相同 URL；
5. `--dry-run` 不改数据库；
6. 无有效候选帖时，系统明确给出“未找到有效招生信息”，不伪造摘要；
7. 任务失败时暴露错误，不静默降级；
8. 整个任务不依赖独立数据库、不依赖独立 `.env`；
9. 每次任务都在 `xhs_crawl_runs` 留下可追踪状态；
10. 并发或重复执行时，不会因应用层查重竞态插入重复帖子。

---

## 10. 实施顺序

### 第一步：迁能力，不迁壳

- 从旧项目挑出真正需要的抓取、搜索、摘要逻辑；
- 删除其独立配置、缓存、数据库依赖；
- 改成读取主仓库配置。

### 第二步：搭出主入口

- 新建 `pipeline/crawl/xhs_recruitment.py`
- 打通单导师：
  - 查询导师
  - 抓取
  - 筛选
  - 摘要
  - 入库

### 第三步：补最小校验

- `external_id` / 唯一约束
- `--dry-run`
- 失败显式抛错
- `xhs_crawl_runs` 状态落库
- 本地调试产物输出

### 第四步：补文档

- 更新 `pipeline/README.md`
- 更新 `pipeline/crawl/README.md`
- 写清它是旁路任务，不是主线 stage

### 第五步：再决定是否把招生摘要纳入推荐

- 先观察产品价值和数据质量；
- 若确认有价值，再修改导师 embedding 源文本，并重建向量。

---

## 11. 需要重点审阅的问题

请审阅者重点判断以下问题，而不是只看文风：

1. 把小红书做成 `crawl/` 旁路而不是主线 stage，这个边界是否正确？
2. 第一版复用 `advisor_mentions` + `advisors.recruitment_summary_json`，并只新增一张轻量 `xhs_crawl_runs` 表，这个边界是否足够？
3. “抓取时不直接做 embedding”是否是正确结论？是否存在我忽略的强理由，需要在采集时立即建向量？
4. 若未来让招生信息影响推荐，应该把哪些字段放进导师 embedding，哪些不该放？
5. 当前方案是否遗漏了幂等性、数据溯源、刷新、失败恢复中的关键问题？
6. 是否需要为“本次抓取运行”保留正式表，而不能只留本地调试文件？
7. 是否存在比“迁能力，不迁旧项目壳”更简单、更稳的集成方式？

---

## 12. 当前倾向

当前推荐结论：

1. 小红书能力并入 `pipeline/crawl/`
2. 作为并行旁路任务，不进入主线 stage
3. 第一版复用现有业务表，但新增 `xhs_crawl_runs` 记录运行事实
4. 采集与 embedding 解耦
5. 若未来要影响推荐，只把结构化摘要中的稳定字段纳入导师 embedding
6. 若未来要搜帖子，再单独建设帖子级向量索引
