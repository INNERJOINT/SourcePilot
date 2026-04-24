"""Result format converters for cross-backend compatibility."""


def graph_result_to_dict(hit: dict) -> dict:
    """Graph 检索 hit 转换为 RRF dict 格式。

    使用子文件粒度 (repo/path:start-end) 避免与 Zoekt/Dense 同文件 chunk dedup 折叠。
    """
    repo = hit.get("repo", "")
    path = hit.get("path", "")
    start = hit.get("start_line")
    end = hit.get("end_line")
    title = f"{repo}/{path}:{start}-{end}" if start is not None else f"{repo}/{path}"
    return {
        "title": title,
        "content": hit.get("content", ""),
        "score": hit.get("score", 0.0),
        "metadata": {
            "repo": repo,
            "path": path,
            "start_line": start,
            "end_line": end,
            "source": "graph",
        },
    }


def feishu_result_to_dict(hit: dict) -> dict:
    """将 Feishu dense hit 转换为 RRF-compatible dict 格式。"""
    meta = hit.get("metadata", {})
    title = meta.get("title", "")
    url = meta.get("url", "")
    return {
        "title": title or "Feishu Document",
        "content": meta.get("content", ""),
        "score": hit.get("score", 0.0),
        "metadata": {
            "title": title,
            "url": url,
            "space_id": meta.get("space_id", ""),
            "node_token": meta.get("node_token", ""),
            "source": "feishu",
        },
    }


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
