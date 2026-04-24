"""Embedding Server — ONNX Runtime multi-model /v1/embeddings API.

Loads multiple ONNX INT8-quantized models, routes by "model" field in request.
CPU-only, optimized for i9-9980XE (18C/36T).
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import onnxruntime as ort
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from tokenizers import Tokenizer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OMP_NUM_THREADS = int(os.environ.get("OMP_NUM_THREADS", "18"))
MAX_BATCH_SIZE = int(os.environ.get("EMBEDDING_MAX_BATCH_SIZE", "64"))
MODEL_DIR = os.environ.get("EMBEDDING_MODEL_DIR", "/app/models")

# Model registry: name -> model_dir_name
MODEL_REGISTRY = {
    "nomic-ai/CodeRankEmbed": "CodeRankEmbed",
    "BAAI/bge-base-zh-v1.5": "bge-base-zh-v1.5",
}

# Runtime state: name -> (session, tokenizer, dim, lock)
MODELS: dict[str, tuple] = {}


def _create_session(onnx_path: str) -> ort.InferenceSession:
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = OMP_NUM_THREADS
    opts.inter_op_num_threads = 2
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return ort.InferenceSession(onnx_path, opts, providers=["CPUExecutionProvider"])


def load_model(name: str, model_dir: str) -> tuple:
    """Load ONNX model and its tokenizer."""
    # Find the ONNX file (prefer quantized)
    model_path = Path(model_dir)
    onnx_file = model_path / "model_quantized.onnx"
    if not onnx_file.exists():
        onnx_file = model_path / "model.onnx"
    if not onnx_file.exists():
        raise FileNotFoundError(f"No ONNX model found in {model_dir}")

    session = _create_session(str(onnx_file))
    tokenizer = Tokenizer.from_file(str(model_path / "tokenizer.json"))
    dim = session.get_outputs()[0].shape[-1]
    assert dim == 768, f"Model {name} has dim {dim}, expected 768"
    lock = asyncio.Lock()
    logger.info("Loaded model '%s' from %s (dim=%d)", name, onnx_file, dim)
    return session, tokenizer, dim, lock


def _mean_pool_and_normalize(token_embeddings: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    """Mean pooling over non-padding tokens, then L2-normalize."""
    mask_expanded = attention_mask[:, :, np.newaxis].astype(np.float32)
    summed = np.sum(token_embeddings * mask_expanded, axis=1)
    counts = np.clip(mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
    pooled = summed / counts
    norms = np.linalg.norm(pooled, axis=1, keepdims=True)
    norms = np.clip(norms, a_min=1e-9, a_max=None)
    return pooled / norms


@asynccontextmanager
async def lifespan(app):
    for name, dir_name in MODEL_REGISTRY.items():
        model_dir = os.path.join(MODEL_DIR, dir_name)
        if os.path.isdir(model_dir):
            try:
                MODELS[name] = load_model(name, model_dir)
            except Exception as e:
                logger.error("Failed to load model '%s': %s", name, e)
                raise
        else:
            logger.warning("Model dir not found: %s — skipping '%s'", model_dir, name)
    if not MODELS:
        raise RuntimeError("No models loaded. Check EMBEDDING_MODEL_DIR and model directories.")
    yield


app = FastAPI(title="ONNX Embedding Server", lifespan=lifespan)


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str


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
    if not MODELS:
        raise HTTPException(status_code=503, detail="No models loaded")
    models_info = {name: {"dim": info[2]} for name, info in MODELS.items()}
    return {"status": "ok", "models": models_info}


@app.post("/v1/embeddings")
async def embeddings(request: EmbeddingRequest) -> EmbeddingResponse:
    texts = request.input if isinstance(request.input, list) else [request.input]
    if not texts:
        raise HTTPException(status_code=400, detail="input must not be empty")
    if len(texts) > MAX_BATCH_SIZE:
        raise HTTPException(status_code=400, detail=f"batch size {len(texts)} exceeds max {MAX_BATCH_SIZE}")

    model_name = request.model
    if model_name not in MODELS:
        available = list(MODELS.keys())
        raise HTTPException(status_code=400, detail=f"Unknown model '{model_name}'. Available: {available}")

    session, tokenizer, dim, lock = MODELS[model_name]

    # Tokenize
    encodings = tokenizer.encode_batch(texts)
    max_len = max(len(e.ids) for e in encodings)
    input_ids = np.zeros((len(texts), max_len), dtype=np.int64)
    attention_mask = np.zeros((len(texts), max_len), dtype=np.int64)
    for i, enc in enumerate(encodings):
        length = len(enc.ids)
        input_ids[i, :length] = enc.ids
        attention_mask[i, :length] = enc.attention_mask

    start = time.perf_counter()
    loop = asyncio.get_event_loop()

    async with lock:
        def _run_inference():
            feeds = {"input_ids": input_ids, "attention_mask": attention_mask}
            # Some models also need token_type_ids
            input_names = [inp.name for inp in session.get_inputs()]
            if "token_type_ids" in input_names:
                feeds["token_type_ids"] = np.zeros_like(input_ids)
            return session.run(None, feeds)

        outputs = await loop.run_in_executor(None, _run_inference)

    token_embeddings = outputs[0]  # (batch, seq_len, dim)
    vectors = _mean_pool_and_normalize(token_embeddings, attention_mask)

    latency = round((time.perf_counter() - start) * 1000, 1)
    logger.info("Encoded %d texts with '%s' in %.1fms", len(texts), model_name, latency)

    data = [
        EmbeddingData(embedding=vec.tolist(), index=i)
        for i, vec in enumerate(vectors)
    ]
    token_count = sum(len(e.ids) for e in encodings)
    return EmbeddingResponse(
        data=data,
        model=model_name,
        usage={"prompt_tokens": token_count, "total_tokens": token_count},
    )


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host=host, port=port)
