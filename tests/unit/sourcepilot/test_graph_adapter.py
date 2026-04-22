"""
GraphAdapter 单元测试

所有 Neo4j 驱动均通过 AsyncMock 模拟，不连接真实数据库。
"""
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─── 辅助工具 ─────────────────────────────────────────────────────────────────

def _make_driver_mock(seed_records=None, neighbor_records=None, index_names=None):
    """构造 Neo4j 异步驱动 mock，支持自定义返回数据。"""

    async def _iter_records(records):
        for r in records:
            yield r

    def _make_result(records):
        result = MagicMock()
        result.__aiter__ = lambda self: _iter_records(records)
        result.single = AsyncMock(return_value=records[0] if records else None)
        return result

    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    # run() 返回值根据调用次序区分
    call_count = {"n": 0}
    results_seq = []
    if seed_records is not None:
        # 两次 fulltext index 查询
        results_seq.append(_make_result(seed_records))
        results_seq.append(_make_result([]))
    if neighbor_records is not None:
        results_seq.append(_make_result(neighbor_records))
    if index_names is not None:
        results_seq.append(_make_result([{"names": index_names}]))

    async def _run(*args, **kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        if idx < len(results_seq):
            return results_seq[idx]
        return _make_result([])

    session.run = _run

    driver = MagicMock()
    driver.session = MagicMock(return_value=session)
    return driver


# ─── Fixture：重置适配器单例 ──────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_graph_adapter():
    """每个测试前后重置 gateway 中的 _graph_adapter 单例。"""
    import gateway.gateway as gw
    gw._graph_adapter = None
    yield
    gw._graph_adapter = None


# ─── 测试套件 ─────────────────────────────────────────────────────────────────

class TestGraphAdapterInit:
    def test_lazy_neo4j_import(self):
        """实例化 GraphAdapter 时不应导入 neo4j 包（懒加载验证）。"""
        # 清理可能已存在的 neo4j 模块
        saved = sys.modules.pop("neo4j", None)
        try:
            from adapters.graph import GraphAdapter
            _ = GraphAdapter(
                neo4j_uri="bolt://fake:7687",
                neo4j_user="neo4j",
                neo4j_password="test",
            )
            assert "neo4j" not in sys.modules, "neo4j 不应在初始化时被导入"
        finally:
            if saved is not None:
                sys.modules["neo4j"] = saved


@pytest.mark.asyncio
class TestSearchByGraph:
    async def test_search_by_graph_returns_formatted_hits(self):
        """search_by_graph 返回格式正确的 hit 字典（包含 repo/path/start_line/end_line/content/score）。"""
        from adapters.graph import GraphAdapter

        seed_records = [
            {"nid": 1, "kind": "Symbol", "props": {"name": "startActivity"}, "score": 1.0},
        ]
        neighbor_records = [
            {
                "file_props": {
                    "repo": "frameworks/base",
                    "path": "core/java/android/app/Activity.java",
                    "start_line": 100,
                    "end_line": 200,
                    "content": "public void startActivity(Intent intent) {}",
                },
                "path_length": 1,
                "anchors": [1],
            }
        ]

        driver_mock = _make_driver_mock(seed_records, neighbor_records)

        adapter = GraphAdapter(
            neo4j_uri="bolt://fake:7687",
            neo4j_user="neo4j",
            neo4j_password="test",
        )
        adapter._driver = driver_mock  # 跳过懒加载

        results = await adapter.search_by_graph("startActivity", top_k=5)

        assert len(results) == 1
        hit = results[0]
        assert hit["repo"] == "frameworks/base"
        assert hit["path"] == "core/java/android/app/Activity.java"
        assert hit["start_line"] == 100
        assert hit["end_line"] == 200
        assert "startActivity" in hit["content"]
        assert isinstance(hit["score"], float)

    async def test_empty_terms_returns_empty(self):
        """查询字符串无法提取实体时，直接返回空列表，不调用驱动。"""
        from adapters.graph import GraphAdapter

        adapter = GraphAdapter()
        # "_" 之类不含有效词元
        results = await adapter.search_by_graph("a b", top_k=5)
        assert results == []


class TestComputeGraphScore:
    def test_score_blend_alpha_0_6(self):
        """alpha=0.6, path=1, match=2, max=4 → 0.6*(1/1) + 0.4*(2/4) = 0.6+0.2 = 0.8"""
        from adapters.graph_traversal import compute_graph_score

        score = compute_graph_score(path_length=1, match_count=2, max_match_count=4, alpha=0.6)
        assert abs(score - 0.8) < 1e-9

    def test_score_clamped_to_0_1(self):
        from adapters.graph_traversal import compute_graph_score

        score = compute_graph_score(path_length=0, match_count=100, max_match_count=1, alpha=1.0)
        assert 0.0 <= score <= 1.0


class TestExtractQueryEntities:
    def test_camel_and_snake(self):
        """'find startActivity in service_manager' 提取 startActivity 和 service_manager（大小写去重）。"""
        from adapters.graph_traversal import extract_query_entities

        terms = extract_query_entities("find startActivity in service_manager")
        lower_terms = [t.lower() for t in terms]
        assert "startactivity" in lower_terms
        assert "service_manager" in lower_terms

    def test_dedup_case_insensitive(self):
        """同一词元不同大小写只保留一次。"""
        from adapters.graph_traversal import extract_query_entities

        terms = extract_query_entities("ActivityManager activitymanager")
        lower_terms = [t.lower() for t in terms]
        assert lower_terms.count("activitymanager") == 1


@pytest.mark.asyncio
class TestHealthCheck:
    async def test_health_check_pass(self):
        """驱动返回两个全文索引时，health_check() 返回 True。"""
        from adapters.graph import GraphAdapter

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        record = {"names": ["symbol_name_idx", "doc_entity_idx"]}
        result_mock = MagicMock()
        result_mock.single = AsyncMock(return_value=record)
        session.run = AsyncMock(return_value=result_mock)

        driver_mock = MagicMock()
        driver_mock.session = MagicMock(return_value=session)

        adapter = GraphAdapter()
        adapter._driver = driver_mock

        ok = await adapter.health_check()
        assert ok is True

    async def test_health_check_fail(self):
        """驱动抛异常时，health_check() 返回 False 而不传播异常。"""
        from adapters.graph import GraphAdapter

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.run = AsyncMock(side_effect=Exception("bolt connect error"))

        driver_mock = MagicMock()
        driver_mock.session = MagicMock(return_value=session)

        adapter = GraphAdapter()
        adapter._driver = driver_mock

        ok = await adapter.health_check()
        assert ok is False


@pytest.mark.asyncio
class TestGetContent:
    async def test_get_content_raises_not_implemented(self):
        """get_content() 应抛出 NotImplementedError。"""
        from adapters.graph import GraphAdapter

        adapter = GraphAdapter()
        with pytest.raises(NotImplementedError):
            await adapter.get_content("graph:some/file.java:1")
