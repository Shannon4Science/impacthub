<p align="center">
  <img src="frontend/public/logo.svg" width="120" alt="ImpactHub Logo" />
</p>

<h1 align="center">ImpactHub</h1>

<p align="center">
  <b>Unified Research Impact Dashboard</b><br/>
  Aggregate your academic papers, GitHub repos, and Hugging Face models into one portfolio.
</p>

<p align="center">
  <a href="#features">Features</a> &bull;
  <a href="#demo">Demo</a> &bull;
  <a href="#quick-start">Quick Start</a> &bull;
  <a href="#configuration">Configuration</a> &bull;
  <a href="#architecture">Architecture</a> &bull;
  <a href="#-中文说明">中文</a>
</p>

---

## Features

### Cross-Platform Profile

One profile that unifies your presence across **Semantic Scholar**, **GitHub**, and **Hugging Face**. Enter your Scholar ID — the system auto-discovers your linked GitHub and HF accounts.

### Citation Intelligence

- H-index auto-computation and CCF-A/B/C venue classification
- Identifies **top scholars** (h-index ≥ 50) and **notable scholars** (h-index ≥ 25) who cite your work
- LLM-powered honor tag enrichment — detects IEEE Fellow, ACM Fellow, 院士 among your citers
- Per-paper citation drill-down with context snippets

### Growth Tracking

- Daily metric snapshots: citations, h-index, stars, forks, downloads, likes
- Interactive trend charts with 30/60/90/365-day windows
- Milestone system: automatic achievements when you hit thresholds (100 citations, 1K stars, etc.)

### Web Buzz Monitoring

- Perplexity-powered web search to gauge your research visibility
- Heat level classification (hot / medium / cold) with source links

### AI-Powered Summary

- LLM-generated researcher bio capturing your research identity
- Auto-generated research tags from your publication topics

### Grant Application Tools

- **Research Basis Generator** (研究基础) for NSFC, Changjiang, Wanren, and other Chinese grant types
- Tone-adaptive formatting: "potential + feasibility" for youth grants vs. "originality + leadership" for senior grants
- Paper selection UI with evidence preview (citation analysis + notable scholars + linked repos)

### Smart Export

- Paper list export: Markdown, BibTeX, JSON
- Filter by year, CCF rank, citation count, first-author
- Comprehensive CV-style summary JSON

### Auto Refresh

- Background scheduler refreshes all data every 6 hours
- Manual refresh on demand via API

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- An OpenAI-compatible API key (for AI summary & buzz features)

### 1. Backend

```bash
cd backend
pip install -r requirements.txt

# Create .env from template
cp ../.env.example .env
# Edit .env and fill in your API key

python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

### 2. Frontend

```bash
cd frontend
npm install

# Development
npm run dev

# Production build (served by backend)
npm run build
```

### 3. One-Command Serve (optional)

```bash
# Serves frontend dist/ + proxies /api to backend
python serve.py 19487
```

Open `http://localhost:19487` and enter your Semantic Scholar ID to get started.

---

## Configuration

Copy `.env.example` to `backend/.env`:

| Variable | Description | Required |
|----------|-------------|----------|
| `LLM_API_BASE` | OpenAI-compatible API endpoint | Yes |
| `LLM_API_KEY` | API key for the LLM provider | Yes |
| `LLM_BUZZ_MODEL` | Model for buzz & summary generation (default: `gpt-5`) | No |
| `OUTBOUND_PROXY` | HTTP proxy for outbound API calls | No |
| `GITHUB_TOKEN` | GitHub PAT for higher rate limits | No |

---

## Architecture

```
impacthub/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry + static file serving
│   │   ├── config.py            # Environment & constants
│   │   ├── models.py            # SQLAlchemy ORM
│   │   ├── schemas.py           # Pydantic schemas
│   │   ├── routers/
│   │   │   ├── profile.py       # Profile CRUD & account linking
│   │   │   ├── stats.py         # Aggregated statistics
│   │   │   ├── citations.py     # Citation analysis & scholar classification
│   │   │   ├── growth.py        # Growth snapshots & trends
│   │   │   ├── milestones.py    # Achievement tracking
│   │   │   ├── buzz.py          # Web presence monitoring
│   │   │   ├── ai_summary.py    # LLM-generated bios & tags
│   │   │   ├── reports.py       # Grant research basis generator
│   │   │   └── data.py          # Export endpoints
│   │   ├── services/            # Business logic per domain
│   │   └── tasks/
│   │       └── scheduler.py     # APScheduler (6h refresh cycle)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/               # Setup, Profile, Milestone, Users
│   │   ├── components/          # Charts, cards, modals, exporters
│   │   └── lib/                 # API client, utils, venue data
│   └── package.json
└── serve.py                     # Simple dev proxy server
```

**Tech Stack**: FastAPI + SQLAlchemy + aiosqlite | React 19 + Tailwind CSS 4 + Recharts | Semantic Scholar + GitHub + Hugging Face APIs

---

## License

MIT

---

# 🇨🇳 中文说明

## 产品介绍

**ImpactHub** 是一个统一的科研影响力仪表盘，将你在 **Semantic Scholar**、**GitHub** 和 **Hugging Face** 上的学术成果整合到一个页面中，帮助你了解自己的学术影响力并辅助基金申请。

## 核心功能

### 跨平台个人主页

输入 Semantic Scholar ID，系统自动发现并关联你的 GitHub 和 Hugging Face 账号，一站式展示论文、代码仓库和模型。

### 引用分析

- 自动计算 H-index，按 CCF-A/B/C 分类期刊/会议
- 识别引用你论文的**顶尖学者**（h-index ≥ 50）和**知名学者**（h-index ≥ 25）
- LLM 驱动的荣誉标签识别 — 检测引用者中的 IEEE Fellow、ACM Fellow、院士等头衔
- 逐篇论文的引用详情，包含引用上下文片段

### 增长追踪

- 每日指标快照：引用数、h-index、Star 数、Fork 数、下载量、点赞数
- 可交互趋势图，支持 30/60/90/365 天窗口
- 里程碑系统：达到阈值自动触发成就（100 次引用、1K Star 等）

### 网络热度监测

- 基于 Perplexity 的网络搜索，评估你的研究可见度
- 热度分级（热门 / 一般 / 冷门），附来源链接

### AI 摘要

- LLM 生成的研究者简介，捕捉你的科研画像
- 基于论文主题自动生成研究标签

### 基金申请工具

- **研究基础生成器**：支持国自然（青年/面上/优青/杰青/重点）、长江学者、万人计划等
- 自适应语气：青年项目强调"潜力+可行性"，资深项目强调"原创性+引领性"
- 论文选择界面，预览引用分析 + 知名学者背书 + 关联代码仓库

### 智能导出

- 论文列表导出：Markdown、BibTeX、JSON
- 按年份、CCF 等级、引用数、一作筛选
- 完整 CV 风格的汇总 JSON

### 自动刷新

- 后台调度器每 6 小时自动刷新所有数据
- 支持手动触发即时刷新

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- OpenAI 兼容的 API Key（用于 AI 摘要和热度功能）

### 后端

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example .env
# 编辑 .env，填入你的 API Key
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

### 前端

```bash
cd frontend
npm install
npm run build    # 生产构建，由后端静态服务
# 或
npm run dev      # 开发模式，热重载
```

### 一键启动（可选）

```bash
python serve.py 19487
```

打开 `http://localhost:19487`，输入你的 Semantic Scholar ID 即可开始使用。

## 环境变量

将 `.env.example` 复制到 `backend/.env` 并填写：

| 变量 | 说明 | 必填 |
|------|------|------|
| `LLM_API_BASE` | OpenAI 兼容的 API 地址 | 是 |
| `LLM_API_KEY` | LLM 服务的 API Key | 是 |
| `LLM_BUZZ_MODEL` | 热度/摘要生成模型（默认 `gpt-5`） | 否 |
| `OUTBOUND_PROXY` | 出站 HTTP 代理 | 否 |
| `GITHUB_TOKEN` | GitHub 个人访问令牌（提高 API 速率限制） | 否 |
