# SourcePilot

A hybrid RAG search engine providing code search and natural-language enhancement for the AOSP codebase.

Built on the Zoekt full-text search engine, SourcePilot elevates traditional code search into a semantic retrieval service through NL classification, LLM query rewriting, multi-path parallel retrieval, RRF fusion, and feature-based reranking. It exposes an HTTP REST API for the MCP access layer and other clients.

## Architecture

```
                        HTTP Request
                            |
                            v
+----------------------------------------------------------+
|  app.py (Starlette HTTP API)                             |
|  7 REST endpoints + audit logging + trace_id management  |
+----------------------------------------------------------+
                            |
                            v
+----------------------------------------------------------+
|  gateway/                                                |
|  +--------------------------+                            |
|  | gateway.py  main orchestrator                         |
|  |  classify -> NL/exact    |                            |
|  +--------------------------+                            |
|  | nl/classifier.py  intent classification (rule-first)  |
|  | nl/rewriter.py    LLM rewrite + keyword fallback      |
|  | nl/cache.py       LRU cache + concept_map             |
|  +--------------------------+                            |
|  | fusion.py    RRF fusion (dedupe/merge multi-path)     |
|  | ranker.py    feature-based lightweight reranking      |
|  | router.py    query routing & parallel dispatch        |
|  +--------------------------+                            |
+----------------------------------------------------------+
                            |
                            v
+----------------------------------------------------------+
|  adapters/                                               |
|  +------------------------------------------------------+|
|  | base.py       SearchAdapter ABC + unified data types ||
|  | zoekt.py      ZoektAdapter — Zoekt HTTP client       ||
|  | feishu.py     FeishuAdapter (placeholder)            ||
|  +------------------------------------------------------+|
+----------------------------------------------------------+
          |                                |
          v                                v
+--------------------+        +------------------------+
| config/            |        | observability/         |
| base.py env vars   |        | audit.py structured    |
| backends.py        |        | JSON audit + trace_id  |
+--------------------+        +------------------------+
```

### Request Flow

1. HTTP request arrives at the matching `app.py` endpoint.
2. Parameters are parsed and a `trace_id` is generated or propagated.
3. `gateway.search()` (or the relevant gateway function) is invoked to enter the business-logic layer.
4. For the `search` endpoint:
   - **Intent classification**: `classifier.py` decides whether the query is `exact` or `natural_language`.
   - **Exact query**: calls `ZoektAdapter.search_zoekt()` directly.
   - **NL query**: LLM rewrite -> parallel multi-path Zoekt queries -> RRF fusion -> feature rerank.
5. A JSON response is returned.

## Running

```bash
# Option 1: use the startup script (recommended)
scripts/run_sourcepilot.sh
scripts/run_sourcepilot.sh --host 127.0.0.1 --port 9001

# Option 2: invoke uvicorn directly
PYTHONPATH=src uvicorn app:app --host 0.0.0.0 --port 9000
```

Defaults to listening on `0.0.0.0:9000`.

## HTTP API

All search endpoints are `POST` with a JSON body.

### GET /api/health

Health check.

**Response:**
```json
{"status": "ok", "service": "sourcepilot"}
```

---

### POST /api/search

Unified search entry point supporting both exact search and natural-language enhanced search.

**Request body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | yes | - | Search query (keywords, symbol names, or natural language) |
| `top_k` | int | no | 10 | Number of results to return |
| `score_threshold` | float | no | 0.0 | Minimum score threshold; results below are filtered out |
| `repos` | string | no | null | Restrict search to a repo-name prefix (e.g. `frameworks/base`) |
| `lang` | string | no | null | Filter by programming language (e.g. `java`, `cpp`, `go`) |
| `branch` | string | no | null | Filter by branch name (e.g. `main`, `android-14.0.0_r1`) |
| `case_sensitive` | string | no | `"auto"` | Case-sensitivity mode: `auto` (sensitive if any uppercase), `yes`, `no` |

**Example request:**
```json
{
  "query": "SystemServer startBootstrapServices",
  "top_k": 5,
  "repos": "frameworks/base",
  "lang": "java"
}
```

**Response:** an array of results; each element includes `title`, `content`, and `metadata` (with `repo`, `path`, `start_line`, `end_line`, `score`).

---

### POST /api/search_symbol

Exact search for code symbols (class names, function names, variable names) using the Zoekt `sym:` prefix.

**Request body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `symbol` | string | yes | - | Symbol name (class, function, etc.) |
| `top_k` | int | no | 5 | Number of results to return |
| `repos` | string | no | null | Repo-name prefix filter |
| `lang` | string | no | null | Programming-language filter |
| `branch` | string | no | null | Branch-name filter |
| `case_sensitive` | string | no | `"auto"` | Case-sensitivity mode |

**Example request:**
```json
{
  "symbol": "ActivityManagerService",
  "lang": "java"
}
```

---

### POST /api/search_file

Search for code files by name or path using the Zoekt `file:` prefix.

**Request body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `path` | string | yes | - | File-name or path pattern (e.g. `SystemServer.java`) |
| `extra_query` | string | no | `""` | Additional keyword to match within the selected files |
| `top_k` | int | no | 5 | Number of results to return |
| `lang` | string | no | null | Programming-language filter |
| `branch` | string | no | null | Branch-name filter |
| `case_sensitive` | string | no | `"auto"` | Case-sensitivity mode |

**Example request:**
```json
{
  "path": "SystemServer.java",
  "extra_query": "startBootstrapServices"
}
```

---

### POST /api/search_regex

Regex-based code search for complex pattern matching.

**Request body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `pattern` | string | yes | - | Regular expression pattern |
| `top_k` | int | no | 10 | Number of results to return |
| `repos` | string | no | null | Repo-name prefix filter |
| `lang` | string | no | null | Programming-language filter |

**Example request:**
```json
{
  "pattern": "func\\s+\\w+\\s*\\(",
  "lang": "go",
  "top_k": 20
}
```

---

### POST /api/list_repos

List repositories in the AOSP codebase, optionally filtered by keyword.

**Request body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | no | `""` | Repo-name filter keyword |
| `top_k` | int | no | 50 | Maximum number of results |

**Example request:**
```json
{
  "query": "frameworks",
  "top_k": 20
}
```

---

### POST /api/get_file_content

Read the full contents of an AOSP source file (or a specified line range).

**Request body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `repo` | string | yes | - | Repo name (from the `repo` field in search results) |
| `filepath` | string | yes | - | File path (from the `path` field in search results; does not include the repo prefix) |
| `start_line` | int | no | 1 | Starting line (1-indexed) |
| `end_line` | int | no | null | Ending line (defaults to end of file) |

**Example request:**
```json
{
  "repo": "frameworks/base",
  "filepath": "core/java/android/os/Process.java",
  "start_line": 100,
  "end_line": 200
}
```

**Response:**
```json
{
  "content": "...(source code)...",
  "total_lines": 850,
  "start_line": 100,
  "end_line": 200
}
```

---

### Error Responses

All endpoints return errors in a uniform format:

```json
{"error": "error description"}
```

Common status codes:
- `400` — missing or malformed parameter
- `404` — file not found
- `500` — internal server error
- `502` — Zoekt backend unreachable

### Request Tracing

All endpoints honor the `X-Trace-Id` request header for distributed tracing. One is generated automatically when absent.

## Configuration

All configuration is driven by environment variables loaded once at import time in `config/base.py` (not per request).

### Zoekt Connection

| Variable | Default | Description |
|----------|---------|-------------|
| `ZOEKT_URL` | `http://localhost:6070` | Zoekt webserver address |

### Natural-Language Enhancement

| Variable | Default | Description |
|----------|---------|-------------|
| `NL_ENABLED` | `true` | Enable the NL-enhanced search pipeline |
| `NL_MODEL` | `deepseek-chat` | LLM model name |
| `NL_API_KEY` | `""` | LLM API key |
| `NL_API_BASE` | `https://api.deepseek.com/v1` | LLM API base URL |
| `NL_TIMEOUT` | `10.0` | LLM call timeout (seconds); falls back to keyword search on timeout |
| `NL_CACHE_TTL` | `86400` | NL rewrite cache TTL (seconds); defaults to 24 hours |

### Audit Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `AUDIT_ENABLED` | `true` | Master switch for audit logging |
| `AUDIT_SLOW_QUERY_MS` | `3000` | Slow-query threshold (milliseconds); exceeding it marks `slow=true` |
| `AUDIT_LOG_FILE` | `""` | Audit log file path; when empty, the transport mode determines the default |
| `AUDIT_SUMMARY_INTERVAL` | `300` | Periodic summary interval (seconds); 0 disables |

## Testing

```bash
PYTHONPATH=src pytest tests/ -v
```

Tests mock Zoekt HTTP responses with `respx`, so no real Zoekt service is required.
