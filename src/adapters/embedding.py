"""EmbeddingClient — HTTP client for local code embedding models.

Compatible with OpenAI embedding API format.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """Embedding 服务 HTTP 客户端，兼容 OpenAI embedding API 格式。"""

    def __init__(self, base_url: str, model: str, timeout: float = 120.0):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量文本 embedding。

        Args:
            texts: 待 embedding 的文本列表

        Returns:
            每条文本对应的向量列表
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
        """单条查询 embedding（便捷方法）。"""
        results = await self.embed([query])
        return results[0]
