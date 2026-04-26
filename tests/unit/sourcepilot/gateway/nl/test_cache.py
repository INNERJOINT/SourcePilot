"""
gateway/nl/cache.py 单元测试

覆盖概念映射表命中、LRU 缓存 miss/hit、TTL 过期、LRU 驱逐、hash key 规范化。

注意：_cache 和 _concept_map 是模块级全局变量，测试间必须清理以防串污。
"""

import time
import pytest
import gateway.nl.cache as cache_module
from gateway.nl.cache import get_cached_rewrite, set_cached_rewrite


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_cache():
    """每个测试前后清空 _cache，防止测试间串污。"""
    cache_module._cache.clear()
    yield
    cache_module._cache.clear()


@pytest.fixture
def concept_map_with_data():
    """临时注入测试用概念映射数据，测试后恢复。"""
    original = dict(cache_module._concept_map)
    cache_module._concept_map["ActivityManager"] = [
        {"query": "ActivityManager", "rationale": "concept_map"},
        {"query": "ActivityManagerService", "rationale": "concept_map"},
    ]
    yield cache_module._concept_map
    cache_module._concept_map.clear()
    cache_module._concept_map.update(original)


# ─── 概念映射表测试 ───────────────────────────────────────────────────────────

class TestConceptMap:
    """concept_map 命中时直接返回映射结果，不走 LRU 缓存。"""

    def test_concept_map_hit(self, concept_map_with_data):
        # query 中包含 "ActivityManager" → 命中概念映射
        result = get_cached_rewrite("ActivityManager是什么")
        assert result is not None
        queries = [q["query"] for q in result]
        assert "ActivityManager" in queries

    def test_concept_map_miss(self, concept_map_with_data):
        # query 不包含任何 concept key → miss
        result = get_cached_rewrite("完全不相关的查询xyz123")
        assert result is None

    def test_concept_map_substring_match(self, concept_map_with_data):
        # "ActivityManager" 是 query 的子串即可命中
        result = get_cached_rewrite("关于ActivityManager的启动流程")
        assert result is not None

    def test_concept_map_exact_key(self, concept_map_with_data):
        # query 与 concept key 完全相同也能命中
        result = get_cached_rewrite("ActivityManager")
        assert result is not None


# ─── LRU 缓存 miss ────────────────────────────────────────────────────────────

class TestCacheMiss:
    """空缓存或未设置的 query → 返回 None。"""

    def test_empty_cache_returns_none(self):
        assert get_cached_rewrite("some query") is None

    def test_different_query_miss(self):
        set_cached_rewrite("query A", [{"query": "A", "rationale": "r"}])
        assert get_cached_rewrite("query B") is None


# ─── set + get 往返测试 ────────────────────────────────────────────────────────

class TestSetGet:
    """set_cached_rewrite 后能通过 get_cached_rewrite 取回相同结果。"""

    def test_set_then_get(self):
        data = [{"query": "SystemServer", "rationale": "test"}]
        set_cached_rewrite("SystemServer启动流程", data)
        result = get_cached_rewrite("SystemServer启动流程")
        assert result == data

    def test_overwrite_same_query(self):
        # 对同一 query 两次 set，取最后一次
        data1 = [{"query": "foo", "rationale": "first"}]
        data2 = [{"query": "bar", "rationale": "second"}]
        set_cached_rewrite("my query", data1)
        set_cached_rewrite("my query", data2)
        result = get_cached_rewrite("my query")
        assert result == data2


# ─── TTL 过期测试 ─────────────────────────────────────────────────────────────

class TestTTLExpiry:
    """缓存条目超过 NL_CACHE_TTL 后应返回 None 并删除条目。"""

    def test_ttl_expiry(self, monkeypatch):
        # 使用不在 concept_map 中的查询键（避免 concept_map 命中干扰）
        data = [{"query": "CustomClassXyz", "rationale": "test"}]
        set_cached_rewrite("CustomClassXyz唯一测试查询", data)

        # 将 cache_module.time.time 伪造到 TTL 之后
        from config import NL_CACHE_TTL
        future_time = time.time() + NL_CACHE_TTL + 1
        monkeypatch.setattr(cache_module.time, "time", lambda: future_time)

        result = get_cached_rewrite("CustomClassXyz唯一测试查询")
        assert result is None

    def test_entry_deleted_after_ttl(self, monkeypatch):
        # TTL 过期后 _cache 中对应条目被删除
        # 使用不在 concept_map 中的查询键
        data = [{"query": "UniqueTestToken999", "rationale": "test"}]
        set_cached_rewrite("UniqueTestToken999初始化", data)

        from gateway.nl.cache import _hash_key
        key = _hash_key("UniqueTestToken999初始化")
        assert key in cache_module._cache

        from config import NL_CACHE_TTL
        future_time = time.time() + NL_CACHE_TTL + 1
        monkeypatch.setattr(cache_module.time, "time", lambda: future_time)

        get_cached_rewrite("UniqueTestToken999初始化")
        assert key not in cache_module._cache

    def test_within_ttl_not_expired(self, monkeypatch):
        # 使用不在 concept_map 中的查询键
        data = [{"query": "PackageManagerXyz", "rationale": "test"}]
        set_cached_rewrite("PackageManagerXyz安装测试", data)

        # 伪造时间为 TTL - 1 秒内（仍有效）
        from config import NL_CACHE_TTL
        near_future = time.time() + NL_CACHE_TTL - 1
        monkeypatch.setattr(cache_module.time, "time", lambda: near_future)

        result = get_cached_rewrite("PackageManagerXyz安装测试")
        assert result == data


# ─── LRU 驱逐测试 ─────────────────────────────────────────────────────────────

class TestLRUEviction:
    """超过 1000 条时驱逐最旧条目，保持缓存大小 ≤ 1000。"""

    def test_eviction_keeps_size_at_most_1000(self):
        # 写入 1001 条，缓存应驱逐最旧的一条，保持 ≤ 1000
        for i in range(1001):
            set_cached_rewrite(f"query_{i}", [{"query": f"q{i}", "rationale": "r"}])
        assert len(cache_module._cache) <= 1000

    def test_oldest_entry_evicted(self):
        # 最先写入的 "query_0" 应该被驱逐
        from gateway.nl.cache import _hash_key
        first_key = _hash_key("query_0")

        for i in range(1001):
            set_cached_rewrite(f"query_{i}", [{"query": f"q{i}", "rationale": "r"}])

        assert first_key not in cache_module._cache


# ─── Hash Key 规范化测试 ──────────────────────────────────────────────────────

class TestHashKey:
    """_hash_key 对 strip().lower() 后的内容做 md5，大小写/空白不影响命中。"""

    def test_same_key_case_insensitive(self):
        from gateway.nl.cache import _hash_key
        assert _hash_key("FOO") == _hash_key("foo")

    def test_same_key_strip_whitespace(self):
        from gateway.nl.cache import _hash_key
        assert _hash_key("  foo  ") == _hash_key("foo")

    def test_case_insensitive_cache_hit(self):
        # 用大写 set，用小写 get → 应命中
        data = [{"query": "Foo", "rationale": "test"}]
        set_cached_rewrite("FOO QUERY", data)
        result = get_cached_rewrite("foo query")
        assert result == data

    def test_different_content_different_key(self):
        from gateway.nl.cache import _hash_key
        assert _hash_key("foo") != _hash_key("bar")
