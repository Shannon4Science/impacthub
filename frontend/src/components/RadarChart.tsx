import { useState, useRef } from "react";
import { motion } from "framer-motion";
import {
  Radar,
  RadarChart as RechartsRadar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
} from "recharts";
import { HelpCircle } from "lucide-react";
import type { Stats } from "@/lib/api";

interface Props {
  stats: Stats;
  buzzHeat?: string;
}

/**
 * Square-root normalization — gentler than log, smoother than linear.
 *   sqrtNorm(100,  20000) ≈  7%
 *   sqrtNorm(1000, 20000) ≈ 22%
 *   sqrtNorm(5000, 20000) ≈ 50%
 *   sqrtNorm(10000,20000) ≈ 71%
 *   sqrtNorm(20000,20000) = 100%
 */
function sqrtNorm(value: number, max: number) {
  if (value <= 0 || max <= 0) return 0;
  return Math.min(Math.round(Math.sqrt(value / max) * 100), 100);
}

export default function RadarChart({ stats, buzzHeat }: Props) {
  const commValue =
    buzzHeat === "very_hot" ? 95 :
    buzzHeat === "hot" ? 75 :
    buzzHeat === "medium" ? 50 :
    buzzHeat === "cold" ? 25 :
    buzzHeat === "very_cold" ? 10 : 0;

  const MIN = 10; // 保底值，避免雷达图塌陷

  const data = [
    { dimension: "学术深度", value: Math.max(MIN, sqrtNorm(stats.total_citations, 10000)) },
    { dimension: "代码影响", value: Math.max(MIN, sqrtNorm(stats.total_stars + stats.total_forks, 10000)) },
    { dimension: "数据贡献", value: Math.max(MIN, sqrtNorm(stats.total_downloads + stats.total_hf_likes, 100000)) },
    { dimension: "产出广度", value: Math.max(MIN, sqrtNorm(stats.paper_count + stats.repo_count + stats.hf_count, 200)) },
    { dimension: "h-index", value: Math.max(MIN, sqrtNorm(stats.h_index, 60)) },
    { dimension: "社区影响", value: Math.max(MIN, commValue) },
  ];

  const criteria = [
    { dim: "学术深度", desc: "总引用数", max: "10,000", unit: "引用" },
    { dim: "代码影响", desc: "GitHub Stars + Forks", max: "10,000", unit: "" },
    { dim: "数据贡献", desc: "HF 下载量 + HF 点赞", max: "100,000", unit: "" },
    { dim: "产出广度", desc: "论文 + 仓库 + HF 项目", max: "200", unit: "项" },
    { dim: "h-index", desc: "h 指数", max: "60", unit: "" },
    { dim: "社区影响", desc: "社区讨论热度", max: "", unit: "" },
  ];

  const [showCriteria, setShowCriteria] = useState(false);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleEnter = () => {
    if (hideTimer.current) {
      clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
    setShowCriteria(true);
  };

  const handleLeave = () => {
    hideTimer.current = setTimeout(() => setShowCriteria(false), 150);
  };

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.5, ease: "easeOut" }}
      className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm"
    >
      <div
        className="relative mb-4 inline-flex items-center gap-1.5"
        onMouseEnter={handleEnter}
        onMouseLeave={handleLeave}
      >
        <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-400">
          影响力雷达
        </h3>
        <button
          type="button"
          className="rounded-full text-gray-400 transition hover:text-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-300"
          aria-label="评分标准说明"
        >
          <HelpCircle className="h-4 w-4" />
        </button>
        {showCriteria && (
          <div
            className="absolute left-0 top-full z-10 mt-1 w-72 rounded-lg border border-gray-200 bg-white px-4 py-3 shadow-lg"
            onMouseEnter={handleEnter}
            onMouseLeave={handleLeave}
          >
            <p className="mb-2 text-xs font-medium text-gray-500">各维度评分标准（√缩放，满分 100）</p>
            <ul className="space-y-1 text-xs text-gray-600">
              {criteria.map((c) => (
                <li key={c.dim}>
                  <span className="font-medium text-gray-700">{c.dim}</span>：{c.desc} / {c.max}
                  {c.unit && ` ${c.unit}`}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <RechartsRadar cx="50%" cy="50%" outerRadius="70%" data={data}>
          <PolarGrid stroke="#e2e8f0" />
          <PolarAngleAxis dataKey="dimension" tick={{ fontSize: 11, fill: "#64748b" }} />
          <PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} axisLine={false} />
          <Radar
            dataKey="value"
            stroke="#6366f1"
            fill="#6366f1"
            fillOpacity={0.2}
            strokeWidth={2}
            animationDuration={1200}
            animationEasing="ease-out"
          />
        </RechartsRadar>
      </ResponsiveContainer>
    </motion.div>
  );
}
