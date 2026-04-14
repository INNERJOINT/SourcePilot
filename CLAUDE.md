# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AOSP Code Search — bridges Zoekt code search with AI coding tools via MCP (Model Context Protocol).

**MCP Server** (`mcp_server.py`): MCP server for AI coding tools (Claude Code, Cursor, etc.) with stdio and Streamable HTTP transport modes

## Commands

```bash
# Run MCP Server (stdio mode, for local AI tools)
PYTHONPATH=src scripts/run_mcp.sh

# Run MCP Server (Streamable HTTP mode, port 8888)
PYTHONPATH=src scripts/run_mcp.sh --transport streamable-http --port 8888

# Run tests
PYTHONPATH=src pytest tests/ -v

# Run a single test class or method
PYTHONPATH=src pytest tests/test_zoekt_enhancements.py::TestSearch -v
PYTHONPATH=src pytest tests/test_zoekt_enhancements.py::TestSearch::test_basic_search -v
```

## Architecture

```
src/aosp_search/
├── mcp_server.py     # MCP Server — tools: search_code, search_symbol, search_file, search_regex, list_repos, get_file_content
├── zoekt_client.py   # Zoekt HTTP client — search(), search_regex(), list_repos(), fetch_file_content()
├── config.py         # All config via env vars (ZOEKT_URL, NL_*, MCP_AUTH_TOKEN, AUDIT_*, etc.)
├── audit.py          # Structured JSON audit logging for tool calls and search stages
├── nl_search.py      # NL enhanced search pipeline (shared module)
└── nl/               # Natural language enhancement pipeline
    ├── classifier.py # Query intent: 'exact' vs 'natural_language' (rule-based)
    ├── rewriter.py   # LLM query rewrite (DeepSeek by default) with keyword fallback on timeout
    ├── merger.py     # RRF (Reciprocal Rank Fusion) multi-route result merging
    ├── reranker.py   # Feature-based lightweight rerank (no GPU, <5ms)
    ├── cache.py      # LRU cache + concept_map.json for high-frequency AOSP queries
    └── concept_map.json  # Maps Chinese NL concepts → AOSP symbol names
```

### Request Flow

**MCP path**: tool call → classify query → exact: `zoekt_client.search()` / NL: rewrite → parallel Zoekt queries → RRF merge → feature rerank → format results as LLM-friendly text. MCP also supports `aosp://` resource URIs for reading file content via `read_resource`.

### Key Design Decisions

- `zoekt_client.py` imports `config` as a bare module (not `aosp_search.config`) — this works because `sys.path` is manipulated at runtime. Scripts set `PYTHONPATH=src`, and `mcp_server.py` inserts its own directory into `sys.path`.
- Zoekt score normalization uses sigmoid mapping: `1/(1+exp(-0.1*(score-10)))` to map BM25 scores (typically 0–50) into 0–1 range.
- Zoekt `/print` endpoint returns HTML, not JSON. `fetch_file_content()` parses `<pre>` tags and strips HTML to extract source code.
- MCP Streamable HTTP mode uses Starlette with `BearerTokenMiddleware` wrapping the session manager. The middleware must pass through `lifespan` events (non-http scope types).

## Environment

- Python virtualenv: `/opt/pyenv/versions/dify_py3_env/bin/python3`
- All configuration is via environment variables (see `config.py`)
- Tests use `respx` to mock Zoekt HTTP responses — no real Zoekt server needed
- The project language is primarily Chinese (comments, docs, error messages, NL pipeline)
