# SourcePilot

混合 RAG 检索引擎，为 AOSP 代码库提供代码搜索 + 自然语言增强能力。

基于 Zoekt 全文搜索引擎，通过 NL 分类、LLM Query Rewrite、多路并行检索、RRF 融合、Feature Rerank 等技术，将传统代码搜索提升为语义级检索服务。对外暴露 HTTP REST API，供 MCP 接入层或其他客户端调用。

## 架构

```
                        HTTP Request
                            |
                            v
+----------------------------------------------------------+
|  app.py (Starlette HTTP API)                             |
|  7 个 REST 端点 + 审计日志 + trace_id 管理              |
+----------------------------------------------------------+
                            |
                            v
+----------------------------------------------------------+
|  gateway/                                                |
|  +--------------------------+                            |
|  | gateway.py  主编排器     |                            |
|  |  classify -> NL/exact    |                            |
|  +--------------------------+                            |
|  | nl/classifier.py  意图分类（规则优先）                |
|  | nl/rewriter.py    LLM 改写 + 关键词降级              |
|  | nl/cache.py       LRU 缓存 + concept_map             |
|  +--------------------------+                            |
|  | fusion.py    RRF 融合（多路结果去重合并）             |
|  | ranker.py    Feature-based 轻量重排                   |
|  | router.py    查询路由 & 并行分发                      |
|  +--------------------------+                            |
+----------------------------------------------------------+
                            |
                            v
+----------------------------------------------------------+
|  adapters/                                               |
|  +------------------------------------------------------+|
|  | base.py       SearchAdapter ABC + 统一数据结构       ||
|  | zoekt.py      ZoektAdapter — Zoekt HTTP 客户端       ||
|  | feishu.py     FeishuAdapter（预留）                   ||
|  +------------------------------------------------------+|
+----------------------------------------------------------+
          |                                |
          v                                v
+--------------------+        +------------------------+
| config/            |        | observability/         |
| base.py 环境变量   |        | audit.py 结构化 JSON   |
| backends.py 后端   |        | 审计日志 + trace_id    |
+--------------------+        +------------------------+
```

### 请求处理流程

1. HTTP 请求到达 `app.py` 对应端点
2. 解析参数，生成/透传 `trace_id`
3. 调用 `gateway.search()` 等函数进入业务逻辑层
4. 对于 `search` 端点：
   - **意图分类**：`classifier.py` 判断查询是 `exact`（精确）还是 `natural_language`（自然语言）
   - **精确查询**：直接调用 `ZoektAdapter.search_zoekt()`
   - **NL 查询**：LLM Rewrite -> 多路 Zoekt 并行查询 -> RRF 融合 -> Feature Rerank
5. 返回 JSON 结果

## 启动

```bash
# 方式一：使用启动脚本（推荐）
scripts/run_sourcepilot.sh
scripts/run_sourcepilot.sh --host 127.0.0.1 --port 9001

# 方式二：直接 uvicorn
PYTHONPATH=src uvicorn app:app --host 0.0.0.0 --port 9000
```

默认监听 `0.0.0.0:9000`。

## HTTP API

所有搜索端点均为 `POST`，请求体为 JSON。

### GET /api/health

健康检查。

**响应：**
```json
{"status": "ok", "service": "sourcepilot"}
```

---

### POST /api/search

统一搜索入口，支持精确搜索和自然语言增强搜索。

**请求体：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `query` | string | 是 | - | 搜索查询（关键词、符号名、自然语言均可） |
| `top_k` | int | 否 | 10 | 返回结果数量 |
| `score_threshold` | float | 否 | 0.0 | 最低分数阈值，低于此分数的结果被过滤 |
| `repos` | string | 否 | null | 限定搜索的仓库名前缀（如 `frameworks/base`） |
| `lang` | string | 否 | null | 按编程语言过滤（如 `java`, `cpp`, `go`） |
| `branch` | string | 否 | null | 按分支名过滤（如 `main`, `android-14.0.0_r1`） |
| `case_sensitive` | string | 否 | `"auto"` | 大小写敏感模式：`auto`（含大写则敏感）、`yes`、`no` |

**请求示例：**
```json
{
  "query": "SystemServer startBootstrapServices",
  "top_k": 5,
  "repos": "frameworks/base",
  "lang": "java"
}
```

**响应：** 返回结果数组，每个元素包含 `title`、`content`、`metadata`（含 `repo`、`path`、`start_line`、`end_line`、`score`）等字段。

---

### POST /api/search_symbol

精确搜索代码符号（类名、函数名、变量名），使用 Zoekt `sym:` 前缀。

**请求体：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `symbol` | string | 是 | - | 符号名（类名、函数名等） |
| `top_k` | int | 否 | 5 | 返回结果数量 |
| `repos` | string | 否 | null | 仓库名前缀过滤 |
| `lang` | string | 否 | null | 编程语言过滤 |
| `branch` | string | 否 | null | 分支名过滤 |
| `case_sensitive` | string | 否 | `"auto"` | 大小写敏感模式 |

**请求示例：**
```json
{
  "symbol": "ActivityManagerService",
  "lang": "java"
}
```

---

### POST /api/search_file

按文件名或路径搜索代码文件，使用 Zoekt `file:` 前缀。

**请求体：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `path` | string | 是 | - | 文件名或路径模式（如 `SystemServer.java`） |
| `extra_query` | string | 否 | `""` | 在匹配文件中进一步搜索的关键词 |
| `top_k` | int | 否 | 5 | 返回结果数量 |
| `lang` | string | 否 | null | 编程语言过滤 |
| `branch` | string | 否 | null | 分支名过滤 |
| `case_sensitive` | string | 否 | `"auto"` | 大小写敏感模式 |

**请求示例：**
```json
{
  "path": "SystemServer.java",
  "extra_query": "startBootstrapServices"
}
```

---

### POST /api/search_regex

使用正则表达式搜索代码，适合复杂模式匹配。

**请求体：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `pattern` | string | 是 | - | 正则表达式模式 |
| `top_k` | int | 否 | 10 | 返回结果数量 |
| `repos` | string | 否 | null | 仓库名前缀过滤 |
| `lang` | string | 否 | null | 编程语言过滤 |

**请求示例：**
```json
{
  "pattern": "func\\s+\\w+\\s*\\(",
  "lang": "go",
  "top_k": 20
}
```

---

### POST /api/list_repos

列出 AOSP 代码库中的仓库列表，可按关键词过滤。

**请求体：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `query` | string | 否 | `""` | 仓库名过滤关键词 |
| `top_k` | int | 否 | 50 | 返回数量上限 |

**请求示例：**
```json
{
  "query": "frameworks",
  "top_k": 20
}
```

---

### POST /api/get_file_content

读取 AOSP 代码文件的完整内容（或指定行范围）。

**请求体：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `repo` | string | 是 | - | 仓库名（从搜索结果的 `repo` 字段获取） |
| `filepath` | string | 是 | - | 文件路径（从搜索结果的 `path` 字段获取，不含 repo 前缀） |
| `start_line` | int | 否 | 1 | 起始行号（从 1 开始） |
| `end_line` | int | 否 | null | 结束行号（默认读取到文件末尾） |

**请求示例：**
```json
{
  "repo": "frameworks/base",
  "filepath": "core/java/android/os/Process.java",
  "start_line": 100,
  "end_line": 200
}
```

**响应：**
```json
{
  "content": "...(源码内容)...",
  "total_lines": 850,
  "start_line": 100,
  "end_line": 200
}
```

---

### 错误响应

所有端点在出错时返回统一格式：

```json
{"error": "错误描述信息"}
```

常见状态码：
- `400` — 参数缺失或格式错误
- `404` — 文件未找到
- `500` — 服务内部错误
- `502` — Zoekt 后端不可达

### 请求追踪

所有端点支持 `X-Trace-Id` 请求头，用于链路追踪。若未提供，服务端将自动生成。

## 配置

所有配置通过环境变量管理，在 `config/base.py` 中 import 时一次性加载（非每次请求读取）。

### Zoekt 连接

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `ZOEKT_URL` | `http://localhost:6070` | Zoekt webserver 地址 |

### 自然语言增强

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `NL_ENABLED` | `true` | 是否启用 NL 增强搜索管线 |
| `NL_MODEL` | `deepseek-chat` | LLM 模型名称 |
| `NL_API_KEY` | `""` | LLM API Key |
| `NL_API_BASE` | `https://api.deepseek.com/v1` | LLM API Base URL |
| `NL_TIMEOUT` | `10.0` | LLM 调用超时（秒），超时后降级为关键词搜索 |
| `NL_CACHE_TTL` | `86400` | NL 重写缓存 TTL（秒），默认 24 小时 |

### 审计日志

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `AUDIT_ENABLED` | `true` | 审计日志总开关 |
| `AUDIT_SLOW_QUERY_MS` | `3000` | 慢查询阈值（毫秒），超过标记为 `slow=true` |
| `AUDIT_LOG_FILE` | `""` | 审计日志文件路径（空则由 transport 模式决定默认值） |
| `AUDIT_SUMMARY_INTERVAL` | `300` | 周期性统计摘要间隔（秒），0 表示禁用 |

## 测试

```bash
PYTHONPATH=src pytest tests/ -v
```

测试使用 `respx` mock Zoekt HTTP 响应，无需真实 Zoekt 服务。
