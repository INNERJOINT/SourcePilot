"""
Query Gateway -- main orchestration entry point.

Flow: classify -> (NL: rewrite -> multi-query) -> dispatch to adapters -> fusion -> rerank

All business logic lives here. Entry layer modules are protocol-only wrappers.
"""

import asyncio
import logging

import config
from adapters.zoekt import ZoektAdapter
from config import get_default_project, get_project
from gateway.converters import dense_result_to_dict, feishu_result_to_dict, graph_result_to_dict
from gateway.fusion import rrf_merge
from gateway.nl.classifier import classify_query
from gateway.nl.rewriter import rewrite_query
from gateway.ranker import feature_rerank
from observability.audit import audit_stage

logger = logging.getLogger(__name__)

# Per-project adapter cache
_adapters: dict[str, ZoektAdapter] = {}
_dense_adapter: dict[tuple[str, str], object] | None = None
_graph_adapter = None


def _is_zoekt_project(project: str | None = None) -> bool:
    """Return False for projects that have no Zoekt backend (e.g. Feishu)."""
    try:
        if project is None:
            proj_cfg = get_default_project()
        else:
            proj_cfg = get_project(project)
        return bool(proj_cfg.zoekt_url) and proj_cfg.project_type == "aosp"
    except ValueError:
        return True


def _get_adapter(project: str | None = None) -> ZoektAdapter:
    """Return a cached ZoektAdapter for the given project (or default)."""
    if project is None:
        proj_cfg = get_default_project()
    else:
        proj_cfg = get_project(project)  # raises ValueError for unknown project
    name = proj_cfg.name
    if name not in _adapters:
        _adapters[name] = ZoektAdapter(zoekt_url=proj_cfg.zoekt_url)
        logger.info("Created ZoektAdapter for project '%s' → %s", name, proj_cfg.zoekt_url)
    return _adapters[name]


def _get_dense_adapter(project: str | None = None):
    """Lazy-init dense adapter by (project, collection) when DENSE_ENABLED=true."""
    global _dense_adapter
    if not config.DENSE_ENABLED:
        return None

    if project is None:
        proj_cfg = get_default_project()
    else:
        proj_cfg = get_project(project)

    key = (proj_cfg.name, proj_cfg.dense_collection_name)
    if _dense_adapter is None:
        _dense_adapter = {}

    if key not in _dense_adapter:
        from adapters.dense import _FEISHU_OUTPUT_FIELDS, DenseAdapter

        output_fields = _FEISHU_OUTPUT_FIELDS if proj_cfg.project_type == "feishu" else None
        _dense_adapter[key] = DenseAdapter(
            vector_db_url=config.DENSE_VECTOR_DB_URL,
            embedding_url=config.DENSE_EMBEDDING_URL,
            collection_name=proj_cfg.dense_collection_name,
            embedding_model=config.DENSE_EMBEDDING_MODEL,
            embedding_dim=config.DENSE_EMBEDDING_DIM,
            top_k=config.DENSE_TOP_K,
            output_fields=output_fields,
        )
        logger.info(
            "Dense adapter initialized for project '%s' collection '%s': %s",
            proj_cfg.name,
            proj_cfg.dense_collection_name,
            config.DENSE_VECTOR_DB_URL,
        )
    return _dense_adapter[key]


def _get_graph_adapter():
    """Lazy-init graph adapter when GRAPH_ENABLED=true。"""
    global _graph_adapter
    if not config.GRAPH_ENABLED:
        return None
    if _graph_adapter is None:
        from adapters.graph import GraphAdapter

        _graph_adapter = GraphAdapter()
        logger.info("Graph adapter initialized")
    return _graph_adapter


# ─── Internal helpers ────────────────────────────────────


async def _search_with_audit(
    query: str, route_index: int, project: str | None = None, **kwargs
) -> list[dict]:
    """单路 Zoekt 搜索，带 audit_stage 记录。"""
    async with audit_stage("zoekt_search", {"query": query, "route_index": route_index}) as stg:
        records = await _get_adapter(project).search_zoekt(query=query, **kwargs)
        stg.set_result({"records_count": len(records), "records": records})
        stg.set_result_count(len(records))
        return records


# ─── Public gateway functions ────────────────────────────


async def search(
    query: str,
    top_k: int = 10,
    score_threshold: float = 0.0,
    repos: str | None = None,
    lang: str | None = None,
    branch: str | None = None,
    case_sensitive: str = "auto",
    project: str | None = None,
) -> list[dict]:
    """
    Unified search entry point — handles NL classification and dispatches accordingly.

    Returns raw list[dict] results. Formatting into MCP TextContent is done by entry layer.
    """
    # Feishu-type projects: dense-only, skip Zoekt entirely
    if not _is_zoekt_project(project):
        return await _feishu_search(query=query, top_k=top_k, score_threshold=score_threshold)

    # NL classification
    async with audit_stage("classify", {"query": query}) as stg:
        if config.NL_ENABLED:
            query_type = classify_query(query)
        else:
            query_type = "exact"
        stg.set_result({"query_type": query_type, "nl_enabled": config.NL_ENABLED})

    logger.info("Query type: %s (config.NL_ENABLED=%s)", query_type, config.NL_ENABLED)

    if query_type == "natural_language":
        return await _nl_search(
            query=query,
            top_k=top_k,
            score_threshold=score_threshold,
            repos=repos,
            lang=lang,
            branch=branch,
            project=project,
        )
    else:
        async with audit_stage("zoekt_search", {"query": query, "repos": repos}) as stg:
            results = await _get_adapter(project).search_zoekt(
                query=query,
                top_k=top_k,
                score_threshold=score_threshold,
                repos=repos,
                lang=lang,
                branch=branch,
                case_sensitive=case_sensitive,
            )
            stg.set_result({"records_count": len(results), "records": results})
            stg.set_result_count(len(results))
        return results


async def _feishu_search(
    query: str,
    top_k: int,
    score_threshold: float,
    project: str | None = None,
) -> list[dict]:
    """Dense-only search for Feishu projects (no Zoekt, no NL rewrite)."""
    async with audit_stage("dense_search", {"query": query, "project": project}) as stg:
        try:
            dense = _get_dense_adapter(project)
            if dense is None:
                stg.set_result({"error": "dense not enabled", "records_count": 0})
                return []
            results = await asyncio.wait_for(
                dense.search_by_embedding(query, top_k=top_k),
                timeout=config.NL_TIMEOUT,
            )
            converted = [feishu_result_to_dict(h) for h in results]
            if score_threshold > 0:
                converted = [r for r in converted if r.get("score", 0) >= score_threshold]
            stg.set_result({"records_count": len(converted), "records": converted})
            stg.set_result_count(len(converted))
            return converted
        except Exception as e:
            logger.warning("Feishu dense search failed: %s", e)
            stg.set_result({"error": str(e), "records_count": 0})
            return []


async def _nl_search(
    query: str,
    top_k: int,
    score_threshold: float,
    repos: str | None,
    lang: str | None = None,
    branch: str | None = None,
    project: str | None = None,
) -> list[dict]:
    """
    NL enhanced search pipeline:
    LLM Rewrite → parallel Zoekt queries + Dense semantic search → RRF fusion → Feature Rerank
    """
    # 1. LLM Query Rewrite
    async with audit_stage("rewrite", {"query": query}) as stg:
        rewrite_results = await rewrite_query(query)
        stg.set_result(
            {
                "method": "llm" if rewrite_results else "empty",
                "query_count": len(rewrite_results),
                "queries": [r["query"] for r in rewrite_results],
            }
        )
    logger.info(
        "NL rewrite: %d queries → %s",
        len(rewrite_results),
        [r["query"] for r in rewrite_results],
    )

    if not rewrite_results:
        # rewrite 完全失败时，降级为直接搜索
        async with audit_stage(
            "fallback_search", {"query": query, "reason": "rewrite_empty"}
        ) as stg:
            records = await _get_adapter(project).search_zoekt(
                query=query,
                top_k=top_k,
                score_threshold=score_threshold,
                repos=repos,
                lang=lang,
                branch=branch,
            )
            stg.set_result({"records_count": len(records), "records": records})
            stg.set_result_count(len(records))
        return records

    # 2. 构建并行任务：Zoekt 多路 rewrite + Dense 单路语义
    tasks = []

    # 2a. Zoekt 通道：rewritten queries → 多路并行
    for i, rq in enumerate(rewrite_results):
        tasks.append(
            _search_with_audit(
                query=rq["query"],
                route_index=i,
                project=project,
                top_k=20,
                score_threshold=0,
                repos=repos,
                lang=lang,
                branch=branch,
            )
        )

    # 2b. Dense 通道：原始 NL query → 单路语义搜索
    dense = _get_dense_adapter(project)
    has_dense = dense is not None
    if has_dense:
        tasks.append(_dense_search_with_audit(query, repos=repos, project=project))

    # 2c. Graph 通道：原始 NL query → 图谱关系搜索
    graph = _get_graph_adapter()
    has_graph = graph is not None
    if has_graph:
        tasks.append(_graph_search_with_audit(query, repos=repos, project=project))

    zoekt_route_count = len(rewrite_results)
    lane_idx = _assemble_lane_indices(zoekt_route_count, has_dense, has_graph)

    # 3. 并行执行所有任务
    async with audit_stage(
        "nl_parallel_search",
        {
            "query": query,
            "zoekt_route_count": zoekt_route_count,
            "dense_enabled": has_dense,
            "graph_enabled": has_graph,
            "queries": [r["query"] for r in rewrite_results],
        },
    ) as stg:
        all_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 4. 分离 Zoekt、Dense 和 Graph 结果
        zoekt_results_raw = all_results[:zoekt_route_count]
        valid_zoekt = [r for r in zoekt_results_raw if isinstance(r, list)]
        failed_zoekt = [r for r in zoekt_results_raw if isinstance(r, Exception)]

        dense_results = []
        if lane_idx["dense"] is not None:
            raw_dense = all_results[lane_idx["dense"]]
            if isinstance(raw_dense, list):
                dense_results = [dense_result_to_dict(h) for h in raw_dense]

        graph_results = []
        if lane_idx["graph"] is not None:
            raw_graph = all_results[lane_idx["graph"]]
            if isinstance(raw_graph, list):
                graph_results = [graph_result_to_dict(h) for h in raw_graph]

        stg.set_result(
            {
                "zoekt_routes_succeeded": len(valid_zoekt),
                "zoekt_routes_failed": len(failed_zoekt),
                "dense_results": len(dense_results),
                "graph_results": len(graph_results),
                "per_route_counts": [len(r) for r in valid_zoekt],
                "errors": [str(e) for e in failed_zoekt][:3],
            }
        )

    logger.info(
        "NL multi-query: %d/%d zoekt routes succeeded, %d dense results, %d graph results",
        len(valid_zoekt),
        len(zoekt_results_raw),
        len(dense_results),
        len(graph_results),
    )

    if not valid_zoekt and not dense_results and not graph_results:
        # 所有路都失败时，降级
        async with audit_stage(
            "fallback_search", {"query": query, "reason": "all_routes_failed"}
        ) as stg:
            records = await _get_adapter(project).search_zoekt(
                query=query,
                top_k=top_k,
                score_threshold=score_threshold,
                repos=repos,
                lang=lang,
                branch=branch,
            )
            stg.set_result({"records_count": len(records), "records": records})
            stg.set_result_count(len(records))
        return records

    # 5. RRF 融合（Zoekt 多路 + Dense 一路 + Graph 一路）
    all_lists = (
        valid_zoekt
        + ([dense_results] if dense_results else [])
        + ([graph_results] if graph_results else [])
    )
    async with audit_stage(
        "rrf_merge",
        {
            "input_lists": len(all_lists),
            "input_total": sum(len(r) for r in all_lists),
        },
    ) as stg:
        merged = rrf_merge(all_lists)
        stg.set_result(
            {
                "merged_count": len(merged),
                "dedup_removed": sum(len(r) for r in all_lists) - len(merged),
                "top_score": merged[0]["score"] if merged else 0,
            }
        )
        stg.set_result_count(len(merged))
    logger.info("NL RRF merged: %d candidates", len(merged))

    # 6. Feature-based Rerank
    async with audit_stage(
        "rerank",
        {
            "query": query,
            "candidate_count": len(merged),
            "top_n": top_k,
        },
    ) as stg:
        reranked = feature_rerank(query, merged, top_n=top_k)
        stg.set_result(
            {
                "output_count": len(reranked),
                "score_range": [reranked[-1]["score"], reranked[0]["score"]] if reranked else [],
            }
        )
        stg.set_result_count(len(reranked))

    # 7. 按 score_threshold 过滤
    if score_threshold > 0:
        reranked = [r for r in reranked if r.get("score", 0) >= score_threshold]

    return reranked


async def _dense_search_with_audit(
    query: str,
    repos: str | None = None,
    project: str | None = None,
) -> list[dict]:
    """Dense 通道搜索，带 audit 和降级。"""
    async with audit_stage("dense_search", {"query": query}) as stg:
        try:
            dense = _get_dense_adapter(project)
            results = await asyncio.wait_for(
                dense.search_by_embedding(query, top_k=config.DENSE_TOP_K, repos=repos),
                timeout=config.NL_TIMEOUT,
            )
            stg.set_result({"records_count": len(results), "records": results})
            stg.set_result_count(len(results))
            return results
        except Exception as e:
            logger.warning("Dense search failed, degrading to pure Zoekt: %s", e)
            stg.set_result({"error": str(e), "degraded": True})
            return []


async def _graph_search_with_audit(
    query: str,
    repos: str | None = None,
    project: str | None = None,
) -> list[dict]:
    """Graph 通道搜索，带 audit 和降级。"""
    async with audit_stage("graph_search", {"query": query}) as stg:
        try:
            graph = _get_graph_adapter()
            results = await asyncio.wait_for(
                graph.search_by_graph(
                    query, top_k=config.DENSE_TOP_K, repos=repos, project=project
                ),
                timeout=config.GRAPH_LANE_TIMEOUT_MS / 1000.0,
            )
            stg.set_result({"records_count": len(results), "records": results})
            stg.set_result_count(len(results))
            return results
        except Exception as e:
            logger.warning("Graph search failed, degrading: %s", e)
            stg.set_result({"error": str(e), "degraded": True})
            return []


def _assemble_lane_indices(
    zoekt_route_count: int, has_dense: bool, has_graph: bool
) -> dict[str, int | None]:
    """计算各 lane 在 asyncio.gather 结果列表中的索引。"""
    idx = zoekt_route_count
    dense_idx = None
    graph_idx = None
    if has_dense:
        dense_idx = idx
        idx += 1
    if has_graph:
        graph_idx = idx
        idx += 1
    return {"dense": dense_idx, "graph": graph_idx}


async def search_symbol(
    symbol: str,
    top_k: int = 5,
    repos: str | None = None,
    lang: str | None = None,
    branch: str | None = None,
    case_sensitive: str = "auto",
    project: str | None = None,
) -> list[dict]:
    """Symbol search via sym: prefix with fallback to plain search."""
    async with audit_stage("search_symbol", {"symbol": symbol, "repos": repos}) as stg:
        query = f"sym:{symbol}"
        adapter = _get_adapter(project)
        results = await adapter.search_zoekt(
            query=query,
            top_k=top_k,
            score_threshold=0,
            repos=repos,
            lang=lang,
            branch=branch,
            case_sensitive=case_sensitive,
        )

        used_fallback = False
        if not results:
            used_fallback = True
            results = await adapter.search_zoekt(
                query=symbol,
                top_k=top_k,
                score_threshold=0,
                repos=repos,
                lang=lang,
                branch=branch,
                case_sensitive=case_sensitive,
            )

        stg.set_result(
            {"records_count": len(results), "records": results, "fallback": used_fallback}
        )
        stg.set_result_count(len(results))
    return results


async def search_file(
    path: str,
    extra_query: str = "",
    top_k: int = 5,
    lang: str | None = None,
    branch: str | None = None,
    case_sensitive: str = "auto",
    project: str | None = None,
) -> list[dict]:
    """File search via file: prefix."""
    async with audit_stage("search_file", {"path": path, "extra_query": extra_query}) as stg:
        query = f"file:{path}"
        if extra_query:
            query = f"file:{path} {extra_query}"

        results = await _get_adapter(project).search_zoekt(
            query=query,
            top_k=top_k,
            score_threshold=0,
            repos=None,
            lang=lang,
            branch=branch,
            case_sensitive=case_sensitive,
        )
        stg.set_result({"records_count": len(results), "records": results})
        stg.set_result_count(len(results))
    return results


async def search_regex(
    pattern: str,
    top_k: int = 10,
    repos: str | None = None,
    lang: str | None = None,
    project: str | None = None,
) -> list[dict]:
    """Regex search."""
    async with audit_stage("search_regex", {"pattern": pattern, "repos": repos}) as stg:
        results = await _get_adapter(project).search_regex(
            pattern=pattern,
            top_k=top_k,
            score_threshold=0,
            repos=repos,
            lang=lang,
        )
        stg.set_result({"records_count": len(results), "records": results})
        stg.set_result_count(len(results))
    return results


async def list_repos(
    query: str = "",
    top_k: int = 50,
    project: str | None = None,
) -> list[dict]:
    """List matching repos."""
    async with audit_stage("list_repos", {"query": query}) as stg:
        results = await _get_adapter(project).list_repos(query=query, top_k=top_k)
        stg.set_result({"records_count": len(results), "records": results})
        stg.set_result_count(len(results))
    return results


async def get_file_content(
    repo: str,
    filepath: str,
    start_line: int = 1,
    end_line: int | None = None,
    project: str | None = None,
) -> dict:
    """Get file content."""
    async with audit_stage("get_file_content", {"repo": repo, "filepath": filepath}) as stg:
        result = await _get_adapter(project).fetch_file_content(
            repo=repo,
            filepath=filepath,
            start_line=start_line,
            end_line=end_line,
        )
        stg.set_result({"total_lines": result.get("total_lines", 0)})
    return result
