"""Tests for shell script syntax and INDEXING_DRY_RUN behaviour."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

# Project root — two levels up from this file (sp-cockpit/tests/ → project root)
PROJECT_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Syntax checks (bash -n)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("script", [
    "scripts/indexing/build_dense_index_batch.sh",
    "scripts/indexing/build_graph_index.sh",
    "scripts/indexing/reindex.sh",
    "scripts/indexing/_indexing_lib.sh",
])
def test_bash_syntax(script):
    """bash -n reports no syntax errors."""
    result = subprocess.run(
        ["bash", "-n", script],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"{script} has syntax errors:\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# DRY_RUN smoke tests
# ---------------------------------------------------------------------------

def _dry_run_env(extra: dict | None = None) -> dict:
    """Build env dict with INDEXING_DRY_RUN=1 and a mock API URL."""
    env = {**os.environ}
    env["INDEXING_DRY_RUN"] = "1"
    # Point at a non-listening port — finish will write a fallback file (non-fatal)
    env["INDEXING_API_URL"] = "http://127.0.0.1:19999"
    env["INDEXING_INTERNAL_TOKEN"] = "test-dry-run"
    if extra:
        env.update(extra)
    return env


def test_build_graph_dry_run_exits_zero(tmp_path):
    """build_graph_index.sh INDEXING_DRY_RUN=1 exits 0 without docker."""
    env = _dry_run_env({
        "AOSP_SOURCE_ROOT": str(tmp_path),
    })
    result = subprocess.run(
        ["bash", "scripts/indexing/build_graph_index.sh", "--source-root", str(tmp_path)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, (
        f"Expected 0, got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # Should mention DRY_RUN in output
    combined = result.stdout + result.stderr
    assert "DRY_RUN" in combined or "dry" in combined.lower()


def test_reindex_dry_run_exits_zero(tmp_path):
    """reindex.sh INDEXING_DRY_RUN=1 exits 0 without docker."""
    # Create a fake repo path so the directory check passes
    fake_repo = tmp_path / ".repo"
    fake_repo.mkdir()

    env = _dry_run_env({
        "ZOEKT_REPO_PATH": str(fake_repo),
    })
    result = subprocess.run(
        ["bash", "scripts/indexing/reindex.sh"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, (
        f"Expected 0, got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "dry" in combined.lower() or "DRY_RUN" in combined


def test_build_dense_dry_run_skips_docker(tmp_path, monkeypatch):
    """build_dense_index_batch.sh dry-run emits dense wrapper command with collection."""
    # Create minimal AOSP-like structure with default-discovery repos.
    frameworks = tmp_path / "frameworks" / "base"
    frameworks.mkdir(parents=True)
    (frameworks / "Foo.java").write_text("class Foo {}")

    packages = tmp_path / "packages" / "apps" / "Settings"
    packages.mkdir(parents=True)
    (packages / "Bar.java").write_text("class Bar {}")

    projects_yaml = tmp_path / "projects.yaml"
    projects_yaml.write_text(
        "projects:\n"
        f"  - name: ace\n"
        f"    source_root: {tmp_path}\n"
        f"    collection_name: aosp_code_ace_custom\n"
    )

    env = _dry_run_env({
        "PROJECTS_CONFIG_PATH": str(projects_yaml),
    })
    result = subprocess.run(
        ["bash", "scripts/indexing/build_dense_index_batch.sh"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"Expected 0, got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "DRY_RUN" in combined or "dry" in combined.lower(), (
        f"Expected DRY_RUN indicator.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "===== INDEX  frameworks/base" in combined
    assert "===== INDEX  packages/apps/Settings" in combined
    assert "--project-name ace" in combined
    assert "--collection-name aosp_code_ace_custom" in combined


def test_build_dense_include_mode_uses_only_config_includes(tmp_path):
    """dense explicit include mode should not run default frameworks/packages discovery."""
    included = tmp_path / "frameworks" / "base"
    included.mkdir(parents=True)
    (included / "Foo.java").write_text("class Foo {}")

    not_included = tmp_path / "packages" / "apps" / "Settings"
    not_included.mkdir(parents=True)
    (not_included / "Bar.java").write_text("class Bar {}")

    projects_yaml = tmp_path / "projects.yaml"
    projects_yaml.write_text(
        "projects:\n"
        "  - name: ace\n"
        f"    source_root: {tmp_path}\n"
        "    dense_index:\n"
        "      include:\n"
        "        - frameworks/base\n"
    )

    env = _dry_run_env({
        "PROJECTS_CONFIG_PATH": str(projects_yaml),
    })
    result = subprocess.run(
        ["bash", "scripts/indexing/build_dense_index_batch.sh"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )

    combined = result.stdout + result.stderr
    assert "mode=explicit" in combined
    assert "===== INDEX  frameworks/base" in combined
    assert "packages/apps/Settings" not in combined


# ---------------------------------------------------------------------------
# Multi-project reindex tests
# ---------------------------------------------------------------------------

def test_reindex_all_dry_run(tmp_path):
    """reindex.sh --all INDEXING_DRY_RUN=1 exits 0 for each configured project."""
    fake_repo = tmp_path / ".repo"
    fake_repo.mkdir()

    # Point projects config at a temp file with our fake repo
    projects_yaml = tmp_path / "projects.yaml"
    projects_yaml.write_text(
        f"projects:\n"
        f"  - name: test-proj\n"
        f"    source_root: {tmp_path}\n"
        f"    repo_path: {fake_repo}\n"
        f"    index_dir: {tmp_path}/zoekt\n"
        f"    zoekt_url: http://localhost:6070\n"
    )

    env = _dry_run_env({
        "PROJECTS_CONFIG_PATH": str(projects_yaml),
    })
    result = subprocess.run(
        ["bash", "scripts/indexing/reindex.sh", "--all"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, (
        f"Expected 0, got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "dry" in combined.lower() or "DRY_RUN" in combined


def test_reindex_single_project_dry_run(tmp_path):
    """reindex.sh --project <name> INDEXING_DRY_RUN=1 exits 0 for a named project."""
    fake_repo = tmp_path / ".repo"
    fake_repo.mkdir()

    projects_yaml = tmp_path / "projects.yaml"
    projects_yaml.write_text(
        f"projects:\n"
        f"  - name: my-proj\n"
        f"    source_root: {tmp_path}\n"
        f"    repo_path: {fake_repo}\n"
        f"    index_dir: {tmp_path}/zoekt\n"
        f"    zoekt_url: http://localhost:6070\n"
        f"  - name: other-proj\n"
        f"    source_root: {tmp_path}\n"
        f"    repo_path: {fake_repo}\n"
        f"    index_dir: {tmp_path}/zoekt2\n"
        f"    zoekt_url: http://localhost:6071\n"
    )

    env = _dry_run_env({
        "PROJECTS_CONFIG_PATH": str(projects_yaml),
    })
    result = subprocess.run(
        ["bash", "scripts/indexing/reindex.sh", "--project", "my-proj"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, (
        f"Expected 0, got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "dry" in combined.lower() or "DRY_RUN" in combined
    # Should mention the targeted project, not the other one
    assert "my-proj" in combined
    assert "other-proj" not in combined


# ---------------------------------------------------------------------------
# Graph batch tests
# ---------------------------------------------------------------------------

def test_build_graph_batch_dry_run(tmp_path):
    """build_graph_index_batch.sh INDEXING_DRY_RUN=1 prints expected DRY_RUN output."""
    frameworks = tmp_path / "frameworks" / "base"
    frameworks.mkdir(parents=True)
    (frameworks / "Foo.java").write_text("class Foo {}")

    projects_yaml = tmp_path / "projects.yaml"
    projects_yaml.write_text(
        f"projects:\n"
        f"  - name: ace\n"
        f"    source_root: {tmp_path}\n"
        f"    graph_index:\n"
        f"      include:\n"
        f"        - frameworks/base\n"
    )

    env = _dry_run_env({
        "PROJECTS_CONFIG_PATH": str(projects_yaml),
    })
    result = subprocess.run(
        ["bash", "scripts/indexing/build_graph_index_batch.sh"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"Expected 0, got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "DRY_RUN" in combined
    assert "--project-name" in combined
    assert "--repo-name frameworks/base" in combined
    assert "--source-root" in combined


def test_build_graph_batch_rejects_managed_args(tmp_path):
    """build_graph_index_batch.sh exits 2 and prints 'managed by' for managed args."""
    managed_args = [
        ["--source-root", "/tmp/foo"],
        ["--project-name", "myproj"],
        ["--repo-name", "frameworks/base"],
        ["--source-root=/tmp/foo"],
    ]

    for extra_args in managed_args:
        result = subprocess.run(
            ["bash", "scripts/indexing/build_graph_index_batch.sh"] + extra_args,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2, (
            f"Expected exit 2 for {extra_args}, got {result.returncode}\n"
            f"stderr: {result.stderr}"
        )
        assert "managed by" in result.stderr, (
            f"Expected 'managed by' in stderr for {extra_args}\nstderr: {result.stderr}"
        )


def test_build_graph_batch_reset_once_per_project(tmp_path):
    """build_graph_index_batch.sh --reset passes --reset only to the first include."""
    frameworks = tmp_path / "frameworks" / "base"
    frameworks.mkdir(parents=True)
    (frameworks / "Foo.java").write_text("class Foo {}")

    settings = tmp_path / "packages" / "apps" / "Settings"
    settings.mkdir(parents=True)
    (settings / "Bar.java").write_text("class Bar {}")

    projects_yaml = tmp_path / "projects.yaml"
    projects_yaml.write_text(
        f"projects:\n"
        f"  - name: ace\n"
        f"    source_root: {tmp_path}\n"
        f"    graph_index:\n"
        f"      include:\n"
        f"        - frameworks/base\n"
        f"        - packages/apps/Settings\n"
    )

    env = _dry_run_env({
        "PROJECTS_CONFIG_PATH": str(projects_yaml),
    })
    result = subprocess.run(
        ["bash", "scripts/indexing/build_graph_index_batch.sh", "--reset"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"Expected 0, got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # Count --reset occurrences in DRY_RUN_CMD lines only
    dry_run_cmd_lines = [
        line for line in combined.splitlines() if line.startswith("DRY_RUN_CMD")
    ]
    reset_count = sum(1 for line in dry_run_cmd_lines if "--reset" in line)
    assert reset_count == 1, (
        f"Expected --reset exactly once in DRY_RUN_CMD lines, got {reset_count}.\n"
        f"DRY_RUN_CMD lines:\n" + "\n".join(dry_run_cmd_lines)
    )
