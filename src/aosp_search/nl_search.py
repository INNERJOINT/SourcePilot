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

logger = logging.getLogger(__name__)


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
    rewrite_results = await rewrite_query(query)
    logger.info(
        "NL rewrite: %d queries → %s",
        len(rewrite_results),
        [r["query"] for r in rewrite_results],
    )

    if not rewrite_results:
        # rewrite 完全失败时，降级为直接搜索
        return await zoekt_client.search(
            query=query, top_k=top_k,
            score_threshold=score_threshold, repos=repos,
            lang=lang, branch=branch,
        )

    # 2. 多路 Zoekt 并行查询
    tasks = [
        zoekt_client.search(
            query=rq["query"],
            top_k=20,
            score_threshold=0,
            repos=repos,
            lang=lang,
            branch=branch,
        )
        for rq in rewrite_results
    ]
    all_results = await asyncio.gather(*tasks, return_exceptions=True)

    # 过滤异常结果
    valid_results = [r for r in all_results if isinstance(r, list)]
    logger.info(
        "NL multi-query: %d/%d routes succeeded",
        len(valid_results), len(all_results),
    )

    if not valid_results:
        # 所有路都失败时，降级
        return await zoekt_client.search(
            query=query, top_k=top_k,
            score_threshold=score_threshold, repos=repos,
            lang=lang, branch=branch,
        )

    # 3. RRF 融合
    merged = rrf_merge(valid_results)
    logger.info("NL RRF merged: %d candidates", len(merged))

    # 4. Feature-based Rerank
    reranked = feature_rerank(query, merged, top_n=top_k)

    # 5. 按 score_threshold 过滤
    if score_threshold > 0:
        reranked = [r for r in reranked if r.get("score", 0) >= score_threshold]

    return reranked
