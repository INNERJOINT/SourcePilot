"""Verify scripts surface external command failures rather than swallowing them."""

from __future__ import annotations

import os

from tests.shell.conftest import PROJ_ROOT, _run_bash

COMMON_SH = str(PROJ_ROOT / "scripts" / "share" / "_common.sh")
INFRA_SH = str(PROJ_ROOT / "scripts" / "share" / "_infra.sh")


def test_infra_wait_http_warn_returns_nonzero(tmp_path, mock_command):
    """When curl always fails and on_fail=warn, _infra_wait_http returns 1, not exit."""
    add_command, _ = mock_command
    add_command("fake-curl", exit_code=22)  # curl HTTP error

    script = f"""
        source "{COMMON_SH}"
        source "{INFRA_SH}"
        CURL_BIN=fake-curl
        INFRA_SLEEP_SECONDS=0
        if _infra_wait_http http://127.0.0.1:1/x "svc" 2 warn; then
            echo "UNEXPECTED-OK"
        else
            echo "WARNED-RC=$?"
        fi
    """
    r = _run_bash(
        script,
        env={
            "PATH": os.environ["PATH"],
            "HOME": "/tmp",
            "TERM": "dumb",
            "NO_COLOR": "1",
            "MOCK_COMMAND_LOG": os.environ["MOCK_COMMAND_LOG"],
        },
    )
    assert r.returncode == 0, f"outer script must continue; stderr: {r.stderr}"
    assert "WARNED-RC=1" in r.stdout, f"stdout: {r.stdout}"


def test_infra_wait_http_die_exits(tmp_path, mock_command):
    """When curl always fails and on_fail=die, the script must exit non-zero."""
    add_command, _ = mock_command
    add_command("fake-curl", exit_code=22)

    script = f"""
        source "{COMMON_SH}"
        source "{INFRA_SH}"
        CURL_BIN=fake-curl
        INFRA_SLEEP_SECONDS=0
        _infra_wait_http http://127.0.0.1:1/x "svc" 1 die
        echo "UNREACHED"
    """
    r = _run_bash(
        script,
        env={
            "PATH": os.environ["PATH"],
            "HOME": "/tmp",
            "TERM": "dumb",
            "NO_COLOR": "1",
            "MOCK_COMMAND_LOG": os.environ["MOCK_COMMAND_LOG"],
        },
    )
    assert r.returncode != 0
    assert "UNREACHED" not in r.stdout


def test_run_helper_propagates_exit_code(tmp_path, mock_command):
    """run() should preserve the wrapped command's exit code."""
    add_command, _ = mock_command
    add_command("fake-fail", exit_code=7)

    script = f"""
        source "{COMMON_SH}"
        set +e
        run fake-fail arg1 arg2
        echo "RC=$?"
    """
    r = _run_bash(
        script,
        env={
            "PATH": os.environ["PATH"],
            "HOME": "/tmp",
            "TERM": "dumb",
            "NO_COLOR": "1",
            "MOCK_COMMAND_LOG": os.environ["MOCK_COMMAND_LOG"],
        },
    )
    assert "RC=7" in r.stdout, f"expected exit code 7 propagated; stdout: {r.stdout}"
