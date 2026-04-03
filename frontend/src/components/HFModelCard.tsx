import { useState, useRef, useCallback, useEffect } from "react";
import type { HFItem } from "@/lib/api";
import { api } from "@/lib/api";
import { formatNumber } from "@/lib/utils";
import { Download, Heart, ExternalLink, Box, Database, AlertCircle, Plus, Loader2, X, Trash2 } from "lucide-react";
import Pagination from "@/components/Pagination";

const PAGE_SIZE = 20;

interface Props {
  items: HFItem[];
  configured?: boolean;
  userId?: string;
  onItemAdded?: (item: HFItem) => void;
  onItemDeleted?: (itemId: number) => void;
}

interface HFSearchResult {
  id: string;
  downloads: number;
  likes: number;
}

export default function HFModelCard({ items, configured = true, userId, onItemAdded, onItemDeleted }: Props) {
  const [page, setPage] = useState(1);
  const [showAdd, setShowAdd] = useState(false);
  const [itemId, setItemId] = useState("");
  const [itemType, setItemType] = useState<"model" | "dataset">("model");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [deletingId, setDeletingId] = useState<number | null>(null);

  // Search autocomplete
  const [suggestions, setSuggestions] = useState<HFSearchResult[]>([]);
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
    setItemId(val);
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
        const res = await api.searchHFItems(val.trim(), itemType);
        setSuggestions(res.results);
        setShowDrop(res.results.length > 0);
      } catch {
        setSuggestions([]);
      } finally {
        setSearching(false);
      }
    }, 350);
  }, [itemType]);

  const handleSelect = (r: HFSearchResult) => {
    setItemId(r.id);
    setShowDrop(false);
  };

  const handleDelete = async (e: React.MouseEvent, id: number) => {
    e.preventDefault();
    e.stopPropagation();
    if (!userId || deletingId !== null) return;
    if (!confirm("确定删除该项目？")) return;
    setDeletingId(id);
    try {
      await api.deleteHFItem(userId, id);
      onItemDeleted?.(id);
    } catch {
      // ignore
    } finally {
      setDeletingId(null);
    }
  };

  const handleAdd = async () => {
    if (!itemId.trim() || !userId) return;
    setAdding(true);
    setError("");
    try {
      const item = await api.addHFItem(userId, itemId.trim(), itemType);
      onItemAdded?.(item as any);
      setItemId("");
      setSuggestions([]);
      setShowAdd(false);
    } catch (err: any) {
      setError(err?.message || "添加失败");
    } finally {
      setAdding(false);
    }
  };

  // Re-search when type changes
  const handleTypeChange = (t: "model" | "dataset") => {
    setItemType(t);
    setSuggestions([]);
    setShowDrop(false);
    if (itemId.trim().length >= 2) {
      // Trigger new search with new type
      setTimeout(() => handleInputChange(itemId), 50);
    }
  };

  if (!configured && items.length === 0) {
    return (
      <div className="space-y-3">
        <div className="flex flex-col items-center rounded-2xl border border-dashed border-amber-200 bg-amber-50/50 py-10">
          <AlertCircle className="h-8 w-8 text-amber-400" />
          <p className="mt-2 text-sm font-medium text-amber-700">Hugging Face 账号未关联</p>
          <p className="mt-1 text-xs text-amber-500">可在设置中关联，或直接手动添加模型/数据集</p>
        </div>
        {renderAddSection()}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {items.length === 0 && !userId ? (
        <p className="py-12 text-center text-gray-400">暂无模型或数据集。</p>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            {items.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE).map((item) => (
              <a
                key={item.id}
                href={item.url}
                target="_blank"
                rel="noreferrer"
                className="group relative rounded-xl border border-gray-100 bg-white p-5 shadow-sm hover-lift"
              >
                {userId && (
                  <button
                    onClick={(e) => handleDelete(e, item.id)}
                    className="absolute right-2 top-2 rounded-full p-1 text-gray-300 opacity-0 transition hover:bg-red-50 hover:text-red-500 group-hover:opacity-100"
                    title="删除项目"
                  >
                    {deletingId === item.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                  </button>
                )}
                <div className="flex items-center gap-2">
                  {item.item_type === "model" ? (
                    <Box className="h-4 w-4 text-amber-500" />
                  ) : (
                    <Database className="h-4 w-4 text-emerald-500" />
                  )}
                  <span className="font-semibold text-gray-900 group-hover:text-amber-600">
                    {item.name}
                  </span>
                  <ExternalLink className="h-3 w-3 text-gray-300 opacity-0 transition group-hover:opacity-100" />
                </div>
                <div className="mt-1 text-xs text-gray-400">
                  {item.item_type === "model" ? "模型" : "数据集"}
                </div>
                <div className="mt-3 flex items-center gap-4 text-xs text-gray-400">
                  <span className="flex items-center gap-0.5">
                    <Download className="h-3 w-3" />
                    {formatNumber(item.downloads)}
                  </span>
                  <span className="flex items-center gap-0.5">
                    <Heart className="h-3 w-3" />
                    {formatNumber(item.likes)}
                  </span>
                </div>
              </a>
            ))}
          </div>

          <Pagination
            current={page}
            total={Math.ceil(items.length / PAGE_SIZE)}
            onChange={setPage}
          />
        </>
      )}

      {/* Add HF item prompt */}
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
            className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-dashed border-gray-200 py-3 text-sm text-gray-400 transition hover:border-amber-300 hover:text-amber-500"
          >
            <Plus className="h-4 w-4" />
            还有其他项目？点击添加
          </button>
        ) : (
          <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-gray-700">添加 HuggingFace 项目</span>
              <button onClick={() => { setShowAdd(false); setError(""); setSuggestions([]); }} className="text-gray-400 hover:text-gray-600">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="flex gap-2 mb-2">
              <button
                type="button"
                onClick={() => handleTypeChange("model")}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                  itemType === "model"
                    ? "bg-amber-500 text-white"
                    : "bg-white text-gray-500 border border-gray-200 hover:border-amber-300"
                }`}
              >
                <Box className="mr-1 inline h-3 w-3" /> 模型
              </button>
              <button
                type="button"
                onClick={() => handleTypeChange("dataset")}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                  itemType === "dataset"
                    ? "bg-emerald-500 text-white"
                    : "bg-white text-gray-500 border border-gray-200 hover:border-emerald-300"
                }`}
              >
                <Database className="mr-1 inline h-3 w-3" /> 数据集
              </button>
            </div>
            <div className="relative flex gap-2" ref={dropRef}>
              <div className="relative flex-1">
                <input
                  type="text"
                  value={itemId}
                  onChange={(e) => handleInputChange(e.target.value)}
                  onFocus={() => suggestions.length > 0 && setShowDrop(true)}
                  placeholder="搜索名称，如 llama"
                  className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:border-amber-400"
                  onKeyDown={(e) => e.key === "Enter" && !showDrop && handleAdd()}
                />
                {searching && (
                  <Loader2 className="absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 animate-spin text-gray-400" />
                )}
                {showDrop && suggestions.length > 0 && (
                  <div className="absolute bottom-full z-50 mb-1 max-h-64 w-full overflow-y-auto rounded-xl border border-gray-200 bg-white shadow-lg">
                    {suggestions.map((s) => (
                      <button
                        key={s.id}
                        type="button"
                        onClick={() => handleSelect(s)}
                        className="flex w-full items-center justify-between border-b border-gray-50 px-3 py-2.5 text-left transition last:border-0 hover:bg-amber-50/60"
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          {itemType === "model" ? (
                            <Box className="h-3.5 w-3.5 shrink-0 text-amber-500" />
                          ) : (
                            <Database className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
                          )}
                          <span className="text-sm font-medium text-gray-900 truncate">{s.id}</span>
                        </div>
                        <div className="flex shrink-0 items-center gap-3 text-xs text-gray-400 ml-2">
                          <span className="flex items-center gap-0.5">
                            <Download className="h-3 w-3" />
                            {formatNumber(s.downloads)}
                          </span>
                          <span className="flex items-center gap-0.5">
                            <Heart className="h-3 w-3" />
                            {s.likes}
                          </span>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button
                onClick={handleAdd}
                disabled={adding || !itemId.trim()}
                className="shrink-0 rounded-lg bg-amber-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-amber-600 disabled:opacity-50"
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
