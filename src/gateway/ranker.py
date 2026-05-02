"""Feature-based lightweight reranking."""

import re

import config


def feature_rerank(
    query: str,
    candidates: list[dict],
    top_n: int = 10,
) -> list[dict]:
    """
    Feature-based lightweight reranking.

    Features:
    1. Number of query keywords present in the title.
    2. Keyword hit density in the content.
    3. File-type priority (.java > .cpp > others).
    4. RRF base score.
    5. Dense semantic match bonus.

    Args:
        query: Original user query.
        candidates: Candidate list after RRF fusion.
        top_n: Number of top results to return.

    Returns:
        Reranked top_n results.
    """
    query_lower = query.lower()
    # Extract Chinese and English keywords
    query_tokens = set(query_lower.split())
    # Also extract individual words from CamelCase
    camel_words = re.findall(r'[A-Z][a-z]+', query)
    query_tokens.update(w.lower() for w in camel_words)
    # Drop tokens that are too short
    query_tokens = {t for t in query_tokens if len(t) >= 2}

    scored = []
    for c in candidates:
        score = c.get("score", 0.0)
        title = c.get("title", "").lower()
        content = c.get("content", "").lower()

        # Feature 1: title hits (higher weight)
        title_hits = sum(1 for t in query_tokens if t in title)
        score += title_hits * 0.15

        # Feature 2: content hit density (capped)
        content_hits = sum(1 for t in query_tokens if t in content)
        score += min(content_hits * 0.03, 0.15)

        # Feature 3: file type priority
        if title.endswith('.java'):
            score += 0.05
        elif title.endswith(('.cpp', '.cc', '.h', '.hpp')):
            score += 0.03
        elif title.endswith('.py'):
            score += 0.02

        # Feature 4: high-value directories in path
        high_value_paths = ['frameworks/base', 'system/core', 'system/server']
        for hvp in high_value_paths:
            if hvp in title:
                score += 0.03
                break

        # Feature 5: Dense semantic match bonus
        meta = c.get("metadata", {})
        if meta.get("source") == "dense":
            score += config.DENSE_RERANK_BOOST

        scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)

    result = []
    for s, c in scored[:top_n]:
        c = c.copy()
        c["score"] = round(s, 4)
        result.append(c)

    return result
