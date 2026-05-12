"""B4: Progress notifications emitted by search_code.

Uses create_connected_server_and_client_session (in-memory transport) to call
search_code with a progress_callback and asserts at least 2 progress events are
received.  SourcePilot /api/search is mocked with respx — no live backend needed.
"""

from __future__ import annotations

import os
import sys

import httpx
import pytest
import respx

_mcp_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "mcp-server")
if _mcp_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_mcp_dir))

SP_URL = "http://mock-sourcepilot:9000"

MOCK_HITS = [
    {
        "title": "frameworks/base/SystemServer.java",
        "content": "L1: void startBootstrapServices() {}",
        "score": 0.9,
        "metadata": {
            "repo": "frameworks/base",
            "path": "SystemServer.java",
            "start_line": 1,
            "end_line": 1,
        },
    }
]


@pytest.mark.anyio
async def test_search_code_emits_two_progress_notifications(monkeypatch):
    """search_code must emit progress(0/2) before the call and progress(2/2) after."""
    monkeypatch.setenv("SOURCEPILOT_URL", SP_URL)
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")

    import entry.tools_state as _ts

    _ts.SOURCEPILOT_URL = SP_URL  # patch the already-imported constant

    from mcp.shared.memory import create_connected_server_and_client_session
    from mcp_server import mcp

    progress_events: list[tuple[float, float]] = []

    def _on_progress(progress: float, total: float | None, message: str | None) -> None:
        progress_events.append((progress, total))

    with respx.mock:
        respx.post(f"{SP_URL}/api/search").mock(
            return_value=httpx.Response(200, json=MOCK_HITS)
        )

        async with create_connected_server_and_client_session(mcp) as session:
            await session.initialize()
            await session.call_tool(
                "search_code",
                {"inp": {"project": "aosp_project", "query": "startBootstrapServices"}},
                progress_callback=_on_progress,
            )

    assert len(progress_events) >= 2, (
        f"Expected at least 2 progress notifications, got {len(progress_events)}: {progress_events}"
    )
    # First notification: progress=0, total=2
    assert progress_events[0] == (0.0, 2.0), f"First progress unexpected: {progress_events[0]}"
    # Last notification: progress=2, total=2
    assert progress_events[-1] == (2.0, 2.0), f"Last progress unexpected: {progress_events[-1]}"
