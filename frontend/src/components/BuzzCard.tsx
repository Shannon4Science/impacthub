import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import type { BuzzSnapshot } from "@/lib/api";
import { Flame, Loader2, RefreshCw, Tag, Globe } from "lucide-react";

interface Props {
  userId: string;
  buzz: BuzzSnapshot | null;
  refreshing: boolean;
  elapsed: number;
  onRefresh: () => void;
}

const heatConfig = {
  very_hot: { label: "极高", color: "text-red-700 bg-red-100",      dot: "bg-red-600" },
  hot:      { label: "较高", color: "text-orange-600 bg-orange-100", dot: "bg-orange-500" },
  medium:   { label: "一般", color: "text-amber-600 bg-amber-100",   dot: "bg-amber-400" },
  cold:     { label: "较低", color: "text-sky-600 bg-sky-100",       dot: "bg-sky-400" },
  very_cold: { label: "极低", color: "text-gray-500 bg-gray-100",    dot: "bg-gray-400" },
  "":       { label: "未知", color: "text-gray-400 bg-gray-50",      dot: "bg-gray-300" },
};

/** Replace [1][2]... with HTML superscript anchor tags before markdown rendering. */
function injectCitations(text: string, sources: { title: string; url: string }[]): string {
  if (!sources.length) return text;
  return text.replace(/\[(\d+)\]/g, (_, n) => {
    const src = sources[parseInt(n) - 1];
    if (!src) return `[${n}]`;
    const escaped = src.url.replace(/"/g, "&quot;");
    return `<sup><a href="${escaped}" target="_blank" rel="noreferrer" class="text-indigo-500 font-semibold hover:text-indigo-700" title="${escaped}">[${n}]</a></sup>`;
  });
}

export default function BuzzCard({ buzz, refreshing, elapsed, onRefresh }: Props) {
  const heat = buzz?.heat_label || "";
  const cfg = heatConfig[heat as keyof typeof heatConfig] ?? heatConfig[""];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-orange-100 text-orange-600">
            <Flame className="h-5 w-5" />
          </div>
          <div>
            <h3 className="font-semibold text-gray-900">社区讨论</h3>
            <p className="text-xs text-gray-400">
              {buzz?.refreshed_at
                ? `更新于 ${new Date(buzz.refreshed_at).toLocaleString("zh-CN")}`
                : "尚未抓取数据"}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {buzz && (
            <span className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${cfg.color}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${cfg.dot}`} />
              {cfg.label}
            </span>
          )}
          <button
            onClick={onRefresh}
            disabled={refreshing}
            className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 transition hover:border-orange-300 hover:text-orange-600 disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
            {buzz ? "刷新" : "开始抓取"}
          </button>
        </div>
      </div>

      {!buzz && !refreshing && (
        <div className="rounded-2xl border border-dashed border-gray-200 bg-gray-50 p-8 text-center text-sm text-gray-400">
          <Globe className="mx-auto mb-2 h-8 w-8 opacity-30" />
          <p>点击「开始抓取」搜索研究者在社交媒体、技术博客、新闻等平台的讨论热度</p>
        </div>
      )}

      {refreshing && (
        <div className="rounded-2xl border border-orange-100 bg-orange-50 p-5">
          <div className="mb-2 flex items-center justify-between text-sm text-orange-600">
            <div className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              {elapsed < 10
                ? "正在搜索全网讨论…"
                : elapsed < 30
                ? "正在分析讨论内容…"
                : elapsed < 60
                ? "正在生成分析报告…"
                : "仍在处理中，请耐心等待…"}
            </div>
            <span className="text-xs font-semibold tabular-nums">{elapsed}s</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-orange-200">
            <div
              className="h-full rounded-full bg-orange-400 transition-all duration-1000"
              style={{ width: `${Math.min(95, Math.round((elapsed / 60) * 100))}%` }}
            />
          </div>
          <div className="mt-2 flex justify-between text-[10px] text-orange-400">
            <span>搜索</span>
            <span>分析</span>
            <span>生成报告</span>
          </div>
        </div>
      )}

      {buzz && (
        <>
          {/* Topics */}
          {buzz.topics.length > 0 && (
            <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-700">
                <Tag className="h-4 w-4 text-indigo-500" />
                讨论热词
              </div>
              <div className="flex flex-wrap gap-2">
                {buzz.topics.map((t) => (
                  <span key={t} className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">
                    {t}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Summary — full markdown with citation links injected */}
          <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
            <div className="mb-3 text-sm font-semibold text-gray-700">讨论摘要</div>
            <div className="prose prose-sm max-w-none text-gray-600
              prose-headings:font-semibold prose-headings:text-gray-800
              prose-a:text-indigo-600 prose-a:no-underline hover:prose-a:underline
              prose-strong:text-gray-800
              prose-table:text-xs prose-th:bg-gray-50 prose-th:px-3 prose-th:py-2
              prose-td:px-3 prose-td:py-2 prose-td:border prose-td:border-gray-200
              prose-li:my-0.5 prose-p:my-1">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeRaw]}
                components={{
                  a: ({ href, children }) => (
                    <a href={href} target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline">
                      {children}
                    </a>
                  ),
                }}
              >
                {injectCitations(buzz.summary, buzz.sources)}
              </ReactMarkdown>
            </div>
          </div>

          {/* Numbered Sources */}
          {buzz.sources.length > 0 && (
            <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
              <div className="mb-3 text-sm font-semibold text-gray-700">
                参考来源 ({buzz.sources.length})
              </div>
              <ol className="space-y-2">
                {buzz.sources.map((s, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-50 text-xs font-bold text-indigo-600">
                      {i + 1}
                    </span>
                    <a
                      href={s.url}
                      target="_blank"
                      rel="noreferrer"
                      className="flex-1 text-indigo-600 hover:underline break-all line-clamp-2"
                      title={s.url}
                    >
                      {s.title && s.title !== `来源 ${i + 1}` ? s.title : s.url}
                    </a>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </>
      )}
    </div>
  );
}
