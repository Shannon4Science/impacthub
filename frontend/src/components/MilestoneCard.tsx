import { useRef } from "react";
import html2canvas from "html2canvas";
import type { Milestone, UserProfile } from "@/lib/api";
import { formatNumber } from "@/lib/utils";
import { Download, Star, Quote, Heart, Sparkles } from "lucide-react";

interface Props {
  milestone: Milestone;
  user: UserProfile;
}

const metricLabels: Record<string, string> = {
  citations: "次引用",
  stars: "个 Star",
  downloads: "次下载",
  hf_likes: "个点赞",
};

const metricConfig: Record<string, { icon: typeof Star; gradient: string }> = {
  citations: { icon: Quote, gradient: "from-violet-600 to-indigo-700" },
  stars: { icon: Star, gradient: "from-amber-500 to-orange-600" },
  downloads: { icon: Download, gradient: "from-emerald-500 to-teal-600" },
  hf_likes: { icon: Heart, gradient: "from-rose-500 to-pink-600" },
};

export default function MilestoneCard({ milestone, user }: Props) {
  const cardRef = useRef<HTMLDivElement>(null);

  const cfg = metricConfig[milestone.metric_type] || metricConfig.citations;
  const label = metricLabels[milestone.metric_type] || milestone.metric_type;
  const isTotal = milestone.metric_key === "__total__";
  const displayKey = isTotal ? "全部" : milestone.metric_key;
  const dateStr = new Date(milestone.achieved_at).toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  const handleExport = async () => {
    if (!cardRef.current) return;
    const canvas = await html2canvas(cardRef.current, {
      scale: 2,
      backgroundColor: null,
      useCORS: true,
    });
    const link = document.createElement("a");
    link.download = `里程碑-${milestone.metric_type}-${milestone.threshold}.png`;
    link.href = canvas.toDataURL("image/png");
    link.click();
  };

  return (
    <div className="relative">
      <div
        ref={cardRef}
        className={`relative overflow-hidden rounded-2xl bg-gradient-to-br ${cfg.gradient} p-8 text-white shadow-xl`}
      >
        <div className="absolute -right-12 -top-12 h-40 w-40 rounded-full bg-white/10" />
        <div className="absolute -bottom-8 -left-8 h-32 w-32 rounded-full bg-white/10" />
        <div className="absolute right-8 bottom-8 h-16 w-16 rounded-full bg-white/5" />

        <div className="relative">
          <div className="mb-4 inline-flex items-center gap-1.5 rounded-full bg-white/20 px-3 py-1 text-xs font-semibold backdrop-blur-sm">
            <Sparkles className="h-3 w-3" />
            里程碑达成
          </div>

          <div className="flex items-baseline gap-3">
            <span className="text-6xl font-extrabold tracking-tight">
              {formatNumber(milestone.threshold)}
            </span>
            <span className="text-lg font-medium text-white/70">
              {label}！
            </span>
          </div>

          <p className="mt-3 text-sm text-white/70">
            <span className="font-medium text-white">{displayKey}</span>{" "}
            已达到 {formatNumber(milestone.achieved_value)}{" "}
            {label}，于 {dateStr}
          </p>

          <div className="mt-6 flex items-center gap-3 border-t border-white/20 pt-4">
            {user.avatar_url ? (
              <img src={user.avatar_url} className="h-8 w-8 rounded-full border border-white/30" alt="" />
            ) : (
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-white/20 text-sm font-bold">
                {(user.name || "?")[0]}
              </div>
            )}
            <div>
              <div className="text-sm font-semibold">{user.name}</div>
              <div className="text-xs text-white/50">由 ImpactHub 生成</div>
            </div>
          </div>
        </div>
      </div>

      <button
        onClick={handleExport}
        className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-xl border border-gray-200 bg-white py-2 text-sm font-medium text-gray-600 shadow-sm transition hover:border-gray-300 hover:text-gray-800"
      >
        <Download className="h-3.5 w-3.5" />
        导出为图片
      </button>
    </div>
  );
}
