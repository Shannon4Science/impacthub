import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, Mail, MapPin, UserCircle2 } from "lucide-react";

import { RecruitmentSummary } from "@/components/advisor/RecruitmentSummary";
import { api } from "@/lib/api";

const LINK_KIND_LABELS: Record<string, string> = {
  personal_homepage: "个人主页",
  lab: "实验室",
  google_scholar: "Google Scholar",
  semantic_scholar: "Semantic Scholar",
  dblp: "DBLP",
  orcid: "ORCID",
  github: "GitHub",
  huggingface: "Hugging Face",
  cv: "CV",
  publications: "论文列表",
  recruitment: "招生信息",
  blog: "博客",
  social: "社交主页",
  other_academic: "学术链接",
};

export default function AdvisorDetailPage() {
  const { advisorId } = useParams<{ advisorId: string }>();
  const id = Number(advisorId);
  const validId = Boolean(advisorId) && !Number.isNaN(id);

  const {
    data: advisor,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["advisor", id],
    queryFn: () => api.getAdvisor(id),
    enabled: validId,
  });

  if (!validId) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-12">
        <div className="text-center text-gray-600">无效的导师 ID</div>
      </div>
    );
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-6">
      <Link
        to="/advisor"
        className="mb-6 inline-flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900"
      >
        <ArrowLeft className="h-4 w-4" />
        返回导师库
      </Link>

      {isLoading && (
        <div className="mb-6 rounded-lg border border-gray-200 bg-white p-6 text-sm text-gray-500">
          正在加载导师信息…
        </div>
      )}

      {error && (
        <div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-700">
          导师信息加载失败
        </div>
      )}

      {advisor && (
        <section className="mb-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          <div className="flex flex-col gap-4 sm:flex-row">
            <div className="shrink-0">
              {advisor.photo_url ? (
                <img
                  src={advisor.photo_url}
                  alt={advisor.name}
                  className="h-20 w-20 rounded-full object-cover ring-1 ring-gray-200"
                />
              ) : (
                <div className="flex h-20 w-20 items-center justify-center rounded-full bg-gradient-to-br from-indigo-100 to-purple-100 text-indigo-500">
                  <UserCircle2 className="h-10 w-10" />
                </div>
              )}
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-2xl font-bold text-gray-900">{advisor.name}</h1>
                {advisor.title && (
                  <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-700">
                    {advisor.title}
                  </span>
                )}
                {advisor.is_doctoral_supervisor && (
                  <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">
                    博导
                  </span>
                )}
                {advisor.is_master_supervisor && (
                  <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">
                    硕导
                  </span>
                )}
              </div>

              <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-gray-600">
                <span className="inline-flex items-center gap-1">
                  <MapPin className="h-4 w-4" />
                  {advisor.school_name} · {advisor.college_name}
                </span>
                {advisor.email && (
                  <a href={`mailto:${advisor.email}`} className="inline-flex items-center gap-1 hover:text-indigo-600">
                    <Mail className="h-4 w-4" />
                    {advisor.email}
                  </a>
                )}
                {advisor.homepage_url && (
                  <a
                    href={advisor.homepage_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 hover:text-indigo-600"
                  >
                    <ExternalLink className="h-4 w-4" />
                    个人主页
                  </a>
                )}
              </div>

              {advisor.research_areas && advisor.research_areas.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {advisor.research_areas.map((area) => (
                    <span key={area} className="rounded bg-indigo-50 px-2 py-1 text-xs text-indigo-700">
                      {area}
                    </span>
                  ))}
                </div>
              )}

              {advisor.bio && (
                <div className="mt-4 whitespace-pre-line text-sm leading-6 text-gray-700">{advisor.bio}</div>
              )}

              {advisor.education && advisor.education.length > 0 && (
                <div className="mt-5">
                  <h2 className="text-sm font-semibold text-gray-900">教育背景</h2>
                  <div className="mt-2 space-y-1 text-sm text-gray-700">
                    {advisor.education.map((item, index) => (
                      <div key={`${item.institution}-${item.degree}-${index}`}>
                        {item.year ? `${item.year} · ` : ""}
                        {[item.institution, item.degree, item.advisor ? `导师：${item.advisor}` : ""]
                          .filter(Boolean)
                          .join(" · ")}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {advisor.honors && advisor.honors.length > 0 && (
                <div className="mt-5">
                  <h2 className="text-sm font-semibold text-gray-900">荣誉与人才项目</h2>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {advisor.honors.map((honor) => (
                      <span key={honor} className="rounded bg-amber-50 px-2 py-1 text-xs text-amber-700">
                        {honor}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {advisor.recruiting_intent && (
                <div className="mt-5">
                  <h2 className="text-sm font-semibold text-gray-900">招生信息</h2>
                  <p className="mt-2 whitespace-pre-line text-sm leading-6 text-gray-700">
                    {advisor.recruiting_intent}
                  </p>
                </div>
              )}

              {advisor.external_links && advisor.external_links.length > 0 && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {advisor.external_links.map((link) => (
                    <a
                      key={`${link.kind}-${link.url}`}
                      href={link.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      title={link.reason || link.url}
                      className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2 py-1 text-xs text-gray-700 hover:border-indigo-200 hover:text-indigo-700"
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                      {link.label || LINK_KIND_LABELS[link.kind] || "学术链接"}
                    </a>
                  ))}
                </div>
              )}
            </div>
          </div>
        </section>
      )}

      <RecruitmentSummary advisorId={id} />
    </main>
  );
}
