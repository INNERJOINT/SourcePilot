# Quality Gates

> **This file documents *suggested* quality gates and review practices. No
> coverage thresholds, flake-tracking infra, or PR templates currently exist
> in this repo.** Every numeric threshold or checklist below is a
> recommendation — adopting any of them is a follow-up change. The one
> section that *is* descriptive (not suggested) is **Audit-log assertion
> patterns**, which documents an idiom already in the codebase.

> Audience: **maintainer / reviewer**.

## Current state (descriptive)

- No coverage thresholds enforced anywhere (no `pytest --cov-fail-under`, no
  CI gate, no commit hook).
- Coverage is **opt-in** via `pytest --cov` (see [ci.md](./ci.md#coverage-report-generation-runnable-today)).
- Smoke scripts (`scripts/smoke_queries.sh`, `scripts/test_dense.sh`,
  `tests/test_mcp_endpoints.sh`) return non-zero on failure but are not wired
  into any CI job.
- No flake-tracking, no quarantine markers, no `pytest.ini` / `pyproject.toml`
  flake plugin (audit-viewer's `pyproject.toml` only configures
  `pytest-asyncio` mode).
- No PR template under `.github/`.
- No new-test review checklist.
- No coverage-gap dashboard. Known gaps from the brownfield exploration:
  - Fusion ranking math (RRF merge correctness) has no dedicated test
  - No live-backend integration tests run under pytest

## Suggested coverage thresholds

Numeric targets to introduce in a follow-up PR (not enforced today). Pick
realistic floors based on the *current* coverage of each suite — measure
first, then set the gate slightly below current to avoid breaking the next
PR.

| Suite | Suggested floor | Rationale |
|-------|----------------|-----------|
| SourcePilot unit (`tests/unit/sourcepilot/`) | ≥ 80 % line | Pure-Python modules with mockable boundaries; the bar should be high |
| SourcePilot integration (`tests/integration/`) | (not measured separately; rolled into SourcePilot total) | Integration adds realism, not coverage breadth |
| MCP unit (`tests/unit/mcp/`) | ≥ 75 % line | Thin proxy layer; some lines are protocol boilerplate that's hard to cover |
| Audit Viewer (`audit-viewer/tests/`) | ≥ 80 % line | Self-contained service with clear boundaries |

Enforcement, when adopted, would look like:

```bash
PYTHONPATH=src pytest tests/unit/sourcepilot/ tests/integration/ tests/e2e/ \
  --cov=src --cov-fail-under=80
```

## Suggested flake handling policy

A consistent policy is more useful than any specific tooling. Suggested:

1. **First failure on a PR**: re-run via `pytest --lf` (re-run only failed
   tests) — if it passes, leave a comment on the PR linking the run; do
   **not** quarantine.
2. **Second failure of the same test on the same PR**: open an issue
   referencing the trace, then mark the test with
   `@pytest.mark.flaky(reruns=2)` (requires `pytest-rerunfailures`, not
   currently a dependency).
3. **Flake quarantine**: `@pytest.mark.skip(reason="flaky; see #NNN")` —
   *only* with an issue number; no naked skips.
4. **Flake budget**: no more than 5 quarantined tests at any time. If the
   budget is exceeded, the next quarantine PR must also remove an existing
   one.

## Suggested new-test review checklist

When reviewing a PR that adds tests, suggested questions:

- [ ] **Path**: does the test live in the right tier (unit/integration/e2e)
      and the right service tree (`tests/unit/sourcepilot/...` vs
      `tests/unit/mcp/...` vs `audit-viewer/tests/...`)?
- [ ] **PYTHONPATH**: does the test rely on the surrounding `conftest.py` to
      add `src/` or `mcp-server/` to `sys.path`? It must not hardcode paths.
- [ ] **Mocking**: outbound HTTP via `respx`; Milvus / async clients via
      `unittest.mock.AsyncMock`. No real network calls.
- [ ] **Fixture reuse**: does it duplicate canned data instead of importing
      from `tests/fixtures/mock_*_responses.py`?
- [ ] **Audit assertion** (when the change touches a new pipeline stage): is
      there a corresponding assertion that the stage emits an audit event
      with the expected `stage`, `records_count`, and `trace_id`?
- [ ] **Naming**: `test_<verb>_<scenario>` (matches existing convention in
      `tests/unit/sourcepilot/gateway/test_*.py`).
- [ ] **Docstring**: one line saying what the test asserts (Chinese is OK if
      consistent with surrounding code; the rest of `tests/conftest.py` and
      its neighbors use Chinese docstrings).
- [ ] **Async**: marked with `@pytest.mark.asyncio` or living in a file
      where `asyncio_mode = "auto"` is set (audit-viewer has this in its
      `pyproject.toml`).
- [ ] **Speed**: a single test should run in well under one second; if it
      sleeps, justify it.
- [ ] **No new live-backend dependency**: pytest must remain runnable
      without Zoekt / Milvus / SourcePilot — those belong in smoke scripts.

## Audit-log assertion patterns (descriptive — already used in the codebase)

The repo treats audit-log emission as a first-class invariant, asserted at
two layers:

### Unit-level (`tests/unit/sourcepilot/observability/test_audit.py`)

The audit module is exercised against a tempfile-backed SQLite DB; tests
assert that `audit.emit(stage=..., trace_id=..., ...)` produces the right
JSONL shape (timestamp, trace_id, event, stage, status, records_count, ...)
and the right SQLite row.

### Live (`scripts/smoke_queries.sh`)

After every smoke case, the script polls `audit-viewer/data/audit.db`:

```sql
SELECT count(*) FROM events
 WHERE stage='dense_search' AND trace_id='<trace_id>'
```

It then verifies `records_count` matches the semantic expectation:
in-scope NL queries should produce dense hits (>0); out-of-scope NL queries
should produce zero. A missing stage row, or a wrong `records_count`,
exits the script non-zero.

### Idiom for new pipeline stages

When you add a new stage to the gateway pipeline, the established pattern is:

1. Emit `audit.emit(stage="my_new_stage", trace_id=trace_id, records_count=n, ...)`.
2. Add a unit test in `tests/unit/sourcepilot/observability/` (or wherever
   the stage lives) that asserts the emit happens with the right payload.
3. Add a case to `scripts/smoke_queries.sh` (or extend an existing case)
   that triggers the new stage and asserts the audit row appears.

## Live-backend tests status (descriptive)

The repo deliberately separates the two concerns:

| | Pytest suites | Smoke scripts |
|---|--------------|---------------|
| Need live Zoekt? | No (respx-mocked) | Yes |
| Need live Milvus? | No (AsyncMock) | Yes (`DENSE_ENABLED=true` + indexed `frameworks/base`) |
| Need live LLM? | No (canned responses) | Optional, depends on `NL_ENABLED` config |
| Run on CI by default? | Yes (suggested) | Manual / on tag (suggested) |

Adding a new "integration test that hits a live backend" to the pytest
suites is **explicitly out of pattern** — that work belongs in smoke
scripts. This is intentional: PR-time CI must be fast and deterministic.

## Coverage gaps (informational)

Known gaps that future PRs may want to close (do not adopt as gates today):

- **Fusion math**: `src/gateway/fusion.py` (RRF merge) does not have a
  dedicated math-correctness test; it is exercised only end-to-end via
  `tests/integration/test_gateway_pipeline.py`.
- **Embedding-model end-to-end**: no test currently calls the embedding
  service against a real model; embedding behavior is fully mocked in
  `tests/unit/sourcepilot/adapters/test_embedding.py`.

These gaps are noted here so a future contributor can plan to fill them; no
current acceptance criterion requires them.

## See also

- [ci.md](./ci.md) — where suggested coverage gates would be enforced
- [pytest-suite.md](./pytest-suite.md) — what tests already exist
- [smoke-scripts.md](./smoke-scripts.md) — live audit assertion details
