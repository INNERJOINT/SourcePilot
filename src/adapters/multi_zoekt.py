import asyncio
import itertools
import logging
from typing import Any

from adapters.zoekt import ZoektAdapter

logger = logging.getLogger(__name__)


class MultiZoektAdapter:
    """Fan-out to N ZoektAdapters, merge results as transparent union."""

    def __init__(self, adapters: dict[str, ZoektAdapter], dedup_by_filepath: bool = False):
        self._adapters = adapters
        self._dedup = dedup_by_filepath

    async def search_zoekt(self, **kwargs) -> list[dict[str, Any]]:
        tasks = [a.search_zoekt(**kwargs) for a in self._adapters.values()]
        results = await asyncio.gather(*tasks)
        merged = list(itertools.chain.from_iterable(results))
        return self._maybe_dedup(merged)

    async def search_regex(self, **kwargs) -> list[dict[str, Any]]:
        tasks = [a.search_regex(**kwargs) for a in self._adapters.values()]
        results = await asyncio.gather(*tasks)
        merged = list(itertools.chain.from_iterable(results))
        return self._maybe_dedup(merged)

    async def list_repos(self, **kwargs) -> list[dict[str, Any]]:
        tasks = [a.list_repos(**kwargs) for a in self._adapters.values()]
        results = await asyncio.gather(*tasks)
        merged = list(itertools.chain.from_iterable(results))
        seen = set()
        unique = []
        for r in merged:
            if r["name"] not in seen:
                seen.add(r["name"])
                unique.append(r)
        return unique

    async def fetch_file_content(self, repo: str, filepath: str, **kwargs) -> dict:
        errors = []
        for label, adapter in self._adapters.items():
            try:
                return await adapter.fetch_file_content(repo=repo, filepath=filepath, **kwargs)
            except (FileNotFoundError, ValueError):
                errors.append(label)
                continue
        raise FileNotFoundError(f"File not found in any sub-container: {repo}/{filepath}")

    async def health_check(self) -> dict[str, bool]:
        results = {}
        for label, adapter in self._adapters.items():
            results[label] = await adapter.health_check()
        return results

    def _maybe_dedup(self, records: list[dict]) -> list[dict]:
        if not self._dedup:
            return records
        seen: dict[tuple, dict] = {}
        for r in records:
            meta = r.get("metadata", {})
            key = (meta.get("repo", ""), meta.get("path", ""))
            if key not in seen or r.get("score", 0) > seen[key].get("score", 0):
                seen[key] = r
        return list(seen.values())
