"""
集成测试配置

将 src/ 加入 Python 路径，提供 gateway 管道测试所需的 fixtures。
"""
import sys
import os

_src_dir = os.path.join(os.path.dirname(__file__), "..", "..", "src")
if _src_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_src_dir))
