"""Tests: M1 — search_regex forwards branch and case_sensitive to SourcePilot."""

import httpx
import pytest
import respx


@respx.mock
@pytest.mark.asyncio
async def test_search_regex_forwards_branch_and_case_sensitive():
    """_handle_search_regex posts branch and case_sensitive to /api/search_regex."""
    posted_body = {}

    def capture(request):
        import json as _json
        posted_body.update(_json.loads(request.content))
        return httpx.Response(200, json=[])

    respx.post("http://mock-sourcepilot:9000/api/search_regex").mock(side_effect=capture)

    from entry.handlers import _handle_search_regex

    await _handle_search_regex(
        {
            "pattern": "startActivity",
            "branch": "android-14",
            "case_sensitive": "yes",
        },
        "trace-m1",
    )

    assert posted_body.get("branch") == "android-14"
    assert posted_body.get("case_sensitive") == "yes"


@respx.mock
@pytest.mark.asyncio
async def test_search_regex_default_case_sensitive():
    """Without case_sensitive arg, defaults to 'auto' via _extract_filters."""
    posted_body = {}

    def capture(request):
        import json as _json
        posted_body.update(_json.loads(request.content))
        return httpx.Response(200, json=[])

    respx.post("http://mock-sourcepilot:9000/api/search_regex").mock(side_effect=capture)

    from entry.handlers import _handle_search_regex

    await _handle_search_regex({"pattern": "TODO"}, "trace-m1-default")

    assert posted_body.get("case_sensitive") == "auto"
