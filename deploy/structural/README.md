# Structural Deploy — Neo4j Graph Database

Docker single-node deployment providing the Neo4j backend for SourcePilot's structural retrieval
feature (Structural Lane).

## Quick Start

```bash
cd deploy/structural

# 1. Start Neo4j (first-time image pull may take a moment)
docker compose up -d

# 2. Verify service health
docker compose ps
docker compose logs neo4j | tail -20

# 3. Open Neo4j Browser (optional)
open http://localhost:7474
# Username: neo4j  Password: sourcepilot
```

## Service Components

| Service | Port        | Description                        |
|---------|-------------|------------------------------------|
| Neo4j   | 7474 (HTTP) | Neo4j Browser / REST API           |
| Neo4j   | 7687 (Bolt) | Bolt protocol (driver connections) |

## Connection Details

Matching the `.env` defaults:

```
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=sourcepilot
```

## Memory Notes

The default configuration is suitable for development/testing environments:

- Heap initial: 512M, max: 2G
- Page Cache: 512M
- **Recommended host memory: 4GB+**
- Indexing the `frameworks/base` subset (`build_structural_index.py`) consumes approximately 1–2GB Neo4j heap

To adjust, modify the `NEO4J_server_memory_*` variables in `docker-compose.yml` and restart the service.

## Building the Graph Index

Since 2026-04, index builds are performed via the containerized `structural-indexer` service
(the `indexer` profile in the same Compose file):

```bash
# Prerequisites: neo4j healthy; AOSP source mounted into container /src via $AOSP_SOURCE_ROOT
cd /opt/aosp/aosp_project2/Dify
AOSP_SOURCE_ROOT=/opt/aosp/aosp_project ./scripts/build_structural_index.sh \
    --source-root /opt/aosp/aosp_project/frameworks/base \
    --languages java,cpp,python \
    --max-files 500
```

The wrapper translates host paths to `/src/<subpath>` before invoking:

```bash
docker compose -f deploy/docker-compose.yml --profile indexer \
    run --rm structural-indexer \
    --source-root /src/frameworks/base \
    --languages java
```

By default `docker compose up -d` starts only `neo4j`; the `indexer` profile is a one-shot job
triggered on demand that exits after completion. `neo4j` / `tree-sitter-*` no longer need to be
installed on the host.

## Backup

```bash
# Export a database snapshot
docker compose exec neo4j neo4j-admin database dump neo4j --to-path=/backups
```

## Rebuilding the Index

```bash
# 1. Stop services and clear data volumes
docker compose down -v

# 2. Restart
docker compose up -d

# 3. Wait for health checks to pass, then re-index
cd /opt/aosp/aosp_project2/Dify
AOSP_SOURCE_ROOT=/opt/aosp/aosp_project ./scripts/build_structural_index.sh \
    --source-root /opt/aosp/aosp_project/frameworks/base --languages java,cpp,python
```

## APOC Plugin

APOC is automatically installed via `NEO4J_PLUGINS='["apoc"]'`, enabling graph algorithms,
bulk imports, and other advanced operations.
