import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { api, type UserProfile, type DiscoveryStatus, type SiteStats, type ScholarSearchResult } from "@/lib/api";
import {
  Github,
  ArrowRight,
  Sparkles,
  Loader2,
  CheckCircle2,
  XCircle,
  BookOpen,
  Box,
  BarChart3,
  Globe,
  TrendingUp,
  Share2,
  Quote,
  Award,
  Users,
  FileText,
  Star,
  Eye,
  Bot,
  Tags,
  ClipboardList,
  Hash,
} from "lucide-react";

export default function SetupPage() {
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = useState("");
  const [manualId, setManualId] = useState("");
  const [searchResults, setSearchResults] = useState<ScholarSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [selectedScholar, setSelectedScholar] = useState<ScholarSearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [discovery, setDiscovery] = useState<DiscoveryStatus | null>(null);
  const [existingUsers, setExistingUsers] = useState<UserProfile[]>([]);
  const [siteStats, setSiteStats] = useState<SiteStats | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    api.listUsers().then(setExistingUsers).catch(() => {});
    api.getSiteStats().then(setSiteStats).catch(() => {});
    api.trackVisit(window.location.pathname).catch(() => {});
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleSearch = useCallback((query: string) => {
    setSearchQuery(query);
    setSelectedScholar(null);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (query.trim().length < 2) {
      setSearchResults([]);
      setHasMore(false);
      setShowDropdown(false);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        const res = await api.searchScholars(query.trim(), 0, 10);
        setSearchResults(res.results);
        setHasMore(res.has_more);
        setShowDropdown(res.results.length > 0);
      } catch {
        setSearchResults([]);
        setHasMore(false);
      } finally {
        setSearching(false);
      }
    }, 400);
  }, []);

  const handleLoadMore = useCallback(async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const res = await api.searchScholars(searchQuery.trim(), searchResults.length, 10);
      setSearchResults((prev) => [...prev, ...res.results]);
      setHasMore(res.has_more);
    } catch {
      // ignore
    } finally {
      setLoadingMore(false);
    }
  }, [loadingMore, hasMore, searchQuery, searchResults.length]);

  const handleSelect = (scholar: ScholarSearchResult) => {
    setSelectedScholar(scholar);
    setSearchQuery(scholar.name);
    setShowDropdown(false);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const sid = selectedScholar?.authorId || manualId.trim() || searchQuery.trim();
    if (!sid) return;
    setLoading(true);
    setDiscovery(null);
    try {
      const result = await api.createProfile({ scholar_id: sid });
      if (result.message?.includes("已有档案")) {
        navigate(`/profile/${result.user.scholar_id}`);
        return;
      }
      setDiscovery(result);
      api.listUsers().then(setExistingUsers).catch(() => {});
    } catch (err: any) {
      alert(err?.message || "创建失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative min-h-screen overflow-hidden bg-gradient-to-br from-indigo-50 via-white to-purple-50">
      {/* Decorative animated background */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
        {/* Large floating blobs — vivid & fast drift */}
        <motion.div
          className="absolute -right-16 -top-16 h-[30rem] w-[30rem] rounded-full bg-gradient-to-br from-indigo-300/50 to-purple-400/40 blur-3xl"
          animate={{ x: [0, 60, -40, 0], y: [0, -50, 30, 0], scale: [1, 1.15, 0.9, 1] }}
          transition={{ duration: 12, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="absolute -bottom-20 -left-20 h-[32rem] w-[32rem] rounded-full bg-gradient-to-tr from-sky-300/40 to-indigo-300/30 blur-3xl"
          animate={{ x: [0, -40, 50, 0], y: [0, 40, -30, 0], scale: [1, 0.88, 1.12, 1] }}
          transition={{ duration: 15, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="absolute right-0 top-1/3 h-80 w-80 rounded-full bg-gradient-to-bl from-violet-300/40 to-pink-300/30 blur-2xl"
          animate={{ x: [0, -30, 40, 0], y: [0, 50, -40, 0], scale: [1, 1.1, 0.92, 1] }}
          transition={{ duration: 10, repeat: Infinity, ease: "easeInOut" }}
        />
        {/* Extra accent blob */}
        <motion.div
          className="absolute left-1/3 top-16 h-48 w-48 rounded-full bg-gradient-to-r from-cyan-300/30 to-blue-300/25 blur-2xl"
          animate={{ x: [0, 35, -25, 0], y: [0, -30, 20, 0] }}
          transition={{ duration: 9, repeat: Infinity, ease: "easeInOut" }}
        />

        {/* Grid pattern overlay */}
        <svg className="absolute inset-0 h-full w-full opacity-[0.04]">
          <defs>
            <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
              <path d="M 40 0 L 0 0 0 40" fill="none" stroke="currentColor" strokeWidth="1" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid)" />
        </svg>

        {/* Orbiting double ring — larger, faster */}
        <motion.svg
          className="absolute left-4 top-24 h-32 w-32 text-indigo-400/30"
          viewBox="0 0 80 80"
          animate={{ rotate: 360 }}
          transition={{ duration: 20, repeat: Infinity, ease: "linear" }}
        >
          <circle cx="40" cy="40" r="36" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <circle cx="40" cy="40" r="22" fill="none" stroke="currentColor" strokeWidth="1" strokeDasharray="6 4" />
          <circle cx="40" cy="4" r="3.5" fill="currentColor" opacity="0.8" />
        </motion.svg>

        {/* Second orbiting ring — right side */}
        <motion.svg
          className="absolute right-8 top-48 h-24 w-24 text-purple-400/25"
          viewBox="0 0 80 80"
          animate={{ rotate: -360 }}
          transition={{ duration: 25, repeat: Infinity, ease: "linear" }}
        >
          <circle cx="40" cy="40" r="34" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="8 5" />
          <circle cx="40" cy="6" r="3" fill="currentColor" opacity="0.7" />
          <circle cx="74" cy="40" r="2.5" fill="currentColor" opacity="0.5" />
        </motion.svg>

        {/* Pulsing hexagon */}
        <motion.svg
          className="absolute bottom-40 right-16 h-24 w-24 text-purple-400/30"
          viewBox="0 0 100 100"
          animate={{ scale: [1, 1.2, 1], opacity: [0.3, 0.5, 0.3], rotate: [0, 30, 0] }}
          transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
        >
          <polygon points="50,5 93,27.5 93,72.5 50,95 7,72.5 7,27.5" fill="none" stroke="currentColor" strokeWidth="2" />
        </motion.svg>

        {/* Spinning triangle — bigger */}
        <motion.svg
          className="absolute left-[15%] top-[65%] h-20 w-20 text-sky-400/30"
          viewBox="0 0 48 48"
          animate={{ rotate: -360 }}
          transition={{ duration: 18, repeat: Infinity, ease: "linear" }}
        >
          <polygon points="24,2 46,42 2,42" fill="none" stroke="currentColor" strokeWidth="2" />
        </motion.svg>

        {/* Animated connecting lines */}
        <svg className="absolute inset-0 h-full w-full text-indigo-400/10">
          <line x1="10%" y1="25%" x2="40%" y2="10%" stroke="currentColor" strokeWidth="1" strokeDasharray="6 8">
            <animate attributeName="stroke-dashoffset" from="0" to="28" dur="4s" repeatCount="indefinite" />
          </line>
          <line x1="60%" y1="85%" x2="90%" y2="55%" stroke="currentColor" strokeWidth="1" strokeDasharray="6 8">
            <animate attributeName="stroke-dashoffset" from="0" to="-28" dur="5s" repeatCount="indefinite" />
          </line>
          <line x1="80%" y1="15%" x2="65%" y2="50%" stroke="currentColor" strokeWidth="1" strokeDasharray="4 6">
            <animate attributeName="stroke-dashoffset" from="0" to="20" dur="3s" repeatCount="indefinite" />
          </line>
        </svg>

        {/* Floating particles — more, bigger, brighter */}
        {[
          { left: "10%", top: "18%", size: 3, delay: 0, dur: 7 },
          { left: "70%", top: "12%", size: 4, delay: 1, dur: 8 },
          { left: "88%", top: "55%", size: 3, delay: 2, dur: 6 },
          { left: "20%", top: "75%", size: 3.5, delay: 0.5, dur: 9 },
          { left: "55%", top: "40%", size: 2.5, delay: 1.5, dur: 7 },
          { left: "40%", top: "8%", size: 3, delay: 3, dur: 8 },
          { left: "92%", top: "30%", size: 2, delay: 2.5, dur: 10 },
          { left: "5%", top: "55%", size: 3.5, delay: 0, dur: 6 },
          { left: "48%", top: "70%", size: 2.5, delay: 4, dur: 9 },
          { left: "78%", top: "78%", size: 3, delay: 1, dur: 7 },
        ].map((p, i) => (
          <motion.div
            key={i}
            className="absolute rounded-full bg-indigo-500/25"
            style={{ left: p.left, top: p.top, width: p.size * 2, height: p.size * 2 }}
            animate={{ y: [0, -30, 15, -20, 0], x: [0, 10, -8, 5, 0], opacity: [0.25, 0.6, 0.2, 0.5, 0.25] }}
            transition={{ duration: p.dur, delay: p.delay, repeat: Infinity, ease: "easeInOut" }}
          />
        ))}
      </div>

      <div className="relative mx-auto max-w-2xl px-4 py-12">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: "easeOut" }}
          className="mb-12 text-center"
        >
          <h1 className="mb-3 text-4xl font-bold tracking-tight text-gray-900">
            你的科研影响力，一站聚合
          </h1>
          <p className="text-lg text-gray-500">
            输入 Semantic Scholar ID，自动关联学术与工程账号。
          </p>
        </motion.div>

        {/* Site Stats */}
        {siteStats && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.1, ease: "easeOut" }}
            className="mb-8 grid grid-cols-4 gap-3"
          >
            {[
              { icon: <Users className="h-4 w-4" />, value: siteStats.total_profiles, label: "研究者档案", color: "from-indigo-500/10 to-indigo-500/5 border-indigo-200/60", iconColor: "text-indigo-500", numColor: "text-indigo-700" },
              { icon: <FileText className="h-4 w-4" />, value: siteStats.total_papers, label: "追踪论文", color: "from-emerald-500/10 to-emerald-500/5 border-emerald-200/60", iconColor: "text-emerald-500", numColor: "text-emerald-700" },
              { icon: <Star className="h-4 w-4" />, value: siteStats.total_stars, label: "GitHub Stars", color: "from-amber-500/10 to-amber-500/5 border-amber-200/60", iconColor: "text-amber-500", numColor: "text-amber-700" },
              { icon: <Eye className="h-4 w-4" />, value: siteStats.total_views, label: "总访问量", color: "from-sky-500/10 to-sky-500/5 border-sky-200/60", iconColor: "text-sky-500", numColor: "text-sky-700" },
            ].map((stat) => (
              <div key={stat.label} className={`flex flex-col items-center rounded-xl border bg-gradient-to-b ${stat.color} px-3 py-3 backdrop-blur`}>
                <div className={`mb-1 ${stat.iconColor}`}>{stat.icon}</div>
                <div className={`text-lg font-bold ${stat.numColor}`}>{formatNum(stat.value)}</div>
                <div className="text-[11px] text-gray-500">{stat.label}</div>
              </div>
            ))}
          </motion.div>
        )}

        <motion.form
          onSubmit={handleSubmit}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.15, ease: "easeOut" }}
          className="rounded-2xl border border-gray-200 bg-white p-8 shadow-sm hover-lift"
        >
          <h2 className="mb-2 text-xl font-semibold text-gray-900">
            创建新档案
          </h2>
          <p className="mb-6 text-sm text-gray-400">
            搜索你的名字，从 Semantic Scholar 中选择你的学术档案
          </p>

          <div className="flex items-start gap-3">
            <div className="mt-2 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-indigo-600 text-white">
              <BookOpen className="h-5 w-5" />
            </div>
            <div className="relative flex-1" ref={dropdownRef}>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                搜索学者
              </label>
              <div className="relative">
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => handleSearch(e.target.value)}
                  onFocus={() => searchResults.length > 0 && setShowDropdown(true)}
                  placeholder="输入姓名搜索，如 Andrej Karpathy"
                  className="w-full rounded-lg border border-gray-200 px-4 py-2.5 text-sm outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
                  autoFocus
                />
                {searching && (
                  <Loader2 className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-gray-400" />
                )}
              </div>

              {/* Selected scholar preview */}
              {selectedScholar && (
                <div className="mt-2 flex items-center gap-3 rounded-lg bg-indigo-50 px-3 py-2.5">
                  <CheckCircle2 className="h-4 w-4 shrink-0 text-indigo-600" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-gray-900 truncate">{selectedScholar.name}</div>
                    <div className="text-xs text-gray-500">
                      {selectedScholar.paperCount} Publications · {formatNum(selectedScholar.citationCount)} Citations · h-index {selectedScholar.hIndex}
                      {selectedScholar.affiliations.length > 0 && ` · ${selectedScholar.affiliations[0]}`}
                    </div>
                  </div>
                  <button type="button" onClick={() => { setSelectedScholar(null); setSearchQuery(""); }} className="text-gray-400 hover:text-gray-600">
                    <XCircle className="h-4 w-4" />
                  </button>
                </div>
              )}

              {/* Dropdown results */}
              <AnimatePresence>
                {showDropdown && searchResults.length > 0 && (
                  <motion.div
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -4 }}
                    className="absolute z-50 mt-1 max-h-96 w-full overflow-y-auto rounded-xl border border-gray-200 bg-white shadow-lg"
                  >
                    {searchResults.map((s) => (
                      <button
                        key={s.authorId}
                        type="button"
                        onClick={() => handleSelect(s)}
                        className="flex w-full items-start gap-3 border-b border-gray-50 px-4 py-3.5 text-left transition last:border-0 hover:bg-indigo-50/60"
                      >
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-sm font-bold text-indigo-600">
                          {(s.name || "?")[0]}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-semibold text-gray-900 truncate">{s.name}</div>
                          {s.affiliations.length > 0 && (
                            <div className="mt-0.5 text-xs text-gray-500 truncate">{s.affiliations.join(" · ")}</div>
                          )}
                          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs">
                            <span className="text-gray-500">
                              <span className="font-medium text-gray-700">{s.paperCount}</span> Publications
                            </span>
                            <span className="text-gray-300">|</span>
                            <span className="text-gray-500">
                              <span className="font-medium text-gray-700">{formatNum(s.citationCount)}</span> Citations
                            </span>
                            {s.domain && (
                              <>
                                <span className="text-gray-300">|</span>
                                <span className="text-gray-500">{s.domain}</span>
                              </>
                            )}
                          </div>
                        </div>
                      </button>
                    ))}
                    {hasMore && (
                      <button
                        type="button"
                        onClick={handleLoadMore}
                        disabled={loadingMore}
                        className="flex w-full items-center justify-center gap-1.5 py-3 text-xs font-medium text-indigo-600 transition hover:bg-indigo-50 disabled:opacity-50"
                      >
                        {loadingMore ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          "加载更多结果"
                        )}
                      </button>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>

          {/* Manual ID input */}
          <div className="mt-4 flex items-start gap-3">
            <div className="mt-2 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gray-100 text-gray-500">
              <Hash className="h-5 w-5" />
            </div>
            <div className="flex-1">
              <label className="mb-1 block text-sm font-medium text-gray-700">
                直接输入 Semantic Scholar ID
              </label>
              <input
                type="text"
                value={manualId}
                onChange={(e) => { setManualId(e.target.value); setSelectedScholar(null); }}
                placeholder="如 47767550"
                className="w-full rounded-lg border border-gray-200 px-4 py-2.5 text-sm outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
              />
              <p className="mt-1 text-xs text-gray-400">
                搜不到？从 <a href="https://www.semanticscholar.org" target="_blank" rel="noopener noreferrer" className="text-indigo-500 underline underline-offset-2">semanticscholar.org</a> 找到你的主页，URL 中的数字即为 ID
              </p>
            </div>
          </div>

          <button
            type="submit"
            disabled={loading || (!selectedScholar && !manualId.trim() && !searchQuery.trim())}
            className="group mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-indigo-600 via-purple-600 to-indigo-600 bg-[length:200%_100%] py-3 text-sm font-semibold text-white transition-all hover:bg-[position:100%_0] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                正在查找账号...
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4" />
                自动发现并创建
              </>
            )}
          </button>
        </motion.form>

        {/* Discovery Result */}
        <AnimatePresence>
        {discovery && (
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96 }}
            transition={{ duration: 0.4, ease: "easeOut" }}
            className="mt-6 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm"
          >
            <div className="mb-4 flex items-center gap-3">
              {discovery.user.avatar_url && (
                <img src={discovery.user.avatar_url} className="h-12 w-12 rounded-xl" alt="" />
              )}
              <div>
                <div className="font-semibold text-gray-900">{discovery.user.name}</div>
                <div className="text-xs text-gray-400">{discovery.user.bio}</div>
              </div>
            </div>

            {/* Auto-discovered platforms summary */}
            <div className="flex flex-wrap gap-2 mb-4">
              <span className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-600">
                <BookOpen className="h-3 w-3" /> Scholar
              </span>
              {(discovery.github_found ?? Boolean(discovery.user.github_username)) && (
                <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-600">
                  <Github className="h-3 w-3" /> {discovery.user.github_username}
                </span>
              )}
              {discovery.hf_found && (
                <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-600">
                  <Box className="h-3 w-3" /> {discovery.user.hf_username}
                </span>
              )}
            </div>

            <p className="text-xs text-gray-400">{discovery.message}</p>
            <p className="mt-1 text-xs text-gray-400">其他平台可在主页设置中随时关联。</p>

            <button
              onClick={() => navigate(`/profile/${discovery.user.scholar_id}`)}
              className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-700"
            >
              进入主页 <ArrowRight className="h-4 w-4" />
            </button>
          </motion.div>
        )}
        </AnimatePresence>

        {/* Features */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.4, delay: 0.3 }}
          className="mt-12 mb-6"
        >
          <h2 className="mb-6 text-center text-lg font-semibold text-gray-800">
            一个平台，全面洞察你的科研影响力
          </h2>
          <div className="grid grid-cols-3 gap-4">
            {[
              { icon: <BarChart3 className="h-5 w-5" />, color: "indigo", title: "多维雷达图", desc: "学术深度、代码影响、数据贡献、产出广度、h-index 五维评估" },
              { icon: <Quote className="h-5 w-5" />, color: "violet", title: "引用分析", desc: "论文级引用趋势、CCF 等级分布、IEEE Fellow / 院士引用识别" },
              { icon: <Globe className="h-5 w-5" />, color: "emerald", title: "社区讨论", desc: "LLM 驱动的实时网络搜索，追踪社区对你工作的讨论与评价" },
              { icon: <TrendingUp className="h-5 w-5" />, color: "amber", title: "增长追踪", desc: "Stars、下载量、引用数的历史快照与增长趋势图" },
              { icon: <Award className="h-5 w-5" />, color: "rose", title: "里程碑", desc: "自动检测关键成就：首篇论文、Star 破千、被知名学者引用等" },
              { icon: <Share2 className="h-5 w-5" />, color: "sky", title: "分享卡片", desc: "一键生成精美分享卡片，展示你的科研影响力全貌" },
              { icon: <Bot className="h-5 w-5" />, color: "indigo", title: "AI 个人总结", desc: "基于全部数据由 AI 自动生成研究者画像，一段话概括科研生涯" },
              { icon: <Tags className="h-5 w-5" />, color: "violet", title: "趣味头衔", desc: "AI 生成个性化标签：「开源布道者」「引用收割机」「跨界炼丹师」" },
              { icon: <ClipboardList className="h-5 w-5" />, color: "emerald", title: "研究基础生成器", desc: "面向国自然申报，选基金类型 → 选代表作 → 自动生成含融入式证据链的「研究基础与可行性分析」段落" },
            ].map((feat, i) => (
              <motion.div
                key={feat.title}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.35 + i * 0.08, ease: "easeOut" }}
                className="h-full"
              >
                <FeatureCard {...feat} />
              </motion.div>
            ))}
          </div>
        </motion.div>
        {existingUsers.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.7, ease: "easeOut" }}
            className="mt-12 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm"
          >
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">
              示例档案
            </h2>
            <div className="space-y-2">
              {existingUsers.slice(0, 4).map((u) => (
                <button
                  key={u.id}
                  onClick={() => navigate(`/profile/${u.scholar_id || u.id}`)}
                  className="flex w-full items-center justify-between rounded-xl border border-gray-100 px-4 py-3 text-left hover-lift"
                >
                  <div className="flex items-center gap-3">
                    {u.avatar_url ? (
                      <img src={u.avatar_url} className="h-9 w-9 rounded-full" alt="" />
                    ) : (
                      <div className="flex h-9 w-9 items-center justify-center rounded-full bg-indigo-100 text-sm font-bold text-indigo-600">
                        {(u.name || "?")[0]}
                      </div>
                    )}
                    <div>
                      <div className="font-medium text-gray-900">
                        {u.name || u.github_username}
                      </div>
                      <div className="flex items-center gap-2 text-xs text-gray-400">
                        {u.scholar_id && <span className="text-indigo-500">Scholar</span>}
                        {u.github_username && <span>@{u.github_username}</span>}
                        {u.hf_username && <span className="text-amber-500">HF</span>}
                      </div>
                    </div>
                  </div>
                  <ArrowRight className="h-4 w-4 text-gray-300" />
                </button>
              ))}
            </div>
            {existingUsers.length > 4 && (
              <p className="mt-3 text-center text-xs text-gray-400">
                共 {existingUsers.length} 个档案，仅展示前 4 个
              </p>
            )}
          </motion.div>
        )}
      </div>
    </div>
  );
}

const colorMap: Record<string, { bg: string; text: string; icon: string }> = {
  indigo: { bg: "bg-indigo-50", text: "text-indigo-700", icon: "text-indigo-500" },
  violet: { bg: "bg-violet-50", text: "text-violet-700", icon: "text-violet-500" },
  emerald: { bg: "bg-emerald-50", text: "text-emerald-700", icon: "text-emerald-500" },
  amber: { bg: "bg-amber-50", text: "text-amber-700", icon: "text-amber-500" },
  rose: { bg: "bg-rose-50", text: "text-rose-700", icon: "text-rose-500" },
  sky: { bg: "bg-sky-50", text: "text-sky-700", icon: "text-sky-500" },
};

function FeatureCard({
  icon,
  color,
  title,
  desc,
}: {
  icon: React.ReactNode;
  color: string;
  title: string;
  desc: string;
}) {
  const c = colorMap[color] || colorMap.indigo;
  return (
    <div className={`flex h-full flex-col rounded-xl border border-gray-100 ${c.bg} p-4 hover-lift cursor-default`}>
      <div className={`mb-2 ${c.icon}`}>{icon}</div>
      <div className={`mb-1 text-sm font-semibold ${c.text}`}>{title}</div>
      <div className="text-xs leading-relaxed text-gray-500">{desc}</div>
    </div>
  );
}

function PlatformRow({
  icon,
  name,
  found,
  detail,
  confidence,
}: {
  icon: React.ReactNode;
  name: string;
  found: boolean;
  detail?: string;
  confidence?: string;
}) {
  return (
    <div className={`flex items-center gap-3 rounded-lg px-3 py-2.5 ${
      found ? "bg-emerald-50" : "bg-gray-50"
    }`}>
      <div className={`${found ? "text-emerald-600" : "text-gray-400"}`}>{icon}</div>
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <span className={`text-sm font-medium ${found ? "text-gray-900" : "text-gray-400"}`}>
            {name}
          </span>
          {found && confidence && confidence !== "manual" && (
            <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
              confidence === "high"
                ? "bg-emerald-100 text-emerald-700"
                : "bg-amber-100 text-amber-700"
            }`}>
              {confidence === "high" ? "高置信" : "可能匹配"}
            </span>
          )}
        </div>
        {detail && <div className="text-xs text-gray-400">{detail}</div>}
        {!found && <div className="text-xs text-amber-500">未找到，可在主页手动关联</div>}
      </div>
      {found ? (
        <CheckCircle2 className="h-4 w-4 text-emerald-500" />
      ) : (
        <XCircle className="h-4 w-4 text-gray-300" />
      )}
    </div>
  );
}

function formatNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return String(n);
}
