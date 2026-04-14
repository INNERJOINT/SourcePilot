"""
RRF 融合模块单元测试

测试 gateway/fusion.py 中的 rrf_merge 函数。
"""
import pytest
from gateway.fusion import rrf_merge


def _make_doc(repo: str, path: str, title: str, score: float = 0.5) -> dict:
    """构造测试用 doc 记录"""
    return {
        "title": title,
        "score": score,
        "metadata": {"repo": repo, "path": path},
    }


class TestRrfMerge:
    """rrf_merge 函数测试套件"""

    def test_empty_input(self):
        """空输入返回空列表"""
        assert rrf_merge([]) == []

    def test_single_list(self):
        """单路结果：每个文档获得 RRF 分数"""
        docs = [
            _make_doc("repo/a", "file1.java", "File1.java"),
            _make_doc("repo/a", "file2.java", "File2.java"),
        ]
        result = rrf_merge([docs])
        assert len(result) == 2
        # RRF 分数 = 1/(60 + rank + 1)，rank=0 → 1/61 ≈ 0.0164
        assert result[0]["score"] == round(1.0 / 61, 4)
        assert result[1]["score"] == round(1.0 / 62, 4)

    def test_normal_fusion_two_lists(self):
        """两路结果融合：分数正确计算，按分数降序"""
        list1 = [_make_doc("repo", "a.java", "A.java")]
        list2 = [_make_doc("repo", "b.java", "B.java"), _make_doc("repo", "a.java", "A.java")]
        result = rrf_merge([list1, list2])
        # a.java 在 list1 rank=0 和 list2 rank=1 都出现
        # score_a = 1/61 + 1/62 ≈ 0.0325
        # score_b = 1/61 (只在 list2 rank=0)
        score_a = round(1.0 / 61 + 1.0 / 62, 4)
        score_b = round(1.0 / 61, 4)
        titles = [r["title"] for r in result]
        assert "A.java" in titles
        assert "B.java" in titles
        # a.java 分数更高，应排在首位
        assert result[0]["title"] == "A.java"
        assert result[0]["score"] == score_a
        assert result[1]["score"] == score_b

    def test_dedup_by_repo_path_title(self):
        """相同 (repo, path, title) 的文档被合并为一条，分数叠加"""
        doc = _make_doc("repo/x", "path/file.java", "File.java")
        result = rrf_merge([[doc], [doc]])
        # 同一文档出现在两路 rank=0
        assert len(result) == 1
        expected = round(1.0 / 61 + 1.0 / 61, 4)
        assert result[0]["score"] == expected

    def test_different_docs_no_dedup(self):
        """不同 (repo, path, title) 的文档不合并"""
        list1 = [_make_doc("repo", "a.java", "A.java")]
        list2 = [_make_doc("repo", "b.java", "B.java")]
        result = rrf_merge([list1, list2])
        assert len(result) == 2

    def test_k_parameter_affects_scores(self):
        """较大的 k 值使分数更均匀（分差更小）"""
        docs = [_make_doc("r", f"f{i}.java", f"F{i}.java") for i in range(3)]
        result_k10 = rrf_merge([[docs[0], docs[1]]], k=10)
        result_k100 = rrf_merge([[docs[0], docs[1]]], k=100)
        # k=10: rank0=1/11≈0.091, rank1=1/12≈0.083, 差值≈0.008
        # k=100: rank0=1/101≈0.0099, rank1=1/102≈0.0098, 差值更小
        diff_k10 = result_k10[0]["score"] - result_k10[1]["score"]
        diff_k100 = result_k100[0]["score"] - result_k100[1]["score"]
        assert diff_k10 > diff_k100

    def test_score_ordering_descending(self):
        """输出按 RRF 分数降序排列"""
        # 构造 3 路结果，第一个文档出现频率最高
        doc_a = _make_doc("r", "a.java", "A.java")
        doc_b = _make_doc("r", "b.java", "B.java")
        doc_c = _make_doc("r", "c.java", "C.java")
        result = rrf_merge([[doc_a, doc_b, doc_c], [doc_a], [doc_b, doc_a]])
        scores = [r["score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_missing_metadata_key(self):
        """没有 metadata 字段的文档使用空字符串作为 doc_id 的前两个元素"""
        doc = {"title": "NoMeta.java", "score": 0.5}  # 无 metadata 字段
        result = rrf_merge([[doc]])
        assert len(result) == 1
        assert result[0]["title"] == "NoMeta.java"
        assert result[0]["score"] == round(1.0 / 61, 4)

    def test_missing_partial_metadata(self):
        """metadata 中缺少 repo/path 字段，降级为空字符串"""
        doc = {"title": "PartialMeta.java", "score": 0.5, "metadata": {"lang": "java"}}
        result = rrf_merge([[doc]])
        assert len(result) == 1

    def test_result_is_copy_not_mutated(self):
        """返回的文档是副本，原始 doc 的 score 不被修改"""
        original_score = 0.999
        doc = _make_doc("r", "f.java", "F.java", score=original_score)
        rrf_merge([[doc]])
        # 原始文档的 score 不应被修改
        assert doc["score"] == original_score
