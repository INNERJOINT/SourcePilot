"""Tests for GET /api/projects endpoint."""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sp_cockpit.api.app import create_app


@pytest.fixture()
def client():
    return TestClient(create_app())


def test_projects_empty_when_no_file(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECTS_CONFIG_PATH", str(tmp_path / "nonexistent.yaml"))
    # Re-import to pick up env — easier to call the loader directly
    from sp_cockpit.api.projects import _load_projects
    assert _load_projects() == []


def test_projects_from_env(tmp_path, monkeypatch):
    yaml_file = tmp_path / "projects.yaml"
    yaml_file.write_text(textwrap.dedent("""\
        projects:
          - name: aosp_project
            source_root: /opt/aosp/aosp_project
            repo_path: /opt/aosp/aosp_project/.repo
            zoekt_url: http://localhost:6070
    """))
    monkeypatch.setenv("PROJECTS_CONFIG_PATH", str(yaml_file))

    from sp_cockpit.api.projects import _load_projects
    result = _load_projects()
    assert len(result) == 1
    assert result[0]["name"] == "aosp_project"
    assert result[0]["zoekt_url"] == "http://localhost:6070"


def test_get_projects_endpoint(tmp_path, monkeypatch):
    yaml_file = tmp_path / "projects.yaml"
    yaml_file.write_text(textwrap.dedent("""\
        projects:
          - name: aosp_project
            source_root: /opt/aosp/aosp_project
            repo_path: /opt/aosp/aosp_project/.repo
            zoekt_url: http://localhost:6070
          - name: beta
            source_root: /opt/aosp/beta
            repo_path: /opt/aosp/beta/.repo
            zoekt_url: http://localhost:6071
    """))
    monkeypatch.setenv("PROJECTS_CONFIG_PATH", str(yaml_file))

    client = TestClient(create_app())
    r = client.get("/api/projects")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["name"] == "aosp_project"
    assert data[1]["name"] == "beta"
    assert "source_root" in data[0]
    assert "repo_path" in data[0]
    assert "zoekt_url" in data[0]
