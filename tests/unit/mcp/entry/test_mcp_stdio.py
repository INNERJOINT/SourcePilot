"""
mcp_stdio.main_stdio 单元测试 (FastMCP)

Tests entry/mcp_stdio.py which delegates to mcp.run_stdio_async().
"""


from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_main_stdio_calls_run_stdio_async():
    """main_stdio() should call mcp.run_stdio_async()."""
    mock_run = AsyncMock()

    with patch("entry.mcp_stdio.mcp") as mock_mcp:
        mock_mcp.run_stdio_async = mock_run
        from entry.mcp_stdio import main_stdio

        await main_stdio()

    mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_main_stdio_no_system_exit():
    """main_stdio() completes without SystemExit when run_stdio_async succeeds."""
    with patch("entry.mcp_stdio.mcp") as mock_mcp:
        mock_mcp.run_stdio_async = AsyncMock(return_value=None)
        from entry.mcp_stdio import main_stdio

        try:
            await main_stdio()
        except SystemExit:
            pytest.fail("main_stdio() raised SystemExit unexpectedly")
