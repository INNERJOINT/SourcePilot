"""
Zoekt 搜索客户端

封装 Zoekt webserver 的 JSON API，将搜索结果转换为 Dify 外部知识库所需的 records 格式。
"""

import logging
from typing import Any

import httpx

from config import ZOEKT_URL, DEFAULT_CONTEXT_LINES

logger = logging.getLogger(__name__)


async def search(
    query: str,
    top_k: int = 5,
    score_threshold: float = 0.0,
    repos: str | None = None,
) -> list[dict[str, Any]]:
    """
    调用 Zoekt 搜索接口，返回 Dify 标准 records 列表。
    """
    import json

    # 构造 Zoekt 查询字符串
    zoekt_query = query
    if repos:
        zoekt_query = f"r:{repos} {query}"

    params = {
        "q": zoekt_query,
        "num": top_k * 3,
        "format": "json",
        "ctx": DEFAULT_CONTEXT_LINES,  # 控制 Zoekt 返回匹配行前后的上下文行数
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # 尝试 /search?format=json（兼容大多数 zoekt-webserver 版本）
            resp = await client.get(f"{ZOEKT_URL}/search", params=params)
            resp.raise_for_status()

            raw_text = resp.text
            logger.debug("Zoekt raw response (first 500 chars): %s", raw_text[:500])

            # 检测是否返回了 HTML（说明 format=json 不被支持）
            if raw_text.strip().startswith("<"):
                logger.error("Zoekt returned HTML instead of JSON. Endpoint may not support JSON format.")
                raise ValueError("Zoekt does not support JSON output on /search endpoint")

            data = json.loads(raw_text)

    except httpx.HTTPStatusError as e:
        logger.error("Zoekt API HTTP error: %s", e)
        raise
    except httpx.RequestError as e:
        logger.error("Zoekt API request error: %s", e)
        raise

    return _convert_results(data, top_k, score_threshold)


def _convert_results(
    data: dict[str, Any],
    top_k: int,
    score_threshold: float,
) -> list[dict[str, Any]]:
    """
    将 Zoekt 原始 JSON 响应转换为 Dify records 格式。

    Zoekt /api/search 返回格式示例:
    {
      "Result": {
        "Files": [
          {
            "FileName": "services/java/.../SystemServer.java",
            "Repository": "base",
            "Score": 12.5,
            "LineMatches": [
              {
                "LineNumber": 120,
                "Line": "base64-encoded-line-content",
                ...
              }
            ]
          }
        ],
        "Stats": { ... }
      }
    }
    """
    records = []

    # Zoekt 返回小写 "result"，内部嵌套一层
    result = data.get("Result") or data.get("result") or data
    if isinstance(result, dict):
        inner = result.get("Result") or result.get("result")
        if isinstance(inner, dict):
            result = inner

    # 字段名: FileMatches
    file_matches = (
        result.get("FileMatches") or result.get("fileMatches") or
        result.get("Files") or result.get("files") or []
    )

    if not file_matches:
        logger.info("Zoekt returned 0 file matches")
        return records

    total = len(file_matches)

    for idx, fm in enumerate(file_matches):
        # Zoekt 无 Score 字段，按排名递减分配分数 (1.0 → 0.x)
        normalized_score = round(1.0 - (idx / max(total, 1)) * 0.5, 4)

        if normalized_score < score_threshold:
            continue

        repo = fm.get("Repo", "")
        file_name = fm.get("FileName", "")
        title = f"{repo}/{file_name}" if repo else file_name

        # 提取匹配行并构建带上下文的代码片段
        content = _build_content_snippet(fm)

        record = {
            "title": title,
            "content": content,
            "score": normalized_score,
            "metadata": {
                "repo": repo,
                "path": file_name,
            },
        }

        # 提取行号信息
        matches = fm.get("Matches") or []
        if matches:
            first_match = matches[0]
            line_num = first_match.get("LineNum", 0)
            if line_num:
                record["metadata"]["start_line"] = max(1, line_num - DEFAULT_CONTEXT_LINES)
                record["metadata"]["end_line"] = line_num + DEFAULT_CONTEXT_LINES

        records.append(record)

        if len(records) >= top_k:
            break

    return records


def _build_content_snippet(file_match: dict[str, Any]) -> str:
    """
    从 Zoekt 文件匹配结果中提取代码片段。

    实际 Zoekt JSON 结构:
    {
      "Matches": [
        {
          "LineNum": 42,
          "Fragments": [
            {"Pre": "code before ", "Match": "keyword", "Post": " code after"}
          ]
        }
      ]
    }
    """
    lines_output = []

    matches = file_match.get("Matches") or []
    for m in matches:
        line_num = m.get("LineNum", 0)
        fragments = m.get("Fragments") or []

        # 拼接行内容：Pre + Match + Post
        line_parts = []
        for frag in fragments:
            pre = frag.get("Pre", "")
            match = frag.get("Match", "")
            post = frag.get("Post", "")
            line_parts.append(f"{pre}{match}{post}")

        line_content = "".join(line_parts).strip()
        if line_content:
            prefix = f"L{line_num}: " if line_num else ""
            lines_output.append(f"{prefix}{line_content}")

    if not lines_output:
        return "(no content preview available)"

    return "\n".join(lines_output)

