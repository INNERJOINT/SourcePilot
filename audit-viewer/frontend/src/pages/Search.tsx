import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { SearchResponse } from "../types/api";

export default function Search() {
  const [q, setQ] = useState("");
  const [data, setData] = useState<SearchResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!q.trim()) return;
    setLoading(true);
    setErr(null);
    try {
      setData(await api.search(q.trim()));
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Search</h1>
      <form onSubmit={submit} className="flex gap-2">
        <input
          className="flex-1 border rounded px-3 py-2"
          placeholder="Search payload (substring)…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button className="px-4 py-2 bg-blue-600 text-white rounded">Search</button>
      </form>

      {loading && <div>Searching…</div>}
      {err && <div className="p-3 bg-red-100 text-red-700 rounded">{err}</div>}

      {data && (
        <div className="bg-white border rounded p-4">
          <div className="text-sm text-slate-600 mb-2">
            {data.total} matching trace(s) for "{data.q}"
          </div>
          <ul className="space-y-1">
            {data.trace_ids.map((tid) => (
              <li key={tid}>
                <Link to={`/trace/${tid}`} className="text-blue-600 hover:underline font-mono">
                  {tid}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
