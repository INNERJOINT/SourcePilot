"""CLI behavior tests for scripts/testing/test_dense.sh.

Covers:
  - --help exits 0 with usage text
"""

from __future__ import annotations

from tests.shell.conftest import PROJ_ROOT, _run_bash

TEST_DENSE_SH = str(PROJ_ROOT / "scripts" / "testing" / "test_dense.sh")


def test_dense_help_exits_zero():
    """--help prints usage and exits 0."""
    r = _run_bash(f'bash "{TEST_DENSE_SH}" --help')
    assert r.returncode == 0
    assert "Usage" in r.stdout or "usage" in r.stdout.lower()
