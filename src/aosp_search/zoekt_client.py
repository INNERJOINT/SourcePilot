"""
Zoekt 搜索客户端

封装 Zoekt webserver 的 JSON API，将搜索结果转换为 Dify 外部知识库所需的 records 格式。
"""

import logging
from typing import Any

import httpx

from config import ZOEKT_URL, DEFAULT_CONTEXT_LINES, USE_BM25_SCORING, NUM_CONTEXT_LINES

logger = logging.getLogger(__name__)


async def search(
    query: str,
    top_k: int = 5,
    score_threshold: float = 0.0,
    repos: str | None = None,
    lang: str | None = None,
    branch: str | None = None,
    case_sensitive: str = "auto",
) -> list[dict[str, Any]]:
    """
    调用 Zoekt 搜索接口，返回 Dify 标准 records 列表。

    Args:
        query: 搜索查询字符串
        top_k: 返回结果数量
        score_threshold: 分数阈值
        repos: 可选，repo 名称过滤（如 frameworks/base）
        lang: 可选，编程语言过滤（如 java, python）
        branch: 可选，分支过滤（如 main）
        case_sensitive: 大小写敏感模式：auto/yes/no
    """
    import json

    # 构造 Zoekt 查询字符串
    zoekt_query = query
    if repos:
        zoekt_query = f"r:{repos} {zoekt_query}"
    if lang:
        zoekt_query = f"lang:{lang} {zoekt_query}"
    if branch:
        zoekt_query = f"branch:{branch} {zoekt_query}"
    if case_sensitive and case_sensitive != "auto":
        zoekt_query = f"case:{case_sensitive} {zoekt_query}"

    params = {
        "q": zoekt_query,
        "num": top_k * 3,
        "format": "json",
    }

    # 上下文行数
    if NUM_CONTEXT_LINES > 0:
        params["ctx"] = NUM_CONTEXT_LINES

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # 尝试 /search?format=json（兼容大多数 zoekt-webserver 版本）
            resp = await client.get(f"{ZOEKT_URL}/search", params=params)

            # Zoekt 对无结果的查询返回 418 "I'm a teapot"
            if resp.status_code == 418:
                logger.info("Zoekt returned 418 (no results) for query: %s", params.get("q"))
                return []

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


async def search_regex(
    pattern: str,
    top_k: int = 10,
    score_threshold: float = 0.0,
    repos: str | None = None,
    lang: str | None = None,
) -> list[dict[str, Any]]:
    """
    使用正则表达式搜索代码。

    Args:
        pattern: 正则表达式模式
        top_k: 返回结果数量
        score_threshold: 分数阈值
        repos: 可选，repo 过滤
        lang: 可选，语言过滤
    """
    # 使用 content:/regex/ 语法
    query = f"content:/{pattern}/"
    return await search(
        query=query,
        top_k=top_k,
        score_threshold=score_threshold,
        repos=repos,
        lang=lang,
    )


async def list_repos(
    query: str = "",
    top_k: int = 50,
) -> list[dict[str, Any]]:
    """
    列出匹配的仓库列表。

    Args:
        query: 可选，仓库名过滤关键词
        top_k: 返回仓库数量上限
    """
    import json

    # 使用 type:repo 查询
    zoekt_query = "type:repo"
    if query:
        zoekt_query = f"type:repo r:{query}"

    params = {
        "q": zoekt_query,
        "num": top_k,
        "format": "json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{ZOEKT_URL}/search", params=params)

            if resp.status_code == 418:
                return []

            resp.raise_for_status()
            raw_text = resp.text

            if raw_text.strip().startswith("<"):
                raise ValueError("Zoekt does not support JSON output on /search endpoint")

            data = json.loads(raw_text)

    except httpx.HTTPStatusError as e:
        logger.error("Zoekt API HTTP error: %s", e)
        raise
    except httpx.RequestError as e:
        logger.error("Zoekt API request error: %s", e)
        raise

    return _extract_repos(data, top_k)


def _extract_repos(data: dict[str, Any], top_k: int) -> list[dict[str, Any]]:
    """从 Zoekt 响应中提取仓库列表。"""
    repos = []

    result = data.get("Result") or data.get("result") or data
    if isinstance(result, dict):
        inner = result.get("Result") or result.get("result")
        if isinstance(inner, dict):
            result = inner

    # 尝试从 RepoURLs 或 Repos 字段提取
    repo_urls = result.get("RepoURLs") or {}
    if repo_urls:
        for repo_name, url in repo_urls.items():
            repos.append({"name": repo_name, "url": url})
            if len(repos) >= top_k:
                break
        return repos

    # 降级：从 FileMatches 中提取去重的 repo 名
    file_matches = (
        result.get("FileMatches") or result.get("fileMatches") or
        result.get("Files") or result.get("files") or []
    )
    seen = set()
    for fm in file_matches:
        repo = fm.get("Repo", "")
        if repo and repo not in seen:
            seen.add(repo)
            repos.append({"name": repo, "url": ""})
            if len(repos) >= top_k:
                break

    return repos


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
        # 优先使用 Zoekt 的 Score 字段（启用 BM25 时有意义）
        raw_score = fm.get("Score", 0)
        if raw_score and raw_score > 0:
            # 将 Zoekt 原始分数归一化到 0~1 区间
            # BM25 分数通常在 0~50 范围，使用 sigmoid 映射
            import math
            normalized_score = round(1.0 / (1.0 + math.exp(-0.1 * (raw_score - 10))), 4)
        else:
            # 无 Score 字段，按排名递减分配分数 (1.0 → 0.x)
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


async def fetch_file_content(
    repo: str,
    filepath: str,
    start_line: int = 1,
    end_line: int | None = None,
) -> dict:
    """
    从 Zoekt /print 端点获取文件完整内容。

    Args:
        repo: 仓库名（如 'frameworks/base'）
        filepath: 文件路径（如 'core/java/android/os/Process.java'）
        start_line: 起始行（从 1 开始，默认 1）
        end_line: 结束行（默认读取全部）

    Returns:
        dict with keys: content, total_lines, repo, filepath, start_line, end_line
    """
    import re
    import html as html_module

    params = {"r": repo, "f": filepath}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{ZOEKT_URL}/print", params=params)

            if resp.status_code == 418:
                raise FileNotFoundError(
                    f"文件未找到: repo={repo!r}, filepath={filepath!r}。"
                    "请用 search_file 工具确认正确的 repo 和文件路径。"
                )
            resp.raise_for_status()
            html_text = resp.text

    except httpx.HTTPStatusError as e:
        logger.error("Zoekt /print HTTP error: %s", e)
        raise
    except httpx.RequestError as e:
        logger.error("Zoekt /print request error: %s", e)
        raise

    # 从所有 <pre> 标签提取文件内容：Zoekt 每行渲染为独立的 <pre> 标签
    # 每个 pre 内格式: <span class="noselect"><a href="#lN">N</a>: </span>CODE...
    all_pres = re.findall(r"<pre[^>]*>(.*?)</pre>", html_text, re.DOTALL)
    if not all_pres:
        raise ValueError(
            f"无法解析 Zoekt 响应，未找到 <pre> 标签: repo={repo!r}, filepath={filepath!r}"
        )

    # 解析每个 pre 块：去除行号 span，提取纯代码文本
    all_lines = []
    for pre in all_pres:
        # 去除行号导航 span: <span class="noselect">...</span>
        code = re.sub(
            r'<span[^>]*class="noselect"[^>]*>.*?</span>',
            "",
            pre,
            flags=re.DOTALL,
        )
        # 去除所有其他 HTML 标签（高亮 span 等）
        code = re.sub(r"<[^>]+>", "", code)
        # 反转义 HTML 实体（&lt; &amp; 等）
        code = html_module.unescape(code)
        all_lines.append(code)

    total_lines = len(all_lines)

    # 应用行范围
    s = max(1, start_line) - 1          # 转为 0-indexed
    e = end_line if end_line else total_lines
    e = min(e, total_lines)

    selected = all_lines[s:e]

    # 添加行号前缀（方便 AI 阅读）
    numbered_lines = [
        f"L{s + i + 1}: {line}"
        for i, line in enumerate(selected)
    ]

    return {
        "content": "\n".join(numbered_lines),
        "total_lines": total_lines,
        "repo": repo,
        "filepath": filepath,
        "start_line": s + 1,
        "end_line": s + len(selected),
    }
