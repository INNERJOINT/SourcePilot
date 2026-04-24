"""
GraphAdapter — Neo4j 图谱检索适配器（完整实现）

封装 Neo4j 异步驱动，实现 SearchAdapter 接口。
neo4j 驱动采用懒加载，仅在实际调用时导入，避免未安装时启动失败。
"""

import logging
import time

from adapters.base import (
    BackendQuery,
    BackendResponse,
    ContentType,
    SearchAdapter,
    SearchItem,
)
from adapters.graph_traversal import (
    compute_graph_score,
    expand_neighbors,
    extract_query_entities,
    format_hit,
    fulltext_search_nodes,
)
from config import (
    GRAPH_LANE_TIMEOUT_MS,
    GRAPH_NEO4J_PASSWORD,
    GRAPH_NEO4J_URI,
    GRAPH_NEO4J_USER,
)

logger = logging.getLogger(__name__)


class GraphAdapter(SearchAdapter):
    """Neo4j 图谱检索适配器"""

    def __init__(
        self,
        neo4j_uri: str = GRAPH_NEO4J_URI,
        neo4j_user: str = GRAPH_NEO4J_USER,
        neo4j_password: str = GRAPH_NEO4J_PASSWORD,
        lane_timeout_ms: int = GRAPH_LANE_TIMEOUT_MS,
    ):
        self._neo4j_uri = neo4j_uri
        self._neo4j_user = neo4j_user
        self._neo4j_password = neo4j_password
        self._lane_timeout_ms = lane_timeout_ms
        self._driver = None  # 懒加载

    async def _get_driver(self):
        """懒加载 Neo4j 异步驱动，首次调用时导入并初始化，执行 RETURN 1 预热。"""
        if self._driver is None:
            from neo4j import AsyncGraphDatabase  # 懒加载：避免未安装时启动失败

            driver = AsyncGraphDatabase.driver(
                self._neo4j_uri,
                auth=(self._neo4j_user, self._neo4j_password),
            )
            # 预热连接，验证可用性
            async with driver.session() as session:
                await session.run("RETURN 1")
            self._driver = driver
        return self._driver

    @property
    def backend_name(self) -> str:
        return "graph"

    @property
    def supported_content_types(self) -> list[ContentType]:
        return [ContentType.CODE]

    async def search(self, query: BackendQuery) -> BackendResponse:
        """执行图谱检索，委托给 search_by_graph()，统一封装计时和错误处理。"""
        start = time.perf_counter()
        try:
            top_k = query.options.max_results
            repos: list[str] | None = query.backend_specific.get("repos")
            hits = await self.search_by_graph(
                query=query.raw_query,
                top_k=top_k,
                repos=repos,
                project=query.backend_specific.get("project"),
            )
            latency_ms = (time.perf_counter() - start) * 1000
            items = [
                SearchItem(
                    id=f"graph:{hit['repo']}/{hit['path']}:{hit.get('start_line', 0)}",
                    source="graph",
                    content_type=ContentType.CODE,
                    title=f"{hit['repo']}/{hit['path']}",
                    summary=hit.get("content", "")[:200],
                    url="",
                    score=hit.get("score", 0.0),
                    matched_terms=hit.get("matched_terms", []),
                    metadata={
                        "repo": hit.get("repo", ""),
                        "path": hit.get("path", ""),
                        "start_line": hit.get("start_line"),
                        "end_line": hit.get("end_line"),
                    },
                )
                for hit in hits
            ]
            return BackendResponse(
                backend="graph",
                status="ok",
                latency_ms=latency_ms,
                total_hits=len(items),
                items=items,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.warning("graph search 失败: %s", exc)
            return BackendResponse(
                backend="graph",
                status="error",
                latency_ms=latency_ms,
                total_hits=0,
                items=[],
                error_detail=str(exc),
            )

    async def search_by_graph(
        self,
        query: str,
        top_k: int = 10,
        repos: list[str] | None = None,
        project: str | None = None,
    ) -> list[dict]:
        """基于图谱的关系检索。

        流程：
        1. 从查询字符串提取实体词元
        2. 全文检索匹配节点
        3. 从匹配节点扩展邻居 File 节点
        4. 计算图谱得分，返回 top_k 结果
        """
        terms = extract_query_entities(query)
        if not terms:
            return []

        driver = await self._get_driver()

        # 第一步：全文检索种子节点
        seed_nodes = await fulltext_search_nodes(driver, terms, limit=20, project=project)
        if not seed_nodes:
            return []

        seed_ids = [n["nid"] for n in seed_nodes]

        # 第二步：扩展到 File 节点
        neighbor_results = await expand_neighbors(driver, seed_ids, max_hops=2, project=project)

        if not neighbor_results:
            return []

        # 计算最大匹配数（用于归一化）
        max_match_count = (
            max(len(r["anchor_nids"]) for r in neighbor_results) if neighbor_results else 1
        )

        hits: list[dict] = []
        for result in neighbor_results:
            file_props = result["file_props"]
            path_length = result["path_length"]
            anchor_nids = result["anchor_nids"]

            # 过滤仓库
            if repos:
                file_repo = file_props.get("repo", "")
                if file_repo not in repos:
                    continue

            # 计算图谱得分
            score = compute_graph_score(
                path_length=path_length,
                match_count=len(anchor_nids),
                max_match_count=max_match_count,
            )

            hit = format_hit(file_props, path_length, terms)
            hit["score"] = score
            hits.append(hit)

        # 按得分降序排列，返回 top_k
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:top_k]

    async def get_content(self, item_id: str) -> dict:
        """不支持：内容获取由 gateway.get_file_content() + ZoektAdapter 统一处理。"""
        raise NotImplementedError(
            "GraphAdapter 不支持 get_content()，"
            "请通过 gateway.get_file_content() 获取文件内容（委托给 ZoektAdapter）"
        )

    async def health_check(self) -> bool:
        """健康检查：验证驱动连接正常且全文索引存在。"""
        try:
            driver = await self._get_driver()
            async with driver.session() as session:
                result = await session.run(
                    "CALL db.indexes() YIELD name RETURN collect(name) AS names"
                )
                record = await result.single()
                index_names: list[str] = record["names"] if record else []
                has_indexes = "symbol_name_idx" in index_names or "doc_entity_idx" in index_names
                return has_indexes
        except Exception as exc:
            logger.debug("graph health_check 失败: %s", exc)
            return False
