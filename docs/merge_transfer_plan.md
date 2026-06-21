# 功能前移方案（执行版）

日期：2026-05-16（修订：2026-05-16）

## 1. 核心结论

以 `/Users/goblinmike/Downloads/impacthub`（同伴最新主线）为唯一目标仓库，把 `/Users/goblinmike/Documents/code/impacthub`（功能开发目录）里真正新增的能力按功能包**手动逐文件移植**过去。

**不用 cherry-pick**。两边从 `1ff8444` 分叉后对几乎所有共享文件做了不同的修改，cherry-pick 会在 6+ 个文件产生冲突，解冲突的代价比手动移植更大、更容易出错。

**不用整仓库 merge / 复制**。那会丢掉目标仓库已有的 pipeline/、导师 AI、口碑墙和最新数据库。

**招生摘要刷新这次不迁移**。来源仓库里的 `refresh_summary()` 仍是空实现，当前又没有把 `xhs_crawler/` 正式接入主系统。把“刷新”按钮和接口先带进主线，只会制造一个看似可用、实际无效的功能。此次只迁移“查看 + 导入”；等爬虫归属确定后，再补真正的刷新链路。

**数据迁移只迁干净数据**。来源库里 `王文冠` 被错误挂在“北京大学 / 建筑学院”，而帖子内容明显指向“浙江大学 / 计算机学院”；目标库里当前也没有可直接匹配的正确记录。因此不能按旧库主键或旧关联直接搬运。此次直接迁移 `严骏驰` 的 1 份摘要和 1 条小红书 mention；`王文冠` 的摘要和 11 条 mention 先保留为待校正数据，等目标库出现正确导师记录后再导入。

## 2. 仓库状态确认

### 目标仓库（最终主线）

- 路径：`/Users/goblinmike/Downloads/impacthub`
- HEAD：`29904ab feat(pipeline): extract crawl + analyze layers, scope frontend to 清北华五 CS/AI`
- 与 `origin/main` 同步
- 已有能力：
  - `pipeline/` 数据采集与分析分层
  - 导师 AI 聊天（`advisor_chat_service.py` + `AdvisorChatPage.tsx`）
  - 口碑墙 / mention feed（`MentionsFeedPage.tsx`）
  - 未关联 mention 的 pending/reconcile 机制
  - 前端限定清北华五 CS/AI 范围
  - 删除旧 scheduler，刷新由 `pipeline/crawl/refresh_all.py` + cron 负责
  - 数据库更新（312 users, 236 SS-linked advisors）

### 功能来源仓库

- 路径：`/Users/goblinmike/Documents/code/impacthub`
- HEAD：`5acfeec`（ahead 3, behind 1 of origin/main）
- 新增提交：
  - `9718c6f feat: add advisor detail page + recruitment summary`
  - `c238042 feat: add advisor recommendation workflow`
  - `5acfeec docs: add merge transfer plan`
- 额外内容：
  - `xhs_crawler/`（独立 git 子项目，有自己的 .env / data / .git）
  - `简历测试样例/`（私人简历 PDF）
  - 设计文档（导师推荐功能方案.md 等）
  - 旧 `backend/app/tasks/scheduler.py` 仍存在且在 `main.py` 中被 import

### 共同祖先

- `1ff8444 feat(advisor): add mentions table + ingest pipeline`

## 3. 要移植的功能包

### 功能包 A：导师详情页 + 招生摘要

来源提交：`9718c6f`

**纯新文件**（直接复制到目标仓库）：

| 文件 | 说明 |
|------|------|
| `backend/app/services/recruitment_summary_service.py` | 招生摘要服务（172 行）|
| `frontend/src/pages/AdvisorDetailPage.tsx` | 导师详情页（44 行）|
| `frontend/src/components/advisor/RecruitmentSummary.tsx` | 招生摘要组件（338 行）|

**需要修改的共享文件**（在目标仓库版本上手动加代码）：

| 文件 | 加什么 | 注意什么 |
|------|--------|---------|
| `backend/app/models.py` | Advisor 类加 3 个字段：`recruitment_summary_json`、`recruitment_summary_refreshed_at`、`recruitment_summary_status` | 保留目标已有的 `pending_advisor_name` / `pending_school_name`（在 AdvisorMention 上）|
| `backend/app/database.py` | 加 3 条 `ALTER TABLE advisors ADD COLUMN recruitment_summary_*` 迁移 | **不动** sqlite-vec 部分（那是功能包 B 的事）；保留目标已有的 `pending_*` 迁移 |
| `backend/app/routers/advisor.py` | 加招生摘要 API 端点（~60 行） | 保留目标已有的聊天 / 口碑墙 / pending mention 端点（~200 行）|
| `frontend/src/App.tsx` | 加 `AdvisorDetailPage` import + `/advisor/advisors/:advisorId` 路由 + 导航链接 | 保留目标已有的 `AdvisorChatPage` / `MentionsFeedPage` import 和路由 |
| `frontend/src/lib/api.ts` | 加招生摘要相关类型和接口函数 | 保留目标已有的聊天 / 口碑墙类型和接口 |
| `frontend/src/main.tsx` | 加 `@tanstack/react-query` 的 `QueryClientProvider` 包裹 `<App />` | `RecruitmentSummary.tsx` 直接依赖 `useQuery`，没有 Provider 会运行时崩溃 |
| `frontend/package.json` | 加 `@tanstack/react-query` 依赖 | 加完后跑 `npm install` 重新生成 lock file |

**不并入**：`backend/import_wwg.py`、`backend/import_wwg_new.py`（阶段 E 数据迁移时再评估）。

**半成品要收口**：
- `refresh_summary()` 目前是 `pass`：本次不迁移空刷新链路
- `AdvisorDetailPage` 只展示 ID + 摘要：至少补上导师基本信息

### 功能包 B：简历推荐 + 套磁信

来源提交：`c238042`

**纯新文件**（直接复制到目标仓库）：

| 文件 | 说明 |
|------|------|
| `backend/app/routers/recommendation.py` | 推荐 API（153 行）|
| `backend/app/services/recommendation_service.py` | 推荐服务（852 行）|
| `backend/scripts/generate_advisor_embeddings.py` | embedding 生成脚本（56 行）|
| `frontend/src/pages/RecommendationPage.tsx` | 推荐页前端（729 行）|

**需要修改的共享文件**（在目标仓库版本上手动加代码）：

| 文件 | 加什么 | 注意什么 |
|------|--------|---------|
| `backend/app/config.py` | 加 DashScope / MinerU / recommendation 相关配置（约 10 行） | 来源有 `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`、`DASHSCOPE_EMBEDDING_MODEL`、`DASHSCOPE_EMBEDDING_DIMENSIONS`、`MINERU_PATH`、`RECOMMENDATION_TOP_N` |
| `backend/app/database.py` | 加 `pysqlite3` 猴子补丁 + `sqlite_vec` 扩展加载 + `advisor_embedding_vec` 虚表创建 | **这是最危险的改动**——猴子补丁影响全局，加载失败整个后端崩溃。保留阶段 A 已加的所有迁移 |
| `backend/app/models.py` | 加 `AdvisorEmbeddingMetadata` 和 `RecommendationSession` 两个模型类 | 保留目标已有的所有模型 |
| `backend/app/main.py` | **只加** `recommendation` 的 import 和 `include_router` 行 | **绝对不要**复制来源的 `from app.tasks.scheduler import start_scheduler` 和 `start_scheduler()` 调用。来源的 `main.py` 仍然保留了旧 scheduler，但目标仓库已经正确删除了它 |
| `backend/app/schemas.py` | 加 `CoverLetterResponse` schema | |
| `backend/requirements.txt` | 加 `python-multipart`、`pysqlite3`、`sqlite-vec` 等依赖 | `python-multipart` 是 PDF 上传接口的运行时依赖，不能漏 |
| `.env.example` | 加 `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL` 等配置项 | |
| `frontend/src/App.tsx` | 加 `RecommendationPage` import + `/recommendation` 路由 + 导航链接 | 保留阶段 A 已加的 AdvisorDetailPage |
| `frontend/src/lib/api.ts` | 加推荐相关类型、接口和 `requestForm()` 帮助函数 | `requestForm()` 的错误处理比目标现有的 `request()` 更复杂——统一成一种风格 |

### 暂不并入的内容

| 内容 | 原因 |
|------|------|
| `xhs_crawler/` 整个目录 | 独立 git、独立 .env、独立数据库、README 说未接入主后端 |
| `简历测试样例/` | 含私人简历 PDF |
| `导师推荐功能方案.md` 等设计文档 | 开发过程文档，不需要进主仓库 |
| `5.8需求迭代.md` | 同上 |
| `AGENTS.md` | 目标仓库有自己的版本 |
| `backend/app/tasks/scheduler.py` | 目标仓库已删除旧 scheduler |
| `backend/data/recommendation_uploads/` | 运行时数据 |

## 4. 所有冲突文件完整清单

下表汇总了两个功能包涉及的所有共享文件，标注了两边各自改了什么：

| 文件 | 来源仓库的改动 | 目标仓库的改动 | 哪个功能包 |
|------|---------------|---------------|-----------|
| `backend/app/database.py` | 加 sqlite-vec + recruitment_summary 迁移 | 加 pending_* 迁移 | A + B |
| `backend/app/models.py` | 加 recruitment_summary 字段 + 2 个新 Model | 改 AdvisorMention（加 pending_* 字段、改 advisor_id default） | A + B |
| `backend/app/routers/advisor.py` | 加招生摘要 API（~60 行） | 加聊天/口碑墙/pending API（~200 行） | A |
| `backend/app/main.py` | 加 recommendation router + 保留旧 scheduler | 删 scheduler，没有 recommendation | B |
| `backend/app/config.py` | 加 DashScope/MinerU 配置 | 无改动 | B |
| `backend/app/schemas.py` | 加 CoverLetterResponse | 无改动 | B |
| `backend/requirements.txt` | 加 python-multipart, pysqlite3, sqlite-vec | 无改动 | B |
| `frontend/src/App.tsx` | 加 AdvisorDetailPage + RecommendationPage | 加 AdvisorChatPage + MentionsFeedPage | A + B |
| `frontend/src/lib/api.ts` | 加推荐/招生摘要类型 + requestForm | 加聊天/口碑墙类型 | A + B |
| `frontend/src/main.tsx` | 加 QueryClientProvider | 无改动 | A |
| `frontend/package.json` | 加 @tanstack/react-query | 无改动 | A |
| `backend/app/services/advisor_crawler_service.py` | 无改动（停留在旧版本） | 加 reconcile_unlinked_mentions() + 改进 URL 匹配（+225 行） | 不直接冲突但需注意 |

## 5. 数据现状与处理原则

### 数据库对比

| 指标 | 目标仓库（主库） | 来源仓库 |
|------|-----------------|---------|
| users | 312 | 84 |
| advisor_colleges | 3131 | 3088 |
| advisors | 50511 | 50284 |
| advisor_mentions | 447 | 459 |
| SS-linked advisors | 236 | 0 |
| recruitment_summary 非空 | 0 | 2 |
| advisor_embedding_metadata | 0 | 38 |
| recommendation_sessions | 0 | 13 |
| 小红书 mentions | 0 | 12 |

说明：
- “SS-linked advisors” 的实际统计字段是 `advisors.semantic_scholar_id != ''`
- “小红书 mentions” 的实际统计字段是 `advisor_mentions.source = 'xiaohongshu'`

### 判断

目标仓库数据库作为主库，来源仓库只迁移：
- 可确认归属正确的真实招生摘要
- 可确认归属正确的小红书 mention

重新生成（不迁移）：
- 向量表和 advisor_embedding_metadata（基于主库最新导师数据重建）

不迁移：
- 旧库整体
- recommendation_sessions（运行过程数据）
- xhs_crawler/ 内部数据库

## 6. 执行步骤

### 阶段 0：准备工作

1. **在目标仓库创建特性分支**
   ```bash
   cd /Users/goblinmike/Downloads/impacthub
   git checkout -b feature/migrate-advisor-features
   ```
   所有迁移工作在此分支完成，验收通过后 PR 回 main。回退成本为零。

2. **验证目标仓库基线**
   ```bash
   cd /Users/goblinmike/Downloads/impacthub
   # 后端
   python -m compileall backend/app
   # 前端
   cd frontend && npm run lint && npm run build
   ```

3. **验证功能包 B 的运行时依赖（门禁）**
   ```bash
   pip install python-multipart pysqlite3 sqlite-vec
   python -c "
   import pysqlite3, sqlite_vec
   conn = pysqlite3.connect(':memory:')
   conn.enable_load_extension(True)
   conn.load_extension(sqlite_vec.loadable_path())
   print(conn.execute('SELECT vec_version()').fetchone())
   "
   ```
   如果这个脚本跑不过，功能包 B 不能继续。不影响功能包 A。

4. **验证功能包 A 的前端依赖**
   ```bash
   cd frontend && npm install @tanstack/react-query
   ```

5. **备份目标数据库**
   ```bash
   cp /Users/goblinmike/Downloads/impacthub/backend/data/impacthub.db /Users/goblinmike/Downloads/impacthub/backend/data/impacthub.db.bak
   ```
   来源仓库本轮只读，不在原地改写，没必要再制造一份同目录备份。

### 阶段 A：移植功能包 A（导师详情页 + 招生摘要）

**操作方式**：打开来源仓库文件作为参考，在目标仓库文件上手动添加代码。

**步骤**：

1. 复制 3 个纯新文件到目标仓库
2. 在目标仓库的 `models.py` 中 Advisor 类上加 3 个 recruitment_summary 字段
3. 在目标仓库的 `database.py` 中加 3 条 ALTER TABLE 迁移（加在现有 pending_* 迁移之后）
4. 在目标仓库的 `routers/advisor.py` 中加招生摘要 API 端点
5. 在目标仓库的 `App.tsx` 中加 import + 路由 + 导航链接
6. 在目标仓库的 `api.ts` 中加招生摘要类型和接口
7. 在目标仓库的 `main.tsx` 中加 QueryClientProvider
8. 收口半成品（导师详情页信息补全）

**本阶段明确不迁移**
- `POST /advisor/advisors/{advisor_id}/recruitment/refresh`
- `refresh_summary()`

原因：当前没有真实刷新链路，提前暴露接口只会制造假能力。

**验收**：

- `python -m compileall backend/app`
- `npm run lint && npm run build`
- 后端启动无报错
- `/advisor/advisors/:advisorId` 可访问
- `/api/advisor/advisors/{id}/recruitment` 返回数据
- `/advisor/chat` 不受影响
- `/advisor/mentions` 不受影响
- `/advisor` 页面导师列表不受影响

### 阶段 B：移植功能包 B（简历推荐 + 套磁信）

**前提**：阶段 0 的 sqlite-vec 门禁已通过。

**步骤**：

1. 复制 4 个纯新文件到目标仓库
2. 修改 `config.py`：加 DashScope/MinerU/recommendation 配置项
3. 修改 `database.py`：加 pysqlite3 补丁 + sqlite-vec 加载 + 向量表创建（保留所有已有迁移）
4. 修改 `models.py`：加 `AdvisorEmbeddingMetadata` 和 `RecommendationSession`
5. 修改 `main.py`：**只加** `from app.routers import recommendation` 和 `app.include_router(recommendation.router, ...)`
6. 修改 `schemas.py`：加 `CoverLetterResponse`
7. 修改 `requirements.txt`：加 python-multipart、pysqlite3、sqlite-vec 等
8. 修改 `.env.example`：加 DashScope 配置项
9. 修改 `App.tsx`：加 RecommendationPage 路由 + 导航
10. 修改 `api.ts`：加推荐相关接口和 `requestForm()`

**验收**：

- 后端启动无报错（sqlite-vec 加载成功）
- `python -m compileall backend/app backend/scripts`
- `npm run lint && npm run build`
- 能生成导师 embedding
- 能上传 PDF 简历
- 能完成推荐任务
- 能生成套磁信
- 阶段 A 的所有功能仍正常

### 阶段 C：xhs_crawler 决策

不急着做。先完成 A + B 验收。

两个选项：

**方案 1：继续独立** — 适合仍在快速试验、依赖差异大的情况。主系统通过 JSON 导入它的产出。

**方案 2：并入 `pipeline/crawl/`** — 适合招生摘要已成为正式产品能力、需要统一调度的情况。不要原样搬入。

无论哪种方案都不迁入：`.git`、`.env`、`config.yaml`、`data/**`、本地缓存。

### 阶段 D：数据补录

1. 从来源仓库数据库导出并导入 `严骏驰` 的 1 份招生摘要
2. 从来源仓库数据库导出并导入 `严骏驰` 的 1 条小红书 mention
3. 将 `王文冠` 的摘要和 11 条 mention 记录为“待校正数据”，本次不直接写入主库
4. 评估 `import_wwg.py` / `import_wwg_new.py` 是否只可作为排查材料使用；在导师身份未校正前，不直接执行
5. 在目标仓库最新数据库上重建 embedding
6. 推荐系统端到端验证

### 阶段 E：收尾

1. 特性分支 PR 回 main，做 review
2. 来源仓库归档（不再在上面开发）
3. 清理 `.env.example`、`CLAUDE.md` 等配置文件

## 7. 不要做的事

| 操作 | 为什么不做 |
|------|-----------|
| `git cherry-pick 9718c6f` / `c238042` | 6+ 个文件会冲突，解冲突比手动移植更慢更危险 |
| 整仓库 merge / 复制 | 会丢失目标仓库的 pipeline/、导师AI、口碑墙 |
| 拿来源数据库覆盖目标数据库 | 来源数据更旧（84 vs 312 users, 0 vs 236 SS-linked）|
| 把 xhs_crawler/ 原样塞入主仓库 | 带着独立 .git/.env/data，会污染主仓库 |
| 恢复旧 scheduler | 目标仓库已正确迁移到 pipeline + cron |
| 在 main 分支上直接操作 | 出问题无法干净回退，无法做 PR review |

## 8. 迁移完成后的总验收清单

### 后端

- [ ] 后端启动无报错
- [ ] `python -m compileall backend/app backend/scripts`
- [ ] `/api/advisor/stats` 正常
- [ ] `/api/advisor/chat` 正常
- [ ] `/api/advisor/mentions/feed` 正常
- [ ] `/api/advisor/advisors/{id}/recruitment` 正常
- [ ] `/api/recommendation/*` 正常
- [ ] sqlite-vec 扩展加载成功

### 前端

- [ ] `npm run lint` 无错误
- [ ] `npm run build` 成功
- [ ] `/advisor` 导师列表正常（仍限定清北华五 CS/AI）
- [ ] `/advisor/chat` 导师 AI 正常
- [ ] `/advisor/mentions` 口碑墙正常
- [ ] `/advisor/advisors/:advisorId` 详情页正常
- [ ] `/recommendation` 推荐页正常

### 数据

- [ ] 目标数据库用户数 >= 312
- [ ] SS-linked 导师数 >= 236
- [ ] 已确认归属正确的招生摘要可查
- [ ] 已确认归属正确的小红书 mention 已导入
- [ ] embedding 已基于最新导师库重建
