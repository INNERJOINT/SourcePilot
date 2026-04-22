"""Zoekt backend integrator."""
from __future__ import annotations

import os
import subprocess
from typing import Optional

import httpx

from audit_viewer import config
from .base import IndexingBackend, BackendError

_ZOEKT_URL = os.getenv("ZOEKT_URL", "http://localhost:6070")


class ZoektBackend(IndexingBackend):

    def trigger(self, repo_path: str, log_path: str, job_id: int) -> subprocess.Popen:
        return subprocess.Popen(
            ["bash", "scripts/reindex.sh", repo_path],
            stdout=open(log_path, "w"),
            stderr=subprocess.STDOUT,
            env={**os.environ, "INDEXING_JOB_ID": str(job_id)},
        )

    def hard_delete(self, repo_path: str) -> None:
        """Call /api/list_repos to resolve shard path; raises NotImplementedError if mapping unavailable."""
        try:
            resp = httpx.get(f"{_ZOEKT_URL}/api/list_repos", timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise BackendError(f"Failed to contact Zoekt: {exc}") from exc

        # Look for the repo in the response and attempt to resolve shard path.
        # Zoekt /api/list_repos returns {"List": {"Repos": [{"Repository": {"Name": ..., "Source": ...}, ...}]}}
        repos = []
        try:
            repos = data.get("List", {}).get("Repos", [])
        except AttributeError:
            pass

        shard_path: Optional[str] = None
        for entry in repos:
            repo_info = entry.get("Repository", {})
            name = repo_info.get("Name", "")
            # Zoekt uses repo name (last component of path) for matching
            if name == repo_path or repo_info.get("Source", "") == repo_path:
                # Check if response contains IndexMetadata with shard file info
                index_meta = entry.get("IndexMetadata", {})
                shard_file = index_meta.get("IndexTime", None)  # not the shard path
                # Zoekt does not expose shard file paths via /api/list_repos
                # We can confirm the repo exists but cannot derive the shard file path
                shard_path = None  # intentionally cannot resolve
                break

        raise NotImplementedError(
            "Zoekt shard mapping not available; use scripts/zoekt_delete_shard.sh"
        )

    def collect_entity_count(self, repo_path: str) -> Optional[int]:
        try:
            resp = httpx.get(
                f"{_ZOEKT_URL}/search",
                params={"q": f"r:{repo_path} type:repo", "format": "json"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            repos = data.get("List", {}).get("Repos", [])
            return len(repos)
        except Exception:
            return None


# Module-level singleton
_backend = ZoektBackend()

trigger = _backend.trigger
hard_delete = _backend.hard_delete
collect_entity_count = _backend.collect_entity_count
