"""Embedding Server — ONNX INT8 /v1/embeddings API.

All models run on a single backend: ONNX INT8 (CPU, AVX-512 VNNI), keeping the
runtime image torch-free. Models that don't export cleanly via optimum (e.g.
nomic_bert / CodeRankEmbed) are pulled from pre-built ONNX releases at build
time (see download_models.py).

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
CODE_EMBEDDING_MODEL = os.environ.get("CODE_EMBEDDING_MODEL", "nomic-ai/CodeRankEmbed")

# Set of supported code embedding models (exactly one is active at runtime).
CODE_MODELS = {"nomic-ai/CodeRankEmbed", "microsoft/unixcoder-base"}

if CODE_EMBEDDING_MODEL not in CODE_MODELS:
    raise RuntimeError(
        f"CODE_EMBEDDING_MODEL={CODE_EMBEDDING_MODEL!r} is not valid. "
        f"Valid values: {sorted(CODE_MODELS)}"
    )

# Model registry: public_name -> (model_dir_name, backend, pooling)
# The public name is what callers pass in `request.model`; we keep
# "nomic-ai/CodeRankEmbed" stable so existing clients (indexers, retrievers)
# don't need to change after the backend swap to ONNX.
MODEL_REGISTRY = {
    "nomic-ai/CodeRankEmbed": ("CodeRankEmbed", "onnx-int8", "mean"),
    "microsoft/unixcoder-base": ("unixcoder-base", "onnx-int8", "cls"),
    "BAAI/bge-base-zh-v1.5": ("bge-base-zh-v1.5", "onnx-int8", "mean"),
}

# Runtime state: name -> dict with backend-specific handles
MODELS: dict[str, dict] = {}


def _create_session(onnx_path: str) -> ort.InferenceSession:
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = OMP_NUM_THREADS
    opts.inter_op_num_threads = 2
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return ort.InferenceSession(onnx_path, opts, providers=["CPUExecutionProvider"])


def load_onnx_model(name: str, model_dir: str, pooling: str) -> dict:
    """Load ONNX (preferring quantized) + tokenizers Tokenizer."""
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
    logger.info(
        "Loaded ONNX model '%s' from %s (dim=%d, pooling=%s)", name, onnx_file, dim, pooling
    )
    return {
        "backend": "onnx-int8",
        "pooling": pooling,
        "session": session,
        "tokenizer": tokenizer,
        "dim": dim,
        "lock": asyncio.Lock(),
    }


def _mean_pool_and_normalize(
    token_embeddings: np.ndarray, attention_mask: np.ndarray
) -> np.ndarray:
    """Mean pooling over non-padding tokens, then L2-normalize."""
    mask_expanded = attention_mask[:, :, np.newaxis].astype(np.float32)
    summed = np.sum(token_embeddings * mask_expanded, axis=1)
    counts = np.clip(mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
    pooled = summed / counts
    norms = np.linalg.norm(pooled, axis=1, keepdims=True)
    norms = np.clip(norms, a_min=1e-9, a_max=None)
    return pooled / norms


def _cls_pool_and_normalize(token_embeddings: np.ndarray) -> np.ndarray:
    """CLS token pooling (index 0), then L2-normalize."""
    pooled = token_embeddings[:, 0, :]
    norms = np.linalg.norm(pooled, axis=1, keepdims=True)
    norms = np.clip(norms, a_min=1e-9, a_max=None)
    return pooled / norms


@asynccontextmanager
async def lifespan(app):
    for name, (dir_name, backend, pooling) in MODEL_REGISTRY.items():
        if name in CODE_MODELS and name != CODE_EMBEDDING_MODEL:
            continue
        model_dir = os.path.join(MODEL_DIR, dir_name)
        if not os.path.isdir(model_dir):
            logger.warning("Model dir not found: %s — skipping '%s'", model_dir, name)
            continue
        try:
            if backend == "onnx-int8":
                MODELS[name] = load_onnx_model(name, model_dir, pooling)
            else:
                raise ValueError(f"Unknown backend '{backend}' for model '{name}'")
        except Exception as e:
            logger.error("Failed to load model '%s' (%s): %s", name, backend, e)
            raise
    if not MODELS:
        raise RuntimeError("No models loaded. Check EMBEDDING_MODEL_DIR and model directories.")
    yield


app = FastAPI(title="Embedding Server", lifespan=lifespan)


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
    code_models_info = {
        name: {"dim": info["dim"], "backend": info["backend"], "pooling": info["pooling"]}
        for name, info in MODELS.items()
        if name in CODE_MODELS
    }
    auxiliary_models_info = {
        name: {"dim": info["dim"], "backend": info["backend"], "pooling": info["pooling"]}
        for name, info in MODELS.items()
        if name not in CODE_MODELS
    }
    return {
        "status": "ok",
        "active_code_model": CODE_EMBEDDING_MODEL,
        "models": {
            "code": code_models_info,
            "auxiliary": auxiliary_models_info,
        },
    }


async def _encode_onnx(info: dict, texts: list[str]) -> tuple[np.ndarray, int]:
    session: ort.InferenceSession = info["session"]
    tokenizer: Tokenizer = info["tokenizer"]
    encodings = tokenizer.encode_batch(texts)
    max_len = max(len(e.ids) for e in encodings)
    input_ids = np.zeros((len(texts), max_len), dtype=np.int64)
    attention_mask = np.zeros((len(texts), max_len), dtype=np.int64)
    for i, enc in enumerate(encodings):
        length = len(enc.ids)
        input_ids[i, :length] = enc.ids
        attention_mask[i, :length] = enc.attention_mask

    loop = asyncio.get_event_loop()
    async with info["lock"]:
        def _run():
            feeds = {"input_ids": input_ids, "attention_mask": attention_mask}
            input_names = [inp.name for inp in session.get_inputs()]
            if "token_type_ids" in input_names:
                feeds["token_type_ids"] = np.zeros_like(input_ids)
            return session.run(None, feeds)
        outputs = await loop.run_in_executor(None, _run)

    pooling = info["pooling"]
    if pooling == "mean":
        vectors = _mean_pool_and_normalize(outputs[0], attention_mask)
    elif pooling == "cls":
        vectors = _cls_pool_and_normalize(outputs[0])
    else:
        raise ValueError(f"Unknown pooling strategy: {pooling!r}")

    token_count = int(sum(len(e.ids) for e in encodings))
    return vectors, token_count


@app.post("/v1/embeddings")
async def embeddings(request: EmbeddingRequest) -> EmbeddingResponse:
    texts = request.input if isinstance(request.input, list) else [request.input]
    if not texts:
        raise HTTPException(status_code=400, detail="input must not be empty")
    if len(texts) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400, detail=f"batch size {len(texts)} exceeds max {MAX_BATCH_SIZE}"
        )

    model_name = request.model
    if model_name not in MODELS:
        available = list(MODELS.keys())
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown model '{model_name}'. Available: {available}. "
                f"active_code_model={CODE_EMBEDDING_MODEL!r}. "
                f"To switch, restart embedding-server with CODE_EMBEDDING_MODEL=<name>."
            ),
        )

    info = MODELS[model_name]
    start = time.perf_counter()

    if info["backend"] == "onnx-int8":
        vectors, token_count = await _encode_onnx(info, texts)
    else:
        raise HTTPException(status_code=500, detail=f"Unknown backend '{info['backend']}'")

    latency = round((time.perf_counter() - start) * 1000, 1)
    logger.info(
        "Encoded %d texts with '%s' (%s) in %.1fms",
        len(texts), model_name, info["backend"], latency
    )

    data = [EmbeddingData(embedding=vec.tolist(), index=i) for i, vec in enumerate(vectors)]
    return EmbeddingResponse(
        data=data,
        model=model_name,
        usage={"prompt_tokens": token_count, "total_tokens": token_count},
    )


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host=host, port=port)
