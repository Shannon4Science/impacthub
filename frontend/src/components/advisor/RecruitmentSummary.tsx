import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { RecruitmentSummaryResponse } from "../../lib/api";
import { Mail, Calendar, BookOpen, FileText, AlertCircle } from "lucide-react";
import { useState } from "react";

interface RecruitmentSummaryProps {
  advisorId: number;
}

export function RecruitmentSummary({ advisorId }: RecruitmentSummaryProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["advisor-recruitment", advisorId],
    queryFn: () => api.getAdvisorRecruitment(advisorId),
    staleTime: 24 * 60 * 60 * 1000, // 24小时
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
      </div>
    );
  }

  if (error) {
    const message = error instanceof Error ? error.message : "";
    if (message.includes("未找到招生信息")) {
      return (
        <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 p-6 text-sm text-gray-500">
          暂无可展示的招生摘要
        </div>
      );
    }
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-6">
        <p className="text-red-800">加载招生信息失败</p>
      </div>
    );
  }

  if (!data) {
    return null;
  }

  const overviewFacts = buildOverviewFacts(data);

  return (
    <div className="space-y-6">
      {/* 状态徽章 */}
      <RecruitmentStatusBadge status={data.recruitment_status} />

      {/* 概述 */}
      <div className="bg-white rounded-lg p-6 shadow-sm border border-gray-200">
        <h3 className="text-lg font-semibold text-gray-900 mb-3">招生概况</h3>
        <p className="text-gray-700 leading-relaxed">{data.summary}</p>
        {overviewFacts.length > 0 && (
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {overviewFacts.map((fact) => (
              <div key={fact.label} className="rounded-md border border-gray-200 bg-gray-50 px-3 py-2">
                <div className="text-xs font-medium text-gray-500">{fact.label}</div>
                <div className="mt-1 text-sm leading-5 text-gray-800">{fact.value}</div>
              </div>
            ))}
          </div>
        )}
        {data.latest_post_published_at && (
          <p className="text-sm text-gray-500 mt-3">
            最新信息发布于 {formatDate(data.latest_post_published_at)}
          </p>
        )}
        {data.cache_status === "stale" && (
          <div className="mt-3 flex items-center gap-2 text-amber-600 text-sm">
            <AlertCircle className="w-4 h-4" />
            <span>信息可能已过期</span>
          </div>
        )}
      </div>

      {/* 招生对象 */}
      {data.targets && data.targets.length > 0 && (
        <CollapsibleCard title="招生对象" icon={<FileText className="w-5 h-5" />} defaultOpen>
          <div className="space-y-3">
            {data.targets.map((target, idx) => (
              <div key={idx} className="border-l-4 border-indigo-400 pl-4 py-2">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-semibold text-gray-900">{target.type}</span>
                  {target.time_sensitivity === "possibly_stale" && (
                    <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded">可能已过期</span>
                  )}
                </div>
                {target.details && target.details.length > 0 && (
                  <ul className="text-sm text-gray-600 space-y-1">
                    {target.details.map((detail, i) => (
                      <li key={i}>• {detail}</li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </CollapsibleCard>
      )}

      {/* 研究方向 */}
      {data.research_directions && data.research_directions.length > 0 && (
        <CollapsibleCard title="研究方向" icon={<BookOpen className="w-5 h-5" />}>
          <div className="space-y-3">
            {data.research_directions.map((dir, idx) => (
              <div key={idx} className="border-l-4 border-emerald-400 pl-4 py-2">
                <p className="font-semibold text-gray-900 mb-1">{dir.direction}</p>
                {dir.details && dir.details.length > 0 && (
                  <ul className="text-sm text-gray-600 space-y-1">
                    {dir.details.map((detail, i) => (
                      <li key={i}>• {detail}</li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </CollapsibleCard>
      )}

      {/* 申请要求 */}
      {data.requirements && data.requirements.length > 0 && (
        <CollapsibleCard title="申请要求" icon={<AlertCircle className="w-5 h-5" />}>
          <ul className="space-y-2">
            {data.requirements.map((req, idx) => (
              <li key={idx} className="flex items-start gap-2 text-gray-700">
                <span className="text-indigo-600 mt-1">•</span>
                <span>{req.requirement}</span>
              </li>
            ))}
          </ul>
        </CollapsibleCard>
      )}

      {/* 联系方式 - 特殊处理 */}
      {data.application_methods && data.application_methods.length > 0 && (
        <div className="bg-white rounded-lg p-6 shadow-sm border border-gray-200">
          <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <Mail className="w-5 h-5 text-indigo-600" />
            联系方式
          </h3>
          {data.application_methods
            .filter((m) => m.is_primary)
            .map((m, idx) => (
              <div key={idx} className="bg-indigo-50 border-2 border-indigo-200 rounded-lg p-4 mb-3">
                <div className="flex items-center gap-2 mb-2">
                  <Mail className="w-5 h-5 text-indigo-600" />
                  <span className="font-semibold text-indigo-900">主要联系方式</span>
                </div>
                <p className="text-gray-800">{m.method}</p>
              </div>
            ))}

          {data.application_methods.filter((m) => !m.is_primary).length > 0 && (
            <div className="mt-4">
              <p className="text-sm text-gray-500 mb-2">其他联系方式：</p>
              {data.application_methods
                .filter((m) => !m.is_primary)
                .map((m, idx) => (
                  <p key={idx} className="text-sm text-gray-600 mb-1">
                    {m.method}
                  </p>
                ))}
            </div>
          )}
        </div>
      )}

      {/* 时间线 */}
      {data.timeline && data.timeline.length > 0 && (
        <CollapsibleCard title="申请时间" icon={<Calendar className="w-5 h-5" />}>
          <div className="space-y-3">
            {data.timeline.map((t, idx) => (
              <div key={idx} className="flex gap-3">
                <div className="flex-shrink-0 w-24 text-sm font-medium text-gray-600">{t.time}</div>
                <div className="flex-1 text-gray-700">{t.detail}</div>
              </div>
            ))}
          </div>
        </CollapsibleCard>
      )}

      {/* 信息来源 */}
      {data.evidence_posts && data.evidence_posts.length > 0 && (
        <CollapsibleCard title="信息来源" icon={<FileText className="w-5 h-5" />} defaultOpen={false}>
          <div className="space-y-2">
            {data.evidence_posts.map((post) => (
              <a
                key={post.note_id}
                href={post.url}
                target="_blank"
                rel="noopener noreferrer"
                className="block p-3 bg-gray-50 hover:bg-gray-100 rounded-lg transition-colors"
              >
                <p className="font-medium text-gray-900 mb-1">{post.title}</p>
                <div className="flex items-center gap-3 text-xs text-gray-500">
                  {post.published_at && <span>{formatDate(post.published_at)}</span>}
                  {post.time_sensitivity === "possibly_stale" && (
                    <span className="bg-amber-100 text-amber-700 px-2 py-0.5 rounded">可能已过期</span>
                  )}
                </div>
              </a>
            ))}
          </div>
        </CollapsibleCard>
      )}

      {/* 限制说明 */}
      {data.limitations && data.limitations.length > 0 && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
          <p className="text-xs text-gray-600">
            {data.limitations.map((lim, idx) => (
              <span key={idx}>
                {lim}
                {idx < data.limitations.length - 1 && " "}
              </span>
            ))}
          </p>
        </div>
      )}
    </div>
  );
}

function buildOverviewFacts(data: RecruitmentSummaryResponse): Array<{ label: string; value: string }> {
  const facts: Array<{ label: string; value: string }> = [];
  const targets = unique(
    data.targets
      ?.map((target) => target.type)
      .filter(Boolean)
      .slice(0, 5) ?? []
  );
  if (targets.length > 0) {
    facts.push({ label: "招生对象", value: targets.join("、") });
  }

  const directions = unique(
    data.research_directions
      ?.map((direction) => direction.direction)
      .filter(Boolean)
      .slice(0, 5) ?? []
  );
  if (directions.length > 0) {
    facts.push({ label: "研究方向", value: directions.join("、") });
  }

  const primaryMethod =
    data.application_methods?.find((method) => method.is_primary)?.method ||
    data.application_methods?.find((method) => method.method)?.method;
  if (primaryMethod) {
    facts.push({ label: "申请方式", value: primaryMethod });
  }

  const currentPosts = data.evidence_posts?.length ?? 0;
  if (currentPosts > 0) {
    facts.push({ label: "信息来源", value: `${currentPosts} 条小红书公开主贴` });
  }

  return facts.slice(0, 4);
}

function unique(items: string[]): string[] {
  return Array.from(new Set(items.map((item) => item.trim()).filter(Boolean)));
}

function RecruitmentStatusBadge({ status }: { status: string }) {
  const config = {
    found_current: { label: "正在招生", color: "bg-green-100 text-green-800 border-green-200" },
    found_stale: { label: "招生信息已过期", color: "bg-amber-100 text-amber-800 border-amber-200" },
    found_unclear: { label: "招生信息不明确", color: "bg-gray-100 text-gray-800 border-gray-200" },
    not_found: { label: "未找到招生信息", color: "bg-red-100 text-red-800 border-red-200" },
  };

  const { label, color } = config[status as keyof typeof config] || config.not_found;

  return (
    <div className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium border ${color}`}>
      {label}
    </div>
  );
}

interface CollapsibleCardProps {
  title: string;
  icon?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

function CollapsibleCard({ title, icon, defaultOpen = true, children }: CollapsibleCardProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between p-6 hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          {icon}
          <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
        </div>
        <svg
          className={`w-5 h-5 text-gray-500 transition-transform ${isOpen ? "rotate-180" : ""}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {isOpen && <div className="px-6 pb-6">{children}</div>}
    </div>
  );
}

function formatDate(dateString: string): string {
  try {
    const date = new Date(dateString);
    return date.toLocaleDateString("zh-CN", {
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  } catch {
    return dateString;
  }
}
