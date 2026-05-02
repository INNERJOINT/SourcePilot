"""B7: Elicitation in search_code.

When query is empty/whitespace or shorter than 3 characters, search_code
calls ctx.elicit() to ask for a refined query.  This test wires an
in-memory elicitation_callback that returns ElicitResult(action="accept",
content={"refined_query": "foo"}) and verifies:

1. The elicitation roundtrip happened (callback was invoked).
2. The tool forwarded the refined query to /api/search.
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
        "content": "L1: void foo() {}",
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
async def test_search_code_elicits_when_query_too_short(monkeypatch):
    """Empty query triggers elicitation; accepted refined_query is forwarded."""
    monkeypatch.setenv("SOURCEPILOT_URL", SP_URL)
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")

    import entry.tools_state as _ts

    _ts.SOURCEPILOT_URL = SP_URL

    from mcp.shared.memory import create_connected_server_and_client_session
    from mcp.types import ElicitRequestParams, ElicitResult
    from mcp_server import mcp

    elicitation_called: list[str] = []
    search_bodies: list[dict] = []

    async def elicitation_callback(context, params: ElicitRequestParams):  # noqa: ANN001
        elicitation_called.append(params.message)
        return ElicitResult(action="accept", content={"refined_query": "foo"})

    def _capture_body(request: httpx.Request) -> httpx.Response:
        import json

        search_bodies.append(json.loads(request.content))
        return httpx.Response(200, json=MOCK_HITS)

    with respx.mock:
        respx.post(f"{SP_URL}/api/search").mock(side_effect=_capture_body)

        async with create_connected_server_and_client_session(
            mcp, elicitation_callback=elicitation_callback
        ) as session:
            await session.initialize()
            result = await session.call_tool(
                "search_code",
                {"inp": {"query": ""}},
            )

    # elicitation must have been invoked
    assert len(elicitation_called) == 1, f"Expected 1 elicitation call, got {elicitation_called}"
    msg = elicitation_called[0].lower()
    assert "too short" in msg or "specific" in msg

    # upstream /api/search must have been called with the refined query
    assert len(search_bodies) == 1, f"Expected 1 /api/search call, got {search_bodies}"
    assert search_bodies[0]["query"] == "foo", f"Expected query=foo, got {search_bodies[0]}"

    # result must contain content
    assert result.content, "Expected non-empty tool result"


@pytest.mark.anyio
async def test_search_code_elicitation_declined_returns_empty(monkeypatch):
    """When user declines elicitation, search_code returns empty hits."""
    monkeypatch.setenv("SOURCEPILOT_URL", SP_URL)
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")

    import entry.tools_state as _ts

    _ts.SOURCEPILOT_URL = SP_URL

    from mcp.shared.memory import create_connected_server_and_client_session
    from mcp.types import ElicitRequestParams, ElicitResult
    from mcp_server import mcp

    async def elicitation_callback(context, params: ElicitRequestParams):  # noqa: ANN001
        return ElicitResult(action="decline")

    with respx.mock:
        # /api/search should NOT be called
        mock_route = respx.post(f"{SP_URL}/api/search").mock(
            return_value=httpx.Response(200, json=[])
        )

        async with create_connected_server_and_client_session(
            mcp, elicitation_callback=elicitation_callback
        ) as session:
            await session.initialize()
            result = await session.call_tool(
                "search_code",
                {"inp": {"query": "x"}},  # length 1 → triggers elicitation
            )

    # upstream search must NOT have been called
    assert not mock_route.called, "/api/search should not be called when elicitation is declined"

    # result content should represent empty hits
    content_str = str(result.content)
    assert "total" in content_str or "hits" in content_str
