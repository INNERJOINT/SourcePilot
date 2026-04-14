"""
adapters/base.py 单元测试

验证数据类（ContentType、QueryOptions、SearchItem 等）和 SearchAdapter ABC。
"""

import pytest
from adapters.base import (
    ContentType,
    QueryOptions,
    Highlight,
    SearchItem,
    BackendQuery,
    BackendResponse,
    SearchAdapter,
)


# ─── ContentType 枚举 ─────────────────────────────────────────────────────────

class TestContentType:
    """ContentType 枚举值验证。"""

    def test_code_value(self):
        assert ContentType.CODE.value == "code"

    def test_document_value(self):
        assert ContentType.DOCUMENT.value == "document"

    def test_message_value(self):
        assert ContentType.MESSAGE.value == "message"

    def test_issue_value(self):
        assert ContentType.ISSUE.value == "issue"

    def test_config_value(self):
        assert ContentType.CONFIG.value == "config"

    def test_all_five_values(self):
        # 枚举共有 5 个成员
        assert len(ContentType) == 5


# ─── QueryOptions 默认值 ───────────────────────────────────────────────────────

class TestQueryOptions:
    """QueryOptions 数据类默认值和自定义值验证。"""

    def test_default_max_results(self):
        opts = QueryOptions()
        assert opts.max_results == 10

    def test_default_timeout_ms(self):
        opts = QueryOptions()
        assert opts.timeout_ms == 30000

    def test_default_cursor_none(self):
        opts = QueryOptions()
        assert opts.cursor is None

    def test_custom_max_results(self):
        opts = QueryOptions(max_results=50)
        assert opts.max_results == 50

    def test_custom_timeout_ms(self):
        opts = QueryOptions(timeout_ms=5000)
        assert opts.timeout_ms == 5000

    def test_custom_cursor(self):
        opts = QueryOptions(cursor="next-page-token")
        assert opts.cursor == "next-page-token"

    def test_all_custom(self):
        opts = QueryOptions(max_results=20, timeout_ms=1000, cursor="abc")
        assert opts.max_results == 20
        assert opts.timeout_ms == 1000
        assert opts.cursor == "abc"


# ─── Highlight 数据类 ──────────────────────────────────────────────────────────

class TestHighlight:
    """Highlight 数据类创建验证。"""

    def test_create_with_text_only(self):
        h = Highlight(text="ActivityManager")
        assert h.text == "ActivityManager"
        assert h.ranges == []

    def test_create_with_ranges(self):
        h = Highlight(text="foo bar", ranges=[(0, 3), (4, 7)])
        assert h.ranges == [(0, 3), (4, 7)]

    def test_ranges_default_is_list(self):
        h1 = Highlight(text="a")
        h2 = Highlight(text="b")
        # 默认 factory 确保不同实例不共享列表
        h1.ranges.append((0, 1))
        assert h2.ranges == []


# ─── SearchItem 数据类 ─────────────────────────────────────────────────────────

class TestSearchItem:
    """SearchItem 数据类创建和可选字段默认值验证。"""

    def _make_item(self, **kwargs):
        defaults = dict(
            id="item-1",
            source="zoekt",
            content_type=ContentType.CODE,
            title="ActivityManager.java",
            summary="Fragment of ActivityManager",
            url="http://zoekt/print?repo=a&file=b",
            score=0.85,
        )
        defaults.update(kwargs)
        return SearchItem(**defaults)

    def test_required_fields(self):
        item = self._make_item()
        assert item.id == "item-1"
        assert item.source == "zoekt"
        assert item.content_type == ContentType.CODE
        assert item.title == "ActivityManager.java"
        assert item.score == 0.85

    def test_optional_timestamp_default_none(self):
        item = self._make_item()
        assert item.timestamp is None

    def test_optional_matched_terms_default_empty(self):
        item = self._make_item()
        assert item.matched_terms == []

    def test_optional_highlights_default_empty(self):
        item = self._make_item()
        assert item.highlights == []

    def test_optional_metadata_default_empty(self):
        item = self._make_item()
        assert item.metadata == {}

    def test_custom_optional_fields(self):
        item = self._make_item(
            timestamp="2024-01-01T00:00:00Z",
            matched_terms=["Activity"],
            highlights=[Highlight(text="Activity")],
            metadata={"repo": "frameworks/base"},
        )
        assert item.timestamp == "2024-01-01T00:00:00Z"
        assert item.matched_terms == ["Activity"]
        assert len(item.highlights) == 1
        assert item.metadata["repo"] == "frameworks/base"


# ─── BackendQuery 数据类 ──────────────────────────────────────────────────────

class TestBackendQuery:
    """BackendQuery 数据类创建验证。"""

    def test_create_minimal(self):
        q = BackendQuery(raw_query="ActivityManager", parsed={"term": "ActivityManager"})
        assert q.raw_query == "ActivityManager"
        assert q.parsed == {"term": "ActivityManager"}

    def test_backend_specific_default_empty(self):
        q = BackendQuery(raw_query="foo", parsed={})
        assert q.backend_specific == {}

    def test_options_default(self):
        q = BackendQuery(raw_query="foo", parsed={})
        assert isinstance(q.options, QueryOptions)
        assert q.options.max_results == 10

    def test_custom_backend_specific(self):
        q = BackendQuery(
            raw_query="foo",
            parsed={},
            backend_specific={"zoekt_param": True},
        )
        assert q.backend_specific["zoekt_param"] is True

    def test_custom_options(self):
        opts = QueryOptions(max_results=25)
        q = BackendQuery(raw_query="foo", parsed={}, options=opts)
        assert q.options.max_results == 25


# ─── BackendResponse 数据类 ───────────────────────────────────────────────────

class TestBackendResponse:
    """BackendResponse 数据类创建验证。"""

    def _make_response(self, **kwargs):
        defaults = dict(
            backend="zoekt",
            status="ok",
            latency_ms=42.5,
            total_hits=10,
        )
        defaults.update(kwargs)
        return BackendResponse(**defaults)

    def test_required_fields(self):
        r = self._make_response()
        assert r.backend == "zoekt"
        assert r.status == "ok"
        assert r.latency_ms == 42.5
        assert r.total_hits == 10

    def test_items_default_empty_list(self):
        r = self._make_response()
        assert r.items == []

    def test_error_detail_default_none(self):
        r = self._make_response()
        assert r.error_detail is None

    def test_cursor_default_none(self):
        r = self._make_response()
        assert r.cursor is None

    def test_status_values(self):
        # 支持 ok / error / timeout / partial
        for status in ("ok", "error", "timeout", "partial"):
            r = self._make_response(status=status)
            assert r.status == status

    def test_with_items(self):
        item = SearchItem(
            id="x",
            source="zoekt",
            content_type=ContentType.CODE,
            title="foo.java",
            summary="s",
            url="http://u",
            score=0.5,
        )
        r = self._make_response(items=[item])
        assert len(r.items) == 1


# ─── SearchAdapter ABC ────────────────────────────────────────────────────────

class TestSearchAdapterABC:
    """SearchAdapter 是抽象基类，不可直接实例化。"""

    def test_cannot_instantiate_directly(self):
        # 直接实例化必须抛出 TypeError
        with pytest.raises(TypeError):
            SearchAdapter()  # type: ignore

    def test_subclass_must_implement_search(self):
        """未实现 search 的子类不可实例化。"""

        class PartialAdapter(SearchAdapter):
            async def get_content(self, item_id: str) -> dict:
                return {}

            async def health_check(self) -> bool:
                return True

            @property
            def backend_name(self) -> str:
                return "partial"

            @property
            def supported_content_types(self) -> list:
                return []

        with pytest.raises(TypeError):
            PartialAdapter()

    def test_full_subclass_can_instantiate(self):
        """实现所有抽象方法的子类可以实例化。"""

        class ConcreteAdapter(SearchAdapter):
            async def search(self, query: BackendQuery) -> BackendResponse:
                return BackendResponse(backend="test", status="ok", latency_ms=0.0, total_hits=0)

            async def get_content(self, item_id: str) -> dict:
                return {}

            async def health_check(self) -> bool:
                return True

            @property
            def backend_name(self) -> str:
                return "test"

            @property
            def supported_content_types(self) -> list:
                return [ContentType.CODE]

        adapter = ConcreteAdapter()
        assert adapter.backend_name == "test"
        assert ContentType.CODE in adapter.supported_content_types
