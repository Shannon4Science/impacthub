import { useState } from "react";
import { api, type UserProfile } from "@/lib/api";
import {
  Settings,
  MessageCircle,
  Save,
  Loader2,
  CheckCircle2,
  X,
  ExternalLink,
  GraduationCap,
  Github,
  Box,
  Globe,
} from "lucide-react";

interface Props {
  user: UserProfile;
  onClose: () => void;
  onUpdated: () => void;
}

export default function SettingsPanel({ user, onClose, onUpdated }: Props) {
  const [scholarId, setScholarId] = useState(user.scholar_id || "");
  const [githubUsername, setGithubUsername] = useState(user.github_username || "");
  const [hfUsername, setHfUsername] = useState(user.hf_username || "");
  const [homepage, setHomepage] = useState(user.homepage || "");
  const [feishuWebhook, setFeishuWebhook] = useState(user.feishu_webhook || "");
  const [twitterUsername, setTwitterUsername] = useState(user.twitter_username || "");
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      const update: Record<string, string> = {};
      if (scholarId !== (user.scholar_id || ""))
        update.scholar_id = scholarId;
      if (githubUsername !== (user.github_username || ""))
        update.github_username = githubUsername;
      if (hfUsername !== (user.hf_username || ""))
        update.hf_username = hfUsername;
      if (homepage !== (user.homepage || ""))
        update.homepage = homepage;
      if (feishuWebhook !== (user.feishu_webhook || ""))
        update.feishu_webhook = feishuWebhook;
      if (twitterUsername !== (user.twitter_username || ""))
        update.twitter_username = twitterUsername;

      if (Object.keys(update).length > 0) {
        await api.updateProfile(user.id, update);
      }
      setDone(true);
      setTimeout(() => {
        onUpdated();
      }, 1000);
    } catch {
      alert("保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative mx-4 w-full max-w-lg rounded-2xl bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
          <div className="flex items-center gap-2">
            <Settings className="h-5 w-5 text-gray-400" />
            <h2 className="text-lg font-semibold text-gray-900">设置</h2>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {done ? (
          <div className="flex flex-col items-center py-12">
            <CheckCircle2 className="h-12 w-12 text-emerald-500" />
            <p className="mt-3 font-medium text-gray-900">设置已保存</p>
          </div>
        ) : (
          <div className="max-h-[70vh] overflow-y-auto p-6">
            {/* --- Account Section --- */}
            <p className="mb-3 text-xs font-bold uppercase tracking-wider text-gray-400">
              账号关联
            </p>

            {/* Semantic Scholar */}
            <div className="mb-4">
              <div className="flex items-center gap-2">
                <GraduationCap className="h-4 w-4 text-indigo-500" />
                <label className="text-sm font-semibold text-gray-700">
                  Semantic Scholar ID
                </label>
              </div>
              <p className="mt-1 text-xs text-gray-400">
                在 Semantic Scholar 个人页 URL 末尾的数字，如 <code>47767550</code>。
              </p>
              <input
                type="text"
                value={scholarId}
                onChange={(e) => setScholarId(e.target.value)}
                placeholder="47767550"
                className="mt-2 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
              />
              {user.scholar_id && (
                <a
                  href={`https://www.semanticscholar.org/author/${user.scholar_id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-1 inline-flex items-center gap-1 text-xs text-indigo-500 hover:underline"
                >
                  查看当前关联主页
                  <ExternalLink className="h-3 w-3" />
                </a>
              )}
            </div>

            {/* GitHub */}
            <div className="mb-4">
              <div className="flex items-center gap-2">
                <Github className="h-4 w-4 text-gray-700" />
                <label className="text-sm font-semibold text-gray-700">
                  GitHub 用户名
                </label>
              </div>
              <input
                type="text"
                value={githubUsername}
                onChange={(e) => setGithubUsername(e.target.value)}
                placeholder="karpathy"
                className="mt-2 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none transition focus:border-gray-400 focus:ring-2 focus:ring-gray-100"
              />
              <p className="mt-1 text-xs text-gray-400">关联后自动拉取仓库数据（含 pinned 项目）。</p>
            </div>

            {/* HuggingFace */}
            <div className="mb-4">
              <div className="flex items-center gap-2">
                <Box className="h-4 w-4 text-yellow-500" />
                <label className="text-sm font-semibold text-gray-700">
                  HuggingFace 用户名
                </label>
              </div>
              <input
                type="text"
                value={hfUsername}
                onChange={(e) => setHfUsername(e.target.value)}
                placeholder="meta-llama"
                className="mt-2 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none transition focus:border-yellow-400 focus:ring-2 focus:ring-yellow-100"
              />
            </div>

            {/* Homepage */}
            <div className="mb-6">
              <div className="flex items-center gap-2">
                <Globe className="h-4 w-4 text-emerald-500" />
                <label className="text-sm font-semibold text-gray-700">
                  个人主页
                </label>
              </div>
              <p className="mt-1 text-xs text-gray-400">
                你的个人网站或学术主页，将作为额外信息源展示在档案中。
              </p>
              <input
                type="url"
                value={homepage}
                onChange={(e) => setHomepage(e.target.value)}
                placeholder="https://karpathy.ai"
                className="mt-2 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
              />
            </div>

            <hr className="mb-5 border-gray-100" />

            <p className="mb-3 text-xs font-bold uppercase tracking-wider text-gray-400">
              通知与社交
            </p>

            {/* Feishu Webhook */}
            <div className="mb-6">
              <div className="flex items-center gap-2">
                <MessageCircle className="h-4 w-4 text-blue-500" />
                <label className="text-sm font-semibold text-gray-700">
                  飞书 Webhook 通知
                </label>
              </div>
              <p className="mt-1 text-xs text-gray-400">
                配置后，当达成里程碑（Star 破千、引用破百等）时会自动推送庆祝卡片到飞书群。
              </p>
              <input
                type="url"
                value={feishuWebhook}
                onChange={(e) => setFeishuWebhook(e.target.value)}
                placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..."
                className="mt-2 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
              />
              <a
                href="https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot"
                target="_blank"
                rel="noreferrer"
                className="mt-1 inline-flex items-center gap-1 text-xs text-blue-500 hover:underline"
              >
                如何创建飞书群机器人
                <ExternalLink className="h-3 w-3" />
              </a>
            </div>

            {/* Twitter */}
            <div className="mb-6">
              <div className="flex items-center gap-2">
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
                </svg>
                <label className="text-sm font-semibold text-gray-700">
                  Twitter / X 用户名
                </label>
              </div>
              <p className="mt-1 text-xs text-gray-400">
                关联后可追踪社交媒体影响力数据。
              </p>
              <div className="mt-2 flex items-center gap-1">
                <span className="text-sm text-gray-400">@</span>
                <input
                  type="text"
                  value={twitterUsername}
                  onChange={(e) => setTwitterUsername(e.target.value)}
                  placeholder="karpathy"
                  className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none transition focus:border-gray-400 focus:ring-2 focus:ring-gray-100"
                />
              </div>
            </div>

            <button
              onClick={handleSave}
              disabled={saving}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:opacity-50"
            >
              {saving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              保存设置
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
