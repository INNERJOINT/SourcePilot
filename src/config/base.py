"""
AOSP Code Search configuration management

Default values can be overridden via environment variables.
"""

import os

# Zoekt webserver address
ZOEKT_URL = os.getenv("ZOEKT_URL", "http://localhost:6070")

# Search result context window: number of lines above and below each hit
DEFAULT_CONTEXT_LINES = int(os.getenv("DEFAULT_CONTEXT_LINES", "20"))

# ─── Zoekt advanced search configuration ──────────────────────────────
# Whether to enable BM25 scoring (passed via Zoekt search parameters)
USE_BM25_SCORING = os.getenv("USE_BM25_SCORING", "true").lower() == "true"
# Number of context lines returned by the Zoekt server (N lines above and below each hit)
NUM_CONTEXT_LINES = int(os.getenv("NUM_CONTEXT_LINES", "3"))

# ─── Natural language enhancement configuration ───────────────────────
NL_ENABLED = os.getenv("NL_ENABLED", "true").lower() == "true"
NL_MODEL = os.getenv("NL_MODEL", "deepseek-chat")
NL_API_KEY = os.getenv("NL_API_KEY", "")
NL_API_BASE = os.getenv("NL_API_BASE", "https://api.deepseek.com/v1")
NL_TIMEOUT = float(os.getenv("NL_TIMEOUT", "10.0"))
NL_CACHE_TTL = int(os.getenv("NL_CACHE_TTL", "86400"))

# ─── MCP authentication configuration ─────────────────────────────────
# Bearer token authentication for Streamable HTTP mode.
# When set, clients must include Authorization: Bearer <token> in HTTP requests.
MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "")

# ─── Dense vector retrieval configuration ─────────────────────────────
DENSE_ENABLED = os.getenv("DENSE_ENABLED", "false").lower() == "true"
DENSE_VECTOR_DB_URL = os.getenv("DENSE_VECTOR_DB_URL", "http://localhost:6333")
DENSE_COLLECTION_NAME = os.getenv("DENSE_COLLECTION_NAME", "aosp_code")
DENSE_EMBEDDING_URL = os.getenv("DENSE_EMBEDDING_URL", "http://localhost:8080/v1")
# DENSE_EMBEDDING_MODEL is a legacy gateway-side default. ProjectConfig.embedding_model
# (config/projects.yaml) overrides it for all real traffic. The embedding-server's
# active code model is selected by CODE_EMBEDDING_MODEL on the server, not here.
DENSE_EMBEDDING_MODEL = os.getenv("DENSE_EMBEDDING_MODEL", "unixcoder-base")
DENSE_EMBEDDING_MODEL_CODE = os.getenv("DENSE_EMBEDDING_MODEL_CODE", "nomic-ai/CodeRankEmbed")
DENSE_EMBEDDING_MODEL_ZH = os.getenv("DENSE_EMBEDDING_MODEL_ZH", "BAAI/bge-base-zh-v1.5")
DENSE_EMBEDDING_DIM = int(os.getenv("DENSE_EMBEDDING_DIM", "768"))
DENSE_TOP_K = int(os.getenv("DENSE_TOP_K", "20"))
DENSE_RERANK_BOOST = float(os.getenv("DENSE_RERANK_BOOST", "0.05"))

# ─── Structural retrieval configuration ───────────────────────────────
# Whether to enable the structural (Neo4j) retrieval lane
STRUCTURAL_ENABLED = os.getenv("STRUCTURAL_ENABLED", "false").lower() == "true"
# Neo4j Bolt connection URI
STRUCTURAL_NEO4J_URI = os.getenv("STRUCTURAL_NEO4J_URI", "bolt://localhost:7687")
# Neo4j username
STRUCTURAL_NEO4J_USER = os.getenv("STRUCTURAL_NEO4J_USER", "neo4j")
# Neo4j password
STRUCTURAL_NEO4J_PASSWORD = os.getenv("STRUCTURAL_NEO4J_PASSWORD", "sourcepilot")
# Structural retrieval lane timeout (milliseconds)
STRUCTURAL_LANE_TIMEOUT_MS = int(os.getenv("STRUCTURAL_LANE_TIMEOUT_MS", "2000"))

# ─── Audit log configuration ───────────────────────────────────────────
# Master switch for audit logging
AUDIT_ENABLED = os.getenv("AUDIT_ENABLED", "true").lower() == "true"
# Slow-query threshold (milliseconds); queries exceeding this are marked slow=true
AUDIT_SLOW_QUERY_MS = int(os.getenv("AUDIT_SLOW_QUERY_MS", "3000"))
# Audit log file path (empty string means the default is determined by transport mode)
AUDIT_LOG_FILE = os.getenv("AUDIT_LOG_FILE", "")
# Periodic summary interval (seconds); 0 disables summaries
AUDIT_SUMMARY_INTERVAL = int(os.getenv("AUDIT_SUMMARY_INTERVAL", "300"))
