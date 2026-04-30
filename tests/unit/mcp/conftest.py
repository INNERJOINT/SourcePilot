"""
MCP 层单元测试配置

将 mcp-server/ 加入 Python 路径，使测试能直接 import MCP 模块。
"""
import os
import sys

import pytest

# 将 mcp-server/ 加入 Python 路径
_mcp_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "mcp-server")
if _mcp_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_mcp_dir))


@pytest.fixture(autouse=True)
def _set_sourcepilot_url(monkeypatch):
    monkeypatch.setenv("SOURCEPILOT_URL", "http://mock-sourcepilot:9000")
