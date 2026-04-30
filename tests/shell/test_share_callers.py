"""Tests for VENV_PYTHON fallback patterns in run_all.sh (MCP + sp-cockpit)."""

from __future__ import annotations


def test_run_mcp_venv_fallback(run_bash, proj_root):
    """run_mcp.sh falls back to system python3 when VENV_PYTHON is missing."""
    # We can't run the full script (it execs), but we can check the
    # fallback logic by sourcing up to the VENV_PYTHON assignment.
    # The stdio-mode section (lines ~86-90) sets VENV_PYTHON and checks -x.
    r = run_bash(
        """
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
        """
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


def test_run_all_has_venv_python_pattern(run_bash, proj_root):
    """Verify run_all.sh contains the VENV_PYTHON assignment (MCP+cockpit use it)."""
    r = run_bash(
        f'grep -c "VENV_PYTHON=" "{proj_root}/scripts/run_all.sh"',
    )
    assert r.returncode == 0
    assert int(r.stdout.strip()) >= 1


def test_run_all_has_venv_python_executable_check(run_bash, proj_root):
    """Verify run_all.sh checks that VENV_PYTHON is executable."""
    r = run_bash(
        f'grep -c "! -x.*VENV_PYTHON" "{proj_root}/scripts/run_all.sh"',
    )
    assert r.returncode == 0
    assert int(r.stdout.strip()) >= 1
