import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Search, Play, Square, Loader2, CheckCircle2, XCircle, Circle,
  Sparkles, ExternalLink,
} from "lucide-react";
import { api, type PipelineDemoAdvisorHit } from "@/lib/api";

const STAGE_PLAN: Array<{ step: number; label: string; description: string }> = [
  { step: 1, label: "resolve_advisor", description: "读取导师在 DB 里的当前状态" },
  { step: 2, label: "ss_lookup",       description: "搜 Semantic Scholar 作者 ID (拼音变体 + 姓名形状过滤 + /author/{id} 存活验证)" },
  { step: 3, label: "discover",        description: "拉 SS 作者主页 + 姓名一致性 assert + 自动发现 GitHub / HuggingFace" },
  { step: 4, label: "create_user",     description: "新建 User 记录 (advisor.impacthub_user_id 留到最后一步全跑完才写)" },
  { step: 5, label: "portfolio",       description: "拉论文 (SS+DBLP) · CCF 评级 · GitHub · HuggingFace · 快照 · 学术人格" },
  { step: 6, label: "persona",         description: "学术人格 (12 类 MBTI 风格)" },
  { step: 7, label: "career",          description: "教育 + 职位时间线 (LLM + 网络搜索)" },
  { step: 8, label: "capability",      description: "多方向能力角色 (开创者/拓展者/跟随者)" },
  { step: 9, label: "buzz",            description: "网络讨论热度 (Perplexity 搜索)" },
  { step: 10, label: "trajectory",     description: "研究轨迹分析 (依赖 buzz)" },
  { step: 11, label: "ai_summary",     description: "整体 AI 摘要 + 标签 (依赖 buzz + trajectory)" },
  { step: 12, label: "finalize",       description: "全部跑完，把 advisor.impacthub_user_id 写回，正式标记为 linked" },
];

type StageStatus = "idle" | "running" | "done" | "error";
type LogEntry = { ts: number; message: string; data?: any };
type StageState = {
  status: StageStatus;
  startedAt?: number;
  duration?: number;
  data?: any;
  error?: string;
  errorData?: any;
  log: LogEntry[];
};
type FinalState = { profileUrl: string; userId: number } | null;

export default function PipelineDemoPage() {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<PipelineDemoAdvisorHit[]>([]);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [unlinkedOnly, setUnlinkedOnly] = useState(true);
  const [selected, setSelected] = useState<PipelineDemoAdvisorHit | null>(null);
  const [scholarId, setScholarId] = useState("");
  const [stages, setStages] = useState<Record<number, StageState>>({});
  const [running, setRunning] = useState(false);
  const [final, setFinal] = useState<FinalState>(null);
  const [fatal, setFatal] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  // Debounced search — empty q returns top N suggestions (sorted unlinked-with-bio).
  useEffect(() => {
    const t = setTimeout(() => {
      api.searchAdvisorForDemo(q, { unlinkedOnly, limit: 30 })
        .then(setResults)
        .catch(() => setResults([]));
    }, 250);
    return () => clearTimeout(t);
  }, [q, unlinkedOnly]);

  useEffect(() => () => { esRef.current?.close(); }, []);

  const start = () => {
    if (!selected) return;
    setStages({});
    setFinal(null);
    setFatal(null);
    setRunning(true);
    const url = `/api/pipeline/demo/stream?advisor_id=${selected.id}` +
                (scholarId.trim() ? `&scholar_id=${encodeURIComponent(scholarId.trim())}` : "");
    const es = new EventSource(url);
    esRef.current = es;
    es.onmessage = (msg) => {
      const ev = JSON.parse(msg.data);
      setStages((prev) => {
        const cur = prev[ev.step] || { status: "idle" as StageStatus, log: [] };
        if (ev.type === "step_start") {
          return { ...prev, [ev.step]: { status: "running", startedAt: ev.ts, log: [] } };
        }
        if (ev.type === "step_progress") {
          return { ...prev, [ev.step]: { ...cur, status: "running", log: [...cur.log, { ts: ev.ts, message: ev.message, data: ev.data }] } };
        }
        if (ev.type === "step_done") {
          return { ...prev, [ev.step]: { ...cur, status: "done", data: ev.data, duration: ev.duration } };
        }
        if (ev.type === "step_error") {
          return { ...prev, [ev.step]: { ...cur, status: "error", error: ev.error, errorData: ev.data } };
        }
        return prev;
      });
      if (ev.type === "done") {
        setFinal({ profileUrl: ev.profile_url, userId: ev.user_id });
        setRunning(false);
        es.close();
      } else if (ev.type === "fatal") {
        setFatal(ev.error);
        setRunning(false);
        es.close();
      }
    };
    es.onerror = () => {
      setRunning(false);
      es.close();
    };
  };

  const stop = () => {
    esRef.current?.close();
    setRunning(false);
  };

  return (
    <main className="mx-auto max-w-5xl px-4 py-6">
      <Hero />
      <Picker
        q={q} setQ={setQ}
        results={results}
        dropdownOpen={dropdownOpen}
        setDropdownOpen={setDropdownOpen}
        unlinkedOnly={unlinkedOnly}
        setUnlinkedOnly={setUnlinkedOnly}
        selected={selected}
        setSelected={(a) => { setSelected(a); setDropdownOpen(false); setQ(a.name); }}
        scholarId={scholarId} setScholarId={setScholarId}
        running={running}
        onStart={start}
        onStop={stop}
        canStart={!!selected && !running}
      />
      {fatal && (
        <div className="mb-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          致命错误：{fatal}
        </div>
      )}
      <Steps stages={stages} />
      {final && <FinalPanel final={final} />}
    </main>
  );
}

function Hero() {
  return (
    <div className="mb-6 rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50 via-white to-purple-50 p-6 shadow-sm">
      <div className="flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white">
          <Sparkles className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-gray-900">单人 Pipeline 实时验收</h1>
          <p className="text-xs text-gray-500">
            选一位导师 → 点开始 → 11 个 step 实时刷出，每步看 ✓ / ⏳ / ✗ 与产出数据
          </p>
        </div>
      </div>
    </div>
  );
}

function Picker({
  q, setQ, results, dropdownOpen, setDropdownOpen,
  unlinkedOnly, setUnlinkedOnly,
  selected, setSelected, scholarId, setScholarId, running, onStart, onStop, canStart,
}: {
  q: string; setQ: (v: string) => void;
  results: PipelineDemoAdvisorHit[];
  dropdownOpen: boolean;
  setDropdownOpen: (v: boolean) => void;
  unlinkedOnly: boolean;
  setUnlinkedOnly: (v: boolean) => void;
  selected: PipelineDemoAdvisorHit | null;
  setSelected: (a: PipelineDemoAdvisorHit) => void;
  scholarId: string; setScholarId: (v: string) => void;
  running: boolean;
  onStart: () => void; onStop: () => void;
  canStart: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setDropdownOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [setDropdownOpen]);

  return (
    <div className="mb-6 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_220px_auto]">
        <div className="relative" ref={containerRef}>
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="点开看候选老师 / 输入姓名筛选"
            value={q}
            onFocus={() => setDropdownOpen(true)}
            onChange={(e) => { setQ(e.target.value); setDropdownOpen(true); }}
            className="w-full rounded-xl border border-gray-200 bg-gray-50 pl-9 pr-3 py-2 text-sm focus:border-indigo-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-100"
          />
          {dropdownOpen && (
            <div className="absolute left-0 right-0 top-full z-20 mt-1 max-h-96 overflow-auto rounded-xl border border-gray-200 bg-white shadow-lg">
              <div className="sticky top-0 flex items-center justify-between gap-2 border-b border-gray-100 bg-gray-50/95 px-3 py-1.5 text-[11px] text-gray-500 backdrop-blur">
                <span>{q.trim() ? `搜索 "${q.trim()}"` : "未匹配老师 (按职称排序，bio 长在前)"} · {results.length} 条</span>
                <label className="flex items-center gap-1 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={unlinkedOnly}
                    onChange={(e) => setUnlinkedOnly(e.target.checked)}
                    className="h-3 w-3"
                  />
                  仅未 linked
                </label>
              </div>
              {results.length === 0 ? (
                <div className="px-3 py-6 text-center text-xs text-gray-400">没有匹配</div>
              ) : results.map((r) => (
                <button
                  key={r.id}
                  onClick={() => setSelected(r)}
                  className="flex w-full items-center justify-between gap-3 border-b border-gray-100 px-3 py-2 text-left text-sm hover:bg-indigo-50 last:border-0"
                >
                  <span className="flex-1 min-w-0">
                    <span className="font-medium text-gray-900">{r.name}</span>
                    <span className="ml-2 text-[11px] text-amber-700">{r.title}</span>
                    <div className="text-[11px] text-gray-500 truncate">{r.school} / {r.college}</div>
                  </span>
                  {r.already_linked ? (
                    <span className="shrink-0 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-700">已 linked</span>
                  ) : (
                    <span className="shrink-0 rounded-full bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-700">待整理</span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
        <input
          type="text"
          placeholder="SS authorId (可选, 跳过自动搜)"
          value={scholarId}
          onChange={(e) => setScholarId(e.target.value)}
          className="rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm focus:border-indigo-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-100"
        />
        {running ? (
          <button onClick={onStop} className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700">
            <Square className="h-4 w-4" />
            停止
          </button>
        ) : (
          <button
            disabled={!canStart}
            onClick={onStart}
            className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:bg-gray-300 disabled:text-gray-500"
          >
            <Play className="h-4 w-4" />
            开始
          </button>
        )}
      </div>
      {selected && (
        <div className="mt-3 flex items-center gap-2 text-xs text-gray-600">
          <span className="font-medium text-gray-900">{selected.name}</span>
          <span className="text-amber-700">{selected.title}</span>
          <span>·</span>
          <span>{selected.school}</span>
          <span>/</span>
          <span>{selected.college}</span>
          {selected.already_linked && (
            <span className="ml-1 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-700">已 linked (会复用 User 并刷新)</span>
          )}
        </div>
      )}
    </div>
  );
}

function Steps({ stages }: { stages: Record<number, StageState> }) {
  return (
    <div className="space-y-2">
      {STAGE_PLAN.map((p) => (
        <StepCard key={p.step} plan={p} state={stages[p.step] || { status: "idle", log: [] }} />
      ))}
    </div>
  );
}

function StepCard({ plan, state }: { plan: typeof STAGE_PLAN[number]; state: StageState }) {
  const Icon =
    state.status === "running" ? Loader2 :
    state.status === "done"    ? CheckCircle2 :
    state.status === "error"   ? XCircle : Circle;
  const iconColor =
    state.status === "running" ? "text-indigo-500 animate-spin" :
    state.status === "done"    ? "text-emerald-500" :
    state.status === "error"   ? "text-rose-500" : "text-gray-300";
  const border =
    state.status === "running" ? "border-indigo-200 bg-indigo-50/40" :
    state.status === "done"    ? "border-emerald-200 bg-emerald-50/40" :
    state.status === "error"   ? "border-rose-200 bg-rose-50/40" : "border-gray-200 bg-white";

  return (
    <div className={`rounded-xl border px-4 py-3 ${border}`}>
      <div className="flex items-start gap-3">
        <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${iconColor}`} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded bg-gray-100 text-[10px] font-bold text-gray-500">{plan.step}</span>
            <span className="font-medium text-gray-900">{plan.label}</span>
            {state.duration != null && (
              <span className="text-[11px] text-gray-400">· {state.duration.toFixed(1)}s</span>
            )}
          </div>
          <div className="mt-0.5 text-[11px] text-gray-500">{plan.description}</div>
          {state.log && state.log.length > 0 && <TraceLog log={state.log} />}
          {state.error && (
            <pre className="mt-2 overflow-x-auto rounded bg-rose-100/60 px-2 py-1 text-[11px] whitespace-pre-wrap text-rose-800">{state.error}</pre>
          )}
          {state.errorData && <ErrorDetail data={state.errorData} />}
          {state.data?.quality_warning && (
            <div className="mt-2 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-[11px] text-amber-800">
              ⚠ 质量警告 — {state.data.quality_warning}
            </div>
          )}
          {state.data && <StepData label={plan.label} data={state.data} />}
        </div>
      </div>
    </div>
  );
}

function TraceLog({ log }: { log: LogEntry[] }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="mt-2 rounded border border-gray-200 bg-gray-50/70">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-2 py-1 text-[11px] text-gray-500"
      >
        <span>📋 实时日志 ({log.length} 条)</span>
        <span>{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div className="border-t border-gray-200 px-2 py-1 font-mono text-[11px] space-y-1">
          {log.map((entry, i) => (
            <div key={i}>
              <div className="text-gray-700">{entry.message}</div>
              {entry.data?.candidates && <CandidateTable cands={entry.data.candidates} />}
              {entry.data?.queries_to_try && (
                <div className="ml-2 text-gray-500">
                  查询列表: {entry.data.queries_to_try.map((q: string) => `"${q}"`).join(" → ")}
                </div>
              )}
              {entry.data?.affiliation_tokens && entry.data.affiliation_tokens.length > 0 && (
                <div className="ml-2 text-gray-500">
                  机构锚定词: {entry.data.affiliation_tokens.join(" / ")}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CandidateTable({ cands }: { cands: any[] }) {
  if (!cands?.length) return <div className="ml-2 text-gray-400">  (0 个候选)</div>;
  return (
    <table className="ml-2 mt-0.5 w-full text-[10px]">
      <thead>
        <tr className="text-gray-400 border-b border-gray-200">
          <th className="text-left">作者 ID</th>
          <th className="text-left">姓名</th>
          <th className="text-right">h 指数</th>
          <th className="text-right">引用</th>
          <th className="text-left">机构</th>
        </tr>
      </thead>
      <tbody>
        {cands.map((c: any, i: number) => (
          <tr key={i} className="border-b border-gray-100">
            <td className="font-mono text-gray-700">{c.id}</td>
            <td className="text-gray-700">{c.name}</td>
            <td className="text-right text-gray-700">{c.h ?? "—"}</td>
            <td className="text-right text-gray-700">{c.cit ?? "—"}</td>
            <td className="text-gray-500">{(c.affs || []).join(" · ") || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ErrorDetail({ data }: { data: any }) {
  return (
    <div className="mt-2 rounded border border-rose-200 bg-rose-50/40 px-2 py-1.5 text-[11px]">
      {data.queries_tried && (
        <div className="mb-1">
          <span className="text-rose-700 font-medium">查询尝试: </span>
          <span className="font-mono text-rose-800">{data.queries_tried.map((q: string) => `"${q}"`).join(" → ")}</span>
        </div>
      )}
      {data.target_surname && (
        <div className="mb-1">
          <span className="text-rose-700 font-medium">目标姓: </span>
          <span className="font-mono text-rose-800">{data.target_surname}</span>
          {data.target_given_variants?.length > 0 && (
            <>
              <span className="text-rose-700 font-medium ml-3">名拼音变体: </span>
              <span className="font-mono text-rose-800">{data.target_given_variants.join(" / ")}</span>
            </>
          )}
        </div>
      )}
      {data.affiliation_tokens_required?.length > 0 && (
        <div className="mb-1">
          <span className="text-rose-700 font-medium">机构锚定词: </span>
          <span className="font-mono text-rose-800">{data.affiliation_tokens_required.join(" / ")}</span>
        </div>
      )}
      {data.hint && <div className="mb-1 text-rose-700">{data.hint}</div>}
      {data.all_candidates_seen?.length > 0 && (
        <details className="mt-1">
          <summary className="cursor-pointer text-rose-700">查看所有候选 ({data.all_candidates_seen.length})</summary>
          <table className="mt-1 w-full text-[10px]">
            <thead>
              <tr className="text-gray-500 border-b border-rose-200">
                <th className="text-left">查询</th>
                <th className="text-left">作者 ID</th>
                <th className="text-left">姓名</th>
                <th className="text-right">h</th>
                <th className="text-right">引用</th>
                <th className="text-left">机构</th>
                <th className="text-right">锚定命中</th>
              </tr>
            </thead>
            <tbody>
              {data.all_candidates_seen.map((c: any, i: number) => (
                <tr key={i} className="border-b border-rose-100">
                  <td className="text-gray-500">{c.query}</td>
                  <td className="font-mono text-gray-700">{c.id}</td>
                  <td className="text-gray-700">{c.name}</td>
                  <td className="text-right text-gray-700">{c.h ?? "—"}</td>
                  <td className="text-right text-gray-700">{c.cit ?? "—"}</td>
                  <td className="text-gray-500 truncate max-w-[200px]">{(c.affs || []).join(" · ") || "—"}</td>
                  <td className="text-right text-gray-700">{c.aff_overlap}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}

function StepData({ label, data }: { label: string; data: any }) {
  const entries = useMemo(() => {
    if (label === "resolve_advisor") {
      return [
        ["name", `${data.name} (${data.title || "—"})`],
        ["school/college", `${data.school} / ${data.college}`],
        ["bio", (data.bio || "—").slice(0, 200)],
        ["research_areas", (data.research_areas || []).join(", ") || "—"],
        ["homepage", data.homepage_url || "—"],
        ["已存在 User?", data.already_linked ? `Yes (User ${data.existing_user_id})` : "no"],
      ];
    }
    if (label === "ss_lookup") {
      return [
        ["scholar_id", data.scholar_id],
        ["source", data.source],
        data.name && ["SS name", data.name],
        data.h_index != null && ["h-index / cites", `${data.h_index} / ${data.citation_count}`],
        data.affiliations?.length && ["affiliations", data.affiliations.join(" · ")],
      ].filter(Boolean) as [string, any][];
    }
    if (label === "discover") {
      const ghCandidate = data.github_auto_candidate;
      const ghKept = data.github_kept;
      return [
        ["SS name", data.name || "—"],
        ["github", ghCandidate
          ? (ghKept
              ? <span className="text-emerald-700">{data.github_username} <span className="text-[10px] text-gray-500">(候选 {ghCandidate}，学校校验通过)</span></span>
              : <span className="text-rose-700">— <span className="text-[10px] text-gray-500">(候选 {ghCandidate}，未通过学校校验，已丢弃)</span></span>
            )
          : (data.github_username || "—")],
        ["hf", data.hf_username || "—"],
      ];
    }
    if (label === "create_user") {
      return [
        ["user_id", data.user_id],
        ["reused?", data.reused ? "yes" : "no"],
        ["name", data.name],
      ];
    }
    if (label === "portfolio") {
      return [
        ["papers", data.papers],
        ["github repos", data.repos],
        ["hf items", data.hf_items],
        ["snapshots", data.snapshots],
        data.top_papers?.length && ["top papers",
          <ul key="x" className="mt-1 space-y-0.5">
            {data.top_papers.map((p: any, i: number) => (
              <li key={i} className="text-[11px] text-gray-700">
                <span className="font-medium text-emerald-700">[{p.citations} cite]</span> {p.title} <span className="text-gray-400">({p.venue || "?"}, {p.year})</span>
              </li>
            ))}
          </ul>,
        ],
      ].filter(Boolean) as [string, any][];
    }
    if (label === "persona") {
      return [
        ["persona_code", data.persona_code || "—"],
        data.dimension_scores && Object.keys(data.dimension_scores).length > 0 && [
          "维度分数",
          <span key="x" className="font-mono">
            {Object.entries(data.dimension_scores).map(([k, v]: any) => `${k}=${(v as number).toFixed(2)}`).join("  ")}
          </span>,
        ],
        data.raw_metrics?.llm_reason && ["reasoning", data.raw_metrics.llm_reason],
      ].filter(Boolean) as [string, any][];
    }
    if (label === "career") {
      const timeline = data.timeline || [];
      return [
        ["现任", data.current || "—"],
        ["timeline 长度", `${timeline.length} 步`],
        ["来源", `${(data.sources || []).length} 个`],
        timeline.length > 0 && [
          "时间线",
          <ul key="t" className="ml-0 mt-1 space-y-0.5">
            {timeline.slice(0, 10).map((s: any, i: number) => (
              <li key={i} className="text-[11px] text-gray-700">
                <span className="font-mono text-gray-500">[{s.start_year}{s.end_year ? `–${s.end_year}` : ""}]</span>{" "}
                <span className="font-medium">{s.role}</span>
                {s.institution && <span className="text-gray-500"> @ {s.institution}</span>}
                {s.note && <span className="text-gray-400"> · {s.note}</span>}
              </li>
            ))}
          </ul>,
        ],
        timeline.length === 0 && [
          "⚠",
          <span key="x" className="text-amber-700">timeline 为空 — LLM 没找到该作者的公开履历信息（可能英文资料少）</span>,
        ],
      ].filter(Boolean) as [string, any][];
    }
    if (label === "capability") {
      const profs = data.profiles || [];
      return [
        ["主方向", `${data.primary_direction || "—"} (${data.primary_role || "—"})`],
        data.rationale && ["rationale", data.rationale],
        profs.length > 0 && [
          `${profs.length} 个方向`,
          <ul key="d" className="ml-0 mt-1 space-y-1">
            {profs.map((p: any, i: number) => (
              <li key={i} className="text-[11px] text-gray-700">
                <span className="font-medium">{p.direction_zh}</span>
                <span className="ml-2 rounded bg-amber-50 px-1.5 py-0.5 text-amber-700">{p.role}</span>
                <span className="ml-2 text-gray-500">权重 {((p.weight || 0) * 100).toFixed(0)}% · 评分 {p.score?.toFixed(2)}</span>
                {p.achievements && <div className="ml-2 text-gray-500">成就: {p.achievements}</div>}
                {p.representative_works?.length > 0 && (
                  <ul className="ml-3 mt-0.5">
                    {p.representative_works.slice(0, 3).map((w: any, j: number) => (
                      <li key={j} className="text-[10px] text-gray-500">· [{w.citing_count} cite] {w.title} ({w.year})</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>,
        ],
      ].filter(Boolean) as [string, any][];
    }
    if (label === "buzz") {
      return [
        ["热度", data.heat_label || "—"],
        ["主题", (data.topics || []).join(" · ") || "—"],
        ["来源", `${(data.sources || []).length} 个`],
        data.summary && ["摘要", <span key="x" className="text-gray-700">{data.summary.slice(0, 400)}</span>],
        (data.sources || []).length > 0 && [
          "源列表",
          <ul key="s" className="mt-1 space-y-0.5">
            {(data.sources || []).slice(0, 8).map((s: any, i: number) => (
              <li key={i} className="text-[11px]">
                {s.url ? <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-indigo-600 hover:underline">{s.title || s.url}</a> : <span>{s.title}</span>}
              </li>
            ))}
          </ul>,
        ],
      ].filter(Boolean) as [string, any][];
    }
    if (label === "trajectory") {
      const t = data.trajectory || {};
      const root = t.root || {};
      const branches = t.branches || t.children || [];
      return [
        root.summary && ["主线", <span key="x" className="text-gray-700">{root.summary}</span>],
        branches.length > 0 && [
          `${branches.length} 条分支`,
          <ul key="b" className="mt-1 space-y-1">
            {branches.slice(0, 6).map((br: any, i: number) => (
              <li key={i} className="text-[11px]">
                <span className="font-medium text-gray-800">{br.label || br.title || `分支 ${i + 1}`}</span>
                {br.summary && <span className="text-gray-500"> — {br.summary.slice(0, 200)}</span>}
              </li>
            ))}
          </ul>,
        ],
        !root.summary && branches.length === 0 && ["raw", <pre key="x" className="text-[10px] overflow-x-auto">{JSON.stringify(t, null, 2).slice(0, 400)}</pre>],
      ].filter(Boolean) as [string, any][];
    }
    if (label === "ai_summary") {
      return [
        ["标签", (data.tags || []).join(" · ") || "—"],
        ["摘要", <span key="x" className="text-gray-700">{data.summary || "—"}</span>],
      ];
    }
    // generic fallback
    return [
      ["status", data.ok ? "ok" : "noop"],
      data.note && ["note", data.note],
    ].filter(Boolean) as [string, any][];
  }, [label, data]);

  if (!entries.length) return null;
  return (
    <dl className="mt-2 grid grid-cols-1 gap-x-3 gap-y-1 rounded-lg bg-white/70 px-3 py-2 text-[11px] md:grid-cols-[120px_1fr]">
      {entries.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-gray-500">{k}</dt>
          <dd className="font-mono text-gray-800 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function FinalPanel({ final }: { final: NonNullable<FinalState> }) {
  return (
    <div className="mt-6 rounded-2xl border border-emerald-200 bg-emerald-50/60 p-5 shadow-sm">
      <div className="flex items-center gap-2">
        <CheckCircle2 className="h-5 w-5 text-emerald-600" />
        <span className="font-semibold text-emerald-900">全流程完成</span>
      </div>
      <div className="mt-2 text-sm text-emerald-800">
        生成的学术档案：
        <Link to={final.profileUrl} className="ml-2 inline-flex items-center gap-1 rounded-md bg-emerald-600 px-2 py-1 text-xs font-medium text-white hover:bg-emerald-700">
          <ExternalLink className="h-3 w-3" />
          /profile/{final.userId}
        </Link>
      </div>
    </div>
  );
}
