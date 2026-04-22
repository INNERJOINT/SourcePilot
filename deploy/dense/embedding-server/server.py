"""Embedding Server — OpenAI-compatible /v1/embeddings API.

使用 sentence-transformers 加载本地模型，提供与 OpenAI embedding API 兼容的 HTTP 接口。
"""

import logging
import os
import time
from contextlib import asynccontextmanager

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "microsoft/unixcoder-base")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))

model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global model
    if model is None:
        logger.info("Loading model: %s", MODEL_NAME)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = SentenceTransformer(MODEL_NAME, device=device)
        logger.info("Model loaded on %s, dim=%d", device, model.get_sentence_embedding_dimension())
    return model


@asynccontextmanager
async def lifespan(app):
    get_model()
    yield


app = FastAPI(title="Embedding Server", lifespan=lifespan)


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str = MODEL_NAME


class EmbeddingData(BaseModel):
    embedding: list[float]
    index: int
    object: str = "embedding"


class EmbeddingResponse(BaseModel):
    data: list[EmbeddingData]
    model: str
    object: str = "list"
    usage: dict


@app.get("/health")
async def health():
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {"status": "ok", "model": MODEL_NAME, "dim": EMBEDDING_DIM}


@app.post("/v1/embeddings")
async def embeddings(request: EmbeddingRequest) -> EmbeddingResponse:
    texts = request.input if isinstance(request.input, list) else [request.input]
    if not texts:
        raise HTTPException(status_code=400, detail="input must not be empty")

    start = time.perf_counter()
    m = get_model()
    vectors = m.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    latency = round((time.perf_counter() - start) * 1000, 1)
    logger.info("Encoded %d texts in %.1fms", len(texts), latency)

    data = [
        EmbeddingData(embedding=vec.tolist(), index=i)
        for i, vec in enumerate(vectors)
    ]
    token_count = sum(len(t.split()) for t in texts)
    return EmbeddingResponse(
        data=data,
        model=request.model,
        usage={"prompt_tokens": token_count, "total_tokens": token_count},
    )


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host=host, port=port)
