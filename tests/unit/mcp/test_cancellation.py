"""Tests: B5 — Cancellation in search_regex.

Pattern: wrap the upstream httpx call inside the anyio cancel scope that the
SDK automatically sets up per-request. When the client sends
notifications/cancelled, the SDK calls RequestResponder.cancel(), which
calls _cancel_scope.cancel(), raising anyio.get_cancelled_exc_class() inside
the handler. The search_regex handler catches this, logs it, and re-raises so
no result message is emitted.

To replicate this pattern for other long-running tools, wrap the upstream call
in a try/except block that catches ``anyio.get_cancelled_exc_class()`` and
re-raises, e.g.:

    cancelled_exc = anyio.get_cancelled_exc_class()
    try:
        results = await _post(ctx, "/api/...", body, trace_id)
    except cancelled_exc:
        logger.info("tool cancelled")
        raise
"""

from __future__ import annotations

import anyio
import httpx
import respx
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    CancelledNotification,
    CancelledNotificationParams,
    ClientNotification,
)


async def test_search_regex_cancellation_aborts_http_call():
    """CancelledNotification while search_regex is pending aborts the httpx call.

    The SDK wraps each request handler in an anyio CancelScope. Sending
    notifications/cancelled triggers RequestResponder.cancel(), which cancels
    that scope. search_regex's try/except block re-raises the CancelledError,
    so the handler never returns a result — the client receives an error
    response (McpError) instead.
    """
    # Coordinate: signal when the slow mock is entered (httpx call in flight)
    httpx_started = anyio.Event()

    async def slow_response(request: httpx.Request) -> httpx.Response:
        httpx_started.set()
        # Block indefinitely; cancelled when the anyio scope is cancelled
        await anyio.sleep(30)
        return httpx.Response(200, json=[])  # pragma: no cover

    with respx.mock:
        respx.post("http://mock-sourcepilot:9000/api/search_regex").mock(
            side_effect=slow_response
        )

        from mcp_server import mcp  # FastMCP instance with lifespan

        async with create_connected_server_and_client_session(
            mcp._mcp_server  # type: ignore[attr-defined]
        ) as client_session:
            # After initialize(), the next request id is 1 (initialize used 0).
            tool_request_id = client_session._request_id  # type: ignore[attr-defined]

            result_holder: list[CallToolResult] = []
            error_holder: list[McpError] = []

            async def call_tool_task() -> None:
                try:
                    result = await client_session.send_request(
                        CallToolRequest(
                            params=CallToolRequestParams(
                                name="search_regex",
                                arguments={"inp": {"pattern": "startActivity"}},
                            )
                        ),
                        CallToolResult,
                    )
                    result_holder.append(result)  # pragma: no cover
                except McpError as exc:
                    error_holder.append(exc)

            with anyio.fail_after(5):
                async with anyio.create_task_group() as tg:
                    tg.start_soon(call_tool_task)

                    # Wait until the httpx call is actually in-flight
                    await httpx_started.wait()

                    # Send cancellation for the in-flight request
                    await client_session.send_notification(
                        ClientNotification(
                            CancelledNotification(
                                params=CancelledNotificationParams(
                                    requestId=tool_request_id,
                                    reason="test cancellation",
                                )
                            )
                        )
                    )

            # The tool call must have raised McpError (cancelled), not returned a result
            assert len(result_holder) == 0, "Handler should not have returned a result"
            assert len(error_holder) == 1, "Handler should have raised McpError on cancel"
