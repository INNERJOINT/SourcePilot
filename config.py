"""
Query API 配置管理

通过环境变量覆盖默认值。
"""

import os

# Zoekt webserver 地址
ZOEKT_URL = os.getenv("ZOEKT_URL", "http://localhost:6070")

# API 鉴权密钥 —— Dify 连接时需要填写此 Key
API_KEY = os.getenv("API_KEY", "your-api-key")

# 搜索结果上下文窗口：命中行上下各取多少行
DEFAULT_CONTEXT_LINES = int(os.getenv("DEFAULT_CONTEXT_LINES", "20"))

# 服务监听配置
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "445"))

# ─── P3：自然语言增强配置 ─────────────────────────────
NL_ENABLED = os.getenv("NL_ENABLED", "true").lower() == "true"
NL_MODEL = os.getenv("NL_MODEL", "deepseek-chat")
NL_API_KEY = os.getenv("NL_API_KEY", "")
NL_API_BASE = os.getenv("NL_API_BASE", "https://api.deepseek.com/v1")
NL_TIMEOUT = float(os.getenv("NL_TIMEOUT", "10.0"))
NL_CACHE_TTL = int(os.getenv("NL_CACHE_TTL", "86400"))
