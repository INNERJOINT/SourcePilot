export interface EventRow {
  id: number;
  ts_ms: number;
  trace_id: string;
  event: string;
  duration_ms: number;
  status: string;
  slow: number;
  tool?: string | null;
  stage?: string | null;
  interface?: string | null;
  payload_json: string;
}

export interface EventsResponse {
  total: number;
  items: EventRow[];
}

export interface StatsBucket {
  ts_ms: number;
  qps: number;
  p50_ms: number;
  p95_ms: number;
  error_rate: number;
}

export interface StatsResponse {
  window: string;
  total_events: number;
  qps: number;
  p50_ms: number;
  p95_ms: number;
  error_rate: number;
  slow_ratio: number;
  buckets: StatsBucket[];
}

export interface TraceResponse {
  trace_id: string;
  event_count: number;
  started_ms: number;
  ended_ms: number;
  total_ms: number;
  has_error: boolean;
  events: EventRow[];
}

export interface SearchResponse {
  q: string;
  trace_ids: string[];
  total: number;
}

export interface ProjectInfo {
  name: string;
  source_root: string;
  repo_path: string;
  zoekt_url: string;
}
