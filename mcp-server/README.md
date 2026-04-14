# AOSP Code Search MCP 接入层

MCP (Model Context Protocol) 协议代理，为 AI 编码工具（Claude Code、Cursor 等）提供 AOSP 代码搜索能力。

本服务是一个薄代理层，自身不包含搜索业务逻辑，所有搜索请求通过 HTTP 转发给 SourcePilot 后端服务处理。

## 架构

```
AI 工具 (Claude Code / Cursor / ...)
        |
        |  MCP 协议 (stdio 或 Streamable HTTP)
        v
+----------------------------------------------+
|  mcp_server.py  入口分发                      |
|  ├── entry/mcp_stdio.py   stdio 传输          |
|  └── entry/mcp_http.py    HTTP 传输 + 鉴权    |
+----------------------------------------------+
|  entry/handlers.py                            |
|  ├── MCP Server + 6 个工具定义                |
|  ├── aosp:// 资源 URI 读取                    |
|  ├── 结果格式化（LLM 友好文本）               |
|  └── httpx 客户端 → SourcePilot API           |
+----------------------------------------------+
        |
        |  HTTP (默认 http://localhost:9000)
        v
+----------------------------------------------+
|  SourcePilot (src/)                           |
|  混合 RAG 检索引擎                             |
+----------------------------------------------+
```

## 前置依赖

**必须先启动 SourcePilot 服务**，MCP 接入层依赖其 HTTP API：

```bash
# 启动 SourcePilot（默认 0.0.0.0:9000）
scripts/run_sourcepilot.sh
```

## 配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `SOURCEPILOT_URL` | `http://localhost:9000` | SourcePilot 后端服务地址 |
| `MCP_AUTH_TOKEN` | `""` | Streamable HTTP 模式的 Bearer Token 鉴权，为空则不启用鉴权 |

## 启动

### stdio 模式（本地 AI 工具）

供 Claude Code、Cursor 等本地工具通过 stdin/stdout 直接调用：

```bash
scripts/run_mcp.sh
```

在 Claude Code 配置中添加：

```json
{
  "mcpServers": {
    "aosp-code-search": {
      "command": "/path/to/scripts/run_mcp.sh"
    }
  }
}
```

### Streamable HTTP 模式（远程访问）

供远程客户端通过 HTTP 访问，端点为 `/mcp`：

```bash
scripts/run_mcp.sh --transport streamable-http --port 8888
```

若设置了 `MCP_AUTH_TOKEN`，客户端需在请求中携带 `Authorization: Bearer <token>`。

## MCP 工具

提供 6 个搜索工具：

### search_code

搜索 AOSP 代码库。支持关键词、类名、函数名、文件路径、属性名等。当 SourcePilot 开启 NL 增强时，自然语言查询会自动触发语义级检索。

```
search_code(query="SystemServer startBootstrapServices", lang="java", repo="frameworks/base")
```

### search_symbol

精确搜索代码符号（类名、函数名、变量名），使用 Zoekt `sym:` 前缀。

```
search_symbol(symbol="ActivityManagerService", lang="java")
```

### search_file

按文件名或路径搜索代码文件，使用 Zoekt `file:` 前缀。

```
search_file(path="SystemServer.java", query="startBootstrapServices")
```

### search_regex

使用正则表达式搜索代码，适合复杂模式匹配。

```
search_regex(pattern="func\\s+\\w+\\s*\\(", lang="go")
```

### list_repos

列出 AOSP 代码库中的仓库列表，可按关键词过滤。

```
list_repos(query="frameworks")
```

### get_file_content

读取 AOSP 代码文件的完整内容或指定行范围。先用 `search_file` 找到文件的 `repo` 和 `filepath`，再用此工具读取。

```
get_file_content(repo="frameworks/base", filepath="core/java/android/os/Process.java", start_line=100, end_line=200)
```

## MCP 资源

支持 `aosp://` 资源 URI，可直接通过 MCP Resources 协议读取 AOSP 源码文件：

```
aosp://{repo}/{filepath}
```

示例：

```
aosp://frameworks/base/core/java/android/os/Process.java
```

URI 模板已通过 `list_resource_templates` 声明，AI 工具可自动发现。
