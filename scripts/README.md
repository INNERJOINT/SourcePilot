# scripts/

Shell scripts for running, testing, and managing the AOSP Code Search stack.

## Directory Structure

```
scripts/
├── run_all.sh / run_sourcepilot.sh / run_mcp.sh / run_sp_cockpit.sh / restart.sh
├── migrate_to_sp_cockpit.sh
├── share/          — shared libraries (sourced, not executed directly)
├── indexing/       — index build & maintenance scripts
└── testing/        — smoke tests, verification, evaluation
```

## Conventions

- Shebang: `#!/usr/bin/env bash` + `set -euo pipefail` (exception: `build_dense_index_batch.sh` omits `-e` for batch-continue semantics)
- All scripts source `share/_common.sh` for shared logging (`log`, `info`, `warn`, `die`) and `--help` via `_common_parse_help`
- Run any script with `-h` or `--help` to see its usage header

## Inventory

### Run / Restart (scripts/)

| Script | Purpose |
|---|---|
| `run_all.sh` | Start full stack (zoekt + SourcePilot + MCP + sp-cockpit) |
| `run_sourcepilot.sh` | Start SourcePilot standalone |
| `run_mcp.sh` | Start MCP server (auto-starts SourcePilot as subprocess) |
| `run_sp_cockpit.sh` | Start SourcePilot Cockpit (FastAPI + React SPA) |
| `restart.sh` | Stop & restart services (supports `--only sp\|mcp\|av`) |
| `migrate_to_sp_cockpit.sh` | One-time migration from audit-viewer to sp-cockpit |

### Shared Libraries (share/)

| Script | Purpose |
|---|---|
| `_common.sh` | Shared library: logging, color, `--help` extraction |
| `_env.sh` | Loads `.env` into environment |
| `_infra.sh` | Reusable infrastructure startup functions (zoekt, dense, graph, cockpit) |
| `_start_sourcepilot.sh` | SourcePilot uvicorn launcher |

### Indexing (indexing/)

| Script | Purpose |
|---|---|
| `_indexing_lib.sh` | Shared helpers for indexing scripts (CLI hooks, dry-run) |
| `build_dense_index_batch.sh` | Batch-build dense vector index for AOSP repos |
| `build_dense_index.py` | Dense index builder (Python) |
| `build_graph_index.sh` | Build Neo4j graph index for a single repo |
| `build_graph_index.py` | Graph index builder (Python) |
| `reindex.sh` | Orchestrate full reindex (zoekt + dense + graph) |
| `zoekt_delete_shard.sh` | Delete zoekt index shards for a repo |

### Testing (testing/)

| Script | Purpose |
|---|---|
| `smoke_queries.sh` | Smoke-test search queries against running SourcePilot |
| `test_dense.sh` | Test dense (Milvus) search pipeline |
| `verify.sh` | Unified verification (`graphrag-audit` / `indexer-containers`) |
| `eval_hybrid.py` | Hybrid search evaluation (Python) |

## CI

The `shell-lint` job in `.github/workflows/test.yml` runs `shellcheck -x -S error` and `bash -n` on all scripts.
