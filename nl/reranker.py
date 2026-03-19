"""
Feature-based 轻量 Rerank

基于简单特征对融合后的候选结果重新排序。
不依赖 GPU 或外部模型，延迟 < 5ms。
"""


def feature_rerank(
    query: str,
    candidates: list[dict],
    top_n: int = 10,
) -> list[dict]:
    """
    基于特征的轻量重排。

    特征：
    1. 标题中包含查询关键词的数量
    2. 内容中关键词命中密度
    3. 文件类型优先级（.java > .cpp > 其他）
    4. RRF 原始分数

    Args:
        query: 用户原始查询
        candidates: RRF 融合后的候选列表
        top_n: 返回 top N 条

    Returns:
        重排后的 top_n 结果
    """
    query_lower = query.lower()
    # 提取中英文关键词
    query_tokens = set(query_lower.split())
    # 额外提取 CamelCase 中的各单词
    import re
    camel_words = re.findall(r'[A-Z][a-z]+', query)
    query_tokens.update(w.lower() for w in camel_words)
    # 丢弃过短的 token
    query_tokens = {t for t in query_tokens if len(t) >= 2}

    scored = []
    for c in candidates:
        score = c.get("score", 0.0)
        title = c.get("title", "").lower()
        content = c.get("content", "").lower()

        # 特征 1：标题命中（权重较高）
        title_hits = sum(1 for t in query_tokens if t in title)
        score += title_hits * 0.15

        # 特征 2：内容命中密度（有上限）
        content_hits = sum(1 for t in query_tokens if t in content)
        score += min(content_hits * 0.03, 0.15)

        # 特征 3：文件类型优先级
        if title.endswith('.java'):
            score += 0.05
        elif title.endswith(('.cpp', '.cc', '.h', '.hpp')):
            score += 0.03
        elif title.endswith('.py'):
            score += 0.02

        # 特征 4：路径中包含高价值目录
        high_value_paths = ['frameworks/base', 'system/core', 'system/server']
        for hvp in high_value_paths:
            if hvp in title:
                score += 0.03
                break

        scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)

    result = []
    for s, c in scored[:top_n]:
        c = c.copy()
        c["score"] = round(s, 4)
        result.append(c)

    return result
