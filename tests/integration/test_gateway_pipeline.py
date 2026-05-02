"""
Gateway pipeline integration tests

Calls gateway.search() directly, mocking Zoekt HTTP responses via respx,
to verify the full internal pipeline (classify → search / NL pipeline → fusion → rerank).
"""
import pytest
import respx
import httpx

import config
from gateway import gateway


# ─── Zoekt mock data ──────────────────────────────────────

ZOEKT_SEARCH_RESPONSE = {
    "Result": {
        "FileMatches": [
            {
                "Repo": "frameworks/base",
                "FileName": "services/core/java/com/android/server/SystemServer.java",
                "Score": 25.5,
                "Matches": [
                    {
                        "LineNum": 120,
                        "Fragments": [
                            {"Pre": "private void ", "Match": "startBootstrapServices", "Post": "() {"}
                        ]
                    }
                ]
            }
        ],
        "Stats": {"MatchCount": 1, "FileCount": 1}
    }
}

ZOEKT_EMPTY_RESPONSE = {
    "Result": {
        "FileMatches": [],
        "Stats": {"MatchCount": 0, "FileCount": 0}
    }
}

LLM_REWRITE_RESPONSE = {
    "choices": [
        {
            "message": {
                "content": '{"queries":[{"query":"SystemServer startBootstrapServices","rationale":"direct method name"},{"query":"startBootstrapServices java","rationale":"language filter"}]}'
            }
        }
    ]
}


# ─── Exact query pipeline tests ──────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_exact_query_pipeline():
    """Exact query (no NL keywords) takes the direct Zoekt path and returns results."""
    respx.get(f"{config.ZOEKT_URL}/search").mock(
        return_value=httpx.Response(200, json=ZOEKT_SEARCH_RESPONSE)
    )

    results = await gateway.search("SystemServer")

    assert isinstance(results, list)
    assert len(results) > 0
    # First result contains information returned from Zoekt
    first = results[0]
    assert "title" in first
    assert "score" in first
    assert "metadata" in first
    assert first["metadata"]["repo"] == "frameworks/base"


@pytest.mark.asyncio
@respx.mock
async def test_exact_query_uses_direct_zoekt_path():
    """With NL_ENABLED=False, all queries take the direct Zoekt path without calling LLM."""
    zoekt_mock = respx.get(f"{config.ZOEKT_URL}/search").mock(
        return_value=httpx.Response(200, json=ZOEKT_SEARCH_RESPONSE)
    )
    # LLM endpoint should not be called
    llm_mock = respx.post(f"{config.NL_API_BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json=LLM_REWRITE_RESPONSE)
    )

    original_nl_enabled = config.NL_ENABLED
    try:
        config.NL_ENABLED = False
        results = await gateway.search("How does SystemServer start")
    finally:
        config.NL_ENABLED = original_nl_enabled

    assert isinstance(results, list)
    # LLM should not be called
    assert not llm_mock.called


@pytest.mark.asyncio
@respx.mock
async def test_nl_query_pipeline_with_mocked_llm():
    """NL query (contains Chinese) goes through the NL pipeline: LLM rewrite → parallel Zoekt → fusion → rerank."""
    # Mock LLM rewrite
    respx.post(f"{config.NL_API_BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json=LLM_REWRITE_RESPONSE)
    )
    # Mock Zoekt search (parallel multi-path all return the same results)
    respx.get(f"{config.ZOEKT_URL}/search").mock(
        return_value=httpx.Response(200, json=ZOEKT_SEARCH_RESPONSE)
    )

    original_nl_enabled = config.NL_ENABLED
    try:
        config.NL_ENABLED = True
        results = await gateway.search("How does SystemServer start")
    finally:
        config.NL_ENABLED = original_nl_enabled

    assert isinstance(results, list)
    # NL pipeline should return results (deduplicated after fusion)
    assert len(results) > 0


@pytest.mark.asyncio
@respx.mock
async def test_empty_results_returns_empty_list():
    """When Zoekt returns empty FileMatches, gateway.search returns an empty list."""
    respx.get(f"{config.ZOEKT_URL}/search").mock(
        return_value=httpx.Response(200, json=ZOEKT_EMPTY_RESPONSE)
    )

    results = await gateway.search("nonexistent_symbol_xyz123abc")

    assert isinstance(results, list)
    assert len(results) == 0


@pytest.mark.asyncio
@respx.mock
async def test_search_with_lang_filter():
    """Search with a language filter includes lang: prefix in the Zoekt request."""
    captured_params = {}

    def capture(request):
        captured_params.update(dict(request.url.params))
        return httpx.Response(200, json=ZOEKT_SEARCH_RESPONSE)

    respx.get(f"{config.ZOEKT_URL}/search").mock(side_effect=capture)

    await gateway.search("ActivityManager", lang="java")

    assert "q" in captured_params
    assert "lang:java" in captured_params["q"]


@pytest.mark.asyncio
@respx.mock
async def test_search_with_repo_filter():
    """Search with a repo filter includes r: prefix in the Zoekt request."""
    captured_params = {}

    def capture(request):
        captured_params.update(dict(request.url.params))
        return httpx.Response(200, json=ZOEKT_SEARCH_RESPONSE)

    respx.get(f"{config.ZOEKT_URL}/search").mock(side_effect=capture)

    await gateway.search("startActivity", repos="frameworks/base")

    assert "q" in captured_params
    assert "r:frameworks/base" in captured_params["q"]


@pytest.mark.asyncio
@respx.mock
async def test_nl_disabled_for_nl_query():
    """With config.NL_ENABLED=False, even a natural language query takes the exact path."""
    respx.get(f"{config.ZOEKT_URL}/search").mock(
        return_value=httpx.Response(200, json=ZOEKT_EMPTY_RESPONSE)
    )
    # Do not mock LLM — a call would cause a connection error
    original = config.NL_ENABLED
    try:
        config.NL_ENABLED = False
        # Even a Chinese NL query only goes through direct Zoekt search
        results = await gateway.search("How do you start an Activity in AOSP")
    finally:
        config.NL_ENABLED = original

    assert isinstance(results, list)
