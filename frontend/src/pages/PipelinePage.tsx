import { useEffect, useState } from "react";
import {
  Database, Layers, Activity, RefreshCw, ChevronDown, ChevronRight,
  CheckCircle2, AlertCircle, Loader2,
} from "lucide-react";
import { api, type PipelineStatus, type PipelineStage } from "@/lib/api";

const LAYER_META = {
  crawl: {
    title: "信息爬取层",
    subtitle: "raw external data → DB",
    accent: "from-sky-500 to-cyan-500",
    Icon: Database,
  },
  analyze: {
    title: "整合分析层",
    subtitle: "LLM-derived per-User tabs",
    accent: "from-violet-500 to-fuchsia-500",
    Icon: Layers,
  },
} as const;

export default function PipelinePage() {
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastFetched, setLastFetched] = useState<Date | null>(null);

  const load = async () => {
    setRefreshing(true);
    try {
      const data = await api.getPipelineStatus();
      setStatus(data);
      setLastFetched(new Date());
    } finally {
      setRefreshing(false);
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  if (loading) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-16 text-center text-gray-400">
        <Loader2 className="mx-auto h-6 w-6 animate-spin" />
      </main>
    );
  }
  if (!status) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-16 text-center text-gray-400">
        无法读取 pipeline 状态
      </main>
    );
  }

  const totals = (stages: PipelineStage[]) => {
    const expected = stages.reduce((a, s) => a + s.expected, 0);
    const done = stages.reduce((a, s) => a + s.done, 0);
    const complete = stages.filter((s) => s.expected > 0 && s.done >= s.expected).length;
    return { expected, done, complete, total: stages.length };
  };
  const crawlTotals = totals(status.crawl);
  const analyzeTotals = totals(status.analyze);

  return (
    <main className="mx-auto max-w-5xl px-4 py-6">
      <Hero
        lastFetched={lastFetched}
        refreshing={refreshing}
        onRefresh={load}
        crawlTotals={crawlTotals}
        analyzeTotals={analyzeTotals}
      />
      <Layer layer="crawl" stages={status.crawl} />
      <Layer layer="analyze" stages={status.analyze} />
      <Legend />
    </main>
  );
}

function Hero({ lastFetched, refreshing, onRefresh, crawlTotals, analyzeTotals }: {
  lastFetched: Date | null;
  refreshing: boolean;
  onRefresh: () => void;
  crawlTotals: ReturnType<typeof totalShape>;
  analyzeTotals: ReturnType<typeof totalShape>;
}) {
  return (
    <div className="mb-6 rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50 via-white to-purple-50 p-6 shadow-sm">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white">
            <Activity className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Pipeline 验收</h1>
            <p className="text-xs text-gray-500">
              CS/AI scope · 清北华五 · {lastFetched ? `最后刷新 ${lastFetched.toLocaleTimeString()}` : "—"}
            </p>
          </div>
        </div>
        <button
          onClick={onRefresh}
          disabled={refreshing}
          className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-white px-3 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-50 disabled:opacity-50"
        >
          {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          刷新
        </button>
      </div>
      <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <HeroStat label="爬取 stages 完成" value={`${crawlTotals.complete}/${crawlTotals.total}`} accent="text-sky-700" />
        <HeroStat label="爬取数据点" value={`${crawlTotals.done}/${crawlTotals.expected}`} accent="text-sky-700" />
        <HeroStat label="分析 tabs 完成" value={`${analyzeTotals.complete}/${analyzeTotals.total}`} accent="text-violet-700" />
        <HeroStat label="分析数据点" value={`${analyzeTotals.done}/${analyzeTotals.expected}`} accent="text-violet-700" />
      </div>
    </div>
  );
}

function totalShape() {
  return { expected: 0, done: 0, complete: 0, total: 0 };
}

function HeroStat({ label, value, accent }: { label: string; value: string; accent: string }) {
  return (
    <div className="rounded-xl bg-white/70 px-3 py-2 ring-1 ring-gray-200">
      <div className={`text-base font-bold tabular-nums ${accent}`}>{value}</div>
      <div className="text-[10px] uppercase tracking-wider text-gray-400">{label}</div>
    </div>
  );
}

function Layer({ layer, stages }: { layer: "crawl" | "analyze"; stages: PipelineStage[] }) {
  const meta = LAYER_META[layer];
  const { Icon } = meta;
  return (
    <section className="mb-6 overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm">
      <header className="flex items-center justify-between border-b border-gray-100 px-5 py-3">
        <div className="flex items-center gap-2.5">
          <div className={`flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br ${meta.accent} text-white`}>
            <Icon className="h-4 w-4" />
          </div>
          <div>
            <div className="text-sm font-semibold text-gray-900">{meta.title}</div>
            <div className="text-[11px] text-gray-500">{meta.subtitle}</div>
          </div>
        </div>
        <code className="rounded bg-gray-50 px-2 py-1 text-[11px] text-gray-500">pipeline/{layer}/</code>
      </header>
      <div className="divide-y divide-gray-100">
        {stages.map((s) => (
          <StageRow key={s.id} layer={layer} stage={s} />
        ))}
      </div>
    </section>
  );
}

function StageRow({ layer, stage }: { layer: "crawl" | "analyze"; stage: PipelineStage }) {
  const [open, setOpen] = useState(false);
  const pct = stage.expected > 0 ? (stage.done / stage.expected) * 100 : 0;
  const isComplete = stage.expected > 0 && stage.done >= stage.expected;
  const hasMissing = stage.missing_examples.length > 0;
  const barColor =
    pct >= 100 ? "bg-emerald-500" :
    pct >= 70  ? "bg-sky-500" :
    pct >= 30  ? "bg-amber-500" : "bg-rose-500";
  const stageFile =
    layer === "crawl"
      ? `0${stage.id}_${stage.label}.py`
      : `0${stage.id}_${stage.label}.py`;

  return (
    <div className="px-5 py-3">
      <button
        onClick={() => hasMissing && setOpen(!open)}
        className="flex w-full items-center gap-3 text-left"
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gray-100 text-xs font-bold text-gray-500">
          {stage.id}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-gray-900">{stage.label}</span>
            {isComplete ? (
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
            ) : (
              <AlertCircle className="h-3.5 w-3.5 text-amber-500" />
            )}
            <code className="rounded bg-gray-50 px-1.5 py-0.5 text-[10px] text-gray-400">{stageFile}</code>
          </div>
          <div className="mt-0.5 truncate text-[11px] text-gray-500">{stage.description}</div>
        </div>
        <div className="hidden shrink-0 text-right md:block">
          <div className="tabular-nums text-sm font-semibold text-gray-900">
            {stage.done} <span className="text-gray-400">/ {stage.expected}</span>
          </div>
          <div className="text-[11px] text-gray-400">{pct.toFixed(1)}%</div>
        </div>
        {hasMissing && (open ? <ChevronDown className="h-4 w-4 text-gray-400" /> : <ChevronRight className="h-4 w-4 text-gray-400" />)}
      </button>

      {/* Progress bar */}
      <div className="ml-10 mt-2">
        <div className="h-2 w-full overflow-hidden rounded-full bg-gray-100">
          <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${Math.min(100, pct)}%` }} />
        </div>
        <div className="mt-1 flex justify-between text-[10px] text-gray-400 md:hidden">
          <span>{stage.done}/{stage.expected}</span>
          <span>{pct.toFixed(1)}%</span>
        </div>
      </div>

      {/* Expandable missing examples */}
      {open && hasMissing && (
        <div className="ml-10 mt-3 rounded-lg border border-amber-100 bg-amber-50/50 px-3 py-2">
          <div className="text-[11px] font-medium text-amber-700">缺失样本 (前 5)</div>
          <ul className="mt-1.5 space-y-0.5">
            {stage.missing_examples.map((m, i) => (
              <li key={i} className="text-[11px] text-amber-800/80">· {m}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Legend() {
  return (
    <div className="mt-4 rounded-xl border border-gray-100 bg-gray-50/50 px-4 py-3 text-[11px] text-gray-500">
      <span className="font-medium text-gray-700">读法：</span>
      每个 stage 对应 <code className="rounded bg-white px-1">pipeline/&lt;layer&gt;/&lt;NN_name&gt;.py</code> 一个脚本 ·
      <span className="ml-1.5 inline-flex items-center gap-0.5"><CheckCircle2 className="h-3 w-3 text-emerald-500" /> 跑满</span> ·
      <span className="ml-1.5 inline-flex items-center gap-0.5"><AlertCircle className="h-3 w-3 text-amber-500" /> 有 gap，点开看样本</span> ·
      数据全部从 <code className="rounded bg-white px-1">backend/data/impacthub.db</code> 实时查询
    </div>
  );
}
