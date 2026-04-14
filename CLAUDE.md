# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AOSP Code Search — two independent services communicating via HTTP API:

1. **SourcePilot** (`src/`) — Hybrid RAG search engine with Starlette HTTP API
2. **MCP Access Layer** (`mcp-server/`) — Thin MCP protocol proxy delegating to SourcePilot via httpx

## Commands

```bash
# Environment setup (copy template, edit values)
cp .env.example .env

# Start full stack (zoekt + SourcePilot + MCP) — reads from .env
scripts/run_all.sh

# Start both services (auto-starts SourcePilot as subprocess)
scripts/run_mcp.sh

# Start SourcePilot standalone
scripts/run_sourcepilot.sh

# Start MCP with external SourcePilot
SOURCEPILOT_URL=http://localhost:9000 scripts/run_mcp.sh

# MCP Streamable HTTP mode
scripts/run_mcp.sh --transport streamable-http --port 8888

# Run SourcePilot tests (unit + integration + e2e)
PYTHONPATH=src pytest tests/unit/sourcepilot/ tests/integration/ tests/e2e/ -v

# Run MCP tests
PYTHONPATH=mcp-server pytest tests/unit/mcp/ -v

# Run all tests
PYTHONPATH=src pytest tests/unit/sourcepilot/ tests/integration/ tests/e2e/ -v && PYTHONPATH=mcp-server pytest tests/unit/mcp/ -v
```

## Architecture

```
src/                              # SourcePilot — Hybrid RAG Search Engine
├── app.py                        # Starlette HTTP API (7 endpoints, port 9000)
├── gateway/                      # Layer 1: Query Gateway (business logic)
│   ├── gateway.py                # Main orchestrator: classify → NL pipeline or direct search
│   ├── router.py                 # Query routing & parallel dispatch
│   ├── fusion.py                 # RRF cross-engine fusion
│   ├── ranker.py                 # Feature-based reranking
│   └── nl/                       # NL sub-module
│       ├── classifier.py         # Query intent classification
│       ├── rewriter.py           # LLM query rewrite
│       ├── cache.py              # LRU cache + concept_map
│       └── concept_map.json
├── adapters/                     # Layer 2: Adapter Layer (pluggable backends)
│   ├── base.py                   # SearchAdapter ABC
│   ├── zoekt.py                  # ZoektAdapter — Zoekt HTTP client
│   └── feishu.py                 # FeishuAdapter placeholder
├── observability/                # Cross-cutting: Observability
│   └── audit.py                  # Structured JSON audit logging
└── config/                       # Cross-cutting: Configuration
    ├── base.py                   # Env var config
    └── backends.py               # Backend registry

mcp-server/                       # MCP Access Layer — Protocol Proxy
├── mcp_server.py                 # Entry-point dispatcher (stdio/HTTP)
├── requirements.txt
└── entry/
    ├── handlers.py               # MCP Server + tools + httpx client → SourcePilot
    ├── mcp_stdio.py              # stdio transport
    └── mcp_http.py               # HTTP transport + BearerTokenMiddleware
```

### Request Flow

**MCP path**: tool call → `mcp-server/entry/handlers.py` → httpx POST → `src/app.py` → `gateway.search()` → classify → ZoektAdapter → format results

**Direct SourcePilot path**: HTTP POST → `src/app.py` → `gateway.search()` → classify → ZoektAdapter → JSON response

### Key Design Decisions

- Two projects communicate via HTTP API (localhost:9000). No shared imports.
- MCP layer uses httpx.AsyncClient (module-level singleton, timeout=30s) to call SourcePilot.
- X-Trace-Id header propagates trace IDs across services.
- Audit/config fully in SourcePilot; MCP layer uses standard logging only.
- All SourcePilot imports use paths relative to `src/` (`from config import ...`, `from gateway.nl.rewriter import ...`).
- All MCP imports use paths relative to `mcp-server/` (`from entry.handlers import ...`).
- Layered dependency within SourcePilot: gateway → adapters → config/observability. No upward dependencies.
- Zoekt score normalization uses sigmoid mapping: `1/(1+exp(-0.1*(score-10)))` inside `ZoektAdapter` to map BM25 scores (typically 0-50) into 0-1 range.
- Zoekt `/print` endpoint returns HTML, not JSON. `ZoektAdapter.fetch_file_content()` parses `<pre>` tags and strips HTML to extract source code.
- MCP Streamable HTTP mode uses Starlette with `BearerTokenMiddleware` wrapping the session manager. The middleware must pass through `lifespan` events (non-http scope types).
- `SearchAdapter` ABC enables pluggable backends. New backends implement `search()`, `get_content()`, `health_check()`.

## Environment

- Python virtualenv: `/opt/pyenv/versions/dify_py3_env/bin/python3`
- Two PYTHONPATH roots: `src/` for SourcePilot, `mcp-server/` for MCP
- SourcePilot tests: `PYTHONPATH=src pytest tests/test_sourcepilot.py tests/test_api_contract.py tests/test_audit.py`
- MCP tests: `PYTHONPATH=mcp-server pytest tests/test_mcp_server.py`
- Key env vars: ZOEKT_URL, SOURCEPILOT_URL (default http://localhost:9000), MCP_AUTH_TOKEN
- Tests use `respx` to mock HTTP responses -- no real Zoekt server needed
- The project language is primarily Chinese (comments, docs, error messages, NL pipeline)
