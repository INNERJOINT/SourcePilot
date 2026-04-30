"""Verify _infra.sh wrapper delegates to _common.sh exit-code contract."""

from __future__ import annotations

import os

from tests.shell.conftest import PROJ_ROOT, _run_bash

COMMON_SH = str(PROJ_ROOT / "scripts" / "share" / "_common.sh")
INFRA_SH = str(PROJ_ROOT / "scripts" / "share" / "_infra.sh")


def _base_env() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/tmp",
        "TERM": "dumb",
        "NO_COLOR": "1",
    }


def test_infra_require_cmd_missing_propagates_exit_deps():
    """_infra_require_cmd is a thin wrapper around _common_require_cmd → exits EXIT_DEPS=3."""
    script = f"""
        source "{COMMON_SH}"
        source "{INFRA_SH}"
        _infra_require_cmd nonexistent-via-infra-xyz "hint goes here"
    """
    r = _run_bash(script, env=_base_env())
    assert r.returncode == 3, f"expected EXIT_DEPS=3 from infra wrapper, got {r.returncode}\nstderr={r.stderr}"
    assert "nonexistent-via-infra-xyz" in r.stderr
    assert "hint goes here" in r.stderr


def test_infra_require_cmd_present_passes():
    """When the command exists, the wrapper returns 0 and execution continues."""
    script = f"""
        source "{COMMON_SH}"
        source "{INFRA_SH}"
        _infra_require_cmd bash
        echo "OK"
    """
    r = _run_bash(script, env=_base_env())
    assert r.returncode == 0, f"unexpected failure: {r.stderr}"
    assert "OK" in r.stdout
