# CI Integration

> **This file documents *suggested* CI integration. No CI pipeline currently
> exists in this repo.** Every YAML/Makefile snippet below is a recommendation,
> not a description of the current state. The repo today has no
> `.github/workflows/`, no top-level `Makefile` for tests, and no enforced
> coverage gates.

> Audience: **CI engineer** wiring this repo into GitHub Actions, GitLab CI,
> or another runner.

## Current state (descriptive)

- **Automation surface that exists today:**
  - `pytest` for the three test suites (see [pytest-suite.md](./pytest-suite.md))
  - `scripts/run_all.sh` to bring up Zoekt + SourcePilot + MCP locally
  - `scripts/smoke_queries.sh` and `scripts/test_dense.sh` for live smoke
  - `tests/test_mcp_endpoints.sh` for MCP streamable-HTTP smoke
  - `audit-viewer/pyproject.toml` declares `pytest`, `pytest-asyncio`, `httpx`,
    and `ruff` as `dev` extras
- **Automation surface that does not exist today:**
  - No GitHub Actions / GitLab CI / CircleCI configuration
  - No top-level `Makefile`
  - No coverage thresholds enforced
  - No flake-tracking infrastructure

The rest of this file is **suggested** wiring you can adopt as a follow-up PR.

## Suggested GitHub Actions template

A minimal three-job workflow that mirrors the canonical commands from
`CLAUDE.md`. Place at `.github/workflows/test.yml` (this file does not
exist today).

```yaml
name: tests

on:
  push:
    branches: [master, "feat/**"]
  pull_request:

jobs:
  sourcepilot:
    name: SourcePilot (unit + integration + e2e)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"
          cache: pip
      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest pytest-asyncio respx httpx pytest-cov
      - name: Run pytest
        run: |
          PYTHONPATH=src pytest tests/unit/sourcepilot/ tests/integration/ tests/e2e/ \
            -v --cov=src --cov-report=xml --cov-report=term-missing
      - name: Upload coverage
        uses: actions/upload-artifact@v4
        with:
          name: coverage-sourcepilot
          path: coverage.xml

  mcp:
    name: MCP unit
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"
          cache: pip
      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r mcp-server/requirements.txt
          pip install pytest pytest-asyncio respx httpx
      - name: Run pytest
        run: PYTHONPATH=mcp-server pytest tests/unit/mcp/ -v

  audit-viewer:
    name: Audit Viewer
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: audit-viewer
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"
          cache: pip
      - name: Install (incl. dev extras)
        run: pip install -e '.[dev]'
      - name: Run pytest
        run: pytest -v
```

### Notes on the template

- **Three jobs, three pip installs.** The two PYTHONPATH roots and the
  audit-viewer `pyproject.toml` cannot share a single venv because their
  dependency sets differ. Three separate jobs is the simplest faithful
  mapping.
- **No live Zoekt / Milvus.** The pytest suites are fully mocked (respx +
  AsyncMock), so no service container is needed. The smoke scripts (which
  *do* need live backends) are NOT in this template — they belong in a
  separate manually-triggered or release workflow.
- **`pip cache`** keyed by `requirements.txt` hash (default behavior of
  `actions/setup-python`'s `cache: pip`).

## Suggested smoke workflow (manual / release)

Smoke scripts need a live SourcePilot + Zoekt + Milvus + Embedding +
audit-viewer. This is impractical for every PR; run on demand or before tag.

```yaml
name: smoke

on:
  workflow_dispatch:
  push:
    tags: ["v*"]

jobs:
  smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Bring up stack
        run: |
          cp .env.example .env
          # ... project-specific live-backend bootstrap
          scripts/run_all.sh &
          sleep 30          # wait for SourcePilot health
      - name: Smoke queries
        run: bash scripts/smoke_queries.sh
      - name: Upload audit.log on failure
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: audit-log
          path: |
            audit.log
            audit-viewer/data/audit.db
```

`scripts/run_all.sh` is project-specific (it depends on access to a Zoekt
mirror and a Milvus cluster); the snippet above shows the *shape* of the
workflow, not a turnkey solution.

## Suggested Makefile targets

A small `Makefile` at the repo root would make it easy to type `make test-unit`
locally and invoke the same commands from CI. (No `Makefile` exists today.)

```makefile
.PHONY: test test-unit test-integration test-e2e test-mcp test-audit-viewer smoke cov

test: test-unit test-integration test-e2e test-mcp test-audit-viewer

test-unit:
	PYTHONPATH=src pytest tests/unit/sourcepilot/ -v

test-integration:
	PYTHONPATH=src pytest tests/integration/ -v

test-e2e:
	PYTHONPATH=src pytest tests/e2e/ -v

test-mcp:
	PYTHONPATH=mcp-server pytest tests/unit/mcp/ -v

test-audit-viewer:
	cd audit-viewer && pytest -v

cov:
	PYTHONPATH=src pytest tests/unit/sourcepilot/ tests/integration/ tests/e2e/ \
		--cov=src --cov-report=term-missing --cov-report=html

smoke:
	bash scripts/smoke_queries.sh
```

## Coverage report generation (runnable today)

Coverage already works locally without any new tooling — install
`pytest-cov` and add `--cov`:

```bash
pip install pytest-cov
PYTHONPATH=src pytest tests/unit/sourcepilot/ tests/integration/ tests/e2e/ \
  --cov=src --cov-report=term-missing --cov-report=html
# HTML report lands in htmlcov/
```

For MCP:

```bash
PYTHONPATH=mcp-server pytest tests/unit/mcp/ \
  --cov=mcp-server --cov-report=term-missing
```

For audit-viewer:

```bash
(cd audit-viewer && pytest --cov=audit_viewer --cov-report=term-missing)
```

These commands work today; you do not need to wait for the suggested CI to be
in place.

## Suggested pip caching

`actions/setup-python@v5` with `cache: pip` (shown above) hashes the
discovered `requirements*.txt` files. If you add a `requirements-dev.txt`
later, pass `cache-dependency-path` explicitly so the cache key tracks both
files.

## Suggested artifact uploads

When the smoke workflow fails, the most useful artifacts are:

- `audit.log` (raw JSONL the smoke script asserts against)
- `audit-viewer/data/audit.db` (SQLite the smoke script polled)
- The full `pytest` output (already captured in the job log)

The smoke workflow snippet above shows the `actions/upload-artifact@v4`
pattern.

## Local-vs-CI differences

| Aspect | Local (`pytest`) | Suggested CI |
|--------|------------------|--------------|
| PYTHONPATH | Set inline per command | Set inline per job step |
| Live backends | Not needed for `pytest`; needed for smoke scripts | Not needed for the `tests` workflow; needed for the separate `smoke` workflow |
| Audit DB | Real `audit-viewer/data/audit.db` if running locally | Tempfile fixtures only (audit-viewer test); not relevant for SourcePilot/MCP unit jobs |
| Coverage | Optional (`--cov`) | Recommended on every run, uploaded as artifact |
| Cache | OS pip cache | GitHub Actions pip cache |

## See also

- [pytest-suite.md](./pytest-suite.md) — canonical run commands these jobs mirror
- [smoke-scripts.md](./smoke-scripts.md) — what the suggested smoke workflow drives
- [quality-gates.md](./quality-gates.md) — suggested coverage thresholds and review checklist
