# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

AOSP Code Search — a hybrid RAG code search system over Android Open Source Project sources. Three decoupled services communicate only via HTTP and a shared audit log:

- **SourcePilot** (`src/`, port 9000) — Starlette HTTP API: query gateway with NL classification, LLM rewriting, multi-path Zoekt retrieval, RRF fusion, and feature-based reranking.
- **MCP Server** (`mcp-server/`, port 8888) — Thin MCP protocol proxy (stdio or Streamable HTTP) forwarding to SourcePilot. No search logic here.
- **SP Cockpit** (`sp-cockpit/`, port 9100) — FastAPI + React SPA for browsing `audit.log` (read-only).

## Build & Run

Infrastructure (Zoekt, Qdrant, Neo4j) runs as Docker containers (Compose project `sourcepilot`, config in `deploy/docker-compose.yml`). Application services (SourcePilot, MCP, SP Cockpit) run as **bare processes** via `run_all_dev.sh` for fast iteration — no image rebuild needed after code changes.

Python runtime: `/opt/pyenv/versions/dify_py3_env/bin/python3`

```bash
scripts/run_all_dev.sh          # Dev mode: infra via Docker, apps as bare processes
scripts/run_all.sh              # Full stack (all Docker): Zoekt → SourcePilot → MCP → SP Cockpit
scripts/run_sourcepilot.sh      # SourcePilot only
scripts/run_mcp.sh              # MCP (auto-starts SourcePilot)
scripts/run_sp_cockpit.sh       # SP Cockpit only
scripts/restart.sh              # Stop & restart (supports --only sp|mcp|av)
```

To inspect or debug running services, **first check the local bare process** (stdout/stderr in the terminal running `run_all_dev.sh`). If the service is not running locally, fall back to Docker:

```bash
docker compose ps                           # List running containers
docker compose logs -f sourcepilot-gateway  # Tail logs (fallback when service runs in Docker)
docker compose exec sourcepilot-gateway sh  # Shell into container
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
- **Project routing**: `config/projects.yaml` defines one or more AOSP checkouts (each with its own Zoekt index and dense collection). All gateway/HTTP/MCP entry points accept a `project` field; in multi-project deployments it is **required** (server returns 400 with `{"error": "project required in multi-project deployment", "available": [...]}`), in single-project deployments it is optional. The MCP layer exposes a `list_projects` tool for client-side discovery.

## Scripts Layout

Scripts are organized under `scripts/`:
- `share/` — shared bash libraries (`_common.sh` logging, `_env.sh` dotenv loader, `_infra.sh` service starters)
- `indexing/` — index build scripts (Zoekt, dense/Qdrant, Neo4j structural)
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
| `CODE_EMBEDDING_MODEL` | `nomic-ai/CodeRankEmbed` | Embedding-server-side; selects which code model to load. Valid: `nomic-ai/CodeRankEmbed`, `microsoft/unixcoder-base`. `bge-base-zh-v1.5` always loads regardless. |

## Switching the Dense Code-Embedding Model

`CODE_EMBEDDING_MODEL` selects the active code model **at embedding-server boot**. Switching is not a hot operation — it requires an image rebuild (the model is baked in by `download_models.py` at `docker build` time) AND a project-config change. Skipping any step silently corrupts the vector store.

**Compose env-file gotcha:** `.env` lives in the repo root, but `docker compose -f deploy/docker-compose.yml` defaults its project directory to `deploy/`, so it looks for `deploy/.env` and silently uses the in-compose `${VAR:-default}` fallbacks instead. **Always pass `--env-file` explicitly** (or run from repo root with `--project-directory .`). Symptom of getting this wrong: `docker compose ... config | grep CODE_EMBEDDING_MODEL` prints the default, and `/health` reports the wrong `active_code_model` despite a correct `.env`.

**Required steps in order** (run from repo root `/mnt/code/SourcePilot`):

1. **Edit `.env`** — set `CODE_EMBEDDING_MODEL=microsoft/unixcoder-base` (or back to `nomic-ai/CodeRankEmbed`).
2. **Rebuild the embedding-server image** — `docker compose --env-file .env -f deploy/docker-compose.yml build dense-index-coderankembed` (~+5min, +500MB the first time UniXcoder is added).
3. **Restart with force-recreate** — `docker compose --env-file .env -f deploy/docker-compose.yml up -d --force-recreate dense-index-coderankembed`. Without `--force-recreate`, env changes may not be applied even after rebuild.
4. **Verify** — first `docker compose --env-file .env -f deploy/docker-compose.yml config | grep CODE_EMBEDDING_MODEL` (should print the new value, not the fallback). Then `curl -s http://localhost:9088/health | jq` must show `"active_code_model": "microsoft/unixcoder-base"`.
5. **Edit `config/projects.yaml`** for each affected project: set `dense_index.embedding_model` to match AND change `dense_index.collection_name` to a **new** name (convention: append `_unixcoder`, e.g. `aosp_code_ace_dense_unixcoder`). The indexer pre-flight (`_preflight_check_active_code_model` in `scripts/indexing/dense/build_dense_index.py`) aborts with an actionable error if server and project disagree.
6. **Run the indexer** — `./scripts/indexing/dense/build_dense_index_batch.sh`.

**Vector-store contamination rule:** Qdrant collections are dimension-only (768 for both models), so writing UniXcoder vectors into a CodeRank collection **succeeds silently** but destroys recall. **Never reuse the same `collection_name` across models.** Old collection can stay (for A/B comparison) or be dropped: `curl -X DELETE http://localhost:6333/collections/<old_name>`.

## CI

GitHub Actions (`.github/workflows/test.yml`) runs three jobs:
1. **test** — SourcePilot + MCP pytest suites (mocks Zoekt, disables NL and audit)
2. **shell-lint** — `shellcheck -x -S error` + `bash -n` on all scripts
3. **sp-cockpit** — ruff + pytest + frontend typecheck/build
