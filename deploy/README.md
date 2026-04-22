# Deploy

Single source of truth for the runtime stack.

```
deploy/
├── docker-compose.yml          # Merged compose (this directory)
├── dense/                      # Milvus + embedding-server + dense-indexer
│   ├── embedding-server/
│   ├── indexer/Dockerfile
│   ├── scripts/
│   ├── MODEL_VERSION
│   └── README.md
├── graph/                      # Neo4j + graph-indexer
│   ├── indexer/Dockerfile
│   └── README.md
└── zoekt/                      # zoekt-webserver / zoekt-indexserver image
    └── Dockerfile
```

## Quick start

```bash
# All non-indexer services
docker compose -f deploy/docker-compose.yml up -d
# or, equivalently, via the root shim:
docker compose up -d

# One-shot indexer runs (profile-gated)
docker compose -f deploy/docker-compose.yml --profile indexer run --rm dense-indexer ...
docker compose -f deploy/docker-compose.yml --profile indexer run --rm graph-indexer ...
```

## Migration history

This tree replaces the previous `dense-deploy/`, `graph-deploy/`, and
`zoekt-deploy/` directories. Wrapper scripts (`scripts/run_all.sh`,
`scripts/build_dense_index_batch.sh`, `scripts/build_graph_index.sh`) and
`scripts/verify_indexer_containers.sh` were updated to point at the new layout.

## Architecture Decision Records

### ADR #1 — Single merged compose

All services live in `deploy/docker-compose.yml`. The three former sub-stacks
were already on the same `sourcepilot-net` network and shared environment
flow; splitting them across files was an organisational artefact, not an
isolation boundary.

### ADR #2 — Root `docker-compose.yml` is a thin shim

The root `docker-compose.yml` is a 2-line `include:` shim. Cost is two
lines; benefit is preserving every developer's `docker compose up -d` muscle
memory and any CI that assumes a root compose. Delete-and-require-`-f` was
considered and rejected as user-hostile with no compensating benefit.

### ADR #3 — Pinned volume names without `external: true`

`etcd_data`, `minio_data`, and `milvus_data` carry the legacy
`dense-deploy_*` prefix via explicit `name:` keys. They are NOT marked
`external: true`:

- On hosts that already have the volumes (production, dev workstations
  pre-migration), compose binds to the existing volumes by name → no data
  movement, no risk of orphaning Milvus state.
- On fresh hosts (CI, new dev boxes), compose creates the volumes on first
  `up` instead of failing with "volume not found", which is what
  `external: true` would do.

Renaming the volumes was rejected because it required a manual
`docker volume rename` migration on every host with no compensating benefit.

### ADR #4 — Neo4j joins `sourcepilot-net`

Previously, `graph-deploy/docker-compose.yml` defined no `networks:` block,
which placed Neo4j on Compose's default project bridge. After the merge,
Neo4j and `graph-indexer` join `sourcepilot-net` so any service in the merged
compose can reach Neo4j by hostname (`neo4j:7687`). This was implicit
isolation, not deliberate; auth (`NEO4J_AUTH=neo4j/sourcepilot`) remains the
access-control mechanism.

### ADR #5 — Compose project name pinned to `dify`

The compose file declares `name: dify` at the top level. Without this,
direct invocation (`docker compose -f deploy/docker-compose.yml ...`) would
use the directory-derived project name `deploy`, while the root shim path
would use `dify`. The two would create parallel `*_sourcepilot-net` networks
and parallel volume copies, silently diverging. Pinning the project name
guarantees a single canonical set of resources regardless of invocation.
