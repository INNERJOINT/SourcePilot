"""Tests for audit_viewer.indexing_backends."""
from __future__ import annotations

import importlib
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
import respx
import httpx


# ---------------------------------------------------------------------------
# Zoekt
# ---------------------------------------------------------------------------

class TestZoektHardDelete:

    def test_zoekt_hard_delete_raises_not_implemented_when_shard_missing(self):
        """hard_delete always raises NotImplementedError because /api/list_repos
        does not expose shard file paths."""
        from audit_viewer.indexing_backends import zoekt

        list_repos_response = {
            "List": {
                "Repos": [
                    {
                        "Repository": {
                            "Name": "frameworks/base",
                            "Source": "frameworks/base",
                        },
                        "IndexMetadata": {},
                    }
                ]
            }
        }

        with respx.mock(base_url="http://localhost:6070") as mock:
            mock.get("/api/list_repos").mock(
                return_value=httpx.Response(200, json=list_repos_response)
            )
            with pytest.raises(NotImplementedError, match="zoekt_delete_shard.sh"):
                zoekt.hard_delete("frameworks/base")

    def test_zoekt_hard_delete_raises_backend_error_on_http_failure(self):
        from audit_viewer.indexing_backends import zoekt
        from audit_viewer.indexing_backends.base import BackendError

        with respx.mock(base_url="http://localhost:6070") as mock:
            mock.get("/api/list_repos").mock(
                return_value=httpx.Response(500, text="internal error")
            )
            with pytest.raises((NotImplementedError, BackendError)):
                zoekt.hard_delete("frameworks/base")


# ---------------------------------------------------------------------------
# Dense
# ---------------------------------------------------------------------------

class TestDenseHardDelete:

    def test_dense_hard_delete_calls_docker_compose(self):
        from audit_viewer.indexing_backends import dense

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            dense.hard_delete("frameworks/base")

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args[0][0]

        assert "docker" in cmd
        assert "compose" in cmd
        assert "--profile" in cmd
        assert "indexer" in cmd
        assert "dense-indexer" in cmd
        assert any("dense_drop" in str(c) for c in cmd)
        assert "frameworks/base" in cmd

    def test_dense_hard_delete_raises_on_failure(self):
        from audit_viewer.indexing_backends import dense
        from audit_viewer.indexing_backends.base import BackendError

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "docker")
            with pytest.raises(BackendError):
                dense.hard_delete("frameworks/base")

    def test_dense_collect_entity_count_returns_int(self):
        from audit_viewer.indexing_backends import dense

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='{"count": 42}\n')
            count = dense.collect_entity_count("frameworks/base")

        assert count == 42

    def test_dense_collect_entity_count_returns_none_on_error(self):
        from audit_viewer.indexing_backends import dense

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = Exception("docker not found")
            count = dense.collect_entity_count("frameworks/base")

        assert count is None


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

class TestGraphHardDelete:

    def test_graph_hard_delete_calls_docker_compose(self):
        from audit_viewer.indexing_backends import graph

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            graph.hard_delete("frameworks/base")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]

        assert "docker" in cmd
        assert "compose" in cmd
        assert "--profile" in cmd
        assert "indexer" in cmd
        assert "graph-indexer" in cmd
        assert any("graph_drop" in str(c) for c in cmd)
        assert "frameworks/base" in cmd

    def test_graph_hard_delete_raises_on_failure(self):
        from audit_viewer.indexing_backends import graph
        from audit_viewer.indexing_backends.base import BackendError

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "docker")
            with pytest.raises(BackendError):
                graph.hard_delete("frameworks/base")

    def test_graph_collect_entity_count_returns_int(self):
        from audit_viewer.indexing_backends import graph

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='{"count": 99}\n')
            count = graph.collect_entity_count("frameworks/base")

        assert count == 99


# ---------------------------------------------------------------------------
# No pymilvus / neo4j imports at module level in audit-viewer
# ---------------------------------------------------------------------------

class TestNoPymilvusNeo4jImports:

    def test_pymilvus_neo4j_not_imported_at_module_level(self):
        """Verify that pymilvus and neo4j are NOT imported by any audit_viewer module."""
        # Import all backend modules to trigger their top-level imports
        import audit_viewer.indexing_backends.dense  # noqa
        import audit_viewer.indexing_backends.graph  # noqa
        import audit_viewer.indexing_backends.zoekt  # noqa
        import audit_viewer.indexing_backends  # noqa

        # Check sys.modules for the forbidden packages
        forbidden = {"pymilvus", "neo4j"}
        loaded = {k.split(".")[0] for k in sys.modules}
        bad = forbidden & loaded
        assert not bad, (
            f"Forbidden packages found in sys.modules after importing audit_viewer.indexing_backends: {bad}"
        )
