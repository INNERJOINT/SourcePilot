"""
DenseAdapter — 向量数据库检索适配器

封装 Milvus 向量数据库客户端和 embedding 调用，实现 SearchAdapter 接口。
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


class DenseAdapter(SearchAdapter):
    """Milvus 向量数据库检索适配器"""

    def __init__(
        self,
        vector_db_url: str = DENSE_VECTOR_DB_URL,
        embedding_url: str = DENSE_EMBEDDING_URL,
        collection_name: str = DENSE_COLLECTION_NAME,
        embedding_model: str = DENSE_EMBEDDING_MODEL,
        embedding_dim: int = DENSE_EMBEDDING_DIM,
        top_k: int = DENSE_TOP_K,
    ):
        self._vector_db_url = vector_db_url
        self._collection_name = collection_name
        self._embedding_dim = embedding_dim
        self._top_k = top_k
        self._embedding_client = EmbeddingClient(
            base_url=embedding_url,
            model=embedding_model,
        )
        self._milvus_client = None

    def _get_milvus_client(self):
        """Lazy-init Milvus client."""
        if self._milvus_client is None:
            from pymilvus import MilvusClient

            self._milvus_client = MilvusClient(uri=self._vector_db_url)
        return self._milvus_client

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
        """实现 SearchAdapter.search — 委托给 search_by_embedding()"""
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
        """语义向量检索（gateway 直接调用此方法）。

        Args:
            query: 自然语言查询
            top_k: 返回结果数量
            repos: 可选，repo 名称过滤

        Returns:
            list[dict]，每个 dict 包含 score + metadata
        """
        if top_k is None:
            top_k = self._top_k

        # 1. 将查询转为向量
        query_vector = await self._embedding_client.embed_query(query)

        # 2. 构建过滤条件
        filter_expr = ""
        if repos:
            filter_expr = f'repo == "{repos}"'

        # 3. Milvus ANN 搜索
        client = self._get_milvus_client()
        search_results = client.search(
            collection_name=self._collection_name,
            data=[query_vector],
            limit=top_k,
            output_fields=["repo", "path", "start_line", "end_line", "content", "language"],
            filter=filter_expr if filter_expr else None,
        )

        # 4. 转换结果
        hits = []
        for result_list in search_results:
            for hit in result_list:
                entity = hit.get("entity", {})
                hits.append(
                    {
                        "id": str(hit.get("id", "")),
                        "score": hit.get("distance", 0.0),
                        "metadata": {
                            "repo": entity.get("repo", ""),
                            "path": entity.get("path", ""),
                            "start_line": entity.get("start_line"),
                            "end_line": entity.get("end_line"),
                            "content": entity.get("content", ""),
                            "language": entity.get("language", ""),
                        },
                    }
                )

        return hits

    async def get_content(self, item_id: str) -> dict:
        """获取完整内容 — 委托给 Zoekt 获取文件。

        Dense 索引只存 chunk，完整文件内容需要从 Zoekt 获取。
        """
        raise NotImplementedError(
            "DenseAdapter.get_content() 需要通过 ZoektAdapter 获取完整文件。"
            "请使用 gateway.get_file_content() 代替。"
        )

    async def health_check(self) -> bool:
        """检查 Milvus 和 embedding 服务是否可用"""
        try:
            client = self._get_milvus_client()
            # 检查 collection 是否存在
            collections = client.list_collections()
            if self._collection_name not in collections:
                logger.warning("Milvus collection '%s' not found", self._collection_name)
                return False
            # 检查 embedding 服务
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
