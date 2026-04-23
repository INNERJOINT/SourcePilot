# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

AOSP Code Search — a hybrid RAG code search system over Android Open Source Project sources. Three decoupled services communicate only via HTTP and a shared audit log:

- **SourcePilot** (`src/`, port 9000) — Starlette HTTP API: query gateway with NL classification, LLM rewriting, multi-path Zoekt retrieval, RRF fusion, and feature-based reranking.
- **MCP Server** (`mcp-server/`, port 8888) — Thin MCP protocol proxy (stdio or Streamable HTTP) forwarding to SourcePilot. No search logic here.
- **SP Cockpit** (`sp-cockpit/`, port 9100) — FastAPI + React SPA for browsing `audit.log` (read-only).

## Build & Run

Python runtime: `/opt/pyenv/versions/dify_py3_env/bin/python3`

```bash
scripts/run_all.sh              # Full stack: Zoekt → SourcePilot → MCP → SP Cockpit
scripts/run_sourcepilot.sh      # SourcePilot only
scripts/run_mcp.sh              # MCP (auto-starts SourcePilot)
scripts/run_sp_cockpit.sh       # SP Cockpit only
scripts/restart.sh              # Stop & restart (supports --only sp|mcp|av)
```

## Testing

```bash
# All SourcePilot tests (unit + integration + e2e)
PYTHONPATH=src pytest tests/unit/sourcepilot/ tests/integration/ tests/e2e/ -v

# MCP tests only
PYTHONPATH=mcp-server pytest tests/unit/mcp/ -v

# Single test file or test
PYTHONPATH=src pytest tests/unit/sourcepilot/test_gateway.py -v
PYTHONPATH=src pytest tests/unit/sourcepilot/test_gateway.py::test_exact_query -v

# SP Cockpit (separate project, run from its directory)
cd sp-cockpit && pytest tests/ -v
```

Tests mock Zoekt via `respx` — no live backend needed. `pytest.ini` config in `pyproject.toml` sets `pythonpath = ["src", "mcp-server"]`, so bare `pytest` works for most cases, but CI runs the two suites separately with explicit PYTHONPATH.

## Linting

```bash
ruff check src/ mcp-server/ tests/        # Python lint (rules: E, F, W, I, B, UP; line-length 100)
ruff check sp-cockpit/sp_cockpit          # SP Cockpit backend
shellcheck -x -S error scripts/*.sh       # Shell lint (CI gate)
```

## Two PYTHONPATH Roots

`src/` and `mcp-server/` are independent Python roots with **no shared imports** — they communicate only over HTTP. When writing imports or running tests, use the correct root:

- SourcePilot code: `PYTHONPATH=src` (imports like `from gateway.gateway import ...`, `from adapters.zoekt import ...`)
- MCP code: `PYTHONPATH=mcp-server` (imports like `from entry.handlers import ...`)

## Key Request Flow (SourcePilot)

`app.py` endpoint → `gateway.search()` → `classifier.py` (exact vs NL intent) → exact: `ZoektAdapter.search_zoekt()` directly; NL: LLM rewrite → parallel multi-path Zoekt queries → `fusion.py` RRF merge → `ranker.py` rerank → response.

## Architecture Details

- **Pluggable backends** via `SearchAdapter` ABC in `src/adapters/base.py` — methods: `search`, `get_content`, `health_check`.
- **Zoekt score normalization**: sigmoid `1/(1+exp(-0.1*(score-10)))` in `ZoektAdapter`.
- **Zoekt `/print`** returns HTML; `ZoektAdapter.fetch_file_content()` extracts `<pre>` and strips tags.
- **Non-blocking audit**: `QueueHandler` / `QueueListener`, started in the Starlette lifespan. Writes JSONL to `audit.log`.
- **`X-Trace-Id`** header propagates across services.
- **NL cache**: LRU + `concept_map` in `src/gateway/nl/cache.py`.

## Scripts Layout

Scripts are organized under `scripts/`:
- `share/` — shared bash libraries (`_common.sh` logging, `_env.sh` dotenv loader, `_infra.sh` service starters)
- `indexing/` — index build scripts (Zoekt, dense/Milvus, Neo4j graph)
- `testing/` — smoke tests (`smoke_queries.sh`), dense verification, hybrid eval

All scripts use `set -euo pipefail` and source `share/_common.sh`. Run any with `-h` for usage.

## Environment Variables

Key variables (see `.env.example` for full list):

| Variable | Default | Notes |
|---|---|---|
| `ZOEKT_URL` | `http://localhost:6070` | Zoekt webserver |
| `ZOEKT_INDEX_PATH` | — | Local index dir for native launch |
| `SOURCEPILOT_URL` | `http://localhost:9000` | Used by MCP layer |
| `NL_ENABLED` | `true` | NL rewrite pipeline toggle |
| `AUDIT_LOG_FILE` | `$PROJ_ROOT/audit.log` | SourcePilot audit output |
| `MCP_AUTH_TOKEN` | — | Bearer token for MCP Streamable HTTP mode |

## CI

GitHub Actions (`.github/workflows/test.yml`) runs three jobs:
1. **test** — SourcePilot + MCP pytest suites (mocks Zoekt, disables NL and audit)
2. **shell-lint** — `shellcheck -x -S error` + `bash -n` on all scripts
3. **sp-cockpit** — ruff + pytest + frontend typecheck/build
