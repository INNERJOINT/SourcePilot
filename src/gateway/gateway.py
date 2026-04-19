"""
Query Gateway -- main orchestration entry point.

Flow: classify -> (NL: rewrite -> multi-query) -> dispatch to adapters -> fusion -> rerank

All business logic lives here. Entry layer modules are protocol-only wrappers.
"""

import asyncio
import logging

from adapters.zoekt import ZoektAdapter
import config
from config import ZOEKT_URL
from gateway.nl.classifier import classify_query
from gateway.nl.rewriter import rewrite_query
from gateway.fusion import rrf_merge
from gateway.ranker import feature_rerank
from gateway.converters import dense_result_to_dict
from observability.audit import audit_stage

logger = logging.getLogger(__name__)

# Default adapter instances
_default_adapter = ZoektAdapter(zoekt_url=ZOEKT_URL)
_dense_adapter = None


def _get_dense_adapter():
    """Lazy-init dense adapter when DENSE_ENABLED=true."""
    global _dense_adapter
    if not config.DENSE_ENABLED:
        return None
    if _dense_adapter is None:
        from adapters.dense import DenseAdapter
        _dense_adapter = DenseAdapter(
            vector_db_url=config.DENSE_VECTOR_DB_URL,
            embedding_url=config.DENSE_EMBEDDING_URL,
            collection_name=config.DENSE_COLLECTION_NAME,
            embedding_model=config.DENSE_EMBEDDING_MODEL,
            embedding_dim=config.DENSE_EMBEDDING_DIM,
            top_k=config.DENSE_TOP_K,
        )
        logger.info("Dense adapter initialized: %s", config.DENSE_VECTOR_DB_URL)
    return _dense_adapter


# ─── Internal helpers ────────────────────────────────────

async def _search_with_audit(query: str, route_index: int, **kwargs) -> list[dict]:
    """单路 Zoekt 搜索，带 audit_stage 记录。"""
    async with audit_stage("zoekt_search", {"query": query, "route_index": route_index}) as stg:
        records = await _default_adapter.search_zoekt(query=query, **kwargs)
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
) -> list[dict]:
    """
    Unified search entry point — handles NL classification and dispatches accordingly.

    Returns raw list[dict] results. Formatting into MCP TextContent is done by entry layer.
    """
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
            query=query, top_k=top_k, score_threshold=score_threshold,
            repos=repos, lang=lang, branch=branch,
        )
    else:
        async with audit_stage("zoekt_search", {"query": query, "repos": repos}) as stg:
            results = await _default_adapter.search_zoekt(
                query=query, top_k=top_k, score_threshold=score_threshold,
                repos=repos, lang=lang, branch=branch, case_sensitive=case_sensitive,
            )
            stg.set_result({"records_count": len(results), "records": results})
            stg.set_result_count(len(results))
        return results


async def _nl_search(
    query: str,
    top_k: int,
    score_threshold: float,
    repos: str | None,
    lang: str | None = None,
    branch: str | None = None,
) -> list[dict]:
    """
    NL enhanced search pipeline:
    LLM Rewrite → parallel Zoekt queries + Dense semantic search → RRF fusion → Feature Rerank
    """
    # 1. LLM Query Rewrite
    async with audit_stage("rewrite", {"query": query}) as stg:
        rewrite_results = await rewrite_query(query)
        stg.set_result({
            "method": "llm" if rewrite_results else "empty",
            "query_count": len(rewrite_results),
            "queries": [r["query"] for r in rewrite_results],
        })
    logger.info(
        "NL rewrite: %d queries → %s",
        len(rewrite_results),
        [r["query"] for r in rewrite_results],
    )

    if not rewrite_results:
        # rewrite 完全失败时，降级为直接搜索
        async with audit_stage("fallback_search", {"query": query, "reason": "rewrite_empty"}) as stg:
            records = await _default_adapter.search_zoekt(
                query=query, top_k=top_k,
                score_threshold=score_threshold, repos=repos,
                lang=lang, branch=branch,
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
                top_k=20,
                score_threshold=0,
                repos=repos,
                lang=lang,
                branch=branch,
            )
        )

    # 2b. Dense 通道：原始 NL query → 单路语义搜索
    dense = _get_dense_adapter()
    has_dense = dense is not None
    if has_dense:
        tasks.append(_dense_search_with_audit(query, repos=repos))

    zoekt_route_count = len(rewrite_results)

    # 3. 并行执行所有任务
    async with audit_stage("nl_parallel_search", {
        "query": query,
        "zoekt_route_count": zoekt_route_count,
        "dense_enabled": has_dense,
        "queries": [r["query"] for r in rewrite_results],
    }) as stg:
        all_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 4. 分离 Zoekt 和 Dense 结果
        zoekt_results_raw = all_results[:zoekt_route_count]
        valid_zoekt = [r for r in zoekt_results_raw if isinstance(r, list)]
        failed_zoekt = [r for r in zoekt_results_raw if isinstance(r, Exception)]

        dense_results = []
        if has_dense and zoekt_route_count < len(all_results):
            raw_dense = all_results[zoekt_route_count]
            if isinstance(raw_dense, list):
                dense_results = [dense_result_to_dict(h) for h in raw_dense]

        stg.set_result({
            "zoekt_routes_succeeded": len(valid_zoekt),
            "zoekt_routes_failed": len(failed_zoekt),
            "dense_results": len(dense_results),
            "per_route_counts": [len(r) for r in valid_zoekt],
            "errors": [str(e) for e in failed_zoekt][:3],
        })

    logger.info(
        "NL multi-query: %d/%d zoekt routes succeeded, %d dense results",
        len(valid_zoekt), len(zoekt_results_raw), len(dense_results),
    )

    if not valid_zoekt and not dense_results:
        # 所有路都失败时，降级
        async with audit_stage("fallback_search", {"query": query, "reason": "all_routes_failed"}) as stg:
            records = await _default_adapter.search_zoekt(
                query=query, top_k=top_k,
                score_threshold=score_threshold, repos=repos,
                lang=lang, branch=branch,
            )
            stg.set_result({"records_count": len(records), "records": records})
            stg.set_result_count(len(records))
        return records

    # 5. RRF 融合（Zoekt 多路 + Dense 一路）
    all_lists = valid_zoekt + ([dense_results] if dense_results else [])
    async with audit_stage("rrf_merge", {
        "input_lists": len(all_lists),
        "input_total": sum(len(r) for r in all_lists),
    }) as stg:
        merged = rrf_merge(all_lists)
        stg.set_result({
            "merged_count": len(merged),
            "dedup_removed": sum(len(r) for r in all_lists) - len(merged),
            "top_score": merged[0]["score"] if merged else 0,
        })
        stg.set_result_count(len(merged))
    logger.info("NL RRF merged: %d candidates", len(merged))

    # 6. Feature-based Rerank
    async with audit_stage("rerank", {
        "query": query,
        "candidate_count": len(merged),
        "top_n": top_k,
    }) as stg:
        reranked = feature_rerank(query, merged, top_n=top_k)
        stg.set_result({
            "output_count": len(reranked),
            "score_range": [reranked[-1]["score"], reranked[0]["score"]] if reranked else [],
        })
        stg.set_result_count(len(reranked))

    # 7. 按 score_threshold 过滤
    if score_threshold > 0:
        reranked = [r for r in reranked if r.get("score", 0) >= score_threshold]

    return reranked


async def _dense_search_with_audit(query: str, repos: str | None = None) -> list[dict]:
    """Dense 通道搜索，带 audit 和降级。"""
    async with audit_stage("dense_search", {"query": query}) as stg:
        try:
            dense = _get_dense_adapter()
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


async def search_symbol(
    symbol: str,
    top_k: int = 5,
    repos: str | None = None,
    lang: str | None = None,
    branch: str | None = None,
    case_sensitive: str = "auto",
) -> list[dict]:
    """Symbol search via sym: prefix with fallback to plain search."""
    async with audit_stage("search_symbol", {"symbol": symbol, "repos": repos}) as stg:
        query = f"sym:{symbol}"
        results = await _default_adapter.search_zoekt(
            query=query, top_k=top_k, score_threshold=0,
            repos=repos, lang=lang, branch=branch, case_sensitive=case_sensitive,
        )

        used_fallback = False
        if not results:
            used_fallback = True
            results = await _default_adapter.search_zoekt(
                query=symbol, top_k=top_k, score_threshold=0,
                repos=repos, lang=lang, branch=branch, case_sensitive=case_sensitive,
            )

        stg.set_result({"records_count": len(results), "records": results, "fallback": used_fallback})
        stg.set_result_count(len(results))
    return results


async def search_file(
    path: str,
    extra_query: str = "",
    top_k: int = 5,
    lang: str | None = None,
    branch: str | None = None,
    case_sensitive: str = "auto",
) -> list[dict]:
    """File search via file: prefix."""
    async with audit_stage("search_file", {"path": path, "extra_query": extra_query}) as stg:
        query = f"file:{path}"
        if extra_query:
            query = f"file:{path} {extra_query}"

        results = await _default_adapter.search_zoekt(
            query=query, top_k=top_k, score_threshold=0,
            repos=None, lang=lang, branch=branch, case_sensitive=case_sensitive,
        )
        stg.set_result({"records_count": len(results), "records": results})
        stg.set_result_count(len(results))
    return results


async def search_regex(
    pattern: str,
    top_k: int = 10,
    repos: str | None = None,
    lang: str | None = None,
) -> list[dict]:
    """Regex search."""
    async with audit_stage("search_regex", {"pattern": pattern, "repos": repos}) as stg:
        results = await _default_adapter.search_regex(
            pattern=pattern, top_k=top_k, score_threshold=0,
            repos=repos, lang=lang,
        )
        stg.set_result({"records_count": len(results), "records": results})
        stg.set_result_count(len(results))
    return results


async def list_repos(
    query: str = "",
    top_k: int = 50,
) -> list[dict]:
    """List matching repos."""
    async with audit_stage("list_repos", {"query": query}) as stg:
        results = await _default_adapter.list_repos(query=query, top_k=top_k)
        stg.set_result({"records_count": len(results), "records": results})
        stg.set_result_count(len(results))
    return results


async def get_file_content(
    repo: str,
    filepath: str,
    start_line: int = 1,
    end_line: int | None = None,
) -> dict:
    """Get file content."""
    async with audit_stage("get_file_content", {"repo": repo, "filepath": filepath}) as stg:
        result = await _default_adapter.fetch_file_content(
            repo=repo, filepath=filepath,
            start_line=start_line, end_line=end_line,
        )
        stg.set_result({"total_lines": result.get("total_lines", 0)})
    return result
