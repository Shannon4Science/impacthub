import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { api, type UserProfile } from "@/lib/api";
import { formatNumber } from "@/lib/utils";
import {
  FileText,
  Star,
  Download,
  BookOpen,
  Github,
  Box,
  ArrowRight,
  Loader2,
  Quote,
  GitFork,
} from "lucide-react";

type UserWithStats = UserProfile & {
  paper_count: number;
  total_citations: number;
  repo_count: number;
  total_stars: number;
  hf_count: number;
  total_downloads: number;
};

export default function UsersPage() {
  const navigate = useNavigate();
  const [users, setUsers] = useState<UserWithStats[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .listUsers()
      .then((data) => setUsers(data))
      .catch(() => {})
      .finally(() => setLoading(false));
    api.trackVisit("/users").catch(() => {});
  }, []);

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-indigo-500" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="mb-8"
      >
        <h1 className="text-2xl font-bold text-gray-900">
          用户档案
        </h1>
        <p className="mt-1 text-sm text-gray-400">
          按加入时间排列，共 {users.length} 位研究者
        </p>
      </motion.div>

      <div className="space-y-3">
        {users.map((u, idx) => (
          <motion.button
            key={u.id}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: idx * 0.04 }}
            onClick={() => navigate(`/profile/${u.scholar_id || u.id}`)}
            className="group flex w-full items-center gap-4 rounded-xl border border-gray-100 bg-white px-5 py-4 text-left shadow-sm transition hover:border-indigo-200 hover:shadow-md"
          >
            {/* Number */}
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gray-100 text-xs font-bold text-gray-400 group-hover:bg-indigo-100 group-hover:text-indigo-600">
              {idx + 1}
            </span>

            {/* Avatar */}
            {u.avatar_url ? (
              <img
                src={u.avatar_url}
                className="h-11 w-11 shrink-0 rounded-full"
                alt=""
              />
            ) : (
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-sm font-bold text-indigo-600">
                {(u.name || "?")[0]}
              </div>
            )}

            {/* Info */}
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate font-semibold text-gray-900 group-hover:text-indigo-600">
                  {u.name || u.github_username || `User #${u.id}`}
                </span>
                {/* Platform badges */}
                <div className="flex items-center gap-1.5">
                  {u.scholar_id && (
                    <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] font-medium text-indigo-500">
                      <BookOpen className="mr-0.5 inline h-2.5 w-2.5" />{u.scholar_id}
                    </span>
                  )}
                  {u.github_username && (
                    <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-500">
                      <Github className="mr-0.5 inline h-2.5 w-2.5" />{u.github_username}
                    </span>
                  )}
                  {u.hf_username && (
                    <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-600">
                      <Box className="mr-0.5 inline h-2.5 w-2.5" />{u.hf_username}
                    </span>
                  )}
                </div>
              </div>

              {/* Stats row */}
              <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-0.5 text-xs text-gray-400">
                {u.paper_count > 0 && (
                  <span className="flex items-center gap-1">
                    <FileText className="h-3 w-3" />
                    {u.paper_count} 论文
                  </span>
                )}
                {u.total_citations > 0 && (
                  <span className="flex items-center gap-1">
                    <Quote className="h-3 w-3" />
                    {formatNumber(u.total_citations)} 引用
                  </span>
                )}
                {u.repo_count > 0 && (
                  <span className="flex items-center gap-1">
                    <GitFork className="h-3 w-3" />
                    {u.repo_count} 仓库
                  </span>
                )}
                {u.total_stars > 0 && (
                  <span className="flex items-center gap-1">
                    <Star className="h-3 w-3" />
                    {formatNumber(u.total_stars)} Stars
                  </span>
                )}
                {u.total_downloads > 0 && (
                  <span className="flex items-center gap-1">
                    <Download className="h-3 w-3" />
                    {formatNumber(u.total_downloads)} 下载
                  </span>
                )}
                {u.created_at && (
                  <span className="text-gray-300">
                    {new Date(u.created_at).toLocaleDateString("zh-CN")}
                  </span>
                )}
              </div>
            </div>

            <ArrowRight className="h-4 w-4 shrink-0 text-gray-300 transition group-hover:text-indigo-500" />
          </motion.button>
        ))}
      </div>

      {users.length === 0 && (
        <div className="rounded-xl border border-dashed border-gray-200 py-16 text-center">
          <p className="text-sm text-gray-400">暂无用户</p>
        </div>
      )}
    </div>
  );
}
