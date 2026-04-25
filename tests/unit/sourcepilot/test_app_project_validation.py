"""
Tests for _resolve_project validation logic in src/app.py.

Covers: multi-project missing field → 400, unknown project → 400,
valid project → 200, single-project no field → 200.
"""
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

import config.projects as cp
from config.projects import ProjectConfig

# ─── Shared test fixtures ─────────────────────────────────────────────────────

PROJECT_ACE = ProjectConfig(
    name="ace",
    source_root="/x",
    repo_path="/repo/ace",
    index_dir="/idx/ace",
    zoekt_url="http://z1:6070",
    dense_collection_name="aosp_code_ace",
)
PROJECT_T2 = ProjectConfig(
    name="t2",
    source_root="/y",
    repo_path="/repo/t2",
    index_dir="/idx/t2",
    zoekt_url="http://z2:6071",
    dense_collection_name="aosp_code_t2",
)

ENDPOINTS = [
    ("/api/search", {"query": "foo"}),
    ("/api/search_symbol", {"symbol": "Bar"}),
    ("/api/search_file", {"path": "X.java"}),
    ("/api/search_regex", {"pattern": "p"}),
    ("/api/list_repos", {}),
    ("/api/get_file_content", {"repo": "r", "filepath": "f"}),
]


def _make_client(monkeypatch, projects: list[ProjectConfig]) -> TestClient:
    """Patch project cache and gateway functions, return a test client."""
    monkeypatch.setattr(cp, "_projects_cache", projects)
    monkeypatch.setattr("config.AUDIT_ENABLED", False)
    monkeypatch.setattr("config.AUDIT_SUMMARY_INTERVAL", 0)
    monkeypatch.setattr("config.NL_ENABLED", False)

    import gateway.gateway as gw

    gw._adapters.clear()

    empty_list: AsyncMock = AsyncMock(return_value=[])
    empty_dict: AsyncMock = AsyncMock(
        return_value={"content": "", "total_lines": 0, "start_line": 1, "end_line": 1}
    )

    monkeypatch.setattr(gw, "search", empty_list)
    monkeypatch.setattr(gw, "search_symbol", empty_list)
    monkeypatch.setattr(gw, "search_file", empty_list)
    monkeypatch.setattr(gw, "search_regex", empty_list)
    monkeypatch.setattr(gw, "list_repos", empty_list)
    monkeypatch.setattr(gw, "get_file_content", empty_dict)

    from app import app

    return TestClient(app)


# ─── Multi-project: missing project field → 400 ───────────────────────────────


@pytest.mark.parametrize("endpoint,base_body", ENDPOINTS)
def test_multi_project_missing_returns_400(endpoint, base_body, monkeypatch):
    """POST without 'project' in multi-project deployment returns 400 with available list."""
    client = _make_client(monkeypatch, [PROJECT_ACE, PROJECT_T2])
    resp = client.post(endpoint, json=base_body)
    assert resp.status_code == 400
    body = resp.json()
    assert "error" in body
    assert "project" in body["error"].lower()
    assert "available" in body
    assert set(body["available"]) == {"ace", "t2"}


# ─── Multi-project: unknown project → 400 ────────────────────────────────────


@pytest.mark.parametrize("endpoint,base_body", ENDPOINTS)
def test_multi_project_unknown_returns_400(endpoint, base_body, monkeypatch):
    """POST with project='nope' in multi-project deployment returns 400."""
    client = _make_client(monkeypatch, [PROJECT_ACE, PROJECT_T2])
    body = {**base_body, "project": "nope"}
    resp = client.post(endpoint, json=body)
    assert resp.status_code == 400
    rb = resp.json()
    assert "error" in rb
    assert "nope" in rb["error"]
    assert "available" in rb


# ─── Multi-project: valid project → 200 ──────────────────────────────────────


@pytest.mark.parametrize("endpoint,base_body", ENDPOINTS)
def test_multi_project_valid_passes_through(endpoint, base_body, monkeypatch):
    """POST with valid project='t2' passes validation and returns 200."""
    client = _make_client(monkeypatch, [PROJECT_ACE, PROJECT_T2])
    body = {**base_body, "project": "t2"}
    resp = client.post(endpoint, json=body)
    assert resp.status_code == 200


# ─── Single-project: no project field → 200 ──────────────────────────────────


@pytest.mark.parametrize("endpoint,base_body", ENDPOINTS)
def test_single_project_no_field_passes(endpoint, base_body, monkeypatch):
    """POST without 'project' in single-project deployment returns 200."""
    client = _make_client(monkeypatch, [PROJECT_ACE])
    resp = client.post(endpoint, json=base_body)
    assert resp.status_code == 200
