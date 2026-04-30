"""Regression test: start_indexing_job must write logs to INDEXING_LOG_DIR, not real .omc/."""

from __future__ import annotations

import os
from pathlib import Path

from tests.shell.conftest import PROJ_ROOT, _run_bash

INDEXING_LIB = str(PROJ_ROOT / "scripts" / "indexing" / "_indexing_lib.sh")

# Use a port that is always refused so the CLI call fails fast without hanging.
_FAST_FAIL_API = "http://127.0.0.1:1"


def _env(log_dir: Path) -> dict:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "TERM": "dumb",
        "NO_COLOR": "1",
        "VIRTUAL_ENV": "",
        "INDEXING_LOG_DIR": str(log_dir),
        "INDEXING_API_URL": _FAST_FAIL_API,
    }


def test_log_path_uses_indexing_log_dir(tmp_path: Path):
    """When INDEXING_LOG_DIR is set, LOG_PATH is under that dir, not .omc/indexing-logs/."""
    log_dir = tmp_path / "test-indexing-logs"
    log_dir.mkdir()

    script = f"""
set -euo pipefail
source "{INDEXING_LIB}"
start_indexing_job /tmp/my-repo zoekt myproj || true
echo "LOG_PATH=$LOG_PATH"
"""
    r = _run_bash(script, env=_env(log_dir), timeout=15)
    assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"

    log_path_line = next((ln for ln in r.stdout.splitlines() if ln.startswith("LOG_PATH=")), None)
    assert log_path_line is not None, f"LOG_PATH not printed; stdout={r.stdout}"
    log_path = log_path_line[len("LOG_PATH="):]
    assert log_path.startswith(str(log_dir)), (
        f"LOG_PATH={log_path!r} should be under {log_dir}"
    )


def test_log_dir_created_under_indexing_log_dir(tmp_path: Path):
    """Parent directory of LOG_PATH is created under INDEXING_LOG_DIR (even if it didn't exist)."""
    log_dir = tmp_path / "new-log-dir"
    # Do NOT pre-create log_dir — start_indexing_job must create it

    script = f"""
set -euo pipefail
source "{INDEXING_LIB}"
start_indexing_job /tmp/some-repo zoekt testproj || true
echo "LOG_PATH=$LOG_PATH"
"""
    r = _run_bash(script, env=_env(log_dir), timeout=15)
    assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"

    log_path_line = next((ln for ln in r.stdout.splitlines() if ln.startswith("LOG_PATH=")), None)
    assert log_path_line is not None, f"LOG_PATH not printed; stdout={r.stdout}"
    log_path = Path(log_path_line[len("LOG_PATH="):])
    assert log_path.parent.exists(), f"Parent dir {log_path.parent} was not created"
    assert str(log_path).startswith(str(log_dir))


def test_real_omc_dir_not_modified(tmp_path: Path):
    """After running start_indexing_job with INDEXING_LOG_DIR, the real .omc dir is untouched."""
    real_omc = PROJ_ROOT / ".omc" / "indexing-logs"
    before_files = set(real_omc.iterdir()) if real_omc.exists() else set()

    log_dir = tmp_path / "isolated-logs"
    log_dir.mkdir()

    script = f"""
set -euo pipefail
source "{INDEXING_LIB}"
start_indexing_job /tmp/test-repo zoekt isolatedproj || true
"""
    _run_bash(script, env=_env(log_dir), timeout=15)

    after_files = set(real_omc.iterdir()) if real_omc.exists() else set()
    new_files = after_files - before_files
    assert not new_files, f"Unexpected files created in .omc/indexing-logs/: {new_files}"
