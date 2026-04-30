"""Tests for pure helper functions in scripts/indexing/dense/build_dense_index_batch.sh.

Covers:
  - _enumerate_default_repos: builds dir|name lines from a tmp AOSP-like tree
  - _parse_dense_config_lines: populates PROJECT_HEADERS and PROJECT_INCLUDES_BY_NAME
"""

from __future__ import annotations

from pathlib import Path

from tests.shell.conftest import PROJ_ROOT, _run_bash

BATCH_SH = str(PROJ_ROOT / "scripts" / "indexing" / "dense" / "build_dense_index_batch.sh")
INDEXING_LIB = str(PROJ_ROOT / "scripts" / "indexing" / "_indexing_lib.sh")
COMMON_SH = str(PROJ_ROOT / "scripts" / "share" / "_common.sh")


def _source_batch(snippet: str, tmp_path: Path | None = None) -> object:
    script = f"""
set -euo pipefail
source "{BATCH_SH}"
{snippet}
"""
    return _run_bash(script)


# ---------------------------------------------------------------------------
# _enumerate_default_repos
# ---------------------------------------------------------------------------

def test_enumerate_default_repos_frameworks(tmp_path: Path):
    """frameworks/* directories are emitted as dir|frameworks/name lines."""
    fw_base = tmp_path / "frameworks" / "base"
    fw_base.mkdir(parents=True)
    fw_av = tmp_path / "frameworks" / "av"
    fw_av.mkdir(parents=True)

    script = f"""
set -euo pipefail
source "{BATCH_SH}"
_enumerate_default_repos "{tmp_path}"
"""
    r = _run_bash(script)
    assert r.returncode == 0, f"stderr={r.stderr}"
    lines = r.stdout.strip().splitlines()
    names = [ln.split("|")[1] for ln in lines if "|" in ln]
    assert "frameworks/base" in names
    assert "frameworks/av" in names


def test_enumerate_default_repos_packages(tmp_path: Path):
    """packages/*/* directories are emitted as dir|packages/cat/name lines."""
    (tmp_path / "packages" / "apps" / "Settings").mkdir(parents=True)
    (tmp_path / "packages" / "providers" / "ContactsProvider").mkdir(parents=True)

    script = f"""
set -euo pipefail
source "{BATCH_SH}"
_enumerate_default_repos "{tmp_path}"
"""
    r = _run_bash(script)
    assert r.returncode == 0, f"stderr={r.stderr}"
    names = [ln.split("|")[1] for ln in r.stdout.strip().splitlines() if "|" in ln]
    assert "packages/apps/Settings" in names
    assert "packages/providers/ContactsProvider" in names


def test_enumerate_default_repos_empty_root(tmp_path: Path):
    """No frameworks/ or packages/ → no output lines (no error)."""
    script = f"""
set -euo pipefail
source "{BATCH_SH}"
_enumerate_default_repos "{tmp_path}"
"""
    r = _run_bash(script)
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert r.stdout.strip() == ""


# ---------------------------------------------------------------------------
# _parse_dense_config_lines
# ---------------------------------------------------------------------------

def _build_config_lines(*projects) -> str:
    """Build a bash CONFIG_LINES array literal.

    Each project is a dict: name, root, collection, mode, includes (list of (dir, name) tuples).
    """
    entries = []
    for p in projects:
        header = f"P\t{p['name']}\t{p['root']}\t{p['collection']}\t{p['mode']}"
        entries.append(f'  "{header}"')
        for inc_dir, inc_name in p.get("includes", []):
            entries.append(f'  "I\t{inc_dir}\t{inc_name}"')
        entries.append('  "E"')
    return "CONFIG_LINES=(\n" + "\n".join(entries) + "\n)"


def test_parse_dense_config_single_project():
    """A single P/I/E block populates PROJECT_HEADERS with one entry."""
    lines = _build_config_lines(
        {"name": "aosp14", "root": "/src/aosp14", "collection": "col14", "mode": "explicit",
         "includes": [("/src/aosp14/frameworks/base", "frameworks/base")]}
    )
    script = f"""
set -euo pipefail
source "{BATCH_SH}"
{lines}
declare -A PROJECT_INCLUDES_BY_NAME=()
_parse_dense_config_lines
echo "HEADERS_COUNT=${{#PROJECT_HEADERS[@]}}"
echo "FIRST_HEADER=${{PROJECT_HEADERS[0]}}"
echo "INCLUDES_aosp14=${{PROJECT_INCLUDES_BY_NAME[aosp14]}}"
"""
    r = _run_bash(script)
    assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
    assert "HEADERS_COUNT=1" in r.stdout
    assert "aosp14" in r.stdout
    assert "frameworks/base" in r.stdout


def test_parse_dense_config_two_projects():
    """Two projects → PROJECT_HEADERS has 2 entries."""
    lines = _build_config_lines(
        {"name": "alpha", "root": "/src/a", "collection": "col_a", "mode": "explicit",
         "includes": [("/src/a/frameworks/base", "frameworks/base")]},
        {"name": "beta", "root": "/src/b", "collection": "col_b", "mode": "default"},
    )
    script = f"""
set -euo pipefail
source "{BATCH_SH}"
{lines}
declare -A PROJECT_INCLUDES_BY_NAME=()
_parse_dense_config_lines
echo "HEADERS_COUNT=${{#PROJECT_HEADERS[@]}}"
"""
    r = _run_bash(script)
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "HEADERS_COUNT=2" in r.stdout


def test_parse_dense_config_empty_includes():
    """A project with no I records gets an empty includes entry."""
    lines = _build_config_lines(
        {"name": "proj1", "root": "/src/p", "collection": "c", "mode": "default"}
    )
    script = f"""
set -euo pipefail
source "{BATCH_SH}"
{lines}
declare -A PROJECT_INCLUDES_BY_NAME=()
_parse_dense_config_lines
echo "INCLUDES_proj1='${{PROJECT_INCLUDES_BY_NAME[proj1]:-}}'"
"""
    r = _run_bash(script)
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "INCLUDES_proj1=''" in r.stdout


def test_parse_dense_config_invalid_record_fails():
    """A record with wrong type tag causes non-zero exit."""
    script = f"""
source "{BATCH_SH}"
CONFIG_LINES=("X\\tbad\\tdata")
declare -A PROJECT_INCLUDES_BY_NAME=()
_parse_dense_config_lines
"""
    r = _run_bash(script)
    assert r.returncode != 0
