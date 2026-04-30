"""CLI behavior tests for scripts/indexing/structural/build_structural_index_batch.sh.

Covers:
  - --help exits 0
  - Rejects managed args (--source-root, --project-name, --repo-name)
"""

from __future__ import annotations

from tests.shell.conftest import PROJ_ROOT, _run_bash

SCRIPT = str(
    PROJ_ROOT / "scripts" / "indexing" / "structural" / "build_structural_index_batch.sh"
)


def test_help_exits_zero():
    r = _run_bash(f'bash "{SCRIPT}" --help')
    assert r.returncode == 0


def test_rejects_source_root():
    """--source-root is managed by the batch script and should be rejected."""
    r = _run_bash(f'bash "{SCRIPT}" --source-root /some/path')
    assert r.returncode == 2
    assert "managed" in r.stderr.lower()


def test_rejects_project_name():
    r = _run_bash(f'bash "{SCRIPT}" --project-name foo')
    assert r.returncode == 2
    assert "managed" in r.stderr.lower()


def test_rejects_repo_name():
    r = _run_bash(f'bash "{SCRIPT}" --repo-name bar')
    assert r.returncode == 2
    assert "managed" in r.stderr.lower()


def test_rejects_equals_form():
    r = _run_bash(f'bash "{SCRIPT}" --source-root=/some/path')
    assert r.returncode == 2
