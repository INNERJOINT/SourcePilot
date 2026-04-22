# audit-viewer

Web UI for browsing SourcePilot audit logs.

## What it does

- **Tails** `audit.log` (JSONL) into a SQLite database (`O_RDONLY`, never writes).
- **Serves** a FastAPI backend (`/api/*`, port `9100`) and a React SPA.
- **Retains** the last 30 days of events (hourly `DELETE`).
- **Survives** rotation (anchors on inode + offset, drains `.5 → .1` on restart).

Three views:

- **Dashboard** — QPS / p50 / p95 / error rate / slow ratio over a 1h/6h/24h window.
- **Events** — paginated list with tool / status / slow filters, URL-bound.
- **Trace detail** — waterfall + per-event JSON for a given `trace_id`.
- **Search** — substring match across event payloads.

## Quick start

```bash
# 1. Backend tests
cd audit-viewer
pytest tests/ -v

# 2. Frontend
cd frontend
npm install
npm run build           # produces frontend/dist
cd ..

# 3. Run
AUDIT_LOG_PATH=../audit.log \
AUDIT_DB_PATH=./data/audit.db \
AUDIT_VIEWER_FRONTEND_DIST=./frontend/dist \
  python -m audit_viewer.main
# → http://127.0.0.1:9100
```

Or via Docker Compose (from repo root):

```bash
docker compose up -d audit-viewer
```

The compose service bind-mounts:

- `${AUDIT_LOG_PATH:-./audit.log}` (host) → `/var/log/sourcepilot/audit.log` (read-only) — same file SourcePilot writes
- `./audit-viewer/data` (host) → `/data` — keeps the SQLite mirror DB at the same path used by `scripts/run_audit_viewer.sh`, so containerized and native runs share one `audit.db`.

## Configuration

| Env var                       | Default                | Notes                                |
|-------------------------------|------------------------|--------------------------------------|
| `AUDIT_LOG_PATH`              | `audit.log`            | Source JSONL — opened read-only      |
| `AUDIT_DB_PATH`               | `./data/audit.db`      | SQLite WAL                           |
| `AUDIT_VIEWER_HOST`           | `0.0.0.0`              | Bind address                         |
| `AUDIT_VIEWER_PORT`           | `9100`                 |                                      |
| `AUDIT_VIEWER_FRONTEND_DIST`  | `./frontend/dist`      | Static files                         |
| `RETENTION_DAYS`              | `30`                   |                                      |
| `POLL_MS`                     | `500`                  | Tail interval                        |
| `ROTATION_MAX_N`              | `5`                    | `.1` … `.N` rotated suffixes         |
| `SHUTDOWN_GRACE_S`            | `2.0`                  | SIGTERM/SIGINT drain window          |
| `CORS_ORIGINS`                | `*`                    |                                      |

## API

- `GET /api/health` — DB row count + latest event timestamp
- `GET /api/stats?window=1h|6h|24h` — windowed metrics + bucketed series
- `GET /api/events?tool=&status=&slow=&event=&trace_id=&from_ms=&to_ms=&limit=&offset=`
- `GET /api/trace/{trace_id}` — events ordered by `ts_ms ASC`
- `GET /api/search?q=&limit=` — distinct trace_ids whose payload contains `q`

## Acceptance criteria coverage

| AC  | Test                                                  |
|-----|-------------------------------------------------------|
| AC1 | `tests/test_ingester.py::test_ac1_freshness`          |
| AC2 | `tests/test_ingester.py::test_ac2_restart_resume`     |
| AC3 | `tests/test_api.py::test_ac3_stats_latency_p95`       |
| AC4 | `tests/test_api.py::test_ac4_events_latency_p95`      |
| AC5 | `tests/test_api.py::test_ac5_trace_waterfall_order`   |
| AC6 | `tests/test_api.py::test_ac6_search_substring`        |
| AC7 | `tests/test_retention.py::test_30d_cutoff`            |
| AC10| `tests/test_ingester.py::test_ac10_*`                 |
| AC11| `frontend/tests-e2e/trace_detail.spec.ts`             |
| AC12| `tests/test_ingester.py::test_ac12_readonly_open`     |
| AC13| `tests/test_parser.py::test_naive_iso_treated_as_utc` |
| AC14| `tests/test_api.py::test_ac14_audit_summary_excluded_from_trace` |
| AC15| `tests/test_ingester.py::test_ac15_sigterm_drains_batch` |

---

## Indexing Admin

Web UI for managing AOSP indexing jobs across three backends (Zoekt, Milvus/dense, Neo4j/graph).

Access: **http://localhost:9100/repos**

### Architecture

```
wrapper scripts (host)
  └─ scripts/_indexing_lib.sh
       ├─ start_job()  → POST /api/indexing/jobs/internal-start  (X-Indexing-Internal-Token)
       └─ finish_job() → POST /api/indexing/jobs/{id}/finish     (X-Indexing-Internal-Token)

FastAPI (audit-viewer, port 9100)
  └─ /api/indexing/* router
       └─ indexing.db  ← sole writer (R4: HTTP callback pattern)

React SPA → /repos
  └─ polls /api/indexing/repos  every ~3 s
  └─ polls /api/indexing/jobs/{id}/log?offset=  every 2.5 s (stops on eof:true)
```

### Data model (`audit-viewer/data/indexing.db`)

> ⚠️ **Two separate databases** — do NOT conflate:
> - `audit.db` — audit log mirror (existing, read-only ingestion from `audit.log`)
> - `indexing.db` — indexing metadata (new, written only by the FastAPI process via HTTP callbacks)

**`index_repos`**

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | auto |
| `repo_path` | TEXT UNIQUE | e.g. `frameworks/base` |
| `created_at` | INTEGER | epoch ms |
| `archived_at` | INTEGER | NULL = active |

**`index_jobs`**

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | auto |
| `repo_id` | INTEGER FK | → `index_repos.id` |
| `backend` | TEXT | `zoekt` \| `dense` \| `graph` |
| `started_at` | INTEGER | epoch ms |
| `finished_at` | INTEGER | NULL while running |
| `status` | TEXT | `pending` / `running` / `success` / `fail` / `warn` |
| `exit_code` | INTEGER | set by `finish` hook |
| `log_path` | TEXT | absolute path on host |
| `entity_count_before` | INTEGER | snapshot before run |
| `entity_count_after` | INTEGER | snapshot after run |

Partial unique index enforces `(repo_id, backend)` singleton lock:

```sql
CREATE UNIQUE INDEX idx_singleton_lock
  ON index_jobs(repo_id, backend)
  WHERE status = 'running';
```

### Configuration

| Env var | Default | Notes |
|---|---|---|
| `INDEXING_DB_PATH` | `indexing.db` | SQLite for indexing metadata |
| `INDEXING_INTERNAL_TOKEN` | `""` | Shared secret between wrapper scripts and API |

### Triggering a reindex

**Via UI** — navigate to `/repos`, click **Trigger Reindex** on a row.
For the `dense` backend a confirmation dialog must be acknowledged first
(guard against accidental Milvus collection rebuild).

**Via CLI** (wrapper scripts call this automatically):

```bash
# Start — emits JOB_ID=N on stdout
export JOB_ID=$(python -m audit_viewer.indexing_cli start \
  --repo-path frameworks/base --backend zoekt \
  --log-path /tmp/job.log --pid-file /tmp/job.pid \
  --internal-token "$INDEXING_INTERNAL_TOKEN")

# … indexer runs …

# Finish
python -m audit_viewer.indexing_cli finish \
  --job-id "$JOB_ID" --status success --exit-code 0 \
  --internal-token "$INDEXING_INTERNAL_TOKEN"
```

**Via wrapper scripts** (preferred — handles trap/cleanup automatically):

```bash
bash scripts/build_graph_index.sh  frameworks/base
bash scripts/build_dense_index_batch.sh  frameworks/base
bash scripts/reindex.sh  frameworks/base
```

### Backend SDK isolation

`pymilvus` and `neo4j-driver` are **not** installed in the audit-viewer environment.
Hard-delete and entity-count operations are executed inside the indexer containers via
`docker compose run --rm <service> python -m scripts.<op>`.

⚠️ **Do NOT call `build_*_index.py` scripts directly** — use the wrapper scripts so
`indexing_cli` hooks fire and metadata is recorded.

### Manual acceptance checklist

- [ ] Navigate to `http://localhost:9100/repos` — page renders without errors
- [ ] `frameworks/base` appears with `dense` and `graph` rows (status `success`)
- [ ] Click **Trigger Reindex** on the `graph` row → status flips to `running`
- [ ] Log viewer streams output in real time; stops on job completion
- [ ] Status turns `success` / `fail`, entity_count refreshes
- [ ] Click **Delete** on a repo row → confirmation dialog → row disappears
- [ ] For `dense` backend Trigger: confirmation dialog **must** appear before POST fires
- [ ] `pytest audit-viewer/tests/test_no_heavy_deps.py` — PASSED (no pymilvus/neo4j)
- [ ] `pytest audit-viewer/tests/test_indexing_e2e.py` — all tests green
