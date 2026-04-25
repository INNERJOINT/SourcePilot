"""Unit tests for lifespan conditional model loading in embedding server."""

import os
import sys
import types
from unittest.mock import MagicMock, patch

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

# Add embedding-server to path
_SERVER_DIR = os.path.join(os.path.dirname(__file__), "../../../deploy/dense/embedding-server")
sys.path.insert(0, _SERVER_DIR)

os.environ.setdefault("CODE_EMBEDDING_MODEL", "nomic-ai/CodeRankEmbed")

import pytest  # noqa: E402


def _reload_server(code_embedding_model: str):
    """Reload server module with a specific CODE_EMBEDDING_MODEL env var."""
    with patch.dict(os.environ, {"CODE_EMBEDDING_MODEL": code_embedding_model}):
        if "server" in sys.modules:
            del sys.modules["server"]
        import server as srv
        return srv


def test_model_registry_has_all_three_entries():
    srv = _reload_server("nomic-ai/CodeRankEmbed")
    assert "nomic-ai/CodeRankEmbed" in srv.MODEL_REGISTRY
    assert "microsoft/unixcoder-base" in srv.MODEL_REGISTRY
    assert "BAAI/bge-base-zh-v1.5" in srv.MODEL_REGISTRY
    assert len(srv.MODEL_REGISTRY) == 3


def test_lifespan_loads_only_active_code_model_and_bge(monkeypatch):
    """When CODE_EMBEDDING_MODEL=nomic-ai/CodeRankEmbed, lifespan skips unixcoder."""
    srv = _reload_server("nomic-ai/CodeRankEmbed")

    loaded_names = []

    def mock_load(name, model_dir, pooling):
        loaded_names.append(name)
        return {
            "backend": "onnx-int8",
            "pooling": pooling,
            "session": MagicMock(),
            "tokenizer": MagicMock(),
            "dim": 768,
            "lock": MagicMock(),
        }

    monkeypatch.setattr(srv, "load_onnx_model", mock_load)
    monkeypatch.setattr(os.path, "isdir", lambda p: True)
    monkeypatch.setattr(srv, "MODELS", {})

    import asyncio

    async def run():
        async with srv.lifespan(srv.app):
            pass

    asyncio.run(run())

    assert "nomic-ai/CodeRankEmbed" in loaded_names
    assert "BAAI/bge-base-zh-v1.5" in loaded_names
    assert "microsoft/unixcoder-base" not in loaded_names


def test_lifespan_loads_unixcoder_when_selected(monkeypatch):
    """When CODE_EMBEDDING_MODEL=microsoft/unixcoder-base, lifespan skips CodeRankEmbed."""
    srv = _reload_server("microsoft/unixcoder-base")

    loaded_names = []

    def mock_load(name, model_dir, pooling):
        loaded_names.append(name)
        return {
            "backend": "onnx-int8",
            "pooling": pooling,
            "session": MagicMock(),
            "tokenizer": MagicMock(),
            "dim": 768,
            "lock": MagicMock(),
        }

    monkeypatch.setattr(srv, "load_onnx_model", mock_load)
    monkeypatch.setattr(os.path, "isdir", lambda p: True)
    monkeypatch.setattr(srv, "MODELS", {})

    import asyncio

    async def run():
        async with srv.lifespan(srv.app):
            pass

    asyncio.run(run())

    assert "microsoft/unixcoder-base" in loaded_names
    assert "BAAI/bge-base-zh-v1.5" in loaded_names
    assert "nomic-ai/CodeRankEmbed" not in loaded_names


def test_invalid_code_embedding_model_raises():
    with pytest.raises(RuntimeError, match="not valid"):
        _reload_server("unknown/model")
