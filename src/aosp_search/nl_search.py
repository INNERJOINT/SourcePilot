"""
自然语言增强搜索 — 共享模块

供 app.py (Dify API) 和 mcp_server.py (MCP Server) 共同调用。
流程：LLM Rewrite → 多路 Zoekt 并行查询 → RRF 融合 → Feature Rerank
"""

import asyncio
import logging

from aosp_search import zoekt_client
from aosp_search.nl.rewriter import rewrite_query
from aosp_search.nl.merger import rrf_merge
from aosp_search.nl.reranker import feature_rerank
from aosp_search.audit import audit_stage

logger = logging.getLogger(__name__)


async def _search_with_audit(query: str, route_index: int, **kwargs) -> list[dict]:
    """单路 Zoekt 搜索，带 audit_stage 记录。"""
    async with audit_stage("zoekt_search", {"query": query, "route_index": route_index}) as stg:
        records = await zoekt_client.search(query=query, **kwargs)
        stg.set_result({"records_count": len(records)})
        stg.set_result_count(len(records))
        return records


async def nl_search(
    query: str,
    top_k: int,
    score_threshold: float,
    repos: str | None,
    lang: str | None = None,
    branch: str | None = None,
) -> list[dict]:
    """
    自然语言增强搜索流程：
    LLM Rewrite → 多路 Zoekt 并行查询 → RRF 融合 → Feature Rerank
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
            records = await zoekt_client.search(
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

        # 过滤异常结果
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
            records = await zoekt_client.search(
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
