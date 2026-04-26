# Pytest Suite Walkthrough

> Audience: **layer author**. Read this when you want to know what each test
> file covers, how to run only the slice you care about, and how to add a new
> test to the right place.

## Suite layout

```
tests/
├── conftest.py                                   # global env + shared mock fixtures
├── fixtures/
│   ├── __init__.py
│   ├── mock_zoekt_responses.py                   # canned Zoekt /search & /repos & /print payloads
│   ├── mock_sourcepilot_responses.py             # canned SourcePilot HTTP API payloads (used by MCP tests)
│   └── mock_llm_responses.py                     # canned LLM rewrite + classifier outputs
├── test_mcp_endpoints.sh                         # bash + curl exerciser (live MCP, not pytest)
├── unit/
│   ├── sourcepilot/
│   │   ├── conftest.py                           # adds src/ to sys.path
│   │   ├── adapters/
│   │   │   ├── test_base.py                      # SearchAdapter ABC contract
│   │   │   ├── test_dense.py                     # DenseAdapter (Qdrant client AsyncMock'd)
│   │   │   ├── test_embedding.py                 # Embedding service client
│   │   │   └── test_zoekt.py                     # ZoektAdapter (respx-mocked Zoekt HTTP)
│   │   ├── config/
│   │   │   ├── test_backends.py                  # backend registry
│   │   │   └── test_base.py                      # env-var config loader
│   │   ├── gateway/
│   │   │   ├── test_converters.py                # result format converters
│   │   │   ├── test_fusion.py                    # RRF cross-engine fusion
│   │   │   ├── test_gateway.py                   # main orchestrator
│   │   │   ├── test_ranker.py                    # feature-based reranking
│   │   │   ├── test_router.py                    # query routing & parallel dispatch
│   │   │   └── nl/
│   │   │       ├── test_cache.py                 # LRU cache + concept_map
│   │   │       ├── test_classifier.py            # query intent classification
│   │   │       └── test_rewriter.py              # LLM query rewrite
│   │   └── observability/
│   │       └── test_audit.py                     # structured JSON audit logging (SQLite tempfile)
│   └── mcp/
│       ├── conftest.py                           # adds mcp-server/ to sys.path
│       ├── test_mcp_server.py                    # entry-point dispatcher (stdio/http)
│       └── entry/
│           ├── test_handlers.py                  # MCP Server + tools + httpx → SourcePilot
│           ├── test_mcp_http.py                  # HTTP transport + BearerTokenMiddleware
│           └── test_mcp_stdio.py                 # stdio transport
├── integration/
│   ├── conftest.py                               # adds src/ to sys.path
│   ├── test_api_contract.py                     # HTTP API contract / response shape
│   └── test_gateway_pipeline.py                 # full gateway pipeline with respx-mocked backends
└── e2e/
    ├── conftest.py                               # adds BOTH src/ and mcp-server/ to sys.path
    └── test_mcp_sourcepilot_chain.py            # MCP → SourcePilot in-process, HTTP via respx

sp-cockpit/tests/
├── conftest.py                                   # SQLite tempfile + SP_COCKPIT_AUDIT_LOG_PATH env override
├── test_api.py                                   # FastAPI endpoints
├── test_ingester.py                              # JSONL → SQLite ingestion loop
├── test_parser.py                                # audit-log line parser
└── test_retention.py                             # retention/pruning policy
```

The repo has several hundred test functions across these trees
(`grep -rn '^def test_\|^async def test_\|^    def test_\|^    async def test_' tests/ sp-cockpit/tests/ | wc -l`).

## Per-directory walkthrough

### `tests/unit/sourcepilot/adapters/`

| File | Module under test | Key technique |
|------|-------------------|---------------|
| `test_base.py` | `src/adapters/base.py` (SearchAdapter ABC) | Direct subclass instantiation, ABC method-presence assertions |
| `test_dense.py` | `src/adapters/dense.py` (Qdrant dense search) | `AsyncMock` patches the Qdrant client; embedding call mocked |
| `test_embedding.py` | `src/adapters/embedding.py` | `respx` against the embedding service URL |
| `test_zoekt.py` | `src/adapters/zoekt.py` | `respx` against Zoekt `/search`, `/repos`, `/print`; HTML `<pre>` parsing for `/print` |

### `tests/unit/sourcepilot/gateway/`

| File | Module under test |
|------|-------------------|
| `test_gateway.py` | `src/gateway/gateway.py` — main `search()` orchestrator |
| `test_router.py` | `src/gateway/router.py` — parallel adapter dispatch |
| `test_fusion.py` | `src/gateway/fusion.py` — RRF cross-engine fusion math |
| `test_ranker.py` | `src/gateway/ranker.py` — feature-based reranking |
| `test_converters.py` | `src/gateway/converters.py` — result-format converters |
| `nl/test_cache.py` | `src/gateway/nl/cache.py` — LRU cache + `concept_map.json` lookup |
| `nl/test_classifier.py` | `src/gateway/nl/classifier.py` — intent classification |
| `nl/test_rewriter.py` | `src/gateway/nl/rewriter.py` — LLM query rewrite |

### `tests/unit/sourcepilot/config/` & `observability/`

| File | Module under test |
|------|-------------------|
| `config/test_base.py` | `src/config/base.py` — env-var loader |
| `config/test_backends.py` | `src/config/backends.py` — backend registry |
| `observability/test_audit.py` | `src/observability/audit.py` — structured JSON audit logger; uses tempfile SQLite via `tmp_paths` fixture |

### `tests/unit/mcp/`

| File | Module under test |
|------|-------------------|
| `test_mcp_server.py` | `mcp-server/mcp_server.py` — entry dispatcher (chooses stdio vs http) |
| `entry/test_handlers.py` | `mcp-server/entry/handlers.py` — MCP tools, httpx client to SourcePilot |
| `entry/test_mcp_http.py` | `mcp-server/entry/mcp_http.py` — HTTP transport + `BearerTokenMiddleware` |
| `entry/test_mcp_stdio.py` | `mcp-server/entry/mcp_stdio.py` — stdio transport |

### `tests/integration/`

| File | What it covers |
|------|----------------|
| `test_gateway_pipeline.py` | Drives `gateway.search()` end-to-end with respx-mocked Zoekt and patched dense; verifies stage chain (classify → rewrite → dense_search → rrf_merge → rerank) |
| `test_api_contract.py` | Starlette `TestClient` against `src/app.py`; asserts response shapes for all 7 endpoints |

### `tests/e2e/`

| File | What it covers |
|------|----------------|
| `test_mcp_sourcepilot_chain.py` | Imports MCP and SourcePilot in the same process; MCP `httpx.AsyncClient` is replaced by an `ASGITransport` against the SourcePilot Starlette app; respx still mocks Zoekt downstream |

### `sp-cockpit/tests/`

| File | Module under test |
|------|-------------------|
| `test_parser.py` | `sp_cockpit/parser.py` — JSONL line parser |
| `test_ingester.py` | `sp_cockpit/ingester.py` — tail JSONL → SQLite |
| `test_api.py` | `sp_cockpit/api.py` — FastAPI endpoints |
| `test_retention.py` | `sp_cockpit/retention.py` — retention/pruning policy |

## Run commands

### Canonical (from `CLAUDE.md`)

```bash
# SourcePilot — unit + integration + e2e
PYTHONPATH=src pytest tests/unit/sourcepilot/ tests/integration/ tests/e2e/ -v

# MCP unit tests
PYTHONPATH=mcp-server pytest tests/unit/mcp/ -v

# All-in-one
PYTHONPATH=src pytest tests/unit/sourcepilot/ tests/integration/ tests/e2e/ -v && \
PYTHONPATH=mcp-server pytest tests/unit/mcp/ -v

# Audit-viewer (separate project, has its own pyproject.toml)
(cd sp-cockpit && pytest -v)
```

### Filtered runs

```bash
# Only one module
PYTHONPATH=src pytest tests/unit/sourcepilot/gateway/test_fusion.py -v

# Only matching test names
PYTHONPATH=src pytest tests/unit/sourcepilot/ -v -k "rerank"

# Stop at first failure, show locals
PYTHONPATH=src pytest tests/unit/sourcepilot/ -x -l

# Re-run only last failures
PYTHONPATH=src pytest tests/unit/sourcepilot/ --lf

# Show coverage
PYTHONPATH=src pytest tests/unit/sourcepilot/ --cov=src --cov-report=term-missing
```

## Adding a new test

### Adding a unit test

1. Pick the module you're testing — say `src/gateway/foo.py`.
2. Create `tests/unit/sourcepilot/gateway/test_foo.py`.
3. The local `tests/unit/sourcepilot/conftest.py` already adds `src/` to
   `sys.path`. The global `tests/conftest.py` already sets the env vars
   (`ZOEKT_URL`, `NL_ENABLED=false`, `AUDIT_ENABLED=false`, ...).
4. Mock outbound HTTP with `respx`; mock async Qdrant/embedding clients with
   `unittest.mock.AsyncMock`. See [fixtures.md](./fixtures.md) for examples.
5. Run only your file: `PYTHONPATH=src pytest tests/unit/sourcepilot/gateway/test_foo.py -v`.

### Adding an integration test

Use `tests/integration/test_gateway_pipeline.py` as a template — it drives
`gateway.search()` with respx-mocked Zoekt and asserts on the stage chain.
Place new files in `tests/integration/` and run with
`PYTHONPATH=src pytest tests/integration/ -v`.

### Adding an e2e test

E2E tests run **both** SourcePilot and the MCP layer in the same Python
process. Add a file under `tests/e2e/` — `tests/e2e/conftest.py` already
adds both `src/` and `mcp-server/` to `sys.path`. See
`tests/e2e/test_mcp_sourcepilot_chain.py` for the ASGI-transport pattern that
lets `httpx.AsyncClient` call the SourcePilot Starlette app in-process.

### Adding an MCP unit test

Place under `tests/unit/mcp/` (top level for the dispatcher) or
`tests/unit/mcp/entry/` (for handlers/transports). The local conftest adds
`mcp-server/` to `sys.path`. Use `respx` to mock the outbound httpx call
to SourcePilot.

### Adding an sp-cockpit test

Place under `sp-cockpit/tests/`. Use the `tmp_paths` fixture from
`sp-cockpit/tests/conftest.py` for a fresh SQLite tempfile and isolated
`SP_COCKPIT_AUDIT_LOG_PATH` / `SP_COCKPIT_AUDIT_DB_PATH` env vars.

## MCP suite caveat — different PYTHONPATH

The MCP suite cannot share a single pytest invocation with the SourcePilot
suite, because the two trees insert different roots into `sys.path` and use
different Python imports. You must run them as two separate `pytest`
invocations (the canonical commands above already do this).

## See also

- [fixtures.md](./fixtures.md) — fixture authoring & mock patterns
- [architecture.md](./architecture.md) — how the suites relate
- [troubleshooting.md](./troubleshooting.md) — common pytest failures
