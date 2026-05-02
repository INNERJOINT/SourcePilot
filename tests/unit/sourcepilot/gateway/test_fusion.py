"""
Unit tests for the RRF fusion module

Tests the rrf_merge function in gateway/fusion.py.
"""
import pytest
from gateway.fusion import rrf_merge


def _make_doc(repo: str, path: str, title: str, score: float = 0.5) -> dict:
    """Build a test doc record."""
    return {
        "title": title,
        "score": score,
        "metadata": {"repo": repo, "path": path},
    }


class TestRrfMerge:
    """rrf_merge function test suite."""

    def test_empty_input(self):
        """Empty input returns an empty list."""
        assert rrf_merge([]) == []

    def test_single_list(self):
        """Single-lane results: each document receives an RRF score."""
        docs = [
            _make_doc("repo/a", "file1.java", "File1.java"),
            _make_doc("repo/a", "file2.java", "File2.java"),
        ]
        result = rrf_merge([docs])
        assert len(result) == 2
        # RRF score = 1/(60 + rank + 1), rank=0 → 1/61 ≈ 0.0164
        assert result[0]["score"] == round(1.0 / 61, 4)
        assert result[1]["score"] == round(1.0 / 62, 4)

    def test_normal_fusion_two_lists(self):
        """Two-lane fusion: scores computed correctly, sorted descending."""
        list1 = [_make_doc("repo", "a.java", "A.java")]
        list2 = [_make_doc("repo", "b.java", "B.java"), _make_doc("repo", "a.java", "A.java")]
        result = rrf_merge([list1, list2])
        # a.java appears in list1 rank=0 and list2 rank=1
        # score_a = 1/61 + 1/62 ≈ 0.0325
        # score_b = 1/61 (only in list2 rank=0)
        score_a = round(1.0 / 61 + 1.0 / 62, 4)
        score_b = round(1.0 / 61, 4)
        titles = [r["title"] for r in result]
        assert "A.java" in titles
        assert "B.java" in titles
        # a.java has higher score; should be first
        assert result[0]["title"] == "A.java"
        assert result[0]["score"] == score_a
        assert result[1]["score"] == score_b

    def test_dedup_by_repo_path_title(self):
        """Documents with the same (repo, path, title) are merged into one entry with cumulative score."""
        doc = _make_doc("repo/x", "path/file.java", "File.java")
        result = rrf_merge([[doc], [doc]])
        # same document appears at rank=0 in both lanes
        assert len(result) == 1
        expected = round(1.0 / 61 + 1.0 / 61, 4)
        assert result[0]["score"] == expected

    def test_different_docs_no_dedup(self):
        """Documents with different (repo, path, title) are not merged."""
        list1 = [_make_doc("repo", "a.java", "A.java")]
        list2 = [_make_doc("repo", "b.java", "B.java")]
        result = rrf_merge([list1, list2])
        assert len(result) == 2

    def test_k_parameter_affects_scores(self):
        """A larger k value makes scores more uniform (smaller difference between ranks)."""
        docs = [_make_doc("r", f"f{i}.java", f"F{i}.java") for i in range(3)]
        result_k10 = rrf_merge([[docs[0], docs[1]]], k=10)
        result_k100 = rrf_merge([[docs[0], docs[1]]], k=100)
        # k=10: rank0=1/11≈0.091, rank1=1/12≈0.083, diff≈0.008
        # k=100: rank0=1/101≈0.0099, rank1=1/102≈0.0098, smaller diff
        diff_k10 = result_k10[0]["score"] - result_k10[1]["score"]
        diff_k100 = result_k100[0]["score"] - result_k100[1]["score"]
        assert diff_k10 > diff_k100

    def test_score_ordering_descending(self):
        """Output is sorted by RRF score in descending order."""
        # three lanes; first document appears most often
        doc_a = _make_doc("r", "a.java", "A.java")
        doc_b = _make_doc("r", "b.java", "B.java")
        doc_c = _make_doc("r", "c.java", "C.java")
        result = rrf_merge([[doc_a, doc_b, doc_c], [doc_a], [doc_b, doc_a]])
        scores = [r["score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_missing_metadata_key(self):
        """Documents without a metadata field use empty strings for the first two doc_id elements."""
        doc = {"title": "NoMeta.java", "score": 0.5}  # no metadata field
        result = rrf_merge([[doc]])
        assert len(result) == 1
        assert result[0]["title"] == "NoMeta.java"
        assert result[0]["score"] == round(1.0 / 61, 4)

    def test_missing_partial_metadata(self):
        """Missing repo/path fields in metadata fall back to empty strings."""
        doc = {"title": "PartialMeta.java", "score": 0.5, "metadata": {"lang": "java"}}
        result = rrf_merge([[doc]])
        assert len(result) == 1

    def test_result_is_copy_not_mutated(self):
        """Returned documents are copies; the original doc's score is not modified."""
        original_score = 0.999
        doc = _make_doc("r", "f.java", "F.java", score=original_score)
        rrf_merge([[doc]])
        # original document's score must not be changed
        assert doc["score"] == original_score
