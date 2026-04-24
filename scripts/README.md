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
| `_infra.sh` | Reusable infrastructure startup functions (zoekt, dense, structural, cockpit) |
| `_start_sourcepilot.sh` | SourcePilot uvicorn launcher |

### Indexing (indexing/)

| Script | Purpose |
|---|---|
| `_indexing_lib.sh` | Shared helpers for indexing scripts (CLI hooks, dry-run) |
| `sparse/reindex.sh` | Orchestrate full reindex (zoekt) |
| `sparse/reindex_docker.sh` | Docker-based Zoekt indexing for repo-managed projects |
| `sparse/zoekt_delete_shard.sh` | Delete zoekt index shards for a repo |
| `dense/build_dense_index_batch.sh` | Batch-build dense vector index for AOSP repos |
| `dense/build_dense_index.py` | Dense index builder (Python) |
| `structural/build_structural_index.sh` | Build Neo4j structural index for a single repo |
| `structural/build_structural_index.py` | Structural index builder (Python) |
| `structural/build_structural_index_batch.sh` | Batch structural index builder |
| `feishu/build_feishu_index.py` | Feishu knowledge base vector index builder |

### Testing (testing/)

| Script | Purpose |
|---|---|
| `smoke_queries.sh` | Smoke-test search queries against running SourcePilot |
| `test_dense.sh` | Test dense (Milvus) search pipeline |
| `verify.sh` | Unified verification (`structural-audit` / `indexer-containers`) |
| `eval_hybrid.py` | Hybrid search evaluation (Python) |

## Sparse Index (Zoekt via Docker)

For AOSP projects managed by the `repo` tool, `reindex_docker.sh` builds Zoekt shards by iterating every sub-project in `.repo/project.list` and running `zoekt-git-index` inside a Docker container.

### Usage

```bash
# Index a single AOSP project (defined in config/projects.yaml)
scripts/indexing/sparse/reindex_docker.sh --project t2

# Index all configured projects
scripts/indexing/sparse/reindex_docker.sh --all

# Increase parallelism (default 4 concurrent containers)
scripts/indexing/sparse/reindex_docker.sh --project t2 --parallelism 8

# Dry run — print docker commands without executing
INDEXING_DRY_RUN=1 scripts/indexing/sparse/reindex_docker.sh --project t2
```

### How it works

1. Reads project config (source root, index dir) from `config/projects.yaml` via `_project_config.py`
2. Reads `.repo/project.list` — one sub-project path per line (e.g. `alps/frameworks/base`)
3. For each sub-project, runs a Docker container:
   ```bash
   docker run --rm \
     -v <source_root>:/src:ro \
     -v <index_dir>:/idx \
     dify-sparse-index-zoekt:latest \
     zoekt-git-index -index /idx /src/<sub_path>
   ```
4. Skips entries without a valid `.git` directory
5. Runs up to `--parallelism N` containers concurrently (default 4)
6. Reports summary: total indexed, failed count, elapsed time

### Environment

| Variable | Default | Purpose |
|---|---|---|
| `ZOEKT_DOCKER_IMAGE` | `dify-sparse-index-zoekt:latest` | Docker image containing `zoekt-git-index` |
| `INDEXING_DRY_RUN` | `0` | Set to `1` to print commands without executing |
| `PROJECTS_CONFIG_PATH` | `config/projects.yaml` | Override project config path |

### Notes

- Re-running overwrites existing shards (full rebuild, no incremental mode)
- The Docker image is built from `deploy/sparse/zoekt/`
- Each sub-project produces one or more `.zoekt` shard files in the index directory

## CI

The `shell-lint` job in `.github/workflows/test.yml` runs `shellcheck -x -S error` and `bash -n` on all scripts.
