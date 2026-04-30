"""Tests: L2 — read_resource handler coverage."""

import httpx
import pytest
import respx
from pydantic import AnyUrl


@respx.mock
@pytest.mark.asyncio
async def test_valid_uri_returns_content():
    """Valid aosp:// URI -> ReadResourceResult with repo+filepath header and content."""
    respx.post("http://mock-sourcepilot:9000/api/get_file_content").mock(
        return_value=httpx.Response(
            200,
            json={
                "total_lines": 10,
                "content": "package android.os;",
            },
        )
    )

    from entry.handlers import read_resource

    uri = AnyUrl("aosp://frameworks/base/core/java/android/os/Process.java")
    result = await read_resource(uri)

    assert len(result.contents) == 1
    text = result.contents[0].text
    assert "frameworks" in text
    assert "base/core/java/android/os/Process.java" in text
    assert "package android.os;" in text


@pytest.mark.asyncio
async def test_invalid_scheme_raises_value_error():
    """Non-aosp:// scheme -> ValueError with 不支持的 URI 格式."""
    from entry.handlers import read_resource

    uri = AnyUrl("http://foo/bar/baz.java")
    with pytest.raises(ValueError, match="不支持的 URI 格式"):
        await read_resource(uri)


@pytest.mark.asyncio
async def test_missing_filepath_raises_value_error():
    """aosp:// URI with no slash after repo -> ValueError."""
    # AnyUrl normalizes URLs, so build a str that looks right but is missing filepath
    # We patch str(uri) by using a mock
    import unittest.mock as mock

    from entry.handlers import read_resource

    fake_uri = mock.MagicMock()
    fake_uri.__str__ = mock.Mock(return_value="aosp://frameworks")

    with pytest.raises(ValueError):
        await read_resource(fake_uri)


@respx.mock
@pytest.mark.asyncio
async def test_gateway_500_raises_value_error():
    """Gateway 500 -> ValueError mentioning 'SourcePilot error'."""
    respx.post("http://mock-sourcepilot:9000/api/get_file_content").mock(
        return_value=httpx.Response(500, json={"error": "internal"})
    )

    from entry.handlers import read_resource

    uri = AnyUrl("aosp://frameworks/base/core/java/android/os/Process.java")
    with pytest.raises(ValueError, match="SourcePilot error"):
        await read_resource(uri)


@respx.mock
@pytest.mark.asyncio
async def test_gateway_timeout_raises_value_error():
    """Gateway timeout -> ValueError mentioning 'unreachable'."""
    respx.post("http://mock-sourcepilot:9000/api/get_file_content").mock(
        side_effect=httpx.TimeoutException("timeout")
    )

    from entry.handlers import read_resource

    uri = AnyUrl("aosp://frameworks/base/core/java/android/os/Process.java")
    with pytest.raises(ValueError, match="unreachable"):
        await read_resource(uri)
