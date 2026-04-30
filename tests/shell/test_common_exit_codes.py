"""Tests for the exit-code contract defined in scripts/share/_common.sh.

Covers:
  - EXIT_* constants exported (0–5)
  - _common_require_cmd: missing command → EXIT_DEPS (3)
  - _common_require_env: missing variable → EXIT_CONFIG (4)
  - _common_require_cmd: present command → exit 0
  - _common_require_env: set variable → exit 0
  - build_dense_index_batch.sh: unknown option → EXIT_USAGE (2)
  - reindex.sh: unknown option → EXIT_USAGE (2)
"""

from __future__ import annotations

import os

import pytest

from tests.shell.conftest import PROJ_ROOT, _run_bash

COMMON_SH = str(PROJ_ROOT / "scripts" / "share" / "_common.sh")
DENSE_BATCH = str(PROJ_ROOT / "scripts" / "indexing" / "dense" / "build_dense_index_batch.sh")
REINDEX_SH = str(PROJ_ROOT / "scripts" / "indexing" / "sparse" / "reindex.sh")

_SOURCE_COMMON = f'source "{COMMON_SH}"'


def _base_env() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "TERM": "dumb",
        "NO_COLOR": "1",
    }


# ---------------------------------------------------------------------------
# Exit-code constants
# ---------------------------------------------------------------------------


def test_exit_constants_exported():
    """All EXIT_* constants are exported with correct values."""
    result = _run_bash(
        f"""
        {_SOURCE_COMMON}
        echo "EXIT_OK=$EXIT_OK"
        echo "EXIT_GENERAL=$EXIT_GENERAL"
        echo "EXIT_USAGE=$EXIT_USAGE"
        echo "EXIT_DEPS=$EXIT_DEPS"
        echo "EXIT_CONFIG=$EXIT_CONFIG"
        echo "EXIT_EXTERNAL=$EXIT_EXTERNAL"
        """,
        env=_base_env(),
    )
    assert result.returncode == 0, f"Unexpected exit: {result.stderr}"
    assert "EXIT_OK=0" in result.stdout
    assert "EXIT_GENERAL=1" in result.stdout
    assert "EXIT_USAGE=2" in result.stdout
    assert "EXIT_DEPS=3" in result.stdout
    assert "EXIT_CONFIG=4" in result.stdout
    assert "EXIT_EXTERNAL=5" in result.stdout


# ---------------------------------------------------------------------------
# _common_require_cmd
# ---------------------------------------------------------------------------


def test_require_cmd_missing_exits_deps():
    """_common_require_cmd for an absent command exits EXIT_DEPS (3)."""
    result = _run_bash(
        f"""
        {_SOURCE_COMMON}
        _common_require_cmd __no_such_cmd_xyz__
        """,
        env=_base_env(),
    )
    assert result.returncode == 3, (
        f"Expected EXIT_DEPS=3; got rc={result.returncode}\nstderr: {result.stderr}"
    )
    assert "required command not found" in result.stderr


def test_require_cmd_missing_includes_hint():
    """_common_require_cmd includes the hint in the error message."""
    result = _run_bash(
        f"""
        {_SOURCE_COMMON}
        _common_require_cmd __no_such_cmd_xyz__ "install it with apt"
        """,
        env=_base_env(),
    )
    assert result.returncode == 3
    assert "install it with apt" in result.stderr


def test_require_cmd_present_exits_ok():
    """_common_require_cmd for a present command exits 0."""
    result = _run_bash(
        f"""
        {_SOURCE_COMMON}
        _common_require_cmd bash
        """,
        env=_base_env(),
    )
    assert result.returncode == 0, f"Unexpected failure: {result.stderr}"


# ---------------------------------------------------------------------------
# _common_require_env
# ---------------------------------------------------------------------------


def test_require_env_missing_exits_config():
    """_common_require_env for an unset variable exits EXIT_CONFIG (4)."""
    env = _base_env()
    env.pop("__TEST_MISSING_VAR__", None)  # ensure absent
    result = _run_bash(
        f"""
        {_SOURCE_COMMON}
        unset __TEST_MISSING_VAR__
        _common_require_env __TEST_MISSING_VAR__
        """,
        env=env,
    )
    assert result.returncode == 4, (
        f"Expected EXIT_CONFIG=4; got rc={result.returncode}\nstderr: {result.stderr}"
    )
    assert "required environment variable not set" in result.stderr


def test_require_env_missing_includes_hint():
    """_common_require_env includes the hint in the error message."""
    result = _run_bash(
        f"""
        {_SOURCE_COMMON}
        unset __TEST_MISSING_VAR__
        _common_require_env __TEST_MISSING_VAR__ "set it in .env"
        """,
        env=_base_env(),
    )
    assert result.returncode == 4
    assert "set it in .env" in result.stderr


def test_require_env_set_exits_ok():
    """_common_require_env for a set variable exits 0."""
    env = _base_env()
    env["MY_TEST_VAR"] = "hello"
    result = _run_bash(
        f"""
        {_SOURCE_COMMON}
        _common_require_env MY_TEST_VAR
        """,
        env=env,
    )
    assert result.returncode == 0, f"Unexpected failure: {result.stderr}"


# ---------------------------------------------------------------------------
# build_dense_index_batch.sh — unknown option → EXIT_USAGE (2)
# ---------------------------------------------------------------------------


def test_dense_batch_unknown_option_exits_usage(tmp_path):
    """build_dense_index_batch.sh exits EXIT_USAGE (2) on an unknown option."""
    # Provide a minimal projects.yaml so the script doesn't fail on config load
    cfg = tmp_path / "projects.yaml"
    cfg.write_text("projects: []\n")
    env = _base_env()
    env["PROJECTS_CONFIG_PATH"] = str(cfg)
    env["INDEXING_DRY_RUN"] = "1"

    result = _run_bash(
        f'bash "{DENSE_BATCH}" --unknown-flag-xyz',
        env=env,
        timeout=15,
    )
    assert result.returncode == 2, (
        f"Expected EXIT_USAGE=2; got rc={result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# reindex.sh — unknown option → EXIT_USAGE (2)
# ---------------------------------------------------------------------------


def test_reindex_unknown_option_exits_usage(tmp_path):
    """reindex.sh exits EXIT_USAGE (2) on an unknown option."""
    cfg = tmp_path / "projects.yaml"
    cfg.write_text("projects: []\n")
    env = _base_env()
    env["PROJECTS_CONFIG_PATH"] = str(cfg)
    env["INDEXING_DRY_RUN"] = "1"
    # Provide a fake zoekt-git-index so the binary-check passes
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_zoekt = fake_bin / "zoekt-git-index"
    fake_zoekt.write_text("#!/usr/bin/env bash\nexit 0\n")
    fake_zoekt.chmod(0o755)
    env["PATH"] = f"{fake_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}"

    result = _run_bash(
        f'bash "{REINDEX_SH}" --unknown-flag-xyz',
        env=env,
        timeout=15,
    )
    assert result.returncode == 2, (
        f"Expected EXIT_USAGE=2; got rc={result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
