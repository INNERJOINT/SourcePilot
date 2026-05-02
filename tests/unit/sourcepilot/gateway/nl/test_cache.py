"""
Unit tests for gateway/nl/cache.py

Covers concept-map hits, LRU cache miss/hit, TTL expiry, LRU eviction, and hash key normalization.

Note: _cache and _concept_map are module-level globals; tests must clean up between runs to prevent cross-contamination.
"""

import time
import pytest
import gateway.nl.cache as cache_module
from gateway.nl.cache import get_cached_rewrite, set_cached_rewrite


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_cache():
    """Clear _cache before and after each test to prevent cross-test contamination."""
    cache_module._cache.clear()
    yield
    cache_module._cache.clear()


@pytest.fixture
def concept_map_with_data():
    """Temporarily inject test concept-map data, then restore the original after the test."""
    original = dict(cache_module._concept_map)
    cache_module._concept_map["ActivityManager"] = [
        {"query": "ActivityManager", "rationale": "concept_map"},
        {"query": "ActivityManagerService", "rationale": "concept_map"},
    ]
    yield cache_module._concept_map
    cache_module._concept_map.clear()
    cache_module._concept_map.update(original)


# ─── Concept-map tests ───────────────────────────────────────────────────────

class TestConceptMap:
    """When a concept-map key is hit, the mapped result is returned directly without touching the LRU cache."""

    def test_concept_map_hit(self, concept_map_with_data):
        # query contains "ActivityManager" → concept-map hit
        result = get_cached_rewrite("ActivityManager是什么")
        assert result is not None
        queries = [q["query"] for q in result]
        assert "ActivityManager" in queries

    def test_concept_map_miss(self, concept_map_with_data):
        # query contains no concept key → miss
        result = get_cached_rewrite("完全不相关的查询xyz123")
        assert result is None

    def test_concept_map_substring_match(self, concept_map_with_data):
        # "ActivityManager" only needs to be a substring of the query to hit
        result = get_cached_rewrite("关于ActivityManager的启动流程")
        assert result is not None

    def test_concept_map_exact_key(self, concept_map_with_data):
        # query identical to the concept key also hits
        result = get_cached_rewrite("ActivityManager")
        assert result is not None


# ─── LRU cache miss ────────────────────────────────────────────────────────────

class TestCacheMiss:
    """Empty cache or unset query → returns None."""

    def test_empty_cache_returns_none(self):
        assert get_cached_rewrite("some query") is None

    def test_different_query_miss(self):
        set_cached_rewrite("query A", [{"query": "A", "rationale": "r"}])
        assert get_cached_rewrite("query B") is None


# ─── set + get round-trip tests ──────────────────────────────────────────────

class TestSetGet:
    """After set_cached_rewrite, get_cached_rewrite returns the same data."""

    def test_set_then_get(self):
        data = [{"query": "SystemServer", "rationale": "test"}]
        set_cached_rewrite("SystemServer启动流程", data)
        result = get_cached_rewrite("SystemServer启动流程")
        assert result == data

    def test_overwrite_same_query(self):
        # two sets for the same query; get returns the second
        data1 = [{"query": "foo", "rationale": "first"}]
        data2 = [{"query": "bar", "rationale": "second"}]
        set_cached_rewrite("my query", data1)
        set_cached_rewrite("my query", data2)
        result = get_cached_rewrite("my query")
        assert result == data2


# ─── TTL expiry tests ─────────────────────────────────────────────────────────

class TestTTLExpiry:
    """Cache entries older than NL_CACHE_TTL should return None and be deleted."""

    def test_ttl_expiry(self, monkeypatch):
        # use a key not in concept_map (to avoid concept_map hit interference)
        data = [{"query": "CustomClassXyz", "rationale": "test"}]
        set_cached_rewrite("CustomClassXyz唯一测试查询", data)

        # fake cache_module.time.time to be past the TTL
        from config import NL_CACHE_TTL
        future_time = time.time() + NL_CACHE_TTL + 1
        monkeypatch.setattr(cache_module.time, "time", lambda: future_time)

        result = get_cached_rewrite("CustomClassXyz唯一测试查询")
        assert result is None

    def test_entry_deleted_after_ttl(self, monkeypatch):
        # after TTL expiry the corresponding entry is removed from _cache
        # use a key not in concept_map
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
        # use a key not in concept_map
        data = [{"query": "PackageManagerXyz", "rationale": "test"}]
        set_cached_rewrite("PackageManagerXyz安装测试", data)

        # fake time to TTL - 1 second (still valid)
        from config import NL_CACHE_TTL
        near_future = time.time() + NL_CACHE_TTL - 1
        monkeypatch.setattr(cache_module.time, "time", lambda: near_future)

        result = get_cached_rewrite("PackageManagerXyz安装测试")
        assert result == data


# ─── LRU eviction tests ───────────────────────────────────────────────────────

class TestLRUEviction:
    """After exceeding 1000 entries the oldest is evicted, keeping cache size ≤ 1000."""

    def test_eviction_keeps_size_at_most_1000(self):
        # write 1001 entries; cache should evict the oldest and stay ≤ 1000
        for i in range(1001):
            set_cached_rewrite(f"query_{i}", [{"query": f"q{i}", "rationale": "r"}])
        assert len(cache_module._cache) <= 1000

    def test_oldest_entry_evicted(self):
        # the first entry written ("query_0") should be evicted
        from gateway.nl.cache import _hash_key
        first_key = _hash_key("query_0")

        for i in range(1001):
            set_cached_rewrite(f"query_{i}", [{"query": f"q{i}", "rationale": "r"}])

        assert first_key not in cache_module._cache


# ─── Hash key normalization tests ─────────────────────────────────────────────

class TestHashKey:
    """_hash_key computes md5 over strip().lower() content; case/whitespace differences don't prevent hits."""

    def test_same_key_case_insensitive(self):
        from gateway.nl.cache import _hash_key
        assert _hash_key("FOO") == _hash_key("foo")

    def test_same_key_strip_whitespace(self):
        from gateway.nl.cache import _hash_key
        assert _hash_key("  foo  ") == _hash_key("foo")

    def test_case_insensitive_cache_hit(self):
        # set with uppercase, get with lowercase → should hit
        data = [{"query": "Foo", "rationale": "test"}]
        set_cached_rewrite("FOO QUERY", data)
        result = get_cached_rewrite("foo query")
        assert result == data

    def test_different_content_different_key(self):
        from gateway.nl.cache import _hash_key
        assert _hash_key("foo") != _hash_key("bar")
