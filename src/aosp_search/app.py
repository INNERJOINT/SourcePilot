"""
Dify 外部知识库 Query API

严格遵循 Dify 外部知识库 API 规范：
https://docs.dify.ai/zh/use-dify/knowledge/external-knowledge-api

端点：POST /retrieval
监听端口：445（通过 config.PORT 配置）
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from aosp_search import config
from aosp_search import zoekt_client

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Zoekt-Dify Query API",
    description="Dify 外部知识库适配层 — 桥接 Zoekt 代码搜索与 Dify 平台",
    version="1.0.0",
)


# ─── 请求/响应模型 ───────────────────────────────────

class RetrievalSetting(BaseModel):
    top_k: int = Field(default=5, ge=1, le=100, description="检索结果最大数量")
    score_threshold: float = Field(default=0.5, ge=0.0, le=1.0, description="分数阈值")


class MetadataCondition(BaseModel):
    """元数据筛选条件（P0 阶段仅解析，不做复杂过滤）"""
    logical_operator: str = "and"
    conditions: list = Field(default_factory=list)


class RetrievalRequest(BaseModel):
    knowledge_id: str = Field(..., description="知识库唯一 ID，如 aosp:android-latest-release")
    query: str = Field(..., min_length=1, description="用户查询")
    retrieval_setting: RetrievalSetting = Field(default_factory=RetrievalSetting)
    metadata_condition: MetadataCondition | None = None


class RecordMetadata(BaseModel):
    repo: str = ""
    path: str = ""
    start_line: int | None = None
    end_line: int | None = None


class Record(BaseModel):
    content: str
    score: float
    title: str
    metadata: dict = Field(default_factory=dict)


class RetrievalResponse(BaseModel):
    records: list[Record]


class ErrorResponse(BaseModel):
    error_code: int
    error_msg: str


# ─── 鉴权辅助 ───────────────────────────────────────

def _verify_auth(request: Request) -> str | None:
    """
    验证 Authorization: Bearer <api-key>。
    返回 None 表示验证通过，否则返回错误类型。
    """
    auth_header = request.headers.get("Authorization", "")

    if not auth_header:
        return "missing"

    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0] != "Bearer":
        return "invalid_format"

    token = parts[1].strip()
    if token != config.API_KEY:
        return "unauthorized"

    return None


# ─── 端点 ────────────────────────────────────────────

@app.post("/retrieval", response_model=RetrievalResponse)
async def retrieval(body: RetrievalRequest, request: Request):
    """
    Dify 外部知识库检索端点。

    Dify 在运行时会对此端点发起 POST 请求，获取与用户查询相关的代码片段。
    """
    # 1. 鉴权
    auth_error = _verify_auth(request)
    if auth_error == "missing" or auth_error == "invalid_format":
        return JSONResponse(
            status_code=403,
            content={
                "error_code": 1001,
                "error_msg": "无效的 Authorization header 格式。预期格式为 'Bearer <api-key>'。",
            },
        )
    if auth_error == "unauthorized":
        return JSONResponse(
            status_code=403,
            content={
                "error_code": 1002,
                "error_msg": "授权失败，请检查 API Key 是否正确。",
            },
        )

    logger.info(
        "Retrieval request: knowledge_id=%s, query=%s, top_k=%d, threshold=%.2f",
        body.knowledge_id,
        body.query,
        body.retrieval_setting.top_k,
        body.retrieval_setting.score_threshold,
    )

    # 2. 从 knowledge_id 解析 repo 过滤条件
    #    格式示例：
    #      "default"           → 不过滤
    #      "aosp:frameworks/base" → repo 过滤 "frameworks/base"
    repos_filter = None
    if body.knowledge_id and ":" in body.knowledge_id:
        parts = body.knowledge_id.split(":", 1)
        if len(parts) == 2 and parts[1]:
            repos_filter = parts[1]

    # 3. 查询分类 & 搜索
    try:
        # 判断查询类型
        if config.NL_ENABLED:
            from nl.classifier import classify_query
            query_type = classify_query(body.query)
        else:
            query_type = "exact"

        logger.info("Query type: %s (NL_ENABLED=%s)", query_type, config.NL_ENABLED)

        if query_type == "natural_language":
            records = await _nl_search(
                query=body.query,
                top_k=body.retrieval_setting.top_k,
                score_threshold=body.retrieval_setting.score_threshold,
                repos=repos_filter,
            )
        else:
            # 精确查询：直接走 Zoekt
            records = await zoekt_client.search(
                query=body.query,
                top_k=body.retrieval_setting.top_k,
                score_threshold=body.retrieval_setting.score_threshold,
                repos=repos_filter,
            )
    except Exception as e:
        logger.error("搜索异常: %s", e)
        return JSONResponse(
            status_code=500,
            content={
                "error_code": 2001,
                "error_msg": f"知识库检索失败: {str(e)}",
            },
        )

    logger.info("Retrieval returned %d records", len(records))

    return {"records": records}


async def _nl_search(
    query: str,
    top_k: int,
    score_threshold: float,
    repos: str | None,
) -> list[dict]:
    """
    自然语言增强搜索流程：
    LLM Rewrite → 多路 Zoekt 并行查询 → RRF 融合 → Feature Rerank
    """
    import asyncio
    from aosp_search.nl.rewriter import rewrite_query
    from aosp_search.nl.merger import rrf_merge
    from aosp_search.nl.reranker import feature_rerank

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
        )

    # 2. 多路 Zoekt 并行查询
    tasks = [
        zoekt_client.search(
            query=rq["query"],
            top_k=20,  # 每路多取一些
            score_threshold=0,  # 融合后再过滤
            repos=repos,
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


# ─── 健康检查 ────────────────────────────────────────

@app.get("/health")
async def health():
    """健康检查端点"""
    return {"status": "ok"}


# ─── 主入口 ──────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    logger.info("Starting Query API on %s:%d", config.HOST, config.PORT)
    uvicorn.run(
        "app:app",
        host=config.HOST,
        port=config.PORT,
        log_level="info",
    )
