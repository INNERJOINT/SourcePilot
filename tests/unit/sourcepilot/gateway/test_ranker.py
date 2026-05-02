"""
Unit tests for the feature re-ranking module

Tests the feature_rerank function in gateway/ranker.py.
"""
import pytest
from gateway.ranker import feature_rerank


def _make_candidate(title: str, content: str = "", score: float = 0.5) -> dict:
    """Build a test candidate record."""
    return {"title": title, "content": content, "score": score}


class TestFeatureRerank:
    """Test suite for the feature_rerank function."""

    def test_empty_candidates(self):
        """Empty candidate list returns empty list."""
        assert feature_rerank("query", []) == []

    def test_title_keyword_hit_bonus(self):
        """Each query keyword hit in the title earns +0.15."""
        # "systemserver" lowercase token matches the title
        c = _make_candidate("systemserver.java", score=0.0)
        result = feature_rerank("systemserver", [c])
        # 1 title hit (+0.15) + .java (+0.05) = 0.20
        assert result[0]["score"] == pytest.approx(0.20, abs=1e-4)

    def test_camelcase_splitting(self):
        """CamelCase query is split into multiple tokens."""
        # "SystemServer" → tokens: {"systemserver", "system", "server"}
        # title contains "system" → matches 2 (system, server) in "systemserver.java"
        # "systemserver" also matches → 3 tokens: systemserver, system, server
        c = _make_candidate("systemserver.java", score=0.0)
        result = feature_rerank("SystemServer", [c])
        # tokens = {systemserver, system, server} (len>=2)
        # title = "systemserver.java"
        # title_hits: "systemserver" ✓, "system" ✓, "server" ✓ → 3 hits
        # score = 0 + 3*0.15 + 0 + 0.05 = 0.50
        assert result[0]["score"] == pytest.approx(0.50, abs=1e-4)

    def test_content_density_bonus_capped(self):
        """Content keyword hits accumulate at 0.03/hit, capped at +0.15."""
        # 6 distinct tokens in query, all hit in content → min(6*0.03, 0.15) = 0.15
        content = "alpha beta gamma delta epsilon zeta"
        c = _make_candidate("file.txt", content=content, score=0.0)
        result = feature_rerank("alpha beta gamma delta epsilon zeta", [c])
        assert result[0]["score"] == pytest.approx(0.15, abs=1e-4)

    def test_content_density_partial(self):
        """3 content hits → +0.09."""
        content = "apple banana cherry"
        c = _make_candidate("file.txt", content=content, score=0.0)
        result = feature_rerank("apple banana cherry", [c])
        assert result[0]["score"] == pytest.approx(0.09, abs=1e-4)

    def test_java_file_bonus(self):
        """.java files receive a +0.05 bonus."""
        c = _make_candidate("SomeClass.java", score=0.5)
        result = feature_rerank("query", [c])
        assert result[0]["score"] == pytest.approx(0.55, abs=1e-4)

    def test_cpp_file_bonus(self):
        """.cpp files receive a +0.03 bonus."""
        c = _make_candidate("main.cpp", score=0.5)
        result = feature_rerank("query", [c])
        assert result[0]["score"] == pytest.approx(0.53, abs=1e-4)

    def test_py_file_bonus(self):
        """.py files receive a +0.02 bonus."""
        c = _make_candidate("utils.py", score=0.5)
        result = feature_rerank("query", [c])
        assert result[0]["score"] == pytest.approx(0.52, abs=1e-4)

    def test_txt_no_file_type_bonus(self):
        """.txt files receive no file-type bonus."""
        c = _make_candidate("notes.txt", score=0.5)
        result = feature_rerank("query", [c])
        assert result[0]["score"] == pytest.approx(0.5, abs=1e-4)

    def test_h_file_bonus(self):
        """.h header files receive a +0.03 bonus."""
        c = _make_candidate("header.h", score=0.5)
        result = feature_rerank("query", [c])
        assert result[0]["score"] == pytest.approx(0.53, abs=1e-4)

    def test_high_value_path_bonus(self):
        """Titles containing the frameworks/base directory receive a +0.03 bonus."""
        c = _make_candidate("frameworks/base/core/SystemServer.java", score=0.5)
        result = feature_rerank("query", [c])
        # .java (+0.05) + frameworks/base (+0.03) = +0.08
        assert result[0]["score"] == pytest.approx(0.58, abs=1e-4)

    def test_high_value_path_only_once(self):
        """High-value path bonus is only applied once (break after first match)."""
        # matches both frameworks/base and system/core → only +0.03 once
        c = _make_candidate("frameworks/base/system/core/file.txt", score=0.5)
        result = feature_rerank("query", [c])
        assert result[0]["score"] == pytest.approx(0.53, abs=1e-4)

    def test_top_n_truncation(self):
        """top_n parameter limits the number of returned results."""
        candidates = [_make_candidate(f"file{i}.txt", score=float(i)) for i in range(5)]
        result = feature_rerank("query", candidates, top_n=3)
        assert len(result) == 3

    def test_top_n_default_is_10(self):
        """Default top_n=10 truncates when there are more than 10 candidates."""
        candidates = [_make_candidate(f"f{i}.txt", score=float(i)) for i in range(15)]
        result = feature_rerank("query", candidates)
        assert len(result) == 10

    def test_score_preserved_and_augmented(self):
        """Original score is preserved; feature scores are added on top of it."""
        c = _make_candidate("plain.txt", score=0.8)
        result = feature_rerank("nonexistent_token_xyz", [c])
        # No keyword hits, no file-type bonus → score stays at 0.8
        assert result[0]["score"] == pytest.approx(0.8, abs=1e-4)

    def test_ordering_by_score_descending(self):
        """Results are sorted by final score in descending order."""
        candidates = [
            _make_candidate("low.txt", score=0.1),
            _make_candidate("high.java", score=0.9),   # +0.05 java
            _make_candidate("mid.py", score=0.5),      # +0.02 py
        ]
        result = feature_rerank("query", candidates)
        scores = [r["score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_short_tokens_ignored(self):
        """Tokens shorter than 2 characters are filtered and do not participate in matching."""
        # query "a b" → tokens {"a", "b"} are both filtered (length < 2)
        c = _make_candidate("a b c", score=0.5)
        result = feature_rerank("a b", [c])
        # no valid tokens; no title bonus
        assert result[0]["score"] == pytest.approx(0.5, abs=1e-4)

    def test_result_is_copy_not_mutated(self):
        """Returned documents are copies; the original candidate's score is not modified."""
        c = _make_candidate("file.java", score=0.3)
        feature_rerank("query", [c])
        assert c["score"] == pytest.approx(0.3, abs=1e-4)
