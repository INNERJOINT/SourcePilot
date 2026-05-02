"""Integration test: run_all.sh bare-MCP startup path.

Uses the fake-PATH JSON-recording pattern from refs/test/mock.md §方案二.
Verifies that with MCP_DOCKER=false, run_all.sh invokes $VENV_PYTHON
with arguments containing '-m' and 'mcp_server'.

Key environment overrides used to keep the script fast and side-effect-free:
  - VENV_PYTHON        → fake python3 (bash script) that records argv and exits 0
  - CURL_BIN           → fake curl that fails only for :8888 (so MCP bare launch fires)
  - DOCKER_BIN         → no-op docker stub (cleanup trap)
  - PROJECTS_CONFIG_PATH → nonexistent path (skip YAML parsing inside infra_start_zoekt)
  - SOURCEPILOT_ENV_NO_AUTOLOAD=1  → skip .env file loading
  - SP_COCKPIT_ENABLED=false       → skip sp-cockpit startup entirely
  - DENSE_ENABLED=false            → skip dense stack
  - STRUCTURAL_ENABLED=false       → skip Neo4j
  - MAX_RETRIES=2                  → fast timeout for _infra_wait_http
  - INFRA_SLEEP_SECONDS=0          → no sleeps between health-check retries
  - STOP_DOCKER_ON_EXIT=false      → skip docker compose stop in cleanup trap

NOTE: fake executables use #!/usr/bin/env bash (not python3) so that running
      VENV_PYTHON='<fake_path>' does not trigger a shebang exec-loop where
      /usr/bin/env finds 'python3' = fake_path again.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.mark.integration
def test_run_all_bare_mcp_invokes_python(tmp_path):
    """run_all.sh with MCP_DOCKER=false must invoke VENV_PYTHON -m mcp_server."""
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()

    calls_log = tmp_path / "calls.txt"

    # Fake VENV_PYTHON: bash script that records argv (one arg per line, prefixed with
    # the literal "PYTHON3_CALL:" so we can filter it) then exits 0 immediately.
    # Must use #!/usr/bin/env bash so the kernel does NOT follow "python3" in PATH —
    # that would cause an exec-loop when $VENV_PYTHON is itself named python3.
    fake_python3 = fake_bin / "python3"
    _write_executable(
        fake_python3,
        f"""\
#!/usr/bin/env bash
printf 'PYTHON3_CALL:%s\\n' "$@" >> {calls_log}
exit 0
""",
    )

    # Fake curl: succeed for all URLs except those containing ":8888".
    # Port 8888 must fail so the script treats MCP as "not running" and launches it bare.
    fake_curl = fake_bin / "curl"
    _write_executable(
        fake_curl,
"""\
#!/usr/bin/env bash
for arg in "$@"; do
    if [[ "$arg" == *:8888* ]]; then
        exit 1
    fi
done
exit 0
""",
    )

    # Fake docker: no-op stub invoked by the EXIT trap.
    fake_docker = fake_bin / "docker"
    _write_executable(fake_docker, "#!/usr/bin/env bash\nexit 0\n")

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
    # Point VENV_PYTHON at our recording fake so -m mcp_server is captured.
    env["VENV_PYTHON"] = str(fake_python3)
    # Override injectable command paths from _infra.sh.
    env["CURL_BIN"] = str(fake_curl)
    env["DOCKER_BIN"] = str(fake_docker)
    # Service toggles.
    env["MCP_DOCKER"] = "false"
    env["SP_COCKPIT_DOCKER"] = "false"
    env["SP_COCKPIT_ENABLED"] = "false"
    env["DENSE_ENABLED"] = "false"
    env["STRUCTURAL_ENABLED"] = "false"
    # Skip .env file loading so the test is hermetic.
    env["SOURCEPILOT_ENV_NO_AUTOLOAD"] = "1"
    # Skip YAML parsing inside infra_start_zoekt (file must not exist).
    env["PROJECTS_CONFIG_PATH"] = str(tmp_path / "no-projects.yaml")
    # Fast health-check timeouts (2 retries × 0 s sleep).
    env["MAX_RETRIES"] = "2"
    env["INFRA_SLEEP_SECONDS"] = "0"
    # Skip docker compose stop in the EXIT trap.
    env["STOP_DOCKER_ON_EXIT"] = "false"
    # Stable service URLs so fake curl can succeed on "already running" checks.
    env["ZOEKT_URL"] = "http://localhost:6070"
    env["SOURCEPILOT_URL"] = "http://localhost:9000"

    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "run_all.sh")],
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    recorded = calls_log.read_text(encoding="utf-8") if calls_log.exists() else ""
    python3_lines = [
        line.removeprefix("PYTHON3_CALL:")
        for line in recorded.splitlines()
        if line.startswith("PYTHON3_CALL:")
    ]

    assert python3_lines, (
        "Expected VENV_PYTHON to be invoked at least once, but no calls were recorded.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )

    # Each invocation appends one line per arg; find a run that has both '-m' and 'mcp_server'.
    # Since args are recorded as one-per-line we check the full recorded text.
    assert "-m" in python3_lines and any(
        "mcp_server" in arg for arg in python3_lines
    ), (
        "Expected python3 -m mcp_server invocation, but got recorded args: "
        f"{python3_lines}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
