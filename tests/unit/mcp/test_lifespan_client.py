"""Tests: H2 — lifespan-owned HTTP client is created and closed."""

import asyncio
import contextlib

import httpx


def test_lifespan_creates_and_closes_client(monkeypatch):
    """Lifespan context manager creates AsyncClient and closes it on exit."""
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")

    closed_clients: list = []

    async def _run_lifespan():
        from entry.handlers import _set_http_client

        @contextlib.asynccontextmanager
        async def fake_run():
            yield

        @contextlib.asynccontextmanager
        async def lifespan(app):
            client = httpx.AsyncClient(timeout=30.0)
            _set_http_client(client)
            try:
                async with fake_run():
                    yield client
            finally:
                await client.aclose()

        async with lifespan(None) as client:
            closed_clients.append(client)

    asyncio.run(_run_lifespan())

    assert len(closed_clients) == 1
    client = closed_clients[0]
    assert client.is_closed
