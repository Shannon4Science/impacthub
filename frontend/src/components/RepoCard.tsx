import { useState, useRef, useCallback, useEffect } from "react";
import type { GithubRepo } from "@/lib/api";
import { api } from "@/lib/api";
import { formatNumber } from "@/lib/utils";
import { Star, GitFork, ExternalLink, AlertCircle, Plus, Loader2, X, Pin, Trash2 } from "lucide-react";
import Pagination from "@/components/Pagination";

const PAGE_SIZE = 20;

interface Props {
  repos: GithubRepo[];
  configured?: boolean;
  userId?: string;
  onRepoAdded?: (repo: GithubRepo) => void;
  onRepoDeleted?: (repoId: number) => void;
}

interface GHSearchResult {
  full_name: string;
  description: string;
  stars: number;
  language: string;
}

const langColors: Record<string, string> = {
  Python: "bg-blue-500",
  TypeScript: "bg-blue-600",
  JavaScript: "bg-yellow-400",
  Rust: "bg-orange-600",
  Go: "bg-cyan-500",
  Java: "bg-red-500",
  "C++": "bg-pink-600",
  C: "bg-gray-600",
};

export default function RepoCard({ repos, configured = true, userId, onRepoAdded, onRepoDeleted }: Props) {
  const [page, setPage] = useState(1);
  const [showAdd, setShowAdd] = useState(false);
  const [repoName, setRepoName] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [deletingId, setDeletingId] = useState<number | null>(null);

  // Search autocomplete
  const [suggestions, setSuggestions] = useState<GHSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [showDrop, setShowDrop] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();
  const dropRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropRef.current && !dropRef.current.contains(e.target as Node)) setShowDrop(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleInputChange = useCallback((val: string) => {
    setRepoName(val);
    setError("");
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (val.trim().length < 2) {
      setSuggestions([]);
      setShowDrop(false);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        const res = await api.searchGithubRepos(val.trim());
        setSuggestions(res.results);
        setShowDrop(res.results.length > 0);
      } catch {
        setSuggestions([]);
      } finally {
        setSearching(false);
      }
    }, 350);
  }, []);

  const handleSelect = (r: GHSearchResult) => {
    setRepoName(r.full_name);
    setShowDrop(false);
  };

  const handleDelete = async (e: React.MouseEvent, repoId: number) => {
    e.preventDefault();
    e.stopPropagation();
    if (!userId || deletingId !== null) return;
    if (!confirm("确定删除该仓库？")) return;
    setDeletingId(repoId);
    try {
      await api.deleteRepo(userId, repoId);
      onRepoDeleted?.(repoId);
    } catch {
      // ignore
    } finally {
      setDeletingId(null);
    }
  };

  const handleAdd = async () => {
    if (!repoName.trim() || !userId) return;
    setAdding(true);
    setError("");
    try {
      const repo = await api.addRepo(userId, repoName.trim());
      onRepoAdded?.(repo as any);
      setRepoName("");
      setSuggestions([]);
      setShowAdd(false);
    } catch (err: any) {
      setError(err?.message || "添加失败");
    } finally {
      setAdding(false);
    }
  };

  if (!configured && repos.length === 0) {
    return (
      <div className="space-y-3">
        <div className="flex flex-col items-center rounded-2xl border border-dashed border-amber-200 bg-amber-50/50 py-10">
          <AlertCircle className="h-8 w-8 text-amber-400" />
          <p className="mt-2 text-sm font-medium text-amber-700">GitHub 账号未关联</p>
          <p className="mt-1 text-xs text-amber-500">可在设置中关联，或直接手动添加仓库</p>
        </div>
        {renderAddSection()}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        {repos.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE).map((r) => (
          <a
            key={r.id}
            href={r.url}
            target="_blank"
            rel="noreferrer"
            className="group relative flex flex-col justify-between rounded-xl border border-gray-100 bg-white p-5 shadow-sm hover-lift"
          >
            {userId && (
              <button
                onClick={(e) => handleDelete(e, r.id)}
                className="absolute right-2 top-2 rounded-full p-1 text-gray-300 opacity-0 transition hover:bg-red-50 hover:text-red-500 group-hover:opacity-100"
                title="删除仓库"
              >
                {deletingId === r.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              </button>
            )}
            <div>
              <div className="flex items-center gap-2">
                {r.is_pinned && (
                  <span className="flex items-center gap-0.5 rounded-full bg-indigo-50 px-1.5 py-0.5 text-[10px] font-medium text-indigo-500">
                    <Pin className="h-2.5 w-2.5" /> Pinned
                  </span>
                )}
                <span className="font-semibold text-gray-900 group-hover:text-indigo-600">
                  {r.repo_name.split("/").pop()}
                </span>
                {r.repo_name.split("/")[0] !== repos[0]?.repo_name.split("/")[0] && (
                  <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-400">
                    {r.repo_name.split("/")[0]}
                  </span>
                )}
                <ExternalLink className="h-3 w-3 text-gray-300 opacity-0 transition group-hover:opacity-100" />
              </div>
              {r.description && (
                <p className="mt-1.5 line-clamp-2 text-sm text-gray-500">{r.description}</p>
              )}
            </div>
            <div className="mt-3 flex items-center gap-4 text-xs text-gray-400">
              {r.language && (
                <span className="flex items-center gap-1">
                  <span className={`inline-block h-2.5 w-2.5 rounded-full ${langColors[r.language] || "bg-gray-400"}`} />
                  {r.language}
                </span>
              )}
              <span className="flex items-center gap-0.5">
                <Star className="h-3 w-3" />
                {formatNumber(r.stars)}
              </span>
              <span className="flex items-center gap-0.5">
                <GitFork className="h-3 w-3" />
                {formatNumber(r.forks)}
              </span>
            </div>
          </a>
        ))}
      </div>

      <Pagination
        current={page}
        total={Math.ceil(repos.length / PAGE_SIZE)}
        onChange={setPage}
      />

      {/* Add repo prompt */}
      {renderAddSection()}
    </div>
  );

  function renderAddSection() {
    if (!userId) return null;
    return (
      <div className="mt-2">
        {!showAdd ? (
          <button
            onClick={() => setShowAdd(true)}
            className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-dashed border-gray-200 py-3 text-sm text-gray-400 transition hover:border-indigo-300 hover:text-indigo-500"
          >
            <Plus className="h-4 w-4" />
            还有其他项目？点击添加
          </button>
        ) : (
          <div className="rounded-xl border border-indigo-200 bg-indigo-50/50 p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-gray-700">添加 GitHub 仓库</span>
              <button onClick={() => { setShowAdd(false); setError(""); setSuggestions([]); }} className="text-gray-400 hover:text-gray-600">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="relative flex gap-2" ref={dropRef}>
              <div className="relative flex-1">
                <input
                  type="text"
                  value={repoName}
                  onChange={(e) => handleInputChange(e.target.value)}
                  onFocus={() => suggestions.length > 0 && setShowDrop(true)}
                  placeholder="搜索仓库名，如 pytorch"
                  className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-400"
                  onKeyDown={(e) => e.key === "Enter" && !showDrop && handleAdd()}
                />
                {searching && (
                  <Loader2 className="absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 animate-spin text-gray-400" />
                )}
                {showDrop && suggestions.length > 0 && (
                  <div className="absolute bottom-full z-50 mb-1 max-h-64 w-full overflow-y-auto rounded-xl border border-gray-200 bg-white shadow-lg">
                    {suggestions.map((s) => (
                      <button
                        key={s.full_name}
                        type="button"
                        onClick={() => handleSelect(s)}
                        className="flex w-full items-start gap-2.5 border-b border-gray-50 px-3 py-2.5 text-left transition last:border-0 hover:bg-indigo-50/60"
                      >
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-medium text-gray-900 truncate">{s.full_name}</div>
                          {s.description && (
                            <div className="mt-0.5 text-xs text-gray-400 truncate">{s.description}</div>
                          )}
                        </div>
                        <div className="flex shrink-0 items-center gap-2 text-xs text-gray-400">
                          {s.language && (
                            <span className="flex items-center gap-1">
                              <span className={`inline-block h-2 w-2 rounded-full ${langColors[s.language] || "bg-gray-400"}`} />
                              {s.language}
                            </span>
                          )}
                          <span className="flex items-center gap-0.5">
                            <Star className="h-3 w-3" />
                            {formatNumber(s.stars)}
                          </span>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button
                onClick={handleAdd}
                disabled={adding || !repoName.trim()}
                className="shrink-0 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:opacity-50"
              >
                {adding ? <Loader2 className="h-4 w-4 animate-spin" /> : "添加"}
              </button>
            </div>
            {error && <p className="mt-1.5 text-xs text-red-500">{error}</p>}
          </div>
        )}
      </div>
    );
  }
}
