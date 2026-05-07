"""Tests for MultiZoektAdapter and multi-Zoekt project configuration."""

from unittest.mock import AsyncMock

import pytest

from adapters.multi_zoekt import MultiZoektAdapter
from adapters.protocol import ZoektProtocol
from adapters.zoekt import ZoektAdapter


@pytest.fixture
def mock_adapters():
    a1 = AsyncMock(spec=ZoektAdapter)
    a2 = AsyncMock(spec=ZoektAdapter)
    return {"sys": a1, "vnd": a2}


@pytest.fixture
def multi_adapter(mock_adapters):
    return MultiZoektAdapter(mock_adapters, dedup_by_filepath=False)


@pytest.fixture
def multi_adapter_dedup(mock_adapters):
    return MultiZoektAdapter(mock_adapters, dedup_by_filepath=True)


async def test_multi_adapter_merges_results(multi_adapter, mock_adapters):
    mock_adapters["sys"].search_zoekt.return_value = [
        {"title": "a", "score": 0.9, "metadata": {"repo": "r1", "path": "f1.java"}}
    ]
    mock_adapters["vnd"].search_zoekt.return_value = [
        {"title": "b", "score": 0.8, "metadata": {"repo": "r2", "path": "f2.java"}}
    ]
    results = await multi_adapter.search_zoekt(query="test", top_k=10)
    assert len(results) == 2


async def test_multi_adapter_fail_fast(multi_adapter, mock_adapters):
    mock_adapters["sys"].search_zoekt.return_value = [{"title": "a", "score": 0.9, "metadata": {}}]
    mock_adapters["vnd"].search_zoekt.side_effect = Exception("connection refused")
    with pytest.raises(Exception, match="connection refused"):
        await multi_adapter.search_zoekt(query="test", top_k=10)


async def test_multi_adapter_dedup_enabled(multi_adapter_dedup, mock_adapters):
    mock_adapters["sys"].search_zoekt.return_value = [
        {"title": "a", "score": 0.9, "metadata": {"repo": "r1", "path": "f1.java"}}
    ]
    mock_adapters["vnd"].search_zoekt.return_value = [
        {"title": "a-dup", "score": 0.7, "metadata": {"repo": "r1", "path": "f1.java"}}
    ]
    results = await multi_adapter_dedup.search_zoekt(query="test", top_k=10)
    assert len(results) == 1
    assert results[0]["score"] == 0.9


async def test_multi_adapter_dedup_disabled(multi_adapter, mock_adapters):
    mock_adapters["sys"].search_zoekt.return_value = [
        {"title": "a", "score": 0.9, "metadata": {"repo": "r1", "path": "f1.java"}}
    ]
    mock_adapters["vnd"].search_zoekt.return_value = [
        {"title": "a-dup", "score": 0.7, "metadata": {"repo": "r1", "path": "f1.java"}}
    ]
    results = await multi_adapter.search_zoekt(query="test", top_k=10)
    assert len(results) == 2


async def test_multi_adapter_list_repos_dedup(multi_adapter, mock_adapters):
    mock_adapters["sys"].list_repos.return_value = [{"name": "frameworks/base", "url": ""}]
    mock_adapters["vnd"].list_repos.return_value = [
        {"name": "frameworks/base", "url": ""},
        {"name": "vendor/lib", "url": ""},
    ]
    results = await multi_adapter.list_repos(query="", top_k=50)
    assert len(results) == 2
    names = [r["name"] for r in results]
    assert "frameworks/base" in names
    assert "vendor/lib" in names


async def test_multi_adapter_fetch_file_content_fallthrough(multi_adapter, mock_adapters):
    mock_adapters["sys"].fetch_file_content.side_effect = FileNotFoundError("not here")
    mock_adapters["vnd"].fetch_file_content.return_value = {"content": "hello", "total_lines": 1}
    result = await multi_adapter.fetch_file_content(repo="r1", filepath="f.java")
    assert result["content"] == "hello"


async def test_multi_adapter_health_per_container(multi_adapter, mock_adapters):
    mock_adapters["sys"].health_check.return_value = True
    mock_adapters["vnd"].health_check.return_value = False
    result = await multi_adapter.health_check()
    assert result == {"sys": True, "vnd": False}


def test_protocol_compliance(mock_adapters):
    adapter = MultiZoektAdapter(mock_adapters)
    assert isinstance(adapter, ZoektProtocol)


def test_single_url_project_uses_zoekt_adapter():
    from config.projects import ProjectConfig

    cfg = ProjectConfig(
        name="test",
        source_root="/tmp",
        repo_path="/tmp/.repo",
        index_dir="/tmp/.zoekt",
        zoekt_url="http://localhost:6070",
    )
    assert not cfg.is_multi_zoekt
    assert cfg.all_zoekt_urls == {"default": "http://localhost:6070"}


def test_multi_url_project():
    from config.projects import ProjectConfig

    cfg = ProjectConfig(
        name="ace",
        source_root="/tmp",
        repo_path="/tmp/.repo",
        index_dir="",
        zoekt_url="",
        zoekt_urls={"sys": "http://sys:6070", "vnd": "http://vnd:6070"},
    )
    assert cfg.is_multi_zoekt
    assert cfg.all_zoekt_urls == {"sys": "http://sys:6070", "vnd": "http://vnd:6070"}
