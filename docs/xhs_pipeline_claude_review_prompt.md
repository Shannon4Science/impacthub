# Claude Review 提示词：小红书 Pipeline 集成方案

请对仓库中的设计文档 `docs/xhs_pipeline_integration_plan.md` 做一次深入、偏架构层面的审阅。

不要只润色文字，也不要顺着文档结论复述；请把自己当成一个会长期维护这个系统的资深工程负责人，尽量找出方案里被低估的复杂度、错误边界和未来会反噬的决定。

请你务必结合仓库现状一起审，而不是只看文档。至少检查这些文件：

- `pipeline/README.md`
- `pipeline/crawl/README.md`
- `pipeline/crawl/mentions.py`
- `backend/app/models.py`
- `backend/app/services/recruitment_summary_service.py`
- `backend/app/services/recommendation_service.py`
- `backend/app/routers/advisor.py`
- `backend/app/database.py`
- `docs/merge_transfer_plan.md`

## 背景

- 当前仓库的 crawl 主线是 01~06 六个顺序 stage，另有 mentions 等旁路。
- 小红书 crawler 目前未正式并入主仓库，但后端已经有 recruitment summary 字段、导入服务和展示接口。
- 现有导师 embedding 是面向“导师画像 / 推荐”的向量，不是帖子索引；当前 embedding 源文本还没有纳入 `recruitment_summary_json`。
- 设计文档当前的核心结论是：
  1. 小红书能力并入 `pipeline/crawl/`
  2. 作为旁路，不作为主线 stage 7
  3. 第一版复用 `advisor_mentions` 与 `advisors.recruitment_summary_json`，不新增正式表
  4. 抓取时不直接生成 embedding
  5. 将来若要影响推荐，只把结构化后的稳定摘要字段并入导师 embedding
  6. 将来若要搜帖子，再单独建帖子级向量索引

## 请重点回答

1. 上述六个结论里，哪些你同意，哪些你反对，理由是什么？
2. “第一版不新增正式表”是否真的稳妥？特别请检查：
   - 运行级溯源
   - 失败恢复
   - 摘要来源可追踪性
   - 未来重跑
   - 调试
   - `advisor_mentions` 是否已经被赋予过多职责
3. 小红书作为旁路而不是主线 stage，是否会让刷新、完整性检查、调度和运维变得模糊？如果是，应该如何设计更清楚？
4. 现有 `recruitment_summary_service.py` 的数据契约，是否已经暗示了更适合的表设计或边界？请具体指出。
5. 关于 embedding：
   - 是否确实不应在采集时生成？
   - 若未来让招生信息影响推荐，哪些字段适合进入导师 embedding，哪些不适合？
   - 是否需要把“用于展示的摘要”和“用于推荐的特征文本”拆成两个产物？
6. 文档里是否缺少关键的状态机、幂等键、唯一约束、刷新策略或失败语义？
7. 如果让你给出一版更稳、更长期主义、但不过度设计的方案，你会怎么改？

## 输出要求

- 先给总体判断：`基本同意 / 部分同意 / 不同意`，并用 3~6 句话说明。
- 然后列出你认为最重要的 5~10 个问题，按严重程度排序。
- 每个问题必须包含：
  - `问题`
  - `为什么重要`
  - `建议怎么改`
- 最后给出一版你建议采用的修订后方案，尽量具体到：
  - 数据模型
  - 任务边界
  - embedding 触发时机
- 如果你认为文档中某个结论其实是对的，也请明确说出“为什么它是对的”，不要为了挑错而挑错。
