"""Failure-path tests for scripts/share/_infra.sh.

Covers:
  - _infra_wait_http retries exhausted → die path (non-zero exit)
  - _infra_wait_http retries exhausted → warn path (returns 1 without exiting)
  - infra_start_sourcepilot: curl never succeeds → non-zero exit via die
  - _infra_require_cmd: missing command → die with install hint
"""

from __future__ import annotations

import os

from tests.shell.conftest import PROJ_ROOT, _run_bash

COMMON_SH = str(PROJ_ROOT / "scripts" / "share" / "_common.sh")
INFRA_SH = str(PROJ_ROOT / "scripts" / "share" / "_infra.sh")

_SOURCE_BOTH = f'source "{COMMON_SH}"; source "{INFRA_SH}"'


def _infra_env() -> dict[str, str]:
    """Base env using the monkeypatched PATH (with fake commands already on it)."""
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "TERM": "dumb",
        "NO_COLOR": "1",
        "MOCK_COMMAND_LOG": os.environ.get("MOCK_COMMAND_LOG", "/dev/null"),
        "INFRA_SLEEP_SECONDS": "0",
        "MAX_RETRIES": "2",
    }


# ---------------------------------------------------------------------------
# _infra_wait_http — die path
# ---------------------------------------------------------------------------


def test_infra_wait_http_die_when_curl_fails(mock_command):
    """Exhausted retries with on_fail=die → non-zero exit + 'startup timed out' in stderr."""
    add_command, _ = mock_command
    add_command("curl", exit_code=7)  # connection refused

    result = _run_bash(
        f"""
        {_SOURCE_BOTH}
        _infra_wait_http "http://localhost:9999/health" "testsvc" 2 die
        """,
        env=_infra_env(),
    )

    assert result.returncode != 0, f"Expected non-zero exit; stderr: {result.stderr}"
    assert "startup timed out" in result.stderr, (
        f"Expected 'startup timed out' in stderr:\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# _infra_wait_http — warn path
# ---------------------------------------------------------------------------


def test_infra_wait_http_warn_does_not_exit(mock_command):
    """Exhausted retries with on_fail=warn → script continues (sentinel echo must appear)."""
    add_command, _ = mock_command
    add_command("curl", exit_code=7)

    result = _run_bash(
        f"""
        set +e
        {_SOURCE_BOTH}
        _infra_wait_http "http://localhost:9999/health" "testsvc" 2 warn || true
        echo "SENTINEL_REACHED"
        """,
        env=_infra_env(),
    )

    assert "SENTINEL_REACHED" in result.stdout, (
        f"warn path exited the script; stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "startup timed out" in result.stderr, (
        f"Expected 'startup timed out' in stderr:\n{result.stderr}"
    )


def test_infra_wait_http_warn_returns_nonzero(mock_command):
    """Exhausted retries with on_fail=warn → overall script exits non-zero (warn returns 1)."""
    add_command, _ = mock_command
    add_command("curl", exit_code=7)

    # _common.sh sources with set -euo pipefail; warn returns 1 which propagates.
    # We confirm returncode is non-zero AND the warning message is present.
    result = _run_bash(
        f"""
        {_SOURCE_BOTH}
        _infra_wait_http "http://localhost:9999/health" "testsvc" 2 warn
        """,
        env=_infra_env(),
    )

    assert result.returncode != 0, (
        f"Expected non-zero rc from warn path; rc={result.returncode}\nstderr: {result.stderr}"
    )
    assert "startup timed out" in result.stderr, (
        f"Expected timeout message in stderr:\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# infra_start_sourcepilot — curl never succeeds → wait_http dies
# ---------------------------------------------------------------------------


def test_infra_start_sourcepilot_dies_when_health_check_times_out(mock_command, tmp_path):
    """infra_start_sourcepilot exits non-zero when the health check never passes."""
    add_command, _ = mock_command
    # curl always fails → initial probe fails (not-already-running) → docker compose up
    # → health check loop fails → die
    add_command("curl", exit_code=7)
    add_command("docker", exit_code=0, stdout="", stderr="")

    # Point COMPOSE_FILE at a harmless path so require_cmd docker passes
    fake_compose = tmp_path / "docker-compose.yml"
    fake_compose.write_text("version: '3'\n")

    env = _infra_env()
    env["COMPOSE_FILE"] = str(fake_compose)

    result = _run_bash(
        f"""
        {_SOURCE_BOTH}
        infra_start_sourcepilot
        """,
        env=env,
    )

    assert result.returncode != 0, (
        f"Expected non-zero exit when sourcepilot health times out; stderr: {result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "sourcepilot" in combined.lower() or "startup timed out" in combined, (
        f"Expected mention of sourcepilot or timeout:\n{combined}"
    )


# ---------------------------------------------------------------------------
# _infra_require_cmd — missing command with install hint
# ---------------------------------------------------------------------------


def test_infra_require_cmd_dies_with_hint(mock_command):
    """_infra_require_cmd for an absent command exits non-zero and includes the hint."""
    add_command, _ = mock_command
    # Do NOT add 'nonesuch' — it must be absent from PATH

    result = _run_bash(
        f"""
        {_SOURCE_BOTH}
        _infra_require_cmd nonesuch "install nonesuch via apt"
        """,
        env=_infra_env(),
    )

    assert result.returncode != 0, (
        f"Expected non-zero exit for missing command; stderr: {result.stderr}"
    )
    assert "install nonesuch via apt" in result.stderr, (
        f"Expected install hint in stderr:\n{result.stderr}"
    )
