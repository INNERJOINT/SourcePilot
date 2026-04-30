"""Fixtures for shell script behavior tests.

Every test runs bash snippets via subprocess against the real scripts in
scripts/share/.  Fixtures provide:
  - tmp_dir: an isolated temporary directory (auto-cleaned)
  - proj_root: the real project root path
  - run_bash: helper to execute a bash snippet with controlled env
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

PROJ_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def proj_root() -> Path:
    return PROJ_ROOT


@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path


def _run_bash(
    script: str,
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    timeout: int = 10,
) -> subprocess.CompletedProcess[str]:
    """Run a bash snippet and return the CompletedProcess.

    Default environment includes isolation vars so tests never write to the
    real .omc/indexing-logs/ directory and never scan the real AOSP source tree:
      INDEXING_LOG_DIR      — per-call temp dir under /tmp (overridable via env)
      INDEXING_SKIP_SOURCE_SCAN=1  — skip find(1) source-file probe in batch scripts
    """
    import tempfile

    default_log_dir = tempfile.mkdtemp(prefix="test-indexing-logs-")
    full_env: dict[str, str] = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "TERM": "dumb",
        "NO_COLOR": "1",
        # Isolation defaults — prevent writes to real .omc/indexing-logs/
        "INDEXING_LOG_DIR": default_log_dir,
        "INDEXING_SKIP_SOURCE_SCAN": "1",
        # Use a fast-fail URL so indexing CLI calls fail immediately (no hang)
        "INDEXING_API_URL": "http://127.0.0.1:1",
    }
    if env:
        full_env.update(env)
    return subprocess.run(
        ["bash", "-c", textwrap.dedent(script)],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=full_env,
        cwd=cwd,
    )


@pytest.fixture()
def run_bash():
    """Return a callable that executes a bash snippet."""
    return _run_bash


@pytest.fixture()
def mock_command(tmp_path, monkeypatch):
    """Create fake commands on PATH that record calls to a JSONL log.

    Returns (add_command, read_calls).  Usage::

        add_command, read_calls = mock_command
        add_command("curl", stdout='{"ok":true}')
        # … run script …
        calls = read_calls()
        assert calls[0]["cmd"] == "curl"
    """
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()

    log_file = tmp_path / "mock-calls.jsonl"

    monkeypatch.setenv("MOCK_COMMAND_LOG", str(log_file))
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ.get('PATH', '')}")

    def add_command(
        name: str,
        *,
        stdout: str = "",
        stderr: str = "",
        exit_code: int = 0,
    ):
        fake_cmd = fake_bin / name
        fake_cmd.write_text(
            f"""#!/usr/bin/env python3
import json, os, pathlib, sys

log_file = pathlib.Path(os.environ["MOCK_COMMAND_LOG"])
record = {{
    "cmd": {name!r},
    "argv": sys.argv[1:],
    "cwd": os.getcwd(),
}}
with log_file.open("a", encoding="utf-8") as f:
    f.write(json.dumps(record, ensure_ascii=False) + "\\n")

sys.stdout.write({stdout!r})
sys.stderr.write({stderr!r})
sys.exit({exit_code!r})
"""
        )
        fake_cmd.chmod(fake_cmd.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return fake_cmd

    def read_calls():
        if not log_file.exists():
            return []
        return [
            json.loads(line)
            for line in log_file.read_text(encoding="utf-8").splitlines()
        ]

    return add_command, read_calls
