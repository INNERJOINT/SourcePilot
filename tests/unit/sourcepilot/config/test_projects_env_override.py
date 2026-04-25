"""
Test that ZOEKT_URL_<NAME> env vars override per-project zoekt_url from YAML.

This lets the same projects.yaml work for both bare-process dev (yaml default
http://localhost:6071) and Docker (compose injects
ZOEKT_URL_T2=http://sparse-index-zoekt-t2:6070).
"""

import textwrap

from config.projects import load_projects, reload_projects


def _write_yaml(tmp_path):
    p = tmp_path / "projects.yaml"
    p.write_text(
        textwrap.dedent(
            """
            projects:
              - name: ace
                source_root: /mnt/code/ACE
                repo_path: /mnt/code/ACE/.repo
                sparse_index:
                  index_dir: /mnt/code/ACE/.repo/.zoekt
                  zoekt_url: http://localhost:6070
              - name: t2
                source_root: /mnt/code/T2
                repo_path: /mnt/code/T2/.repo
                sparse_index:
                  index_dir: /mnt/code/T2/.repo/.zoekt
                  zoekt_url: http://localhost:6071
            """
        )
    )
    return str(p)


def test_yaml_default_when_env_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("ZOEKT_URL_ACE", raising=False)
    monkeypatch.delenv("ZOEKT_URL_T2", raising=False)
    cfg = _write_yaml(tmp_path)
    monkeypatch.setenv("PROJECTS_CONFIG_PATH", cfg)
    reload_projects()
    projects = {p.name: p for p in load_projects()}
    assert projects["ace"].zoekt_url == "http://localhost:6070"
    assert projects["t2"].zoekt_url == "http://localhost:6071"


def test_env_overrides_yaml(tmp_path, monkeypatch):
    cfg = _write_yaml(tmp_path)
    monkeypatch.setenv("PROJECTS_CONFIG_PATH", cfg)
    monkeypatch.setenv("ZOEKT_URL_T2", "http://sparse-index-zoekt-t2:6070")
    reload_projects()
    projects = {p.name: p for p in load_projects()}
    # ace falls back to yaml since ZOEKT_URL_ACE is unset
    assert projects["ace"].zoekt_url == "http://localhost:6070"
    # t2 picks up the override
    assert projects["t2"].zoekt_url == "http://sparse-index-zoekt-t2:6070"
