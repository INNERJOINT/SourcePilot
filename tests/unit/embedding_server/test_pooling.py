"""Unit tests for pooling functions in embedding server."""

import os
import sys
import types
from unittest.mock import MagicMock

# Stub heavy deps that aren't in the test env (they live in the embedding-server image only)
for _mod in ("onnxruntime", "fastapi", "tokenizers", "uvicorn", "pydantic"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
# Pydantic BaseModel must be importable as a class — give it a real class
class _BaseModel:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
sys.modules["pydantic"].BaseModel = _BaseModel
# FastAPI app/HTTPException stubs
sys.modules["fastapi"].FastAPI = MagicMock
class _HTTPException(Exception):
    def __init__(self, status_code=500, detail=""):
        self.status_code, self.detail = status_code, detail
sys.modules["fastapi"].HTTPException = _HTTPException
# onnxruntime symbols touched at import time
ort = sys.modules["onnxruntime"]
ort.SessionOptions = MagicMock
ort.InferenceSession = MagicMock
ort.GraphOptimizationLevel = types.SimpleNamespace(ORT_ENABLE_ALL=99)
ort.ExecutionMode = types.SimpleNamespace(ORT_SEQUENTIAL=0)
# tokenizers.Tokenizer
sys.modules["tokenizers"].Tokenizer = MagicMock

# Add embedding-server to path so we can import server module directly
_SERVER_DIR = os.path.join(os.path.dirname(__file__), "../../../deploy/dense/embedding-server")
sys.path.insert(0, _SERVER_DIR)

# Set required env before import to avoid RuntimeError on CODE_EMBEDDING_MODEL validation
os.environ.setdefault("CODE_EMBEDDING_MODEL", "nomic-ai/CodeRankEmbed")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from server import _cls_pool_and_normalize  # noqa: E402


@pytest.fixture
def token_embeddings():
    """Shape (B=2, T=5, D=8) with distinct CLS tokens."""
    rng = np.random.default_rng(42)
    return rng.standard_normal((2, 5, 8)).astype(np.float32)


def test_cls_pool_takes_index_zero(token_embeddings):
    result = _cls_pool_and_normalize(token_embeddings)
    # Shape check
    assert result.shape == (2, 8)
    # The pooled vectors should be proportional to token_embeddings[:, 0, :]
    for i in range(2):
        cls_vec = token_embeddings[i, 0, :]
        normed = cls_vec / np.linalg.norm(cls_vec)
        np.testing.assert_allclose(result[i], normed, atol=1e-6)


def test_cls_pool_l2_norm(token_embeddings):
    result = _cls_pool_and_normalize(token_embeddings)
    norms = np.linalg.norm(result, axis=1)
    for norm in norms:
        assert 0.999 <= norm <= 1.001, f"L2 norm {norm} out of [0.999, 1.001]"


def test_cls_pool_zero_vector_clipped():
    """Near-zero CLS vector should not produce NaN (norm clipped to 1e-9)."""
    embeddings = np.zeros((1, 3, 4), dtype=np.float32)
    result = _cls_pool_and_normalize(embeddings)
    assert not np.any(np.isnan(result))
