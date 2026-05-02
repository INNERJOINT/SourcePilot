"""Cross-engine result fusion via Reciprocal Rank Fusion."""

from collections import defaultdict


def rrf_merge(result_lists: list[list[dict]], k: int = 60) -> list[dict]:
    """
    Reciprocal Rank Fusion.

    Args:
        result_lists: Multi-lane search results; each lane is a list of records.
        k: RRF smoothing constant (default 60).

    Returns:
        Merged result list sorted by score in descending order.
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
            # Keep the highest-scoring version
            if doc_id not in docs:
                docs[doc_id] = doc

    # Sort by RRF score descending
    sorted_ids = sorted(scores, key=scores.get, reverse=True)

    merged = []
    for doc_id in sorted_ids:
        doc = docs[doc_id].copy()
        doc["score"] = round(scores[doc_id], 4)
        merged.append(doc)

    return merged
