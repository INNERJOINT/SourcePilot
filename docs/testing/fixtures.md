# Fixtures, Mocks, and Conftest Hierarchy

> Audience: **test author**. Read this when you need to know where to put a
> shared fixture, what mocks already exist, and how the project intercepts
> outbound HTTP / Milvus / LLM calls.

## Conftest hierarchy

```
tests/
├── conftest.py                       # GLOBAL: env vars + Zoekt/SourcePilot mock fixtures
├── unit/
│   ├── sourcepilot/
│   │   └── conftest.py               # adds src/ to sys.path
│   └── mcp/
│       └── conftest.py               # adds mcp-server/ to sys.path
├── integration/
│   └── conftest.py                   # adds src/ to sys.path
└── e2e/
    └── conftest.py                   # adds BOTH src/ and mcp-server/ to sys.path

sp-cockpit/tests/
└── conftest.py                       # tempfile audit.log + audit.db, AUDIT_*_PATH env override
```

`tests/conftest.py` runs first for every pytest session under `tests/`. It
sets the four critical environment variables **before any project import**:

```python
os.environ.setdefault("ZOEKT_URL", "http://mock-zoekt:6070")
os.environ.setdefault("NL_ENABLED", "false")
os.environ.setdefault("SOURCEPILOT_URL", "http://mock-sourcepilot:9000")
os.environ.setdefault("MCP_AUTH_TOKEN", "test-token-12345")
os.environ.setdefault("AUDIT_ENABLED", "false")
```

Setting these via `setdefault` means a CI environment can override them, but
local pytest runs always get sane defaults. The mock URLs are deliberately
non-resolvable (`mock-zoekt`, `mock-sourcepilot`) so any unintercepted call
fails loudly instead of accidentally hitting a real service.

## Global mock fixtures (`tests/conftest.py`)

| Fixture | Returns | Source |
|---------|---------|--------|
| `mock_zoekt_search_response` | Dict — Zoekt `/search` payload with two `FileMatches` and `Stats` | `MOCK_SEARCH_RESPONSE` in `tests/fixtures/mock_zoekt_responses.py` |
| `mock_empty_response` | Dict — Zoekt empty-result payload | `MOCK_EMPTY_SEARCH_RESPONSE` |
| `mock_sourcepilot_results` | List — SourcePilot HTTP API search results | `MOCK_SP_SEARCH_RESULTS` in `tests/fixtures/mock_sourcepilot_responses.py` |

(See `tests/conftest.py` for the full list — it also exposes `mock_repo_response`,
`mock_file_content_html`, `mock_sp_repos`, `mock_sp_file_content`, etc.)

## Mock-data modules (`tests/fixtures/`)

| File | Exports | Used by |
|------|---------|---------|
| `mock_zoekt_responses.py` | `MOCK_SEARCH_RESPONSE`, `MOCK_EMPTY_SEARCH_RESPONSE`, `MOCK_REPO_RESPONSE`, `MOCK_FILE_CONTENT_HTML` | SourcePilot adapter & gateway tests, integration tests |
| `mock_sourcepilot_responses.py` | `MOCK_SP_SEARCH_RESULTS`, `MOCK_SP_REPOS`, `MOCK_SP_FILE_CONTENT` | MCP unit tests, e2e tests |
| `mock_llm_responses.py` | `MOCK_LLM_VALID_RESPONSE`, `MOCK_LLM_INVALID_RESPONSE`, `MOCK_LLM_TIMEOUT_RESPONSE`, `MOCK_CLASSIFIER_NL_RESULT`, `MOCK_CLASSIFIER_EXACT_RESULT`, ... | NL rewriter & classifier unit tests |
| `__init__.py` | (empty marker) | Makes `tests.fixtures` an importable package |

The mock data deliberately mirrors the real shapes (e.g., the Zoekt response
includes `Result.FileMatches[].Repo`, `FileName`, `Score`, `Matches[].LineNum`,
`Matches[].Fragments[].{Pre,Match,Post}`). When the real backend's response
shape changes, these fixtures must be updated.

## respx patterns (HTTP mocking)

`respx` intercepts every `httpx` call and returns canned responses. The repo
uses respx in two main places:

### Adapter unit tests — mocking outbound HTTP

```python
import respx
from httpx import Response
from tests.fixtures.mock_zoekt_responses import MOCK_SEARCH_RESPONSE

@respx.mock
async def test_zoekt_adapter_search():
    respx.get("http://mock-zoekt:6070/search").mock(
        return_value=Response(200, json=MOCK_SEARCH_RESPONSE)
    )
    adapter = ZoektAdapter()
    results = await adapter.search("startBootstrap")
    assert len(results) == 2
```

### Integration tests — mocking the entire backend layer

`tests/integration/test_gateway_pipeline.py` registers respx routes for every
backend the gateway calls, then drives `gateway.search()` and asserts the
stage chain ran end-to-end. This is the canonical pattern for new
integration tests.

### E2E tests — ASGI transport + respx for downstream

`tests/e2e/test_mcp_sourcepilot_chain.py` runs both MCP and SourcePilot
in-process. The MCP layer's `httpx.AsyncClient` is wired via `ASGITransport`
to the SourcePilot Starlette app, so MCP→SourcePilot calls are real Python
calls (no socket). Downstream Zoekt / dense calls are still respx-mocked.

## AsyncMock pattern (Milvus, embedding, LLM)

The dense search adapter and LLM rewriter use `unittest.mock.AsyncMock` /
`patch` rather than respx, because they don't go over httpx (Milvus uses its
own gRPC client; LLM may be a custom SDK).

```python
from unittest.mock import AsyncMock, patch

@patch("adapters.dense.MilvusClient")
async def test_dense_search(mock_milvus_cls):
    mock_milvus = AsyncMock()
    mock_milvus.search.return_value = [{"id": 1, "distance": 0.12, ...}]
    mock_milvus_cls.return_value = mock_milvus

    adapter = DenseAdapter()
    results = await adapter.search([0.0] * 768, top_k=5)
    assert len(results) == 1
```

See `tests/unit/sourcepilot/adapters/test_dense.py` and
`tests/unit/sourcepilot/gateway/nl/test_rewriter.py` for the full patterns.

## Audit-log fixtures (`tests/unit/sourcepilot/observability/test_audit.py`)

The audit-emission unit test writes to a tempfile-backed SQLite DB so it
doesn't touch the real `sp-cockpit/data/audit.db`. This works because the
audit module's path is config-driven; the test sets the env vars to a
`tmp_path` location (the built-in pytest fixture, not the sp-cockpit
`tmp_paths` fixture below).

## Audit-viewer fixtures (`sp-cockpit/tests/conftest.py`)

The sp-cockpit tests are isolated from the rest of the repo:

```python
@pytest.fixture
def tmp_paths(tmp_path: Path, monkeypatch):
    log_p = tmp_path / "audit.log"
    db_p = tmp_path / "audit.db"
    log_p.touch()
    monkeypatch.setenv("SP_COCKPIT_AUDIT_LOG_PATH", str(log_p))
    monkeypatch.setenv("SP_COCKPIT_AUDIT_DB_PATH", str(db_p))
    monkeypatch.setenv("SP_COCKPIT_FRONTEND_DIST", "/nonexistent-spa")
    import importlib
    from sp_cockpit import config as cfg
    importlib.reload(cfg)               # so cached config picks up new env
    yield {"log": log_p, "db": db_p, "tmp": tmp_path}
```

Note the explicit `importlib.reload(cfg)` — sp-cockpit caches its config at
module import time, so any test that needs different paths must reload it.
The same conftest also exposes `make_line(...)` for synthesizing one
audit-log JSONL line with arbitrary fields (`trace_id`, `event`, `stage`,
`tool`, `status`, `slow`, ...) used by parser/ingester tests.

## How to add a new fixture

Use this decision tree:

1. **Will it be used in only one test file?**
   → Define it in that file, scope `function`.

2. **Will it be shared across multiple files in the same directory?**
   → Add it to the nearest `conftest.py`. For example, a fixture used
   across `tests/unit/sourcepilot/adapters/*` belongs in
   `tests/unit/sourcepilot/adapters/conftest.py` (create it if absent).

3. **Will it be shared across SourcePilot and MCP suites?**
   → Add it to `tests/conftest.py`. (This is rare — most cross-suite shared
   data is canned response data, not a fixture.)

4. **Is it canned response data (JSON/dict)?**
   → Add it to `tests/fixtures/mock_*_responses.py` as a module-level
   constant, then import it from `tests/conftest.py` and wrap it in a
   fixture if needed (so each test gets a `.copy()` and can mutate freely).

5. **Is it sp-cockpit-specific?**
   → `sp-cockpit/tests/conftest.py`. Audit-viewer is a separate project
   and does not share fixtures with the SourcePilot/MCP suites.

### Avoid

- Importing across suites (`tests/unit/mcp/` should not import from
  `tests/unit/sourcepilot/`). The two suites have different `sys.path`.
- Reading real files from disk inside fixtures — use `tmp_path` /
  `tmp_path_factory`.
- Hitting real network endpoints. If you need an HTTP fake, register a respx
  route. If respx is not active for that test, the call will fail because
  the default URLs (`mock-zoekt`, `mock-sourcepilot`) are not resolvable.

## See also

- [pytest-suite.md](./pytest-suite.md) — where each fixture is consumed
- [architecture.md](./architecture.md) — flow diagram showing where mocks slot in
- [troubleshooting.md](./troubleshooting.md) — "respx not intercepting", "SP_COCKPIT_AUDIT_LOG_PATH leaking"
