"""
mcp_stdio.main_stdio 单元测试

测试 entry/mcp_stdio.py 中 main_stdio 函数是否正确调用
stdio_server context manager 和 server.run。

注意：main_stdio 在函数体内动态 import stdio_server，
所以需要在 mcp.server.stdio 模块层面 patch。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager


@pytest.mark.asyncio
async def test_main_stdio_calls_server_run():
    """main_stdio 应调用 server.run，并将流对象和初始化选项传入"""
    mock_read_stream = MagicMock(name="read_stream")
    mock_write_stream = MagicMock(name="write_stream")
    mock_init_opts = MagicMock(name="init_opts")

    # 模拟 stdio_server 为 async context manager
    @asynccontextmanager
    async def mock_stdio_server():
        yield (mock_read_stream, mock_write_stream)

    mock_run = AsyncMock()

    # main_stdio 在函数体内 import stdio_server，需要 patch mcp.server.stdio
    with patch("mcp.server.stdio.stdio_server", mock_stdio_server):
        import entry.mcp_stdio as mod
        with patch.object(mod.server, "run", mock_run):
            with patch.object(mod.server, "create_initialization_options", return_value=mock_init_opts):
                await mod.main_stdio()

    # 验证 server.run 被正确调用
    mock_run.assert_called_once_with(
        mock_read_stream,
        mock_write_stream,
        mock_init_opts,
    )


@pytest.mark.asyncio
async def test_main_stdio_uses_context_manager_streams():
    """main_stdio 从 stdio_server 拿到的流必须原样传给 server.run"""
    read_obj = object()
    write_obj = object()
    received_args = {}

    @asynccontextmanager
    async def mock_stdio():
        yield (read_obj, write_obj)

    async def capture_run(r, w, opts):
        received_args["read"] = r
        received_args["write"] = w
        received_args["opts"] = opts

    with patch("mcp.server.stdio.stdio_server", mock_stdio):
        import entry.mcp_stdio as mod
        with patch.object(mod.server, "run", side_effect=capture_run):
            with patch.object(mod.server, "create_initialization_options", return_value=None):
                await mod.main_stdio()

    assert received_args["read"] is read_obj
    assert received_args["write"] is write_obj
