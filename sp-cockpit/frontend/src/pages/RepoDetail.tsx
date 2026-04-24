import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { indexingApi } from "../api/indexing";
import type { RepoDetail as RepoDetailType, Job } from "../api/indexing";
import LogViewer from "../components/LogViewer";

export default function RepoDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<RepoDetailType | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [logJobId, setLogJobId] = useState<number | null>(null);

  const numId = Number(id);
  const isValidId = !!id && !isNaN(numId);

  useEffect(() => {
    if (!isValidId) return;
    indexingApi
      .getRepoDetail(numId)
      .then(setDetail)
      .catch((e) => setErr(String(e)));
  }, [isValidId, numId]);

  if (!isValidId) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate("/repos")} className="text-blue-600 hover:underline text-sm">
            ← Repositories
          </button>
          <h1 className="text-2xl font-semibold">Repo Detail</h1>
        </div>
        <div className="p-3 bg-red-100 text-red-700 rounded">Invalid repository ID</div>
      </div>
    );
  }

  function statusClass(s: string | null) {
    if (s === "success") return "text-emerald-600 font-semibold";
    if (s === "fail") return "text-red-600 font-semibold";
    if (s === "running") return "text-blue-600 font-semibold";
    if (s === "warn") return "text-amber-600 font-semibold";
    return "text-slate-400";
  }

  function relTime(ts: string | null) {
    if (!ts) return "—";
    const diff = (Date.now() - new Date(ts).getTime()) / 1000;
    if (diff < 60) return `${Math.round(diff)}s ago`;
    if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
    return `${Math.round(diff / 86400)}d ago`;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate("/repos")} className="text-blue-600 hover:underline text-sm">
          ← Repositories
        </button>
        <h1 className="text-2xl font-semibold">Repo Detail</h1>
      </div>

      {err && <div className="p-3 bg-red-100 text-red-700 rounded">{err}</div>}

      {detail && (
        <>
          <div className="bg-white border rounded p-4 space-y-2">
            <div><span className="font-medium">路径:</span> {detail.repo.repo_path}</div>
            <div><span className="font-medium">Backend:</span> {detail.repo.backend}</div>
            <div>
              <span className="font-medium">状态:</span>{" "}
              <span className={statusClass(detail.repo.last_status)}>
                {detail.repo.last_status ?? "—"}
              </span>
            </div>
            <div><span className="font-medium">最近完成:</span> {relTime(detail.repo.last_finished_at)}</div>
            <div><span className="font-medium">实体数:</span> {detail.repo.entity_count ?? "—"}</div>
          </div>

          <div className="bg-white border rounded overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-100 text-left">
                <tr>
                  <th className="p-2">Job ID</th>
                  <th className="p-2">Status</th>
                  <th className="p-2">Started</th>
                  <th className="p-2">Finished</th>
                  <th className="p-2">Duration</th>
                  <th className="p-2">Entities</th>
                  <th className="p-2">Log</th>
                </tr>
              </thead>
              <tbody>
                {detail.jobs.map((job: Job) => (
                  <tr key={job.id} className="border-t hover:bg-slate-50">
                    <td className="p-2 font-mono text-xs">{job.id}</td>
                    <td className={`p-2 ${statusClass(job.status)}`}>{job.status}</td>
                    <td className="p-2 text-xs">{job.started_at ? new Date(job.started_at).toLocaleString() : "—"}</td>
                    <td className="p-2 text-xs">{job.finished_at ? new Date(job.finished_at).toLocaleString() : "—"}</td>
                    <td className="p-2">{job.duration_s != null ? `${job.duration_s.toFixed(1)}s` : "—"}</td>
                    <td className="p-2">{job.entity_count ?? "—"}</td>
                    <td className="p-2">
                      <button
                        onClick={() => setLogJobId(job.id)}
                        className="text-blue-600 hover:underline text-xs"
                      >
                        View Log
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Log Modal */}
      {logJobId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-3xl p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">Job #{logJobId} Log</h2>
              <button onClick={() => setLogJobId(null)} className="text-slate-500 hover:text-slate-800">✕</button>
            </div>
            <LogViewer jobId={logJobId} />
          </div>
        </div>
      )}
    </div>
  );
}
