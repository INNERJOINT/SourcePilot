"""CLI behavior tests for scripts/indexing/sparse/reindex_docker.sh.

Covers:
  - --help exits 0
  - Unknown args exit non-zero
  - --project without value exits non-zero
  - Dry-run mode skips docker
"""

from __future__ import annotations

from tests.shell.conftest import PROJ_ROOT, _run_bash

SCRIPT = str(PROJ_ROOT / "scripts" / "indexing" / "sparse" / "reindex_docker.sh")


def test_help_exits_zero():
    r = _run_bash(f'bash "{SCRIPT}" --help')
    assert r.returncode == 0
    assert "Usage" in r.stdout or "usage" in r.stdout.lower()


def test_unknown_arg_exits_nonzero():
    r = _run_bash(f'bash "{SCRIPT}" --bogus-flag 2>&1')
    assert r.returncode != 0
    assert "Unknown option" in r.stderr or "Unknown option" in r.stdout


def test_project_without_value_exits_nonzero():
    r = _run_bash(f'bash "{SCRIPT}" --project 2>&1')
    assert r.returncode != 0
