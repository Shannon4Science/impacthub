import { useState } from "react";
import type { Paper } from "@/lib/api";
import { formatNumber } from "@/lib/utils";
import { abbreviateVenue } from "@/lib/venues";
import { ExternalLink, Quote, AlertCircle, SlidersHorizontal } from "lucide-react";
import Pagination from "@/components/Pagination";

const PAGE_SIZE = 20;

const CCF_COLORS: Record<string, string> = {
  A: "bg-red-500 text-white",
  B: "bg-orange-400 text-white",
  C: "bg-sky-400 text-white",
};

interface Props {
  papers: Paper[];
  configured?: boolean;
}

export default function PublicationList({ papers, configured = true }: Props) {
  const [ccfFilter, setCcfFilter] = useState<string>("");
  const [showFilters, setShowFilters] = useState(false);
  const [yearFrom, setYearFrom] = useState("");
  const [minCitations, setMinCitations] = useState("");
  const [page, setPage] = useState(1);

  if (!configured) {
    return (
      <div className="flex flex-col items-center rounded-2xl border border-dashed border-amber-200 bg-amber-50/50 py-14">
        <AlertCircle className="h-10 w-10 text-amber-400" />
        <p className="mt-3 text-sm font-medium text-amber-700">Semantic Scholar 账号未关联</p>
        <p className="mt-1 text-xs text-amber-500">请在创建档案时填写 Scholar ID 以展示论文数据</p>
      </div>
    );
  }

  if (!papers.length) {
    return <p className="py-12 text-center text-gray-400">论文数据正在后台加载中...</p>;
  }

  const ccfA = papers.filter((p) => p.ccf_rank === "A").length;
  const ccfB = papers.filter((p) => p.ccf_rank === "B").length;
  const ccfC = papers.filter((p) => p.ccf_rank === "C").length;

  let filtered = papers;
  if (ccfFilter) {
    filtered = filtered.filter((p) => p.ccf_rank === ccfFilter);
  }
  if (yearFrom) {
    filtered = filtered.filter((p) => p.year >= parseInt(yearFrom));
  }
  if (minCitations) {
    filtered = filtered.filter((p) => p.citation_count >= parseInt(minCitations));
  }

  return (
    <div className="space-y-3">
      {/* Stats & Filter Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-gray-500">共 <strong className="text-gray-900">{papers.length}</strong> 篇</span>
          {ccfA > 0 && (
            <button
              onClick={() => setCcfFilter(ccfFilter === "A" ? "" : "A")}
              className={`rounded-full px-2 py-0.5 font-bold transition ${
                ccfFilter === "A" ? "bg-red-500 text-white" : "bg-red-50 text-red-600 hover:bg-red-100"
              }`}
            >
              CCF-A: {ccfA}
            </button>
          )}
          {ccfB > 0 && (
            <button
              onClick={() => setCcfFilter(ccfFilter === "B" ? "" : "B")}
              className={`rounded-full px-2 py-0.5 font-bold transition ${
                ccfFilter === "B" ? "bg-orange-400 text-white" : "bg-orange-50 text-orange-600 hover:bg-orange-100"
              }`}
            >
              CCF-B: {ccfB}
            </button>
          )}
          {ccfC > 0 && (
            <button
              onClick={() => setCcfFilter(ccfFilter === "C" ? "" : "C")}
              className={`rounded-full px-2 py-0.5 font-bold transition ${
                ccfFilter === "C" ? "bg-sky-400 text-white" : "bg-sky-50 text-sky-600 hover:bg-sky-100"
              }`}
            >
              CCF-C: {ccfC}
            </button>
          )}
          {ccfFilter && (
            <button
              onClick={() => setCcfFilter("")}
              className="rounded-full bg-gray-100 px-2 py-0.5 text-gray-500 hover:bg-gray-200"
            >
              清除
            </button>
          )}
        </div>
        <button
          onClick={() => setShowFilters(!showFilters)}
          className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600"
        >
          <SlidersHorizontal className="h-3 w-3" />
          高级筛选
        </button>
      </div>

      {showFilters && (
        <div className="flex flex-wrap gap-3 rounded-xl border border-gray-100 bg-gray-50 px-4 py-3">
          <div>
            <label className="block text-[10px] font-medium text-gray-500">起始年份</label>
            <input
              type="number"
              value={yearFrom}
              onChange={(e) => setYearFrom(e.target.value)}
              placeholder="如 2020"
              className="mt-0.5 w-24 rounded border border-gray-200 px-2 py-1 text-xs outline-none focus:border-indigo-300"
            />
          </div>
          <div>
            <label className="block text-[10px] font-medium text-gray-500">最低引用</label>
            <input
              type="number"
              value={minCitations}
              onChange={(e) => setMinCitations(e.target.value)}
              placeholder="如 10"
              className="mt-0.5 w-24 rounded border border-gray-200 px-2 py-1 text-xs outline-none focus:border-indigo-300"
            />
          </div>
          <div className="flex items-end">
            <a
              href={`/api/report/${papers[0]?.id ? "" : ""}${window.location.pathname.split("/").pop()}/papers?format=markdown${ccfFilter ? `&ccf_rank=${ccfFilter}` : ""}${yearFrom ? `&year_from=${yearFrom}` : ""}${minCitations ? `&min_citations=${minCitations}` : ""}`}
              target="_blank"
              className="rounded-lg bg-indigo-600 px-3 py-1 text-xs font-semibold text-white hover:bg-indigo-700"
            >
              导出 Markdown
            </a>
          </div>
        </div>
      )}

      {/* Filtered count */}
      {(ccfFilter || yearFrom || minCitations) && (
        <p className="text-xs text-gray-400">
          筛选结果: {filtered.length} 篇 / {papers.length} 篇
        </p>
      )}

      {/* Paper List */}
      {filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE).map((p) => {
        const venueShort = abbreviateVenue(p.venue, p.year > 0 ? p.year : undefined);

        return (
          <div
            key={p.id}
            className="group rounded-xl border border-gray-100 bg-white px-5 py-4 shadow-sm hover-lift"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <a
                  href={p.url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium text-gray-900 transition hover:text-indigo-600"
                >
                  {p.title}
                  <ExternalLink className="ml-1 inline h-3 w-3 opacity-0 transition group-hover:opacity-50" />
                </a>
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-gray-400">
                  {p.ccf_rank && (
                    <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold leading-none ${CCF_COLORS[p.ccf_rank] || "bg-gray-200 text-gray-600"}`}>
                      CCF-{p.ccf_rank}
                    </span>
                  )}
                  {venueShort && (
                    <span className="rounded-full bg-violet-50 px-2 py-0.5 font-medium text-violet-600">
                      {venueShort}
                    </span>
                  )}
                  {!venueShort && p.year > 0 && <span>{p.year}</span>}
                  {p.authors.length > 0 && (
                    <span className="truncate text-gray-400">
                      {p.authors.slice(0, 3).join(", ")}
                      {p.authors.length > 3 && ` +${p.authors.length - 3}`}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1.5 rounded-lg bg-indigo-50 px-3 py-1.5 text-sm font-bold text-indigo-600">
                <Quote className="h-3 w-3" />
                {formatNumber(p.citation_count)}
              </div>
            </div>
          </div>
        );
      })}

      <Pagination
        current={page}
        total={Math.ceil(filtered.length / PAGE_SIZE)}
        onChange={setPage}
      />
    </div>
  );
}
