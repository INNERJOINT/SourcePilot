"""
ZoektAdapter — Zoekt search engine adapter

Wraps the Zoekt webserver JSON API, implementing the SearchAdapter interface.
Converts search results into the standard records format.
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
    """Zoekt search engine adapter."""

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
        """Implement SearchAdapter.search — unified interface search."""
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
        """Implement SearchAdapter.get_content — fetch file content."""
        # item_id format: "zoekt:repo/filepath"
        if item_id.startswith("zoekt:"):
            item_id = item_id[6:]
        parts = item_id.split("/", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid item_id format: {item_id}")
        return await self.fetch_file_content(repo=parts[0], filepath=parts[1])

    async def health_check(self) -> bool:
        """Implement SearchAdapter.health_check."""
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
        Call the Zoekt search endpoint and return a standard records list.

        Args:
            query: Search query string.
            top_k: Number of results to return.
            score_threshold: Minimum score threshold.
            repos: Optional repo name filter (e.g. frameworks/base).
            lang: Optional programming language filter (e.g. java, python).
            branch: Optional branch filter (e.g. main).
            case_sensitive: Case-sensitivity mode: auto/yes/no.
        """
        # Build the Zoekt query string
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

        # Number of context lines
        if NUM_CONTEXT_LINES > 0:
            params["ctx"] = NUM_CONTEXT_LINES

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{self._zoekt_url}/search", params=params)

                # Zoekt returns 418 "I'm a teapot" for queries with no results
                if resp.status_code == 418:
                    logger.info("Zoekt returned 418 (no results) for query: %s", params.get("q"))
                    return []

                resp.raise_for_status()

                raw_text = resp.text
                logger.debug("Zoekt raw response (first 500 chars): %s", raw_text[:500])

                # Detect if HTML was returned (indicates format=json is not supported)
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
        Search code using a regular expression.

        Args:
            pattern: Regular expression pattern.
            top_k: Number of results to return.
            score_threshold: Minimum score threshold.
            repos: Optional repo filter.
            lang: Optional language filter.
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
        List matching repositories.

        Args:
            query: Optional keyword to filter repository names.
            top_k: Maximum number of repositories to return.
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
        Fetch the full content of a file from the Zoekt /print endpoint.

        Args:
            repo: Repository name (e.g. 'frameworks/base').
            filepath: File path (e.g. 'core/java/android/os/Process.java').
            start_line: First line to return (1-indexed, default 1).
            end_line: Last line to return (default: read all).

        Returns:
            dict with keys: content, total_lines, repo, filepath, start_line, end_line.
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
                            f"Zoekt returned ambiguous result: repo={repo!r}, filepath={filepath!r}. "
                            f"Raw response: {body[:200]}"
                        )
                    raise FileNotFoundError(
                        f"File not found: repo={repo!r}, filepath={filepath!r}. "
                        "Use the search_file tool to confirm the correct repo and file path."
                    )
                resp.raise_for_status()
                html_text = resp.text

        except httpx.HTTPStatusError as e:
            logger.error("Zoekt /print HTTP error: %s", e)
            raise
        except httpx.RequestError as e:
            logger.error("Zoekt /print request error: %s", e)
            raise

        # Extract file content from all <pre> tags
        all_pres = re.findall(r"<pre[^>]*>(.*?)</pre>", html_text, re.DOTALL)
        if not all_pres:
            raise ValueError(
                f"Failed to parse Zoekt response — no <pre> tags found: repo={repo!r}, filepath={filepath!r}"
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
        """Extract the repository list from a Zoekt response."""
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
        """Convert raw Zoekt JSON response into the standard records format."""
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
        """Extract a code snippet from a Zoekt file match result."""
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
