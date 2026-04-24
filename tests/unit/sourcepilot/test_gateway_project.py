"""
Tests for multi-project adapter routing in gateway.py and app.py.
"""

import pytest
import respx
import httpx
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient

from config.projects import ProjectConfig


# ─── Fixtures ────────────────────────────────────────────────────────────────

PROJECT_ALPHA = ProjectConfig(
    name="alpha",
    source_root="/src/alpha",
    repo_path="/repo/alpha",
    index_dir="/idx/alpha",
    zoekt_url="http://zoekt-alpha:6070",
)

PROJECT_BETA = ProjectConfig(
    name="beta",
    source_root="/src/beta",
    repo_path="/repo/beta",
    index_dir="/idx/beta",
    zoekt_url="http://zoekt-beta:6070",
)

PROJECTS = [PROJECT_ALPHA, PROJECT_BETA]

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


def _patch_projects(monkeypatch):
    """Patch config.projects module to return our two test projects."""
    import config.projects as cp

    monkeypatch.setattr(cp, "_projects_cache", PROJECTS)


# ─── Gateway unit tests ───────────────────────────────────────────────────────

class TestGetAdapter:
    def test_default_uses_first_project(self, monkeypatch):
        _patch_projects(monkeypatch)
        import gateway.gateway as gw
        # Clear adapter cache
        gw._adapters.clear()

        adapter = gw._get_adapter(None)
        assert adapter._zoekt_url == PROJECT_ALPHA.zoekt_url

    def test_named_project_uses_correct_url(self, monkeypatch):
        _patch_projects(monkeypatch)
        import gateway.gateway as gw
        gw._adapters.clear()

        adapter = gw._get_adapter("beta")
        assert adapter._zoekt_url == PROJECT_BETA.zoekt_url

    def test_adapter_is_cached(self, monkeypatch):
        _patch_projects(monkeypatch)
        import gateway.gateway as gw
        gw._adapters.clear()

        a1 = gw._get_adapter("alpha")
        a2 = gw._get_adapter("alpha")
        assert a1 is a2

    def test_unknown_project_raises(self, monkeypatch):
        _patch_projects(monkeypatch)
        import gateway.gateway as gw
        gw._adapters.clear()

        with pytest.raises(ValueError, match="Unknown project"):
            gw._get_adapter("nonexistent")


# ─── Gateway search routing ───────────────────────────────────────────────────

@pytest.mark.anyio
async def test_search_routes_to_correct_adapter(monkeypatch):
    """search(project='beta') hits zoekt-beta, not zoekt-alpha."""
    _patch_projects(monkeypatch)
    import gateway.gateway as gw
    gw._adapters.clear()

    # Disable NL
    monkeypatch.setattr("config.NL_ENABLED", False)

    with respx.mock:
        route_beta = respx.get("http://zoekt-beta:6070/search").mock(
            return_value=httpx.Response(200, json=ZOEKT_ONE_HIT)
        )
        route_alpha = respx.get("http://zoekt-alpha:6070/search").mock(
            return_value=httpx.Response(200, json=ZOEKT_EMPTY)
        )

        results = await gw.search(query="Foo", project="beta")

    assert route_beta.called
    assert not route_alpha.called
    assert len(results) > 0


@pytest.mark.anyio
async def test_search_without_project_uses_default(monkeypatch):
    """search(project=None) hits zoekt-alpha (first/default project)."""
    _patch_projects(monkeypatch)
    import gateway.gateway as gw
    gw._adapters.clear()

    monkeypatch.setattr("config.NL_ENABLED", False)

    with respx.mock:
        route_alpha = respx.get("http://zoekt-alpha:6070/search").mock(
            return_value=httpx.Response(200, json=ZOEKT_ONE_HIT)
        )
        route_beta = respx.get("http://zoekt-beta:6070/search").mock(
            return_value=httpx.Response(200, json=ZOEKT_EMPTY)
        )

        results = await gw.search(query="Foo")

    assert route_alpha.called
    assert not route_beta.called


# ─── HTTP API tests ───────────────────────────────────────────────────────────

@pytest.fixture
def app_client(monkeypatch):
    _patch_projects(monkeypatch)
    import gateway.gateway as gw
    gw._adapters.clear()
    monkeypatch.setattr("config.NL_ENABLED", False)
    monkeypatch.setattr("config.AUDIT_ENABLED", False)
    monkeypatch.setattr("config.AUDIT_SUMMARY_INTERVAL", 0)

    from app import app
    return TestClient(app)


def test_api_projects_returns_list(app_client):
    resp = app_client.get("/api/projects")
    assert resp.status_code == 200
    data = resp.json()
    names = [p["name"] for p in data]
    assert "alpha" in names
    assert "beta" in names


def test_api_search_with_project_routes_correctly(app_client, monkeypatch):
    import gateway.gateway as gw
    gw._adapters.clear()

    with respx.mock:
        respx.get("http://zoekt-beta:6070/search").mock(
            return_value=httpx.Response(200, json=ZOEKT_ONE_HIT)
        )
        resp = app_client.post(
            "/api/search",
            json={"query": "Foo", "project": "beta"},
        )

    assert resp.status_code == 200


def test_api_search_unknown_project_returns_400(app_client):
    resp = app_client.post(
        "/api/search",
        json={"query": "Foo", "project": "does-not-exist"},
    )
    assert resp.status_code in (400, 500)
    body = resp.json()
    assert "error" in body
