import { useRef, useState } from "react";
import { toPng } from "html-to-image";
import type { UserProfile, Stats, BuzzSnapshot, CitationOverview, AISummary } from "@/lib/api";
import ShareCard from "./ShareCard";
import { X, Download, Copy, Check, Loader2 } from "lucide-react";

interface Props {
  user: UserProfile;
  stats: Stats;
  buzz?: BuzzSnapshot | null;
  citationOverview?: CitationOverview | null;
  aiSummary?: AISummary | null;
  onClose: () => void;
}

export default function ShareModal({ user, stats, buzz, citationOverview, aiSummary, onClose }: Props) {
  const cardRef = useRef<HTMLDivElement>(null);
  const [exporting, setExporting] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  const doExport = async (): Promise<string | null> => {
    if (!cardRef.current) return null;
    setError("");
    try {
      return await toPng(cardRef.current, {
        pixelRatio: 3,
        cacheBust: true,
        skipAutoScale: true,
        filter: (node: HTMLElement) => {
          // Skip nodes that might cause issues
          return !node.classList?.contains("sr-only");
        },
      });
    } catch (err) {
      console.error("Export failed:", err);
      setError("生成图片失败，请重试");
      return null;
    }
  };

  const handleDownload = async () => {
    setExporting(true);
    try {
      const dataUrl = await doExport();
      if (!dataUrl) return;
      const link = document.createElement("a");
      const name = user.name || "ImpactHub";
      link.download = `${name}-影响力卡片.png`;
      link.href = dataUrl;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch (err) {
      console.error("Download failed:", err);
      setError("导出失败，请重试");
    } finally {
      setExporting(false);
    }
  };

  const handleCopyToClipboard = async () => {
    setExporting(true);
    try {
      const dataUrl = await doExport();
      if (!dataUrl) return;
      const response = await fetch(dataUrl);
      const blob = await response.blob();
      try {
        await navigator.clipboard.write([
          new ClipboardItem({ "image/png": blob }),
        ]);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      } catch {
        handleDownload();
      }
    } catch {
      handleDownload();
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      <div className="relative mx-4 flex max-h-[90vh] flex-col rounded-2xl bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">
              导出分享卡片
            </h2>
            <p className="text-xs text-gray-400">
              生成精美卡片，分享你的科研影响力
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-gray-400 transition hover:bg-gray-100 hover:text-gray-600"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="overflow-auto p-6">
          <div className="flex justify-center">
            <ShareCard ref={cardRef} user={user} stats={stats} buzz={buzz} citationOverview={citationOverview} aiSummary={aiSummary} />
          </div>
        </div>

        {error && (
          <div className="mx-6 mb-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">
            {error}
          </div>
        )}

        <div className="flex items-center gap-3 border-t border-gray-100 px-6 py-4">
          <button
            onClick={handleDownload}
            disabled={exporting}
            className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-indigo-600 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:opacity-50"
          >
            {exporting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            保存为图片
          </button>
          <button
            onClick={handleCopyToClipboard}
            disabled={exporting}
            className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-gray-200 bg-white py-2.5 text-sm font-semibold text-gray-700 transition hover:bg-gray-50 disabled:opacity-50"
          >
            {copied ? (
              <>
                <Check className="h-4 w-4 text-green-500" />
                已复制
              </>
            ) : (
              <>
                <Copy className="h-4 w-4" />
                复制到剪贴板
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
