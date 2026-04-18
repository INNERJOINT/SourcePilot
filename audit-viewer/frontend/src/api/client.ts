import type {
  EventsResponse,
  HealthResponse,
  SearchResponse,
  StatsResponse,
  TraceResponse,
} from "../types/api";

const BASE = "/api";

async function get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(BASE + path, window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== "" && v !== null) url.searchParams.set(k, String(v));
    }
  }
  const r = await fetch(url.toString());
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
  return (await r.json()) as T;
}

export const api = {
  health: () => get<HealthResponse>("/health"),
  stats: (window: string) => get<StatsResponse>("/stats", { window }),
  events: (params: Record<string, string | number | undefined>) =>
    get<EventsResponse>("/events", params),
  trace: (traceId: string) => get<TraceResponse>(`/trace/${encodeURIComponent(traceId)}`),
  search: (q: string, limit = 50) => get<SearchResponse>("/search", { q, limit }),
};
