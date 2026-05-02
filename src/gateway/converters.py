"""Result format converters for cross-backend compatibility."""


def structural_result_to_dict(hit: dict) -> dict:
    """Convert a Structural retrieval hit into an RRF-compatible dict format.

    Uses sub-file granularity (repo/path:start-end) to avoid dedup collapsing
    same-file chunks from Zoekt/Dense.
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
            "source": "structural",
        },
    }


def feishu_result_to_dict(hit: dict) -> dict:
    """Convert a Feishu dense hit into an RRF-compatible dict format."""
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
    """Convert a vector-database hit into the same dict format used by Zoekt.

    Input hit format (from Qdrant):
        {"id": "...", "score": 0.85, "metadata": {"repo": "frameworks/base",
         "path": "core/java/...", "start_line": 1, "end_line": 100,
         "content": "..."}}

    Output dict format (consistent with ZoektAdapter._convert_results):
        {"title": "frameworks/base/core/java/...", "content": "...",
         "score": 0.85, "metadata": {"repo": "...", "path": "..."}}

    Key: rrf_merge (fusion.py:23-27) uses (metadata.repo, metadata.path, title)
    as the dedup key, so all three fields must be populated in the same format as Zoekt.
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
