"""
SourcePilot unit test configuration

Adds src/ to the Python path so tests can import SourcePilot modules directly.
"""
import sys
import os

# Add src/ to the Python path
_src_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "src")
if _src_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_src_dir))
