# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AOSP Code Search — three independent services:

1. **SourcePilot** (`src/`) — Hybrid RAG search engine with Starlette HTTP API
2. **MCP Access Layer** (`mcp-server/`) — Thin MCP protocol proxy delegating to SourcePilot via httpx
3. **Audit Viewer** (`audit-viewer/`) — FastAPI + React SPA for browsing SourcePilot's `audit.log` (port 9100). Tails JSONL into SQLite, exposes Dashboard / Events / Trace / Search. Read-only against `audit.log`. See `audit-viewer/README.md`.

## Commands

```bash
# Environment setup (copy template, edit values)
cp .env.example .env

# Start full stack (zoekt + SourcePilot + MCP) — reads from .env
scripts/run_all.sh

# Start both services (auto-starts SourcePilot as subprocess)
scripts/run_mcp.sh

# Start SourcePilot standalone
scripts/run_sourcepilot.sh

# Start MCP with external SourcePilot
SOURCEPILOT_URL=http://localhost:9000 scripts/run_mcp.sh

# MCP Streamable HTTP mode
scripts/run_mcp.sh --transport streamable-http --port 8888

# Run SourcePilot tests (unit + integration + e2e)
PYTHONPATH=src pytest tests/unit/sourcepilot/ tests/integration/ tests/e2e/ -v

# Run MCP tests
PYTHONPATH=mcp-server pytest tests/unit/mcp/ -v

# Run all tests
PYTHONPATH=src pytest tests/unit/sourcepilot/ tests/integration/ tests/e2e/ -v && PYTHONPATH=mcp-server pytest tests/unit/mcp/ -v
```

## Architecture

```
src/                              # SourcePilot — Hybrid RAG Search Engine
├── app.py                        # Starlette HTTP API (7 endpoints, port 9000)
├── gateway/                      # Layer 1: Query Gateway (business logic)
│   ├── gateway.py                # Main orchestrator: classify → NL pipeline or direct search
│   ├── router.py                 # Query routing & parallel dispatch
│   ├── fusion.py                 # RRF cross-engine fusion
│   ├── ranker.py                 # Feature-based reranking
│   └── nl/                       # NL sub-module
│       ├── classifier.py         # Query intent classification
│       ├── rewriter.py           # LLM query rewrite
│       ├── cache.py              # LRU cache + concept_map
│       └── concept_map.json
├── adapters/                     # Layer 2: Adapter Layer (pluggable backends)
│   ├── base.py                   # SearchAdapter ABC
│   ├── zoekt.py                  # ZoektAdapter — Zoekt HTTP client
│   └── feishu.py                 # FeishuAdapter placeholder
├── observability/                # Cross-cutting: Observability
│   └── audit.py                  # Structured JSON audit logging
└── config/                       # Cross-cutting: Configuration
    ├── base.py                   # Env var config
    └── backends.py               # Backend registry

mcp-server/                       # MCP Access Layer — Protocol Proxy
├── mcp_server.py                 # Entry-point dispatcher (stdio/HTTP)
├── requirements.txt
└── entry/
    ├── handlers.py               # MCP Server + tools + httpx client → SourcePilot
    ├── mcp_stdio.py              # stdio transport
    └── mcp_http.py               # HTTP transport + BearerTokenMiddleware
```

### Request Flow

**MCP path**: tool call → `mcp-server/entry/handlers.py` → httpx POST → `src/app.py` → `gateway.search()` → classify → ZoektAdapter → format results

**Direct SourcePilot path**: HTTP POST → `src/app.py` → `gateway.search()` → classify → ZoektAdapter → JSON response

### Key Design Decisions

- Two projects communicate via HTTP API (localhost:9000). No shared imports.
- MCP layer uses httpx.AsyncClient (module-level singleton, timeout=30s) to call SourcePilot.
- X-Trace-Id header propagates trace IDs across services.
- Audit/config fully in SourcePilot; MCP layer uses standard logging only.
- All SourcePilot imports use paths relative to `src/` (`from config import ...`, `from gateway.nl.rewriter import ...`).
- All MCP imports use paths relative to `mcp-server/` (`from entry.handlers import ...`).
- Layered dependency within SourcePilot: gateway → adapters → config/observability. No upward dependencies.
- Zoekt score normalization uses sigmoid mapping: `1/(1+exp(-0.1*(score-10)))` inside `ZoektAdapter` to map BM25 scores (typically 0-50) into 0-1 range.
- Zoekt `/print` endpoint returns HTML, not JSON. `ZoektAdapter.fetch_file_content()` parses `<pre>` tags and strips HTML to extract source code.
- MCP Streamable HTTP mode uses Starlette with `BearerTokenMiddleware` wrapping the session manager. The middleware must pass through `lifespan` events (non-http scope types).
- `SearchAdapter` ABC enables pluggable backends. New backends implement `search()`, `get_content()`, `health_check()`.

## Environment

- Python virtualenv: `/opt/pyenv/versions/dify_py3_env/bin/python3`
- Two PYTHONPATH roots: `src/` for SourcePilot, `mcp-server/` for MCP
- SourcePilot tests: `PYTHONPATH=src pytest tests/test_sourcepilot.py tests/test_api_contract.py tests/test_audit.py`
- MCP tests: `PYTHONPATH=mcp-server pytest tests/test_mcp_server.py`
- Key env vars: ZOEKT_URL, SOURCEPILOT_URL (default http://localhost:9000), MCP_AUTH_TOKEN
- Tests use `respx` to mock HTTP responses -- no real Zoekt server needed
- The project language is primarily Chinese (comments, docs, error messages, NL pipeline)

## Indexing Admin (audit-viewer extension)

Embedded in `audit-viewer/` (port 9100, `/repos` route). Manages AOSP indexing jobs for three backends.

### Two separate databases — DO NOT conflate

| DB file | Purpose | Writer |
|---|---|---|
| `audit-viewer/data/audit.db` | Audit log mirror (existing) | `audit_viewer.ingester` tails `audit.log` |
| `audit-viewer/data/indexing.db` | Indexing job metadata (new) | **Only** FastAPI process via HTTP callbacks |

`audit.db` is never written by the indexing subsystem. `indexing.db` is never read by the audit ingester.

### Script hooks

All three wrapper scripts call `python -m audit_viewer.indexing_cli` at job boundaries:

```bash
# Pattern in each wrapper script:
JOB_ID=$(python -m audit_viewer.indexing_cli start \
  --repo-path "$REPO" --backend "$BACKEND" --log-path "$LOG" \
  --internal-token "$INDEXING_INTERNAL_TOKEN")
trap 'python -m audit_viewer.indexing_cli finish --job-id "$JOB_ID" \
  --status fail --exit-code $? --internal-token "$INDEXING_INTERNAL_TOKEN"' EXIT
# ... run indexer ...
python -m audit_viewer.indexing_cli finish --job-id "$JOB_ID" --status success --exit-code 0 \
  --internal-token "$INDEXING_INTERNAL_TOKEN"
trap - EXIT
```

The CLI uses HTTP (`POST /api/indexing/jobs/internal-start` and `POST /api/indexing/jobs/{id}/finish`)
authenticated with `X-Indexing-Internal-Token`. SQLite is **never written directly** by the CLI.

### Internal token

Set `INDEXING_INTERNAL_TOKEN` in `.env` (same value used by wrapper scripts and audit-viewer):

```bash
INDEXING_INTERNAL_TOKEN=change-me-to-random-token
```

### Backend SDK isolation

`pymilvus` and `neo4j-driver` are **not** installed in audit-viewer's Python env.
Heavy operations (hard-delete, entity-count) run inside indexer containers:

```bash
docker compose --profile indexer run --rm dense-indexer python -m scripts.dense_drop REPO
docker compose --profile indexer run --rm graph-indexer python -m scripts.graph_drop REPO
```

### Commands

```bash
# Start audit-viewer (includes indexing admin)
scripts/run_audit_viewer.sh

# Run audit-viewer tests (includes indexing DB + API + e2e)
cd audit-viewer && PYTHONPATH=. pytest tests/ -v

# Verify no heavy deps in viewer venv
cd audit-viewer && PYTHONPATH=. pytest tests/test_no_heavy_deps.py -v

# Syntax-check wrapper scripts
bash -n scripts/build_dense_index_batch.sh scripts/build_graph_index.sh scripts/reindex.sh

# Dry-run a script (only fires CLI hooks, no docker)
INDEXING_DRY_RUN=1 bash scripts/build_graph_index.sh frameworks/base
```
