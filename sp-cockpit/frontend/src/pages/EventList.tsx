import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { EventsResponse } from "../types/api";

const PAGE_SIZE = 50;

export default function EventList() {
  const [params, setParams] = useSearchParams();
  const tool = params.get("tool") ?? "";
  const status = params.get("status") ?? "";
  const slow = params.get("slow") ?? "";
  const event = params.get("event") ?? "";
  const offset = Number(params.get("offset") ?? 0);

  const [data, setData] = useState<EventsResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setErr(null);
    const slowParam = slow === "true" ? "1" : slow === "false" ? "0" : "";
    api
      .events({ tool, status, slow: slowParam, event, limit: PAGE_SIZE, offset })
      .then(setData)
      .catch((e) => setErr(String(e)));
  }, [tool, status, slow, event, offset]);

  function update(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("offset");
    setParams(next);
  }

  function setOffset(n: number) {
    const next = new URLSearchParams(params);
    next.set("offset", String(Math.max(0, n)));
    setParams(next);
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Events</h1>
      <div className="flex flex-wrap gap-2 bg-white border rounded p-3">
        <input
          placeholder="tool"
          className="border rounded px-2 py-1"
          value={tool}
          onChange={(e) => update("tool", e.target.value)}
        />
        <select
          className="border rounded px-2 py-1"
          value={status}
          onChange={(e) => update("status", e.target.value)}
        >
          <option value="">any status</option>
          <option value="ok">ok</option>
          <option value="error">error</option>
        </select>
        <select
          className="border rounded px-2 py-1"
          value={slow}
          onChange={(e) => update("slow", e.target.value)}
        >
          <option value="">any speed</option>
          <option value="true">slow only</option>
          <option value="false">fast only</option>
        </select>
        <input
          placeholder="event (e.g. tool_call)"
          className="border rounded px-2 py-1"
          value={event}
          onChange={(e) => update("event", e.target.value)}
        />
      </div>

      {err && <div className="p-3 bg-red-100 text-red-700 rounded">{err}</div>}

      {data && (
        <>
          <div className="text-sm text-slate-600">
            {data.total} total — showing {data.items.length}
          </div>
          <div className="bg-white border rounded overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-100 text-left">
                <tr>
                  <th className="p-2">Time</th>
                  <th className="p-2">Trace</th>
                  <th className="p-2">Event</th>
                  <th className="p-2">Tool/Stage</th>
                  <th className="p-2">Status</th>
                  <th className="p-2 text-right">Duration (ms)</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((e) => (
                  <tr key={e.id} className="border-t hover:bg-slate-50">
                    <td className="p-2 whitespace-nowrap">
                      {new Date(e.ts_ms).toLocaleString()}
                    </td>
                    <td className="p-2 font-mono text-xs">
                      {e.trace_id ? (
                        <Link to={`/trace/${e.trace_id}`} className="text-blue-600 hover:underline">
                          {e.trace_id}
                        </Link>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className="p-2">{e.event}</td>
                    <td className="p-2">{e.tool ?? e.stage ?? "—"}</td>
                    <td className="p-2">
                      <span
                        className={
                          e.status === "error"
                            ? "text-red-600 font-semibold"
                            : "text-emerald-600"
                        }
                      >
                        {e.status}
                      </span>
                      {e.slow ? <span className="ml-1 text-amber-600">slow</span> : null}
                    </td>
                    <td className="p-2 text-right font-mono">{e.duration_ms.toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex gap-2 justify-end">
            <button
              className="px-3 py-1 border rounded bg-white disabled:opacity-50"
              onClick={() => setOffset(offset - PAGE_SIZE)}
              disabled={offset <= 0}
            >
              Prev
            </button>
            <button
              className="px-3 py-1 border rounded bg-white disabled:opacity-50"
              onClick={() => setOffset(offset + PAGE_SIZE)}
              disabled={offset + PAGE_SIZE >= data.total}
            >
              Next
            </button>
          </div>
        </>
      )}
    </div>
  );
}
