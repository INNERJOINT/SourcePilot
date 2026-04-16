"""
AOSP Code Search 配置管理

通过环境变量覆盖默认值。
"""

import os

# Zoekt webserver 地址
ZOEKT_URL = os.getenv("ZOEKT_URL", "http://localhost:6070")

# 搜索结果上下文窗口：命中行上下各取多少行
DEFAULT_CONTEXT_LINES = int(os.getenv("DEFAULT_CONTEXT_LINES", "20"))

# ─── Zoekt 高级检索配置 ─────────────────────────────
# 是否启用 BM25 评分（通过 Zoekt search 参数传入）
USE_BM25_SCORING = os.getenv("USE_BM25_SCORING", "true").lower() == "true"
# Zoekt 服务端返回的上下文行数（命中行上下各 N 行）
NUM_CONTEXT_LINES = int(os.getenv("NUM_CONTEXT_LINES", "3"))

# ─── P3：自然语言增强配置 ─────────────────────────────
NL_ENABLED = os.getenv("NL_ENABLED", "true").lower() == "true"
NL_MODEL = os.getenv("NL_MODEL", "deepseek-chat")
NL_API_KEY = os.getenv("NL_API_KEY", "")
NL_API_BASE = os.getenv("NL_API_BASE", "https://api.deepseek.com/v1")
NL_TIMEOUT = float(os.getenv("NL_TIMEOUT", "10.0"))
NL_CACHE_TTL = int(os.getenv("NL_CACHE_TTL", "86400"))

# ─── MCP 鉴权配置 ──────────────────────────────────────
# Streamable HTTP 模式的 Bearer Token 鉴权
# 设置后，客户端需在 HTTP 请求中携带 Authorization: Bearer <token>
MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "")

# ─── Dense 向量检索配置 ──────────────────────────────────
DENSE_ENABLED = os.getenv("DENSE_ENABLED", "false").lower() == "true"
DENSE_VECTOR_DB_URL = os.getenv("DENSE_VECTOR_DB_URL", "http://localhost:19530")
DENSE_COLLECTION_NAME = os.getenv("DENSE_COLLECTION_NAME", "aosp_code")
DENSE_EMBEDDING_URL = os.getenv("DENSE_EMBEDDING_URL", "http://localhost:8080/v1")
DENSE_EMBEDDING_MODEL = os.getenv("DENSE_EMBEDDING_MODEL", "unixcoder-base")
DENSE_EMBEDDING_DIM = int(os.getenv("DENSE_EMBEDDING_DIM", "768"))
DENSE_TOP_K = int(os.getenv("DENSE_TOP_K", "20"))
DENSE_RERANK_BOOST = float(os.getenv("DENSE_RERANK_BOOST", "0.05"))

# ─── 审计日志配置 ──────────────────────────────────────
# 审计日志总开关
AUDIT_ENABLED = os.getenv("AUDIT_ENABLED", "true").lower() == "true"
# 慢查询阈值（毫秒），超过此值标记为 slow=true
AUDIT_SLOW_QUERY_MS = int(os.getenv("AUDIT_SLOW_QUERY_MS", "3000"))
# 审计日志文件路径（空字符串表示由 transport 模式决定默认值）
AUDIT_LOG_FILE = os.getenv("AUDIT_LOG_FILE", "")
# 周期性摘要间隔（秒），0 表示禁用
AUDIT_SUMMARY_INTERVAL = int(os.getenv("AUDIT_SUMMARY_INTERVAL", "300"))
