"""Tests for DenseAdapter."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from adapters.dense import DenseAdapter
from adapters.base import BackendQuery, QueryOptions


@pytest.fixture
def mock_qdrant_client():
    client = MagicMock()
    client.collection_exists.return_value = True
    point1 = MagicMock()
    point1.id = "1"
    point1.score = 0.92
    point1.payload = {
        "repo": "frameworks/base",
        "path": "core/java/android/app/Activity.java",
        "start_line": 1,
        "end_line": 100,
        "content": "public class Activity extends ...",
        "language": "java",
    }
    point2 = MagicMock()
    point2.id = "2"
    point2.score = 0.85
    point2.payload = {
        "repo": "frameworks/base",
        "path": "services/core/java/com/android/server/am/ActivityManagerService.java",
        "start_line": 50,
        "end_line": 150,
        "content": "public class ActivityManagerService ...",
        "language": "java",
    }
    result = MagicMock()
    result.points = [point1, point2]
    client.query_points.return_value = result
    return client


@pytest.fixture
def adapter(mock_qdrant_client):
    a = DenseAdapter(
        vector_db_url="http://localhost:6333",
        embedding_url="http://localhost:8080/v1",
        collection_name="aosp_code",
    )
    a._qdrant_client = mock_qdrant_client
    return a


class TestDenseAdapterProperties:
    def test_backend_name(self, adapter):
        assert adapter.backend_name == "dense"

    def test_supported_content_types(self, adapter):
        from adapters.base import ContentType
        assert ContentType.CODE in adapter.supported_content_types


class TestSearchByEmbedding:
    @pytest.mark.asyncio
    async def test_basic_search(self, adapter, mock_qdrant_client):
        with patch.object(adapter._embedding_client, "embed_query", new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = [0.1] * 768
            results = await adapter.search_by_embedding("Activity lifecycle", top_k=5)

        assert len(results) == 2
        assert results[0]["score"] == 0.92
        assert results[0]["metadata"]["repo"] == "frameworks/base"
        assert results[0]["metadata"]["path"] == "core/java/android/app/Activity.java"
        mock_qdrant_client.query_points.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_with_repo_filter(self, adapter):
        mock_models = MagicMock()
        mock_filter = MagicMock()
        mock_models.Filter.return_value = mock_filter
        with patch.object(adapter._embedding_client, "embed_query", new_callable=AsyncMock) as mock_embed, \
                patch.dict("sys.modules", {"qdrant_client": MagicMock(), "qdrant_client.models": mock_models}):
            mock_embed.return_value = [0.1] * 768
            await adapter.search_by_embedding("test", repos="frameworks/base")

        call_kwargs = adapter._qdrant_client.query_points.call_args
        assert call_kwargs[1]["query_filter"] is not None

    @pytest.mark.asyncio
    async def test_search_without_filter(self, adapter):
        with patch.object(adapter._embedding_client, "embed_query", new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = [0.1] * 768
            await adapter.search_by_embedding("test")

        call_kwargs = adapter._qdrant_client.query_points.call_args
        assert call_kwargs[1]["query_filter"] is None


class TestSearchABC:
    @pytest.mark.asyncio
    async def test_search_delegates_to_search_by_embedding(self, adapter):
        with patch.object(adapter, "search_by_embedding", new_callable=AsyncMock) as mock_sbe:
            mock_sbe.return_value = [{"id": "1", "score": 0.9, "metadata": {}}]
            query = BackendQuery(raw_query="test", parsed={}, options=QueryOptions(max_results=5))
            response = await adapter.search(query)

        assert response.backend == "dense"
        assert response.status == "ok"
        assert response.total_hits == 1
        mock_sbe.assert_awaited_once_with(query="test", top_k=5)

    @pytest.mark.asyncio
    async def test_search_error_returns_error_response(self, adapter):
        with patch.object(adapter, "search_by_embedding", new_callable=AsyncMock) as mock_sbe:
            mock_sbe.side_effect = ConnectionError("qdrant down")
            query = BackendQuery(raw_query="test", parsed={}, options=QueryOptions(max_results=5))
            response = await adapter.search(query)

        assert response.status == "error"
        assert "qdrant down" in response.error_detail


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_healthy(self, adapter):
        with patch.object(adapter._embedding_client, "embed_query", new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = [0.1] * 768
            result = await adapter.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_collection_missing(self, adapter):
        adapter._qdrant_client.collection_exists.return_value = False
        result = await adapter.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_embedding_dim_mismatch(self, adapter):
        with patch.object(adapter._embedding_client, "embed_query", new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = [0.1] * 512  # wrong dim
            result = await adapter.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_connection_error(self, adapter):
        adapter._qdrant_client.collection_exists.side_effect = ConnectionError("down")
        result = await adapter.health_check()
        assert result is False
