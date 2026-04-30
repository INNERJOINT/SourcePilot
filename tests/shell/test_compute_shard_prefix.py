"""Tests for _compute_shard_prefix in scripts/indexing/_indexing_lib.sh."""

from __future__ import annotations

from tests.shell.conftest import PROJ_ROOT, _run_bash

INDEXING_LIB = str(PROJ_ROOT / "scripts" / "indexing" / "_indexing_lib.sh")


def _call_prefix(project: str, sub_path: str) -> str:
    script = f"""
source "{INDEXING_LIB}"
_compute_shard_prefix "{project}" "{sub_path}"
"""
    r = _run_bash(script)
    assert r.returncode == 0, f"stderr={r.stderr}"
    return r.stdout.strip()


def test_simple_slash():
    assert _call_prefix("proj1", "external/openssl") == "proj1_external_openssl"


def test_no_slash():
    assert _call_prefix("myproject", "frameworks") == "myproject_frameworks"


def test_multiple_slashes():
    result = _call_prefix("aosp", "packages/apps/Settings")
    assert result == "aosp_packages_apps_Settings"


def test_empty_sub_path():
    result = _call_prefix("proj", "")
    assert result == "proj_"


def test_project_name_preserved():
    result = _call_prefix("t2_aosp14", "external/openssl")
    assert result.startswith("t2_aosp14_")
