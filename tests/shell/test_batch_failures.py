"""Failure-path / batch-continue tests for dense and structural batch indexing scripts.

Both scripts intentionally omit -e so a single project/repo failure must not
abort remaining entries.  These tests verify that contract using a fake
BUILD_SCRIPT injected via the BUILD_SCRIPT env variable.
"""

from __future__ import annotations

import os
import stat
import textwrap
from pathlib import Path

from tests.shell.conftest import PROJ_ROOT, _run_bash

DENSE_BATCH = str(PROJ_ROOT / "scripts" / "indexing" / "dense" / "build_dense_index_batch.sh")
STRUCTURAL_BATCH = str(
    PROJ_ROOT / "scripts" / "indexing" / "structural" / "build_structural_index_batch.sh"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source_dir(tmp_path: Path, rel_path: str) -> Path:
    """Create a source directory with a dummy .java file inside."""
    d = tmp_path / rel_path
    d.mkdir(parents=True, exist_ok=True)
    (d / "Dummy.java").write_text("// dummy\n")
    return d


def _make_counting_build_script(tmp_path: Path, *, fail_first: int = 1) -> Path:
    """Return a bash script: exits 1 for the first `fail_first` calls, 0 afterwards."""
    counter_file = tmp_path / "call_count"
    counter_file.write_text("0\n")
    script = tmp_path / "fake_build.sh"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            count=$(cat "{counter_file}")
            count=$((count + 1))
            echo "$count" > "{counter_file}"
            if [ "$count" -le {fail_first} ]; then
                echo "FAKE BUILD FAIL call=$count" >&2
                exit 1
            fi
            echo "FAKE BUILD OK call=$count" >&2
            exit 0
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


def _base_env(cfg_path: Path, build_script: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "TERM": "dumb",
        "NO_COLOR": "1",
        "PROJECTS_CONFIG_PATH": str(cfg_path),
        "BUILD_SCRIPT": str(build_script),
        "INDEXING_DRY_RUN": "0",
        "INDEXING_SKIP_SOURCE_SCAN": "1",  # skip find(1) probe — source dirs are stubs
        "INDEXING_API_URL": "http://localhost:19999",  # non-existent; lib warns but continues
    }


# ---------------------------------------------------------------------------
# Dense batch: per-repo failure must not abort remaining repos
# ---------------------------------------------------------------------------


def test_dense_batch_continues_after_per_repo_failure(tmp_path):
    """First repo BUILD_SCRIPT exit=1, second exit=0 → summary shows Succeeded≥1 AND Failed≥1."""
    root = tmp_path / "aosp_root"
    _make_source_dir(root, "frameworks/alpha")
    _make_source_dir(root, "frameworks/beta")

    cfg = tmp_path / "projects.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""\
            projects:
              - name: testproj
                source_root: {root}
                dense_index:
                  collection_name: testproj_col
                  include:
                    - frameworks/alpha
                    - frameworks/beta
            """
        )
    )

    build_script = _make_counting_build_script(tmp_path, fail_first=1)
    env = _base_env(cfg, build_script)

    result = _run_bash(f'bash "{DENSE_BATCH}"', env=env, timeout=30)
    combined = result.stdout + result.stderr

    assert "ALL PROJECTS" in combined, f"Summary line missing:\n{combined}"

    import re

    m_succ = re.search(r"Succeeded:\s*(\d+)", combined)
    m_fail = re.search(r"Failed:\s*(\d+)", combined)
    assert m_succ and int(m_succ.group(1)) >= 1, f"Expected Succeeded>=1:\n{combined}"
    assert m_fail and int(m_fail.group(1)) >= 1, f"Expected Failed>=1:\n{combined}"


def test_dense_batch_all_repos_fail_still_prints_summary(tmp_path):
    """Even when every repo fails the dense batch still prints the summary line."""
    root = tmp_path / "aosp_root"
    _make_source_dir(root, "frameworks/alpha")

    cfg = tmp_path / "projects.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""\
            projects:
              - name: failproj
                source_root: {root}
                dense_index:
                  collection_name: failproj_col
                  include:
                    - frameworks/alpha
            """
        )
    )

    build_script = _make_counting_build_script(tmp_path, fail_first=999)
    env = _base_env(cfg, build_script)

    result = _run_bash(f'bash "{DENSE_BATCH}"', env=env, timeout=30)
    combined = result.stdout + result.stderr

    assert "ALL PROJECTS" in combined, f"Summary line missing:\n{combined}"

    import re

    m = re.search(r"Failed:\s*(\d+)", combined)
    assert m and int(m.group(1)) >= 1, f"Expected Failed>=1:\n{combined}"


# ---------------------------------------------------------------------------
# Structural batch: per-project failure must not abort remaining projects
# ---------------------------------------------------------------------------


def test_structural_batch_continues_after_project_failure(tmp_path):
    """First project BUILD_SCRIPT exit=1, second exit=0 → both projects appear in output."""
    root_a = tmp_path / "aosp_a"
    root_b = tmp_path / "aosp_b"
    root_a.mkdir()
    root_b.mkdir()

    cfg = tmp_path / "projects.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""\
            projects:
              - name: proj_a
                source_root: {root_a}
                structural_index:
                  enabled: true
              - name: proj_b
                source_root: {root_b}
                structural_index:
                  enabled: true
            """
        )
    )

    build_script = _make_counting_build_script(tmp_path, fail_first=1)
    env = _base_env(cfg, build_script)

    result = _run_bash(f'bash "{STRUCTURAL_BATCH}"', env=env, timeout=30)
    combined = result.stdout + result.stderr

    # Both projects must be mentioned
    assert "proj_a" in combined, f"proj_a missing:\n{combined}"
    assert "proj_b" in combined, f"proj_b missing:\n{combined}"

    # Summary line
    assert "Structural batch complete" in combined, (
        f"Missing structural summary line:\n{combined}"
    )

    import re

    m_succ = re.search(r"Succeeded=(\d+)", combined)
    m_fail = re.search(r"Failed=(\d+)", combined)
    assert m_succ and int(m_succ.group(1)) >= 1, f"Expected Succeeded>=1:\n{combined}"
    assert m_fail and int(m_fail.group(1)) >= 1, f"Expected Failed>=1:\n{combined}"


def test_structural_batch_dry_run_all_succeed(tmp_path):
    """INDEXING_DRY_RUN=1 exits 0 without invoking BUILD_SCRIPT."""
    root_a = tmp_path / "aosp_a"
    root_b = tmp_path / "aosp_b"
    root_a.mkdir()
    root_b.mkdir()

    cfg = tmp_path / "projects.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""\
            projects:
              - name: proj_a
                source_root: {root_a}
                structural_index:
                  enabled: true
              - name: proj_b
                source_root: {root_b}
                structural_index:
                  enabled: true
            """
        )
    )

    # Build script would always fail — but DRY_RUN should skip it
    build_script = _make_counting_build_script(tmp_path, fail_first=999)
    env = _base_env(cfg, build_script)
    env["INDEXING_DRY_RUN"] = "1"

    result = _run_bash(f'bash "{STRUCTURAL_BATCH}"', env=env, timeout=30)

    assert result.returncode == 0, (
        f"INDEXING_DRY_RUN=1 should exit 0; rc={result.returncode}\n"
        f"stderr: {result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "DRY_RUN" in combined, f"Expected DRY_RUN marker:\n{combined}"
    assert "proj_a" in combined and "proj_b" in combined
