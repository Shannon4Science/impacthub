import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { Link } from "react-router-dom";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  Copy,
  ExternalLink,
  FileText,
  GraduationCap,
  Loader2,
  Mail,
  RefreshCw,
  School,
  SlidersHorizontal,
  Sparkles,
  UploadCloud,
  X,
} from "lucide-react";
import {
  api,
  type AdvisorCollegeBrief,
  type AdvisorSchoolBrief,
  type AdvisorRecommendation,
  type RecommendationAdvisor,
  type RecommendationResult,
  type RecommendationStatusResponse,
  type ResumeProjectSummary,
} from "@/lib/api";

const STATUS_STEPS = [
  { key: "queued", label: "上传" },
  { key: "parsing", label: "解析" },
  { key: "extracting", label: "抽取" },
  { key: "embedding", label: "向量" },
  { key: "recommending", label: "匹配" },
  { key: "completed", label: "完成" },
];

const statusOrder: Record<string, number> = STATUS_STEPS.reduce<Record<string, number>>(
  (acc, step, index) => {
    acc[step.key] = index;
    return acc;
  },
  {}
);

export default function RecommendationPage() {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [requirements, setRequirements] = useState("");
  const [topN, setTopN] = useState(3);
  const [schools, setSchools] = useState<AdvisorSchoolBrief[]>([]);
  const [schoolId, setSchoolId] = useState<number | "">("");
  const [colleges, setColleges] = useState<AdvisorCollegeBrief[]>([]);
  const [collegeId, setCollegeId] = useState<number | "">("");
  const [submitting, setSubmitting] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const [status, setStatus] = useState<RecommendationStatusResponse | null>(null);
  const [result, setResult] = useState<RecommendationResult | null>(null);
  const [error, setError] = useState("");
  const [selectedCoverLetterAdvisor, setSelectedCoverLetterAdvisor] = useState<RecommendationAdvisor | null>(null);
  const [coverLetter, setCoverLetter] = useState("");
  const [coverLetterError, setCoverLetterError] = useState("");
  const [generatingAdvisorId, setGeneratingAdvisorId] = useState<number | null>(null);
  const [copiedCoverLetter, setCopiedCoverLetter] = useState(false);

  useEffect(() => {
    api.listAdvisorSchools()
      .then((items) => {
        setSchools(items);
        const sjtu = items.find((s) => s.name === "上海交通大学");
        if (sjtu) setSchoolId(sjtu.id);
      })
      .catch(() => setSchools([]));
  }, []);

  useEffect(() => {
    if (!schoolId) {
      setColleges([]);
      setCollegeId("");
      return;
    }
    api.getAdvisorSchool(Number(schoolId))
      .then((detail) => {
        setColleges(detail.colleges);
        const aiCollege = detail.colleges.find((c) => c.name.includes("人工智能"));
        setCollegeId(aiCollege?.id ?? "");
      })
      .catch(() => {
        setColleges([]);
        setCollegeId("");
      });
  }, [schoolId]);

  useEffect(() => {
    if (!sessionId) return;
    if (status?.status === "completed" || status?.status === "failed") return;

    const tick = () => {
      api.getRecommendationStatus(sessionId)
        .then(setStatus)
        .catch((err: Error) => setError(err.message));
    };
    tick();
    const id = window.setInterval(tick, 1600);
    return () => window.clearInterval(id);
  }, [sessionId, status?.status]);

  useEffect(() => {
    if (!sessionId || status?.status !== "completed" || result) return;
    api.getRecommendationResult(sessionId)
      .then(setResult)
      .catch((err: Error) => setError(err.message));
  }, [sessionId, status?.status, result]);

  const selectedSchool = useMemo(
    () => schools.find((s) => s.id === schoolId),
    [schools, schoolId]
  );
  const selectedCollege = useMemo(
    () => colleges.find((c) => c.id === collegeId),
    [colleges, collegeId]
  );

  const acceptFile = (picked: File | undefined) => {
    if (!picked) return;
    if (!picked.name.toLowerCase().endsWith(".pdf")) {
      setError("只支持 PDF 简历");
      return;
    }
    setFile(picked);
    setError("");
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    acceptFile(Array.from(event.dataTransfer.files)[0]);
  };

  const submit = async () => {
    if (!file) {
      setError("请先选择 PDF 简历");
      return;
    }
    setSubmitting(true);
    setError("");
    setResult(null);
    setStatus(null);
    setSelectedCoverLetterAdvisor(null);
    setCoverLetter("");
    setCoverLetterError("");
    setCopiedCoverLetter(false);
    try {
      const upload = await api.uploadResumeForRecommendation(file, {
        requirements,
        top_n: topN,
        school_id: schoolId || undefined,
        college_id: collegeId || undefined,
      });
      setSessionId(upload.session_id);
      setStatus({
        session_id: upload.session_id,
        status: upload.status,
        progress: 5,
        message: "已上传，等待解析",
        error: null,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setSubmitting(false);
    }
  };

  const generateCoverLetter = async (advisor: RecommendationAdvisor) => {
    if (!sessionId) {
      setError("缺少推荐任务 ID");
      return;
    }
    setSelectedCoverLetterAdvisor(advisor);
    setCoverLetter("");
    setCoverLetterError("");
    setCopiedCoverLetter(false);
    setGeneratingAdvisorId(advisor.id);
    try {
      const response = await api.generateCoverLetter(sessionId, advisor.id);
      setCoverLetter(response.content);
    } catch (err) {
      setCoverLetterError(err instanceof Error ? err.message : "套磁信生成失败");
    } finally {
      setGeneratingAdvisorId(null);
    }
  };

  const copyCoverLetter = async () => {
    if (!coverLetter) return;
    try {
      await navigator.clipboard.writeText(coverLetter);
      setCopiedCoverLetter(true);
      window.setTimeout(() => setCopiedCoverLetter(false), 1600);
    } catch {
      setCoverLetterError("复制失败，请手动选择文本复制");
    }
  };

  const activeIndex = status ? statusOrder[status.status] ?? 0 : 0;

  return (
    <main className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-5 flex flex-col gap-3 border-b border-gray-200 pb-4 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-lg bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
            <Sparkles className="h-3.5 w-3.5" />
            保研导师匹配
          </div>
          <h1 className="text-2xl font-bold text-gray-900">导师推荐</h1>
          <p className="mt-1 text-sm text-gray-500">
            默认范围：{selectedSchool?.name || "全部学校"} {selectedCollege ? ` / ${selectedCollege.name}` : ""}
          </p>
        </div>
        <Link
          to="/advisor"
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
        >
          <GraduationCap className="h-4 w-4" />
          导师库
        </Link>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <section className="space-y-4">
          <div
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`rounded-lg border border-dashed bg-white p-5 shadow-sm transition ${
              dragging ? "border-emerald-400 bg-emerald-50" : "border-gray-300"
            }`}
          >
            <input
              ref={inputRef}
              type="file"
              accept="application/pdf,.pdf"
              className="hidden"
              onChange={(event) => acceptFile(event.target.files?.[0])}
            />
            <div className="flex items-start gap-4">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-slate-900 text-white">
                <UploadCloud className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="font-semibold text-gray-900">PDF 简历</div>
                <div className="mt-1 text-sm text-gray-500">
                  {file ? file.name : "拖拽到这里，或点击选择文件"}
                </div>
                {file && (
                  <div className="mt-2 inline-flex items-center gap-1.5 rounded-lg bg-gray-100 px-2 py-1 text-xs text-gray-600">
                    <FileText className="h-3.5 w-3.5" />
                    {(file.size / 1024 / 1024).toFixed(2)} MB
                    <button
                      type="button"
                      onClick={() => {
                        setFile(null);
                        if (inputRef.current) inputRef.current.value = "";
                      }}
                      className="ml-1 rounded p-0.5 text-gray-400 hover:bg-white hover:text-gray-700"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                )}
              </div>
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700"
              >
                选择
              </button>
            </div>
          </div>

          <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
            <label className="mb-2 block text-sm font-semibold text-gray-900">文字要求</label>
            <textarea
              value={requirements}
              onChange={(event) => setRequirements(event.target.value)}
              rows={6}
              placeholder="例如：希望导师方向偏计算机视觉、多模态、机器人，组内科研训练强，适合保研硕士。"
              className="w-full resize-none rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm leading-6 outline-none transition focus:border-emerald-400 focus:bg-white focus:ring-2 focus:ring-emerald-100"
            />
          </div>

          <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900">
              <SlidersHorizontal className="h-4 w-4" />
              推荐范围
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <label className="block">
                <span className="mb-1 block text-xs text-gray-500">学校</span>
                <select
                  value={schoolId}
                  onChange={(event) => setSchoolId(event.target.value ? Number(event.target.value) : "")}
                  className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm outline-none focus:border-emerald-400 focus:bg-white"
                >
                  <option value="">全部学校</option>
                  {schools.map((school) => (
                    <option key={school.id} value={school.id}>
                      {school.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-gray-500">学院</span>
                <select
                  value={collegeId}
                  onChange={(event) => setCollegeId(event.target.value ? Number(event.target.value) : "")}
                  className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm outline-none focus:border-emerald-400 focus:bg-white"
                  disabled={!schoolId}
                >
                  <option value="">全部学院</option>
                  {colleges.map((college) => (
                    <option key={college.id} value={college.id}>
                      {college.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-gray-500">数量</span>
                <select
                  value={topN}
                  onChange={(event) => setTopN(Number(event.target.value))}
                  className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm outline-none focus:border-emerald-400 focus:bg-white"
                >
                  {[3, 5, 8, 10].map((n) => (
                    <option key={n} value={n}>
                      Top {n}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          {error && (
            <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              {error}
            </div>
          )}

          <button
            type="button"
            onClick={submit}
            disabled={submitting || !file}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            开始推荐
          </button>
        </section>

        <section className="space-y-4">
          <ProgressPanel status={status} activeIndex={activeIndex} />
          {status?.status === "failed" && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              {status.error || "推荐任务失败"}
            </div>
          )}
          {result ? (
            <>
              <RecommendationList
                items={result.recommendations}
                generatingAdvisorId={generatingAdvisorId}
                onGenerateCoverLetter={generateCoverLetter}
              />
              <ResumeSummaryPanel result={result} />
            </>
          ) : (
            <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-sm text-gray-500 shadow-sm">
              <School className="mx-auto mb-3 h-8 w-8 text-gray-300" />
              推荐结果会显示在这里
            </div>
          )}
        </section>
      </div>
      {selectedCoverLetterAdvisor && (
        <CoverLetterModal
          advisor={selectedCoverLetterAdvisor}
          value={coverLetter}
          error={coverLetterError}
          isGenerating={generatingAdvisorId === selectedCoverLetterAdvisor.id}
          copied={copiedCoverLetter}
          onChange={setCoverLetter}
          onClose={() => setSelectedCoverLetterAdvisor(null)}
          onCopy={copyCoverLetter}
          onRegenerate={() => generateCoverLetter(selectedCoverLetterAdvisor)}
        />
      )}
    </main>
  );
}

function ProgressPanel({
  status,
  activeIndex,
}: {
  status: RecommendationStatusResponse | null;
  activeIndex: number;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-semibold text-gray-900">进度</div>
        <div className="text-xs text-gray-500">{status ? `${status.progress}%` : "未开始"}</div>
      </div>
      <div className="mb-4 h-2 overflow-hidden rounded-full bg-gray-100">
        <div
          className="h-full rounded-full bg-emerald-500 transition-all"
          style={{ width: `${status?.progress ?? 0}%` }}
        />
      </div>
      <div className="grid grid-cols-6 gap-2">
        {STATUS_STEPS.map((step, index) => {
          const done = status?.status === "completed" || index < activeIndex;
          const active = index === activeIndex && status?.status !== "completed";
          return (
            <div key={step.key} className="text-center">
              <div
                className={`mx-auto mb-1 flex h-7 w-7 items-center justify-center rounded-full border ${
                  done
                    ? "border-emerald-500 bg-emerald-500 text-white"
                    : active
                      ? "border-emerald-500 bg-emerald-50 text-emerald-700"
                      : "border-gray-200 bg-gray-50 text-gray-300"
                }`}
              >
                {done ? <CheckCircle2 className="h-4 w-4" /> : active ? <Loader2 className="h-4 w-4 animate-spin" /> : index + 1}
              </div>
              <div className={`text-[11px] ${done || active ? "text-gray-700" : "text-gray-400"}`}>{step.label}</div>
            </div>
          );
        })}
      </div>
      {status?.message && <div className="mt-3 text-xs text-gray-500">{status.message}</div>}
    </div>
  );
}

function RecommendationList({
  items,
  generatingAdvisorId,
  onGenerateCoverLetter,
}: {
  items: AdvisorRecommendation[];
  generatingAdvisorId: number | null;
  onGenerateCoverLetter: (advisor: RecommendationAdvisor) => void;
}) {
  return (
    <div className="space-y-3">
      {items.map((item, index) => (
        <AdvisorCard
          key={item.advisor.id}
          item={item}
          rank={index + 1}
          isGeneratingCoverLetter={generatingAdvisorId === item.advisor.id}
          onGenerateCoverLetter={onGenerateCoverLetter}
        />
      ))}
    </div>
  );
}

function AdvisorCard({
  item,
  rank,
  isGeneratingCoverLetter,
  onGenerateCoverLetter,
}: {
  item: AdvisorRecommendation;
  rank: number;
  isGeneratingCoverLetter: boolean;
  onGenerateCoverLetter: (advisor: RecommendationAdvisor) => void;
}) {
  const advisor = item.advisor;
  const percent = Math.round(item.similarity * 100);
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex gap-3">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-slate-100 text-sm font-bold text-slate-600">
          {advisor.photo_url ? (
            <img src={advisor.photo_url} alt={advisor.name} className="h-full w-full object-cover" />
          ) : (
            advisor.name.slice(0, 1)
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded bg-slate-900 px-1.5 py-0.5 text-[11px] font-semibold text-white">#{rank}</span>
            <h2 className="text-base font-bold text-gray-900">{advisor.name}</h2>
            {advisor.title && <span className="text-xs text-gray-500">{advisor.title}</span>}
            <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-xs font-semibold text-emerald-700">
              {percent}%
            </span>
          </div>
          <div className="mt-1 text-xs text-gray-500">
            {advisor.school_name} / {advisor.college_name}
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {advisor.research_areas.slice(0, 6).map((area) => (
              <span key={area} className="rounded bg-gray-100 px-2 py-1 text-xs text-gray-700">
                {area}
              </span>
            ))}
          </div>
          <p className="mt-3 text-sm leading-6 text-gray-700">{item.explanation}</p>
          {item.matched_keywords.length > 0 && (
            <div className="mt-2 text-xs text-gray-500">
              关键词：{item.matched_keywords.slice(0, 6).join("、")}
            </div>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="text-xs text-gray-500">H-index {advisor.h_index}</span>
            <span className="text-xs text-gray-500">引用 {advisor.citation_count}</span>
            {advisor.accepts_recommended != null && (
              <span className="text-xs text-gray-500">
                保研：{advisor.accepts_recommended ? "可能接收" : "未标记接收"}
              </span>
            )}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link
              to={`/advisor/advisors/${advisor.id}`}
              className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-2 text-xs font-medium text-white hover:bg-slate-700"
            >
              查看详情
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
            {advisor.homepage_url && (
              <a
                href={advisor.homepage_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-2 text-xs text-gray-700 hover:bg-gray-50"
              >
                主页
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}
            <button
              type="button"
              onClick={() => onGenerateCoverLetter(advisor)}
              disabled={isGeneratingCoverLetter}
              className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-200 px-3 py-2 text-xs font-medium text-emerald-700 hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isGeneratingCoverLetter ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Mail className="h-3.5 w-3.5" />}
              {isGeneratingCoverLetter ? "生成中" : "套磁信"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function CoverLetterModal({
  advisor,
  value,
  error,
  isGenerating,
  copied,
  onChange,
  onClose,
  onCopy,
  onRegenerate,
}: {
  advisor: RecommendationAdvisor;
  value: string;
  error: string;
  isGenerating: boolean;
  copied: boolean;
  onChange: (value: string) => void;
  onClose: () => void;
  onCopy: () => void;
  onRegenerate: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4 py-6">
      <div className="flex max-h-[92vh] w-full max-w-2xl flex-col rounded-lg bg-white shadow-xl">
        <div className="flex items-start justify-between gap-4 border-b border-gray-200 px-5 py-4">
          <div className="min-w-0">
            <div className="text-base font-bold text-gray-900">{advisor.name}的套磁信</div>
            <div className="mt-1 text-xs text-gray-500">
              {advisor.school_name} / {advisor.college_name}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {error && (
            <div className="mb-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              {error}
            </div>
          )}
          <textarea
            value={value}
            onChange={(event) => onChange(event.target.value)}
            rows={16}
            disabled={isGenerating && !value}
            placeholder={isGenerating ? "正在生成..." : "生成结果会显示在这里"}
            className="min-h-[360px] w-full resize-y rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm leading-7 text-gray-800 outline-none transition focus:border-emerald-400 focus:bg-white focus:ring-2 focus:ring-emerald-100 disabled:cursor-wait disabled:text-gray-400"
          />
          <div className="mt-2 text-right text-xs text-gray-500">字数 {value.length}</div>
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-gray-200 px-5 py-4">
          <button
            type="button"
            onClick={onCopy}
            disabled={!value || isGenerating}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Copy className="h-4 w-4" />
            {copied ? "已复制" : "复制"}
          </button>
          <button
            type="button"
            onClick={onRegenerate}
            disabled={isGenerating}
            className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-200 px-3 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isGenerating ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            重新生成
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}

function ResumeSummaryPanel({ result }: { result: RecommendationResult }) {
  const summary = result.resume_summary;
  return (
    <details className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <summary className="cursor-pointer text-sm font-semibold text-gray-900">简历摘要</summary>
      <div className="mt-4 space-y-4 text-sm text-gray-700">
        <SummaryBlock title="研究兴趣" items={summary.research_interests} />
        <SummaryBlock title="技能" items={summary.skills} />
        <SummaryBlock title="论文/成果" items={summary.publications} />
        <SummaryBlock title="荣誉" items={summary.honors} />
        {summary.education.length > 0 && (
          <div>
            <div className="mb-1 text-xs font-semibold text-gray-500">教育背景</div>
            <div className="space-y-1">
              {summary.education.map((edu, index) => (
                <div key={`${edu.school}-${index}`} className="rounded bg-gray-50 px-3 py-2 text-xs text-gray-700">
                  {[edu.school, edu.major, edu.degree, edu.gpa].filter(Boolean).join(" / ")}
                </div>
              ))}
            </div>
          </div>
        )}
        {summary.projects.length > 0 && (
          <div>
            <div className="mb-1 text-xs font-semibold text-gray-500">项目经历</div>
            <div className="space-y-2">
              {summary.projects.map((project, index) => (
                <ProjectSummary key={`${project.name}-${index}`} project={project} />
              ))}
            </div>
          </div>
        )}
      </div>
    </details>
  );
}

function SummaryBlock({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div>
      <div className="mb-1 text-xs font-semibold text-gray-500">{title}</div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <span key={item} className="rounded bg-gray-100 px-2 py-1 text-xs text-gray-700">
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

function ProjectSummary({ project }: { project: ResumeProjectSummary }) {
  return (
    <div className="rounded bg-gray-50 px-3 py-2">
      {project.name && <div className="text-xs font-semibold text-gray-900">{project.name}</div>}
      {project.description && <div className="mt-1 text-xs leading-5 text-gray-600">{project.description}</div>}
      {project.tech_stack && project.tech_stack.length > 0 && (
        <div className="mt-1 text-xs text-gray-500">{project.tech_stack.join("、")}</div>
      )}
    </div>
  );
}
