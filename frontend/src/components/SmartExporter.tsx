import { useState, useEffect, useCallback } from "react";
import {
  api,
  type Paper,
  type GithubRepo,
  type HFItem,
  type PaperReportResult,
  type GrantTypeInfo,
  type PaperEvidenceOut,
  type PaperSelectionIn,
} from "@/lib/api";
import { formatNumber } from "@/lib/utils";
import {
  FileDown,
  FileText,
  BookOpen,
  Award,
  GraduationCap,
  SlidersHorizontal,
  Loader2,
  Download,
  ChevronRight,
  ChevronLeft,
  ChevronDown,
  ChevronUp,
  Check,
  Copy,
  Globe,
  Briefcase,
  Zap,
  Star,
  Sparkles,
  Trophy,
  GitFork,
  AlertCircle,
  Crown,
  Flame,
  Users,
  Medal,
} from "lucide-react";

interface Props {
  userId: string;
  papers?: Paper[];
  repos?: GithubRepo[];
  hfItems?: HFItem[];
}

// ----- Grant type icons + colors -----
const grantMeta: Record<string, { icon: typeof BookOpen; color: string }> = {
  // NSFC
  youth_c: { icon: GraduationCap, color: "blue" },
  youth_b: { icon: Award, color: "violet" },
  youth_a: { icon: Trophy, color: "amber" },
  overseas: { icon: Globe, color: "teal" },
  general: { icon: Briefcase, color: "gray" },
  key_project: { icon: Zap, color: "rose" },
  // Talent programs
  changjiang_youth: { icon: Medal, color: "emerald" },
  changjiang: { icon: Crown, color: "amber" },
  youth_support: { icon: Flame, color: "cyan" },
  wanren: { icon: Users, color: "rose" },
};

const colorMap: Record<string, { bg: string; border: string; text: string; icon: string }> = {
  blue: { bg: "bg-blue-50", border: "border-blue-200", text: "text-blue-700", icon: "text-blue-500" },
  violet: { bg: "bg-violet-50", border: "border-violet-200", text: "text-violet-700", icon: "text-violet-500" },
  amber: { bg: "bg-amber-50", border: "border-amber-200", text: "text-amber-700", icon: "text-amber-500" },
  teal: { bg: "bg-teal-50", border: "border-teal-200", text: "text-teal-700", icon: "text-teal-500" },
  gray: { bg: "bg-gray-50", border: "border-gray-200", text: "text-gray-700", icon: "text-gray-500" },
  rose: { bg: "bg-rose-50", border: "border-rose-200", text: "text-rose-700", icon: "text-rose-500" },
  indigo: { bg: "bg-indigo-50", border: "border-indigo-200", text: "text-indigo-700", icon: "text-indigo-500" },
  emerald: { bg: "bg-emerald-50", border: "border-emerald-200", text: "text-emerald-700", icon: "text-emerald-500" },
  cyan: { bg: "bg-cyan-50", border: "border-cyan-200", text: "text-cyan-700", icon: "text-cyan-500" },
};

// ----- Custom filter templates (old flow) -----
const currentYear = new Date().getFullYear();
const customTemplates = [
  { key: "nsfc", label: "国自然基金", desc: "近5年，CCF-A/B，引用≥10", icon: BookOpen, color: "indigo", filters: { yearFrom: currentYear - 5, yearTo: currentYear, ccfRanks: ["A", "B"], minCitations: 10, firstAuthor: "" } },
  { key: "talent", label: "重点人才计划", desc: "近3年，一作，CCF-A", icon: Award, color: "violet", filters: { yearFrom: currentYear - 3, yearTo: currentYear, ccfRanks: ["A"], minCitations: 0, firstAuthor: "" } },
  { key: "scholarship", label: "国家奖学金", desc: "近1年，全部论文", icon: GraduationCap, color: "amber", filters: { yearFrom: currentYear - 1, yearTo: currentYear, ccfRanks: [], minCitations: 0, firstAuthor: "" } },
];

// ----- Paper selection state -----
interface PaperMeta {
  paper: Paper;
  selected: boolean;
  expanded: boolean;
  evidence: PaperEvidenceOut | null;
  loadingEvidence: boolean;
  scientific_question: string;
  innovation_summary: string;
  relevance: string;
  linked_repo_ids: number[];
  linked_hf_item_ids: number[];
}

export default function SmartExporter({ userId, papers = [], repos = [], hfItems = [] }: Props) {
  // Mode: "grant" (research basis) or "custom" (old filter flow)
  const [mode, setMode] = useState<"grant" | "custom" | null>(null);
  const [step, setStep] = useState(1); // 1=select grant, 2=select papers, 3=preview

  // Grant type state
  const [grantTypes, setGrantTypes] = useState<GrantTypeInfo[]>([]);
  const [selectedGrant, setSelectedGrant] = useState<string>("");
  const [projectTitle, setProjectTitle] = useState("");

  // Paper selection state
  const [paperMetas, setPaperMetas] = useState<PaperMeta[]>([]);

  // Generation state
  const [generating, setGenerating] = useState(false);
  const [markdown, setMarkdown] = useState("");
  const [copied, setCopied] = useState(false);

  // Custom filter state (old flow)
  const [customTemplate, setCustomTemplate] = useState<string | null>(null);
  const [filters, setFilters] = useState({ yearFrom: 0, yearTo: 9999, ccfRanks: [] as string[], minCitations: 0, firstAuthor: "" });
  const [preview, setPreview] = useState<PaperReportResult | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);

  // Load grant types
  useEffect(() => {
    api.getGrantTypes().then(setGrantTypes).catch(() => {});
  }, []);

  // Initialize paper metas — only reset when the actual paper id list changes
  const paperIdKey = papers.map((p) => p.id).join(",");
  useEffect(() => {
    setPaperMetas((prev) => {
      const prevMap = new Map(prev.map((pm) => [pm.paper.id, pm]));
      return papers.map((p) => {
        const existing = prevMap.get(p.id);
        if (existing) return { ...existing, paper: p }; // preserve user state
        return {
          paper: p,
          selected: false,
          expanded: false,
          evidence: null,
          loadingEvidence: false,
          scientific_question: "",
          innovation_summary: "",
          relevance: "",
          linked_repo_ids: [],
          linked_hf_item_ids: [],
        };
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paperIdKey]);

  // Toggle paper selection
  const togglePaper = useCallback((paperId: number) => {
    setPaperMetas((prev) =>
      prev.map((pm) => (pm.paper.id === paperId ? { ...pm, selected: !pm.selected } : pm))
    );
  }, []);

  // Expand paper and load evidence
  const toggleExpand = useCallback(
    (paperId: number) => {
      setPaperMetas((prev) => {
        const target = prev.find((pm) => pm.paper.id === paperId);
        if (!target) return prev;
        const newExpanded = !target.expanded;
        const needLoad = newExpanded && !target.evidence && !target.loadingEvidence;
        if (needLoad) {
          // Kick off fetch outside of the updater via microtask
          queueMicrotask(() => {
            api.getPaperEvidence(userId, paperId).then((ev) => {
              setPaperMetas((p) =>
                p.map((pm) => (pm.paper.id === paperId ? { ...pm, evidence: ev, loadingEvidence: false } : pm))
              );
            }).catch(() => {
              setPaperMetas((p) =>
                p.map((pm) => (pm.paper.id === paperId ? { ...pm, loadingEvidence: false } : pm))
              );
            });
          });
        }
        return prev.map((pm) => {
          if (pm.paper.id !== paperId) return pm;
          return needLoad
            ? { ...pm, expanded: true, loadingEvidence: true }
            : { ...pm, expanded: newExpanded };
        });
      });
    },
    [userId]
  );

  // Update paper meta field
  const updatePaperMeta = useCallback((paperId: number, field: string, value: unknown) => {
    setPaperMetas((prev) =>
      prev.map((pm) => (pm.paper.id === paperId ? { ...pm, [field]: value } : pm))
    );
  }, []);

  // Generate research basis
  const handleGenerate = async () => {
    const selected = paperMetas.filter((pm) => pm.selected);
    if (selected.length === 0) return;
    setGenerating(true);
    try {
      const req = {
        grant_type: selectedGrant,
        project_title: projectTitle,
        papers: selected.map((pm): PaperSelectionIn => ({
          paper_id: pm.paper.id,
          scientific_question: pm.scientific_question,
          innovation_summary: pm.innovation_summary,
          relevance: pm.relevance,
          linked_repo_ids: pm.linked_repo_ids,
          linked_hf_item_ids: pm.linked_hf_item_ids,
        })),
      };
      const res = await api.generateResearchBasis(userId, req);
      setMarkdown(res.markdown);
      setStep(3);
    } catch (err: any) {
      alert(err?.message || "生成失败");
    } finally {
      setGenerating(false);
    }
  };

  // Download filename by grant type
  const downloadFilenames: Record<string, string> = {
    changjiang_youth: "长江青年学者-候选人推荐表.md",
    changjiang: "长江学者-学术成绩与代表性成果.md",
    youth_support: "青年人才托举-申报材料.md",
    wanren: "万人计划-主要创新成果.md",
  };

  // Download markdown
  const handleDownload = () => {
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = downloadFilenames[selectedGrant] || "研究基础与可行性分析.md";
    a.click();
    URL.revokeObjectURL(url);
  };

  // Copy to clipboard
  const handleCopy = async () => {
    await navigator.clipboard.writeText(markdown);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Custom filter flow
  const applyCustomTemplate = (key: string) => {
    setCustomTemplate(key);
    const tpl = customTemplates.find((t) => t.key === key);
    if (tpl) setFilters({ ...tpl.filters });
  };

  useEffect(() => {
    if (mode !== "custom" || !customTemplate) return;
    let cancelled = false;
    setLoadingPreview(true);
    const params: Record<string, unknown> = {};
    if (filters.yearFrom > 0) params.year_from = filters.yearFrom;
    if (filters.yearTo < 9999) params.year_to = filters.yearTo;
    if (filters.ccfRanks.length > 0) params.ccf_rank = filters.ccfRanks.join(",");
    if (filters.minCitations > 0) params.min_citations = filters.minCitations;
    if (filters.firstAuthor) params.first_author = filters.firstAuthor;
    api.getPaperReport(userId, params as Parameters<typeof api.getPaperReport>[1])
      .then((res) => { if (!cancelled) setPreview(res); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoadingPreview(false); });
    return () => { cancelled = true; };
  }, [userId, mode, customTemplate, filters]);

  const toggleCCF = (rank: string) => {
    setFilters((f) => ({
      ...f,
      ccfRanks: f.ccfRanks.includes(rank) ? f.ccfRanks.filter((r) => r !== rank) : [...f.ccfRanks, rank],
    }));
  };

  const buildDownloadUrl = (format: "markdown" | "bibtex") => {
    const sp = new URLSearchParams();
    if (filters.yearFrom > 0) sp.set("year_from", String(filters.yearFrom));
    if (filters.yearTo < 9999) sp.set("year_to", String(filters.yearTo));
    if (filters.ccfRanks.length > 0) sp.set("ccf_rank", filters.ccfRanks.join(","));
    if (filters.minCitations > 0) sp.set("min_citations", String(filters.minCitations));
    if (filters.firstAuthor) sp.set("first_author", filters.firstAuthor);
    sp.set("format", format);
    return `/api/report/${userId}/papers?${sp.toString()}`;
  };

  const selectedCount = paperMetas.filter((pm) => pm.selected).length;

  // Pagination for Step 2 paper list
  const PAGE_SIZE = 10;
  const [paperPage, setPaperPage] = useState(0);
  const totalPaperPages = Math.max(1, Math.ceil(paperMetas.length / PAGE_SIZE));
  const pagedPaperMetas = paperMetas.slice(paperPage * PAGE_SIZE, (paperPage + 1) * PAGE_SIZE);

  // ===== No mode selected =====
  if (!mode) {
    return (
      <div className="space-y-6">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-500">选择导出模式</h3>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {/* Research Basis mode */}
          <button
            onClick={() => { setMode("grant"); setStep(1); }}
            className="flex flex-col items-start rounded-xl border border-indigo-200 bg-gradient-to-br from-indigo-50 to-white p-6 text-left transition hover:shadow-md"
          >
            <Sparkles className="mb-3 h-6 w-6 text-indigo-500" />
            <span className="text-base font-bold text-gray-900">研究基础生成器</span>
            <span className="mt-1 text-sm text-gray-500">
              面向国自然申报，按基金类型生成"研究基础与可行性分析"段落，含融入式证据链
            </span>
            <span className="mt-3 rounded-full bg-indigo-100 px-2.5 py-0.5 text-xs font-medium text-indigo-600">
              推荐
            </span>
          </button>

          {/* Custom filter mode */}
          <button
            onClick={() => setMode("custom")}
            className="flex flex-col items-start rounded-xl border border-gray-200 bg-white p-6 text-left transition hover:shadow-md"
          >
            <SlidersHorizontal className="mb-3 h-6 w-6 text-gray-400" />
            <span className="text-base font-bold text-gray-900">论文列表导出</span>
            <span className="mt-1 text-sm text-gray-500">
              按年份、CCF、引用数筛选，导出 Markdown 或 BibTeX 论文列表
            </span>
          </button>
        </div>
      </div>
    );
  }

  // ===== Custom filter mode (old flow) =====
  if (mode === "custom") {
    return (
      <div className="space-y-6">
        <button onClick={() => setMode(null)} className="flex items-center gap-1 text-sm text-gray-400 hover:text-gray-600">
          <ChevronLeft className="h-3.5 w-3.5" /> 返回
        </button>
        <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-500">选择模板</h3>
        <div className="grid grid-cols-3 gap-3">
          {customTemplates.map((tpl) => {
            const c = colorMap[tpl.color] || colorMap.gray;
            const Icon = tpl.icon;
            const active = customTemplate === tpl.key;
            return (
              <button key={tpl.key} onClick={() => applyCustomTemplate(tpl.key)}
                className={`flex flex-col items-start rounded-xl border p-4 text-left transition hover-lift ${active ? `${c.bg} ${c.border} ring-2 ring-offset-1 ring-indigo-400` : "border-gray-100 bg-white hover:border-gray-200"}`}>
                <Icon className={`mb-2 h-5 w-5 ${active ? c.icon : "text-gray-400"}`} />
                <span className={`text-sm font-semibold ${active ? c.text : "text-gray-700"}`}>{tpl.label}</span>
                <span className="mt-0.5 text-xs text-gray-400">{tpl.desc}</span>
              </button>
            );
          })}
        </div>

        {customTemplate && (
          <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
            <h3 className="mb-4 text-sm font-semibold text-gray-700">筛选条件</h3>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <div>
                <label className="mb-1 block text-xs text-gray-500">起始年份</label>
                <input type="number" value={filters.yearFrom || ""} onChange={(e) => setFilters((f) => ({ ...f, yearFrom: Number(e.target.value) || 0 }))} placeholder="不限" className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-500">结束年份</label>
                <input type="number" value={filters.yearTo < 9999 ? filters.yearTo : ""} onChange={(e) => setFilters((f) => ({ ...f, yearTo: Number(e.target.value) || 9999 }))} placeholder="不限" className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-500">最低引用数</label>
                <input type="number" value={filters.minCitations || ""} onChange={(e) => setFilters((f) => ({ ...f, minCitations: Number(e.target.value) || 0 }))} placeholder="0" className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-500">一作关键词</label>
                <input type="text" value={filters.firstAuthor} onChange={(e) => setFilters((f) => ({ ...f, firstAuthor: e.target.value }))} placeholder="如 Zhang" className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
              </div>
            </div>
            <div className="mt-4">
              <label className="mb-1.5 block text-xs text-gray-500">CCF 等级</label>
              <div className="flex gap-2">
                {["A", "B", "C"].map((rank) => (
                  <button key={rank} onClick={() => toggleCCF(rank)}
                    className={`rounded-lg px-4 py-1.5 text-sm font-medium transition ${filters.ccfRanks.includes(rank) ? "bg-indigo-600 text-white" : "border border-gray-200 bg-white text-gray-500 hover:bg-gray-50"}`}>
                    CCF-{rank}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {customTemplate && (
          <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-gray-700">预览结果</h3>
              {loadingPreview && <Loader2 className="h-4 w-4 animate-spin text-indigo-500" />}
            </div>
            {preview && !loadingPreview && (
              <>
                <div className="mb-4 flex flex-wrap gap-3">
                  <StatBadge label="筛选论文" value={preview.summary.total} />
                  <StatBadge label="总引用" value={preview.summary.total_citations} />
                  <StatBadge label="CCF-A" value={preview.summary.ccf_a} />
                  <StatBadge label="CCF-B" value={preview.summary.ccf_b} />
                  <StatBadge label="CCF-C" value={preview.summary.ccf_c} />
                </div>
                {preview.papers.length > 0 ? (
                  <div className="max-h-80 space-y-2 overflow-y-auto">
                    {preview.papers.map((p, i) => (
                      <div key={i} className="rounded-lg border border-gray-50 bg-gray-50/50 px-3 py-2">
                        <div className="flex items-start gap-2">
                          <span className="mt-0.5 shrink-0 text-xs text-gray-400">{i + 1}.</span>
                          <div className="min-w-0 flex-1">
                            <div className="text-sm font-medium text-gray-800 line-clamp-2">{p.title}</div>
                            <div className="mt-0.5 flex flex-wrap gap-2 text-xs text-gray-400">
                              <span>{p.venue}</span><span>{p.year}</span><span>引用 {p.citation_count}</span>
                              {p.ccf_rank && <span className="rounded bg-indigo-100 px-1.5 text-indigo-600 font-medium">CCF-{p.ccf_rank}</span>}
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="py-8 text-center text-sm text-gray-400">没有符合条件的论文</p>
                )}
                {preview.papers.length > 0 && (
                  <div className="mt-4 flex gap-3">
                    <a href={buildDownloadUrl("markdown")} target="_blank" rel="noreferrer" className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-indigo-600 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-700">
                      <FileText className="h-4 w-4" /> 下载 Markdown
                    </a>
                    <a href={buildDownloadUrl("bibtex")} target="_blank" rel="noreferrer" className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-gray-200 bg-white py-2.5 text-sm font-semibold text-gray-700 transition hover:bg-gray-50">
                      <Download className="h-4 w-4" /> 下载 BibTeX
                    </a>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>
    );
  }

  // ===== Grant mode: Step 1 - Select grant type =====
  if (step === 1) {
    return (
      <div className="space-y-6">
        <button onClick={() => setMode(null)} className="flex items-center gap-1 text-sm text-gray-400 hover:text-gray-600">
          <ChevronLeft className="h-3.5 w-3.5" /> 返回
        </button>

        <div>
          <h3 className="mb-1 text-sm font-semibold uppercase tracking-wider text-gray-500">Step 1：选择申报类型</h3>
          <p className="text-xs text-gray-400">不同基金类型会生成不同语气和侧重的证据链</p>
        </div>

        {/* NSFC group */}
        {(() => {
          const nsfcTypes = grantTypes.filter((gt) => (gt.group || "nsfc") === "nsfc");
          const talentTypes = grantTypes.filter((gt) => gt.group === "talent");
          const renderCard = (gt: GrantTypeInfo) => {
            const meta = grantMeta[gt.key] || { icon: BookOpen, color: "gray" };
            const c = colorMap[meta.color] || colorMap.gray;
            const Icon = meta.icon;
            const active = selectedGrant === gt.key;
            return (
              <button
                key={gt.key}
                onClick={() => setSelectedGrant(gt.key)}
                className={`flex flex-col items-start rounded-xl border p-4 text-left transition hover-lift ${
                  active ? `${c.bg} ${c.border} ring-2 ring-offset-1 ring-indigo-400` : "border-gray-100 bg-white hover:border-gray-200"
                }`}
              >
                <Icon className={`mb-2 h-5 w-5 ${active ? c.icon : "text-gray-400"}`} />
                <span className={`text-sm font-semibold ${active ? c.text : "text-gray-700"}`}>{gt.name}</span>
                <span className="mt-0.5 text-[11px] font-medium text-indigo-500">{gt.tone}</span>
                <span className="mt-1 text-xs text-gray-400 line-clamp-2">{gt.desc}</span>
              </button>
            );
          };
          return (
            <>
              {nsfcTypes.length > 0 && (
                <>
                  <p className="text-xs font-medium text-gray-400">国家自然科学基金</p>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                    {nsfcTypes.map(renderCard)}
                  </div>
                </>
              )}
              {talentTypes.length > 0 && (
                <>
                  <p className="mt-2 text-xs font-medium text-gray-400">人才计划</p>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                    {talentTypes.map(renderCard)}
                  </div>
                </>
              )}
            </>
          );
        })()}

        {selectedGrant && (
          <button
            onClick={() => setStep(2)}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 py-3 text-sm font-semibold text-white transition hover:bg-indigo-700"
          >
            下一步：选择代表作 <ChevronRight className="h-4 w-4" />
          </button>
        )}
      </div>
    );
  }

  // ===== Grant mode: Step 2 - Select papers =====
  if (step === 2) {
    return (
      <div className="space-y-5">
        <div className="flex items-center justify-between">
          <button onClick={() => setStep(1)} className="flex items-center gap-1 text-sm text-gray-400 hover:text-gray-600">
            <ChevronLeft className="h-3.5 w-3.5" /> 返回选择类型
          </button>
          <span className="text-xs text-gray-400">
            共 {paperMetas.length} 篇 · 已选 {selectedCount} 篇（建议 3-5 篇）
          </span>
        </div>

        <div>
          <h3 className="mb-1 text-sm font-semibold uppercase tracking-wider text-gray-500">Step 2：选择代表作并填写信息</h3>
          <p className="text-xs text-gray-400">勾选论文，展开填写科学问题、创新点等（可留空，生成时标 [待填写]）</p>
        </div>

        {/* Project title */}
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-600">项目名称（可选）</label>
          <input
            type="text"
            value={projectTitle}
            onChange={(e) => setProjectTitle(e.target.value)}
            placeholder="如：基于多模态大模型的医学影像智能诊断"
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400"
          />
        </div>

        {/* Paper list */}
        <div className="space-y-2">
          {pagedPaperMetas.map((pm) => (
            <div
              key={pm.paper.id}
              className={`rounded-xl border transition ${pm.selected ? "border-indigo-200 bg-indigo-50/30" : "border-gray-100 bg-white"}`}
            >
              {/* Paper header row */}
              <div className="flex items-start gap-3 px-4 py-3">
                <button
                  onClick={() => togglePaper(pm.paper.id)}
                  className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border transition ${
                    pm.selected ? "border-indigo-600 bg-indigo-600 text-white" : "border-gray-300 bg-white"
                  }`}
                >
                  {pm.selected && <Check className="h-3 w-3" />}
                </button>
                <div className="min-w-0 flex-1 cursor-pointer" onClick={() => toggleExpand(pm.paper.id)}>
                  <div className="text-sm font-medium text-gray-800 line-clamp-2">{pm.paper.title}</div>
                  <div className="mt-0.5 flex flex-wrap gap-2 text-xs text-gray-400">
                    <span>{pm.paper.venue}</span>
                    <span>{pm.paper.year}</span>
                    <span>引用 {pm.paper.citation_count}</span>
                    {pm.paper.ccf_rank && (
                      <span className="rounded bg-indigo-100 px-1.5 font-medium text-indigo-600">CCF-{pm.paper.ccf_rank}</span>
                    )}
                  </div>
                </div>
                <button onClick={() => toggleExpand(pm.paper.id)} className="mt-1 text-gray-400">
                  {pm.expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                </button>
              </div>

              {/* Expanded section */}
              {pm.expanded && (
                <div className="border-t border-gray-100 px-4 py-3 space-y-3">
                  {/* Evidence preview */}
                  {pm.loadingEvidence && (
                    <div className="flex items-center gap-2 text-xs text-gray-400">
                      <Loader2 className="h-3 w-3 animate-spin" /> 加载证据数据...
                    </div>
                  )}
                  {pm.evidence && (
                    <div className="rounded-lg bg-gray-50 p-3 text-xs text-gray-500 space-y-1">
                      <div className="font-medium text-gray-700">引用分析数据</div>
                      <div className="flex flex-wrap gap-3">
                        <span>被引论文 {pm.evidence.total_citing_papers} 篇</span>
                        <span>影响力引用 {pm.evidence.influential_count}</span>
                        <span>顶尖学者(h≥50) {pm.evidence.top_scholar_count}</span>
                        <span>知名学者(h≥25) {pm.evidence.notable_scholar_count}</span>
                      </div>
                      {pm.evidence.notable_citations.length > 0 && (
                        <div className="mt-1.5 space-y-1">
                          <div className="font-medium text-gray-700">知名学者引用</div>
                          {pm.evidence.notable_citations.slice(0, 3).map((nc, i) => (
                            <div key={i} className="flex items-center gap-2">
                              <span className="font-medium text-gray-700">{nc.author_name}</span>
                              <span className="text-gray-400">h={nc.author_h_index}</span>
                              {nc.honor_tags.length > 0 && (
                                <span className="rounded bg-amber-100 px-1.5 text-[10px] font-medium text-amber-700">
                                  {nc.honor_tags.join(", ")}
                                </span>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                      {!pm.evidence.total_citing_papers && (
                        <div className="flex items-center gap-1.5 text-amber-600">
                          <AlertCircle className="h-3 w-3" />
                          尚未运行引用分析，生成时将缺少知名学者引用证据
                        </div>
                      )}
                    </div>
                  )}

                  {/* User input fields */}
                  <div>
                    <label className="mb-1 block text-xs text-gray-500">对应的关键科学问题</label>
                    <input
                      type="text"
                      value={pm.scientific_question}
                      onChange={(e) => updatePaperMeta(pm.paper.id, "scientific_question", e.target.value)}
                      placeholder="如：多模态数据对齐难"
                      className="w-full rounded-lg border border-gray-200 px-3 py-1.5 text-sm outline-none focus:border-indigo-400"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-gray-500">创新与突破</label>
                    <input
                      type="text"
                      value={pm.innovation_summary}
                      onChange={(e) => updatePaperMeta(pm.paper.id, "innovation_summary", e.target.value)}
                      placeholder="如：首次引入 XXX 机制，解决了传统方法的 YYY 问题"
                      className="w-full rounded-lg border border-gray-200 px-3 py-1.5 text-sm outline-none focus:border-indigo-400"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-gray-500">对本项目的支撑</label>
                    <input
                      type="text"
                      value={pm.relevance}
                      onChange={(e) => updatePaperMeta(pm.paper.id, "relevance", e.target.value)}
                      placeholder="如：本项目将直接沿用该算法框架并拓展至新场景"
                      className="w-full rounded-lg border border-gray-200 px-3 py-1.5 text-sm outline-none focus:border-indigo-400"
                    />
                  </div>

                  {/* Link repos */}
                  {repos.length > 0 && (
                    <div>
                      <label className="mb-1 block text-xs text-gray-500">关联 GitHub 仓库</label>
                      <div className="flex flex-wrap gap-1.5">
                        {repos.map((r) => {
                          const linked = pm.linked_repo_ids.includes(r.id);
                          return (
                            <button
                              key={r.id}
                              onClick={() => {
                                const ids = linked ? pm.linked_repo_ids.filter((id) => id !== r.id) : [...pm.linked_repo_ids, r.id];
                                updatePaperMeta(pm.paper.id, "linked_repo_ids", ids);
                              }}
                              className={`flex items-center gap-1 rounded-lg px-2 py-1 text-xs transition ${
                                linked ? "bg-indigo-600 text-white" : "border border-gray-200 text-gray-500 hover:bg-gray-50"
                              }`}
                            >
                              <GitFork className="h-3 w-3" />
                              {r.repo_name.split("/").pop()}
                              {r.stars > 0 && <span className="opacity-70">({formatNumber(r.stars)})</span>}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Link HF items */}
                  {hfItems.length > 0 && (
                    <div>
                      <label className="mb-1 block text-xs text-gray-500">关联 HuggingFace 模型/数据集</label>
                      <div className="flex flex-wrap gap-1.5">
                        {hfItems.map((h) => {
                          const linked = pm.linked_hf_item_ids.includes(h.id);
                          return (
                            <button
                              key={h.id}
                              onClick={() => {
                                const ids = linked ? pm.linked_hf_item_ids.filter((id) => id !== h.id) : [...pm.linked_hf_item_ids, h.id];
                                updatePaperMeta(pm.paper.id, "linked_hf_item_ids", ids);
                              }}
                              className={`flex items-center gap-1 rounded-lg px-2 py-1 text-xs transition ${
                                linked ? "bg-amber-600 text-white" : "border border-gray-200 text-gray-500 hover:bg-gray-50"
                              }`}
                            >
                              <Star className="h-3 w-3" />
                              {h.name || h.item_id}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Pagination */}
        {totalPaperPages > 1 && (
          <div className="flex items-center justify-center gap-2">
            <button
              onClick={() => setPaperPage((p) => Math.max(0, p - 1))}
              disabled={paperPage === 0}
              className="flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 transition hover:bg-gray-50 disabled:opacity-40"
            >
              <ChevronLeft className="h-3.5 w-3.5" /> 上一页
            </button>
            <div className="flex gap-1">
              {Array.from({ length: totalPaperPages }, (_, i) => (
                <button
                  key={i}
                  onClick={() => setPaperPage(i)}
                  className={`h-7 w-7 rounded-lg text-xs font-medium transition ${
                    paperPage === i ? "bg-indigo-600 text-white" : "text-gray-500 hover:bg-gray-100"
                  }`}
                >
                  {i + 1}
                </button>
              ))}
            </div>
            <button
              onClick={() => setPaperPage((p) => Math.min(totalPaperPages - 1, p + 1))}
              disabled={paperPage === totalPaperPages - 1}
              className="flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 transition hover:bg-gray-50 disabled:opacity-40"
            >
              下一页 <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        {/* Generate button */}
        <button
          onClick={handleGenerate}
          disabled={selectedCount === 0 || generating}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 py-3 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:opacity-50"
        >
          {generating ? (
            <><Loader2 className="h-4 w-4 animate-spin" /> 生成中...</>
          ) : (
            <><Sparkles className="h-4 w-4" /> 生成研究基础（{selectedCount} 篇代表作）</>
          )}
        </button>
      </div>
    );
  }

  // ===== Grant mode: Step 3 - Preview + Download =====
  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <button onClick={() => setStep(2)} className="flex items-center gap-1 text-sm text-gray-400 hover:text-gray-600">
          <ChevronLeft className="h-3.5 w-3.5" /> 返回编辑
        </button>
        <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-500">Step 3：预览 & 下载</h3>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap p-6 text-sm leading-relaxed text-gray-700 font-[inherit]">
          {markdown}
        </pre>
      </div>

      <div className="flex gap-3">
        <button
          onClick={handleDownload}
          className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-indigo-600 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-700"
        >
          <FileDown className="h-4 w-4" /> 下载 Markdown
        </button>
        <button
          onClick={handleCopy}
          className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-gray-200 bg-white py-2.5 text-sm font-semibold text-gray-700 transition hover:bg-gray-50"
        >
          {copied ? <><Check className="h-4 w-4 text-emerald-500" /> 已复制</> : <><Copy className="h-4 w-4" /> 复制到剪贴板</>}
        </button>
      </div>
    </div>
  );
}

function StatBadge({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg bg-gray-50 px-3 py-1.5">
      <span className="text-xs text-gray-400">{label}</span>
      <span className="ml-1.5 text-sm font-bold text-gray-800">{value}</span>
    </div>
  );
}
