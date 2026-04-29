"""CLI behavior tests for scripts/testing/verify.sh.

Covers:
  - --help exits 0 with usage text
  - Invalid subcommand exits non-zero with error message
  - No args exits non-zero
"""

from __future__ import annotations

from tests.shell.conftest import PROJ_ROOT, _run_bash

VERIFY_SH = str(PROJ_ROOT / "scripts" / "testing" / "verify.sh")


def test_verify_help_exits_zero():
    """--help prints usage and exits 0."""
    r = _run_bash(f'bash "{VERIFY_SH}" --help')
    assert r.returncode == 0
    assert "Usage" in r.stdout or "usage" in r.stdout.lower()


def test_verify_invalid_subcommand_exits_nonzero():
    """Invalid subcommand causes a non-zero exit with error message."""
    r = _run_bash(f'bash "{VERIFY_SH}" bogus-cmd 2>&1')
    assert r.returncode != 0
    assert r.stdout or r.stderr


def test_verify_no_args_exits_nonzero():
    """No arguments cause a non-zero exit."""
    r = _run_bash(f'bash "{VERIFY_SH}" 2>&1')
    assert r.returncode != 0
