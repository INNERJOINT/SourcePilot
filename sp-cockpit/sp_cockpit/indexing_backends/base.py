"""Abstract base class for indexing backends."""
from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from typing import Optional


class BackendError(Exception):
    """Raised when a backend operation fails."""


class IndexingBackend(ABC):
    """ABC for all indexing backend integrators."""

    @abstractmethod
    def trigger(self, repo_path: str, log_path: str, job_id: int) -> subprocess.Popen:
        """Start an indexing job; return the Popen handle."""

    @abstractmethod
    def hard_delete(self, repo_path: str) -> None:
        """Delete all indexed data for repo_path.

        Raises NotImplementedError if the operation is not supported, or
        BackendError on failure.
        """

    @abstractmethod
    def collect_entity_count(self, repo_path: str) -> Optional[int]:
        """Return the number of indexed entities for repo_path, or None on error."""
