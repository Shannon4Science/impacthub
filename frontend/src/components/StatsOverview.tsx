import type React from "react";
import { motion } from "framer-motion";
import type { Stats, BuzzSnapshot, CitationOverview } from "@/lib/api";
import { formatNumber } from "@/lib/utils";
import {
  FileText,
  GitFork,
  Heart,
  Box,
  Flame,
  Star,
  TrendingUp,
  BookMarked,
  Award,
  Users,
  Tag,
  Loader2,
} from "lucide-react";

interface Props {
  stats: Stats;
  buzz?: BuzzSnapshot | null;
  citationOverview?: CitationOverview | null;
  userId?: string;
}

const heatConfig = {
  very_hot: { label: "极高", color: "text-red-700",    bg: "bg-red-50",     dot: "bg-red-600" },
  hot:      { label: "较高", color: "text-orange-600",  bg: "bg-orange-50",  dot: "bg-orange-500" },
  medium:   { label: "一般", color: "text-amber-600",   bg: "bg-amber-50",   dot: "bg-amber-400" },
  cold:     { label: "较低", color: "text-sky-600",     bg: "bg-sky-50",     dot: "bg-sky-400" },
  very_cold: { label: "极低", color: "text-gray-500",   bg: "bg-gray-50",    dot: "bg-gray-400" },
  "":       { label: "未抓取", color: "text-gray-400",  bg: "bg-gray-50",    dot: "bg-gray-300" },
};

function SectionHeader({ title, color }: { title: string; color: string }) {
  return (
    <div className={`mb-2 text-xs font-semibold uppercase tracking-wider ${color}`}>
      {title}
    </div>
  );
}

function MetricCell({
  label,
  value,
  sub,
  icon: Icon,
  iconClass = "text-gray-400",
}: {
  label: string;
  value: string | number | null | React.ReactNode;
  sub?: string;
  icon: typeof FileText;
  iconClass?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5 rounded-xl border border-gray-100 bg-white px-3 py-2.5 shadow-sm hover-lift">
      <div className="flex items-center gap-1 text-xs font-medium text-gray-500">
        <Icon className={`h-3 w-3 ${iconClass}`} />
        {label}
      </div>
      <div className="text-lg font-bold leading-tight text-gray-800">
        {value === null ? <span className="text-xs text-gray-300">分析中</span> : value}
      </div>
      {sub && <div className="text-xs text-gray-400">{sub}</div>}
    </div>
  );
}

export default function StatsOverview({ stats, buzz, citationOverview, userId }: Props) {
  const isEnriching = citationOverview?.honor_is_enriching;
  // Aggregate citation breakdown from per-paper analyses
  const hasAnalysis = citationOverview && citationOverview.total_papers_analyzed > 0;
  const totalInfluential = hasAnalysis
    ? citationOverview.paper_analyses.reduce((s, p) => s + p.influential_count, 0)
    : null;
  const totalTopScholar = hasAnalysis
    ? citationOverview.paper_analyses.reduce((s, p) => s + p.top_scholar_count, 0)
    : null;
  const totalNotableScholar = hasAnalysis
    ? citationOverview.paper_analyses.reduce((s, p) => s + p.notable_scholar_count, 0)
    : null;

  const buzzHeat = (buzz?.heat_label ?? "") as keyof typeof heatConfig;
  const heatCfg = heatConfig[buzzHeat] ?? heatConfig[""];

  return (
    <div className="space-y-4">
      {/* ── 学术论文 ── */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, ease: "easeOut" }}
        className="rounded-2xl border border-violet-100 bg-violet-50/40 p-4"
      >
        <SectionHeader title="学术论文" color="text-violet-500" />
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-4">
          <MetricCell label="论文数"    value={stats.paper_count}       icon={FileText}   iconClass="text-violet-400" />
          <MetricCell label="总引用"    value={stats.total_citations}    icon={TrendingUp} iconClass="text-violet-400" />
          <MetricCell label="h-index"  value={stats.h_index}            icon={Award}      iconClass="text-violet-400" />
          <MetricCell label="CCF-A"    value={stats.ccf_a_count}        icon={BookMarked} iconClass="text-violet-400" sub="顶会/期刊" />
        </div>

        {/* Citation breakdown — shown when analysis exists */}
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <MetricCell
            label="高影响力引用"
            value={citationOverview?.is_analyzing ? null : totalInfluential}
            icon={Star}
            iconClass="text-amber-400"
            sub="SS isInfluential"
          />
          <MetricCell
            label="顶级学者引用"
            value={citationOverview?.is_analyzing ? null : totalTopScholar}
            icon={Users}
            iconClass="text-indigo-400"
            sub="h-index ≥ 50"
          />
          <MetricCell
            label="知名学者引用"
            value={citationOverview?.is_analyzing ? null : totalNotableScholar}
            icon={Users}
            iconClass="text-blue-400"
            sub="h-index ≥ 25"
          />
          {/* IEEE / 院士 — LLM enrichment */}
          <div className="flex flex-col gap-0.5 rounded-xl border border-gray-100 bg-white px-3 py-2.5 shadow-sm hover-lift">
            <div className="flex items-center gap-1 text-xs font-medium text-gray-500">
              <Award className="h-3 w-3 text-amber-500" />
              IEEE / 院士
            </div>
            {citationOverview === undefined || citationOverview === null ? (
              <div className="text-lg font-bold text-gray-300">—</div>
            ) : isEnriching ? (
              <div className="flex items-center gap-1 text-sm text-amber-500">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                识别中…
              </div>
            ) : citationOverview.honor_enriched ? (
              <div className="text-lg font-bold text-amber-600">
                {formatNumber(citationOverview.honor_scholar_count)}
              </div>
            ) : citationOverview.is_analyzing ? (
              <div className="flex items-center gap-1 text-xs text-gray-400">
                <Loader2 className="h-3 w-3 animate-spin" />
                分析后自动识别
              </div>
            ) : (
              <div className="text-lg font-bold text-gray-300">—</div>
            )}
            <div className="text-xs text-gray-400">LLM 搜索识别</div>
          </div>
        </div>
      </motion.div>

      {/* ── 开源项目 ── */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, delay: 0.12, ease: "easeOut" }}
        className="rounded-2xl border border-emerald-100 bg-emerald-50/40 p-4"
      >
        <SectionHeader title="开源项目" color="text-emerald-600" />
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <MetricCell label="GitHub 仓库" value={stats.repo_count}       icon={GitFork}   iconClass="text-gray-500"   sub={`★ ${formatNumber(stats.total_stars)}`} />
          <MetricCell label="HF 项目"      value={stats.hf_count}         icon={Box}       iconClass="text-amber-500"  sub={`↓ ${formatNumber(stats.total_downloads)}`} />
          <MetricCell label="总 Fork"       value={stats.total_forks}      icon={GitFork}   iconClass="text-emerald-500" />
          <MetricCell label="HF 点赞"       value={stats.total_hf_likes}   icon={Heart}     iconClass="text-rose-400" />
        </div>
      </motion.div>

      {/* ── 网络讨论 ── */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, delay: 0.24, ease: "easeOut" }}
        className="rounded-2xl border border-orange-100 bg-orange-50/40 p-4"
      >
        <SectionHeader title="网络讨论" color="text-orange-500" />
        <div className="grid grid-cols-3 gap-2">
          {/* Heat */}
          <div className={`flex flex-col gap-0.5 rounded-xl border border-gray-100 px-3 py-2.5 shadow-sm ${heatCfg.bg}`}>
            <div className="flex items-center gap-1 text-xs font-medium text-gray-500">
              <Flame className="h-3 w-3 text-orange-400" />
              社区讨论
            </div>
            <div className={`flex items-center gap-1.5 text-lg font-bold leading-tight ${heatCfg.color}`}>
              <span className={`h-2 w-2 rounded-full ${heatCfg.dot}`} />
              {heatCfg.label}
            </div>
            {buzz?.refreshed_at && (
              <div className="text-xs text-gray-400">
                {new Date(buzz.refreshed_at).toLocaleDateString("zh-CN")}
              </div>
            )}
          </div>
          {/* Topics */}
          <div className="col-span-2 flex flex-col gap-1 rounded-xl border border-gray-100 bg-white px-3 py-2.5 shadow-sm">
            <div className="flex items-center gap-1 text-xs font-medium text-gray-500">
              <Tag className="h-3 w-3 text-orange-400" />
              讨论热词
            </div>
            {buzz?.topics && buzz.topics.length > 0 ? (
              <div className="flex flex-wrap gap-1.5 pt-0.5">
                {buzz.topics.slice(0, 8).map((t) => (
                  <span key={t} className="rounded-full bg-orange-100 px-2 py-0.5 text-xs text-orange-700">
                    {t}
                  </span>
                ))}
                {buzz.topics.length > 8 && (
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-400">
                    +{buzz.topics.length - 8}
                  </span>
                )}
              </div>
            ) : (
              <div className="text-lg font-bold text-gray-300">—</div>
            )}
          </div>
        </div>
      </motion.div>
    </div>
  );
}
