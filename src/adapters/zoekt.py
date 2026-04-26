"""
ZoektAdapter — Zoekt 搜索引擎适配器

封装 Zoekt webserver 的 JSON API，实现 SearchAdapter 接口。
将搜索结果转换为标准 records 格式。
"""

import html as html_module
import json
import logging
import math
import re
from typing import Any

import httpx

from adapters.base import SearchAdapter, BackendQuery, BackendResponse, ContentType
from config import ZOEKT_URL, DEFAULT_CONTEXT_LINES, USE_BM25_SCORING, NUM_CONTEXT_LINES

logger = logging.getLogger(__name__)


class ZoektAdapter(SearchAdapter):
    """Zoekt 搜索引擎适配器"""

    def __init__(self, zoekt_url: str = ZOEKT_URL, timeout: float = 30.0):
        self._zoekt_url = zoekt_url
        self._timeout = timeout

    @property
    def backend_name(self) -> str:
        return "zoekt"

    @property
    def supported_content_types(self) -> list[ContentType]:
        return [ContentType.CODE, ContentType.CONFIG]

    async def search(self, query: BackendQuery) -> BackendResponse:
        """实现 SearchAdapter.search — 统一接口搜索"""
        import time
        start = time.perf_counter()
        try:
            results = await self.search_zoekt(
                query=query.raw_query,
                top_k=query.options.max_results,
            )
            latency = round((time.perf_counter() - start) * 1000, 1)
            return BackendResponse(
                backend=self.backend_name,
                status="ok",
                latency_ms=latency,
                total_hits=len(results),
                items=[],  # raw dict results for now
            )
        except Exception as e:
            latency = round((time.perf_counter() - start) * 1000, 1)
            return BackendResponse(
                backend=self.backend_name,
                status="error",
                latency_ms=latency,
                total_hits=0,
                error_detail=str(e),
            )

    async def get_content(self, item_id: str) -> dict:
        """实现 SearchAdapter.get_content — 获取文件内容"""
        # item_id format: "zoekt:repo/filepath"
        if item_id.startswith("zoekt:"):
            item_id = item_id[6:]
        parts = item_id.split("/", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid item_id format: {item_id}")
        return await self.fetch_file_content(repo=parts[0], filepath=parts[1])

    async def health_check(self) -> bool:
        """实现 SearchAdapter.health_check"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._zoekt_url}/")
                return resp.status_code == 200
        except Exception:
            return False

    # ─── Public methods (called via shim and gateway) ─────────────

    async def search_zoekt(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.0,
        repos: str | None = None,
        lang: str | None = None,
        branch: str | None = None,
        case_sensitive: str = "auto",
    ) -> list[dict[str, Any]]:
        """
        调用 Zoekt 搜索接口，返回标准 records 列表。

        Args:
            query: 搜索查询字符串
            top_k: 返回结果数量
            score_threshold: 分数阈值
            repos: 可选，repo 名称过滤（如 frameworks/base）
            lang: 可选，编程语言过滤（如 java, python）
            branch: 可选，分支过滤（如 main）
            case_sensitive: 大小写敏感模式：auto/yes/no
        """
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
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{self._zoekt_url}/search", params=params)

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

        return self._convert_results(data, top_k, score_threshold)

    async def search_regex(
        self,
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
        query = f"content:/{pattern}/"
        return await self.search_zoekt(
            query=query,
            top_k=top_k,
            score_threshold=score_threshold,
            repos=repos,
            lang=lang,
        )

    async def list_repos(
        self,
        query: str = "",
        top_k: int = 50,
    ) -> list[dict[str, Any]]:
        """
        列出匹配的仓库列表。

        Args:
            query: 可选，仓库名过滤关键词
            top_k: 返回仓库数量上限
        """
        zoekt_query = "type:repo"
        if query:
            zoekt_query = f"type:repo r:{query}"

        params = {
            "q": zoekt_query,
            "num": top_k,
            "format": "json",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{self._zoekt_url}/search", params=params)

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

        return self._extract_repos(data, top_k)

    async def fetch_file_content(
        self,
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
        # Anchor repo regex to avoid matching multiple repos with a common prefix
        # (e.g. "NetworkStack" otherwise also matches "NetworkStackNext"), which
        # makes Zoekt return 418 "ambiguous result".
        params = {"r": f"^{re.escape(repo)}$", "f": filepath}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{self._zoekt_url}/print", params=params)

                if resp.status_code == 418:
                    body = (resp.text or "").strip()
                    if body.startswith("ambiguous result"):
                        raise ValueError(
                            f"Zoekt 返回歧义结果: repo={repo!r}, filepath={filepath!r}。"
                            f"原始响应: {body[:200]}"
                        )
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

        # 从所有 <pre> 标签提取文件内容
        all_pres = re.findall(r"<pre[^>]*>(.*?)</pre>", html_text, re.DOTALL)
        if not all_pres:
            raise ValueError(
                f"无法解析 Zoekt 响应，未找到 <pre> 标签: repo={repo!r}, filepath={filepath!r}"
            )

        all_lines = []
        for pre in all_pres:
            code = re.sub(
                r'<span[^>]*class="noselect"[^>]*>.*?</span>',
                "",
                pre,
                flags=re.DOTALL,
            )
            code = re.sub(r"<[^>]+>", "", code)
            code = html_module.unescape(code)
            all_lines.append(code)

        total_lines = len(all_lines)

        s = max(1, start_line) - 1
        e = end_line if end_line else total_lines
        e = min(e, total_lines)

        selected = all_lines[s:e]

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

    # ─── Private helpers ──────────────────────────────────────

    def _extract_repos(self, data: dict[str, Any], top_k: int) -> list[dict[str, Any]]:
        """从 Zoekt 响应中提取仓库列表。"""
        repos = []

        result = data.get("Result") or data.get("result") or data
        if isinstance(result, dict):
            inner = result.get("Result") or result.get("result")
            if isinstance(inner, dict):
                result = inner

        repo_urls = result.get("RepoURLs") or {}
        if repo_urls:
            for repo_name, url in repo_urls.items():
                repos.append({"name": repo_name, "url": url})
                if len(repos) >= top_k:
                    break
            return repos

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
        self,
        data: dict[str, Any],
        top_k: int,
        score_threshold: float,
    ) -> list[dict[str, Any]]:
        """将 Zoekt 原始 JSON 响应转换为标准 records 格式。"""
        records = []

        result = data.get("Result") or data.get("result") or data
        if isinstance(result, dict):
            inner = result.get("Result") or result.get("result")
            if isinstance(inner, dict):
                result = inner

        file_matches = (
            result.get("FileMatches") or result.get("fileMatches") or
            result.get("Files") or result.get("files") or []
        )

        if not file_matches:
            logger.info("Zoekt returned 0 file matches")
            return records

        total = len(file_matches)

        for idx, fm in enumerate(file_matches):
            raw_score = fm.get("Score", 0)
            if raw_score and raw_score > 0:
                normalized_score = round(1.0 / (1.0 + math.exp(-0.1 * (raw_score - 10))), 4)
            else:
                normalized_score = round(1.0 - (idx / max(total, 1)) * 0.5, 4)

            if normalized_score < score_threshold:
                continue

            repo = fm.get("Repo", "")
            file_name = fm.get("FileName", "")
            title = f"{repo}/{file_name}" if repo else file_name

            content = self._build_content_snippet(fm)

            record = {
                "title": title,
                "content": content,
                "score": normalized_score,
                "metadata": {
                    "repo": repo,
                    "path": file_name,
                },
            }

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

    def _build_content_snippet(self, file_match: dict[str, Any]) -> str:
        """从 Zoekt 文件匹配结果中提取代码片段。"""
        lines_output = []

        matches = file_match.get("Matches") or []
        for m in matches:
            line_num = m.get("LineNum", 0)
            fragments = m.get("Fragments") or []

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
