"""
Integration tests for project routing in SourcePilot HTTP API.

Tests that search requests are routed to the correct Zoekt backend
based on the 'project' field, and that missing project returns 400.
"""
import httpx
import pytest
import respx
from starlette.testclient import TestClient

import config.projects as cp
from config.projects import ProjectConfig

PROJECT_ACE = ProjectConfig(
    name="ace",
    source_root="/x",
    repo_path="/repo/ace",
    index_dir="/idx/ace",
    zoekt_url="http://localhost:6070",
    dense_collection_name="aosp_code_ace",
)
PROJECT_T2 = ProjectConfig(
    name="t2",
    source_root="/y",
    repo_path="/repo/t2",
    index_dir="/idx/t2",
    zoekt_url="http://localhost:6071",
    dense_collection_name="aosp_code_t2",
)

ZOEKT_EMPTY = {"Result": {"Files": None}}

ZOEKT_ONE_HIT = {
    "Result": {
        "Files": [
            {
                "FileName": "core/Foo.java",
                "Repository": "frameworks/base",
                "Branches": ["main"],
                "Language": "Java",
                "LineMatches": [
                    {
                        "Line": "class Foo {}",
                        "LineNumber": 10,
                        "LineFragments": [{"LineOffset": 0, "MatchLength": 3}],
                    }
                ],
                "Score": 20.0,
            }
        ]
    }
}


@pytest.fixture
def multi_project_client(monkeypatch):
    """Test client with two projects patched into config cache."""
    monkeypatch.setattr(cp, "_projects_cache", [PROJECT_ACE, PROJECT_T2])
    monkeypatch.setattr("config.AUDIT_ENABLED", False)
    monkeypatch.setattr("config.AUDIT_SUMMARY_INTERVAL", 0)
    monkeypatch.setattr("config.NL_ENABLED", False)

    import gateway.gateway as gw

    gw._adapters.clear()

    from app import app

    return TestClient(app)


def test_search_project_ace_calls_zoekt_6070(multi_project_client):
    """POST /api/search project=ace hits zoekt on :6070, not :6071."""
    with respx.mock:
        route_ace = respx.get("http://localhost:6070/search").mock(
            return_value=httpx.Response(200, json=ZOEKT_ONE_HIT)
        )
        route_t2 = respx.get("http://localhost:6071/search").mock(
            return_value=httpx.Response(200, json=ZOEKT_EMPTY)
        )
        resp = multi_project_client.post(
            "/api/search", json={"query": "Foo", "project": "ace"}
        )

    assert resp.status_code == 200
    assert route_ace.called
    assert not route_t2.called


def test_search_project_t2_calls_zoekt_6071(multi_project_client):
    """POST /api/search project=t2 hits zoekt on :6071, not :6070."""
    with respx.mock:
        route_ace = respx.get("http://localhost:6070/search").mock(
            return_value=httpx.Response(200, json=ZOEKT_EMPTY)
        )
        route_t2 = respx.get("http://localhost:6071/search").mock(
            return_value=httpx.Response(200, json=ZOEKT_ONE_HIT)
        )
        resp = multi_project_client.post(
            "/api/search", json={"query": "Foo", "project": "t2"}
        )

    assert resp.status_code == 200
    assert route_t2.called
    assert not route_ace.called


def test_search_without_project_returns_400(multi_project_client):
    """POST /api/search without 'project' in multi-project deployment returns 400."""
    resp = multi_project_client.post("/api/search", json={"query": "Foo"})
    assert resp.status_code == 400
    body = resp.json()
    assert "error" in body
    assert "available" in body
    assert set(body["available"]) == {"ace", "t2"}
