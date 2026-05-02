"""
MCP layer unit-test configuration.

Adds mcp-server/ to the Python path so tests can directly import MCP modules.
"""

import asyncio
import os
import sys

import httpx
import pytest

# Add mcp-server/ to Python path
_mcp_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "mcp-server")
if _mcp_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_mcp_dir))


@pytest.fixture(autouse=True)
def _set_sourcepilot_url(monkeypatch):
    monkeypatch.setenv("SOURCEPILOT_URL", "http://mock-sourcepilot:9000")


@pytest.fixture(autouse=True)
def _http_client_fixture():
    """Provide a real httpx.AsyncClient via ContextVar so handlers can use _get_http_client().

    Also sets the resource client used by entry/resources.py.
    """
    from entry.handlers import _set_http_client
    from entry.resources import set_resource_client

    client = httpx.AsyncClient(timeout=30.0)
    _set_http_client(client)
    set_resource_client(client)
    yield client
    try:
        asyncio.get_event_loop().run_until_complete(client.aclose())
    except RuntimeError:
        # No running event loop in sync teardown — client will be GC'd
        pass
