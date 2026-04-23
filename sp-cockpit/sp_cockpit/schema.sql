CREATE TABLE IF NOT EXISTS events (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_ms        INTEGER NOT NULL,
  trace_id     TEXT NOT NULL,
  event        TEXT NOT NULL,
  duration_ms  REAL NOT NULL DEFAULT 0,
  status       TEXT NOT NULL DEFAULT 'ok',
  slow         INTEGER NOT NULL DEFAULT 0,
  tool         TEXT,
  stage        TEXT,
  interface    TEXT,
  payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_ts        ON events(ts_ms DESC);
CREATE INDEX IF NOT EXISTS idx_events_trace_ts  ON events(trace_id, ts_ms ASC);
CREATE INDEX IF NOT EXISTS idx_events_tool_ts   ON events(tool, ts_ms DESC);
CREATE INDEX IF NOT EXISTS idx_events_status_ts ON events(status, ts_ms DESC);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
