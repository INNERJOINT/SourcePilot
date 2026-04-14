"""
SourcePilot 单元测试配置

将 src/ 加入 Python 路径，使测试能直接 import SourcePilot 模块。
"""
import sys
import os

# 将 src/ 加入 Python 路径
_src_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "src")
if _src_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_src_dir))
