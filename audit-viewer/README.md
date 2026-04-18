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

Or via Docker Compose:

```bash
docker compose up -d audit-viewer
```

## Configuration

| Env var                       | Default                | Notes                                |
|-------------------------------|------------------------|--------------------------------------|
| `AUDIT_LOG_PATH`              | `audit.log`            | Source JSONL — opened read-only      |
| `AUDIT_DB_PATH`               | `./data/audit.db`      | SQLite WAL                           |
| `AUDIT_VIEWER_HOST`           | `127.0.0.1`            | Bind address                         |
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
