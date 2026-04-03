import { forwardRef } from "react";
import type { UserProfile, Stats, BuzzSnapshot, CitationOverview, AISummary as AISummaryType } from "@/lib/api";
import { formatNumber } from "@/lib/utils";

function proxyUrl(url: string): string {
  if (!url) return "";
  return `/api/proxy/image?url=${encodeURIComponent(url)}`;
}

interface Props {
  user: UserProfile;
  stats: Stats;
  buzz?: BuzzSnapshot | null;
  citationOverview?: CitationOverview | null;
  aiSummary?: AISummaryType | null;
}

/* ── helpers ─────────────────────────────────────────────────────────────── */

function norm(v: number, max: number) {
  if (v <= 0 || max <= 0) return 0;
  return Math.min(Math.sqrt(v / max), 1);
}

function pt(cx: number, cy: number, r: number, angle: number, value: number) {
  const rad = (angle - 90) * (Math.PI / 180);
  return { x: cx + r * value * Math.cos(rad), y: cy + r * value * Math.sin(rad) };
}

const HEAT: Record<string, { text: string; color: string; bg: string }> = {
  very_hot: { text: "极高", color: "#dc2626", bg: "rgba(220,38,38,0.12)" },
  hot:      { text: "较高", color: "#fb923c", bg: "rgba(251,146,60,0.15)" },
  medium:   { text: "一般", color: "#facc15", bg: "rgba(250,204,21,0.12)" },
  cold:     { text: "较低", color: "#38bdf8", bg: "rgba(56,189,248,0.12)" },
  very_cold: { text: "极低", color: "#94a3b8", bg: "rgba(148,163,184,0.1)" },
};

/* ── Inline SVG icons (16×16, for html-to-image compat) ────────────────── */

const ico = {
  cite: (c: string) => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 21c3 0 7-1 7-8V5c0-1.25-.756-2.017-2-2H4c-1.25 0-2 .75-2 1.972V11c0 1.25.75 2 2 2 1 0 1 0 1 1v1c0 1-1 2-2 2s-1 .008-1 1.031V21z"/><path d="M15 21c3 0 7-1 7-8V5c0-1.25-.757-2.017-2-2h-4c-1.25 0-2 .75-2 1.972V11c0 1.25.75 2 2 2h.75c0 2.25.25 4-2.75 5v3z"/></svg>,
  hIdx: (c: string) => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/></svg>,
  paper: (c: string) => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/></svg>,
  star: (c: string) => <svg width="14" height="14" viewBox="0 0 24 24" fill={c} stroke={c} strokeWidth="1.5"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>,
  award: (c: string) => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="8" r="6"/><path d="M15.477 12.89 17 22l-5-3-5 3 1.523-9.11"/></svg>,
  bolt: (c: string) => <svg width="13" height="13" viewBox="0 0 24 24" fill={c} stroke={c} strokeWidth="1"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>,
  crown: (c: string) => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M11.562 3.266a.5.5 0 0 1 .876 0L15.39 8.87a1 1 0 0 0 1.516.294L21.183 5.5a.5.5 0 0 1 .798.519l-2.834 10.246a1 1 0 0 1-.956.734H5.81a1 1 0 0 1-.957-.734L2.02 6.02a.5.5 0 0 1 .798-.519l4.276 3.664a1 1 0 0 0 1.516-.294z"/><path d="M5.5 21h13"/></svg>,
  userOk: (c: string) => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><polyline points="16 11 18 13 22 9"/></svg>,
  shield: (c: string) => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/></svg>,
  code: (c: string) => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>,
  fork: (c: string) => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><path d="M18 9v2c0 .6-.4 1-1 1H7c-.6 0-1-.4-1-1V9"/><path d="M12 12v3"/></svg>,
  box: (c: string) => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/></svg>,
  dl: (c: string) => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>,
  flame: (c: string) => <svg width="14" height="14" viewBox="0 0 24 24" fill={c} stroke={c} strokeWidth="1"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/></svg>,
  chat: (c: string) => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/></svg>,
};

/* ── SVG Radar ───────────────────────────────────────────────────────────── */

function RadarSvg({ stats, buzzHeat }: { stats: Stats; buzzHeat: string }) {
  const cx = 130, cy = 130, R = 100;
  const commV = buzzHeat === "very_hot" ? 0.95 : buzzHeat === "hot" ? 0.75 : buzzHeat === "medium" ? 0.5 : buzzHeat === "cold" ? 0.25 : buzzHeat === "very_cold" ? 0.1 : 0;

  const dims = [
    { label: "学术深度", v: norm(stats.total_citations, 10000), color: "#60a5fa" },
    { label: "代码影响", v: norm(stats.total_stars + stats.total_forks, 20000), color: "#34d399" },
    { label: "数据贡献", v: norm(stats.total_downloads + stats.total_hf_likes, 100000), color: "#a78bfa" },
    { label: "产出广度", v: norm(stats.paper_count + stats.repo_count + stats.hf_count, 200), color: "#fbbf24" },
    { label: "h-index", v: norm(stats.h_index, 60), color: "#f472b6" },
    { label: "社区影响", v: commV, color: "#fb923c" },
  ];
  const n = dims.length;
  const angles = dims.map((_, i) => (360 / n) * i);

  const ring = (frac: number) =>
    angles.map((a) => pt(cx, cy, R, a, frac)).map((p, i) => `${i ? "L" : "M"}${p.x},${p.y}`).join(" ") + "Z";

  const data =
    dims.map(({ v }, i) => pt(cx, cy, R, angles[i], Math.max(v, 0.05))).map((p, i) => `${i ? "L" : "M"}${p.x},${p.y}`).join(" ") + "Z";

  const lblR = R + 22;

  return (
    <svg width={260} height={260} viewBox="0 0 260 260" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="rFill" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="rgba(96,165,250,0.3)" />
          <stop offset="50%" stopColor="rgba(167,139,250,0.25)" />
          <stop offset="100%" stopColor="rgba(52,211,153,0.2)" />
        </linearGradient>
      </defs>
      {[0.25, 0.5, 0.75, 1].map((f) => (
        <path key={f} d={ring(f)} fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth={0.8} />
      ))}
      {angles.map((a, i) => {
        const o = pt(cx, cy, R, a, 1);
        return <line key={i} x1={cx} y1={cy} x2={o.x} y2={o.y} stroke="rgba(255,255,255,0.05)" strokeWidth={0.8} />;
      })}
      <path d={data} fill="url(#rFill)" stroke="rgba(196,181,253,0.7)" strokeWidth={1.8} />
      {dims.map(({ v, color }, i) => {
        const p = pt(cx, cy, R, angles[i], Math.max(v, 0.05));
        return <circle key={i} cx={p.x} cy={p.y} r={3.5} fill={color} />;
      })}
      {dims.map(({ label, color }, i) => {
        const p = pt(cx, cy, lblR, angles[i], 1);
        return (
          <text key={i} x={p.x} y={p.y} textAnchor="middle" dominantBaseline="central" fontSize={10} fontWeight={600} fill={color} fillOpacity={0.85} fontFamily="'Inter','Noto Sans SC',system-ui,sans-serif">
            {label}
          </text>
        );
      })}
    </svg>
  );
}

/* ── Main Card ───────────────────────────────────────────────────────────── */

const ShareCard = forwardRef<HTMLDivElement, Props>(({ user, stats, buzz, citationOverview, aiSummary }, ref) => {
  const buzzHeat = buzz?.heat_label ?? "";
  const heat = HEAT[buzzHeat];
  const hasCA = citationOverview && citationOverview.total_papers_analyzed > 0;
  const influential = hasCA ? citationOverview.paper_analyses.reduce((a, p) => a + p.influential_count, 0) : 0;
  const topScholars = hasCA ? citationOverview.paper_analyses.reduce((a, p) => a + p.top_scholar_count, 0) : 0;
  const notableScholars = hasCA ? citationOverview.paper_analyses.reduce((a, p) => a + p.notable_scholar_count, 0) : 0;
  const honorCount = citationOverview?.honor_scholar_count ?? 0;

  return (
    <div ref={ref} style={{ width: 540, fontFamily: "'Inter','Noto Sans SC',system-ui,sans-serif", background: "linear-gradient(150deg, #0f172a 0%, #1e1b4b 45%, #1a1333 100%)", borderRadius: 24, overflow: "hidden", color: "white", position: "relative" }}>
      {/* Rainbow top accent */}
      <div style={{ height: 3, background: "linear-gradient(90deg, #60a5fa, #818cf8, #a78bfa, #c084fc, #e879f9, #fb923c)" }} />

      <div style={{ padding: "30px 32px 24px", position: "relative" }}>
        {/* Decorative blobs */}
        <div style={{ position: "absolute", top: -30, right: -30, width: 140, height: 140, borderRadius: "50%", background: "radial-gradient(circle, rgba(99,102,241,0.12), transparent 70%)" }} />
        <div style={{ position: "absolute", bottom: 40, left: -40, width: 160, height: 160, borderRadius: "50%", background: "radial-gradient(circle, rgba(168,85,247,0.08), transparent 70%)" }} />

        {/* ── Header ── */}
        <div style={{ display: "flex", alignItems: "center", gap: 16, position: "relative" }}>
          {user.avatar_url ? (
            <img src={proxyUrl(user.avatar_url)} alt="" style={{ width: 60, height: 60, borderRadius: 14, border: "2px solid rgba(255,255,255,0.12)", objectFit: "cover", flexShrink: 0 }} />
          ) : (
            <div style={{ width: 60, height: 60, borderRadius: 14, border: "2px solid rgba(255,255,255,0.12)", background: "linear-gradient(135deg, rgba(99,102,241,0.3), rgba(168,85,247,0.3))", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 24, fontWeight: 700, flexShrink: 0 }}>
              {(user.name || "?")[0]}
            </div>
          )}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 20, fontWeight: 800, letterSpacing: -0.3 }}>{user.name || "研究者"}</div>
            {aiSummary?.summary ? (
              <div style={{ marginTop: 2, fontSize: 11, color: "rgba(255,255,255,0.65)", lineHeight: 1.5 }}>{aiSummary.summary}</div>
            ) : user.bio ? (
              <div style={{ marginTop: 2, fontSize: 11, color: "rgba(255,255,255,0.45)", lineHeight: 1.4, overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>{user.bio}</div>
            ) : null}
            <div style={{ marginTop: 6, display: "flex", gap: 5, flexWrap: "wrap" }}>
              {user.github_username && <PlatformTag icon="gh" text={`@${user.github_username}`} />}
              {user.scholar_id && <PlatformTag icon="ss" text="Scholar" />}
              {user.hf_username && <PlatformTag icon="hf" text="HuggingFace" />}
              {aiSummary?.tags?.map((tag) => (
                <span key={tag} style={{ display: "inline-flex", alignItems: "center", background: "rgba(167,139,250,0.15)", border: "1px solid rgba(167,139,250,0.25)", borderRadius: 20, padding: "2px 9px", fontSize: 10, fontWeight: 600, color: "rgba(167,139,250,0.9)" }}>{tag}</span>
              ))}
            </div>
          </div>
        </div>

        {/* ── Key numbers ── */}
        <div style={{ marginTop: 20, display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8 }}>
          <BigNum icon={ico.cite("#60a5fa")} label="总引用" value={stats.total_citations} accent="rgba(96,165,250,0.1)" border="rgba(96,165,250,0.2)" />
          <BigNum icon={ico.hIdx("#f472b6")} label="h-index" value={stats.h_index} accent="rgba(244,114,182,0.1)" border="rgba(244,114,182,0.2)" />
          <BigNum icon={ico.paper("#a78bfa")} label="论文数" value={stats.paper_count} accent="rgba(167,139,250,0.1)" border="rgba(167,139,250,0.2)" />
          <BigNum icon={ico.star("#fbbf24")} label="Stars" value={stats.total_stars} accent="rgba(251,191,36,0.1)" border="rgba(251,191,36,0.2)" />
        </div>

        {/* ── Radar + details ── */}
        <div style={{ marginTop: 14, display: "flex", gap: 8, alignItems: "center" }}>
          <div style={{ flexShrink: 0 }}>
            <RadarSvg stats={stats} buzzHeat={buzzHeat} />
          </div>

          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6 }}>
            {/* 学术 */}
            <SectionBox title="学术论文" color="#60a5fa">
              {stats.ccf_a_count > 0 && <Mini icon={ico.award("#fbbf24")} label="CCF-A" value={stats.ccf_a_count} />}
              {stats.ccf_b_count > 0 && <Mini icon={ico.award("#94a3b8")} label="CCF-B" value={stats.ccf_b_count} />}
              {influential > 0 && <Mini icon={ico.bolt("#fb923c")} label="高影响力引用" value={influential} />}
              {topScholars > 0 && <Mini icon={ico.crown("#fbbf24")} label="顶级学者引用" value={topScholars} hint="h≥50" />}
              {notableScholars > 0 && <Mini icon={ico.userOk("#34d399")} label="知名学者引用" value={notableScholars} hint="h≥30" />}
              {honorCount > 0 && <Mini icon={ico.shield("#e879f9")} label="IEEE Fellow/院士引用" value={honorCount} />}
            </SectionBox>

            {/* 开源 */}
            <SectionBox title="开源项目" color="#34d399">
              <Mini icon={ico.code("#34d399")} label="github仓库" value={stats.repo_count} />
              <Mini icon={ico.fork("#94a3b8")} label="Forks" value={stats.total_forks} />
              <Mini icon={ico.box("#a78bfa")} label="HF项目" value={stats.hf_count} />
              <Mini icon={ico.dl("#60a5fa")} label="HF下载" value={stats.total_downloads} />
            </SectionBox>

            {/* 讨论 */}
            {heat && (
              <SectionBox title="网络讨论" color="#fb923c">
                <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                  {ico.flame(heat.color)}
                  <span style={{ fontSize: 12, fontWeight: 700, color: heat.color }}>{heat.text}</span>
                </div>
                {buzz?.topics && buzz.topics.length > 0 && (
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 3 }}>
                    {buzz.topics.slice(0, 3).map((t) => (
                      <span key={t} style={{ background: heat.bg, borderRadius: 10, padding: "2px 8px", fontSize: 9, color: heat.color, fontWeight: 500 }}>{t}</span>
                    ))}
                  </div>
                )}
              </SectionBox>
            )}
          </div>
        </div>

        {/* ── Footer ── */}
        <div style={{ marginTop: 18, display: "flex", alignItems: "center", justifyContent: "space-between", borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 24, height: 24, borderRadius: 7, background: "linear-gradient(135deg, #6366f1, #a855f7)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 800 }}>I</div>
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, color: "rgba(255,255,255,0.7)" }}>ImpactHub</div>
              <div style={{ fontSize: 8, color: "rgba(255,255,255,0.3)" }}>科研影响力看板</div>
            </div>
          </div>
          <div style={{ fontSize: 9, color: "rgba(255,255,255,0.2)" }}>
            {new Date().toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric" })}
          </div>
        </div>
      </div>
    </div>
  );
});

ShareCard.displayName = "ShareCard";

/* ── Sub-components ──────────────────────────────────────────────────────── */

function PlatformTag({ icon, text }: { icon: "gh" | "ss" | "hf"; text: string }) {
  const colors: Record<string, string> = { gh: "#94a3b8", ss: "#60a5fa", hf: "#fbbf24" };
  const c = colors[icon];
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, background: "rgba(255,255,255,0.06)", border: `1px solid rgba(255,255,255,0.08)`, borderRadius: 20, padding: "2px 9px 2px 6px", fontSize: 10, fontWeight: 500, color: "rgba(255,255,255,0.55)" }}>
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: c, flexShrink: 0 }} />
      {text}
    </span>
  );
}

function BigNum({ icon, label, value, accent, border }: { icon: React.ReactNode; label: string; value: number; accent: string; border: string }) {
  return (
    <div style={{ background: accent, border: `1px solid ${border}`, borderRadius: 14, padding: "10px 6px 8px", textAlign: "center" }}>
      <div style={{ display: "flex", justifyContent: "center", marginBottom: 4 }}>{icon}</div>
      <div style={{ fontSize: 19, fontWeight: 800, letterSpacing: -0.5, lineHeight: 1 }}>{formatNumber(value)}</div>
      <div style={{ fontSize: 9, fontWeight: 500, color: "rgba(255,255,255,0.4)", marginTop: 3 }}>{label}</div>
    </div>
  );
}

function SectionBox({ title, color, children }: { title: string; color: string; children: React.ReactNode }) {
  return (
    <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.05)", borderRadius: 12, padding: "7px 10px" }}>
      <div style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color, opacity: 0.7, marginBottom: 5 }}>{title}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px", alignItems: "center" }}>
        {children}
      </div>
    </div>
  );
}

function Mini({ icon, label, value, hint }: { icon: React.ReactNode; label: string; value: number; hint?: string }) {
  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      {icon}
      <span style={{ fontSize: 10, color: "rgba(255,255,255,0.45)" }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 700 }}>{formatNumber(value)}</span>
      {hint && <span style={{ fontSize: 8, color: "rgba(255,255,255,0.25)" }}>{hint}</span>}
    </div>
  );
}

export default ShareCard;
