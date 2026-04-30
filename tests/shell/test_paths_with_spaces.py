"""Verify scripts handle paths containing spaces without breaking."""

from __future__ import annotations

import os

from tests.shell.conftest import PROJ_ROOT, _run_bash

COMMON_SH = str(PROJ_ROOT / "scripts" / "share" / "_common.sh")
INFRA_SH = str(PROJ_ROOT / "scripts" / "share" / "_infra.sh")


def test_common_logging_with_spaces_in_msg(tmp_path):
    spaced = tmp_path / "dir with spaces"
    spaced.mkdir()
    log_file = spaced / "out.log"

    script = f"""
        source "{COMMON_SH}"
        info "hello world from {spaced}" 2>"{log_file}"
        cat "{log_file}"
    """
    r = _run_bash(script)
    assert r.returncode == 0, r.stderr
    assert "hello world from" in r.stdout
    assert str(spaced) in r.stdout


def test_infra_require_cmd_with_spaced_hint(tmp_path, mock_command):
    add_command, _ = mock_command
    add_command("foobar-tool", exit_code=0)

    script = f"""
        source "{COMMON_SH}"
        source "{INFRA_SH}"
        _common_require_cmd foobar-tool "install via brew install foo bar"
        echo OK
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
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert "OK" in r.stdout


def test_reindex_help_runs_when_pwd_has_spaces(tmp_path):
    """Run reindex.sh --help from a CWD that contains spaces."""
    spaced = tmp_path / "work dir with spaces"
    spaced.mkdir()
    script = f"""
        cd "{spaced}"
        bash "{PROJ_ROOT}/scripts/indexing/sparse/reindex.sh" --help
    """
    r = _run_bash(script)
    assert r.returncode == 0, f"stderr: {r.stderr}"
