"""Tests for scripts/indexing/_indexing_lib.sh shared functions.

Covers:
  - Source guard (double-source is idempotent)
  - _get_project_config safe key=value parsing
  - _wait_for_slot (background job gating)
"""

from __future__ import annotations

from tests.shell.conftest import PROJ_ROOT, _run_bash


INDEXING_LIB = PROJ_ROOT / "scripts" / "indexing" / "_indexing_lib.sh"
COMMON_SH = PROJ_ROOT / "scripts" / "share" / "_common.sh"


def _source_preamble() -> str:
    """Bash preamble that sources _common.sh then _indexing_lib.sh."""
    return f"""\
        source "{COMMON_SH}"
        source "{INDEXING_LIB}"
    """


# ── source guard ──────────────────────────────────────────────────────────


def test_source_guard_idempotent():
    """Sourcing _indexing_lib.sh twice does not error."""
    r = _run_bash(f"""\
        source "{COMMON_SH}"
        source "{INDEXING_LIB}"
        source "{INDEXING_LIB}"
        echo "ok"
    """)
    assert r.returncode == 0
    assert "ok" in r.stdout


# ── _get_project_config ───────────────────────────────────────────────────


def test_get_project_config_parses_simple_values(tmp_path):
    """_get_project_config sets NAME, REPO_PATH etc. from Python output."""
    fake_py = tmp_path / "fake_config.py"
    fake_py.write_text(
        """\
print("NAME='myproject'")
print("REPO_PATH='/opt/aosp/myproject/.repo'")
print("INDEX_DIR='/data/index'")
print("ZOEKT_URL='http://localhost:6070'")
"""
    )

    r = _run_bash(f"""\
        source "{COMMON_SH}"
        source "{INDEXING_LIB}"
        # Override the pyhelper to our fake
        _INDEXING_PYHELPER="{fake_py}"
        _get_project_config ignored_arg
        echo "NAME=$NAME"
        echo "REPO_PATH=$REPO_PATH"
        echo "INDEX_DIR=$INDEX_DIR"
        echo "ZOEKT_URL=$ZOEKT_URL"
    """)
    assert r.returncode == 0
    assert "NAME=myproject" in r.stdout
    assert "REPO_PATH=/opt/aosp/myproject/.repo" in r.stdout
    assert "INDEX_DIR=/data/index" in r.stdout
    assert "ZOEKT_URL=http://localhost:6070" in r.stdout


def test_get_project_config_handles_spaces_in_values(tmp_path):
    """Values with spaces are handled correctly (quotes stripped)."""
    fake_py = tmp_path / "fake_config.py"
    fake_py.write_text(
        """\
print("NAME='my project'")
print("REPO_PATH='/opt/aosp/my project/.repo'")
print("INDEX_DIR='/data/my index'")
print("ZOEKT_URL='http://localhost:6070'")
"""
    )

    r = _run_bash(f"""\
        source "{COMMON_SH}"
        source "{INDEXING_LIB}"
        _INDEXING_PYHELPER="{fake_py}"
        _get_project_config ignored
        echo "NAME=$NAME"
    """)
    assert r.returncode == 0
    assert "NAME=my project" in r.stdout


def test_get_project_config_warns_unknown_key(tmp_path):
    """Unknown keys emit a warning but don't cause failure."""
    fake_py = tmp_path / "fake_config.py"
    fake_py.write_text(
        """\
print("NAME='test'")
print("UNKNOWN_KEY='value'")
print("REPO_PATH='/tmp'")
print("INDEX_DIR='/tmp'")
print("ZOEKT_URL='http://localhost:6070'")
"""
    )

    r = _run_bash(f"""\
        source "{COMMON_SH}"
        source "{INDEXING_LIB}"
        _INDEXING_PYHELPER="{fake_py}"
        _get_project_config ignored
        echo "NAME=$NAME"
    """)
    assert r.returncode == 0
    assert "Unknown config key: UNKNOWN_KEY" in r.stderr
    assert "NAME=test" in r.stdout


def test_get_project_config_handles_equals_in_value(tmp_path):
    """Values containing = signs are parsed correctly (split at first = only)."""
    fake_py = tmp_path / "fake_config.py"
    fake_py.write_text(
        """\
print("NAME='proj'")
print("REPO_PATH='/tmp'")
print("INDEX_DIR='/tmp'")
print("ZOEKT_URL='http://localhost:6070?key=val&x=y'")
"""
    )

    r = _run_bash(f"""\
        source "{COMMON_SH}"
        source "{INDEXING_LIB}"
        _INDEXING_PYHELPER="{fake_py}"
        _get_project_config ignored
        echo "ZOEKT_URL=$ZOEKT_URL"
    """)
    assert r.returncode == 0
    assert "ZOEKT_URL=http://localhost:6070?key=val&x=y" in r.stdout


def test_get_project_config_handles_empty_lines(tmp_path):
    """Empty lines in Python output are skipped."""
    fake_py = tmp_path / "fake_config.py"
    fake_py.write_text(
        """\
print("NAME='proj'")
print("")
print("REPO_PATH='/tmp'")
print("INDEX_DIR='/tmp'")
print("ZOEKT_URL='http://localhost:6070'")
"""
    )

    r = _run_bash(f"""\
        source "{COMMON_SH}"
        source "{INDEXING_LIB}"
        _INDEXING_PYHELPER="{fake_py}"
        _get_project_config ignored
        echo "NAME=$NAME"
        echo "REPO_PATH=$REPO_PATH"
    """)
    assert r.returncode == 0
    assert "NAME=proj" in r.stdout
    assert "REPO_PATH=/tmp" in r.stdout


# ── _wait_for_slot ────────────────────────────────────────────────────────


def test_wait_for_slot_returns_immediately_when_no_jobs():
    """_wait_for_slot returns immediately when no background jobs exist."""
    r = _run_bash(f"""\
        source "{COMMON_SH}"
        source "{INDEXING_LIB}"
        _wait_for_slot 4
        echo "done"
    """)
    assert r.returncode == 0
    assert "done" in r.stdout
