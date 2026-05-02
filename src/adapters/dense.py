"""
DenseAdapter — vector database retrieval adapter

Wraps the Qdrant vector database client and embedding calls, implementing the SearchAdapter interface.
"""

import logging
import time
from typing import Any

from adapters.base import (
    BackendQuery,
    BackendResponse,
    ContentType,
    SearchAdapter,
)
from adapters.embedding import EmbeddingClient
from config import (
    DENSE_COLLECTION_NAME,
    DENSE_EMBEDDING_DIM,
    DENSE_EMBEDDING_MODEL,
    DENSE_EMBEDDING_URL,
    DENSE_TOP_K,
    DENSE_VECTOR_DB_URL,
)

logger = logging.getLogger(__name__)


_AOSP_OUTPUT_FIELDS = ["repo", "path", "start_line", "end_line", "content", "language"]
_FEISHU_OUTPUT_FIELDS = ["title", "url", "space_id", "node_token", "content"]


class DenseAdapter(SearchAdapter):
    """Qdrant vector database retrieval adapter."""

    def __init__(
        self,
        vector_db_url: str = DENSE_VECTOR_DB_URL,
        embedding_url: str = DENSE_EMBEDDING_URL,
        collection_name: str = DENSE_COLLECTION_NAME,
        embedding_model: str = DENSE_EMBEDDING_MODEL,
        embedding_dim: int = DENSE_EMBEDDING_DIM,
        top_k: int = DENSE_TOP_K,
        output_fields: list[str] | None = None,
    ):
        self._vector_db_url = vector_db_url
        self._collection_name = collection_name
        self._embedding_dim = embedding_dim
        self._top_k = top_k
        self._output_fields = output_fields if output_fields is not None else _AOSP_OUTPUT_FIELDS
        self._embedding_client = EmbeddingClient(
            base_url=embedding_url,
            model=embedding_model,
        )
        self._qdrant_client = None

    def _get_qdrant_client(self):
        """Lazy-init Qdrant client."""
        if self._qdrant_client is None:
            from qdrant_client import QdrantClient

            self._qdrant_client = QdrantClient(url=self._vector_db_url)
        return self._qdrant_client

    @property
    def backend_name(self) -> str:
        return "dense"

    @property
    def collection_name(self) -> str:
        return self._collection_name

    @property
    def supported_content_types(self) -> list[ContentType]:
        return [ContentType.CODE]

    async def search(self, query: BackendQuery) -> BackendResponse:
        """Implement SearchAdapter.search — delegates to search_by_embedding()."""
        start = time.perf_counter()
        try:
            results = await self.search_by_embedding(
                query=query.raw_query,
                top_k=query.options.max_results,
            )
            latency = round((time.perf_counter() - start) * 1000, 1)
            return BackendResponse(
                backend=self.backend_name,
                status="ok",
                latency_ms=latency,
                total_hits=len(results),
                items=[],
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

    async def search_by_embedding(
        self,
        query: str,
        top_k: int | None = None,
        repos: str | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic vector search (called directly by the gateway).

        Args:
            query: Natural language query string.
            top_k: Number of results to return.
            repos: Optional repo name filter.

        Returns:
            list[dict], each dict containing score + metadata.
        """
        if top_k is None:
            top_k = self._top_k

        # 1. Embed the query into a vector
        query_vector = await self._embedding_client.embed_query(query)

        # 2. Build filter conditions
        query_filter = None
        if repos and "repo" in self._output_fields:
            from qdrant_client import models

            query_filter = models.Filter(
                must=[models.FieldCondition(key="repo", match=models.MatchValue(value=repos))]
            )

        # 3. Qdrant ANN search
        client = self._get_qdrant_client()
        search_results = client.query_points(
            collection_name=self._collection_name,
            query=query_vector,
            limit=top_k,
            with_payload=True,
            query_filter=query_filter,
        )

        # 4. Convert results
        hits = []
        for point in search_results.points:
            hits.append(
                {
                    "id": str(point.id),
                    "score": point.score,
                    "metadata": {field: point.payload.get(field) for field in self._output_fields},
                }
            )

        return hits

    async def get_content(self, item_id: str) -> dict:
        """Fetch full content — delegates to Zoekt for file retrieval.

        The dense index stores only chunks; full file content must be fetched from Zoekt.
        """
        raise NotImplementedError(
            "DenseAdapter.get_content() requires fetching the full file via ZoektAdapter. "
            "Use gateway.get_file_content() instead."
        )

    async def health_check(self) -> bool:
        """Check whether Qdrant and the embedding service are available."""
        try:
            client = self._get_qdrant_client()
            # Check that the collection exists
            if not client.collection_exists(self._collection_name):
                logger.warning("Qdrant collection '%s' not found", self._collection_name)
                return False
            # Check the embedding service
            test_vec = await self._embedding_client.embed_query("test")
            if len(test_vec) != self._embedding_dim:
                logger.warning(
                    "Embedding dim mismatch: expected %d, got %d",
                    self._embedding_dim,
                    len(test_vec),
                )
                return False
            return True
        except Exception as e:
            logger.warning("Dense health check failed: %s", e)
            return False
