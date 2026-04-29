"""CLI behavior tests for scripts/indexing/sparse/reindex.sh.

Covers:
  - --help exits 0 with usage text
  - Unknown args exit non-zero with error message
  - --project without value exits non-zero
"""

from __future__ import annotations

from tests.shell.conftest import PROJ_ROOT, _run_bash

REINDEX_SH = str(PROJ_ROOT / "scripts" / "indexing" / "sparse" / "reindex.sh")


def test_help_exits_zero():
    """--help prints usage and exits 0."""
    r = _run_bash(f'bash "{REINDEX_SH}" --help')
    assert r.returncode == 0
    assert "Usage" in r.stdout or "usage" in r.stdout.lower()


def test_unknown_arg_exits_nonzero():
    """Unknown arguments cause a non-zero exit with error message."""
    r = _run_bash(f'bash "{REINDEX_SH}" --bogus-flag 2>&1')
    assert r.returncode != 0
    assert "Unknown option" in r.stderr or "Unknown option" in r.stdout


def test_project_without_value_exits_nonzero():
    """--project without a following name exits non-zero."""
    r = _run_bash(f'bash "{REINDEX_SH}" --project 2>&1')
    assert r.returncode != 0
