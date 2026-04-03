"""Generate grant application documents: NSFC research basis, Changjiang Scholar,
Wanren Plan, Youth Support, etc.  Each grant type has its own Markdown format."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Paper, GithubRepo, HFItem, CitationAnalysis, NotableCitation

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Grant type configuration
# ---------------------------------------------------------------------------

GRANT_TYPES: dict[str, dict] = {
    # ===== NSFC (国自然) =====
    "youth_c": {
        "name": "青年科学基金（C类）",
        "tone": "潜力+可行",
        "desc": "侧重具体技术点的验证，强调模型/代码「好用」「被复现」",
        "impact_priority": ["opensource", "downloads", "citations", "notable_scholars"],
        "closing": "上述工作为本项目提供了成熟可靠的技术底座，大幅降低了项目实施风险。",
        "format": "nsfc_basis",
        "group": "nsfc",
    },
    "youth_b": {
        "name": "优秀青年基金（B类/优青）",
        "tone": "特色+标签",
        "desc": "侧重方向的代表性，强调不可替代性和辨识度",
        "impact_priority": ["citations", "notable_scholars", "opensource", "downloads"],
        "closing": "上述系列工作确立了申请人在该细分方向的领先地位和鲜明学术标签。",
        "format": "nsfc_basis",
        "group": "nsfc",
    },
    "youth_a": {
        "name": "杰出青年基金（A类/杰青）",
        "tone": "引领+体系",
        "desc": "侧重体系的完整性，强调开创新方向、国际引领",
        "impact_priority": ["notable_scholars", "citations", "opensource", "downloads"],
        "closing": "上述工作构建了从理论到应用的完整学术体系，为本项目的深入推进奠定了坚实基础。",
        "format": "nsfc_basis",
        "group": "nsfc",
    },
    "overseas": {
        "name": "海外优秀青年（B类海外）",
        "tone": "衔接+落地",
        "desc": "侧重国际前沿与国内落地的结合",
        "impact_priority": ["citations", "opensource", "downloads", "notable_scholars"],
        "closing": "上述海外期间积累的前沿成果已具备国内落地条件，为本项目的实施提供了高起点的技术储备。",
        "format": "nsfc_basis",
        "group": "nsfc",
    },
    "general": {
        "name": "面上项目",
        "tone": "积累+创新",
        "desc": "侧重积累的厚度与创新的逻辑，强调前期工作与本项目的逻辑链条",
        "impact_priority": ["citations", "notable_scholars", "opensource", "downloads"],
        "closing": "上述长期系列研究为本项目提供了扎实的理论与数据基础，确保了技术路线的可行性。",
        "format": "nsfc_basis",
        "group": "nsfc",
    },
    "key_project": {
        "name": "重点项目",
        "tone": "重大需求+攻关",
        "desc": "侧重国家需求与实际贡献，强调解决关键瓶颈",
        "impact_priority": ["notable_scholars", "citations", "opensource", "downloads"],
        "closing": "上述工作直接服务于国家重大需求，为本项目攻克关键科学问题提供了有力支撑。",
        "format": "nsfc_basis",
        "group": "nsfc",
    },
    # ===== 人才计划 =====
    "changjiang_youth": {
        "name": "长江青年学者",
        "tone": "潜力+国际前沿",
        "desc": "论文情况表格（含收录及他引）+ 主要学术贡献叙述（限三页）",
        "impact_priority": ["citations", "notable_scholars", "opensource", "downloads"],
        "closing": "综上，申请人已具备扎实的研究基础和突出的创新能力，具有成长为该领域领军人才的潜力。",
        "format": "changjiang_youth",
        "group": "talent",
    },
    "changjiang": {
        "name": "长江学者",
        "tone": "原创性+引领性",
        "desc": "主要学术成绩（800-1500字综述）+ 代表性成果（5-8项，含标志性意义）",
        "impact_priority": ["notable_scholars", "citations", "opensource", "downloads"],
        "closing": "申请人已从跟随者成长为该方向国际公认的领军人物，显著提升了我国在该领域的国际话语权。",
        "format": "changjiang",
        "group": "talent",
    },
    "youth_support": {
        "name": "青年人才托举",
        "tone": "创新能力+潜力",
        "desc": "论文情况表格 + 300字以内科研能力简述",
        "impact_priority": ["citations", "opensource", "notable_scholars", "downloads"],
        "closing": "申请人致力于引领我国在该领域实现国际领跑。",
        "format": "youth_support",
        "group": "talent",
    },
    "wanren": {
        "name": "万人计划（科技创新领军）",
        "tone": "国家需求+自主可控",
        "desc": "2-3项主要创新成果（各800-1000字），强调自主可控与卡脖子突破",
        "impact_priority": ["notable_scholars", "citations", "opensource", "downloads"],
        "closing": "上述成果直接服务于国家重大战略需求，实现了关键核心技术的自主可控。",
        "format": "wanren",
        "group": "talent",
    },
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PaperEvidence:
    paper: Paper
    citation_analysis: CitationAnalysis | None = None
    notable_citations: list[NotableCitation] = field(default_factory=list)
    repos: list[GithubRepo] = field(default_factory=list)
    hf_items: list[HFItem] = field(default_factory=list)


@dataclass
class PaperInput:
    """User-provided per-paper metadata."""
    paper_id: int
    scientific_question: str = ""
    innovation_summary: str = ""
    relevance: str = ""
    linked_repo_ids: list[int] = field(default_factory=list)
    linked_hf_item_ids: list[int] = field(default_factory=list)


@dataclass
class _UserStats:
    """Aggregated user stats for summary sections."""
    paper_count: int = 0
    total_citations: int = 0
    h_index: int = 0
    ccf_a: int = 0
    ccf_b: int = 0
    ccf_c: int = 0
    total_stars: int = 0
    total_forks: int = 0
    total_downloads: int = 0
    total_hf_likes: int = 0
    repo_count: int = 0
    hf_count: int = 0


# ---------------------------------------------------------------------------
# Evidence collection
# ---------------------------------------------------------------------------

async def collect_paper_evidence(
    db: AsyncSession,
    paper_id: int,
    user_id: int,
    repo_ids: list[int] | None = None,
    hf_item_ids: list[int] | None = None,
) -> PaperEvidence | None:
    """Collect all available evidence for a single paper."""
    paper = await db.get(Paper, paper_id)
    if not paper or paper.user_id != user_id:
        return None

    ca = (await db.execute(
        select(CitationAnalysis).where(CitationAnalysis.paper_id == paper_id)
    )).scalars().first()

    ncs_all = (await db.execute(
        select(NotableCitation)
        .where(NotableCitation.paper_id == paper_id, NotableCitation.user_id == user_id)
        .order_by(NotableCitation.author_h_index.desc())
    )).scalars().all()

    honored = [nc for nc in ncs_all if nc.honor_tags]
    rest = [nc for nc in ncs_all if not nc.honor_tags]
    notable_sorted = honored + rest

    repos: list[GithubRepo] = []
    if repo_ids:
        for rid in repo_ids:
            r = await db.get(GithubRepo, rid)
            if r and r.user_id == user_id:
                repos.append(r)

    hf_items: list[HFItem] = []
    if hf_item_ids:
        for hid in hf_item_ids:
            h = await db.get(HFItem, hid)
            if h and h.user_id == user_id:
                hf_items.append(h)

    return PaperEvidence(
        paper=paper,
        citation_analysis=ca,
        notable_citations=notable_sorted[:10],
        repos=repos,
        hf_items=hf_items,
    )


# ---------------------------------------------------------------------------
# Aggregate stats helper
# ---------------------------------------------------------------------------

async def _aggregate_user_stats(db: AsyncSession, user_id: int) -> _UserStats:
    from app.utils.paper_dedup import deduplicate_papers

    all_papers_raw = (await db.execute(
        select(Paper).where(Paper.user_id == user_id).order_by(Paper.citation_count.desc())
    )).scalars().all()
    papers = deduplicate_papers(all_papers_raw)
    repos = (await db.execute(
        select(GithubRepo).where(GithubRepo.user_id == user_id)
    )).scalars().all()
    hf_items = (await db.execute(
        select(HFItem).where(HFItem.user_id == user_id)
    )).scalars().all()

    total_cit = sum(p.citation_count for p in papers)
    cits = sorted([p.citation_count for p in papers], reverse=True)
    h_index = 0
    for i, c in enumerate(cits):
        if c >= i + 1:
            h_index = i + 1
        else:
            break

    return _UserStats(
        paper_count=len(papers),
        total_citations=total_cit,
        h_index=h_index,
        ccf_a=sum(1 for p in papers if p.ccf_rank == "A"),
        ccf_b=sum(1 for p in papers if p.ccf_rank == "B"),
        ccf_c=sum(1 for p in papers if p.ccf_rank == "C"),
        total_stars=sum(r.stars for r in repos),
        total_forks=sum(r.forks for r in repos),
        total_downloads=sum(h.downloads for h in hf_items),
        total_hf_likes=sum(h.likes for h in hf_items),
        repo_count=len(repos),
        hf_count=len(hf_items),
    )


# ---------------------------------------------------------------------------
# Evidence chain bullet generation
# ---------------------------------------------------------------------------

def _build_evidence_bullets(ev: PaperEvidence, grant_config: dict) -> list[str]:
    """Generate 'evidence chain' style bullets from paper evidence."""
    tagged: list[tuple[str, str]] = []
    paper = ev.paper
    ca = ev.citation_analysis
    current_year = datetime.now().year
    paper_age = current_year - (paper.year or current_year)

    # --- Citation evidence ---
    if paper.citation_count > 0:
        venue_tag = paper.venue or ""
        if paper.ccf_rank:
            venue_tag += f"（CCF-{paper.ccf_rank}）"

        if paper_age <= 2 and paper.citation_count >= 20:
            temporal = (f"发表仅 {paper_age} 年已被引 {paper.citation_count} 次，"
                        f"在同细分方向年度论文中位列前列，显示出极高的实用价值和社区关注度")
        elif paper_age >= 4 and paper.citation_count >= 50:
            temporal = (f"连续 {paper_age} 年保持稳定的引用增长，累计被引 {paper.citation_count} 余次，"
                        f"表明其并非短期热点，而是成为了同行长期依赖的基础工具，具备极高的方法学稳定性")
        elif paper.citation_count >= 10:
            temporal = f"已被引 {paper.citation_count} 次，得到同行广泛认可"
        else:
            temporal = f"被引 {paper.citation_count} 次"

        base = f"该成果发表于 {venue_tag}，{temporal}"

        honored = [nc for nc in ev.notable_citations if nc.honor_tags]
        if honored:
            top_nc = honored[0]
            honor_str = "、".join(top_nc.honor_tags) if isinstance(top_nc.honor_tags, list) else str(top_nc.honor_tags)
            context_snippet = ""
            contexts = top_nc.contexts_json if isinstance(top_nc.contexts_json, list) else []
            if contexts:
                ctx = contexts[0]
                if len(ctx) > 80:
                    ctx = ctx[:77] + "..."
                context_snippet = f"（\"{ctx}\"）"
            base += (f"。其中包括 {top_nc.author_name}（{honor_str}，h-index {top_nc.author_h_index}）"
                     f"团队在 {top_nc.citing_paper_venue} 上的正面引用{context_snippet}，"
                     f"证明其理论先进性获顶尖同行认可")
        elif ev.notable_citations:
            top_nc = ev.notable_citations[0]
            if top_nc.author_h_index >= 50:
                base += (f"。其中包括 {top_nc.author_name}（h-index {top_nc.author_h_index}）"
                         f"等顶尖学者的引用，证明其方法受到权威同行关注")
            elif ca and ca.top_scholar_count > 0:
                base += f"。其中 {ca.top_scholar_count} 次引用来自 h-index≥50 的顶尖学者"

        tagged.append(("citations", base + "。"))

    # --- Notable scholars summary ---
    if ca and (ca.top_scholar_count or 0) + (ca.notable_scholar_count or 0) > 5:
        total_notable = (ca.top_scholar_count or 0) + (ca.notable_scholar_count or 0)
        tagged.append(("notable_scholars",
            f"该工作共吸引了 {total_notable} 位知名学者（h-index≥25）的引用关注，"
            f"其中 {ca.top_scholar_count or 0} 位为顶尖学者（h-index≥50），"
            f"显示出极强的学术影响力和方法通用性。"))

    # --- Open-source evidence ---
    for repo in ev.repos:
        if repo.stars >= 10:
            forks_text = f"、被 Fork {repo.forks} 次" if repo.forks >= 10 else ""
            tagged.append(("opensource",
                f"相关代码已开源（GitHub Stars {repo.stars}+{forks_text}），"
                f"验证了其工程落地能力和可复现性。"))
            break

    # --- HuggingFace evidence ---
    for hf in ev.hf_items:
        if hf.downloads >= 50:
            type_label = "预训练模型" if hf.item_type == "model" else "数据集"
            tagged.append(("downloads",
                f"该{type_label}在 HuggingFace 平台累计下载超 {hf.downloads:,} 次"
                + (f"、获赞 {hf.likes}" if hf.likes >= 10 else "")
                + f"，验证了其泛化能力与鲁棒性。"))
            break

    # Reorder by grant priority
    priority = grant_config.get("impact_priority", [])
    priority_map = {cat: i for i, cat in enumerate(priority)}
    tagged.sort(key=lambda item: priority_map.get(item[0], 99))
    return [text for _, text in tagged]


def _evidence_to_narrative(bullets: list[str]) -> str:
    """Convert bullet list into a single flowing paragraph."""
    if not bullets:
        return ""
    # Remove trailing periods to join, then add final period
    parts = [b.rstrip("。").rstrip(".") for b in bullets]
    return "；".join(parts) + "。"


def _author_str(paper: Paper, limit: int = 5) -> str:
    authors = paper.authors_json if isinstance(paper.authors_json, list) else []
    s = ", ".join(authors[:limit])
    if len(authors) > limit:
        s += f" 等 {len(authors)} 人"
    return s


# ---------------------------------------------------------------------------
# Format router
# ---------------------------------------------------------------------------

async def generate_research_basis(
    db: AsyncSession,
    user_id: int,
    grant_type: str,
    project_title: str,
    paper_inputs: list[PaperInput],
) -> str:
    """Route to format-specific generator based on grant type."""
    config = GRANT_TYPES.get(grant_type, GRANT_TYPES["general"])
    fmt = config.get("format", "nsfc_basis")

    if fmt == "changjiang_youth":
        return await _gen_changjiang_youth(db, user_id, config, paper_inputs)
    elif fmt == "changjiang":
        return await _gen_changjiang(db, user_id, config, paper_inputs)
    elif fmt == "youth_support":
        return await _gen_youth_support(db, user_id, config, paper_inputs)
    elif fmt == "wanren":
        return await _gen_wanren(db, user_id, config, paper_inputs)
    else:
        return await _gen_nsfc_basis(db, user_id, config, project_title, paper_inputs)


# ===========================================================================
# NSFC: 研究基础与可行性分析 (original format, unchanged)
# ===========================================================================

async def _gen_nsfc_basis(
    db: AsyncSession, user_id: int, config: dict,
    project_title: str, paper_inputs: list[PaperInput],
) -> str:
    from app.models import User
    user = await db.get(User, user_id)
    if not user:
        return "# 错误：用户不存在"

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = [
        "# 研究基础与可行性分析",
        "",
        f"> 申报类型：{config['name']} | 核心逻辑：{config['tone']}",
    ]
    if project_title:
        lines.append(f"> 项目名称：{project_title}")
    lines.append(f"> 生成时间：{now_str}")
    lines += ["", "---", ""]

    for idx, pi in enumerate(paper_inputs, 1):
        ev = await collect_paper_evidence(
            db, pi.paper_id, user_id, pi.linked_repo_ids, pi.linked_hf_item_ids
        )
        if not ev:
            lines.append(f"## {idx}. ⚠️ 论文 ID {pi.paper_id} 未找到\n")
            continue

        paper = ev.paper
        question = pi.scientific_question or "[待填写：本项目关键科学问题]"
        innovation = pi.innovation_summary or "[待填写：该工作的核心创新点]"
        relevance = pi.relevance or "[待填写：该工作对本项目的具体支撑作用]"
        ccf_tag = f"CCF-{paper.ccf_rank}" if paper.ccf_rank else ""

        lines.append(f"## {idx}. 关于「{question}」的研究积累")
        lines.append("")
        lines.append(f"**【工作基础】** （代表作 {idx}）")
        lines.append("")
        venue_display = paper.venue or ""
        if ccf_tag:
            venue_display += f" ({ccf_tag})"
        lines.append(f"- {paper.title}")
        lines.append(f"- {_author_str(paper)}")
        lines.append(f"- {venue_display}, {paper.year} | 被引 {paper.citation_count}")
        if paper.url:
            lines.append(f"- URL: {paper.url}")
        lines.append("")

        lines.append(f"**【创新与突破】** {innovation}")
        lines.append("")

        bullets = _build_evidence_bullets(ev, config)
        if bullets:
            lines.append("**【学术影响力】**（融入式写法）：")
            lines.append("")
            for b in bullets:
                lines.append(f"- {b}")
            lines.append("")
        else:
            lines.append("**【学术影响力】** [引用分析数据暂缺，运行引用分析后可自动生成证据链]")
            lines.append("")

        lines.append(f"**【对本项目的支撑】** {relevance}")
        lines += ["", "---", ""]

    # Summary
    stats = await _aggregate_user_stats(db, user_id)
    lines.append("## 整体研究基础总结")
    lines.append("")
    summary_parts = [f"申请人已发表论文 {stats.paper_count} 篇，总引用 {stats.total_citations:,} 次，h-index {stats.h_index}"]
    if stats.ccf_a or stats.ccf_b:
        summary_parts.append(f"其中 CCF-A {stats.ccf_a} 篇、CCF-B {stats.ccf_b} 篇")
    if stats.total_stars > 0:
        summary_parts.append(f"开源代码获 GitHub Stars {stats.total_stars:,}+")
    if stats.total_downloads > 0:
        summary_parts.append(f"模型/数据集下载超 {stats.total_downloads:,} 次")
    lines.append("。".join(summary_parts) + "。")
    lines += ["", config["closing"], ""]

    return "\n".join(lines)


# ===========================================================================
# 长江青年学者: 论文情况表格 + 学术贡献叙述
# ===========================================================================

async def _gen_changjiang_youth(
    db: AsyncSession, user_id: int, config: dict,
    paper_inputs: list[PaperInput],
) -> str:
    from app.models import User
    user = await db.get(User, user_id)
    if not user:
        return "# 错误：用户不存在"

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    stats = await _aggregate_user_stats(db, user_id)

    lines: list[str] = [
        "# 长江青年学者候选人推荐表",
        "",
        f"> 候选人：{user.name} | 生成时间：{now_str}",
        "",
        "---",
        "",
        "## 一、论文情况",
        "",
        "| 序号 | 论文题目 | 作者 | 代表性 | 期刊/会议名称 | 发表年度 | CCF等级 | 他引次数 |",
        "| :--: | :------- | :--- | :----: | :------------ | :------: | :-----: | -------: |",
    ]

    evidences: list[tuple[PaperInput, PaperEvidence | None]] = []
    for idx, pi in enumerate(paper_inputs, 1):
        ev = await collect_paper_evidence(
            db, pi.paper_id, user_id, pi.linked_repo_ids, pi.linked_hf_item_ids
        )
        evidences.append((pi, ev))
        if not ev:
            lines.append(f"| {idx} | ⚠️ 未找到 | — | — | — | — | — | — |")
            continue
        p = ev.paper
        is_representative = "★" if pi.scientific_question or pi.innovation_summary else ""
        ccf = f"CCF-{p.ccf_rank}" if p.ccf_rank else "—"
        lines.append(
            f"| {idx} | {p.title} | {_author_str(p, 3)} | {is_representative} | "
            f"{p.venue or '—'} | {p.year} | {ccf} | {p.citation_count} |"
        )

    lines += ["", "---", ""]

    # Section 2: 主要学术贡献
    lines.append("## 二、候选人主要学术贡献、重要创新成果及其科学价值（近五年为主）")
    lines.append("")

    # Opening paragraph
    lines.append(
        f"申请人长期致力于相关领域研究，已发表论文 {stats.paper_count} 篇，"
        f"总引用 {stats.total_citations:,} 次，h-index {stats.h_index}"
        + (f"，其中 CCF-A {stats.ccf_a} 篇、CCF-B {stats.ccf_b} 篇" if stats.ccf_a or stats.ccf_b else "")
        + (f"。开源代码获 GitHub Stars {stats.total_stars:,}+" if stats.total_stars else "")
        + (f"，模型/数据集下载超 {stats.total_downloads:,} 次" if stats.total_downloads else "")
        + "。主要学术贡献如下："
    )
    lines.append("")

    # Per-paper contribution paragraph
    contribution_num = 0
    for pi, ev in evidences:
        if not ev:
            continue
        contribution_num += 1
        paper = ev.paper
        innovation = pi.innovation_summary or "[待填写：该工作的核心创新点]"
        question = pi.scientific_question or "[待填写：解决的科学问题]"

        lines.append(f"**（{contribution_num}）{question}**")
        lines.append("")

        ccf_tag = f"（CCF-{paper.ccf_rank}）" if paper.ccf_rank else ""
        lines.append(
            f"针对上述问题，申请人提出了创新性解决方案（代表作：{paper.title}，"
            f"发表于 {paper.venue}{ccf_tag}，{paper.year}）。{innovation}"
        )

        # Evidence as narrative
        bullets = _build_evidence_bullets(ev, config)
        if bullets:
            narrative = _evidence_to_narrative(bullets)
            lines.append(f"学术影响方面，{narrative}")
        lines.append("")

    # Closing
    lines.append(config["closing"])
    lines.append("")

    return "\n".join(lines)


# ===========================================================================
# 长江学者: 主要学术成绩 (800-1500字) + 代表性成果 (5-8项)
# ===========================================================================

async def _gen_changjiang(
    db: AsyncSession, user_id: int, config: dict,
    paper_inputs: list[PaperInput],
) -> str:
    from app.models import User
    user = await db.get(User, user_id)
    if not user:
        return "# 错误：用户不存在"

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    stats = await _aggregate_user_stats(db, user_id)

    lines: list[str] = [
        "# 长江学者特聘教授申报材料",
        "",
        f"> 申请人：{user.name} | 生成时间：{now_str}",
        "",
        "---",
        "",
        "## 一、主要学术成绩（800-1500字）",
        "",
    ]

    # Opening paragraph — career overview
    overview_parts = [
        f"申请人长期致力于 [核心研究领域] 研究",
    ]
    if stats.ccf_a > 0:
        overview_parts.append(
            f"以第一/通讯作者在 CCF-A 类会议/期刊发表论文 {stats.ccf_a} 篇"
            + (f"（CCF-B {stats.ccf_b} 篇）" if stats.ccf_b else "")
        )
    overview_parts.append(f"总引用 {stats.total_citations:,} 次，h-index {stats.h_index}")
    if stats.total_stars > 100:
        overview_parts.append(f"主导的开源项目汇聚全球 {stats.total_stars:,}+ Star")
    if stats.total_downloads > 100:
        overview_parts.append(f"HuggingFace 累计下载超 {stats.total_downloads:,} 次")
    lines.append("，".join(overview_parts) + "。主要学术贡献如下：")
    lines.append("")

    # Per-paper detailed narrative sections
    evidences: list[tuple[PaperInput, PaperEvidence | None]] = []
    section_num = 0
    for pi in paper_inputs:
        ev = await collect_paper_evidence(
            db, pi.paper_id, user_id, pi.linked_repo_ids, pi.linked_hf_item_ids
        )
        evidences.append((pi, ev))
        if not ev:
            continue
        section_num += 1
        paper = ev.paper

        question = pi.scientific_question or "[待填写：关键科学问题]"
        innovation = pi.innovation_summary or "[待填写：核心创新点]"

        # Chinese numeral sections
        cn_nums = ["一", "二", "三", "四", "五", "六", "七", "八"]
        cn = cn_nums[section_num - 1] if section_num <= len(cn_nums) else str(section_num)

        lines.append(f"**{cn}、{question}**")
        lines.append("")

        ccf_tag = f"（CCF-{paper.ccf_rank}）" if paper.ccf_rank else ""
        lines.append(
            f"针对 {question} 的难题，申请人提出了 {innovation}（代表作："
            f"{paper.title}，{paper.venue}{ccf_tag}，{paper.year}，被引 {paper.citation_count} 次）。"
        )

        # Evidence narrative — woven into paragraph
        bullets = _build_evidence_bullets(ev, config)
        if bullets:
            lines.append(_evidence_to_narrative(bullets))

        # Relevance
        if pi.relevance:
            lines.append(f"该工作 {pi.relevance}。")
        lines.append("")

    # Closing
    lines.append(config["closing"])
    lines += ["", "---", ""]

    # Section 2: 代表性成果
    lines.append(f"## 二、代表性成果（限 5-8 项，共 {len(paper_inputs)} 项）")
    lines.append("")

    result_num = 0
    for pi, ev in evidences:
        if not ev:
            continue
        result_num += 1
        paper = ev.paper
        innovation = pi.innovation_summary or "[待填写]"
        question = pi.scientific_question or "[待填写]"

        ccf_tag = f"（CCF-{paper.ccf_rank}）" if paper.ccf_rank else ""
        lines.append(f"**成果{result_num}：{question}**")
        lines.append("")
        lines.append(f"- **代表作**：{paper.title}")
        lines.append(f"- **发表载体**：{paper.venue}{ccf_tag}，{paper.year}")
        lines.append(f"- **作者**：{_author_str(paper)}")
        lines.append(f"- **被引次数**：{paper.citation_count}")
        lines.append(f"- **创新总结**：{innovation}")

        # Significance summary
        bullets = _build_evidence_bullets(ev, config)
        if bullets:
            significance = _evidence_to_narrative(bullets)
            lines.append(f"- **标志性意义**：{significance}")
        else:
            lines.append("- **标志性意义**：[待补充证据链——请先运行引用分析]")

        # Repos/HF
        for repo in ev.repos:
            lines.append(f"- **开源**：GitHub {repo.repo_name}（Stars {repo.stars}+）")
        for hf in ev.hf_items:
            type_label = "模型" if hf.item_type == "model" else "数据集"
            lines.append(f"- **{type_label}**：HuggingFace {hf.item_id}（下载 {hf.downloads:,}）")
        lines.append("")

    return "\n".join(lines)


# ===========================================================================
# 青年人才托举: 论文表格 + 300字能力简述
# ===========================================================================

async def _gen_youth_support(
    db: AsyncSession, user_id: int, config: dict,
    paper_inputs: list[PaperInput],
) -> str:
    from app.models import User
    user = await db.get(User, user_id)
    if not user:
        return "# 错误：用户不存在"

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    stats = await _aggregate_user_stats(db, user_id)

    lines: list[str] = [
        "# 青年人才托举工程申报材料",
        "",
        f"> 申请人：{user.name} | 生成时间：{now_str}",
        "",
        "---",
        "",
        "## 一、论文情况",
        "",
        "| 序号 | 论文、论著名称 | 年份 | 排名 | 发表刊物或出版社名称 | 是否被三大检索收录 | 被引用次数 |",
        "| :--: | :------------- | :--: | :--: | :------------------- | :----------------: | ---------: |",
    ]

    all_evidence_bullets: list[str] = []
    for idx, pi in enumerate(paper_inputs, 1):
        ev = await collect_paper_evidence(
            db, pi.paper_id, user_id, pi.linked_repo_ids, pi.linked_hf_item_ids
        )
        if not ev:
            lines.append(f"| {idx} | ⚠️ 未找到 | — | — | — | — | — |")
            continue
        p = ev.paper
        authors = p.authors_json if isinstance(p.authors_json, list) else []
        # Guess author rank
        rank_str = "[待填写]"
        if user.name and authors:
            for i, a in enumerate(authors):
                if user.name.lower() in a.lower():
                    rank_str = f"第{i+1}作者" if i < 3 else "其他"
                    break

        ccf_tag = f"CCF-{p.ccf_rank}" if p.ccf_rank else ""
        index_str = ccf_tag if ccf_tag else "—"

        lines.append(
            f"| {idx} | {p.title} | {p.year} | {rank_str} | "
            f"{p.venue or '—'} | {index_str} | {p.citation_count} |"
        )

        bullets = _build_evidence_bullets(ev, config)
        all_evidence_bullets.extend(bullets)

    lines += ["", "---", ""]

    # 300-word summary
    lines.append("## 二、科研能力、创新能力及取得的科研进展或重要成果（300字以内）")
    lines.append("")

    # Paragraph 1: Innovation
    innovation_summaries = []
    for pi in paper_inputs:
        if pi.innovation_summary:
            innovation_summaries.append(pi.innovation_summary)
    if innovation_summaries:
        lines.append(
            f"申请人具备独立的原始创新与工程落地能力。"
            + "；".join(innovation_summaries[:3]) + "。"
        )
    else:
        lines.append(
            "申请人具备独立的原始创新与工程落地能力，[待填写：首创了XXX，突破了具体瓶颈]。"
        )

    # Paragraph 2: Impact
    impact_parts = []
    if stats.ccf_a > 0:
        impact_parts.append(f"以第一/通讯作者在 CCF-A 发表论文 {stats.ccf_a} 篇")
    impact_parts.append(f"总被引 {stats.total_citations:,} 次")
    if stats.h_index > 0:
        impact_parts.append(f"h-index {stats.h_index}")
    if stats.total_stars > 100:
        impact_parts.append(f"GitHub Star 超 {stats.total_stars:,}")
    if stats.total_downloads > 100:
        impact_parts.append(f"全球下载/调用 {stats.total_downloads:,} 次")
    lines.append(
        "学术影响力方面：" + "，".join(impact_parts) + "。"
    )

    # Paragraph 3: Application
    lines.append(
        "应用转化方面：[待填写：成果实现自主可控，部署于XX，效率提升XX%，产生经济效益XX]。"
    )
    lines.append("")
    lines.append(config["closing"])
    lines.append("")

    return "\n".join(lines)


# ===========================================================================
# 万人计划: 主要创新成果 (2-3项，各800-1000字)
# ===========================================================================

async def _gen_wanren(
    db: AsyncSession, user_id: int, config: dict,
    paper_inputs: list[PaperInput],
) -> str:
    from app.models import User
    user = await db.get(User, user_id)
    if not user:
        return "# 错误：用户不存在"

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    stats = await _aggregate_user_stats(db, user_id)

    lines: list[str] = [
        "# 万人计划（科技创新领军人才）申报材料",
        "",
        f"> 申请人：{user.name} | 生成时间：{now_str}",
        "",
        "---",
        "",
        "## 主要创新成果",
        "",
        f"> 共 {len(paper_inputs)} 项创新成果。每项应围绕关键核心技术突破展开，"
        f"体现「自主可控」和「解决卡脖子问题」。",
        "",
    ]

    cn_nums = ["一", "二", "三", "四", "五"]
    for idx, pi in enumerate(paper_inputs):
        ev = await collect_paper_evidence(
            db, pi.paper_id, user_id, pi.linked_repo_ids, pi.linked_hf_item_ids
        )
        if not ev:
            lines.append(f"### 创新成果{cn_nums[idx]}：⚠️ 论文未找到\n")
            continue

        paper = ev.paper
        question = pi.scientific_question or "[待填写：关键技术方向]"
        innovation = pi.innovation_summary or "[待填写：核心技术突破描述]"
        relevance = pi.relevance or "[待填写：应用场景与国家需求的对接]"

        ccf_tag = f"（CCF-{paper.ccf_rank}）" if paper.ccf_rank else ""

        lines.append(f"### 创新成果{cn_nums[idx]}：{question}")
        lines.append("")

        # 1. 技术突破
        lines.append("**一、核心技术突破**")
        lines.append("")
        lines.append(
            f"针对 {question} 领域长期存在的技术瓶颈，申请人首创了 {innovation}"
            f"（代表作：{paper.title}，发表于 {paper.venue}{ccf_tag}，{paper.year}）。"
            f"该成果突破了 [具体技术指标] 的理论极限，性能超越国际主流方案 [XX]%。"
        )
        lines.append("")

        # 2. 学术影响力 → 转化为"行业认可"口吻
        lines.append("**二、行业认可与生态影响**")
        lines.append("")

        bullets = _build_evidence_bullets(ev, config)
        if bullets:
            # Transform to wanren style
            impact_lines = []
            for b in bullets:
                impact_lines.append(f"- {b}")
            lines.extend(impact_lines)
        else:
            lines.append("- [待补充：运行引用分析后可自动生成影响力证据]")

        # Open source / HF as "ecosystem dominance"
        for repo in ev.repos:
            if repo.stars >= 10:
                lines.append(
                    f"- 相关技术已完全开源（GitHub Stars {repo.stars:,}+），"
                    f"形成了以我为核心的开源创新生态，被全球 [XX] 所顶尖机构广泛采用。"
                )
                break
        for hf in ev.hf_items:
            if hf.downloads >= 50:
                type_label = "模型" if hf.item_type == "model" else "数据集"
                lines.append(
                    f"- {type_label}在 HuggingFace 累计下载超 {hf.downloads:,} 次，"
                    f"已成为领域事实标准，掌握了国际评测话语权。"
                )
                break
        lines.append("")

        # 3. 国家需求 + 自主可控
        lines.append("**三、国家需求对接与自主可控**")
        lines.append("")
        lines.append(
            f"面向国家重大战略需求，{relevance}。"
            f"核心算法与数据 100% 自主可控，性能指标超越国外同类商用系统 [XX]%，"
            f"彻底解决了「卡脖子」隐患。成果已规模化部署于 [待填写：具体应用单位]，"
            f"将 [研发周期/生产效率] 提升 [XX]%，产生间接经济效益超 [X] 亿元。"
        )
        lines += ["", "---", ""]

    # Overall closing
    lines.append("## 总结")
    lines.append("")
    summary_parts = [f"申请人已发表论文 {stats.paper_count} 篇，总引用 {stats.total_citations:,} 次，h-index {stats.h_index}"]
    if stats.ccf_a or stats.ccf_b:
        summary_parts.append(f"CCF-A {stats.ccf_a} 篇、CCF-B {stats.ccf_b} 篇")
    if stats.total_stars > 0:
        summary_parts.append(f"开源代码获 Stars {stats.total_stars:,}+")
    if stats.total_downloads > 0:
        summary_parts.append(f"模型/数据集下载超 {stats.total_downloads:,} 次")
    lines.append("，".join(summary_parts) + "。")
    lines.append("")
    lines.append(config["closing"])
    lines.append("")

    return "\n".join(lines)
