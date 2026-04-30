"""Verify orchestration scripts are sourceable for unit-testing helpers.

Per refs/test/framework.md §1: scripts that do all work at top-level cannot be
unit-tested. After the lib+main refactor, sourcing a script must NOT execute
its main loop and individual helpers must be callable in isolation.
"""

from __future__ import annotations

from pathlib import Path


def test_run_all_mode_label_callable(run_bash, proj_root: Path):
  """Sourcing run_all.sh exposes _mode_label without executing main()."""
  script = f"""
    source {proj_root}/scripts/run_all.sh
    _mode_label true
    _mode_label false
  """
  result = run_bash(script, timeout=15)
  assert result.returncode == 0, f"stderr={result.stderr}"
  out = result.stdout.strip().splitlines()
  assert out == ["Docker", "bare"], out


def test_run_all_no_top_level_orchestration(run_bash, proj_root: Path):
  """Sourcing run_all.sh must not call infra_start_zoekt (no main() invoked)."""
  script = f"""
    # Stub infra functions to detect accidental invocation.
    infra_start_zoekt() {{ echo CALLED >&2; exit 1; }}
    infra_start_dense() {{ echo CALLED >&2; exit 1; }}
    infra_start_structural() {{ echo CALLED >&2; exit 1; }}
    infra_start_sourcepilot() {{ echo CALLED >&2; exit 1; }}
    source {proj_root}/scripts/run_all.sh
    echo SOURCED_OK
  """
  result = run_bash(script, timeout=15)
  assert "SOURCED_OK" in result.stdout, f"stdout={result.stdout} stderr={result.stderr}"
  assert "CALLED" not in result.stderr


def test_dense_batch_sourceable(run_bash, proj_root: Path):
  """build_dense_index_batch.sh is sourceable without executing the batch loop."""
  script = f"""
    source {proj_root}/scripts/indexing/dense/build_dense_index_batch.sh
    declare -F main >/dev/null && echo MAIN_DEFINED
    declare -F _emit_dense_project_lines >/dev/null && echo HELPER_DEFINED
  """
  result = run_bash(script, timeout=15)
  assert "MAIN_DEFINED" in result.stdout
  assert "HELPER_DEFINED" in result.stdout


def test_structural_batch_sourceable(run_bash, proj_root: Path):
  """build_structural_index_batch.sh is sourceable without executing the batch loop."""
  script = f"""
    source {proj_root}/scripts/indexing/structural/build_structural_index_batch.sh
    declare -F main >/dev/null && echo MAIN_DEFINED
    declare -F _emit_structural_project_lines >/dev/null && echo HELPER_DEFINED
  """
  result = run_bash(script, timeout=15)
  assert "MAIN_DEFINED" in result.stdout
  assert "HELPER_DEFINED" in result.stdout


def test_smoke_queries_run_case_callable(run_bash, proj_root: Path):
  """smoke_queries.sh exposes run_case helper without running pre-flight checks."""
  script = f"""
    source {proj_root}/scripts/testing/smoke_queries.sh
    declare -F run_case >/dev/null && echo RUN_CASE_DEFINED
    declare -F gen_trace_id >/dev/null && echo GEN_TRACE_ID_DEFINED
    declare -F main >/dev/null && echo MAIN_DEFINED
  """
  result = run_bash(script, timeout=15)
  assert "RUN_CASE_DEFINED" in result.stdout
  assert "GEN_TRACE_ID_DEFINED" in result.stdout
  assert "MAIN_DEFINED" in result.stdout


# ---------------------------------------------------------------------------
# _print_startup_summary tests (added after extraction from inline echo block)
# ---------------------------------------------------------------------------

def test_print_startup_summary_callable(run_bash, proj_root: Path):
  """_print_startup_summary is exposed after sourcing and writes to stderr."""
  script = f"""
    source {proj_root}/scripts/run_all.sh
    ZOEKT_URL=http://localhost:6070
    SOURCEPILOT_URL=http://localhost:9000
    MCP_PORT=8888
    SP_COCKPIT_PORT=9100
    SP_COCKPIT_ENABLED=true
    MCP_DOCKER=false
    SP_COCKPIT_DOCKER=false
    DENSE_ENABLED=false
    STRUCTURAL_ENABLED=false
    ZOEKT_DOCKER=false
    MCP_RUNNING=false
    MCP_PID=""
    SP_COCKPIT_PID=""
    SP_COCKPIT_RUNNING=false
    _print_startup_summary 2>&1
  """
  result = run_bash(script, timeout=15)
  assert result.returncode == 0, f"stderr={result.stderr}"
  combined = result.stdout + result.stderr
  assert "SourcePilot" in combined
  assert "═" in combined


def test_print_startup_summary_zoekt_docker_label(run_bash, proj_root: Path):
  """When ZOEKT_DOCKER=true the summary shows '(Docker)'."""
  script = f"""
    source {proj_root}/scripts/run_all.sh
    ZOEKT_URL=http://localhost:6070
    SOURCEPILOT_URL=http://localhost:9000
    MCP_PORT=8888 SP_COCKPIT_PORT=9100
    SP_COCKPIT_ENABLED=true
    MCP_DOCKER=false SP_COCKPIT_DOCKER=false
    DENSE_ENABLED=false STRUCTURAL_ENABLED=false
    ZOEKT_DOCKER=true
    MCP_RUNNING=false MCP_PID="" SP_COCKPIT_PID="" SP_COCKPIT_RUNNING=false
    _print_startup_summary 2>&1
  """
  result = run_bash(script, timeout=15)
  combined = result.stdout + result.stderr
  assert "Docker" in combined
  assert "sparse-index-zoekt" in combined


def test_print_startup_summary_mcp_pid_shown(run_bash, proj_root: Path):
  """When MCP_RUNNING=true and MCP_PID is set, the PID appears in the summary."""
  script = f"""
    source {proj_root}/scripts/run_all.sh
    ZOEKT_URL=http://localhost:6070
    SOURCEPILOT_URL=http://localhost:9000
    MCP_PORT=8888 SP_COCKPIT_PORT=9100
    SP_COCKPIT_ENABLED=true
    MCP_DOCKER=false SP_COCKPIT_DOCKER=false
    DENSE_ENABLED=false STRUCTURAL_ENABLED=false
    ZOEKT_DOCKER=false
    MCP_RUNNING=true MCP_PID=9999
    SP_COCKPIT_PID="" SP_COCKPIT_RUNNING=false
    _print_startup_summary 2>&1
  """
  result = run_bash(script, timeout=15)
  combined = result.stdout + result.stderr
  assert "9999" in combined
  assert "MCP Server" in combined


def test_print_startup_summary_mcp_failed_label(run_bash, proj_root: Path):
  """When MCP_RUNNING=false the summary says 'startup failed'."""
  script = f"""
    source {proj_root}/scripts/run_all.sh
    ZOEKT_URL=http://localhost:6070
    SOURCEPILOT_URL=http://localhost:9000
    MCP_PORT=8888 SP_COCKPIT_PORT=9100
    SP_COCKPIT_ENABLED=true
    MCP_DOCKER=false SP_COCKPIT_DOCKER=false
    DENSE_ENABLED=false STRUCTURAL_ENABLED=false
    ZOEKT_DOCKER=false
    MCP_RUNNING=false MCP_PID="" SP_COCKPIT_PID="" SP_COCKPIT_RUNNING=false
    _print_startup_summary 2>&1
  """
  result = run_bash(script, timeout=15)
  combined = result.stdout + result.stderr
  assert "startup failed" in combined
