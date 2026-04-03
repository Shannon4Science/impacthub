import { useEffect, useState, useRef } from "react";
import { motion } from "framer-motion";
import type { UserProfile, Stats, AISummary } from "@/lib/api";
import { formatNumber } from "@/lib/utils";
import { BookOpen, Star, Download, Award, Link2, Sparkles, Loader2, RefreshCw } from "lucide-react";

interface Props {
  user: UserProfile;
  stats: Stats;
  aiSummary?: AISummary | null;
  aiSummaryLoading?: boolean;
  onGenerateAISummary?: () => void;
  onLinkAccounts?: () => void;
}

/** Hook: animate a number from 0 to target over `duration` ms */
function useCountUp(target: number, duration = 1200): number {
  const [val, setVal] = useState(0);
  const rafRef = useRef(0);
  useEffect(() => {
    const start = performance.now();
    const tick = (now: number) => {
      const p = Math.min((now - start) / duration, 1);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - p, 3);
      setVal(Math.round(eased * target));
      if (p < 1) rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [target, duration]);
  return val;
}

const statItems = [
  { key: "total_citations" as const, label: "总引用", icon: BookOpen, color: "text-violet-600 bg-violet-100" },
  { key: "total_stars" as const, label: "GitHub Stars", icon: Star, color: "text-amber-600 bg-amber-100" },
  { key: "total_downloads" as const, label: "总下载", icon: Download, color: "text-emerald-600 bg-emerald-100" },
  { key: "h_index" as const, label: "h-index", icon: Award, color: "text-blue-600 bg-blue-100" },
];

const platforms = [
  { field: "scholar_id" as const, name: "Semantic Scholar", url: (v: string) => `https://www.semanticscholar.org/author/${v}` },
  { field: "github_username" as const, name: "GitHub", url: (v: string) => `https://github.com/${v}` },
  { field: "hf_username" as const, name: "Hugging Face", url: (v: string) => `https://huggingface.co/${v}` },
  { field: "homepage" as const, name: "个人主页", url: (v: string) => v.startsWith("http") ? v : `https://${v}` },
];

export default function HeroSection({ user, stats, aiSummary, aiSummaryLoading, onGenerateAISummary, onLinkAccounts }: Props) {
  const citationCount = useCountUp(stats.total_citations);
  const starCount = useCountUp(stats.total_stars);
  const downloadCount = useCountUp(stats.total_downloads);
  const hIndex = useCountUp(stats.h_index, 800);

  const animatedStats: Record<string, number> = {
    total_citations: citationCount,
    total_stars: starCount,
    total_downloads: downloadCount,
    h_index: hIndex,
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, ease: "easeOut" }}
      className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-indigo-600 via-purple-600 to-indigo-700 p-8 text-white shadow-xl sm:p-12"
    >
      {/* Animated decorative circles */}
      <div className="absolute -right-20 -top-20 h-64 w-64 rounded-full bg-white/5 animate-float" />
      <div className="absolute -bottom-16 -left-16 h-48 w-48 rounded-full bg-white/5 animate-float" style={{ animationDelay: "1.5s" }} />

      <div className="relative flex flex-col items-center gap-6 sm:flex-row sm:items-start">
        {user.avatar_url ? (
          <img
            src={user.avatar_url}
            alt={user.name}
            className="h-24 w-24 rounded-2xl border-4 border-white/20 shadow-lg"
          />
        ) : (
          <div className="flex h-24 w-24 items-center justify-center rounded-2xl border-4 border-white/20 bg-white/10 text-3xl font-bold">
            {(user.name || "?")[0]}
          </div>
        )}
        <div className="text-center sm:text-left">
          <h1 className="text-3xl font-bold tracking-tight">{user.name || "研究者"}</h1>
          {user.bio && <p className="mt-1 text-white/70">{user.bio}</p>}
          <div className="mt-2 flex flex-wrap justify-center gap-2 text-xs sm:justify-start">
            {platforms.map((p) => {
              const value = user[p.field];
              if (!value) return null;
              return (
                <a
                  key={p.field}
                  href={p.url(value)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-full bg-white/10 px-2.5 py-0.5 text-white/50 transition hover:bg-white/20 hover:text-white/80"
                >
                  {p.name}
                </a>
              );
            })}
          </div>
        </div>
      </div>

      {aiSummary ? (
        <div className="relative mt-5">
          <div className="mb-2 flex flex-wrap items-center gap-1.5">
            {aiSummary.tags.map((tag) => (
              <span
                key={tag}
                className="rounded-full bg-white/10 px-2.5 py-0.5 text-xs font-medium text-white/80 backdrop-blur-sm"
              >
                {tag}
              </span>
            ))}
            {onGenerateAISummary && (
              <button
                onClick={onGenerateAISummary}
                disabled={aiSummaryLoading}
                className="ml-auto flex items-center gap-1 rounded-full bg-white/10 px-2 py-0.5 text-[10px] text-white/50 transition hover:bg-white/20 hover:text-white/80 disabled:opacity-50"
                title="重新生成"
              >
                {aiSummaryLoading ? <Loader2 className="h-2.5 w-2.5 animate-spin" /> : <RefreshCw className="h-2.5 w-2.5" />}
              </button>
            )}
          </div>
          <p className="text-sm leading-relaxed text-white/60">{aiSummary.summary}</p>
        </div>
      ) : (
        onGenerateAISummary && (
          <button
            onClick={onGenerateAISummary}
            disabled={aiSummaryLoading}
            className="relative mt-5 flex w-full items-center gap-2 rounded-xl bg-white/10 px-4 py-2.5 text-left text-xs text-white/70 backdrop-blur-sm transition hover:bg-white/15 disabled:opacity-50"
          >
            {aiSummaryLoading ? (
              <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-white/50" />
            ) : (
              <Sparkles className="h-3.5 w-3.5 shrink-0 text-white/50" />
            )}
            <span className="flex-1">
              {aiSummaryLoading ? "AI 正在生成个人总结与趣味标签..." : "生成 AI 个人总结与趣味标签"}
            </span>
            {!aiSummaryLoading && (
              <span className="flex shrink-0 items-center gap-1 rounded-full bg-white/20 px-2.5 py-0.5 text-[10px] font-semibold text-white">
                生成
              </span>
            )}
          </button>
        )
      )}

      {!user.homepage && (
        <button
          onClick={onLinkAccounts}
          className="relative mt-5 flex w-full items-center gap-2 rounded-xl bg-white/10 px-4 py-2.5 text-left text-xs text-white/70 backdrop-blur-sm transition hover:bg-white/15"
        >
          <Link2 className="h-3.5 w-3.5 shrink-0 text-white/50" />
          <span className="flex-1">
            添加个人主页链接，展示在你的档案中
          </span>
          <span className="flex shrink-0 items-center gap-1 rounded-full bg-white/20 px-2.5 py-0.5 text-[10px] font-semibold text-white">
            添加
          </span>
        </button>
      )}

      <div className="relative mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {statItems.map(({ key, label, icon: Icon, color }, i) => (
          <motion.div
            key={key}
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.3 + i * 0.1, ease: "easeOut" }}
            className="rounded-2xl bg-white/10 px-4 py-3 backdrop-blur-sm transition-all duration-300 hover:bg-white/15"
          >
            <div className="flex items-center gap-2">
              <div className={`rounded-lg p-1.5 ${color}`}>
                <Icon className="h-3.5 w-3.5" />
              </div>
              <span className="text-xs text-white/60">{label}</span>
            </div>
            <div className="mt-1 text-2xl font-bold tabular-nums">
              {formatNumber(animatedStats[key])}
            </div>
          </motion.div>
        ))}
      </div>
    </motion.div>
  );
}
