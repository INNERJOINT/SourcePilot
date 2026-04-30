"""Tests for scripts/indexing/project_config.sh shell functions.

Covers:
  - fallback_single_project default output format
  - fallback_single_project with custom AOSP_SOURCE_ROOT
  - load_projects falls back when no config file exists
"""

from __future__ import annotations

import os

from tests.shell.conftest import PROJ_ROOT, _run_bash

SCRIPT = str(PROJ_ROOT / "scripts" / "indexing" / "project_config.sh")


def _source_and_call(func_name, *, env=None):
    """Source project_config.sh and call a function."""
    return _run_bash(
        f'source "{SCRIPT}" && {func_name}',
        env=env,
    )


def test_fallback_single_project_default():
    """Default fallback emits name|source_root|collection_name."""
    r = _source_and_call(
        "fallback_single_project",
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            "TERM": "dumb",
            "NO_COLOR": "1",
        },
    )
    assert r.returncode == 0
    line = r.stdout.strip()
    parts = line.split("|")
    assert len(parts) == 3, f"Expected 3 pipe-separated fields, got: {line}"
    name, source_root, collection = parts
    assert name  # non-empty
    assert source_root.startswith("/")
    assert collection.startswith("aosp_code_")


def test_fallback_single_project_custom_root():
    """AOSP_SOURCE_ROOT changes the derived name."""
    r = _source_and_call(
        "fallback_single_project",
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            "TERM": "dumb",
            "NO_COLOR": "1",
            "AOSP_SOURCE_ROOT": "/opt/aosp/MyProject",
        },
    )
    assert r.returncode == 0
    line = r.stdout.strip()
    parts = line.split("|")
    assert parts[0] == "myproject"
    assert parts[1] == "/opt/aosp/MyProject"
    assert parts[2] == "aosp_code_myproject"


def test_load_projects_no_config_falls_back(tmp_path):
    """Without projects.yaml, load_projects uses fallback_single_project."""
    r = _run_bash(
        f"""
        source "{SCRIPT}"
        _PC_CONFIG="{tmp_path}/nonexistent.yaml"
        load_projects
        """,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            "TERM": "dumb",
            "NO_COLOR": "1",
        },
    )
    assert r.returncode == 0
    line = r.stdout.strip()
    parts = line.split("|")
    assert len(parts) == 3


def test_load_projects_with_config(tmp_path):
    """With a valid projects.yaml, load_projects parses it."""
    cfg = tmp_path / "projects.yaml"
    cfg.write_text(
        """\
projects:
  - name: alpha
    source_root: /opt/aosp/alpha
    collection_name: aosp_code_alpha
  - name: beta
    source_root: /opt/aosp/beta
    collection_name: aosp_code_beta
"""
    )

    r = _run_bash(
        f"""
        source "{SCRIPT}"
        _PC_CONFIG="{cfg}"
        load_projects
        """,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            "TERM": "dumb",
            "NO_COLOR": "1",
        },
    )
    assert r.returncode == 0
    lines = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
    assert len(lines) == 2
    assert "alpha|/opt/aosp/alpha|aosp_code_alpha" in lines[0]
    assert "beta|/opt/aosp/beta|aosp_code_beta" in lines[1]
