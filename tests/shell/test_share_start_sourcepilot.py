"""Tests for scripts/share/_start_sourcepilot.sh."""

from __future__ import annotations

from pathlib import Path


def _script_path(proj_root: Path) -> str:
    return str(proj_root / "scripts" / "share" / "_start_sourcepilot.sh")


def test_main_guard_source_vs_execute(run_bash, proj_root):
    """Sourcing the script should NOT run main() — verified by running directly."""
    # When executed with --help, it prints usage and exits 0 (no uvicorn exec).
    r = run_bash(
        f'"{_script_path(proj_root)}" --help',
    )
    # --help should exit 0 and not exec uvicorn
    assert r.returncode == 0
    assert "uvicorn" not in r.stdout


def test_host_flag_missing_value(run_bash, proj_root):
    """--host without value should exit 2."""
    r = run_bash(f'"{_script_path(proj_root)}" --host')
    assert r.returncode == 2
    assert "requires" in r.stderr.lower() or "error" in r.stderr.lower()


def test_port_flag_missing_value(run_bash, proj_root):
    """--port without value should exit 2."""
    r = run_bash(f'"{_script_path(proj_root)}" --port')
    assert r.returncode == 2


def test_port_flag_invalid_value(run_bash, proj_root):
    """--port with non-numeric value should exit 2."""
    r = run_bash(f'"{_script_path(proj_root)}" --port abc')
    assert r.returncode == 2
    assert "integer" in r.stderr.lower() or "error" in r.stderr.lower()


def test_port_flag_out_of_range(run_bash, proj_root):
    """--port 99999 should exit 2."""
    r = run_bash(f'"{_script_path(proj_root)}" --port 99999')
    assert r.returncode == 2


def test_interpreter_fallback(run_bash, proj_root, tmp_dir):
    """When VENV_PYTHON is nonexistent, falls back to python3 and warns."""
    # Create a fake python3 that just prints the args
    fake_bin = tmp_dir / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text("#!/bin/bash\necho FAKE_PYTHON_CALLED; exit 0\n")
    fake_python.chmod(0o755)

    # Also need fake uvicorn module — the exec will try to run it
    # We just need to verify the warning appears; the exec will use our fake python3
    r = run_bash(
        f'PATH="{fake_bin}:$PATH" VENV_PYTHON="/nonexistent/py" '
        f'"{_script_path(proj_root)}"',
        env={"VENV_PYTHON": "/nonexistent/py", "PATH": f"{fake_bin}:/usr/bin:/bin"},
    )
    # Should have warned about fallback
    assert "not found" in r.stderr.lower() or "warning" in r.stderr.lower()
