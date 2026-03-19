"""
RRF (Reciprocal Rank Fusion) 多路召回融合

将多路 Zoekt 搜索结果按排名融合去重。
"""

from collections import defaultdict


def rrf_merge(result_lists: list[list[dict]], k: int = 60) -> list[dict]:
    """
    Reciprocal Rank Fusion。

    Args:
        result_lists: 多路搜索结果，每路是一个 record 列表
        k: RRF 平滑常数（默认 60）

    Returns:
        融合并按分数降序排列的结果列表
    """
    scores: dict[tuple, float] = defaultdict(float)
    docs: dict[tuple, dict] = {}

    for results in result_lists:
        for rank, doc in enumerate(results):
            meta = doc.get("metadata", {})
            doc_id = (
                meta.get("repo", ""),
                meta.get("path", ""),
                doc.get("title", ""),
            )
            scores[doc_id] += 1.0 / (k + rank + 1)
            # 保留分数最高的版本
            if doc_id not in docs:
                docs[doc_id] = doc

    # 按 RRF 分数降序排列
    sorted_ids = sorted(scores, key=scores.get, reverse=True)

    merged = []
    for doc_id in sorted_ids:
        doc = docs[doc_id].copy()
        doc["score"] = round(scores[doc_id], 4)
        merged.append(doc)

    return merged
