import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  GraduationCap, Search, MapPin, Building2, Users, Loader2,
  ExternalLink, ChevronRight, ChevronDown, Award, ArrowLeft, RefreshCw, Sparkles,
  UserCircle2, Mail, BookOpen,
} from "lucide-react";
import {
  api,
  type AdvisorSchoolBrief,
  type AdvisorSchoolDetail,
  type AdvisorBrief,
} from "@/lib/api";

// ──────────────── Index page ────────────────

// Provisional scope: 清北华五 + CS/AI only. Backend still has everything;
// this filters what the frontend surfaces until we expand coverage.
const ELITE_SCHOOLS: Array<{ name: string; short: string }> = [
  { name: "清华大学", short: "清华" },
  { name: "北京大学", short: "北大" },
  { name: "复旦大学", short: "复旦" },
  { name: "上海交通大学", short: "上交" },
  { name: "中国科学技术大学", short: "中科大" },
  { name: "浙江大学", short: "浙大" },
  { name: "南京大学", short: "南大" },
];
const ELITE_NAME_SET = new Set<string>(ELITE_SCHOOLS.map((s) => s.name));
const ELITE_SHORT_SET = new Set<string>(ELITE_SCHOOLS.map((s) => s.short));
const isEliteSchool = (s: { name?: string; short_name?: string }) =>
  ELITE_NAME_SET.has((s.name || "").trim()) || ELITE_SHORT_SET.has((s.short_name || "").trim());
const CS_AI_KEYWORDS = ["计算机", "人工智能", "软件", "信息", "AI", "智能", "数据", "网络空间"];
const isCsAiCollege = (name: string) => CS_AI_KEYWORDS.some((k) => name.includes(k));

export default function AdvisorPage() {
  const { schoolId } = useParams<{ schoolId?: string }>();
  if (schoolId) {
    return <SchoolDetail schoolId={Number(schoolId)} />;
  }
  return <SchoolDirectory />;
}

const TIER_COLORS = {
  "985": { bg: "bg-amber-100", text: "text-amber-800", border: "border-amber-300" },
  "211": { bg: "bg-indigo-100", text: "text-indigo-800", border: "border-indigo-300" },
  "双一流": { bg: "bg-emerald-100", text: "text-emerald-800", border: "border-emerald-300" },
};

const SCHOOL_TYPE_COLORS: Record<string, string> = {
  "综合": "bg-blue-50 text-blue-700",
  "理工": "bg-cyan-50 text-cyan-700",
  "师范": "bg-rose-50 text-rose-700",
  "财经": "bg-amber-50 text-amber-700",
  "医药": "bg-emerald-50 text-emerald-700",
  "政法": "bg-slate-50 text-slate-700",
  "农林": "bg-lime-50 text-lime-700",
  "民族": "bg-purple-50 text-purple-700",
  "语言": "bg-fuchsia-50 text-fuchsia-700",
  "艺术": "bg-pink-50 text-pink-700",
  "军事": "bg-stone-50 text-stone-700",
  "体育": "bg-orange-50 text-orange-700",
};

function SchoolDirectory() {
  const [schools, setSchools] = useState<AdvisorSchoolBrief[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [province, setProvince] = useState("");
  const [tier, setTier] = useState<"" | "985" | "211">("");
  const [schoolType, setSchoolType] = useState("");

  useEffect(() => {
    setLoading(true);
    api.listAdvisorSchools({
      q: q || undefined,
      province: province || undefined,
      tier: tier || undefined,
      school_type: schoolType || undefined,
    })
      .then((all) => {
        const filtered = all.filter(isEliteSchool);
        if (filtered.length === 0 && all.length > 0) {
          console.warn("[advisor] elite filter matched 0; sample names:", all.slice(0, 5).map((s) => `${s.name}|${s.short_name}`));
        }
        setSchools(filtered);
      })
      .catch(() => setSchools([]))
      .finally(() => setLoading(false));
  }, [q, province, tier, schoolType]);

  // Derive filter options from the elite-scoped school list, not the full-DB stats.
  const provinces = useMemo(() => {
    const m = new Map<string, number>();
    for (const s of schools) if (s.province) m.set(s.province, (m.get(s.province) || 0) + 1);
    return Array.from(m.entries()).sort((a, b) => b[1] - a[1]);
  }, [schools]);
  const schoolTypes = useMemo(() => {
    const m = new Map<string, number>();
    for (const s of schools) if (s.school_type) m.set(s.school_type, (m.get(s.school_type) || 0) + 1);
    return Array.from(m.entries()).sort((a, b) => b[1] - a[1]);
  }, [schools]);

  return (
    <main className="mx-auto max-w-6xl px-4 py-6">
      {/* Hero */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="mb-6 rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50 via-white to-purple-50 p-6 shadow-sm"
      >
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white">
              <GraduationCap className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900">保研导师库</h1>
              <p className="text-xs text-gray-500">
                当前范围：<strong>清北华五 7 所</strong> 高校 · 仅 <strong>计算机 / 人工智能</strong> 方向
              </p>
            </div>
          </div>
          <div className="hidden md:flex items-center gap-4 text-xs text-gray-600">
            <Stat label="高校" value={ELITE_SCHOOLS.length} />
            <Stat label="已加载" value={schools.length} highlight />
          </div>
        </div>
      </motion.div>

      {/* Filter bar */}
      <div className="mb-4 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          {/* Search */}
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              placeholder="搜索学校名 / 简称 / 城市…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="w-full rounded-xl border border-gray-200 bg-gray-50 pl-9 pr-3 py-2 text-sm focus:border-indigo-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-100"
            />
          </div>
          {/* Tier */}
          <Select value={tier} onChange={(v) => setTier(v as typeof tier)}
            options={[
              { value: "", label: "全部层次" },
              { value: "985", label: "985" },
              { value: "211", label: "211" },
            ]} />
          {/* Province */}
          <Select value={province} onChange={setProvince}
            options={[{ value: "", label: "全部省份" }, ...provinces.map(([p, c]) => ({ value: p, label: `${p} (${c})` }))]} />
          {/* School type */}
          <Select value={schoolType} onChange={setSchoolType}
            options={[{ value: "", label: "全部类型" }, ...schoolTypes.map(([t, c]) => ({ value: t, label: `${t} (${c})` }))]} />
        </div>
        <div className="mt-2 text-xs text-gray-400">{loading ? "加载中…" : `${schools.length} 所匹配`}</div>
      </div>

      {/* School grid */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        <AnimatePresence>
          {schools.map((s, i) => (
            <motion.div
              key={s.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(i * 0.015, 0.5), duration: 0.25 }}
            >
              <SchoolCard school={s} />
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {!loading && schools.length === 0 && (
        <div className="rounded-2xl border border-dashed border-gray-200 bg-gray-50 p-8 text-center text-sm text-gray-400">
          没有匹配的学校
        </div>
      )}
    </main>
  );
}

function SchoolCard({ school }: { school: AdvisorSchoolBrief }) {
  const tierColor = school.is_985 ? TIER_COLORS["985"] : school.is_211 ? TIER_COLORS["211"] : TIER_COLORS["双一流"];
  const tierLabel = school.is_985 ? "985" : school.is_211 ? "211" : "双一流";
  const typeColor = SCHOOL_TYPE_COLORS[school.school_type] || "bg-gray-50 text-gray-700";

  return (
    <Link
      to={`/advisor/schools/${school.id}`}
      className="group block rounded-2xl border border-gray-200 bg-white p-4 shadow-sm transition hover:border-indigo-300 hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 mb-1">
            <span className={`inline-flex items-center rounded-full border ${tierColor.bg} ${tierColor.text} ${tierColor.border} px-1.5 py-0.5 text-[10px] font-bold`}>
              {tierLabel}
            </span>
            <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] ${typeColor}`}>
              {school.school_type}
            </span>
          </div>
          <div className="text-base font-bold text-gray-900 group-hover:text-indigo-600 truncate">
            {school.name}
          </div>
          {school.english_name && (
            <div className="mt-0.5 text-[11px] text-gray-400 truncate">{school.english_name}</div>
          )}
        </div>
        <ChevronRight className="h-4 w-4 shrink-0 text-gray-300 group-hover:text-indigo-500 transition" />
      </div>

      <div className="mt-3 flex items-center justify-between text-[11px] text-gray-500">
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1">
            <MapPin className="h-3 w-3" />
            {school.city}
          </span>
          {school.college_count > 0 && (
            <span className="inline-flex items-center gap-1">
              <Building2 className="h-3 w-3" />
              {school.college_count} 学院
            </span>
          )}
          {school.advisor_count > 0 && (
            <span className="inline-flex items-center gap-1 text-indigo-600 font-medium">
              <Users className="h-3 w-3" />
              {school.advisor_count} 导师
            </span>
          )}
        </div>
        {school.homepage_url && (
          <a
            href={school.homepage_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-gray-400 hover:text-gray-600"
          >
            <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
    </Link>
  );
}

// ──────────────── School detail page ────────────────

function SchoolDetail({ schoolId }: { schoolId: number }) {
  const navigate = useNavigate();
  const [data, setData] = useState<AdvisorSchoolDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [crawling, setCrawling] = useState(false);

  const refresh = () => api.getAdvisorSchool(schoolId).then(setData).catch(() => {});

  useEffect(() => {
    setLoading(true);
    refresh().finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schoolId]);

  useEffect(() => {
    if (!crawling) return;
    const id = window.setInterval(refresh, 6000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [crawling]);

  // Auto-stop polling when crawl looks done (colleges_crawled_at advanced + has colleges)
  useEffect(() => {
    if (!crawling || !data) return;
    if (data.colleges.length > 0 && data.colleges_crawled_at) {
      // Wait one more poll to be safe, then stop
      const t = setTimeout(() => setCrawling(false), 6000);
      return () => clearTimeout(t);
    }
  }, [data, crawling]);

  const handleCrawl = async (fetchAdvisors: boolean) => {
    setCrawling(true);
    try {
      await api.crawlAdvisorSchool(schoolId, fetchAdvisors);
    } catch {
      setCrawling(false);
    }
  };

  if (loading) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-12 text-center text-sm text-gray-400">
        <Loader2 className="mx-auto h-6 w-6 animate-spin" />
      </main>
    );
  }

  if (!data) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-12 text-center text-sm text-gray-400">
        学校未找到
      </main>
    );
  }

  const s = data.school;
  if (!isEliteSchool(s)) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-12 text-center text-sm text-gray-500">
        <p className="mb-2">{s.name} 暂不在当前展示范围内</p>
        <p className="text-xs text-gray-400">当前仅开放清北华五 7 所高校的 CS/AI 导师</p>
        <button
          onClick={() => navigate("/advisor")}
          className="mt-4 inline-flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50"
        >
          <ArrowLeft className="h-3 w-3" />
          返回
        </button>
      </main>
    );
  }
  const csaiColleges = data.colleges.filter((c) => isCsAiCollege(c.name));
  const tierColor = s.is_985 ? TIER_COLORS["985"] : s.is_211 ? TIER_COLORS["211"] : TIER_COLORS["双一流"];

  return (
    <main className="mx-auto max-w-5xl px-4 py-6">
      <button
        onClick={() => navigate("/advisor")}
        className="mb-4 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-indigo-600"
      >
        <ArrowLeft className="h-4 w-4" />
        返回学校列表
      </button>

      {/* School header */}
      <div className="mb-6 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-2">
              <span className={`inline-flex items-center rounded-full border ${tierColor.bg} ${tierColor.text} ${tierColor.border} px-2 py-0.5 text-xs font-bold`}>
                {s.is_985 ? "985" : s.is_211 ? "211" : "双一流"}
              </span>
              <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-700">
                {s.school_type}
              </span>
              <span className="inline-flex items-center gap-1 text-xs text-gray-500">
                <MapPin className="h-3 w-3" />
                {s.city}, {s.province}
              </span>
            </div>
            <h1 className="text-2xl font-bold text-gray-900">{s.name}</h1>
            {s.english_name && (
              <div className="mt-1 text-sm text-gray-500">{s.english_name}</div>
            )}
          </div>
          <div className="flex items-center gap-2">
            {s.homepage_url && (
              <a
                href={s.homepage_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                官网
              </a>
            )}
            <button
              onClick={() => handleCrawl(false)}
              disabled={crawling}
              className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-100 disabled:opacity-50"
            >
              {crawling ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : data.colleges.length > 0 ? <RefreshCw className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}
              {crawling ? "抓取中…" : data.colleges.length > 0 ? "重新抓取学院" : "抓取学院"}
            </button>
            {data.colleges.length > 0 && (
              <button
                onClick={() => handleCrawl(true)}
                disabled={crawling}
                className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50"
                title="抓取所有学院的导师 stub（耗时较长，按学院数 × 30s 估算）"
              >
                {crawling ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                抓全院导师
              </button>
            )}
          </div>
        </div>

        <div className="mt-5 grid grid-cols-3 gap-3">
          <Stat label="CS/AI 学院" value={csaiColleges.length} />
          <Stat label="已收录导师" value={s.advisor_count} highlight />
          <Stat label="爬取状态" value={data.colleges_crawled_at ? "已完成" : "未抓取"} />
        </div>
      </div>

      {/* Colleges */}
      <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900">
            CS / AI 学院 <span className="ml-1 text-xs font-normal text-gray-400">仅显示计算机 / 人工智能方向</span>
          </h2>
          {!data.colleges.length && (
            <span className="text-xs text-gray-400">尚未抓取学院数据</span>
          )}
        </div>

        {data.colleges.length === 0 ? (
          <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 p-8 text-center text-sm text-gray-400">
            <Award className="mx-auto mb-2 h-8 w-8 opacity-30" />
            <p>该校学院列表尚未抓取</p>
            <p className="mt-1 text-[11px] text-gray-300">点击右上角"抓取学院"按钮启动 — 通常 30 秒内完成</p>
          </div>
        ) : csaiColleges.length === 0 ? (
          <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 p-8 text-center text-sm text-gray-400">
            该校已抓取 {data.colleges.length} 个学院，但无匹配 CS/AI 关键词的学院
          </div>
        ) : (
          <div className="space-y-2">
            {csaiColleges.map((c) => (
              <CollegeBlock key={c.id} college={c} />
            ))}
          </div>
        )}
      </div>
    </main>
  );
}

// ──────────────── College block with lazy advisor expansion ────────────────

function CollegeBlock({ college }: { college: { id: number; name: string; discipline_category: string; homepage_url: string; advisor_count: number } }) {
  const [open, setOpen] = useState(false);
  const [advisors, setAdvisors] = useState<AdvisorBrief[] | null>(null);
  const [loading, setLoading] = useState(false);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && advisors === null) {
      setLoading(true);
      try {
        const rows = await api.listAdvisorsInCollege(college.id);
        setAdvisors(rows);
      } catch {
        setAdvisors([]);
      } finally {
        setLoading(false);
      }
    }
  };

  return (
    <div className="rounded-xl border border-gray-200 bg-white">
      <button
        onClick={toggle}
        className="flex w-full items-center justify-between px-3 py-2.5 text-left text-sm hover:bg-gray-50"
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            {open ? <ChevronDown className="h-4 w-4 text-gray-400" /> : <ChevronRight className="h-4 w-4 text-gray-400" />}
            <span className="font-medium text-gray-900">{college.name}</span>
          </div>
          <div className="mt-0.5 ml-5 flex items-center gap-2 text-[11px] text-gray-500">
            {college.discipline_category && <span>{college.discipline_category}</span>}
            {college.advisor_count > 0 && (
              <span className="text-indigo-600">{college.advisor_count} 导师</span>
            )}
          </div>
        </div>
        {college.homepage_url && (
          <a
            href={college.homepage_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-gray-400 hover:text-indigo-500"
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        )}
      </button>
      {open && (
        <div className="border-t border-gray-100 bg-gray-50/50 p-3">
          {loading ? (
            <div className="py-6 text-center text-xs text-gray-400">
              <Loader2 className="mx-auto h-4 w-4 animate-spin" />
            </div>
          ) : !advisors || advisors.length === 0 ? (
            <div className="py-4 text-center text-xs text-gray-400">尚无导师数据</div>
          ) : (
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
              {advisors.map((a) => (
                <AdvisorCard key={a.id} advisor={a} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AdvisorCard({ advisor }: { advisor: AdvisorBrief }) {
  const linked = advisor.impacthub_user_id != null && advisor.impacthub_user_id !== 0;
  return (
    <div className="flex gap-3 rounded-lg border border-gray-200 bg-white p-3 text-sm shadow-sm">
      {/* Avatar */}
      <div className="shrink-0">
        {advisor.photo_url ? (
          <img
            src={advisor.photo_url}
            alt={advisor.name}
            className="h-12 w-12 rounded-full object-cover ring-1 ring-gray-200"
            onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
          />
        ) : (
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-indigo-100 to-purple-100 text-indigo-500">
            <UserCircle2 className="h-7 w-7" />
          </div>
        )}
      </div>

      {/* Main */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate font-semibold text-gray-900">{advisor.name}</span>
          {advisor.title && (
            <span className="shrink-0 rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700">{advisor.title}</span>
          )}
        </div>
        {advisor.research_areas && advisor.research_areas.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {advisor.research_areas.slice(0, 4).map((r) => (
              <span key={r} className="rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] text-indigo-700">{r}</span>
            ))}
          </div>
        )}
        {advisor.bio && (
          <p className="mt-1.5 line-clamp-2 text-[11px] leading-snug text-gray-500">{advisor.bio}</p>
        )}
        <div className="mt-2 flex items-center gap-3 text-[11px]">
          {linked ? (
            <Link
              to={`/profile/${advisor.impacthub_user_id}`}
              className="inline-flex items-center gap-1 rounded-md bg-indigo-600 px-2 py-1 font-medium text-white hover:bg-indigo-700"
            >
              <BookOpen className="h-3 w-3" />
              学术档案
            </Link>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2 py-1 text-gray-400" title="尚未匹配到 Semantic Scholar 档案">
              <BookOpen className="h-3 w-3" />
              档案待匹配
            </span>
          )}
          {advisor.homepage_url && (
            <a
              href={advisor.homepage_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-gray-500 hover:text-indigo-600"
            >
              <ExternalLink className="h-3 w-3" />
              个人主页
            </a>
          )}
          {advisor.email && (
            <a
              href={`mailto:${advisor.email}`}
              className="inline-flex items-center gap-1 text-gray-500 hover:text-indigo-600"
            >
              <Mail className="h-3 w-3" />
              邮件
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

// ──────────────── Tiny helpers ────────────────

function Stat({ label, value, highlight }: { label: string; value: string | number; highlight?: boolean }) {
  return (
    <div className={`rounded-lg ${highlight ? "bg-indigo-50" : "bg-gray-50"} px-3 py-2 text-center`}>
      <div className={`text-base font-bold tabular-nums ${highlight ? "text-indigo-700" : "text-gray-900"}`}>{value}</div>
      <div className="text-[10px] uppercase tracking-wider text-gray-400">{label}</div>
    </div>
  );
}

function Select({ value, onChange, options }: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}
