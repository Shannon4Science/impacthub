import { useState } from "react";
import type { TimelineEntry } from "@/lib/api";
import { BookOpen, GitBranch, Box, Database, ExternalLink } from "lucide-react";
import Pagination from "@/components/Pagination";

const PAGE_SIZE = 20;

interface Props {
  entries: TimelineEntry[];
}

const typeConfig: Record<string, { icon: typeof BookOpen; color: string; bg: string }> = {
  paper: { icon: BookOpen, color: "text-violet-600", bg: "bg-violet-100" },
  repo: { icon: GitBranch, color: "text-gray-700", bg: "bg-gray-100" },
  hf_model: { icon: Box, color: "text-amber-600", bg: "bg-amber-100" },
  hf_dataset: { icon: Database, color: "text-emerald-600", bg: "bg-emerald-100" },
};

export default function Timeline({ entries }: Props) {
  const [page, setPage] = useState(1);

  if (!entries.length) {
    return <p className="py-12 text-center text-gray-400">暂无时间轴数据。</p>;
  }

  const pageEntries = entries.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <div className="space-y-0">
      <div className="relative">
        <div className="absolute left-5 top-0 bottom-0 w-px bg-gray-200" />
        {pageEntries.map((entry, idx) => {
          const cfg = typeConfig[entry.type] || typeConfig.paper;
          const Icon = cfg.icon;
          return (
            <div key={idx} className="relative flex gap-4 py-3 pl-0">
              <div className={`relative z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${cfg.bg} ${cfg.color}`}>
                <Icon className="h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1 pt-1">
                <a
                  href={entry.url}
                  target="_blank"
                  rel="noreferrer"
                  className="group flex items-center gap-1 font-medium text-gray-900 hover:text-indigo-600"
                >
                  <span className="truncate">{entry.title}</span>
                  <ExternalLink className="h-3 w-3 shrink-0 opacity-0 transition group-hover:opacity-50" />
                </a>
                <p className="text-xs text-gray-400">
                  {entry.date} &middot; {entry.detail}
                </p>
              </div>
            </div>
          );
        })}
      </div>

      <Pagination
        current={page}
        total={Math.ceil(entries.length / PAGE_SIZE)}
        onChange={setPage}
      />
    </div>
  );
}
