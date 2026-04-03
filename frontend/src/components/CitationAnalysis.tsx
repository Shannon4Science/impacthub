import { useEffect, useState, useCallback } from "react";
import {
  api,
  type CitationOverview,
  type NotableCitationItem,
  type PaperCitationAnalysis,
} from "@/lib/api";
import { formatNumber } from "@/lib/utils";
import {
  Loader2,
  Sparkles,
  Crown,
  Award,
  Quote,
  ChevronDown,
  ChevronUp,
  Zap,
  Users,
  FileText,
  ExternalLink,
} from "lucide-react";
import Pagination from "@/components/Pagination";

interface Props {
  userId: string;
  configured: boolean;
  initialData?: CitationOverview | null;
}

export default function CitationAnalysis({ userId, configured, initialData }: Props) {
  const [data, setData] = useState<CitationOverview | null>(initialData ?? null);
  const [loading, setLoading] = useState(!initialData);
  const [analyzing, setAnalyzing] = useState(initialData?.is_analyzing ?? false);
  const [expandedScholar, setExpandedScholar] = useState<number | null>(null);

  // Extra scholars loaded via pagination
  const [extraTop, setExtraTop] = useState<NotableCitationItem[]>([]);
  const [extraNotable, setExtraNotable] = useState<NotableCitationItem[]>([]);
  const [extraPapers, setExtraPapers] = useState<PaperCitationAnalysis[]>([]);
  const [loadingMore, setLoadingMore] = useState<"top" | "notable" | "papers" | null>(null);
  const [topPage, setTopPage] = useState(1);
  const [notablePage, setNotablePage] = useState(1);
  const [paperPage, setPaperPage] = useState(1);

  const fetchData = useCallback(async () => {
    try {
      const d = await api.getCitationOverview(userId);
      setData(d);
      setAnalyzing(d.is_analyzing);
      setExtraTop([]);
      setExtraNotable([]);
      setExtraPapers([]);
      setTopPage(1);
      setNotablePage(1);
      setPaperPage(1);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (!analyzing) return;
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [analyzing, fetchData]);

  const loadMore = async (level: "top" | "notable" | "papers") => {
    if (!data || loadingMore) return;
    setLoadingMore(level);
    try {
      if (level === "papers") {
        const offset = data.paper_analyses.length + extraPapers.length;
        const res = await api.getPaperAnalyses(userId, offset);
        setExtraPapers((prev) => [...prev, ...res.items]);
      } else {
        const currentExtra = level === "top" ? extraTop : extraNotable;
        const offset = data[level === "top" ? "top_scholars" : "notable_scholars"].length + currentExtra.length;
        const res = await api.getScholars(userId, level, offset);
        if (level === "top") {
          setExtraTop((prev) => [...prev, ...res.items]);
        } else {
          setExtraNotable((prev) => [...prev, ...res.items]);
        }
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingMore(null);
    }
  };

  const handleAnalyze = async () => {
    setAnalyzing(true);
    try {
      await api.triggerCitationAnalysis(userId);
    } catch (err) {
      console.error(err);
      setAnalyzing(false);
    }
  };

  if (!configured) {
    return (
      <div className="flex flex-col items-center rounded-2xl border border-dashed border-amber-200 bg-amber-50/50 py-14">
        <Quote className="h-10 w-10 text-amber-400" />
        <p className="mt-3 text-sm font-medium text-amber-700">Semantic Scholar 账号未关联</p>
        <p className="mt-1 text-xs text-amber-500">需要关联 Scholar ID 才能分析引用</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-indigo-400" />
      </div>
    );
  }

  const hasData = data && data.total_papers_analyzed > 0;

  return (
    <div className="space-y-6">
      {/* Action bar */}
      <div className="flex items-center justify-between rounded-xl border border-gray-200 bg-white px-5 py-3 shadow-sm">
        <div className="text-sm text-gray-500">
          {hasData ? (
            <>
              已分析 <strong className="text-gray-900">{data.total_papers_analyzed}</strong> 篇论文，
              发现 <strong className="text-indigo-600">{data.unique_notable_scholars}</strong> 位知名学者引用
            </>
          ) : (
            "点击按钮开始分析你的论文被哪些知名学者引用"
          )}
        </div>
        <button
          onClick={handleAnalyze}
          disabled={analyzing}
          className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:opacity-50"
        >
          {analyzing ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              分析中...
            </>
          ) : (
            <>
              <Sparkles className="h-3.5 w-3.5" />
              {hasData ? "重新分析" : "开始分析"}
            </>
          )}
        </button>
      </div>

      {analyzing && (
        <div className="rounded-xl border border-indigo-100 bg-indigo-50 px-4 py-3">
          <div className="mb-2 flex items-center justify-between text-sm text-indigo-700">
            <div className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在从 Semantic Scholar 获取施引文献并分析学者信息…
            </div>
            {data && data.analysis_total > 0 && (
              <span className="text-xs font-semibold">
                {data.analysis_done} / {data.analysis_total} 篇
              </span>
            )}
          </div>
          {data && data.analysis_total > 0 && (
            <div className="h-2 overflow-hidden rounded-full bg-indigo-200">
              <div
                className="h-full rounded-full bg-indigo-500 transition-all duration-500"
                style={{ width: `${Math.round((data.analysis_done / data.analysis_total) * 100)}%` }}
              />
            </div>
          )}
          {data && data.analysis_total === 0 && (
            <div className="h-2 overflow-hidden rounded-full bg-indigo-200">
              <div className="h-full w-1/3 animate-pulse rounded-full bg-indigo-400" />
            </div>
          )}
        </div>
      )}

      {hasData && (
        <>
          {/* Summary Stats */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            <SummaryCard
              icon={Users}
              label="知名学者引用"
              value={data.unique_notable_scholars}
              accent="text-indigo-600 bg-indigo-50 border-indigo-200"
            />
            <SummaryCard
              icon={Crown}
              label="顶级学者"
              sublabel="h-index ≥ 50"
              value={data.top_scholars.length}
              accent="text-amber-600 bg-amber-50 border-amber-200"
            />
            <SummaryCard
              icon={Award}
              label="IEEE / 院士"
              value={data.honor_scholar_count}
              loading={data.honor_is_enriching}
              accent="text-rose-600 bg-rose-50 border-rose-200"
            />
            <SummaryCard
              icon={Zap}
              label="高影响力引用"
              value={data.paper_analyses.reduce((s, a) => s + a.influential_count, 0)}
              accent="text-emerald-600 bg-emerald-50 border-emerald-200"
            />
            <SummaryCard
              icon={FileText}
              label="已分析论文"
              value={data.total_papers_analyzed}
              accent="text-violet-600 bg-violet-50 border-violet-200"
            />
          </div>

          {/* Top Scholars Section */}
          {data.top_scholars.length > 0 && (() => {
            const PAGE_SIZE = 20;
            const allTop = deduplicateByAuthor([...data.top_scholars, ...extraTop]);
            const totalPages = Math.ceil(data.top_scholar_total / PAGE_SIZE);
            const pageItems = allTop.slice((topPage - 1) * PAGE_SIZE, topPage * PAGE_SIZE);

            const handleTopPage = async (p: number) => {
              setTopPage(p);
              const needed = p * PAGE_SIZE;
              if (needed > allTop.length && allTop.length < data.top_scholar_total) {
                setLoadingMore("top");
                try {
                  const res = await api.getScholars(userId, "top", allTop.length, needed - allTop.length);
                  setExtraTop((prev) => [...prev, ...res.items]);
                } catch (err) {
                  console.error(err);
                } finally {
                  setLoadingMore(null);
                }
              }
            };

            return (
            <section>
              <div className="mb-3 flex items-center gap-2">
                <Crown className="h-4 w-4 text-amber-500" />
                <h3 className="text-sm font-semibold text-gray-900">
                  顶级学者引用
                </h3>
                <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                  h-index ≥ 50
                </span>
                <span className="text-xs text-gray-400">共 {data.top_scholar_total} 位</span>
              </div>
              <div className="space-y-2">
                {loadingMore === "top" && pageItems.length === 0 ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="h-5 w-5 animate-spin text-amber-400" />
                  </div>
                ) : (
                  pageItems.map((scholar) => (
                  <ScholarCard
                    key={scholar.id}
                    scholar={scholar}
                    level="top"
                    expanded={expandedScholar === scholar.id}
                    onToggle={() =>
                      setExpandedScholar(expandedScholar === scholar.id ? null : scholar.id)
                    }
                  />
                  ))
                )}
              </div>
              <Pagination current={topPage} total={totalPages} onChange={handleTopPage} />
            </section>
            );
          })()}

          {/* Notable Scholars Section */}
          {data.notable_scholars.length > 0 && (() => {
            const PAGE_SIZE = 20;
            const allNotable = deduplicateByAuthor([...data.notable_scholars, ...extraNotable]);
            const totalPages = Math.ceil(data.notable_scholar_total / PAGE_SIZE);
            const pageItems = allNotable.slice((notablePage - 1) * PAGE_SIZE, notablePage * PAGE_SIZE);

            const handleNotablePage = async (p: number) => {
              setNotablePage(p);
              const needed = p * PAGE_SIZE;
              if (needed > allNotable.length && allNotable.length < data.notable_scholar_total) {
                setLoadingMore("notable");
                try {
                  const res = await api.getScholars(userId, "notable", allNotable.length, needed - allNotable.length);
                  setExtraNotable((prev) => [...prev, ...res.items]);
                } catch (err) {
                  console.error(err);
                } finally {
                  setLoadingMore(null);
                }
              }
            };

            return (
            <section>
              <div className="mb-3 flex items-center gap-2">
                <Award className="h-4 w-4 text-indigo-500" />
                <h3 className="text-sm font-semibold text-gray-900">
                  知名学者引用
                </h3>
                <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-700">
                  h-index ≥ 25
                </span>
                <span className="text-xs text-gray-400">共 {data.notable_scholar_total} 位</span>
              </div>
              <div className="space-y-2">
                {loadingMore === "notable" && pageItems.length === 0 ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="h-5 w-5 animate-spin text-indigo-400" />
                  </div>
                ) : (
                  pageItems.map((scholar) => (
                  <ScholarCard
                    key={scholar.id}
                    scholar={scholar}
                    level="notable"
                    expanded={expandedScholar === scholar.id}
                    onToggle={() =>
                      setExpandedScholar(expandedScholar === scholar.id ? null : scholar.id)
                    }
                  />
                  ))
                )}
              </div>
              <Pagination current={notablePage} total={totalPages} onChange={handleNotablePage} />
            </section>
            );
          })()}

          {/* Per-paper breakdown */}
          {data.paper_analyses.length > 0 && (() => {
            const PAPER_PAGE_SIZE = 10;
            const allPapers = [...data.paper_analyses, ...extraPapers];
            const totalPages = Math.ceil(data.paper_analyses_total / PAPER_PAGE_SIZE);
            const pageItems = allPapers.slice((paperPage - 1) * PAPER_PAGE_SIZE, paperPage * PAPER_PAGE_SIZE);

            const handlePaperPage = async (p: number) => {
              setPaperPage(p);
              // Check if we need to fetch more data for this page
              const needed = p * PAPER_PAGE_SIZE;
              if (needed > allPapers.length && allPapers.length < data.paper_analyses_total) {
                setLoadingMore("papers");
                try {
                  const res = await api.getPaperAnalyses(userId, allPapers.length, needed - allPapers.length);
                  setExtraPapers((prev) => [...prev, ...res.items]);
                } catch (err) {
                  console.error(err);
                } finally {
                  setLoadingMore(null);
                }
              }
            };

            return (
            <section>
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-gray-900">
                  各论文引用概况
                </h3>
                <span className="text-xs text-gray-400">
                  共 {data.paper_analyses_total} 篇已分析
                </span>
              </div>
              <div className="space-y-2">
                {loadingMore === "papers" && pageItems.length === 0 ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
                  </div>
                ) : (
                  pageItems.map((pa) => (
                  <div
                    key={pa.paper_id}
                    className="rounded-xl border border-gray-100 bg-white px-5 py-3 shadow-sm hover-lift"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-gray-900">
                          {pa.paper_title}
                        </p>
                        <div className="mt-1 flex flex-wrap gap-3 text-xs text-gray-400">
                          <span>引用 {formatNumber(pa.paper_citation_count)}</span>
                          <span>施引 {pa.total_citing_papers} 篇</span>
                          {pa.top_scholar_count > 0 && (
                            <span className="font-medium text-amber-600">
                              顶级学者 {pa.top_scholar_count}
                            </span>
                          )}
                          {pa.notable_scholar_count > 0 && (
                            <span className="font-medium text-indigo-600">
                              知名学者 {pa.notable_scholar_count}
                            </span>
                          )}
                          {pa.influential_count > 0 && (
                            <span className="font-medium text-emerald-600">
                              高影响 {pa.influential_count}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                  ))
                )}
              </div>
              <Pagination
                current={paperPage}
                total={totalPages}
                onChange={handlePaperPage}
              />
            </section>
            );
          })()}
        </>
      )}
    </div>
  );
}

function SummaryCard({
  icon: Icon,
  label,
  sublabel,
  value,
  accent,
  loading,
}: {
  icon: typeof Users;
  label: string;
  sublabel?: string;
  value: number;
  accent: string;
  loading?: boolean;
}) {
  return (
    <div className={`rounded-xl border px-4 py-3 ${accent}`}>
      <div className="flex items-center gap-1.5">
        <Icon className="h-3.5 w-3.5 opacity-70" />
        <span className="text-xs font-medium opacity-70">{label}</span>
      </div>
      {sublabel && <div className="text-[10px] opacity-50">{sublabel}</div>}
      {loading ? (
        <div className="mt-1 flex items-center gap-1 text-sm opacity-60">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          识别中…
        </div>
      ) : (
        <div className="mt-0.5 text-2xl font-bold">{formatNumber(value)}</div>
      )}
    </div>
  );
}

function ScholarCard({
  scholar,
  level,
  expanded,
  onToggle,
}: {
  scholar: NotableCitationItem;
  level: "top" | "notable";
  expanded: boolean;
  onToggle: () => void;
}) {
  const borderColor = level === "top" ? "border-amber-200 hover:border-amber-300" : "border-gray-100 hover:border-indigo-200";
  const badgeColor = level === "top" ? "bg-amber-100 text-amber-700" : "bg-indigo-100 text-indigo-700";

  return (
    <div className={`rounded-xl border bg-white shadow-sm transition hover-lift ${borderColor}`}>
      <button
        onClick={onToggle}
        className="flex w-full items-center gap-4 px-5 py-3.5 text-left"
      >
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-gray-100 to-gray-50 text-sm font-bold text-gray-600">
          {scholar.author_name[0]}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <a
              href={`https://www.semanticscholar.org/author/${scholar.author_ss_id}`}
              target="_blank"
              rel="noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="font-semibold text-gray-900 hover:text-indigo-600"
            >
              {scholar.author_name}
              <ExternalLink className="ml-1 inline h-3 w-3 opacity-0 transition group-hover:opacity-50" />
            </a>
            <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${badgeColor}`}>
              h-index {scholar.author_h_index}
            </span>
            {scholar.honor_tags?.map((tag) => (
              <span key={tag} className="rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-semibold text-rose-700">
                {tag}
              </span>
            ))}
            {scholar.is_influential && (
              <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
                高影响
              </span>
            )}
          </div>
          <div className="mt-0.5 flex items-center gap-3 text-xs text-gray-400">
            <span>引用 {formatNumber(scholar.author_citation_count)}</span>
            <span>论文 {formatNumber(scholar.author_paper_count)}</span>
            <span className="truncate">引用了: {scholar.paper_title}</span>
          </div>
        </div>
        <div className="shrink-0 text-gray-300">
          {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-gray-100 px-5 py-3">
          <div className="mb-2 text-xs font-medium text-gray-500">
            通过论文引用：
          </div>
          <div className="mb-2 rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-700">
            {scholar.citing_paper_title}
            {scholar.citing_paper_venue && (
              <span className="ml-2 text-xs text-gray-400">
                {scholar.citing_paper_venue} {scholar.citing_paper_year}
              </span>
            )}
          </div>
          {scholar.contexts.length > 0 && (
            <div className="mt-3">
              <div className="mb-1.5 text-xs font-medium text-gray-500">引用原文：</div>
              <div className="space-y-2">
                {scholar.contexts.map((ctx, i) => (
                  <blockquote
                    key={i}
                    className="border-l-2 border-indigo-200 pl-3 text-xs leading-relaxed text-gray-600 italic"
                  >
                    "{ctx}"
                  </blockquote>
                ))}
              </div>
            </div>
          )}
          {scholar.intents.length > 0 && (
            <div className="mt-2 flex items-center gap-1.5">
              <span className="text-xs text-gray-400">引用意图：</span>
              {scholar.intents.map((intent) => (
                <span
                  key={intent}
                  className="rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-medium text-violet-600"
                >
                  {intentLabel(intent)}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function intentLabel(intent: string): string {
  const map: Record<string, string> = {
    methodology: "方法引用",
    background: "背景引用",
    "result comparison": "结果对比",
    extension: "扩展研究",
  };
  return map[intent.toLowerCase()] || intent;
}

function deduplicateByAuthor(items: NotableCitationItem[]): NotableCitationItem[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = item.author_ss_id || item.author_name;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
