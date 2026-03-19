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
