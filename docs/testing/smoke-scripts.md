# Live Smoke Scripts

> Audience: **release engineer / live-system tester**. Read this when you need
> to verify a real, running stack (Zoekt + Milvus + Embedding + SourcePilot
> + sp-cockpit + optionally MCP) end-to-end. None of these scripts run under
> `pytest`; they are bash + curl + jq + sqlite3.

## Inventory

| Script | Target | Dependencies | Exit semantics |
|--------|--------|--------------|----------------|
| [`scripts/smoke_queries.sh`](#scriptssmoke_queriessh) | live SourcePilot (`:9000`) + audit.db | bash, curl, jq, sqlite3, uuidgen-or-openssl, GNU date | `0` all PASS + audit OK · `1` any FAIL or audit fail · `2` precondition failed |
| [`scripts/test_dense.sh`](#scriptstest_densesh) | live SourcePilot (`:9000`) + `audit.log` | bash, curl, jq | `0` dense search reachable (warns if no results) · `1` HTTP/audit failure · `2` SourcePilot unreachable |
| [`tests/test_mcp_endpoints.sh`](#teststest_mcp_endpointssh) | live MCP server (`:8888/mcp` streamable-HTTP) | bash, curl | non-zero on session-id failure; otherwise informational |

## Common prerequisites

Before any of these scripts is meaningful, bring the real stack up via
`scripts/run_all.sh` (per `CLAUDE.md`):

```bash
cp .env.example .env       # edit values
scripts/run_all.sh         # starts zoekt + SourcePilot (+ optionally MCP/sp-cockpit)
```

`scripts/smoke_queries.sh` and `scripts/test_dense.sh` additionally require:

- **`DENSE_ENABLED=true`** when starting SourcePilot (otherwise the `dense_search` stage never appears).
- **Milvus** running (default `localhost:19530`) with the `frameworks/base` collection indexed.
- **Embedding service** running (default `localhost:8080`).
- **`sp-cockpit`** running on `:9100` so it can tail `audit.log` and populate `sp-cockpit/data/audit.db` (smoke_queries inspects the SQLite DB, not the JSONL).

## `scripts/smoke_queries.sh`

The flagship live-stack verifier. Fires 8 query cases against SourcePilot,
generates a fresh `trace_id` per case, then queries `sp-cockpit/data/audit.db`
to verify each pipeline stage actually ran with the right `records_count`.

### What it tests (8 cases)

| # | Case name | Endpoint | Payload | Expected behavior |
|---|-----------|----------|---------|-------------------|
| 1 | `zoekt_keyword` | `/api/search` | `{"query":"binder_open","top_k":5}` | Plain keyword → Zoekt path, dense not required |
| 2 | `nl_inscope_dense` | `/api/search` | `{"query":"binder 驱动的权限校验机制","top_k":5}` | NL query in scope of `frameworks/base` index → dense returns hits |
| 3 | `nl_outscope_dense` | `/api/search` | `{"query":"Launcher3 桌面布局加载流程","top_k":5}` | NL query out of scope → dense returns 0 (correctness signal) |
| 4 | `symbol` | `/api/search_symbol` | `{"symbol":"startBootstrapServices","top_k":3}` | Symbol search via Zoekt |
| 5 | `file` | `/api/search_file` | `{"path":"AndroidManifest.xml","top_k":3}` | Filename search |
| 6 | `regex` | `/api/search_regex` | `{"pattern":"binder_[a-z_]+","top_k":3}` | Regex search |
| 7 | `list_repos` | `/api/list_repos` | `{"query":"","top_k":5}` | Repository listing |
| 8 | `get_file` | `/api/get_file_content` | `{"repo":"frameworks/base","filepath":"core/java/android/os/Binder.java","start_line":1,"end_line":40}` | File-content slice (HTML `<pre>` parsed by ZoektAdapter); marked `optional` (warn-only) and `dict` shape |

### Audit DB validation

After each case, the script polls
`sp-cockpit/data/audit.db` (path overridable via `AUDIT_DB`):

```sql
SELECT count(*) FROM events
 WHERE stage='dense_search' AND trace_id='<probe>'
```

It verifies that the expected stages (`classify`, `rewrite`, `dense_search`,
`rrf_merge`, `rerank`) appear for the case's trace_id, and that `records_count`
in `stage_result` matches semantic expectation (in-scope dense > 0,
out-of-scope dense == 0).

### Pre-flight (early exit code 2)

The script aborts with exit code `2` if any of these fail:

1. Required tool missing (`curl`, `jq`, `sqlite3`, and one of `uuidgen` / `openssl`).
2. `sp-cockpit/data/audit.db` does not exist (sp-cockpit not running).
3. SourcePilot health endpoint (`GET /api/health`) does not respond within `TIMEOUT` (default 15s).
4. **Dense probe**: a single `binder 驱动权限校验 probe` query is fired; if no
   `dense_search` stage row appears in `audit.db` within 3 seconds, the script
   prints "Set `DENSE_ENABLED=true`, ensure Milvus is running with
   `frameworks/base` indexed, and restart SourcePilot." and exits 2.

### Reading the output

```text
[1/8] zoekt_keyword           ... PASS  (HTTP 200, 5 results, 142ms)
[2/8] nl_inscope_dense        ... PASS  (HTTP 200, 5 results, dense=3)
...
=== Audit verification ===
trace=abcd... stages: classify rewrite dense_search rrf_merge rerank   OK
...
Summary: 8 PASS / 0 FAIL / 0 SKIP   audit: OK
```

A non-zero exit means **at least one** case failed HTTP, returned a wrong
shape, or its audit chain was missing/wrong.

### Useful overrides

| Env var | Default | Purpose |
|---------|---------|---------|
| `SOURCEPILOT_URL` | `http://localhost:9000` | Target SourcePilot HTTP API |
| `TIMEOUT` | `15` | Per-request timeout (seconds) |
| `AUDIT_DB` | `sp-cockpit/data/audit.db` | Where to look for sp-cockpit's SQLite DB |

## `scripts/test_dense.sh`

A focused, single-query verifier for the dense search path. Useful for
"is dense alive at all?" smoke checks during local development.

### Behavior

1. Health-checks SourcePilot at `$SOURCEPILOT_URL/api/health`.
2. Generates a `trace_id`.
3. Sends one NL query: `"binder 驱动的权限校验机制"` to `/api/search` with `top_k=5`.
4. Reports response status, total result count, and how many results have
   `source == "dense"` vs other.
5. Greps `audit.log` (path `AUDIT_LOG`, default `./audit.log`) for that
   trace_id and verifies the `dense_search` stage was emitted with a
   `records_count`. If `audit.log` is missing, the audit check is skipped
   with a warning (this script reads the JSONL directly, **not** `audit.db`).

### Differences vs `smoke_queries.sh`

| | `smoke_queries.sh` | `test_dense.sh` |
|---|--------------------|-----------------|
| Cases | 8 | 1 |
| Audit source | `sp-cockpit/data/audit.db` (SQLite via sp-cockpit) | `audit.log` (raw JSONL) |
| Requires sp-cockpit running? | Yes | No |
| Exit on no dense results | FAIL (case 2) | WARN (script still exits 0) |

Use `test_dense.sh` when sp-cockpit is not running; use `smoke_queries.sh`
for full release verification.

## `tests/test_mcp_endpoints.sh`

A bash + curl exerciser for the MCP server's **streamable-HTTP** transport.
It does **not** use `pytest`, and it does **not** target SourcePilot directly —
it goes through the MCP protocol.

### Prerequisites

```bash
scripts/run_mcp.sh --transport streamable-http --port 8888
```

### Behavior

1. Opens an SSE connection to `http://localhost:8888/mcp` and extracts the
   `mcp-session-id` header (the script greps `(?<=mcp-session-id: ).*`).
2. Sends three JSON-RPC `tools/call` requests covering the three tools the
   MCP layer exposes:
   - `search_file`
   - `search_symbol`
   - `search_code`
3. Prints each request/response pair.

The script uses a temporary SSE sink and kills the background `curl` SSE
process on exit. Failure to obtain a session ID exits non-zero with
"❌ 错误: 无法获取 Session ID".

### When to use it

- Verifying the MCP server is up after `scripts/run_mcp.sh --transport streamable-http`.
- Reproducing a bug report against the streamable-HTTP transport without
  pulling in a Python MCP client.
- Smoke-testing the `BearerTokenMiddleware` interaction (set `MCP_AUTH_TOKEN`
  appropriately on both server and client).

## Failure modes (cross-script)

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `smoke_queries.sh` exits 2 with "audit.db 不存在" | sp-cockpit not running, or wrong `AUDIT_DB` path | Start sp-cockpit (port 9100); set `AUDIT_DB=sp-cockpit/data/audit.db` |
| `smoke_queries.sh` exits 2 with "dense_search stage not seen" | `DENSE_ENABLED` not true, Milvus down, or `frameworks/base` not indexed | Re-export `DENSE_ENABLED=true` and restart SourcePilot |
| `test_dense.sh` warns "audit.log 不存在" | SourcePilot configured to write audit elsewhere or audit disabled | Set `AUDIT_LOG=...` or check SourcePilot env |
| `test_mcp_endpoints.sh` "无法获取 Session ID" | MCP not started in `streamable-http` mode, or wrong port | Start with `scripts/run_mcp.sh --transport streamable-http --port 8888` |
| Any script: `command not found: jq` | `jq` not installed | `apt install jq` (or platform equivalent) |

## See also

- [pytest-suite.md](./pytest-suite.md) — for the in-process (mocked) test layers
- [architecture.md](./architecture.md) — request-flow diagram including audit.db
- [troubleshooting.md](./troubleshooting.md) — broader failure patterns
