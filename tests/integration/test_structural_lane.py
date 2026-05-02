"""
Structural lane integration tests

Calls gateway._nl_search() directly, mocking StructuralAdapter via monkeypatch,
to verify the STRUCTURAL_ENABLED toggle, RRF fusion, and degradation behavior.
No real Neo4j connection required.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
from gateway import gateway
from gateway.gateway import _assemble_lane_indices

# ─── Fixture ────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_adapters():
    """Reset all adapter singletons in gateway before and after each test."""
    gateway._structural_adapter = None
    gateway._dense_adapter = None
    yield
    gateway._structural_adapter = None
    gateway._dense_adapter = None


def _make_zoekt_results(n: int = 2) -> list[dict]:
    return [
        {
            "title": f"frameworks/base/File{i}.java",
            "score": 0.9 - i * 0.1,
            "content": f"content {i}",
            "metadata": {"repo": "frameworks/base", "path": f"File{i}.java"},
        }
        for i in range(n)
    ]


def _make_structural_hits(n: int = 1) -> list[dict]:
    return [
        {
            "repo": "frameworks/base",
            "path": f"StructuralFile{i}.java",
            "start_line": i * 10,
            "end_line": i * 10 + 50,
            "content": f"structural content {i}",
            "score": 0.75,
            "matched_terms": ["startActivity"],
        }
        for i in range(n)
    ]


# ─── STRUCTURAL_ENABLED=false zero-impact test ──────────────────────────────────


@pytest.mark.asyncio
async def test_structural_disabled_zero_impact(monkeypatch):
    """With STRUCTURAL_ENABLED=false, results are identical to the pure Zoekt path."""
    monkeypatch.setattr(config, "STRUCTURAL_ENABLED", False)
    monkeypatch.setattr(config, "DENSE_ENABLED", False)
    monkeypatch.setattr(config, "NL_ENABLED", True)

    zoekt_results = _make_zoekt_results(2)
    rewrite_output = [{"query": "SystemServer start"}]

    with (
        patch("gateway.gateway.rewrite_query", new=AsyncMock(return_value=rewrite_output)),
        patch("gateway.gateway._get_adapter") as mock_get_adapter,
    ):
        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(return_value=zoekt_results)
        mock_get_adapter.return_value = mock_adapter

        result = await gateway._nl_search(
            query="how does SystemServer start",
            top_k=10,
            score_threshold=0.0,
            repos=None,
        )

    # structural adapter should not be initialized
    assert gateway._structural_adapter is None
    assert isinstance(result, list)
    assert len(result) > 0


# ─── STRUCTURAL_ENABLED=true results enter RRF test ────────────────────────────────


@pytest.mark.asyncio
async def test_structural_enabled_results_in_rrf(monkeypatch):
    """With STRUCTURAL_ENABLED=true, structural hits are fused into the final results via RRF."""
    monkeypatch.setattr(config, "STRUCTURAL_ENABLED", True)
    monkeypatch.setattr(config, "DENSE_ENABLED", False)
    monkeypatch.setattr(config, "NL_ENABLED", True)
    monkeypatch.setattr(config, "DENSE_TOP_K", 10)
    monkeypatch.setattr(config, "STRUCTURAL_LANE_TIMEOUT_MS", 2000)

    zoekt_results = _make_zoekt_results(2)
    structural_hits = _make_structural_hits(1)
    rewrite_output = [{"query": "startActivity intent"}]

    mock_structural_adapter = MagicMock()
    mock_structural_adapter.search_by_structural = AsyncMock(return_value=structural_hits)

    with (
        patch("gateway.gateway.rewrite_query", new=AsyncMock(return_value=rewrite_output)),
        patch("gateway.gateway._get_structural_adapter", return_value=mock_structural_adapter),
        patch("gateway.gateway._get_adapter") as mock_get_adapter,
    ):
        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(return_value=zoekt_results)
        mock_get_adapter.return_value = mock_adapter

        result = await gateway._nl_search(
            query="find startActivity",
            top_k=10,
            score_threshold=0.0,
            repos=None,
        )

    mock_structural_adapter.search_by_structural.assert_awaited_once_with(
        "find startActivity", top_k=10, repos=None, project=None
    )

    titles = [r["title"] for r in result]
    assert isinstance(result, list)
    assert len(result) > 0
    # structural_result_to_dict generates titles containing StructuralFile
    all_titles = " ".join(titles)
    assert "StructuralFile" in all_titles


@pytest.mark.asyncio
async def test_structural_lane_passes_project_to_adapter(monkeypatch):
    """When a project is specified, the structural lane call must forward the project parameter."""
    monkeypatch.setattr(config, "STRUCTURAL_ENABLED", True)
    monkeypatch.setattr(config, "DENSE_ENABLED", False)
    monkeypatch.setattr(config, "NL_ENABLED", True)
    monkeypatch.setattr(config, "DENSE_TOP_K", 10)
    monkeypatch.setattr(config, "STRUCTURAL_LANE_TIMEOUT_MS", 2000)

    zoekt_results = _make_zoekt_results(1)
    structural_hits = _make_structural_hits(1)
    rewrite_output = [{"query": "startActivity intent"}]

    mock_structural_adapter = MagicMock()
    mock_structural_adapter.search_by_structural = AsyncMock(return_value=structural_hits)

    with (
        patch("gateway.gateway.rewrite_query", new=AsyncMock(return_value=rewrite_output)),
        patch("gateway.gateway._get_structural_adapter", return_value=mock_structural_adapter),
        patch("gateway.gateway._get_adapter") as mock_get_adapter,
    ):
        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(return_value=zoekt_results)
        mock_get_adapter.return_value = mock_adapter

        result = await gateway._nl_search(
            query="find startActivity",
            top_k=10,
            score_threshold=0.0,
            repos=None,
            project="beta",
        )

    mock_structural_adapter.search_by_structural.assert_awaited_once_with(
        "find startActivity", top_k=10, repos=None, project="beta"
    )
    assert isinstance(result, list)
    assert len(result) > 0


@pytest.mark.parametrize(
    "dense_on,structural_on",
    [
        (False, False),
        (True, False),
        (False, True),
        (True, True),
    ],
)
def test_all_4_lane_combinations_index(dense_on, structural_on):
    """_assemble_lane_indices returns correct indices for all four lane toggle combinations."""
    zoekt_count = 2
    idx = _assemble_lane_indices(zoekt_count, dense_on, structural_on)

    if not dense_on and not structural_on:
        assert idx == {"dense": None, "structural": None}
    elif dense_on and not structural_on:
        assert idx == {"dense": 2, "structural": None}
    elif not dense_on and structural_on:
        assert idx == {"dense": None, "structural": 2}
    else:
        assert idx == {"dense": 2, "structural": 3}


# ─── Structural timeout degradation test ───────────────────────────────────────


@pytest.mark.asyncio
async def test_structural_timeout_degrades(monkeypatch):
    """When search_by_structural times out, gateway degrades to pure Zoekt results without raising."""
    monkeypatch.setattr(config, "STRUCTURAL_ENABLED", True)
    monkeypatch.setattr(config, "DENSE_ENABLED", False)
    monkeypatch.setattr(config, "NL_ENABLED", True)
    monkeypatch.setattr(config, "DENSE_TOP_K", 10)
    # Set a very short timeout
    monkeypatch.setattr(config, "STRUCTURAL_LANE_TIMEOUT_MS", 1)

    zoekt_results = _make_zoekt_results(2)
    rewrite_output = [{"query": "startActivity"}]

    async def _slow_search(*args, **kwargs):
        await asyncio.sleep(10)  # far exceeds timeout
        return []

    mock_structural_adapter = MagicMock()
    mock_structural_adapter.search_by_structural = _slow_search

    with (
        patch("gateway.gateway.rewrite_query", new=AsyncMock(return_value=rewrite_output)),
        patch("gateway.gateway._get_structural_adapter", return_value=mock_structural_adapter),
        patch("gateway.gateway._get_adapter") as mock_get_adapter,
    ):
        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(return_value=zoekt_results)
        mock_get_adapter.return_value = mock_adapter

        result = await gateway._nl_search(
            query="find startActivity",
            top_k=10,
            score_threshold=0.0,
            repos=None,
        )

    # After timeout gateway does not raise; returns Zoekt results
    assert isinstance(result, list)
    assert len(result) > 0
    # After timeout all results come from Zoekt (no structural source)
    for r in result:
        assert r.get("metadata", {}).get("source") != "structural"
