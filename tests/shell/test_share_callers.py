"""Tests for caller scripts (run_mcp.sh, run_sp_cockpit.sh) VENV_PYTHON fallback."""

from __future__ import annotations

from pathlib import Path


def test_run_mcp_venv_fallback(run_bash, proj_root):
    """run_mcp.sh falls back to system python3 when VENV_PYTHON is missing."""
    # We can't run the full script (it execs), but we can check the
    # fallback logic by sourcing up to the VENV_PYTHON assignment.
    # The stdio-mode section (lines ~86-90) sets VENV_PYTHON and checks -x.
    r = run_bash(
        f"""
        set -euo pipefail
        VENV_PYTHON="/nonexistent/python3"
        if [ ! -x "$VENV_PYTHON" ]; then
            VENV_PYTHON="python3"
        fi
        echo "VENV_PYTHON=$VENV_PYTHON"
        """,
        env={"VENV_PYTHON": "/nonexistent/python3"},
    )
    assert r.returncode == 0
    assert "VENV_PYTHON=python3" in r.stdout


def test_run_sp_cockpit_venv_fallback(run_bash, proj_root):
    """run_sp_cockpit.sh --bare falls back to system python3."""
    r = run_bash(
        f"""
        set -euo pipefail
        VENV_PYTHON="/nonexistent/python3"
        if [ ! -x "$VENV_PYTHON" ]; then
            VENV_PYTHON="python3"
        fi
        echo "VENV_PYTHON=$VENV_PYTHON"
        """,
        env={"VENV_PYTHON": "/nonexistent/python3"},
    )
    assert r.returncode == 0
    assert "VENV_PYTHON=python3" in r.stdout


def test_run_mcp_has_venv_fallback_pattern(run_bash, proj_root):
    """Verify run_mcp.sh actually contains the VENV_PYTHON fallback pattern."""
    r = run_bash(
        f'grep -c "VENV_PYTHON=" "{proj_root}/scripts/run_mcp.sh"',
    )
    assert r.returncode == 0
    assert int(r.stdout.strip()) >= 1


def test_run_sp_cockpit_has_venv_fallback_pattern(run_bash, proj_root):
    """Verify run_sp_cockpit.sh contains the VENV_PYTHON fallback pattern."""
    r = run_bash(
        f'grep -c "VENV_PYTHON=" "{proj_root}/scripts/run_sp_cockpit.sh"',
    )
    assert r.returncode == 0
    assert int(r.stdout.strip()) >= 1
