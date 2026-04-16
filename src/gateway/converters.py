"""Result format converters for cross-backend compatibility."""


def dense_result_to_dict(hit: dict) -> dict:
    """将向量数据库返回的 hit 转换为与 Zoekt 相同的 dict 格式。

    输入 hit 格式（来自 Milvus）:
        {"id": "...", "score": 0.85, "metadata": {"repo": "frameworks/base",
         "path": "core/java/...", "start_line": 1, "end_line": 100,
         "content": "..."}}

    输出 dict 格式（与 ZoektAdapter._convert_results 一致）:
        {"title": "frameworks/base/core/java/...", "content": "...",
         "score": 0.85, "metadata": {"repo": "...", "path": "..."}}

    关键：rrf_merge (fusion.py:23-27) 用 (metadata.repo, metadata.path, title)
    作为 dedup key，所以必须填充这三个字段且格式与 Zoekt 一致。
    """
    meta = hit.get("metadata", {})
    repo = meta.get("repo", "")
    path = meta.get("path", "")
    title = f"{repo}/{path}" if repo else path

    return {
        "title": title,
        "content": meta.get("content", ""),
        "score": hit.get("score", 0.0),
        "metadata": {
            "repo": repo,
            "path": path,
            "start_line": meta.get("start_line"),
            "end_line": meta.get("end_line"),
            "source": "dense",
        },
    }
