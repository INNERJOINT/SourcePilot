"""Tests for EmbeddingClient."""

import pytest
import respx
import httpx

from adapters.embedding import EmbeddingClient


@pytest.fixture
def client():
    return EmbeddingClient(base_url="http://localhost:8080/v1", model="unixcoder-base")


class TestEmbed:
    @respx.mock
    @pytest.mark.asyncio
    async def test_batch_embed(self, client):
        respx.post("http://localhost:8080/v1/embeddings").mock(
            return_value=httpx.Response(200, json={
                "data": [
                    {"embedding": [0.1, 0.2, 0.3], "index": 0},
                    {"embedding": [0.4, 0.5, 0.6], "index": 1},
                ],
            })
        )
        result = await client.embed(["hello", "world"])
        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]
        assert result[1] == [0.4, 0.5, 0.6]

    @respx.mock
    @pytest.mark.asyncio
    async def test_embed_preserves_order(self, client):
        """Test that results are sorted by index even if API returns out of order."""
        respx.post("http://localhost:8080/v1/embeddings").mock(
            return_value=httpx.Response(200, json={
                "data": [
                    {"embedding": [0.4, 0.5], "index": 1},
                    {"embedding": [0.1, 0.2], "index": 0},
                ],
            })
        )
        result = await client.embed(["first", "second"])
        assert result[0] == [0.1, 0.2]
        assert result[1] == [0.4, 0.5]

    @respx.mock
    @pytest.mark.asyncio
    async def test_http_error_raises(self, client):
        respx.post("http://localhost:8080/v1/embeddings").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        with pytest.raises(httpx.HTTPStatusError):
            await client.embed(["test"])

    @respx.mock
    @pytest.mark.asyncio
    async def test_connection_error_raises(self, client):
        respx.post("http://localhost:8080/v1/embeddings").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        with pytest.raises(httpx.ConnectError):
            await client.embed(["test"])


class TestEmbedQuery:
    @respx.mock
    @pytest.mark.asyncio
    async def test_single_query(self, client):
        respx.post("http://localhost:8080/v1/embeddings").mock(
            return_value=httpx.Response(200, json={
                "data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}],
            })
        )
        result = await client.embed_query("hello")
        assert result == [0.1, 0.2, 0.3]
