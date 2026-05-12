import React, { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Send, Sparkles, Loader2, MapPin, ExternalLink,
  MessageSquare, Trophy, AlertTriangle, Users,
} from "lucide-react";
import {
  api,
  type AdvisorChatRecommendation, type AdvisorChatCriteria,
  type AdvisorChatProfile,
} from "@/lib/api";

type Msg =
  | { role: "user"; content: string }
  | {
      role: "assistant";
      content: string;
      recommendations?: AdvisorChatRecommendation[];
      advisor_profiles?: AdvisorChatProfile[];
      criteria?: AdvisorChatCriteria | null;
      status?: string; // ephemeral: "正在搜索…" / "正在查 X 老师…"
    };

const STARTERS = [
  "我想找做大模型方向的985导师",
  "上海地区计算机方向有哪些招生友好的导师？",
  "想找组氛围好、不太 push 的 NLP 老师",
];

const TIER_META: Record<string, { label: string; bg: string; text: string }> = {
  perfect: { label: "完美匹配", bg: "bg-gradient-to-br from-emerald-500 to-teal-600", text: "text-emerald-700" },
  strong: { label: "强匹配", bg: "bg-gradient-to-br from-indigo-500 to-blue-600", text: "text-indigo-700" },
  potential: { label: "潜力候选", bg: "bg-gradient-to-br from-amber-500 to-orange-600", text: "text-amber-700" },
};

const SOURCE_LABEL: Record<string, string> = {
  wechat: "公众号",
  xiaohongshu: "小红书",
  zhihu: "知乎",
  forum: "论坛",
};

// Top-level boundary so any render crash shows a visible message instead of white screen
class ChatErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(err: Error) { return { error: err }; }
  componentDidCatch(err: Error, info: React.ErrorInfo) {
    console.error("ChatPage render crash:", err, info);
  }
  render() {
    if (this.state.error) {
      return (
        <main className="mx-auto max-w-3xl px-4 py-12 text-center">
          <div className="rounded-xl border border-rose-200 bg-rose-50 p-6">
            <div className="text-base font-semibold text-rose-900 mb-2">页面崩溃了</div>
            <div className="text-xs text-rose-700 font-mono whitespace-pre-wrap break-all mb-3">
              {this.state.error.message}
            </div>
            <button
              onClick={() => { this.setState({ error: null }); window.location.reload(); }}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700"
            >
              重新加载
            </button>
            <p className="mt-3 text-xs text-gray-500">
              请打开 F12 → Console 复制错误堆栈给开发者
            </p>
          </div>
        </main>
      );
    }
    return this.props.children;
  }
}

export default function AdvisorChatPage() {
  return (
    <ChatErrorBoundary>
      <AdvisorChatPageInner />
    </ChatErrorBoundary>
  );
}

function AdvisorChatPageInner() {
  const [messages, setMessages] = useState<Msg[]>([
    {
      role: "assistant",
      content: "我是 ImpactHub 保研顾问。告诉我你的方向、地理偏好、对学校层次/导师风格的要求，我会从 147 所双一流的导师库里给你推荐。",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  const send = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || loading) return;

    const userMsg: Msg = { role: "user", content: trimmed };
    const placeholder: Msg = {
      role: "assistant",
      content: "",
      status: "正在思考…",
      recommendations: [],
      advisor_profiles: [],
    };
    const next = [...messages, userMsg, placeholder];
    setMessages(next);
    setInput("");
    setLoading(true);

    const apiMessages = [...messages, userMsg].map((m) => ({ role: m.role, content: m.content }));

    const TOOL_LABEL: Record<string, string> = {
      search_advisors: "搜索导师",
      lookup_advisor: "查老师详情",
      get_advisor_mentions: "拉公众号口碑",
      find_colleges: "查学院",
      web_search: "联网搜索",
    };

    const updateAssistant = (patch: Partial<Extract<Msg, { role: "assistant" }>>) => {
      setMessages((prev) => {
        const arr = [...prev];
        const lastIdx = arr.length - 1;
        const last = arr[lastIdx];
        if (last && last.role === "assistant") {
          arr[lastIdx] = { ...last, ...patch };
        }
        return arr;
      });
    };

    // Batch delta tokens with rAF — instead of N setMessages per delta (=N
    // full re-renders), accumulate ~16ms worth of tokens and flush once.
    let pendingDelta = "";
    let rafScheduled = false;
    const flushDelta = () => {
      if (!pendingDelta) {
        rafScheduled = false;
        return;
      }
      const chunk = pendingDelta;
      pendingDelta = "";
      rafScheduled = false;
      setMessages((prev) => {
        const arr = [...prev];
        const lastIdx = arr.length - 1;
        const last = arr[lastIdx];
        if (last && last.role === "assistant") {
          arr[lastIdx] = { ...last, content: last.content + chunk, status: undefined };
        }
        return arr;
      });
    };

    try {
      let collectedRecs: AdvisorChatRecommendation[] = [];
      let collectedProfiles: AdvisorChatProfile[] = [];
      for await (const ev of api.advisorChatStream(apiMessages)) {
        if (ev.type === "thinking") {
          updateAssistant({ status: "正在思考…" });
        } else if (ev.type === "tool_start") {
          const lbl = TOOL_LABEL[ev.name] || ev.name;
          let detail = "";
          const a = ev.args as { name?: string; school_name?: string; direction_keywords?: string[] };
          if (ev.name === "lookup_advisor" && a.name) {
            detail = ` ${a.name}${a.school_name ? "@" + a.school_name : ""}`;
          } else if (ev.name === "search_advisors" && a.direction_keywords?.length) {
            detail = ` (${a.direction_keywords.slice(0, 3).join("/")})`;
          }
          updateAssistant({ status: `${lbl}${detail}…` });
        } else if (ev.type === "tool_end") {
          if (ev.advisor_profile) {
            collectedProfiles = [...collectedProfiles, ev.advisor_profile];
            updateAssistant({ advisor_profiles: collectedProfiles, status: `已找到 ${ev.advisor_profile.name}` });
          } else if (ev.new_advisors_count) {
            updateAssistant({ status: `匹配 ${ev.new_advisors_count} 位候选` });
          } else {
            updateAssistant({ status: `${TOOL_LABEL[ev.name] || ev.name} 完成` });
          }
        } else if (ev.type === "delta") {
          pendingDelta += ev.content;
          if (!rafScheduled) {
            rafScheduled = true;
            requestAnimationFrame(flushDelta);
          }
        } else if (ev.type === "done") {
          // Flush any remaining tokens before applying done state
          flushDelta();
          setMessages((prev) => {
            const arr = [...prev];
            const lastIdx = arr.length - 1;
            const last = arr[lastIdx];
            if (last && last.role === "assistant") {
              const fallback = last.content
                ? last.content
                : ev.error
                  ? `生成回复失败：${ev.error}。但下面有候选信息可以参考。`
                  : "未生成文字回复，但已找到候选导师，可看下方卡片。";
              arr[lastIdx] = {
                ...last,
                content: fallback,
                status: undefined,
                recommendations: ev.recommendations || [],
                advisor_profiles: ev.advisor_profiles || [],
              };
            }
            return arr;
          });
          collectedRecs = ev.recommendations || [];
        }
      }
    } catch {
      updateAssistant({ content: "刚刚网络抖了一下，再试一次？", status: undefined });
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="mx-auto flex h-[calc(100vh-72px)] max-w-6xl flex-col px-4 py-4">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-3 flex items-center gap-3 rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50 via-white to-purple-50 p-4 shadow-sm"
      >
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white">
          <MessageSquare className="h-5 w-5" />
        </div>
        <div className="flex-1">
          <h1 className="text-base font-bold text-gray-900">保研导师推荐 · 对话式</h1>
          <p className="text-xs text-gray-500">告诉我你的需求，AI 会从 147 所双一流的 3654+ 位导师中推荐</p>
        </div>
      </motion.div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
        <AnimatePresence initial={false}>
          {messages.map((m, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2 }}
              className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div className={`${m.role === "user" ? "max-w-[75%]" : "max-w-[92%] w-full"}`}>
                {m.role === "user" ? (
                  <div className="rounded-2xl rounded-br-sm bg-indigo-600 px-4 py-2.5 text-sm text-white shadow-sm">
                    {m.content}
                  </div>
                ) : (
                  <>
                    {m.status && (
                      <div className="mb-1.5 inline-flex items-center gap-1.5 rounded-full bg-indigo-50 border border-indigo-200 px-3 py-1 text-[11px] text-indigo-700">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        {m.status}
                      </div>
                    )}
                    {(m.content || !m.status) && (
                      <div className="rounded-2xl rounded-bl-sm border border-gray-200 bg-gray-50 px-4 py-2.5 text-sm leading-relaxed text-gray-800 whitespace-pre-wrap">
                        {m.content || "…"}
                      </div>
                    )}
                    {m.criteria && hasFilters(m.criteria) && (
                      <CriteriaChips criteria={m.criteria} />
                    )}
                    {(() => {
                      // Merge profiles + recommendations, dedup by advisor_id
                      // Profiles come first (full data); recommendations append fillers
                      const profileIds = new Set((m.advisor_profiles || []).map((p) => p.advisor_id));
                      const recExtras = (m.recommendations || []).filter((r) => !profileIds.has(r.advisor_id));
                      const merged: AdvisorChatRecommendation[] = [
                        ...(m.advisor_profiles || []),
                        ...recExtras,
                      ];
                      const VISIBLE = 8;
                      const visible = merged.slice(0, VISIBLE);
                      const overflow = merged.length - visible.length;
                      return visible.length > 0 ? (
                        <div className="mt-3 space-y-2">
                          {visible.map((p) => (
                            <CardErrorBoundary
                              key={p.advisor_id}
                              fallback={
                                <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">
                                  导师卡渲染失败：{p.name} @ {p.school}
                                </div>
                              }
                            >
                              <AdvisorCard p={p} />
                            </CardErrorBoundary>
                          ))}
                          {overflow > 0 && (
                            <div className="text-[11px] text-gray-400 text-center">还有 {overflow} 位候选未展示</div>
                          )}
                        </div>
                      ) : null;
                    })()}
                  </>
                )}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {/* Starter chips (only when no user message yet) */}
      {messages.filter((m) => m.role === "user").length === 0 && !loading && (
        <div className="mt-3 flex flex-wrap gap-2">
          {STARTERS.map((s) => (
            <button
              key={s}
              onClick={() => send(s)}
              className="rounded-full border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-700 transition hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700"
            >
              <Sparkles className="mr-1 inline h-3 w-3" />
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="mt-3 flex items-center gap-2 rounded-2xl border border-gray-200 bg-white p-2 shadow-sm focus-within:border-indigo-400 focus-within:ring-2 focus-within:ring-indigo-100"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="输入你的需求…"
          disabled={loading}
          className="flex-1 bg-transparent px-2 py-1.5 text-sm text-gray-900 placeholder-gray-400 focus:outline-none"
        />
        <button
          type="submit"
          disabled={!input.trim() || loading}
          className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 text-white shadow-sm transition hover:shadow-md disabled:opacity-40"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
        </button>
      </form>
    </main>
  );
}

function hasFilters(c: AdvisorChatCriteria) {
  return (
    c.direction_keywords.length > 0 ||
    c.school_tier !== "any" ||
    c.provinces.length > 0 ||
    c.school_types.length > 0 ||
    c.must_have_mention ||
    c.preferred_traits.length > 0
  );
}

function CriteriaChips({ criteria: c }: { criteria: AdvisorChatCriteria }) {
  const Chip = ({ children, color }: { children: React.ReactNode; color: string }) => {
    const palette: Record<string, string> = {
      indigo: "bg-indigo-50 text-indigo-700 border-indigo-200",
      purple: "bg-purple-50 text-purple-700 border-purple-200",
      amber: "bg-amber-50 text-amber-700 border-amber-200",
      sky: "bg-sky-50 text-sky-700 border-sky-200",
      rose: "bg-rose-50 text-rose-700 border-rose-200",
    };
    return (
      <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${palette[color]}`}>
        {children}
      </span>
    );
  };
  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5 px-1">
      {c.school_tier !== "any" && <Chip color="amber">{c.school_tier}</Chip>}
      {c.direction_keywords.map((k) => (
        <Chip key={`d-${k}`} color="indigo">方向 · {k}</Chip>
      ))}
      {c.provinces.map((p) => (
        <Chip key={`p-${p}`} color="sky">{p}</Chip>
      ))}
      {c.school_types.map((t) => (
        <Chip key={`t-${t}`} color="purple">{t}</Chip>
      ))}
      {c.must_have_mention && <Chip color="rose">需口碑信息</Chip>}
      {c.preferred_traits.map((t) => (
        <Chip key={`tr-${t}`} color="rose">{t}</Chip>
      ))}
    </div>
  );
}


// Safety wrapper — if ProfileCard crashes (bad data), show fallback instead of white screen
class CardErrorBoundary extends React.Component<
  { children: React.ReactNode; fallback: React.ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };
  static getDerivedStateFromError() { return { hasError: true }; }
  componentDidCatch(err: unknown) { console.error("ProfileCard render error:", err); }
  render() { return this.state.hasError ? this.props.fallback : this.props.children; }
}

function AdvisorCard({ p }: { p: AdvisorChatRecommendation }) {
  const [showFullBio, setShowFullBio] = useState(false);
  const [showAllMentions, setShowAllMentions] = useState(false);

  const SOURCE_LABEL: Record<string, string> = {
    wechat: "公众号", xiaohongshu: "小红书", zhihu: "知乎", forum: "论坛",
  };
  const sentimentColor: Record<string, string> = {
    positive: "text-emerald-700",
    negative: "text-rose-700",
    neutral: "text-slate-500",
  };

  // Defensive defaults — fields differ between lookup_advisor (full) and search_advisors (brief)
  const research_areas = Array.isArray(p.research_areas) ? p.research_areas : [];
  const honors = Array.isArray(p.honors) ? p.honors : [];
  const education = Array.isArray(p.education) ? p.education : [];
  const mentions = Array.isArray(p.mentions) ? p.mentions : [];
  const concerns = Array.isArray(p.concerns) ? p.concerns : [];
  const highlights = Array.isArray(p.highlights) ? p.highlights : [];
  const bio = p.bio || "";
  const recruiting_intent = p.recruiting_intent || "";
  const homepage = p.homepage || p.homepage_url || "";
  const tier = p.tier ? (TIER_META[p.tier] || TIER_META.potential) : null;
  const nMentions = mentions.length || p.n_mentions || 0;

  // ── Smart extractions for 保研 perspective ──
  const text = `${bio} ${recruiting_intent}`;
  const citationMatch = text.match(/(引用|被引)[^0-9一二三四五六七八九十百千万亿]{0,5}([0-9一二三四五六七八九十百千万亿.]+)\s*(万|千|余次|次)/);
  const academicCount = citationMatch ? `${citationMatch[2]}${citationMatch[3]}` : null;

  const mentionTags = Array.from(new Set(mentions.flatMap((m) => m.tags || [])));
  const styleHints: string[] = [];
  for (const t of mentionTags) {
    if (["push", "卷王", "压榨"].some((k) => t.includes(k))) styleHints.push("⚠ 偏 push");
    else if (["放养", "氛围"].some((k) => t.includes(k))) styleHints.push("✓ 氛围相关");
  }

  const recruitingFromMentions = mentions
    .filter((m) => Array.isArray(m.tags) && m.tags.some((t) => ["招生", "扩招"].includes(t)))
    .map((m) => m.snippet || m.title)[0];

  const hasAdmissionInfo = !!(recruiting_intent || recruitingFromMentions);

  // Avatar initial from name (first char)
  const initial = p.name?.charAt(0) || "?";
  // Use inline style for gradient to avoid Tailwind JIT missing dynamic class names
  const avatarGradients = [
    "linear-gradient(135deg, #818cf8, #a855f7)",
    "linear-gradient(135deg, #fb7185, #fbbf24)",
    "linear-gradient(135deg, #34d399, #14b8a6)",
    "linear-gradient(135deg, #60a5fa, #38bdf8)",
  ];
  const avatarStyle = { background: avatarGradients[(p.advisor_id || 0) % avatarGradients.length] };

  return (
    <div className="rounded-2xl border border-gray-200 bg-white shadow-sm overflow-hidden hover:shadow-md transition-shadow">
      {/* ── Header band ── */}
      <div className="bg-gradient-to-r from-indigo-50 via-white to-purple-50 px-4 pt-3 pb-3 border-b border-gray-100">
        <div className="flex items-start gap-3">
          {/* Avatar */}
          <div
            className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl text-white text-lg font-bold shadow-sm"
            style={avatarStyle}
          >
            {initial}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-[15px] font-bold text-gray-900">{p.name}</span>
              {p.title && (
                <span className="rounded-md bg-white border border-gray-200 px-1.5 py-px text-[10px] text-gray-700 font-medium">{p.title}</span>
              )}
              {p.is_985 && (
                <span className="inline-flex items-center rounded-md bg-gradient-to-br from-amber-400 to-orange-500 px-1.5 py-px text-[9px] font-bold text-white shadow-sm">985</span>
              )}
              {p.is_211 && !p.is_985 && (
                <span className="inline-flex items-center rounded-md bg-indigo-500 px-1.5 py-px text-[9px] font-bold text-white shadow-sm">211</span>
              )}
              {p.is_doctoral_supervisor && (
                <span className="inline-flex items-center rounded-md bg-indigo-50 border border-indigo-200 px-1.5 py-px text-[9px] font-semibold text-indigo-700">博导</span>
              )}
              {nMentions > 0 && (
                <span className="inline-flex items-center rounded-md bg-rose-50 border border-rose-200 px-1.5 py-px text-[9px] font-semibold text-rose-700">💬 {nMentions}</span>
              )}
              {tier && p.match_score !== undefined && (
                <span className={`ml-auto shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-bold text-white ${tier.bg}`}>
                  {p.match_score} · {tier.label}
                </span>
              )}
              {p.h_index !== undefined && p.h_index > 0 && (
                <span className="ml-auto text-[11px] text-gray-500 font-mono">h={p.h_index}</span>
              )}
            </div>
            <div className="mt-1 flex items-center gap-1.5 flex-wrap text-[12px] text-gray-700">
              <Users className="h-3 w-3 text-gray-400 shrink-0" />
              <span className="font-medium">{p.school}</span>
              <span className="text-gray-300">·</span>
              <span>{p.college}</span>
              {p.province && (
                <>
                  <span className="text-gray-300">·</span>
                  <MapPin className="h-3 w-3 text-gray-400" />
                  <span className="text-gray-600">{p.province}</span>
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="p-4">
      {/* (sections wrapped here) */}

      {/* ── LLM rerank reasoning (only present when set) ── */}
      {p.reasoning && (
        <div className="mb-2 rounded-lg bg-gradient-to-r from-indigo-50 to-purple-50 px-2.5 py-1.5 text-[12px] leading-relaxed text-gray-800">
          <Trophy className="mr-1 inline h-3 w-3 text-amber-500" />{p.reasoning}
        </div>
      )}
      {highlights.length > 0 && (
        <ul className="mb-2 space-y-0.5">
          {highlights.map((h, i) => (
            <li key={i} className="flex items-start gap-1 text-[11px] text-emerald-700">
              <Trophy className="mt-0.5 h-2.5 w-2.5 shrink-0" />{h}
            </li>
          ))}
        </ul>
      )}
      {concerns.length > 0 && (
        <div className="mb-2 space-y-0.5">
          {concerns.map((c, i) => (
            <div key={i} className="flex items-start gap-1 text-[11px] text-orange-700">
              <AlertTriangle className="mt-0.5 h-2.5 w-2.5 shrink-0" />{c}
            </div>
          ))}
        </div>
      )}

      {/* ── 1. 做什么方向 ── */}
      {(research_areas.length > 0 || bio) && (
        <Block icon="📚" title="研究方向" subtitle="你能跟着学什么" source="主页" accent="indigo">
          {research_areas.length > 0 && (
            <div className="flex flex-wrap gap-1 mb-1.5">
              {research_areas.map((r) => (
                <span key={r} className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] text-indigo-700 border border-indigo-200">{r}</span>
              ))}
            </div>
          )}
          {bio && (
            <>
              <p className={`text-[12px] leading-relaxed text-gray-700 ${showFullBio ? "" : "line-clamp-2"}`}>{bio}</p>
              {bio.length > 80 && (
                <button onClick={() => setShowFullBio((v) => !v)} className="text-[11px] text-indigo-600 hover:underline mt-0.5">
                  {showFullBio ? "收起" : "展开简介"}
                </button>
              )}
            </>
          )}
        </Block>
      )}

      {/* ── 2. 招生 & 联系（保研最关心） ── */}
      <Block icon="✉️" title="招生信息" subtitle="能不能进 / 怎么联系" accent="emerald">
        {hasAdmissionInfo ? (
          <>
            {recruiting_intent && (
              <p className="text-[12px] leading-relaxed text-emerald-900 bg-emerald-50 border border-emerald-200 rounded px-2 py-1 mb-1">
                {recruiting_intent}<span className="text-emerald-400 ml-1 text-[10px]">[主页]</span>
              </p>
            )}
            {recruitingFromMentions && (
              <p className="text-[12px] leading-relaxed text-gray-800 bg-amber-50 border border-amber-200 rounded px-2 py-1 mb-1">
                <span className="text-amber-700 font-medium mr-1">学长口碑：</span>
                "{recruitingFromMentions}"
              </p>
            )}
          </>
        ) : (
          <p className="text-[11px] text-gray-400 mb-1">主页未公开招生意愿；可邮件直接询问。</p>
        )}
        <div className="flex items-center gap-2 flex-wrap text-[11px]">
          {p.email && (
            <a href={`mailto:${p.email}`} className="text-indigo-700 hover:underline font-mono">✉ {p.email}</a>
          )}
          {p.is_doctoral_supervisor && <span className="text-gray-600">📜 招博硕</span>}
          {p.homepage && (
            <a href={p.homepage} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-0.5 rounded-full bg-gray-100 px-2 py-0.5 text-gray-600 hover:bg-gray-200">
              <ExternalLink className="h-2.5 w-2.5" /> 主页
            </a>
          )}
        </div>
      </Block>

      {/* ── 3. 学术实力 ── */}
      {(honors.length > 0 || p.h_index > 0 || academicCount) && (
        <Block icon="⚡" title="学术实力" subtitle="组的资源和影响力" accent="amber">
          <div className="flex flex-wrap gap-1.5 mb-1 items-center text-[11px]">
            {p.h_index > 0 && (
              <span className="rounded-full bg-blue-50 px-2 py-0.5 text-blue-700 border border-blue-200">h-index <b>{p.h_index}</b></span>
            )}
            {academicCount && (
              <span className="rounded-full bg-blue-50 px-2 py-0.5 text-blue-700 border border-blue-200">引用 <b>{academicCount}</b></span>
            )}
          </div>
          {honors.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1">
              {honors.map((h) => (
                <span key={h} className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-800 border border-amber-200">🏆 {h}</span>
              ))}
            </div>
          )}
        </Block>
      )}

      {/* ── 4. 学缘 ── */}
      {education.length > 0 && (
        <Block icon="🎓" title="学缘" subtitle="老师的学术背景" source="主页" accent="blue">
          <ul className="space-y-0.5">
            {education.map((e, i) => (
              <li key={i} className="text-[11px] text-gray-700 flex items-baseline gap-1.5">
                <span className="text-gray-400 font-mono shrink-0 w-10">{e.year || "—"}</span>
                <span className="font-medium">{e.degree}</span>
                <span className="text-gray-600">@ {e.institution}</span>
                {e.advisor && <span className="text-gray-500">· 师从 {e.advisor}</span>}
              </li>
            ))}
          </ul>
        </Block>
      )}

      {/* ── 5. 学长学姐口碑 ── */}
      {mentions.length > 0 ? (
        <Block icon="💬" title="学长学姐口碑" subtitle={`${mentions.length} 条公众号摘抄`} accent="rose">
          {styleHints.length > 0 && (
            <div className="mb-1.5 flex flex-wrap gap-1">
              {styleHints.map((s) => (
                <span key={s} className="rounded-full bg-rose-50 px-2 py-0.5 text-[11px] text-rose-700 border border-rose-200 font-medium">{s}</span>
              ))}
            </div>
          )}
          <div className="space-y-1.5">
            {(showAllMentions ? mentions : mentions.slice(0, 2)).map((m, i) => (
              <div key={i} className="rounded-lg bg-white border border-gray-200 px-2 py-1.5">
                <div className="flex items-center gap-1.5 mb-0.5 flex-wrap text-[10px]">
                  <span className="rounded bg-gray-100 px-1.5 py-px text-gray-700 font-medium">
                    {SOURCE_LABEL[m.source] || m.source}
                  </span>
                  {m.source_account && (
                    <span className="rounded bg-indigo-50 px-1.5 py-px text-indigo-700 border border-indigo-200">{m.source_account}</span>
                  )}
                  {m.sentiment && (
                    <span className={sentimentColor[m.sentiment] || "text-slate-500"}>
                      ●{m.sentiment === "positive" ? "正向" : m.sentiment === "negative" ? "负向" : "中性"}
                    </span>
                  )}
                  {m.published_at && <span className="text-gray-400 ml-auto">{m.published_at.slice(0, 10)}</span>}
                </div>
                {m.snippet && <p className="text-[12px] leading-relaxed text-gray-700 mb-1">{m.snippet}</p>}
                {Array.isArray(m.tags) && m.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-1">
                    {m.tags.map((t) => (
                      <span key={t} className="rounded-full bg-amber-50 px-1.5 py-px text-[10px] text-amber-700 border border-amber-200">#{t}</span>
                    ))}
                  </div>
                )}
                {m.url && (
                  <a href={m.url} target="_blank" rel="noopener noreferrer"
                    className="inline-flex items-center gap-0.5 text-[10px] text-indigo-600 hover:underline">
                    <ExternalLink className="h-2.5 w-2.5" /> {m.title || "查看原文"}
                  </a>
                )}
              </div>
            ))}
          </div>
          {mentions.length > 2 && (
            <button onClick={() => setShowAllMentions((v) => !v)}
              className="mt-1 text-[11px] text-indigo-600 hover:underline">
              {showAllMentions ? "收起" : `展开剩余 ${mentions.length - 2} 条`}
            </button>
          )}
        </Block>
      ) : (
        <Block icon="💬" title="学长学姐口碑" subtitle="" accent="slate">
          <p className="text-[11px] text-gray-400">暂无公众号/小红书等口碑数据 — 建议自行联系学长学姐了解组氛围。</p>
        </Block>
      )}

      {/* ── 数据来源 ── */}
      <div className="mt-3 pt-2 border-t border-dashed border-gray-200 flex items-center gap-2 flex-wrap text-[10px] text-gray-400">
        <span>数据来源：</span>
        {p.homepage && (
          <a href={p.homepage} target="_blank" rel="noopener noreferrer"
            className="inline-flex items-center gap-0.5 rounded-full bg-gray-100 px-2 py-0.5 text-gray-600 hover:bg-gray-200">
            <ExternalLink className="h-2.5 w-2.5" /> 个人主页
          </a>
        )}
        {mentions.length > 0 && <span className="text-gray-500">+ {mentions.length} 条公众号引用</span>}
        {p.crawl_status === "stub" && (
          <span className="text-amber-600 bg-amber-50 px-1.5 rounded" title="尚未抓取主页详情，仅基础信息">仅 stub</span>
        )}
      </div>
      </div>
    </div>
  );
}

function Block({
  icon, title, subtitle, source, accent = "indigo", children,
}: {
  icon: string;
  title: string;
  subtitle?: string;
  source?: string;
  accent?: "indigo" | "emerald" | "blue" | "amber" | "rose" | "slate";
  children: React.ReactNode;
}) {
  const accentColors: Record<string, { bar: string; title: string; iconBg: string }> = {
    indigo: { bar: "bg-indigo-400", title: "text-indigo-900", iconBg: "bg-indigo-50" },
    emerald: { bar: "bg-emerald-400", title: "text-emerald-900", iconBg: "bg-emerald-50" },
    blue: { bar: "bg-blue-400", title: "text-blue-900", iconBg: "bg-blue-50" },
    amber: { bar: "bg-amber-400", title: "text-amber-900", iconBg: "bg-amber-50" },
    rose: { bar: "bg-rose-400", title: "text-rose-900", iconBg: "bg-rose-50" },
    slate: { bar: "bg-slate-400", title: "text-slate-900", iconBg: "bg-slate-50" },
  };
  const c = accentColors[accent];
  return (
    <div className="mb-3 last:mb-0">
      <div className="flex items-center gap-2 mb-1.5">
        <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-lg ${c.iconBg} text-[13px]`}>{icon}</span>
        <span className={`text-[12px] font-semibold ${c.title}`}>{title}</span>
        {subtitle && <span className="text-[10px] text-gray-500">· {subtitle}</span>}
        {source && <span className="ml-auto text-[10px] text-gray-300">[来源: {source}]</span>}
      </div>
      <div className="pl-8 relative">
        <div className={`absolute left-3 top-0 bottom-0 w-px ${c.bar} opacity-30`} />
        {children}
      </div>
    </div>
  );
}
