import { useEffect, useState, useRef } from "react";
import { useParams, Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  api,
  type ProfileFull,
  type Stats,
  type TimelineEntry,
  type BuzzSnapshot,
  type CitationOverview,
  type AISummary,
} from "@/lib/api";
import HeroSection from "@/components/HeroSection";
import RadarChart from "@/components/RadarChart";
import StatsOverview from "@/components/StatsOverview";
import PublicationList from "@/components/PublicationList";
import RepoCard from "@/components/RepoCard";
import HFModelCard from "@/components/HFModelCard";
import Timeline from "@/components/Timeline";
import ShareModal from "@/components/ShareModal";
import CitationAnalysisView from "@/components/CitationAnalysis";
import LinkAccountModal from "@/components/LinkAccountModal";
import GrowthDashboard from "@/components/GrowthDashboard";
import SettingsPanel from "@/components/SettingsPanel";
import BuzzCard from "@/components/BuzzCard";
import SmartExporter from "@/components/SmartExporter";
import {
  RefreshCw,
  BookOpen,
  GitBranch,
  Box,
  Clock,
  Trophy,
  Loader2,
  ArrowLeft,
  Share2,
  Quote,
  TrendingUp,
  Settings,
  Flame,
  Sparkles,
  FileDown,
} from "lucide-react";

type TabKey = "papers" | "repos" | "hf" | "citations" | "growth" | "buzz" | "timeline" | "export";

const tabs: { key: TabKey; label: string; icon: typeof BookOpen }[] = [
  { key: "papers", label: "学术论文", icon: BookOpen },
  { key: "citations", label: "引用分析", icon: Quote },
  { key: "repos", label: "代码仓库", icon: GitBranch },
  { key: "hf", label: "模型与数据集", icon: Box },
  { key: "growth", label: "增量追踪", icon: TrendingUp },
  { key: "buzz", label: "社区讨论", icon: Flame },
  { key: "timeline", label: "时间轴", icon: Clock },
  { key: "export", label: "智能导出", icon: FileDown },
];

export default function ProfilePage() {
  const { id } = useParams<{ id: string }>();
  const userId = id || "";

  const [profile, setProfile] = useState<ProfileFull | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [buzz, setBuzz] = useState<BuzzSnapshot | null>(null);
  const [buzzRefreshing, setBuzzRefreshing] = useState(false);
  const [buzzElapsed, setBuzzElapsed] = useState(0);
  const buzzTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const buzzPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [citationOverview, setCitationOverview] = useState<CitationOverview | null>(null);
  const [aiSummary, setAISummary] = useState<AISummary | null>(null);
  const [aiSummaryLoading, setAISummaryLoading] = useState(false);
  const aiPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("papers");
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [showShare, setShowShare] = useState(false);
  const [showLink, setShowLink] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const fetchData = async () => {
    try {
      const [p, s, t] = await Promise.all([
        api.getProfile(userId),
        api.getStats(userId),
        api.getTimeline(userId),
      ]);
      setProfile(p);
      setStats(s);
      setTimeline(t);
      // Fetch buzz, citation overview, and AI summary in background (non-blocking)
      api.getBuzz(userId).then((b) => setBuzz(b)).catch(() => {});
      api.getCitationOverview(userId).then((c) => setCitationOverview(c)).catch(() => {});
      api.getAISummary(userId).then((s) => setAISummary(s)).catch(() => {});
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    api.trackVisit(`/profile/${userId}`).catch(() => {});
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, [userId]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await api.refresh(userId);
      setTimeout(fetchData, 3000);
    } catch (err) {
      console.error(err);
    } finally {
      setTimeout(() => setRefreshing(false), 3000);
    }
  };

  const handleShare = async () => {
    setShowShare(true);
  };

  const handleGenerateAISummary = async () => {
    if (aiSummaryLoading) return;
    setAISummaryLoading(true);
    try {
      await api.refreshAISummary(userId);
      const prevRefreshed = aiSummary?.refreshed_at;
      if (aiPollRef.current) clearInterval(aiPollRef.current);
      aiPollRef.current = setInterval(async () => {
        const s = await api.getAISummary(userId).catch(() => null);
        if (s && s.refreshed_at !== prevRefreshed) {
          setAISummary(s);
          setAISummaryLoading(false);
          if (aiPollRef.current) { clearInterval(aiPollRef.current); aiPollRef.current = null; }
        }
      }, 3000);
      // Timeout after 90s
      setTimeout(() => {
        if (aiPollRef.current) { clearInterval(aiPollRef.current); aiPollRef.current = null; }
        setAISummaryLoading(false);
      }, 90000);
    } catch {
      setAISummaryLoading(false);
    }
  };

  const handleBuzzRefresh = async () => {
    if (buzzRefreshing) return;
    setBuzzRefreshing(true);
    setBuzzElapsed(0);
    // Start elapsed timer
    if (buzzTimerRef.current) clearInterval(buzzTimerRef.current);
    buzzTimerRef.current = setInterval(() => setBuzzElapsed((e) => e + 1), 1000);
    try {
      await api.refreshBuzz(userId);
      const prev = buzz?.refreshed_at;
      let tries = 0;
      if (buzzPollRef.current) clearInterval(buzzPollRef.current);
      buzzPollRef.current = setInterval(async () => {
        tries++;
        const fresh = await api.getBuzz(userId).catch(() => null);
        if ((fresh?.refreshed_at && fresh.refreshed_at !== prev) || tries > 180) {
          if (buzzPollRef.current) clearInterval(buzzPollRef.current);
          if (buzzTimerRef.current) clearInterval(buzzTimerRef.current);
          buzzPollRef.current = null;
          buzzTimerRef.current = null;
          if (fresh?.refreshed_at && fresh.refreshed_at !== prev) {
            setBuzz(fresh);
          }
          setBuzzRefreshing(false);
        }
      }, 3000);
    } catch {
      setBuzzRefreshing(false);
      if (buzzTimerRef.current) { clearInterval(buzzTimerRef.current); buzzTimerRef.current = null; }
    }
  };

  // Cleanup polling on unmount
  useEffect(() => () => {
    if (buzzTimerRef.current) clearInterval(buzzTimerRef.current);
    if (buzzPollRef.current) clearInterval(buzzPollRef.current);
    if (aiPollRef.current) clearInterval(aiPollRef.current);
  }, []);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
      </div>
    );
  }

  if (!profile || !stats) {
    return (
      <div className="flex min-h-screen items-center justify-center text-gray-400">
        未找到该用户。
      </div>
    );
  }

  const user = profile.user;
  const hasScholar = Boolean(user.scholar_id);
  const hasGithub = Boolean(user.github_username);
  const hasHF = Boolean(user.hf_username);

  return (
    <div className="relative min-h-screen overflow-hidden bg-gradient-to-br from-indigo-50 via-white to-purple-50">
      {/* Animated background decorations — fixed so they stay visible while scrolling */}
      <div className="pointer-events-none fixed inset-0 z-0 overflow-hidden" aria-hidden="true">
        {/* Large vivid blobs */}
        <motion.div
          className="absolute -right-16 -top-16 h-[36rem] w-[36rem] rounded-full bg-gradient-to-br from-indigo-200/35 to-purple-200/25 blur-3xl"
          animate={{ x: [0, 60, -40, 0], y: [0, -50, 30, 0], scale: [1, 1.15, 0.88, 1] }}
          transition={{ duration: 12, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="absolute -bottom-20 -left-20 h-[32rem] w-[32rem] rounded-full bg-gradient-to-tr from-sky-200/30 to-indigo-200/20 blur-3xl"
          animate={{ x: [0, -45, 55, 0], y: [0, 45, -35, 0], scale: [1, 0.88, 1.15, 1] }}
          transition={{ duration: 16, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="absolute left-[20%] top-[35%] h-80 w-80 rounded-full bg-gradient-to-bl from-violet-200/25 to-pink-200/18 blur-2xl"
          animate={{ x: [0, -35, 45, 0], y: [0, 50, -40, 0], scale: [1, 1.1, 0.92, 1] }}
          transition={{ duration: 10, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="absolute right-[15%] top-[60%] h-64 w-64 rounded-full bg-gradient-to-r from-cyan-200/22 to-blue-200/15 blur-2xl"
          animate={{ x: [0, 30, -20, 0], y: [0, -35, 25, 0] }}
          transition={{ duration: 11, repeat: Infinity, ease: "easeInOut" }}
        />

        {/* Orbiting double ring */}
        <motion.svg
          className="absolute right-12 top-24 h-36 w-36 text-indigo-300/22"
          viewBox="0 0 80 80"
          animate={{ rotate: 360 }}
          transition={{ duration: 18, repeat: Infinity, ease: "linear" }}
        >
          <circle cx="40" cy="40" r="36" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <circle cx="40" cy="40" r="22" fill="none" stroke="currentColor" strokeWidth="1" strokeDasharray="5 4" />
          <circle cx="40" cy="4" r="4" fill="currentColor" opacity="0.8" />
        </motion.svg>

        {/* Counter-rotating ring — left */}
        <motion.svg
          className="absolute left-6 top-[55%] h-28 w-28 text-purple-400/30"
          viewBox="0 0 80 80"
          animate={{ rotate: -360 }}
          transition={{ duration: 24, repeat: Infinity, ease: "linear" }}
        >
          <circle cx="40" cy="40" r="34" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="8 5" />
          <circle cx="40" cy="6" r="3" fill="currentColor" opacity="0.7" />
          <circle cx="74" cy="40" r="2.5" fill="currentColor" opacity="0.5" />
        </motion.svg>

        {/* Pulsing hexagon */}
        <motion.svg
          className="absolute bottom-28 right-16 h-28 w-28 text-purple-400/35"
          viewBox="0 0 100 100"
          animate={{ scale: [1, 1.2, 1], opacity: [0.35, 0.55, 0.35], rotate: [0, 30, 0] }}
          transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
        >
          <polygon points="50,5 93,27.5 93,72.5 50,95 7,72.5 7,27.5" fill="none" stroke="currentColor" strokeWidth="2" />
        </motion.svg>

        {/* Spinning triangle */}
        <motion.svg
          className="absolute left-[18%] top-[75%] h-20 w-20 text-sky-400/30"
          viewBox="0 0 48 48"
          animate={{ rotate: -360 }}
          transition={{ duration: 16, repeat: Infinity, ease: "linear" }}
        >
          <polygon points="24,2 46,42 2,42" fill="none" stroke="currentColor" strokeWidth="2" />
        </motion.svg>

        {/* Animated connecting lines */}
        <svg className="absolute inset-0 h-full w-full text-indigo-400/15">
          <line x1="5%" y1="20%" x2="35%" y2="5%" stroke="currentColor" strokeWidth="1" strokeDasharray="6 8">
            <animate attributeName="stroke-dashoffset" from="0" to="28" dur="4s" repeatCount="indefinite" />
          </line>
          <line x1="60%" y1="90%" x2="95%" y2="55%" stroke="currentColor" strokeWidth="1" strokeDasharray="6 8">
            <animate attributeName="stroke-dashoffset" from="0" to="-28" dur="5s" repeatCount="indefinite" />
          </line>
          <line x1="80%" y1="10%" x2="60%" y2="45%" stroke="currentColor" strokeWidth="1" strokeDasharray="4 6">
            <animate attributeName="stroke-dashoffset" from="0" to="20" dur="3s" repeatCount="indefinite" />
          </line>
        </svg>

        {/* Floating particles */}
        {[
          { left: "8%", top: "12%", size: 4, delay: 0, dur: 7 },
          { left: "88%", top: "18%", size: 3.5, delay: 1, dur: 8 },
          { left: "78%", top: "65%", size: 4, delay: 2, dur: 6 },
          { left: "12%", top: "78%", size: 3.5, delay: 0.5, dur: 9 },
          { left: "52%", top: "30%", size: 3, delay: 3, dur: 7 },
          { left: "35%", top: "55%", size: 3.5, delay: 1.5, dur: 8 },
          { left: "65%", top: "80%", size: 3, delay: 2.5, dur: 6 },
          { left: "25%", top: "25%", size: 3, delay: 4, dur: 9 },
        ].map((p, i) => (
          <motion.div
            key={`particle-${i}`}
            className="absolute rounded-full bg-indigo-500/30"
            style={{ left: p.left, top: p.top, width: p.size * 2, height: p.size * 2 }}
            animate={{ y: [0, -30, 15, -20, 0], x: [0, 12, -8, 6, 0], opacity: [0.3, 0.6, 0.2, 0.5, 0.3] }}
            transition={{ duration: p.dur, delay: p.delay, repeat: Infinity, ease: "easeInOut" }}
          />
        ))}
      </div>

      <div className="relative mx-auto max-w-5xl px-4 py-4">
        <div className="mb-6 flex items-center justify-between">
          <Link
            to="/"
            className="flex items-center gap-1.5 text-sm text-gray-400 transition hover:text-gray-600"
          >
            <ArrowLeft className="h-4 w-4" />
            返回
          </Link>
          <div className="flex items-center gap-2">
            <button
              onClick={handleShare}
              className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-600 shadow-sm transition hover:border-indigo-300 hover:text-indigo-600"
            >
              <Share2 className="h-3.5 w-3.5" />
              分享卡片
            </button>
            <Link
              to={`/milestones/${userId}`}
              className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-600 shadow-sm transition hover:border-amber-300 hover:text-amber-600"
            >
              <Trophy className="h-3.5 w-3.5" />
              里程碑
            </Link>
            <button
              onClick={() => setShowSettings(true)}
              className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-600 shadow-sm transition hover:border-gray-400 hover:text-gray-800"
            >
              <Settings className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-600 shadow-sm transition hover:border-indigo-300 hover:text-indigo-600 disabled:opacity-50"
            >
              <RefreshCw
                className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`}
              />
              刷新数据
            </button>
          </div>
        </div>

        <HeroSection
          user={user}
          stats={stats}
          aiSummary={aiSummary}
          aiSummaryLoading={aiSummaryLoading}
          onGenerateAISummary={handleGenerateAISummary}
          onLinkAccounts={() => setShowLink(true)}
        />

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.15, ease: "easeOut" }}
          className="mt-6 grid gap-6 lg:grid-cols-3"
        >
          <div className="lg:col-span-1">
            <RadarChart stats={stats} buzzHeat={buzz?.heat_label} />
          </div>
          <div className="flex flex-col gap-4 lg:col-span-2">
            <StatsOverview
              stats={stats}
              buzz={buzz}
              citationOverview={citationOverview}
              userId={userId}
            />
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.3, ease: "easeOut" }}
          className="mt-8"
        >
          <div className="flex gap-1 overflow-x-auto rounded-xl border border-gray-200 bg-white p-1 shadow-sm">
            {tabs.map(({ key, label, icon: Icon }) => {
              const unconfigured =
                ((key === "papers" || key === "citations") && !hasScholar) ||
                (key === "repos" && !hasGithub) ||
                (key === "hf" && !hasHF);
              const needsAction =
                (key === "citations" && hasScholar && citationOverview && citationOverview.total_papers_analyzed === 0 && !citationOverview.is_analyzing) ||
                (key === "buzz" && !buzz);
              return (
                <button
                  key={key}
                  onClick={() => setActiveTab(key)}
                  className={`relative flex shrink-0 flex-1 items-center justify-center gap-1.5 rounded-lg py-2.5 text-sm font-medium transition ${
                    activeTab === key
                      ? "bg-indigo-600 text-white shadow"
                      : "text-gray-500 hover:bg-gray-50 hover:text-gray-700"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {label}
                  {unconfigured && (
                    <span
                      className={`ml-1 inline-block h-1.5 w-1.5 rounded-full ${
                        activeTab === key ? "bg-amber-300" : "bg-amber-400"
                      }`}
                    />
                  )}
                  {needsAction && !unconfigured && (
                    <span
                      className={`ml-1 inline-block h-1.5 w-1.5 rounded-full ${
                        activeTab === key ? "bg-red-300" : "bg-red-500"
                      }`}
                    />
                  )}
                </button>
              );
            })}
          </div>

          {/* Tip: unanalyzed features */}
          {(() => {
            const tips: { label: string; tab: TabKey }[] = [];
            if (hasScholar && citationOverview && citationOverview.total_papers_analyzed === 0 && !citationOverview.is_analyzing) {
              tips.push({ label: "引用分析", tab: "citations" });
            }
            if (!buzz) {
              tips.push({ label: "社区讨论", tab: "buzz" });
            }
            if (tips.length === 0) return null;
            return (
              <div className="mt-3 flex items-center gap-2 rounded-xl border border-indigo-100 bg-indigo-50/60 px-4 py-2.5 text-sm text-indigo-700">
                <Sparkles className="h-4 w-4 shrink-0 text-indigo-400" />
                <span>
                  以下功能尚未启用：
                  {tips.map((t, i) => (
                    <span key={t.tab}>
                      {i > 0 && "、"}
                      <button
                        onClick={() => setActiveTab(t.tab)}
                        className="font-semibold underline decoration-indigo-300 underline-offset-2 transition hover:text-indigo-900"
                      >
                        {t.label}
                      </button>
                    </span>
                  ))}
                  ，点击进入后开始分析
                </span>
              </div>
            );
          })()}

          <div className="mt-4">
            <AnimatePresence mode="wait">
              <motion.div
                key={activeTab}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.25, ease: "easeOut" }}
              >
            {activeTab === "papers" && (
              <PublicationList papers={profile.papers} configured={hasScholar} />
            )}
            {activeTab === "citations" && (
              <CitationAnalysisView userId={userId} configured={hasScholar} initialData={citationOverview} />
            )}
            {activeTab === "repos" && (
              <RepoCard
                repos={profile.repos}
                configured={hasGithub}
                userId={userId}
                onRepoAdded={(repo) => setProfile((p) => p ? { ...p, repos: [...p.repos, repo] } : p)}
                onRepoDeleted={(repoId) => setProfile((p) => p ? { ...p, repos: p.repos.filter((r) => r.id !== repoId) } : p)}
              />
            )}
            {activeTab === "hf" && (
              <HFModelCard
                items={profile.hf_items}
                configured={hasHF}
                userId={userId}
                onItemAdded={(item) => setProfile((p) => p ? { ...p, hf_items: [...p.hf_items, item] } : p)}
                onItemDeleted={(itemId) => setProfile((p) => p ? { ...p, hf_items: p.hf_items.filter((h) => h.id !== itemId) } : p)}
              />
            )}
            {activeTab === "growth" && <GrowthDashboard userId={userId} />}
            {activeTab === "buzz" && (
              <BuzzCard
                userId={userId}
                buzz={buzz}
                refreshing={buzzRefreshing}
                elapsed={buzzElapsed}
                onRefresh={handleBuzzRefresh}
              />
            )}
            {activeTab === "timeline" && <Timeline entries={timeline} />}
            {activeTab === "export" && (
              <SmartExporter
                userId={userId}
                papers={profile.papers}
                repos={profile.repos}
                hfItems={profile.hf_items}
              />
            )}
              </motion.div>
            </AnimatePresence>
          </div>
        </motion.div>
      </div>

      {showShare && (
        <ShareModal
          user={user}
          stats={stats}
          buzz={buzz}
          citationOverview={citationOverview}
          aiSummary={aiSummary}
          onClose={() => setShowShare(false)}
        />
      )}

      {showLink && (
        <LinkAccountModal
          userId={userId}
          currentHomepage={user.homepage}
          onClose={() => setShowLink(false)}
          onUpdated={() => {
            setShowLink(false);
            fetchData();
          }}
        />
      )}

      {showSettings && (
        <SettingsPanel
          user={user}
          onClose={() => setShowSettings(false)}
          onUpdated={() => {
            setShowSettings(false);
            fetchData();
          }}
        />
      )}
    </div>
  );
}
