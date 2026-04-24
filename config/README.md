# config/ — Project Configuration

This directory contains the declarative project registry for multi-AOSP indexing.

## Canonical parser

Use `scripts/indexing/project_config.py` for sparse, dense, and structural scope resolution:

```bash
python3 scripts/indexing/project_config.py --format json --backend sparse [--project ace] [--config /path/projects.yaml]
python3 scripts/indexing/project_config.py --format json --backend dense [--project ace] [--config /path/projects.yaml]
python3 scripts/indexing/project_config.py --format json --backend structural [--project ace] [--config /path/projects.yaml]
```

Config precedence:

1. `--config`
2. `PROJECTS_CONFIG_PATH`
3. `<repo>/config/projects.yaml`
4. fallback single project from `AOSP_SOURCE_ROOT`

`_project_config.py` remains Zoekt-only legacy shell glue. Dense and structural batch scripts should use `project_config.py` for scope decisions.

## `projects.yaml`

Copy `config/projects.yaml.example` to `config/projects.yaml` and edit each project entry.

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `name` | Yes | — | Project identifier. Must match `[a-z0-9_]+`. Used as the project key and dense collection suffix. |
| `source_root` | Yes | — | Absolute path to the AOSP checkout directory. |
| `repo_path` | No | `source_root/.repo` | Path to the repo metadata directory. |
| `index_dir` | No | `source_root/.repo/.zoekt` | Path to the Zoekt index directory. Prefer `sparse_index.index_dir`. |
| `zoekt_url` | No | `http://localhost:6070` | Zoekt webserver URL. Prefer `sparse_index.zoekt_url`. |
| `collection_name` | No | `aosp_code_{name}` | Dense fallback collection name. |
| `sub_project_globs` | No | `[]` | Legacy shared scope. Do not combine with backend-specific non-empty `include` lists. |
| `sparse_index` | No | `{}` | Sparse (Zoekt) backend override block. |
| `dense_index` | No | `{}` | Dense backend override block. |
| `structural_index` | No | `{}` | Structural backend override block. |

### Backend section schema

All three backend sections (`sparse_index`, `dense_index`, `structural_index`) accept:

| Key | Meaning |
|-----|---------|
| `enabled` | Optional boolean. Omitted means `true`. `false` disables that backend for the project. |
| `include` | Optional list of relative glob patterns under `source_root`. `include: []` disables that backend explicitly. |

Additionally, `sparse_index` accepts:

| Key | Meaning |
|-----|---------|
| `index_dir` | Overrides top-level `index_dir`. Path to Zoekt index directory. |
| `zoekt_url` | Overrides top-level `zoekt_url`. Zoekt webserver URL. |

And `dense_index` accepts:

| Key | Meaning |
|-----|---------|
| `collection_name` | Overrides the top-level `collection_name` for dense indexing. |

Include patterns are validated as relative paths under `source_root`:

- absolute paths are rejected
- empty or whitespace-only patterns are rejected
- `.` / `..` path segments are rejected
- newline and NUL characters are rejected
- matches must resolve to directories under `source_root`
- duplicate resolved `source_dir` or `repo_name` entries are rejected

### Dense collection precedence

When dense indexing resolves a collection name, precedence is:

1. `dense_index.collection_name`
2. top-level `collection_name`
3. `aosp_code_{name}`

### Structural identity and display

Structural indexing stores source identity as `(project, repo, path)`.

- `repo` is the repo-relative identity, not the project name.
- `path` is relative to `repo`.
- Structural output should render as `repo/path`, not `project/repo/path`.

## Data isolation

- **Dense**: each project gets its own collection.
- **Structural**: every node/edge should carry project-aware identity so projects do not collide.
- **Zoekt**: each project keeps its own `repo_path` and `index_dir`.

## Usage

```bash
# Render backend config JSON
python3 scripts/indexing/project_config.py --format json --backend sparse
python3 scripts/indexing/project_config.py --format json --backend dense
python3 scripts/indexing/project_config.py --format json --backend structural --project ace

# Batch indexing
scripts/indexing/build_dense_index_batch.sh
scripts/indexing/build_structural_index_batch.sh

# Dry run (no Docker, no real indexing)
INDEXING_DRY_RUN=1 scripts/indexing/build_dense_index_batch.sh

# Reset structural data for one project only
python scripts/indexing/build_structural_index.py --source-root /mnt/code/ACE --project-name ace --reset
```

