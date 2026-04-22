import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { indexingApi } from "../api/indexing";
import type { Repo, BackendName } from "../api/indexing";
import AddRepoModal from "../components/AddRepoModal";
import DenseTriggerGuard from "../components/DenseTriggerGuard";
import ConfirmDialog from "../components/ConfirmDialog";

const BACKENDS = ["all", "zoekt", "dense", "graph"] as const;
const STATUSES = ["all", "success", "fail", "running", "warn"] as const;

type SortKey = "last_finished_at";

function relTime(ts: string | null) {
  if (!ts) return "—";
  const diff = (Date.now() - new Date(ts).getTime()) / 1000;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

function statusChip(s: string | null) {
  if (!s) return <span className="text-slate-400">—</span>;
  const cls: Record<string, string> = {
    success: "bg-emerald-100 text-emerald-800",
    fail: "bg-red-100 text-red-800",
    running: "bg-blue-100 text-blue-800",
    warn: "bg-amber-100 text-amber-800",
  };
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${cls[s] ?? "bg-slate-100 text-slate-700"}`}>
      {s}
    </span>
  );
}

function backendChip(b: string) {
  const cls: Record<string, string> = {
    zoekt: "bg-purple-100 text-purple-800",
    dense: "bg-teal-100 text-teal-800",
    graph: "bg-orange-100 text-orange-800",
  };
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${cls[b] ?? "bg-slate-100 text-slate-700"}`}>
      {b}
    </span>
  );
}

export default function Repositories() {
  const navigate = useNavigate();
  const [repos, setRepos] = useState<Repo[]>([]);
  const [total, setTotal] = useState(0);
  const [backendFilter, setBackendFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [sortAsc, setSortAsc] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Repo | null>(null);

  const load = useCallback(() => {
    const params: Record<string, string> = {};
    if (backendFilter !== "all") params.backend = backendFilter;
    if (statusFilter !== "all") params.status = statusFilter;
    indexingApi
      .listRepos(params)
      .then((r) => {
        setTotal(r.total);
        const sorted = [...r.items].sort((a, b) => {
          const ta = a.last_finished_at ? new Date(a.last_finished_at).getTime() : 0;
          const tb = b.last_finished_at ? new Date(b.last_finished_at).getTime() : 0;
          return sortAsc ? ta - tb : tb - ta;
        });
        setRepos(sorted);
      })
      .catch((e) => setErr(String(e)));
  }, [backendFilter, statusFilter, sortAsc]);

  useEffect(() => { load(); }, [load]);

  async function handleTrigger(repo: Repo) {
    try {
      await indexingApi.createJob(repo.repo_path, repo.backend);
      load();
    } catch (e) {
      setErr(String(e));
    }
  }

  async function handleDelete(repo: Repo) {
    try {
      await indexingApi.deleteRepo(repo.id, repo.backend);
      setDeleteTarget(null);
      load();
    } catch (e) {
      setErr(String(e));
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold">Repositories</h1>
        <span className="text-slate-500 text-sm">{total} total</span>
        <button
          onClick={() => setAddOpen(true)}
          className="ml-auto px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm"
        >
          + Add Repo
        </button>
      </div>

      <div className="flex flex-wrap gap-2 bg-white border rounded p-3">
        <select
          className="border rounded px-2 py-1 text-sm"
          value={backendFilter}
          onChange={(e) => setBackendFilter(e.target.value)}
          data-testid="filter-backend"
        >
          {BACKENDS.map((b) => (
            <option key={b} value={b}>{b === "all" ? "所有 backend" : b}</option>
          ))}
        </select>
        <select
          className="border rounded px-2 py-1 text-sm"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          data-testid="filter-status"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>{s === "all" ? "所有状态" : s}</option>
          ))}
        </select>
      </div>

      {err && <div className="p-3 bg-red-100 text-red-700 rounded">{err}</div>}

      <div className="bg-white border rounded overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr>
              <th className="p-2">仓库路径</th>
              <th className="p-2">Backend</th>
              <th
                className="p-2 cursor-pointer select-none hover:bg-slate-200"
                onClick={() => setSortAsc((v) => !v)}
                data-testid="sort-last-finished"
              >
                最近完成 {sortAsc ? "↑" : "↓"}
              </th>
              <th className="p-2">耗时</th>
              <th className="p-2">状态</th>
              <th className="p-2">实体数</th>
              <th className="p-2">操作</th>
            </tr>
          </thead>
          <tbody>
            {repos.map((repo) => (
              <tr key={`${repo.id}-${repo.backend}`} className="border-t hover:bg-slate-50">
                <td className="p-2 font-mono text-xs">{repo.repo_path}</td>
                <td className="p-2">{backendChip(repo.backend)}</td>
                <td className="p-2 text-xs">{relTime(repo.last_finished_at)}</td>
                <td className="p-2 text-xs">
                  {repo.last_duration_s != null ? `${repo.last_duration_s.toFixed(1)}s` : "—"}
                </td>
                <td className="p-2">{statusChip(repo.last_status)}</td>
                <td className="p-2">{repo.entity_count ?? "—"}</td>
                <td className="p-2">
                  <div className="flex gap-2">
                    <button
                      onClick={() => navigate(`/repos/${repo.id}`)}
                      className="text-blue-600 hover:underline text-xs"
                    >
                      详情
                    </button>
                    <DenseTriggerGuard
                      repoPath={repo.repo_path}
                      backend={repo.backend as BackendName}
                      onConfirmed={() => handleTrigger(repo)}
                    >
                      {(trigger) => (
                        <button
                          onClick={trigger}
                          className="text-amber-600 hover:underline text-xs"
                          data-testid={`trigger-${repo.id}`}
                        >
                          重新索引
                        </button>
                      )}
                    </DenseTriggerGuard>
                    <button
                      onClick={() => setDeleteTarget(repo)}
                      className="text-red-600 hover:underline text-xs"
                      data-testid={`delete-${repo.id}`}
                    >
                      删除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <AddRepoModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onAdded={() => { setAddOpen(false); load(); }}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        title="确认删除"
        message={deleteTarget ? `确认删除仓库 ${deleteTarget.repo_path} (${deleteTarget.backend})?` : ""}
        onConfirm={() => deleteTarget && handleDelete(deleteTarget)}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
