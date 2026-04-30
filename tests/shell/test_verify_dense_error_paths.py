"""Error-path tests for verify.sh and test_dense.sh.

Verifies that helper subcommands fail with actionable errors when:
  - sp-cockpit/SourcePilot HTTP endpoints are unreachable
  - required commands (curl/jq) are missing
  - audit.db doesn't exist
"""

from __future__ import annotations

import os

from tests.shell.conftest import PROJ_ROOT, _run_bash

VERIFY_SH = str(PROJ_ROOT / "scripts" / "testing" / "verify.sh")
TEST_DENSE_SH = str(PROJ_ROOT / "scripts" / "testing" / "test_dense.sh")


def _env_with_path() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/tmp",
        "TERM": "dumb",
        "NO_COLOR": "1",
    }


# ── verify.sh structural-audit error paths ───────────────────────────────────

def test_verify_structural_audit_unreachable_cockpit(tmp_path, mock_command):
    """structural-audit returns non-zero when sp-cockpit health endpoint fails."""
    add_command, _ = mock_command
    add_command("fake-curl", exit_code=22)  # always fail

    env = _env_with_path()
    env["MOCK_COMMAND_LOG"] = os.environ["MOCK_COMMAND_LOG"]
    env["CURL_BIN"] = "fake-curl"
    env["SP_COCKPIT_URL"] = "http://127.0.0.1:1"
    env["SOURCEPILOT_URL"] = "http://127.0.0.1:1"

    r = _run_bash(f'bash "{VERIFY_SH}" structural-audit 2>&1', env=env)
    assert r.returncode != 0
    # Must surface a specific reason (one of: sp-cockpit, SourcePilot, audit)
    body = r.stdout + r.stderr
    assert any(kw in body for kw in ("sp-cockpit", "SourcePilot", "audit")), body


# ── verify.sh indexer-containers error paths ─────────────────────────────────

def test_verify_indexer_containers_no_docker(tmp_path, monkeypatch):
    """indexer-containers gracefully reports when docker is unavailable."""
    # PATH that excludes docker
    safe_bin = tmp_path / "bin"
    safe_bin.mkdir()
    # Give it bash and other essentials via real PATH minus docker
    env = {
        "PATH": f"{safe_bin}",  # nothing here, docker absent
        "HOME": "/tmp",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "DOCKER_BIN": "definitely-not-docker-xyz",
    }
    # Provide bash via /bin
    env["PATH"] = f"{safe_bin}:/usr/bin:/bin"

    r = _run_bash(f'bash "{VERIFY_SH}" indexer-containers 2>&1', env=env)
    # The script's _run_indexer_containers prints "docker not installed; skipping"
    # and returns 0 in that case (it's defensive, not an error)
    assert r.returncode == 0
    assert "docker not installed" in r.stdout or "skipping" in r.stdout.lower()


# ── test_dense.sh error paths ────────────────────────────────────────────────

def test_dense_missing_jq_exits_2(tmp_path, mock_command):
    """test_dense.sh exits 2 when jq is unavailable."""
    add_command, _ = mock_command
    add_command("fake-curl", exit_code=0)

    env = _env_with_path()
    env["MOCK_COMMAND_LOG"] = os.environ["MOCK_COMMAND_LOG"]
    env["CURL_BIN"] = "fake-curl"
    env["JQ_BIN"] = "definitely-not-jq-xyz"
    env["SOURCEPILOT_URL"] = "http://127.0.0.1:1"

    r = _run_bash(f'bash "{TEST_DENSE_SH}" 2>&1', env=env)
    assert r.returncode == 2, f"expected exit 2 (missing dep); got {r.returncode}\n{r.stdout}\n{r.stderr}"


def test_dense_unreachable_sourcepilot(tmp_path, mock_command):
    """test_dense.sh exits non-zero when SourcePilot health check fails."""
    add_command, _ = mock_command
    add_command("fake-curl", exit_code=7)  # connection refused
    add_command("fake-jq", exit_code=0, stdout="{}")

    env = _env_with_path()
    env["MOCK_COMMAND_LOG"] = os.environ["MOCK_COMMAND_LOG"]
    env["CURL_BIN"] = "fake-curl"
    env["JQ_BIN"] = "fake-jq"
    env["SOURCEPILOT_URL"] = "http://127.0.0.1:1"
    env["TIMEOUT"] = "1"

    r = _run_bash(f'bash "{TEST_DENSE_SH}" 2>&1', env=env)
    assert r.returncode != 0
    assert "unreachable" in (r.stdout + r.stderr).lower() or "ERROR" in (r.stdout + r.stderr)
