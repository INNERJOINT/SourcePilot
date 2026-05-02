"""Unit tests for _post() error paths in entry.handlers."""

import httpx
import pytest
import respx


@pytest.fixture(autouse=True)
def _inject_http_client(monkeypatch):
    """Use the real httpx.AsyncClient already set by conftest _http_client_fixture."""
    # conftest.py autouse fixture already sets the ContextVar — nothing extra needed.
    pass


@pytest.mark.asyncio
async def test_post_5xx_non_json_raises_runtime_error():
    """5xx response with non-JSON body raises RuntimeError with status code."""
    from entry.handlers import _post

    with respx.mock(base_url="http://mock-sourcepilot:9000") as mock:
        mock.post("/api/search").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        with pytest.raises(RuntimeError, match=r"SourcePilot error \(500\): 500"):
            await _post("/api/search", {"query": "foo"}, "trace-abc")


@pytest.mark.asyncio
async def test_post_5xx_json_error_key_in_message():
    """5xx response with JSON {'error': 'x'} raises RuntimeError with the error message."""
    from entry.handlers import _post

    with respx.mock(base_url="http://mock-sourcepilot:9000") as mock:
        mock.post("/api/search").mock(
            return_value=httpx.Response(503, json={"error": "service unavailable"})
        )
        with pytest.raises(RuntimeError, match=r"SourcePilot error \(503\): service unavailable"):
            await _post("/api/search", {"query": "bar"}, "trace-xyz")
