"""
Integration test configuration

Adds src/ to the Python path and provides fixtures required by gateway pipeline tests.
"""
import sys
import os

_src_dir = os.path.join(os.path.dirname(__file__), "..", "..", "src")
if _src_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_src_dir))
