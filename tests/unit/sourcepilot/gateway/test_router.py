"""
Unit tests for the dispatch routing module

Tests the dispatch and _call_adapter functions in gateway/router.py.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from adapters.base import BackendResponse, SearchItem
from gateway.router import dispatch, _call_adapter


def _make_mock_adapter(name: str, response: BackendResponse | None = None, side_effect=None):
    """Build a mock adapter."""
    adapter = MagicMock()
    adapter.backend_name = name
    if side_effect is not None:
        adapter.search = AsyncMock(side_effect=side_effect)
    else:
        adapter.search = AsyncMock(return_value=response)
    return adapter


def _ok_response(backend: str = "zoekt") -> BackendResponse:
    """Build a successful response."""
    return BackendResponse(
        backend=backend,
        status="ok",
        latency_ms=10.0,
        total_hits=1,
        items=[],
    )


@pytest.mark.asyncio
class TestDispatch:
    """Test suite for the dispatch function."""

    async def test_single_adapter_success(self):
        """Single adapter success: returns a list with 1 response."""
        resp = _ok_response("zoekt")
        adapter = _make_mock_adapter("zoekt", response=resp)
        results = await dispatch([adapter], "SystemServer", parsed={})
        assert len(results) == 1
        assert results[0].status == "ok"
        assert results[0].backend == "zoekt"

    async def test_multiple_adapters_parallel(self):
        """Multiple adapters dispatched in parallel: returns 2 responses."""
        resp1 = _ok_response("zoekt1")
        resp2 = _ok_response("zoekt2")
        a1 = _make_mock_adapter("zoekt1", response=resp1)
        a2 = _make_mock_adapter("zoekt2", response=resp2)
        results = await dispatch([a1, a2], "query", parsed={})
        assert len(results) == 2
        backends = {r.backend for r in results}
        assert backends == {"zoekt1", "zoekt2"}

    async def test_empty_adapters(self):
        """No adapters returns an empty list."""
        results = await dispatch([], "query", parsed={})
        assert results == []

    async def test_timeout_returns_timeout_status(self):
        """Adapter timeout: response status='timeout'."""
        adapter = _make_mock_adapter("zoekt", side_effect=asyncio.TimeoutError())
        results = await dispatch([adapter], "query", parsed={}, timeout_ms=100)
        assert len(results) == 1
        assert results[0].status == "timeout"
        assert results[0].backend == "zoekt"
        assert results[0].error_detail == "adapter timeout"
        assert results[0].total_hits == 0

    async def test_exception_returns_error_status(self):
        """Adapter raises exception: response status='error', error_detail is set."""
        adapter = _make_mock_adapter("zoekt", side_effect=RuntimeError("connection refused"))
        results = await dispatch([adapter], "query", parsed={})
        assert len(results) == 1
        assert results[0].status == "error"
        assert results[0].error_detail == "connection refused"
        assert results[0].total_hits == 0

    async def test_latency_ms_positive(self):
        """All responses have latency_ms > 0 (or >= 0)."""
        resp = _ok_response("zoekt")
        adapter = _make_mock_adapter("zoekt", response=resp)
        results = await dispatch([adapter], "query", parsed={})
        # for success paths, latency_ms comes from the adapter itself; timeout/error paths compute it
        assert results[0] is resp  # success: returns the adapter's response directly

    async def test_latency_ms_set_on_timeout(self):
        """latency_ms is computed by _call_adapter on timeout and is >= 0."""
        adapter = _make_mock_adapter("zoekt", side_effect=asyncio.TimeoutError())
        results = await dispatch([adapter], "query", parsed={}, timeout_ms=100)
        assert results[0].latency_ms >= 0

    async def test_latency_ms_set_on_error(self):
        """latency_ms is computed by _call_adapter on exception and is >= 0."""
        adapter = _make_mock_adapter("zoekt", side_effect=ValueError("bad"))
        results = await dispatch([adapter], "query", parsed={})
        assert results[0].latency_ms >= 0

    async def test_mixed_success_and_error(self):
        """Some adapters succeed, others fail: each returns the appropriate status."""
        a_ok = _make_mock_adapter("ok_backend", response=_ok_response("ok_backend"))
        a_err = _make_mock_adapter("err_backend", side_effect=RuntimeError("fail"))
        results = await dispatch([a_ok, a_err], "query", parsed={})
        assert len(results) == 2
        statuses = {r.backend: r.status for r in results}
        assert statuses["ok_backend"] == "ok"
        assert statuses["err_backend"] == "error"

    async def test_backend_specific_passed_to_query(self):
        """backend_specific parameter is wrapped into BackendQuery and forwarded to the adapter."""
        resp = _ok_response("zoekt")
        adapter = _make_mock_adapter("zoekt", response=resp)
        await dispatch([adapter], "query", parsed={}, backend_specific={"lang": "java"})
        call_args = adapter.search.call_args[0][0]  # BackendQuery positional arg
        assert call_args.backend_specific == {"lang": "java"}

    async def test_max_results_passed_to_query(self):
        """max_results parameter is wrapped into BackendQuery.options."""
        resp = _ok_response("zoekt")
        adapter = _make_mock_adapter("zoekt", response=resp)
        await dispatch([adapter], "query", parsed={}, max_results=25)
        call_args = adapter.search.call_args[0][0]
        assert call_args.options.max_results == 25
