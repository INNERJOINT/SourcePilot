"""CLI behavior tests for scripts/indexing/sparse/zoekt_delete_shard.sh.

Covers:
  - --help exits 0
  - No arguments exits non-zero (exit 2)
  - Deletes matching .zoekt shard files
  - No matching shards exits non-zero
  - Non-existent index dir exits non-zero
  - Index dir path with spaces works correctly
"""

from __future__ import annotations

from tests.shell.conftest import PROJ_ROOT, _run_bash

SCRIPT = str(PROJ_ROOT / "scripts" / "indexing" / "sparse" / "zoekt_delete_shard.sh")


def test_help_exits_zero():
    r = _run_bash(f'bash "{SCRIPT}" --help')
    assert r.returncode == 0


def test_no_args_exits_nonzero():
    r = _run_bash(f'bash "{SCRIPT}"')
    assert r.returncode != 0
    assert "Usage" in r.stderr or "repo_name" in r.stderr


def test_deletes_matching_shards(tmp_path):
    """Create fake .zoekt files, run script, verify they are deleted."""
    index_dir = tmp_path / "index"
    index_dir.mkdir()

    # Create shard files matching the repo name pattern
    (index_dir / "myrepo.00000.zoekt").write_text("fake")
    (index_dir / "myrepo.00001.zoekt").write_text("fake")
    # This one should NOT be deleted (different repo)
    (index_dir / "otherrepo.00000.zoekt").write_text("keep")

    r = _run_bash(
        f'bash "{SCRIPT}" myrepo',
        env={
            "PATH": __import__("os").environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp_path),
            "TERM": "dumb",
            "NO_COLOR": "1",
            "ZOEKT_INDEX_DIR": str(index_dir),
        },
    )

    assert r.returncode == 0
    assert not (index_dir / "myrepo.00000.zoekt").exists()
    assert not (index_dir / "myrepo.00001.zoekt").exists()
    assert (index_dir / "otherrepo.00000.zoekt").exists()


def test_no_matching_shards_exits_nonzero(tmp_path):
    index_dir = tmp_path / "index"
    index_dir.mkdir()

    r = _run_bash(
        f'bash "{SCRIPT}" nonexistent',
        env={
            "PATH": __import__("os").environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp_path),
            "TERM": "dumb",
            "NO_COLOR": "1",
            "ZOEKT_INDEX_DIR": str(index_dir),
        },
    )

    assert r.returncode != 0
    assert "No shards found" in r.stderr


def test_nonexistent_index_dir_exits_nonzero(tmp_path):
    r = _run_bash(
        f'bash "{SCRIPT}" myrepo',
        env={
            "PATH": __import__("os").environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp_path),
            "TERM": "dumb",
            "NO_COLOR": "1",
            "ZOEKT_INDEX_DIR": str(tmp_path / "does_not_exist"),
        },
    )

    assert r.returncode != 0
    assert "not found" in r.stderr or "Index directory" in r.stderr


def test_index_dir_with_spaces(tmp_path):
    """Paths containing spaces must work correctly."""
    index_dir = tmp_path / "dir with spaces"
    index_dir.mkdir()

    (index_dir / "spacerepo.00000.zoekt").write_text("fake")

    r = _run_bash(
        f'bash "{SCRIPT}" spacerepo',
        env={
            "PATH": __import__("os").environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp_path),
            "TERM": "dumb",
            "NO_COLOR": "1",
            "ZOEKT_INDEX_DIR": str(index_dir),
        },
    )

    assert r.returncode == 0
    assert not (index_dir / "spacerepo.00000.zoekt").exists()
