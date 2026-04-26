"""Tests for gateway.converters and ranker dense boost."""

import pytest

from gateway.converters import dense_result_to_dict
from gateway.fusion import rrf_merge
from gateway.ranker import feature_rerank


class TestDenseResultToDict:
    def test_basic_conversion(self):
        hit = {
            "id": "1",
            "score": 0.92,
            "metadata": {
                "repo": "frameworks/base",
                "path": "core/java/android/app/Activity.java",
                "content": "public class Activity",
                "start_line": 1,
                "end_line": 100,
            },
        }
        result = dense_result_to_dict(hit)
        assert result["title"] == "frameworks/base/core/java/android/app/Activity.java"
        assert result["score"] == 0.92
        assert result["content"] == "public class Activity"
        assert result["metadata"]["source"] == "dense"
        assert result["metadata"]["repo"] == "frameworks/base"
        assert result["metadata"]["path"] == "core/java/android/app/Activity.java"

    def test_empty_repo(self):
        hit = {"id": "1", "score": 0.5, "metadata": {"repo": "", "path": "test.java", "content": ""}}
        result = dense_result_to_dict(hit)
        assert result["title"] == "test.java"

    def test_missing_metadata(self):
        hit = {"id": "1", "score": 0.5}
        result = dense_result_to_dict(hit)
        assert result["title"] == ""
        assert result["metadata"]["source"] == "dense"


class TestRRFMergeDedupCompatibility:
    """Verify that Dense dict format is compatible with rrf_merge dedup key."""

    def test_dedup_across_zoekt_and_dense(self):
        """Same file from both backends should be deduped."""
        zoekt_results = [[{
            "title": "frameworks/base/core/java/Test.java",
            "content": "zoekt content",
            "score": 0.5,
            "metadata": {"repo": "frameworks/base", "path": "core/java/Test.java"},
        }]]
        dense_results = [[dense_result_to_dict({
            "id": "1",
            "score": 0.9,
            "metadata": {
                "repo": "frameworks/base",
                "path": "core/java/Test.java",
                "content": "dense content",
            },
        })]]

        merged = rrf_merge(zoekt_results + dense_results)
        # Same file should be deduped — only 1 result
        titles = [r["title"] for r in merged]
        assert titles.count("frameworks/base/core/java/Test.java") == 1

    def test_different_files_not_deduped(self):
        """Different files should not be deduped."""
        zoekt_results = [[{
            "title": "frameworks/base/A.java",
            "content": "a",
            "score": 0.5,
            "metadata": {"repo": "frameworks/base", "path": "A.java"},
        }]]
        dense_results = [[dense_result_to_dict({
            "id": "1",
            "score": 0.9,
            "metadata": {"repo": "frameworks/base", "path": "B.java", "content": "b"},
        })]]

        merged = rrf_merge(zoekt_results + dense_results)
        assert len(merged) == 2


class TestRankerDenseBoost:
    """Verify ranker applies dense boost correctly."""

    def test_dense_source_gets_boost(self):
        candidates = [
            {
                "title": "frameworks/base/A.java",
                "content": "test",
                "score": 0.016,
                "metadata": {"repo": "frameworks/base", "path": "A.java", "source": "dense"},
            },
            {
                "title": "frameworks/base/B.java",
                "content": "test",
                "score": 0.016,
                "metadata": {"repo": "frameworks/base", "path": "B.java"},
            },
        ]
        result = feature_rerank("test query", candidates, top_n=2)
        # Dense result should rank higher due to boost
        assert result[0]["metadata"].get("source") == "dense"
        assert result[0]["score"] > result[1]["score"]

    def test_no_boost_without_dense_source(self):
        candidates = [
            {
                "title": "A.java",
                "content": "test",
                "score": 0.02,
                "metadata": {"repo": "r", "path": "A.java"},
            },
            {
                "title": "B.java",
                "content": "test",
                "score": 0.01,
                "metadata": {"repo": "r", "path": "B.java"},
            },
        ]
        result = feature_rerank("query", candidates, top_n=2)
        # A should still rank first (higher base score)
        assert "A.java" in result[0]["title"]
