CREATE TABLE IF NOT EXISTS index_repos (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_path   TEXT    NOT NULL,
  project     TEXT,
  created_at  INTEGER NOT NULL DEFAULT (strftime('%s','now') * 1000),
  archived_at INTEGER,
  UNIQUE(repo_path, project)
);

CREATE TABLE IF NOT EXISTS index_jobs (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_id              INTEGER NOT NULL REFERENCES index_repos(id),
  backend              TEXT    NOT NULL CHECK(backend IN ('zoekt', 'dense', 'graph')),
  started_at           INTEGER NOT NULL DEFAULT (strftime('%s','now') * 1000),
  finished_at          INTEGER,
  status               TEXT    NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'running', 'success', 'fail', 'warn')),
  exit_code            INTEGER,
  log_path             TEXT,
  entity_count_before  INTEGER,
  entity_count_after   INTEGER
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_singleton_lock
  ON index_jobs(repo_id, backend)
  WHERE status = 'running';

CREATE INDEX IF NOT EXISTS idx_jobs_repo_backend
  ON index_jobs(repo_id, backend, started_at DESC);

CREATE TABLE IF NOT EXISTS indexing_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
