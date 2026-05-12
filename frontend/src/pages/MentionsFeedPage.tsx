import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  MessageSquare, Search, ExternalLink, ThumbsUp, Eye, MessageCircle,
  Loader2, MapPin, ChevronLeft, ChevronRight,
} from "lucide-react";
import { api, type MentionFeedResponse, type MentionFeedItem } from "@/lib/api";

const SOURCE_LABEL: Record<string, string> = {
  wechat: "公众号",
  xiaohongshu: "小红书",
  zhihu: "知乎",
  forum: "论坛",
  other: "其他",
};

const SENTIMENT_META: Record<string, { label: string; color: string }> = {
  positive: { label: "正向", color: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  neutral: { label: "中性", color: "bg-slate-50 text-slate-700 border-slate-200" },
  negative: { label: "负向", color: "bg-rose-50 text-rose-700 border-rose-200" },
};

const PAGE_SIZE = 20;

export default function MentionsFeedPage() {
  const [data, setData] = useState<MentionFeedResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const [q, setQ] = useState("");
  const [qDeferred, setQDeferred] = useState(""); // debounced
  const [source, setSource] = useState("");
  const [account, setAccount] = useState("");
  const [sentiment, setSentiment] = useState("");
  const [offset, setOffset] = useState(0);
  // Bumped on tab focus / visibility change → triggers a re-fetch
  const [refreshTick, setRefreshTick] = useState(0);

  // debounce search box
  useEffect(() => {
    const t = setTimeout(() => setQDeferred(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);

  // Auto-refresh when tab regains focus or becomes visible
  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === "visible") setRefreshTick((n) => n + 1);
    };
    const onFocus = () => setRefreshTick((n) => n + 1);
    document.addEventListener("visibilitychange", onVis);
    window.addEventListener("focus", onFocus);
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("focus", onFocus);
    };
  }, []);

  useEffect(() => {
    setLoading(true);
    api.mentionsFeed({
      q: qDeferred || undefined,
      source: source || undefined,
      account: account || undefined,
      sentiment: sentiment || undefined,
      offset,
      limit: PAGE_SIZE,
    })
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [qDeferred, source, account, sentiment, offset, refreshTick]);

  // Reset to page 0 when filters change (but not when offset changes)
  useEffect(() => {
    setOffset(0);
  }, [qDeferred, source, account, sentiment]);

  const facets = data?.facets ?? { sources: {}, accounts: {}, sentiments: {} };
  const totalAcrossSources = useMemo(
    () => Object.values(facets.sources).reduce((a, b) => a + b, 0),
    [facets.sources]
  );

  return (
    <main className="mx-auto max-w-5xl px-4 py-6">
      {/* Hero */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-6 rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50 via-white to-purple-50 p-6 shadow-sm"
      >
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white">
            <MessageSquare className="h-5 w-5" />
          </div>
          <div className="flex-1">
            <h1 className="text-xl font-bold text-gray-900">导师口碑墙</h1>
            <p className="text-xs text-gray-500">
              来自公众号 / 小红书 / 知乎等渠道关于导师的内容（{totalAcrossSources} 条）
            </p>
          </div>
        </div>
      </motion.div>

      {/* Filters */}
      <div className="mb-4 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
        {/* Search */}
        <div className="relative mb-3">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索导师名 / 文章标题 / 摘要 / 公众号名…"
            className="w-full rounded-xl border border-gray-200 bg-gray-50 pl-9 pr-3 py-2 text-sm focus:border-indigo-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-100"
          />
        </div>

        {/* Facet chips */}
        <FacetRow label="来源" value={source} onChange={setSource} options={facets.sources} formatter={(k) => SOURCE_LABEL[k] || k} />
        <FacetRow label="账号" value={account} onChange={setAccount} options={facets.accounts} max={8} />
        {Object.keys(facets.sentiments).length > 0 && (
          <FacetRow label="情感" value={sentiment} onChange={setSentiment} options={facets.sentiments} formatter={(k) => SENTIMENT_META[k]?.label || k} />
        )}
      </div>

      {/* Results */}
      <div className="mb-3 flex items-center justify-between text-xs text-gray-500">
        <span>{loading ? "加载中…" : `共 ${data?.total ?? 0} 条`}</span>
        {data && data.total > PAGE_SIZE && (
          <Pagination offset={offset} total={data.total} pageSize={PAGE_SIZE} onChange={setOffset} />
        )}
      </div>

      <div className="space-y-3">
        <AnimatePresence>
          {data?.items.map((m, i) => (
            <motion.div
              key={m.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(i * 0.02, 0.3), duration: 0.2 }}
            >
              <MentionCard m={m} />
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {!loading && data && data.items.length === 0 && (
        <div className="rounded-2xl border border-dashed border-gray-200 bg-gray-50 p-10 text-center text-sm text-gray-400">
          没有匹配的提及。换个关键词试试？
        </div>
      )}

      {loading && !data && (
        <div className="flex justify-center py-20">
          <Loader2 className="h-8 w-8 animate-spin text-indigo-400" />
        </div>
      )}

      {data && data.total > PAGE_SIZE && (
        <div className="mt-6 flex justify-center">
          <Pagination offset={offset} total={data.total} pageSize={PAGE_SIZE} onChange={setOffset} />
        </div>
      )}
    </main>
  );
}

function FacetRow({
  label, value, onChange, options, formatter, max = 12,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: Record<string, number>;
  formatter?: (key: string) => string;
  max?: number;
}) {
  const entries = Object.entries(options).sort((a, b) => b[1] - a[1]).slice(0, max);
  if (entries.length === 0) return null;
  return (
    <div className="mb-2 flex items-center gap-2 flex-wrap">
      <span className="w-10 shrink-0 text-[11px] text-gray-400">{label}</span>
      <button
        onClick={() => onChange("")}
        className={`rounded-full border px-2.5 py-0.5 text-xs transition ${
          value === ""
            ? "border-indigo-400 bg-indigo-50 text-indigo-700"
            : "border-gray-200 bg-white text-gray-600 hover:border-gray-300"
        }`}
      >
        全部
      </button>
      {entries.map(([k, n]) => (
        <button
          key={k}
          onClick={() => onChange(value === k ? "" : k)}
          className={`rounded-full border px-2.5 py-0.5 text-xs transition ${
            value === k
              ? "border-indigo-400 bg-indigo-50 text-indigo-700"
              : "border-gray-200 bg-white text-gray-600 hover:border-gray-300"
          }`}
        >
          {formatter ? formatter(k) : k} <span className="text-gray-400">{n}</span>
        </button>
      ))}
    </div>
  );
}

function MentionCard({ m }: { m: MentionFeedItem }) {
  const sm = SENTIMENT_META[m.sentiment];
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm transition hover:shadow-md">
      <div className="flex items-start gap-3">
        {m.cover_url ? (
          <img
            src={m.cover_url}
            alt=""
            className="h-16 w-16 shrink-0 rounded-lg border border-gray-200 object-cover"
          />
        ) : (
          <div className="flex h-16 w-16 shrink-0 flex-col items-center justify-center rounded-lg bg-gradient-to-br from-indigo-100 to-purple-100 text-[10px] font-semibold text-indigo-700">
            <MessageSquare className="mb-0.5 h-4 w-4" />
            {SOURCE_LABEL[m.source] || m.source}
          </div>
        )}

        <div className="min-w-0 flex-1">
          {/* Top row: source + sentiment + date */}
          <div className="mb-1 flex items-center gap-1.5 flex-wrap">
            <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-700">
              {SOURCE_LABEL[m.source] || m.source}
            </span>
            {m.source_account && (
              <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] font-medium text-indigo-700 border border-indigo-200">
                {m.source_account}
              </span>
            )}
            {sm && (
              <span className={`rounded-full border px-1.5 py-0.5 text-[10px] font-medium ${sm.color}`}>
                {sm.label}
              </span>
            )}
            {m.published_at && (
              <span className="ml-auto text-[10px] text-gray-400">
                {m.published_at.slice(0, 10)}
              </span>
            )}
          </div>

          {/* Title */}
          {m.title && (
            <a
              href={m.url || "#"}
              target="_blank"
              rel="noopener noreferrer"
              className="block text-sm font-semibold text-gray-900 hover:text-indigo-600"
            >
              {m.title}
              {m.url && <ExternalLink className="ml-1 inline h-3 w-3 text-gray-400" />}
            </a>
          )}

          {/* Snippet */}
          {m.snippet && (
            <p className="mt-1 text-xs leading-relaxed text-gray-700">
              {m.snippet}
            </p>
          )}

          {/* Tags */}
          {m.tags && m.tags.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {m.tags.map((t) => (
                <span
                  key={t}
                  className="rounded-full bg-amber-50 px-1.5 py-px text-[10px] text-amber-700 border border-amber-200"
                >
                  #{t}
                </span>
              ))}
            </div>
          )}

          {/* Advisor block */}
          <div className="mt-2 flex items-center gap-2 border-t border-gray-100 pt-2 text-[11px]">
            {m.is_linked ? (
              <Link
                to={`/advisor/schools/${m.school_id}`}
                className="font-semibold text-indigo-700 hover:underline"
              >
                {m.advisor_name}
              </Link>
            ) : (
              <span className="font-semibold text-gray-700">{m.advisor_name}</span>
            )}
            <span className="text-gray-400">·</span>
            <span className="text-gray-600 truncate">
              {m.school_short}
              {m.college_name && ` · ${m.college_name}`}
            </span>
            {!m.is_linked && (
              <span className="rounded-full bg-gray-100 px-1.5 py-px text-[9px] text-gray-500 border border-gray-200" title="导师还未爬到 DB；老师入库后会自动关联">
                待关联
              </span>
            )}
            {m.is_985 && (
              <span className="ml-auto inline-flex items-center rounded-full bg-amber-100 px-1.5 py-px text-[9px] font-bold text-amber-800 border border-amber-200">
                985
              </span>
            )}
            {m.school_province && (
              <span className="inline-flex items-center gap-0.5 text-gray-500">
                <MapPin className="h-2.5 w-2.5" />
                {m.school_province}
              </span>
            )}
          </div>

          {/* Engagement */}
          {(m.likes > 0 || m.reads > 0 || m.comments > 0) && (
            <div className="mt-1.5 flex items-center gap-3 text-[11px] text-gray-500">
              {m.reads > 0 && (
                <span className="inline-flex items-center gap-0.5">
                  <Eye className="h-3 w-3" />
                  {formatNumber(m.reads)}
                </span>
              )}
              {m.likes > 0 && (
                <span className="inline-flex items-center gap-0.5">
                  <ThumbsUp className="h-3 w-3" />
                  {formatNumber(m.likes)}
                </span>
              )}
              {m.comments > 0 && (
                <span className="inline-flex items-center gap-0.5">
                  <MessageCircle className="h-3 w-3" />
                  {m.comments}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Pagination({
  offset, total, pageSize, onChange,
}: { offset: number; total: number; pageSize: number; onChange: (n: number) => void }) {
  const page = Math.floor(offset / pageSize) + 1;
  const totalPages = Math.ceil(total / pageSize);
  return (
    <div className="flex items-center gap-1">
      <button
        onClick={() => onChange(Math.max(0, offset - pageSize))}
        disabled={offset === 0}
        className="rounded-lg border border-gray-200 p-1 text-gray-500 hover:bg-gray-50 disabled:opacity-30"
      >
        <ChevronLeft className="h-4 w-4" />
      </button>
      <span className="px-2 text-xs text-gray-600">
        {page} / {totalPages}
      </span>
      <button
        onClick={() => onChange(offset + pageSize)}
        disabled={offset + pageSize >= total}
        className="rounded-lg border border-gray-200 p-1 text-gray-500 hover:bg-gray-50 disabled:opacity-30"
      >
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  );
}

function formatNumber(n: number): string {
  if (n >= 10000) return `${(n / 10000).toFixed(1)}w`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return n.toString();
}
