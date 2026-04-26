"""
特征重排模块单元测试

测试 gateway/ranker.py 中的 feature_rerank 函数。
"""
import pytest
from gateway.ranker import feature_rerank


def _make_candidate(title: str, content: str = "", score: float = 0.5) -> dict:
    """构造测试用候选记录"""
    return {"title": title, "content": content, "score": score}


class TestFeatureRerank:
    """feature_rerank 函数测试套件"""

    def test_empty_candidates(self):
        """空候选列表返回空列表"""
        assert feature_rerank("query", []) == []

    def test_title_keyword_hit_bonus(self):
        """标题中包含查询关键词时，每命中 +0.15"""
        # "systemserver" 全小写 token 命中标题
        c = _make_candidate("systemserver.java", score=0.0)
        result = feature_rerank("systemserver", [c])
        # 标题命中 1 次 (+0.15) + .java (+0.05) = 0.20
        assert result[0]["score"] == pytest.approx(0.20, abs=1e-4)

    def test_camelcase_splitting(self):
        """CamelCase 查询被拆分为多个 token"""
        # "SystemServer" → tokens: {"systemserver", "system", "server"}
        # 标题包含 "system" → 命中 2 次 (system, server) in "systemserver.java"
        # 实际上 "systemserver" 也命中，共 3 个 token: systemserver, system, server
        c = _make_candidate("systemserver.java", score=0.0)
        result = feature_rerank("SystemServer", [c])
        # tokens = {systemserver, system, server} (len>=2)
        # title = "systemserver.java"
        # title_hits: "systemserver" in title ✓, "system" in title ✓, "server" in title ✓ → 3 hits
        # score = 0 + 3*0.15 + 0 + 0.05 = 0.50
        assert result[0]["score"] == pytest.approx(0.50, abs=1e-4)

    def test_content_density_bonus_capped(self):
        """内容关键词命中按 0.03/hit 累加，最多 +0.15"""
        # 查询包含 6 个不同 token，全部在内容中命中 → min(6*0.03, 0.15) = 0.15
        content = "alpha beta gamma delta epsilon zeta"
        c = _make_candidate("file.txt", content=content, score=0.0)
        result = feature_rerank("alpha beta gamma delta epsilon zeta", [c])
        assert result[0]["score"] == pytest.approx(0.15, abs=1e-4)

    def test_content_density_partial(self):
        """内容 3 次命中 → +0.09"""
        content = "apple banana cherry"
        c = _make_candidate("file.txt", content=content, score=0.0)
        result = feature_rerank("apple banana cherry", [c])
        assert result[0]["score"] == pytest.approx(0.09, abs=1e-4)

    def test_java_file_bonus(self):
        """.java 文件获得 +0.05 加分"""
        c = _make_candidate("SomeClass.java", score=0.5)
        result = feature_rerank("query", [c])
        assert result[0]["score"] == pytest.approx(0.55, abs=1e-4)

    def test_cpp_file_bonus(self):
        """.cpp 文件获得 +0.03 加分"""
        c = _make_candidate("main.cpp", score=0.5)
        result = feature_rerank("query", [c])
        assert result[0]["score"] == pytest.approx(0.53, abs=1e-4)

    def test_py_file_bonus(self):
        """.py 文件获得 +0.02 加分"""
        c = _make_candidate("utils.py", score=0.5)
        result = feature_rerank("query", [c])
        assert result[0]["score"] == pytest.approx(0.52, abs=1e-4)

    def test_txt_no_file_type_bonus(self):
        """.txt 文件不获得文件类型加分"""
        c = _make_candidate("notes.txt", score=0.5)
        result = feature_rerank("query", [c])
        assert result[0]["score"] == pytest.approx(0.5, abs=1e-4)

    def test_h_file_bonus(self):
        """.h 头文件获得 +0.03 加分"""
        c = _make_candidate("header.h", score=0.5)
        result = feature_rerank("query", [c])
        assert result[0]["score"] == pytest.approx(0.53, abs=1e-4)

    def test_high_value_path_bonus(self):
        """标题包含 frameworks/base 目录获得 +0.03 加分"""
        c = _make_candidate("frameworks/base/core/SystemServer.java", score=0.5)
        result = feature_rerank("query", [c])
        # .java (+0.05) + frameworks/base (+0.03) = +0.08
        assert result[0]["score"] == pytest.approx(0.58, abs=1e-4)

    def test_high_value_path_only_once(self):
        """高价值路径加分只计一次（break 后不继续）"""
        # 同时匹配 frameworks/base 和 system/core → 只加 0.03 一次
        c = _make_candidate("frameworks/base/system/core/file.txt", score=0.5)
        result = feature_rerank("query", [c])
        assert result[0]["score"] == pytest.approx(0.53, abs=1e-4)

    def test_top_n_truncation(self):
        """top_n 参数限制返回数量"""
        candidates = [_make_candidate(f"file{i}.txt", score=float(i)) for i in range(5)]
        result = feature_rerank("query", candidates, top_n=3)
        assert len(result) == 3

    def test_top_n_default_is_10(self):
        """默认 top_n=10，超过 10 个候选时截断"""
        candidates = [_make_candidate(f"f{i}.txt", score=float(i)) for i in range(15)]
        result = feature_rerank("query", candidates)
        assert len(result) == 10

    def test_score_preserved_and_augmented(self):
        """原始分数被保留，特征分数是在其基础上叠加的"""
        c = _make_candidate("plain.txt", score=0.8)
        result = feature_rerank("nonexistent_token_xyz", [c])
        # 无关键词命中，无文件类型加分 → 保持 0.8
        assert result[0]["score"] == pytest.approx(0.8, abs=1e-4)

    def test_ordering_by_score_descending(self):
        """结果按最终分数降序排列"""
        candidates = [
            _make_candidate("low.txt", score=0.1),
            _make_candidate("high.java", score=0.9),   # +0.05 java
            _make_candidate("mid.py", score=0.5),      # +0.02 py
        ]
        result = feature_rerank("query", candidates)
        scores = [r["score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_short_tokens_ignored(self):
        """长度 < 2 的 token 被过滤，不参与匹配"""
        # 查询 "a b" → tokens {"a", "b"} 都被过滤（长度 < 2）
        c = _make_candidate("a b c", score=0.5)
        result = feature_rerank("a b", [c])
        # 无有效 token，无标题加分
        assert result[0]["score"] == pytest.approx(0.5, abs=1e-4)

    def test_result_is_copy_not_mutated(self):
        """返回的文档是副本，原始候选的 score 不被修改"""
        c = _make_candidate("file.java", score=0.3)
        feature_rerank("query", [c])
        assert c["score"] == pytest.approx(0.3, abs=1e-4)
