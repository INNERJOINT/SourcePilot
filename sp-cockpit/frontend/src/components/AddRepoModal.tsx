import { useState } from "react";
import type { BackendName } from "../api/indexing";
import { indexingApi } from "../api/indexing";

interface AddRepoModalProps {
  open: boolean;
  onClose: () => void;
  onAdded: () => void;
}

const BACKENDS: BackendName[] = ["zoekt", "dense", "graph"];

export default function AddRepoModal({ open, onClose, onAdded }: AddRepoModalProps) {
  const [repoPath, setRepoPath] = useState("");
  const [checked, setChecked] = useState<Set<BackendName>>(new Set(["zoekt"]));
  const [submitting, setSubmitting] = useState(false);
  const [progress, setProgress] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  function toggleBackend(b: BackendName) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(b)) next.delete(b);
      else next.add(b);
      return next;
    });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!repoPath.trim()) return;
    if (checked.size === 0) {
      setError("至少选择一个 backend");
      return;
    }
    setSubmitting(true);
    setError(null);
    setProgress([]);
    const backends = Array.from(checked);
    let successCount = 0;
    for (const backend of backends) {
      try {
        await indexingApi.createJob(repoPath.trim(), backend);
        setProgress((p) => [...p, `✓ ${backend} job triggered`]);
        successCount++;
      } catch (e) {
        setProgress((p) => [...p, `✗ ${backend}: ${String(e)}`]);
      }
    }
    setSubmitting(false);
    if (successCount > 0) {
      onAdded();
    }
  }

  function handleClose() {
    setRepoPath("");
    setChecked(new Set(["zoekt"]));
    setProgress([]);
    setError(null);
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-md p-6 space-y-4">
        <h2 className="text-lg font-semibold">添加仓库 / 触发索引</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">仓库路径</label>
            <input
              type="text"
              value={repoPath}
              onChange={(e) => setRepoPath(e.target.value)}
              placeholder="/path/to/repo"
              className="w-full border rounded px-3 py-2"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Backend</label>
            <div className="flex gap-4">
              {BACKENDS.map((b) => (
                <label key={b} className="flex items-center gap-1 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={checked.has(b)}
                    onChange={() => toggleBackend(b)}
                    data-testid={`checkbox-${b}`}
                  />
                  {b}
                </label>
              ))}
            </div>
          </div>

          {error && <div className="p-2 bg-red-100 text-red-700 rounded text-sm">{error}</div>}

          {progress.length > 0 && (
            <ul className="text-sm space-y-1">
              {progress.map((msg, i) => (
                <li key={i} className={msg.startsWith("✓") ? "text-green-700" : "text-red-600"}>
                  {msg}
                </li>
              ))}
            </ul>
          )}

          <div className="flex gap-3 justify-end">
            <button
              type="button"
              onClick={handleClose}
              className="px-4 py-2 border rounded hover:bg-slate-50"
              disabled={submitting}
            >
              取消
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {submitting ? "提交中..." : "提交"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
