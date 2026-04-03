import { useState } from "react";
import { api } from "@/lib/api";
import { X, Globe, Loader2, CheckCircle2 } from "lucide-react";

interface Props {
  userId: string;
  currentHomepage?: string;
  onClose: () => void;
  onUpdated: () => void;
}

export default function LinkAccountModal({ userId, currentHomepage, onClose, onUpdated }: Props) {
  const [homepage, setHomepage] = useState(currentHomepage || "");
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);

  const handleSave = async () => {
    if (!homepage.trim()) { onClose(); return; }
    setSaving(true);
    try {
      await api.updateProfile(userId, { homepage: homepage.trim() });
      setDone(true);
      setTimeout(() => {
        onUpdated();
        onClose();
      }, 1200);
    } catch {
      alert("保存失败，请重试");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="relative mx-4 w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">添加个人主页</h2>
          <button onClick={onClose} className="rounded-lg p-1 text-gray-400 hover:bg-gray-100">
            <X className="h-5 w-5" />
          </button>
        </div>

        {done ? (
          <div className="flex flex-col items-center py-8">
            <CheckCircle2 className="h-12 w-12 text-emerald-500" />
            <p className="mt-3 font-medium text-gray-900">已保存！</p>
          </div>
        ) : (
          <>
            <div className="flex items-start gap-3">
              <div className="mt-2 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-100 text-emerald-600">
                <Globe className="h-4 w-4" />
              </div>
              <div className="flex-1">
                <label className="mb-1 block text-sm font-medium text-gray-700">
                  个人主页链接
                </label>
                <input
                  type="url"
                  value={homepage}
                  onChange={(e) => setHomepage(e.target.value)}
                  placeholder="https://karpathy.ai"
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
                  autoFocus
                />
                <p className="mt-1 text-xs text-gray-400">
                  填写你的个人网站或学术主页，将展示在档案中
                </p>
              </div>
            </div>

            <button
              onClick={handleSave}
              disabled={saving}
              className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : "保存"}
            </button>

            <p className="mt-3 text-center text-xs text-gray-400">
              GitHub、HuggingFace 等平台可在设置中关联
            </p>
          </>
        )}
      </div>
    </div>
  );
}
