"""
路由分发模块单元测试

测试 gateway/router.py 中的 dispatch 和 _call_adapter 函数。
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from adapters.base import BackendResponse, SearchItem
from gateway.router import dispatch, _call_adapter


def _make_mock_adapter(name: str, response: BackendResponse | None = None, side_effect=None):
    """构造 mock 适配器"""
    adapter = MagicMock()
    adapter.backend_name = name
    if side_effect is not None:
        adapter.search = AsyncMock(side_effect=side_effect)
    else:
        adapter.search = AsyncMock(return_value=response)
    return adapter


def _ok_response(backend: str = "zoekt") -> BackendResponse:
    """构造成功响应"""
    return BackendResponse(
        backend=backend,
        status="ok",
        latency_ms=10.0,
        total_hits=1,
        items=[],
    )


@pytest.mark.asyncio
class TestDispatch:
    """dispatch 函数测试套件"""

    async def test_single_adapter_success(self):
        """单适配器成功：返回包含 1 个响应的列表"""
        resp = _ok_response("zoekt")
        adapter = _make_mock_adapter("zoekt", response=resp)
        results = await dispatch([adapter], "SystemServer", parsed={})
        assert len(results) == 1
        assert results[0].status == "ok"
        assert results[0].backend == "zoekt"

    async def test_multiple_adapters_parallel(self):
        """多适配器并行分发：返回 2 个响应"""
        resp1 = _ok_response("zoekt1")
        resp2 = _ok_response("zoekt2")
        a1 = _make_mock_adapter("zoekt1", response=resp1)
        a2 = _make_mock_adapter("zoekt2", response=resp2)
        results = await dispatch([a1, a2], "query", parsed={})
        assert len(results) == 2
        backends = {r.backend for r in results}
        assert backends == {"zoekt1", "zoekt2"}

    async def test_empty_adapters(self):
        """无适配器时返回空列表"""
        results = await dispatch([], "query", parsed={})
        assert results == []

    async def test_timeout_returns_timeout_status(self):
        """适配器超时：响应 status='timeout'"""
        adapter = _make_mock_adapter("zoekt", side_effect=asyncio.TimeoutError())
        results = await dispatch([adapter], "query", parsed={}, timeout_ms=100)
        assert len(results) == 1
        assert results[0].status == "timeout"
        assert results[0].backend == "zoekt"
        assert results[0].error_detail == "adapter timeout"
        assert results[0].total_hits == 0

    async def test_exception_returns_error_status(self):
        """适配器抛出异常：响应 status='error'，error_detail 有内容"""
        adapter = _make_mock_adapter("zoekt", side_effect=RuntimeError("connection refused"))
        results = await dispatch([adapter], "query", parsed={})
        assert len(results) == 1
        assert results[0].status == "error"
        assert results[0].error_detail == "connection refused"
        assert results[0].total_hits == 0

    async def test_latency_ms_positive(self):
        """所有响应都有 latency_ms > 0（或 >= 0）"""
        resp = _ok_response("zoekt")
        adapter = _make_mock_adapter("zoekt", response=resp)
        results = await dispatch([adapter], "query", parsed={})
        # 正常响应的 latency_ms 来自 adapter 本身，但 timeout/error 路径会计算
        assert results[0] is resp  # 成功时直接返回 adapter 的响应

    async def test_latency_ms_set_on_timeout(self):
        """超时时 latency_ms 由 _call_adapter 自行计算并 >= 0"""
        adapter = _make_mock_adapter("zoekt", side_effect=asyncio.TimeoutError())
        results = await dispatch([adapter], "query", parsed={}, timeout_ms=100)
        assert results[0].latency_ms >= 0

    async def test_latency_ms_set_on_error(self):
        """异常时 latency_ms 由 _call_adapter 自行计算并 >= 0"""
        adapter = _make_mock_adapter("zoekt", side_effect=ValueError("bad"))
        results = await dispatch([adapter], "query", parsed={})
        assert results[0].latency_ms >= 0

    async def test_mixed_success_and_error(self):
        """部分适配器成功，部分失败：各自返回对应状态"""
        a_ok = _make_mock_adapter("ok_backend", response=_ok_response("ok_backend"))
        a_err = _make_mock_adapter("err_backend", side_effect=RuntimeError("fail"))
        results = await dispatch([a_ok, a_err], "query", parsed={})
        assert len(results) == 2
        statuses = {r.backend: r.status for r in results}
        assert statuses["ok_backend"] == "ok"
        assert statuses["err_backend"] == "error"

    async def test_backend_specific_passed_to_query(self):
        """backend_specific 参数被包装到 BackendQuery 并传给适配器"""
        resp = _ok_response("zoekt")
        adapter = _make_mock_adapter("zoekt", response=resp)
        await dispatch([adapter], "query", parsed={}, backend_specific={"lang": "java"})
        call_args = adapter.search.call_args[0][0]  # BackendQuery 位置参数
        assert call_args.backend_specific == {"lang": "java"}

    async def test_max_results_passed_to_query(self):
        """max_results 参数被包装到 BackendQuery.options"""
        resp = _ok_response("zoekt")
        adapter = _make_mock_adapter("zoekt", response=resp)
        await dispatch([adapter], "query", parsed={}, max_results=25)
        call_args = adapter.search.call_args[0][0]
        assert call_args.options.max_results == 25
