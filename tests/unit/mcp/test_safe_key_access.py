"""Tests: H3 — safe key access in _handle_get_file_content."""

import httpx
import pytest
import respx


@respx.mock
@pytest.mark.asyncio
async def test_malformed_response_no_key_error():
    """Malformed SourcePilot response -> structured generic error, no KeyError."""
    respx.post("http://mock-sourcepilot:9000/api/get_file_content").mock(
        return_value=httpx.Response(200, json={"error": "internal server error"})
    )

    from entry.handlers import _handle_get_file_content

    result = await _handle_get_file_content(
        {"repo": "frameworks/base", "filepath": "core/java/android/os/Process.java"},
        "trace-123",
    )

    assert len(result) == 1
    text = result[0].text
    # Generic message present
    assert "malformed" in text.lower() or "N/A" in text
    # Upstream error body NOT leaked
    assert "internal server error" not in text


@respx.mock
@pytest.mark.asyncio
async def test_valid_response_formats_correctly():
    """Valid SourcePilot response -> formatted header + content."""
    respx.post("http://mock-sourcepilot:9000/api/get_file_content").mock(
        return_value=httpx.Response(
            200,
            json={
                "total_lines": 100,
                "start_line": 1,
                "end_line": 50,
                "content": "package android.os;",
                "repo": "frameworks/base",
                "filepath": "core/java/android/os/Process.java",
            },
        )
    )

    from entry.handlers import _handle_get_file_content

    result = await _handle_get_file_content(
        {"repo": "frameworks/base", "filepath": "core/java/android/os/Process.java"},
        "trace-456",
    )

    assert len(result) == 1
    text = result[0].text
    assert "frameworks/base" in text
    assert "package android.os;" in text
