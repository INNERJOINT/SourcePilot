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
from observability.audit import audit_stage

logger = logging.getLogger(__name__)

# Default adapter instance
_default_adapter = ZoektAdapter(zoekt_url=ZOEKT_URL)


# ─── Internal helpers ────────────────────────────────────

async def _search_with_audit(query: str, route_index: int, **kwargs) -> list[dict]:
    """单路 Zoekt 搜索，带 audit_stage 记录。"""
    async with audit_stage("zoekt_search", {"query": query, "route_index": route_index}) as stg:
        records = await _default_adapter.search_zoekt(query=query, **kwargs)
        stg.set_result({"records_count": len(records)})
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
            stg.set_result({"records_count": len(results)})
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
    LLM Rewrite → parallel Zoekt queries → RRF fusion → Feature Rerank
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
            stg.set_result({"records_count": len(records)})
            stg.set_result_count(len(records))
        return records

    # 2. 多路 Zoekt 并行查询
    async with audit_stage("nl_parallel_search", {
        "query": query,
        "route_count": len(rewrite_results),
        "queries": [r["query"] for r in rewrite_results],
    }) as stg:
        tasks = [
            _search_with_audit(
                query=rq["query"],
                route_index=i,
                top_k=20,
                score_threshold=0,
                repos=repos,
                lang=lang,
                branch=branch,
            )
            for i, rq in enumerate(rewrite_results)
        ]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_results = [r for r in all_results if isinstance(r, list)]
        failed_results = [r for r in all_results if isinstance(r, Exception)]
        stg.set_result({
            "routes_succeeded": len(valid_results),
            "routes_failed": len(failed_results),
            "per_route_counts": [len(r) for r in valid_results],
            "errors": [str(e) for e in failed_results][:3],
        })

    logger.info(
        "NL multi-query: %d/%d routes succeeded",
        len(valid_results), len(all_results),
    )

    if not valid_results:
        # 所有路都失败时，降级
        async with audit_stage("fallback_search", {"query": query, "reason": "all_routes_failed"}) as stg:
            records = await _default_adapter.search_zoekt(
                query=query, top_k=top_k,
                score_threshold=score_threshold, repos=repos,
                lang=lang, branch=branch,
            )
            stg.set_result({"records_count": len(records)})
            stg.set_result_count(len(records))
        return records

    # 3. RRF 融合
    async with audit_stage("rrf_merge", {
        "input_lists": len(valid_results),
        "input_total": sum(len(r) for r in valid_results),
    }) as stg:
        merged = rrf_merge(valid_results)
        stg.set_result({
            "merged_count": len(merged),
            "dedup_removed": sum(len(r) for r in valid_results) - len(merged),
            "top_score": merged[0]["score"] if merged else 0,
        })
        stg.set_result_count(len(merged))
    logger.info("NL RRF merged: %d candidates", len(merged))

    # 4. Feature-based Rerank
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

    # 5. 按 score_threshold 过滤
    if score_threshold > 0:
        reranked = [r for r in reranked if r.get("score", 0) >= score_threshold]

    return reranked


async def search_symbol(
    symbol: str,
    top_k: int = 5,
    repos: str | None = None,
    lang: str | None = None,
    branch: str | None = None,
    case_sensitive: str = "auto",
) -> list[dict]:
    """Symbol search via sym: prefix with fallback to plain search."""
    query = f"sym:{symbol}"
    results = await _default_adapter.search_zoekt(
        query=query, top_k=top_k, score_threshold=0,
        repos=repos, lang=lang, branch=branch, case_sensitive=case_sensitive,
    )

    if not results:
        # 降级：普通搜索
        results = await _default_adapter.search_zoekt(
            query=symbol, top_k=top_k, score_threshold=0,
            repos=repos, lang=lang, branch=branch, case_sensitive=case_sensitive,
        )

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
    query = f"file:{path}"
    if extra_query:
        query = f"file:{path} {extra_query}"

    return await _default_adapter.search_zoekt(
        query=query, top_k=top_k, score_threshold=0,
        repos=None, lang=lang, branch=branch, case_sensitive=case_sensitive,
    )


async def search_regex(
    pattern: str,
    top_k: int = 10,
    repos: str | None = None,
    lang: str | None = None,
) -> list[dict]:
    """Regex search."""
    return await _default_adapter.search_regex(
        pattern=pattern, top_k=top_k, score_threshold=0,
        repos=repos, lang=lang,
    )


async def list_repos(
    query: str = "",
    top_k: int = 50,
) -> list[dict]:
    """List matching repos."""
    return await _default_adapter.list_repos(query=query, top_k=top_k)


async def get_file_content(
    repo: str,
    filepath: str,
    start_line: int = 1,
    end_line: int | None = None,
) -> dict:
    """Get file content."""
    return await _default_adapter.fetch_file_content(
        repo=repo, filepath=filepath,
        start_line=start_line, end_line=end_line,
    )
