"""Dense (Milvus) backend integrator.

NO pymilvus import here — heavy ops run inside the dense-indexer container.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Optional

from .base import IndexingBackend, BackendError

_COMPOSE_FILE = "dense-deploy/docker-compose.yml"
_SERVICE = "dense-indexer"


class DenseBackend(IndexingBackend):

    def trigger(self, repo_path: str, log_path: str, job_id: int) -> subprocess.Popen:
        return subprocess.Popen(
            ["bash", "scripts/build_dense_index_batch.sh", repo_path],
            stdout=open(log_path, "w"),
            stderr=subprocess.STDOUT,
            env={**os.environ, "INDEXING_JOB_ID": str(job_id)},
        )

    def hard_delete(self, repo_path: str) -> None:
        try:
            subprocess.run(
                [
                    "docker", "compose",
                    "--profile", "indexer",
                    "-f", _COMPOSE_FILE,
                    "run", "--rm", _SERVICE,
                    "python", "/app/scripts/dense_drop.py", repo_path,
                ],
                check=True,
                timeout=300,
            )
        except subprocess.CalledProcessError as exc:
            raise BackendError(f"dense hard_delete failed (exit {exc.returncode})") from exc

    def collect_entity_count(self, repo_path: str) -> Optional[int]:
        try:
            result = subprocess.run(
                [
                    "docker", "compose",
                    "--profile", "indexer",
                    "-f", _COMPOSE_FILE,
                    "run", "--rm", _SERVICE,
                    "python", "/app/scripts/dense_count.py", repo_path,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            data = json.loads(result.stdout.strip())
            return int(data["count"])
        except Exception:
            return None


_backend = DenseBackend()

trigger = _backend.trigger
hard_delete = _backend.hard_delete
collect_entity_count = _backend.collect_entity_count
