# Testing — Documentation Index

> Audience: **new contributors**. Read this first; jump to a sibling file when you have a specific task.

This directory documents the test framework that ships with the repo today.
It covers three Python services and the live smoke scripts that exercise them
end-to-end.

| Service | Source dir | Test root | PYTHONPATH |
|---------|-----------|-----------|------------|
| SourcePilot (search engine) | `src/` | `tests/unit/sourcepilot/`, `tests/integration/`, `tests/e2e/` | `src` |
| MCP Access Layer | `mcp-server/` | `tests/unit/mcp/` | `mcp-server` |
| SourcePilot Cockpit (FastAPI + SPA) | `sp-cockpit/sp_cockpit/` | `sp-cockpit/tests/` | (its own pyproject) |

## Doc Index

| File | Audience | What you get |
|------|----------|--------------|
| [architecture.md](./architecture.md) | architect, new contributor | Test pyramid, layering, request-flow mermaid diagrams |
| [pytest-suite.md](./pytest-suite.md) | layer author | Per-directory walkthrough, run commands, "add a test" recipes |
| [smoke-scripts.md](./smoke-scripts.md) | live-system tester | `scripts/smoke_queries.sh`, `scripts/test_dense.sh`, `tests/test_mcp_endpoints.sh` deep-dive |
| [fixtures.md](./fixtures.md) | test author | `conftest.py` hierarchy, mock fixtures, respx & AsyncMock patterns |
| [ci.md](./ci.md) | CI engineer | **Suggested** GitHub Actions / Makefile templates (no CI exists today) |
| [quality-gates.md](./quality-gates.md) | maintainer / reviewer | **Suggested** coverage gates, flake policy, review checklist |
| [troubleshooting.md](./troubleshooting.md) | debugger | Symptom → cause → fix table for common failures |

## 5-Minute Quickstart

From a clean checkout:

```bash
# 1. Set up the Python environment used by the project
#    (the canonical interpreter per CLAUDE.md is /opt/pyenv/versions/dify_py3_env/bin/python3,
#     but any Python ≥ 3.10 venv with pip works for tests)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # SourcePilot deps
pip install -r mcp-server/requirements.txt
pip install pytest pytest-asyncio respx httpx

# 2. Run SourcePilot unit + integration + e2e (uses respx mocks; no live backend needed)
PYTHONPATH=src pytest tests/unit/sourcepilot/ tests/integration/ tests/e2e/ -v

# 3. Run MCP unit tests
PYTHONPATH=mcp-server pytest tests/unit/mcp/ -v

# 4. Run sp-cockpit tests (separate project)
(cd sp-cockpit && pip install -e '.[dev]' && pytest -v)
```

A green run looks roughly like `=== N passed in S seconds ===` per suite.
The repo exposes several hundred test cases across the three services
(`grep -rn '^def test_\|^async def test_\|^    def test_\|^    async def test_' tests/ sp-cockpit/tests/ | wc -l`).

## Conventions

- **Two PYTHONPATH roots.** SourcePilot tests run with `PYTHONPATH=src`; MCP
  tests run with `PYTHONPATH=mcp-server`. The two services intentionally do
  not share Python imports — they communicate over HTTP. Audit-viewer is a
  third, self-contained project with its own `pyproject.toml`.
- **No live backend by default.** Pytest suites mock Zoekt, Milvus, the
  SourcePilot HTTP API, and LLM responses via `respx`, `unittest.mock`, and
  static fixture data. Live-backend coverage lives in the smoke scripts under
  `scripts/` (see [smoke-scripts.md](./smoke-scripts.md)).
- **Audit-log is asserted, not just produced.** Audit emission has a unit test
  (`tests/unit/sourcepilot/observability/test_audit.py`) and a live check
  (`scripts/smoke_queries.sh` polls `sp-cockpit/data/audit.db`). When you
  add a new pipeline stage, add an audit assertion too — see
  [quality-gates.md](./quality-gates.md).
- **Doc language is English** (consistent with the top-level README).
  In-code Chinese comments and Chinese error strings are kept verbatim — do
  not translate them in tests.

## When to read which file

- "I want to run the tests" → here, then [pytest-suite.md](./pytest-suite.md).
- "I want to understand how the tests are layered" → [architecture.md](./architecture.md).
- "I want to add a unit/integration/e2e test" → [pytest-suite.md](./pytest-suite.md) → [fixtures.md](./fixtures.md).
- "I want to verify a release against a live SourcePilot" → [smoke-scripts.md](./smoke-scripts.md).
- "I want to wire tests into CI" → [ci.md](./ci.md).
- "Something is failing and I do not know why" → [troubleshooting.md](./troubleshooting.md).

## See also

- Top-level [`README.md`](../../README.md) — project overview
- [`CLAUDE.md`](../../CLAUDE.md) — canonical commands and architecture notes
- [`sp-cockpit/README.md`](../../sp-cockpit/README.md) — sp-cockpit service
