"""
端到端测试配置

同时将 src/ 和 mcp-server/ 加入 Python 路径。
提供真实服务器启动/关闭 fixtures。
"""
import sys
import os

_src_dir = os.path.join(os.path.dirname(__file__), "..", "..", "src")
_mcp_dir = os.path.join(os.path.dirname(__file__), "..", "..", "mcp-server")
for d in [_src_dir, _mcp_dir]:
    if d not in sys.path:
        sys.path.insert(0, os.path.abspath(d))
