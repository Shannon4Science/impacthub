import { useEffect, useState, useCallback } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { api, type GrowthData, type GrowthSeries } from "@/lib/api";
import { formatNumber } from "@/lib/utils";
import { TrendingUp, TrendingDown, Minus, Loader2, BarChart3 } from "lucide-react";

interface Props {
  userId: string;
}

const METRIC_COLORS: Record<string, string> = {
  total_citations: "#6366f1",
  total_stars: "#f59e0b",
  total_downloads: "#10b981",
  total_hf_likes: "#ef4444",
  paper_count: "#8b5cf6",
  h_index: "#06b6d4",
  ccf_a_count: "#dc2626",
  ccf_b_count: "#f97316",
};

const METRIC_ORDER = [
  "total_citations",
  "total_stars",
  "total_downloads",
  "h_index",
  "paper_count",
  "ccf_a_count",
];

export default function GrowthDashboard({ userId }: Props) {
  const [data, setData] = useState<GrowthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedMetric, setSelectedMetric] = useState("total_citations");
  const [days, setDays] = useState(30);

  const fetchData = useCallback(async () => {
    try {
      const d = await api.getGrowth(userId, days);
      setData(d);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [userId, days]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-indigo-400" />
      </div>
    );
  }

  if (!data || data.series.length === 0) {
    return (
      <div className="flex flex-col items-center rounded-2xl border border-dashed border-gray-200 bg-gray-50 py-14">
        <BarChart3 className="h-10 w-10 text-gray-300" />
        <p className="mt-3 text-sm font-medium text-gray-500">暂无增量数据</p>
        <p className="mt-1 text-xs text-gray-400">
          数据快照将在每次刷新时自动记录，请稍后再来查看趋势
        </p>
      </div>
    );
  }

  const seriesMap = new Map<string, GrowthSeries>();
  for (const s of data.series) {
    seriesMap.set(s.metric, s);
  }

  const currentSeries = seriesMap.get(selectedMetric);
  const chartData = currentSeries?.data || [];

  const sortedMetrics = METRIC_ORDER.filter((m) => seriesMap.has(m));
  const otherMetrics = [...seriesMap.keys()].filter(
    (m) => !METRIC_ORDER.includes(m),
  );
  const allMetrics = [...sortedMetrics, ...otherMetrics];

  return (
    <div className="space-y-4">
      {/* Daily Deltas */}
      {Object.keys(data.daily_delta).length > 0 && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {allMetrics.map((metric) => {
            const delta = data.daily_delta[metric];
            if (delta === undefined) return null;
            const label = seriesMap.get(metric)?.label || metric;
            return (
              <DeltaCard key={metric} label={label} delta={delta} />
            );
          })}
        </div>
      )}

      {/* Chart Controls */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
        <div className="flex flex-wrap gap-1">
          {allMetrics.map((metric) => {
            const s = seriesMap.get(metric)!;
            return (
              <button
                key={metric}
                onClick={() => setSelectedMetric(metric)}
                className={`rounded-full px-2.5 py-1 text-xs font-medium transition ${
                  selectedMetric === metric
                    ? "bg-indigo-600 text-white"
                    : "bg-gray-100 text-gray-500 hover:bg-gray-200"
                }`}
              >
                {s.label}
              </button>
            );
          })}
        </div>
        <div className="flex gap-1">
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`rounded px-2 py-0.5 text-xs font-medium transition ${
                days === d
                  ? "bg-gray-900 text-white"
                  : "text-gray-400 hover:text-gray-600"
              }`}
            >
              {d}天
            </button>
          ))}
        </div>
      </div>

      {/* Chart */}
      {chartData.length > 0 ? (
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
          <h3 className="mb-3 text-sm font-semibold text-gray-700">
            {currentSeries?.label} 趋势
          </h3>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10, fill: "#94a3b8" }}
                tickFormatter={(v: string) => v.slice(5)}
              />
              <YAxis
                tick={{ fontSize: 10, fill: "#94a3b8" }}
                tickFormatter={(v: number) => formatNumber(v)}
              />
              <Tooltip
                contentStyle={{
                  borderRadius: "8px",
                  border: "1px solid #e2e8f0",
                  fontSize: 12,
                }}
                formatter={(v) => [formatNumber(v as number), currentSeries?.label]}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke={METRIC_COLORS[selectedMetric] || "#6366f1"}
                strokeWidth={2}
                dot={{ r: 3 }}
                activeDot={{ r: 5 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p className="py-8 text-center text-sm text-gray-400">
          该指标暂无数据点
        </p>
      )}
    </div>
  );
}

function DeltaCard({ label, delta }: { label: string; delta: number }) {
  const isPositive = delta > 0;
  const isZero = delta === 0;

  return (
    <div className="rounded-xl border border-gray-100 bg-white px-3 py-2.5 shadow-sm">
      <div className="text-[10px] font-medium text-gray-400">{label}</div>
      <div className="mt-0.5 flex items-center gap-1">
        {isZero ? (
          <Minus className="h-3 w-3 text-gray-300" />
        ) : isPositive ? (
          <TrendingUp className="h-3 w-3 text-emerald-500" />
        ) : (
          <TrendingDown className="h-3 w-3 text-red-500" />
        )}
        <span
          className={`text-sm font-bold ${
            isZero
              ? "text-gray-400"
              : isPositive
                ? "text-emerald-600"
                : "text-red-600"
          }`}
        >
          {isPositive ? "+" : ""}
          {formatNumber(delta)}
        </span>
      </div>
    </div>
  );
}
