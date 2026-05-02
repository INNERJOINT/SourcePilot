"""
End-to-end test configuration

Adds both src/ and mcp-server/ to the Python path.
Provides fixtures for real server startup/shutdown.
"""
import os
import sys
from pathlib import Path

import pytest

_src_dir = os.path.join(os.path.dirname(__file__), "..", "..", "src")
_mcp_dir = os.path.join(os.path.dirname(__file__), "..", "..", "mcp-server")
for d in [_src_dir, _mcp_dir]:
    if d not in sys.path:
        sys.path.insert(0, os.path.abspath(d))


@pytest.fixture(autouse=True, scope="function")
def _isolated_audit_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect AUDIT_LOG_FILE to a per-test tmp directory.

    Prevents e2e tests from writing to or polluting audit.log in the repo root.
    """
    monkeypatch.setenv("AUDIT_LOG_FILE", str(tmp_path / "audit.log"))
