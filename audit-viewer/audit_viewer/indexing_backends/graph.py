"""Graph (Neo4j) backend integrator.

NO neo4j driver import here — heavy ops run inside the graph-indexer container.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Optional

from .base import IndexingBackend, BackendError

_COMPOSE_FILE = "graph-deploy/docker-compose.yml"
_SERVICE = "graph-indexer"


class GraphBackend(IndexingBackend):

    def trigger(self, repo_path: str, log_path: str, job_id: int) -> subprocess.Popen:
        return subprocess.Popen(
            ["bash", "scripts/build_graph_index.sh", repo_path],
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
                    "python", "/app/scripts/graph_drop.py", repo_path,
                ],
                check=True,
                timeout=300,
            )
        except subprocess.CalledProcessError as exc:
            raise BackendError(f"graph hard_delete failed (exit {exc.returncode})") from exc

    def collect_entity_count(self, repo_path: str) -> Optional[int]:
        try:
            result = subprocess.run(
                [
                    "docker", "compose",
                    "--profile", "indexer",
                    "-f", _COMPOSE_FILE,
                    "run", "--rm", _SERVICE,
                    "python", "/app/scripts/graph_count.py", repo_path,
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


_backend = GraphBackend()

trigger = _backend.trigger
hard_delete = _backend.hard_delete
collect_entity_count = _backend.collect_entity_count
