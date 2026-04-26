"""
StructuralAdapter 单元测试

所有 Neo4j 驱动均通过 AsyncMock 模拟，不连接真实数据库。
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
def reset_structural_adapter():
    """每个测试前后重置 gateway 中的 _structural_adapter 单例。"""
    import gateway.gateway as gw

    gw._structural_adapter = None
    yield
    gw._structural_adapter = None


# ─── 测试套件 ─────────────────────────────────────────────────────────────────


class TestStructuralAdapterInit:
    def test_lazy_neo4j_import(self):
        """实例化 StructuralAdapter 时不应导入 neo4j 包（懒加载验证）。"""
        # 清理可能已存在的 neo4j 模块
        saved = sys.modules.pop("neo4j", None)
        try:
            from adapters.structural import StructuralAdapter

            _ = StructuralAdapter(
                neo4j_uri="bolt://fake:7687",
                neo4j_user="neo4j",
                neo4j_password="test",
            )
            assert "neo4j" not in sys.modules, "neo4j 不应在初始化时被导入"
        finally:
            if saved is not None:
                sys.modules["neo4j"] = saved


@pytest.mark.asyncio
class TestSearchByStructural:
    async def test_search_by_structural_returns_formatted_hits(self):
        """search_by_structural 返回格式正确的 hit 字典（含核心字段）。"""
        from adapters.structural import StructuralAdapter

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

        adapter = StructuralAdapter(
            neo4j_uri="bolt://fake:7687",
            neo4j_user="neo4j",
            neo4j_password="test",
        )
        adapter._driver = driver_mock  # 跳过懒加载

        results = await adapter.search_by_structural("startActivity", top_k=5)

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
        from adapters.structural import StructuralAdapter

        adapter = StructuralAdapter()
        # "_" 之类不含有效词元
        results = await adapter.search_by_structural("a b", top_k=5)
        assert results == []


@pytest.mark.asyncio
class TestProjectScoping:
    async def test_search_by_structural_passes_project_to_traversal(self):
        """search_by_structural 应将 project 透传给 traversal 查询，避免跨项目污染。"""
        from adapters.structural import StructuralAdapter

        seed_nodes = [{"nid": 1, "kind": "Symbol", "props": {}, "score": 1.0}]
        neighbor_nodes = [
            {
                "file_props": {
                    "repo": "frameworks/base",
                    "path": "core/Foo.java",
                    "start_line": 1,
                    "end_line": 2,
                    "content": "class Foo {}",
                },
                "path_length": 1,
                "anchor_nids": [1],
            }
        ]

        mock_fulltext = AsyncMock(return_value=seed_nodes)
        mock_expand = AsyncMock(return_value=neighbor_nodes)

        adapter = StructuralAdapter()
        adapter._driver = MagicMock()

        with (
            patch("adapters.structural.fulltext_search_nodes", new=mock_fulltext),
            patch("adapters.structural.expand_neighbors", new=mock_expand),
        ):
            results = await adapter.search_by_structural("find startActivity", top_k=5, project="beta")

        assert len(results) == 1
        assert mock_fulltext.await_args.kwargs["project"] == "beta"
        assert mock_fulltext.await_args.kwargs["limit"] == 20
        assert mock_expand.await_args.kwargs["project"] == "beta"
        assert mock_expand.await_args.kwargs["max_hops"] == 2

    async def test_fulltext_search_nodes_scopes_by_project_in_query(self):
        """fulltext_search_nodes 在 Cypher 和参数里都应带 project 过滤。"""
        from adapters.structural_traversal import fulltext_search_nodes

        empty_result = MagicMock()

        async def _iter_empty():
            for r in []:
                yield r

        empty_result.__aiter__ = lambda self: _iter_empty()

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.run = AsyncMock(return_value=empty_result)

        driver = MagicMock()
        driver.session = MagicMock(return_value=session)

        await fulltext_search_nodes(driver, ["startactivity"], project="beta")

        assert session.run.await_count == 2
        for call in session.run.await_args_list:
            cypher = call.args[0]
            params = call.args[1]
            assert "node.project = $project" in cypher
            assert params["project"] == "beta"

    async def test_expand_neighbors_scopes_by_project_in_query(self):
        """expand_neighbors 在 Cypher 和参数里都应带 project 过滤。"""
        from adapters.structural_traversal import expand_neighbors

        empty_result = MagicMock()

        async def _iter_empty():
            for r in []:
                yield r

        empty_result.__aiter__ = lambda self: _iter_empty()

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.run = AsyncMock(return_value=empty_result)

        driver = MagicMock()
        driver.session = MagicMock(return_value=session)

        await expand_neighbors(driver, [1], project="beta")

        cypher = session.run.await_args.args[0]
        params = session.run.await_args.args[1]
        assert "file.project = $project" in cypher
        assert params["project"] == "beta"


class TestComputeStructuralScore:
    def test_score_blend_alpha_0_6(self):
        """alpha=0.6, path=1, match=2, max=4 → 0.6*(1/1) + 0.4*(2/4) = 0.6+0.2 = 0.8"""
        from adapters.structural_traversal import compute_structural_score

        score = compute_structural_score(path_length=1, match_count=2, max_match_count=4, alpha=0.6)
        assert abs(score - 0.8) < 1e-9

    def test_score_clamped_to_0_1(self):
        from adapters.structural_traversal import compute_structural_score

        score = compute_structural_score(path_length=0, match_count=100, max_match_count=1, alpha=1.0)
        assert 0.0 <= score <= 1.0


class TestExtractQueryEntities:
    def test_camel_and_snake(self):
        """提取 startActivity 与 service_manager，且大小写去重。"""
        from adapters.structural_traversal import extract_query_entities

        terms = extract_query_entities("find startActivity in service_manager")
        lower_terms = [t.lower() for t in terms]
        assert "startactivity" in lower_terms
        assert "service_manager" in lower_terms

    def test_dedup_case_insensitive(self):
        """同一词元不同大小写只保留一次。"""
        from adapters.structural_traversal import extract_query_entities

        terms = extract_query_entities("ActivityManager activitymanager")
        lower_terms = [t.lower() for t in terms]
        assert lower_terms.count("activitymanager") == 1


@pytest.mark.asyncio
class TestHealthCheck:
    async def test_health_check_pass(self):
        """驱动返回两个全文索引时，health_check() 返回 True。"""
        from adapters.structural import StructuralAdapter

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        record = {"names": ["symbol_name_idx", "doc_entity_idx"]}
        result_mock = MagicMock()
        result_mock.single = AsyncMock(return_value=record)
        session.run = AsyncMock(return_value=result_mock)

        driver_mock = MagicMock()
        driver_mock.session = MagicMock(return_value=session)

        adapter = StructuralAdapter()
        adapter._driver = driver_mock

        ok = await adapter.health_check()
        assert ok is True

    async def test_health_check_fail(self):
        """驱动抛异常时，health_check() 返回 False 而不传播异常。"""
        from adapters.structural import StructuralAdapter

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.run = AsyncMock(side_effect=Exception("bolt connect error"))

        driver_mock = MagicMock()
        driver_mock.session = MagicMock(return_value=session)

        adapter = StructuralAdapter()
        adapter._driver = driver_mock

        ok = await adapter.health_check()
        assert ok is False


@pytest.mark.asyncio
class TestGetContent:
    async def test_get_content_raises_not_implemented(self):
        """get_content() 应抛出 NotImplementedError。"""
        from adapters.structural import StructuralAdapter

        adapter = StructuralAdapter()
        with pytest.raises(NotImplementedError):
            await adapter.get_content("structural:some/file.java:1")
