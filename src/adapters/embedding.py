"""EmbeddingClient — HTTP client for local code embedding models.

Compatible with OpenAI embedding API format.
"""

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """HTTP client for the embedding service, compatible with the OpenAI embedding API format."""

    def __init__(self, base_url: str, model: str, timeout: float = 120.0):
        self._base_url = base_url.rstrip("/")
        self._model = model
        max_conns = int(os.environ.get("EMBEDDING_MAX_CONNECTIONS", "64"))
        max_keepalive = int(os.environ.get("EMBEDDING_MAX_KEEPALIVE", "32"))
        self._client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(
                max_connections=max_conns, max_keepalive_connections=max_keepalive
            ),
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Batch text embedding.

        Args:
            texts: List of texts to embed.

        Returns:
            List of vectors, one per input text.
        """
        payload: dict[str, Any] = {
            "input": texts,
            "model": self._model,
        }

        try:
            resp = await self._client.post(
                f"{self._base_url}/embeddings",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("Embedding API HTTP error: %s", e)
            raise
        except httpx.RequestError as e:
            logger.error("Embedding API request error: %s", e)
            raise

        # OpenAI format: {"data": [{"embedding": [...], "index": 0}, ...]}
        items = data.get("data", [])
        items.sort(key=lambda x: x.get("index", 0))
        return [item["embedding"] for item in items]

    async def embed_query(self, query: str) -> list[float]:
        """Single-query embedding (convenience method)."""
        results = await self.embed([query])
        return results[0]
