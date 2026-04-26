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
              - name: aosp_project
                source_root: /opt/aosp/aosp_project
                repo_path: /opt/aosp/aosp_project/.repo
                sparse_index:
                  index_dir: /opt/aosp/aosp_project/.repo/.zoekt
                  zoekt_url: http://localhost:6070
              - name: t2
                source_root: /opt/aosp/aosp_project2
                repo_path: /opt/aosp/aosp_project2/.repo
                sparse_index:
                  index_dir: /opt/aosp/aosp_project2/.repo/.zoekt
                  zoekt_url: http://localhost:6071
            """
        )
    )
    return str(p)


def test_yaml_default_when_env_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("ZOEKT_URL_AOSP_PROJECT", raising=False)
    monkeypatch.delenv("ZOEKT_URL_T2", raising=False)
    cfg = _write_yaml(tmp_path)
    monkeypatch.setenv("PROJECTS_CONFIG_PATH", cfg)
    reload_projects()
    projects = {p.name: p for p in load_projects()}
    assert projects["aosp_project"].zoekt_url == "http://localhost:6070"
    assert projects["t2"].zoekt_url == "http://localhost:6071"


def test_env_overrides_yaml(tmp_path, monkeypatch):
    cfg = _write_yaml(tmp_path)
    monkeypatch.setenv("PROJECTS_CONFIG_PATH", cfg)
    monkeypatch.setenv("ZOEKT_URL_T2", "http://sparse-index-zoekt-t2:6070")
    reload_projects()
    projects = {p.name: p for p in load_projects()}
    # aosp_project falls back to yaml since ZOEKT_URL_AOSP_PROJECT is unset
    assert projects["aosp_project"].zoekt_url == "http://localhost:6070"
    # t2 picks up the override
    assert projects["t2"].zoekt_url == "http://sparse-index-zoekt-t2:6070"
