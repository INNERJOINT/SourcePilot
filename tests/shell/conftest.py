"""Fixtures for shell script behavior tests.

Every test runs bash snippets via subprocess against the real scripts in
scripts/share/.  Fixtures provide:
  - tmp_dir: an isolated temporary directory (auto-cleaned)
  - proj_root: the real project root path
  - run_bash: helper to execute a bash snippet with controlled env
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path
from typing import Any

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
    """Run a bash snippet and return the CompletedProcess."""
    full_env: dict[str, str] = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "TERM": "dumb",
        "NO_COLOR": "1",
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
