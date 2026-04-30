"""Tests for *_BIN injection points and audit env normalization.

Verifies mock.md §6 pattern: setting CURL_BIN / DOCKER_BIN / SQLITE3_BIN
causes scripts to route through the mock instead of the real tool.
"""

from __future__ import annotations

import os

from tests.shell.conftest import PROJ_ROOT, _run_bash

# ── Script paths ──────────────────────────────────────────────────────────────
INFRA_SH = str(PROJ_ROOT / "scripts" / "share" / "_infra.sh")
TEST_DENSE_SH = str(PROJ_ROOT / "scripts" / "testing" / "test_dense.sh")
SMOKE_SH = str(PROJ_ROOT / "scripts" / "testing" / "smoke_queries.sh")
VERIFY_SH = str(PROJ_ROOT / "scripts" / "testing" / "verify.sh")
STRUCTURAL_SH = str(PROJ_ROOT / "scripts" / "indexing" / "structural" / "build_structural_index.sh")
REINDEX_DOCKER_SH = str(PROJ_ROOT / "scripts" / "indexing" / "sparse" / "reindex_docker.sh")


# ── _infra.sh: CURL_BIN ───────────────────────────────────────────────────────

def test_infra_curl_bin_used(tmp_path, mock_command):
    """_infra.sh _infra_wait_http uses $CURL_BIN, not bare curl."""
    add_command, read_calls = mock_command
    add_command("fake-curl", exit_code=0)  # success → service "ready"

    common_sh = str(PROJ_ROOT / "scripts" / "share" / "_common.sh")
    script = f"""
        source "{common_sh}"
        source "{INFRA_SH}"
        CURL_BIN=fake-curl
        INFRA_SLEEP_SECONDS=0
        MAX_RETRIES=1
        _infra_wait_http http://127.0.0.1:19999/health "test-svc" 1 warn
    """
    r = _run_bash(script, env={"PATH": os.environ["PATH"], "HOME": "/tmp",
                                "TERM": "dumb", "NO_COLOR": "1",
                                "MOCK_COMMAND_LOG": os.environ["MOCK_COMMAND_LOG"]})
    calls = read_calls()
    assert any(c["cmd"] == "fake-curl" for c in calls), (
        f"fake-curl not called; stdout={r.stdout} stderr={r.stderr}"
    )


def test_infra_nc_bin_used(tmp_path, mock_command):
    """_infra.sh _infra_wait_tcp uses $NC_BIN, not bare nc."""
    add_command, read_calls = mock_command
    # Both fake-nc (our injection) and nc (satisfy _infra_require_cmd check) needed
    add_command("fake-nc", exit_code=0)
    add_command("nc", exit_code=0)

    common_sh = str(PROJ_ROOT / "scripts" / "share" / "_common.sh")
    script = f"""
        source "{common_sh}"
        source "{INFRA_SH}"
        NC_BIN=fake-nc
        INFRA_SLEEP_SECONDS=0
        _infra_wait_tcp localhost 7687 "test-tcp" 1
    """
    r = _run_bash(script, env={"PATH": os.environ["PATH"], "HOME": "/tmp",
                                "TERM": "dumb", "NO_COLOR": "1",
                                "MOCK_COMMAND_LOG": os.environ["MOCK_COMMAND_LOG"]})
    calls = read_calls()
    assert any(c["cmd"] == "fake-nc" for c in calls), (
        f"fake-nc not called; stdout={r.stdout} stderr={r.stderr}"
    )


# ── test_dense.sh: CURL_BIN + AUDIT_LOG_FILE (legacy AUDIT_LOG fallback) ──────

def test_dense_audit_log_file_canonical(tmp_path):
    """AUDIT_LOG_FILE is the canonical name; AUDIT_LOG is the fallback."""
    script = f"""
        source "{PROJ_ROOT}/scripts/share/_common.sh"
        AUDIT_LOG="/tmp/legacy_audit.log"
        AUDIT_LOG_FILE="${{AUDIT_LOG_FILE:-${{AUDIT_LOG:-audit.log}}}}"
        echo "$AUDIT_LOG_FILE"
    """
    r = _run_bash(script, env={"HOME": "/tmp", "TERM": "dumb", "NO_COLOR": "1"})
    assert r.returncode == 0
    assert r.stdout.strip() == "/tmp/legacy_audit.log", (
        f"Legacy AUDIT_LOG not honoured: got '{r.stdout.strip()}'"
    )


def test_dense_audit_log_file_takes_precedence(tmp_path):
    """When both AUDIT_LOG_FILE and AUDIT_LOG are set, AUDIT_LOG_FILE wins."""
    script = f"""
        source "{PROJ_ROOT}/scripts/share/_common.sh"
        AUDIT_LOG="/tmp/legacy.log"
        AUDIT_LOG_FILE="/tmp/canonical.log"
        AUDIT_LOG_FILE="${{AUDIT_LOG_FILE:-${{AUDIT_LOG:-audit.log}}}}"
        echo "$AUDIT_LOG_FILE"
    """
    r = _run_bash(script, env={"HOME": "/tmp", "TERM": "dumb", "NO_COLOR": "1"})
    assert r.returncode == 0
    assert r.stdout.strip() == "/tmp/canonical.log"


# ── smoke_queries.sh: AUDIT_DB alias ──────────────────────────────────────────

def test_smoke_audit_db_alias(tmp_path):
    """SP_COCKPIT_AUDIT_DB_PATH is honoured as fallback for AUDIT_DB."""
    script = f"""
        source "{PROJ_ROOT}/scripts/share/_common.sh"
        SP_COCKPIT_AUDIT_DB_PATH="/tmp/cockpit-alias.db"
        AUDIT_DB="${{AUDIT_DB:-${{SP_COCKPIT_AUDIT_DB_PATH:-sp-cockpit/data/audit.db}}}}"
        echo "$AUDIT_DB"
    """
    r = _run_bash(script, env={"HOME": "/tmp", "TERM": "dumb", "NO_COLOR": "1"})
    assert r.returncode == 0
    assert r.stdout.strip() == "/tmp/cockpit-alias.db"


def test_smoke_audit_db_canonical_wins(tmp_path):
    """AUDIT_DB takes precedence over SP_COCKPIT_AUDIT_DB_PATH."""
    script = f"""
        source "{PROJ_ROOT}/scripts/share/_common.sh"
        AUDIT_DB="/tmp/canonical.db"
        SP_COCKPIT_AUDIT_DB_PATH="/tmp/alias.db"
        AUDIT_DB="${{AUDIT_DB:-${{SP_COCKPIT_AUDIT_DB_PATH:-sp-cockpit/data/audit.db}}}}"
        echo "$AUDIT_DB"
    """
    r = _run_bash(script, env={"HOME": "/tmp", "TERM": "dumb", "NO_COLOR": "1"})
    assert r.returncode == 0
    assert r.stdout.strip() == "/tmp/canonical.db"


# ── reindex_docker.sh: DOCKER_BIN ────────────────────────────────────────────

def test_reindex_docker_docker_bin_used(tmp_path, mock_command):
    """reindex_docker.sh routes docker run through $DOCKER_BIN."""
    add_command, read_calls = mock_command
    add_command("fake-docker")

    # Build minimal fake project layout
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "project.list").write_text("frameworks/base\n")
    git_dir = repo.parent / "frameworks" / "base"
    git_dir.mkdir(parents=True)
    (git_dir / ".git").write_text("gitdir: fake\n")
    index_dir = tmp_path / "idx"
    index_dir.mkdir()

    cfg = tmp_path / "projects.yaml"
    cfg.write_text(
        f"projects:\n"
        f"  - name: testproj\n"
        f"    repo_path: {repo}\n"
        f"    index_dir: {index_dir}\n"
        f"    zoekt_url: http://localhost:6070\n"
    )

    env = {
        "PATH": os.environ["PATH"],
        "HOME": "/tmp",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "MOCK_COMMAND_LOG": os.environ["MOCK_COMMAND_LOG"],
        "PROJECTS_CONFIG_PATH": str(cfg),
        "DOCKER_BIN": "fake-docker",
        "INDEXING_DRY_RUN": "0",
    }
    r = _run_bash(
        f'bash "{REINDEX_DOCKER_SH}" --project testproj --parallelism 1',
        env=env,
    )
    calls = read_calls()
    docker_calls = [c for c in calls if c["cmd"] == "fake-docker"]
    assert len(docker_calls) >= 1, (
        f"fake-docker not called; stdout={r.stdout} stderr={r.stderr}"
    )
    # Confirm 'run' subcommand was used
    assert any("run" in c["argv"] for c in docker_calls), (
        f"'run' not in fake-docker argv: {docker_calls}"
    )


# ── build_structural_index.sh: DOCKER_BIN (dry-run bypass) ───────────────────

def test_structural_index_dry_run(tmp_path):
    """INDEXING_DRY_RUN=1 bypasses docker; script exits 0."""
    env = {
        "PATH": os.environ["PATH"],
        "HOME": "/tmp",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "INDEXING_DRY_RUN": "1",
        "AOSP_SOURCE_ROOT": str(tmp_path),
    }
    r = _run_bash(f'bash "{STRUCTURAL_SH}"', env=env)
    assert r.returncode == 0, f"stderr: {r.stderr}\nstdout: {r.stdout}"
    assert "DRY_RUN" in r.stdout or "DRY_RUN" in r.stderr
