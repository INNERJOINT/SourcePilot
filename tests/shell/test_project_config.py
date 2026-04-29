"""Tests for scripts/indexing/_project_config.py.

Covers:
  - --list output (one project name per line)
  - --project output (shell-safe KEY='value' lines)
  - --project with unknown name exits non-zero
  - _shell_quote escapes embedded single quotes
  - sparse_index overrides top-level fields
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

from tests.shell.conftest import PROJ_ROOT

CONFIG_SCRIPT = PROJ_ROOT / "scripts" / "indexing" / "_project_config.py"


def _write_config(tmp_path: Path, yaml_content: str) -> Path:
    cfg = tmp_path / "projects.yaml"
    cfg.write_text(textwrap.dedent(yaml_content))
    return cfg


def _run_config(
    *args: str, config_path: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env_extra = {}
    if config_path:
        env_extra["PROJECTS_CONFIG_PATH"] = str(config_path)
    import os

    env = {**os.environ, **env_extra}
    return subprocess.run(
        ["python3", str(CONFIG_SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


def test_list_outputs_project_names(tmp_path):
    cfg = _write_config(
        tmp_path,
        """\
        projects:
          - name: alpha
            repo_path: /opt/alpha/.repo
            index_dir: /idx/alpha
            zoekt_url: http://localhost:6070
          - name: beta
            repo_path: /opt/beta/.repo
            index_dir: /idx/beta
            zoekt_url: http://localhost:6071
        """,
    )
    r = _run_config("--list", config_path=cfg)
    assert r.returncode == 0
    lines = r.stdout.strip().splitlines()
    assert lines == ["alpha", "beta"]


def test_project_outputs_shell_safe_lines(tmp_path):
    cfg = _write_config(
        tmp_path,
        """\
        projects:
          - name: myproj
            repo_path: /opt/aosp/.repo
            index_dir: /data/index
            zoekt_url: http://localhost:6070
        """,
    )
    r = _run_config("--project", "myproj", config_path=cfg)
    assert r.returncode == 0
    assert "NAME='myproj'" in r.stdout
    assert "REPO_PATH='/opt/aosp/.repo'" in r.stdout
    assert "INDEX_DIR='/data/index'" in r.stdout
    assert "ZOEKT_URL='http://localhost:6070'" in r.stdout


def test_project_unknown_name_exits_nonzero(tmp_path):
    cfg = _write_config(
        tmp_path,
        """\
        projects:
          - name: alpha
            repo_path: /opt/alpha/.repo
            index_dir: /idx
            zoekt_url: http://localhost:6070
        """,
    )
    r = _run_config("--project", "nonexistent", config_path=cfg)
    assert r.returncode != 0
    assert "unknown project" in r.stderr.lower()


def test_shell_quote_escapes_single_quotes(tmp_path):
    cfg = _write_config(
        tmp_path,
        """\
        projects:
          - name: proj's
            repo_path: /opt/it's/.repo
            index_dir: /idx
            zoekt_url: http://localhost:6070
        """,
    )
    r = _run_config("--project", "proj's", config_path=cfg)
    assert r.returncode == 0
    # Escaped single quote: 'proj'\''s'
    assert "NAME='proj'\\''s'" in r.stdout


def test_sparse_index_overrides_top_level(tmp_path):
    cfg = _write_config(
        tmp_path,
        """\
        projects:
          - name: overridden
            repo_path: /opt/aosp/.repo
            index_dir: /default/index
            zoekt_url: http://default:6070
            sparse_index:
              index_dir: /sparse/index
              zoekt_url: http://sparse:6070
        """,
    )
    r = _run_config("--project", "overridden", config_path=cfg)
    assert r.returncode == 0
    assert "INDEX_DIR='/sparse/index'" in r.stdout
    assert "ZOEKT_URL='http://sparse:6070'" in r.stdout


def test_all_outputs_multiple_projects(tmp_path):
    cfg = _write_config(
        tmp_path,
        """\
        projects:
          - name: first
            repo_path: /a/.repo
            index_dir: /idx/a
            zoekt_url: http://localhost:6070
          - name: second
            repo_path: /b/.repo
            index_dir: /idx/b
            zoekt_url: http://localhost:6071
        """,
    )
    r = _run_config("--all", config_path=cfg)
    assert r.returncode == 0
    assert "NAME='first'" in r.stdout
    assert "NAME='second'" in r.stdout


def test_shared_index_dir_from_top_level(tmp_path):
    """Top-level sparse_index.shared_index_dir is emitted as SHARED_INDEX_DIR."""
    cfg = _write_config(
        tmp_path,
        """\
        sparse_index:
          shared_index_dir: /mnt/data/zoekt-index
        projects:
          - name: proj
            repo_path: /opt/.repo
            index_dir: /idx
            zoekt_url: http://localhost:6070
        """,
    )
    r = _run_config("--project", "proj", config_path=cfg)
    assert r.returncode == 0
    assert "SHARED_INDEX_DIR='/mnt/data/zoekt-index'" in r.stdout


def test_shared_index_dir_per_project_override(tmp_path):
    """Per-project sparse_index.shared_index_dir overrides the top-level default."""
    cfg = _write_config(
        tmp_path,
        """\
        sparse_index:
          shared_index_dir: /mnt/data/default-index
        projects:
          - name: proj
            repo_path: /opt/.repo
            index_dir: /idx
            zoekt_url: http://localhost:6070
            sparse_index:
              shared_index_dir: /mnt/data/project-index
        """,
    )
    r = _run_config("--project", "proj", config_path=cfg)
    assert r.returncode == 0
    assert "SHARED_INDEX_DIR='/mnt/data/project-index'" in r.stdout


def test_no_shared_index_dir_omits_line(tmp_path):
    """When no shared_index_dir is set, SHARED_INDEX_DIR line is omitted."""
    cfg = _write_config(
        tmp_path,
        """\
        projects:
          - name: proj
            repo_path: /opt/.repo
            index_dir: /idx
            zoekt_url: http://localhost:6070
        """,
    )
    r = _run_config("--project", "proj", config_path=cfg)
    assert r.returncode == 0
    assert "SHARED_INDEX_DIR" not in r.stdout


def test_missing_config_exits_nonzero(tmp_path):
    missing = tmp_path / "nonexistent.yaml"
    r = _run_config("--list", config_path=missing)
    assert r.returncode != 0
    assert "not found" in r.stderr.lower()
