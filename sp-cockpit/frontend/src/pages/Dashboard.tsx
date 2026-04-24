import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api/client";
import type { StatsResponse } from "../types/api";

const WINDOWS = ["1h", "6h", "24h"] as const;

export default function Dashboard() {
  const [window, setWindow] = useState<string>("1h");
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setErr(null);
    api.stats(window).then(setStats).catch((e) => setErr(String(e)));
  }, [window]);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <div className="ml-auto flex gap-2">
          {WINDOWS.map((w) => (
            <button
              key={w}
              onClick={() => setWindow(w)}
              className={`px-3 py-1 rounded border ${
                w === window ? "bg-blue-600 text-white border-blue-600" : "bg-white"
              }`}
            >
              {w}
            </button>
          ))}
        </div>
      </div>

      {err && <div className="p-3 bg-red-100 text-red-700 rounded">{err}</div>}

      {stats && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <Metric label="Total" value={(stats.total_events ?? 0).toLocaleString()} />
            <Metric label="QPS" value={(stats.qps ?? 0).toFixed(2)} />
            <Metric label="p50 (ms)" value={(stats.p50_ms ?? 0).toFixed(1)} />
            <Metric label="p95 (ms)" value={(stats.p95_ms ?? 0).toFixed(1)} />
            <Metric label="Error rate" value={`${((stats.error_rate ?? 0) * 100).toFixed(2)}%`} />
          </div>
          <div className="bg-white border rounded p-4" data-testid="latency-chart">
            <h2 className="font-semibold mb-2">Latency over time</h2>
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={stats.buckets}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="ts_ms"
                  tickFormatter={(v) => new Date(v).toLocaleTimeString()}
                />
                <YAxis />
                <Tooltip
                  labelFormatter={(v) => new Date(Number(v)).toLocaleString()}
                />
                <Line type="monotone" dataKey="p50_ms" stroke="#3b82f6" dot={false} />
                <Line type="monotone" dataKey="p95_ms" stroke="#ef4444" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="bg-white border rounded p-4">
            <h2 className="font-semibold mb-2">QPS over time</h2>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={stats.buckets}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="ts_ms" tickFormatter={(v) => new Date(v).toLocaleTimeString()} />
                <YAxis />
                <Tooltip labelFormatter={(v) => new Date(Number(v)).toLocaleString()} />
                <Line type="monotone" dataKey="qps" stroke="#10b981" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white border rounded p-4">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className="text-2xl font-semibold">{value}</div>
    </div>
  );
}
