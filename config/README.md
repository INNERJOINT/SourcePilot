# config/ — Project Configuration

This directory holds the declarative configuration for multi-AOSP project indexing.

## projects.yaml

Defines all AOSP checkouts to index. Copy `projects.yaml.example` to `projects.yaml` and edit:

```yaml
projects:
  - name: ace                       # Project identifier (used everywhere)
    source_root: /mnt/code/ACE      # Absolute path to AOSP checkout
    # collection_name: aosp_code_ace  # Milvus collection (default: aosp_code_{name})
    # sub_project_globs:              # Sub-repos to index (default: frameworks/*, packages/*/*)
    #   - frameworks/*
    #   - packages/*/*
    #   - system/core/*

  - name: aosp15
    source_root: /mnt/code/AOSP15
```

### Fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `name` | Yes | — | Project identifier. Must match `[a-z0-9_]+`. Used as Neo4j `project` property and Milvus collection suffix. |
| `source_root` | Yes | — | Absolute path to the AOSP checkout directory. |
| `collection_name` | No | `aosp_code_{name}` | Override the Milvus collection name. |
| `sub_project_globs` | No | `frameworks/*`, `packages/*/*` | Glob patterns for sub-repo discovery in dense batch indexing. |

### Data Isolation

- **Milvus**: Each project gets its own collection (e.g. `aosp_code_ace`, `aosp_code_aosp15`). Dropping one collection does not affect others.
- **Neo4j**: All projects share one database (Community Edition). Isolation is property-based — every node carries a `project` field. Per-project reset deletes only nodes matching that project.

### Backward Compatibility

When `projects.yaml` does not exist, all scripts fall back to the `AOSP_SOURCE_ROOT` environment variable and behave as a single-project setup. No configuration file is required for existing single-project deployments.

## Usage

```bash
# Index all projects (dense + graph)
scripts/indexing/build_dense_index_batch.sh
scripts/indexing/build_graph_index_batch.sh

# Index a single project by name
scripts/indexing/build_graph_index.sh --project-name ace --source-root /mnt/code/ACE

# Dry run (no Docker, no real indexing)
INDEXING_DRY_RUN=1 scripts/indexing/build_dense_index_batch.sh

# Reset graph data for one project only
python scripts/indexing/build_graph_index.py --source-root /mnt/code/ACE --project-name ace --reset
```
