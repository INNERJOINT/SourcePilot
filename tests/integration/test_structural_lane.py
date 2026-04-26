"""
Structural lane 集成测试

直接调用 gateway._nl_search()，通过 monkeypatch 模拟 StructuralAdapter，
验证 STRUCTURAL_ENABLED 开关、RRF 融合、降级行为。
不连接真实 Neo4j。
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
    """每个测试前后重置 gateway 中所有适配器单例。"""
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


# ─── STRUCTURAL_ENABLED=false 零影响测试 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_structural_disabled_zero_impact(monkeypatch):
    """STRUCTURAL_ENABLED=false 时，结果与纯 Zoekt 路径完全一致。"""
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

    # structural adapter 不应被初始化
    assert gateway._structural_adapter is None
    assert isinstance(result, list)
    assert len(result) > 0


# ─── STRUCTURAL_ENABLED=true 结果进入 RRF 测试 ────────────────────────────────────


@pytest.mark.asyncio
async def test_structural_enabled_results_in_rrf(monkeypatch):
    """STRUCTURAL_ENABLED=true 时，structural hits 通过 RRF 融合进入最终结果。"""
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
    # structural_result_to_dict 生成的 title 含 StructuralFile
    all_titles = " ".join(titles)
    assert "StructuralFile" in all_titles


@pytest.mark.asyncio
async def test_structural_lane_passes_project_to_adapter(monkeypatch):
    """指定 project 时，structural lane 调用应透传 project 参数。"""
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
    """_assemble_lane_indices 在四种 lane 开关组合下均返回正确索引。"""
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


# ─── Structural 超时降级测试 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_structural_timeout_degrades(monkeypatch):
    """search_by_structural 超时时，gateway 降级为纯 Zoekt 结果，不抛异常。"""
    monkeypatch.setattr(config, "STRUCTURAL_ENABLED", True)
    monkeypatch.setattr(config, "DENSE_ENABLED", False)
    monkeypatch.setattr(config, "NL_ENABLED", True)
    monkeypatch.setattr(config, "DENSE_TOP_K", 10)
    # 设置极短超时
    monkeypatch.setattr(config, "STRUCTURAL_LANE_TIMEOUT_MS", 1)

    zoekt_results = _make_zoekt_results(2)
    rewrite_output = [{"query": "startActivity"}]

    async def _slow_search(*args, **kwargs):
        await asyncio.sleep(10)  # 远超 timeout
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

    # 超时后 gateway 不抛异常，返回 Zoekt 结果
    assert isinstance(result, list)
    assert len(result) > 0
    # 超时后所有结果来自 Zoekt（无 structural source）
    for r in result:
        assert r.get("metadata", {}).get("source") != "structural"
