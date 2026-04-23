# Troubleshooting

> Audience: **debugger / new contributor stuck on a failing test or smoke run**.
> Look up your symptom; each entry has a cause and a fix.

## `ModuleNotFoundError: No module named 'gateway'` (or `'adapters'`, `'observability'`)

**Cause.** The PYTHONPATH was not set, or it was set to the wrong root.

**Fix.** Use the correct root for the suite you're running:

```bash
# SourcePilot (gateway / adapters / observability / config)
PYTHONPATH=src pytest tests/unit/sourcepilot/ -v

# MCP (entry / handlers / mcp_http / mcp_stdio)
PYTHONPATH=mcp-server pytest tests/unit/mcp/ -v

# E2E needs both — but tests/e2e/conftest.py already adds them; you only
# need PYTHONPATH=src here, conftest does the rest:
PYTHONPATH=src pytest tests/e2e/ -v
```

If you ran `pytest` without `PYTHONPATH=...`, the conftests still try to add
the right root via `sys.path.insert`, but pytest may have already imported
stale module paths. Stop, set the env var, and re-run.

## `ModuleNotFoundError: No module named 'sp_cockpit'`

**Cause.** You ran `pytest` from the repo root for the sp-cockpit tests.
Audit-viewer is a separate project with its own `pyproject.toml` and
`sp_cockpit/` package.

**Fix.**

```bash
(cd sp-cockpit && pip install -e '.[dev]' && pytest -v)
```

The `-e .[dev]` install also pulls `pytest-asyncio`, which the sp-cockpit
suite needs for `asyncio_mode = "auto"`.

## `respx` not intercepting (real network call attempted)

**Cause.** One of:
- Test function is not decorated with `@respx.mock` (or the surrounding
  fixture didn't open a `respx.mock()` context).
- `respx.<verb>(URL)` was called with a different URL than the code under
  test resolves to — common after changing `ZOEKT_URL` in your local env
  without reloading config.
- The code under test creates its own `httpx.Client` *outside* of the
  module-level singleton, and the test patched the singleton.

**Fix.**
1. Check `tests/conftest.py` env defaults — `ZOEKT_URL=http://mock-zoekt:6070`
   and `SOURCEPILOT_URL=http://mock-sourcepilot:9000`. Your respx route must
   match these exact URLs (unless you override the env in the test).
2. Confirm decorator: `@respx.mock` (sync test) or
   `respx.mock(using="httpx")` (async test) is in scope.
3. Add `assert respx.calls.call_count == 1` after the call to confirm
   interception.

## `audit.db` not populated after smoke run

**Cause.** One of:
- `sp-cockpit` is not running, so nothing is tailing `audit.log` into
  `audit.db`.
- The path `AUDIT_DB` in your environment doesn't match the path
  sp-cockpit is writing to (default is `sp-cockpit/data/audit.db`).
- SourcePilot was started with `AUDIT_ENABLED=false` (or the env var was
  not set — defaults vary).
- `scripts/smoke_queries.sh` was run from a directory where the relative
  `AUDIT_DB` path resolves wrong; run it from the repo root.

**Fix.**

```bash
# 1. Make sure sp-cockpit is up
ls sp-cockpit/data/audit.db

# 2. Make sure SourcePilot was started with audit on (in .env or shell)
grep AUDIT_ENABLED .env
# AUDIT_ENABLED=true

# 3. Run smoke from repo root
cd <repo-root>
bash scripts/smoke_queries.sh
```

If `scripts/smoke_queries.sh` aborts with
`ERROR: dense_search stage not seen after 3s`, see the next entry.

## `dense_search stage not seen` (smoke script preflight)

**Cause.** SourcePilot is up, but the dense path is not active for the
probe query. Possible reasons:
- `DENSE_ENABLED` was not set to `true` when SourcePilot started.
- Milvus is unreachable or `frameworks/base` collection isn't indexed.
- The classifier did not classify the probe query as natural-language.

**Fix.**

```bash
# Restart SourcePilot with DENSE_ENABLED=true
DENSE_ENABLED=true scripts/run_sourcepilot.sh

# Verify Milvus is reachable
curl -fsS http://localhost:19530/v1/vector/collections
```

If you only need a one-shot dense check, `scripts/test_dense.sh` is more
forgiving than `smoke_queries.sh` — it greps `audit.log` directly and does
not require sp-cockpit.

> **Memory note:** the user only indexed `frameworks/base` into Milvus —
> queries for other repos (e.g. Launcher3) will legitimately return zero
> dense hits. That's not a bug; `nl_outscope_dense` in `smoke_queries.sh`
> is the case that asserts this behavior.

## MCP transport mismatch (`无法获取 Session ID`)

**Cause.** `tests/test_mcp_endpoints.sh` only works against the
**streamable-HTTP** transport. If MCP was started in `stdio` mode, there's
no `mcp-session-id` header to grep.

**Fix.**

```bash
scripts/run_mcp.sh --transport streamable-http --port 8888
# then
bash tests/test_mcp_endpoints.sh
```

If you intended to test stdio, use the Python MCP client (or the unit tests
in `tests/unit/mcp/entry/test_mcp_stdio.py`) instead.

## Zoekt / SourcePilot / Milvus connection refused (smoke)

**Cause.** The relevant service isn't running, or there's a port collision.

**Fix.**

```bash
# Bring up the full stack
scripts/run_all.sh

# Verify each port
curl -fsS http://localhost:9000/api/health   # SourcePilot
curl -fsS http://localhost:6070/             # Zoekt
curl -fsS http://localhost:9100/api/health   # sp-cockpit (if running)

# Ports occupied? Find offender
ss -lntp | grep -E ':9000|:6070|:9100|:8888|:19530'
```

## Audit-viewer test SQLite leak / "DB locked"

**Cause.** A previous test held an open SQLite connection across the
fixture boundary, or the sp-cockpit module cached a config object
referring to the old tempfile.

**Fix.** The `tmp_paths` fixture in `sp-cockpit/tests/conftest.py`
calls `importlib.reload(cfg)` for exactly this reason. If you wrote a new
fixture that bypasses `tmp_paths`, mirror that reload pattern. Always
close any explicit `sqlite3.connect(...)` you open.

## `test_dense.py` or `test_embedding.py` errors with "no Milvus collection"

**Cause.** Despite the test name, these files are **fully mocked** unit
tests (Milvus client is `AsyncMock`'d). If you see a real Milvus error,
the test was inadvertently skipping the mock — usually because someone
patched the wrong import path.

**Fix.** Patch where the symbol is *used*, not where it is *defined*.
Example: if `src/adapters/dense.py` does `from milvus import MilvusClient`,
patch `src.adapters.dense.MilvusClient`, not `milvus.MilvusClient`.

## `pytest` succeeds locally but fails in (a hypothetical) CI

**Cause.** Most likely causes, in rough order:
1. CI installed a different Python minor version (3.10 vs 3.11) and one
   dependency picked up a different default.
2. Local `.env` is providing values that override `tests/conftest.py`'s
   `setdefault`s. CI runs without `.env`, so the test gets the conftest
   defaults instead.
3. CI runs with a clean working directory; tests that read relative paths
   (`audit.log`, `data/`) silently land in the wrong place.

**Fix.** Run with the same env vars CI uses:

```bash
env -i HOME=$HOME PATH=$PATH \
  PYTHONPATH=src pytest tests/unit/sourcepilot/ -v
```

This mimics a fresh shell with no leaked vars.

## `OSError: [Errno 98] Address already in use` during e2e

**Cause.** A previous SourcePilot or sp-cockpit instance is still bound
to `:9000` or `:9100`.

**Fix.**

```bash
ss -lntp | grep -E ':9000|:9100'
# kill the offending PID
```

If you're hitting this in `tests/e2e/`, note that those tests use
`ASGITransport` — they should *not* bind a real port. If they are, the
test is creating an `httpx.AsyncClient(base_url="http://...")` against a
real server instead of `ASGITransport(app=...)`. Fix the test.

## Slow `pytest` startup (collection phase)

**Cause.** `tests/conftest.py` reloads project config; if you've added a
fixture that imports a heavy module (e.g., the entire `gateway` tree) at
collection time, every test session pays that cost.

**Fix.** Defer heavy imports inside fixture functions, not at module level.

## See also

- [pytest-suite.md](./pytest-suite.md) — canonical commands referenced above
- [smoke-scripts.md](./smoke-scripts.md) — full pre-flight requirements
- [fixtures.md](./fixtures.md) — respx, AsyncMock, and sp-cockpit fixture patterns
