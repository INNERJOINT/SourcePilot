"""
StructuralAdapter — Neo4j structural retrieval adapter (full implementation)

Wraps the Neo4j async driver, implementing the SearchAdapter interface.
The neo4j driver is lazily loaded — imported only on first use to avoid startup
failures when the package is not installed.
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
from adapters.structural_traversal import (
    compute_structural_score,
    expand_neighbors,
    extract_query_entities,
    format_hit,
    fulltext_search_nodes,
)
from config import (
    STRUCTURAL_LANE_TIMEOUT_MS,
    STRUCTURAL_NEO4J_PASSWORD,
    STRUCTURAL_NEO4J_URI,
    STRUCTURAL_NEO4J_USER,
)

logger = logging.getLogger(__name__)


class StructuralAdapter(SearchAdapter):
    """Neo4j structural retrieval adapter."""

    def __init__(
        self,
        neo4j_uri: str = STRUCTURAL_NEO4J_URI,
        neo4j_user: str = STRUCTURAL_NEO4J_USER,
        neo4j_password: str = STRUCTURAL_NEO4J_PASSWORD,
        lane_timeout_ms: int = STRUCTURAL_LANE_TIMEOUT_MS,
    ):
        self._neo4j_uri = neo4j_uri
        self._neo4j_user = neo4j_user
        self._neo4j_password = neo4j_password
        self._lane_timeout_ms = lane_timeout_ms
        self._driver = None  # lazily initialized

    async def _get_driver(self):
        """Lazily initialize the Neo4j async driver on first call; warm up with RETURN 1."""
        if self._driver is None:
            from neo4j import AsyncGraphDatabase  # lazy import: avoid failure when package not installed

            driver = AsyncGraphDatabase.driver(
                self._neo4j_uri,
                auth=(self._neo4j_user, self._neo4j_password),
            )
            # Warm up the connection to verify availability
            async with driver.session() as session:
                await session.run("RETURN 1")
            self._driver = driver
        return self._driver

    @property
    def backend_name(self) -> str:
        return "structural"

    @property
    def supported_content_types(self) -> list[ContentType]:
        return [ContentType.CODE]

    async def search(self, query: BackendQuery) -> BackendResponse:
        """Execute structural search, delegating to search_by_structural() with unified timing and error handling."""
        start = time.perf_counter()
        try:
            top_k = query.options.max_results
            repos: list[str] | None = query.backend_specific.get("repos")
            hits = await self.search_by_structural(
                query=query.raw_query,
                top_k=top_k,
                repos=repos,
                project=query.backend_specific.get("project"),
            )
            latency_ms = (time.perf_counter() - start) * 1000
            items = [
                SearchItem(
                    id=f"structural:{hit['repo']}/{hit['path']}:{hit.get('start_line', 0)}",
                    source="structural",
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
                backend="structural",
                status="ok",
                latency_ms=latency_ms,
                total_hits=len(items),
                items=items,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.warning("structural search failed: %s", exc)
            return BackendResponse(
                backend="structural",
                status="error",
                latency_ms=latency_ms,
                total_hits=0,
                items=[],
                error_detail=str(exc),
            )

    async def search_by_structural(
        self,
        query: str,
        top_k: int = 10,
        repos: list[str] | None = None,
        project: str | None = None,
    ) -> list[dict]:
        """Relationship-based retrieval using the structural index.

        Steps:
        1. Extract entity tokens from the query string.
        2. Full-text search to match nodes.
        3. Expand matched nodes to neighbouring File nodes.
        4. Compute structural scores and return top_k results.
        """
        terms = extract_query_entities(query)
        if not terms:
            return []

        driver = await self._get_driver()

        # Step 1: full-text search for seed nodes
        seed_nodes = await fulltext_search_nodes(driver, terms, limit=20, project=project)
        if not seed_nodes:
            return []

        seed_ids = [n["nid"] for n in seed_nodes]

        # Step 2: expand to File nodes
        neighbor_results = await expand_neighbors(driver, seed_ids, max_hops=2, project=project)

        if not neighbor_results:
            return []

        # Compute max match count (used for normalization)
        max_match_count = (
            max(len(r["anchor_nids"]) for r in neighbor_results) if neighbor_results else 1
        )

        hits: list[dict] = []
        for result in neighbor_results:
            file_props = result["file_props"]
            path_length = result["path_length"]
            anchor_nids = result["anchor_nids"]

            # Filter by repo
            if repos:
                file_repo = file_props.get("repo", "")
                if file_repo not in repos:
                    continue

            # Compute structural score
            score = compute_structural_score(
                path_length=path_length,
                match_count=len(anchor_nids),
                max_match_count=max_match_count,
            )

            hit = format_hit(file_props, path_length, terms)
            hit["score"] = score
            hits.append(hit)

        # Sort by score descending and return top_k
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:top_k]

    async def get_content(self, item_id: str) -> dict:
        """Not supported: content retrieval is handled centrally by gateway.get_file_content() + ZoektAdapter."""
        raise NotImplementedError(
            "StructuralAdapter does not support get_content(). "
            "Use gateway.get_file_content() to fetch file content (delegates to ZoektAdapter)."
        )

    async def health_check(self) -> bool:
        """Health check: verify driver connection is healthy and the full-text index exists."""
        try:
            driver = await self._get_driver()
            async with driver.session() as session:
                result = await session.run(
                    "SHOW INDEXES YIELD name RETURN collect(name) AS names"
                )
                record = await result.single()
                index_names: list[str] = record["names"] if record else []
                has_indexes = "symbol_name_idx" in index_names or "doc_entity_idx" in index_names
                return has_indexes
        except Exception as exc:
            logger.debug("structural health_check failed: %s", exc)
            return False
