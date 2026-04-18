import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import type { TraceResponse } from "../types/api";

export default function TraceDetail() {
  const { traceId = "" } = useParams();
  const [data, setData] = useState<TraceResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setErr(null);
    api.trace(traceId).then(setData).catch((e) => setErr(String(e)));
  }, [traceId]);

  if (err) return <div className="p-3 bg-red-100 text-red-700 rounded">{err}</div>;
  if (!data) return <div>Loading…</div>;

  const total = Math.max(1, data.total_ms);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold font-mono">{data.trace_id}</h1>
        <div className="text-sm text-slate-600">
          {data.event_count} events · {data.total_ms.toFixed(1)}ms total ·{" "}
          {data.has_error ? (
            <span className="text-red-600 font-semibold">has error</span>
          ) : (
            <span className="text-emerald-600">all ok</span>
          )}
        </div>
      </div>

      <div className="bg-white border rounded p-4" data-testid="waterfall">
        <h2 className="font-semibold mb-3">Waterfall</h2>
        <div className="space-y-1">
          {data.events.map((e) => {
            const offset = ((e.ts_ms - data.started_ms) / total) * 100;
            const width = Math.max(0.5, (e.duration_ms / total) * 100);
            const label = e.tool ?? e.stage ?? e.event;
            return (
              <div key={e.id} className="flex items-center gap-2 text-xs">
                <div className="w-40 truncate font-mono text-slate-700">{label}</div>
                <div className="flex-1 relative h-5 bg-slate-100 rounded">
                  <div
                    className={`absolute h-5 rounded ${
                      e.status === "error"
                        ? "bg-red-400"
                        : e.slow
                        ? "bg-amber-400"
                        : "bg-blue-400"
                    }`}
                    style={{ left: `${offset}%`, width: `${width}%` }}
                    title={`${e.duration_ms.toFixed(1)}ms`}
                  />
                </div>
                <div className="w-20 text-right font-mono">{e.duration_ms.toFixed(1)}ms</div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="bg-white border rounded p-4">
        <h2 className="font-semibold mb-3">Events</h2>
        <div className="space-y-2">
          {data.events.map((e) => (
            <details key={e.id} className="border rounded p-2">
              <summary className="cursor-pointer text-sm">
                <span className="font-mono">
                  {new Date(e.ts_ms).toLocaleTimeString()}
                </span>{" "}
                · {e.event} · {e.tool ?? e.stage ?? "—"} · {e.status} ·{" "}
                {e.duration_ms.toFixed(1)}ms
              </summary>
              <pre className="mt-2 text-xs bg-slate-50 p-2 rounded overflow-x-auto">
                {prettyJson(e.payload_json)}
              </pre>
            </details>
          ))}
        </div>
      </div>
    </div>
  );
}

function prettyJson(s: string): string {
  try {
    return JSON.stringify(JSON.parse(s), null, 2);
  } catch {
    return s;
  }
}
