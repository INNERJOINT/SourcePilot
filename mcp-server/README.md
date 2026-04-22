# AOSP Code Search — MCP Access Layer

An MCP (Model Context Protocol) proxy that exposes AOSP code search to AI coding tools such as Claude Code and Cursor.

This service is a thin proxy: it contains no search business logic and forwards every search request over HTTP to the SourcePilot backend.

## Architecture

```
AI tools (Claude Code / Cursor / ...)
        |
        |  MCP protocol (stdio or Streamable HTTP)
        v
+----------------------------------------------+
|  mcp_server.py  entry-point dispatcher        |
|  ├── entry/mcp_stdio.py   stdio transport     |
|  └── entry/mcp_http.py    HTTP transport +    |
|                           auth                |
+----------------------------------------------+
|  entry/handlers.py                            |
|  ├── MCP Server + 6 tool definitions          |
|  ├── aosp:// resource URI reads               |
|  ├── result formatting (LLM-friendly text)    |
|  └── httpx client → SourcePilot API           |
+----------------------------------------------+
        |
        |  HTTP (default http://localhost:9000)
        v
+----------------------------------------------+
|  SourcePilot (src/)                           |
|  Hybrid RAG search engine                     |
+----------------------------------------------+
```

## Prerequisites

**SourcePilot must be running first** — the MCP access layer depends on its HTTP API:

```bash
# Start SourcePilot (defaults to 0.0.0.0:9000)
scripts/run_sourcepilot.sh
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SOURCEPILOT_URL` | `http://localhost:9000` | SourcePilot backend address |
| `MCP_AUTH_TOKEN` | `""` | Bearer-token auth for Streamable HTTP mode; empty disables auth |

## Running

### stdio mode (local AI tools)

For local tools such as Claude Code or Cursor that speak MCP over stdin/stdout:

```bash
scripts/run_mcp.sh
```

Add to your Claude Code config:

```json
{
  "mcpServers": {
    "aosp-code-search": {
      "command": "/path/to/scripts/run_mcp.sh"
    }
  }
}
```

### Streamable HTTP mode (remote access)

For remote clients connecting over HTTP; endpoint is `/mcp`:

```bash
scripts/run_mcp.sh --transport streamable-http --port 8888
```

When `MCP_AUTH_TOKEN` is set, clients must include `Authorization: Bearer <token>`.

## MCP Tools

Six search tools are exposed:

### search_code

Search the AOSP codebase. Supports keywords, class names, function names, file paths, attribute names, and more. When SourcePilot has NL enhancement enabled, natural-language queries automatically trigger semantic retrieval.

```
search_code(query="SystemServer startBootstrapServices", lang="java", repo="frameworks/base")
```

### search_symbol

Exact search for code symbols (class names, function names, variable names) using the Zoekt `sym:` prefix.

```
search_symbol(symbol="ActivityManagerService", lang="java")
```

### search_file

Search for code files by name or path using the Zoekt `file:` prefix.

```
search_file(path="SystemServer.java", query="startBootstrapServices")
```

### search_regex

Regex-based code search for complex pattern matching.

```
search_regex(pattern="func\\s+\\w+\\s*\\(", lang="go")
```

### list_repos

List repositories in the AOSP codebase, optionally filtered by keyword.

```
list_repos(query="frameworks")
```

### get_file_content

Read the full contents of an AOSP source file or a specified line range. Use `search_file` first to locate the file's `repo` and `filepath`, then read it with this tool.

```
get_file_content(repo="frameworks/base", filepath="core/java/android/os/Process.java", start_line=100, end_line=200)
```

## MCP Resources

The `aosp://` resource URI is supported and can be read directly through the MCP Resources protocol:

```
aosp://{repo}/{filepath}
```

Example:

```
aosp://frameworks/base/core/java/android/os/Process.java
```

The URI template is advertised via `list_resource_templates`, so AI tools can discover it automatically.
