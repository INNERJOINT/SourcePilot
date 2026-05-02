"""
Unit tests for gateway/nl/rewriter.py

Covers normal LLM responses, timeout degradation, error degradation,
JSON extraction, and _fallback_extract branches.
Uses respx to mock LLM HTTP POST.
"""

import json
import pytest
import httpx
import respx

from gateway.nl.rewriter import rewrite_query, _extract_json, _fallback_extract


# ─── _extract_json utility tests (synchronous) ────────────────────────────────

class TestExtractJson:
    """_extract_json strips markdown code-block wrappers from LLM output."""

    def test_plain_json_passthrough(self):
        text = '{"queries":[{"query":"foo","rationale":"bar"}]}'
        assert _extract_json(text) == text

    def test_strips_json_markdown_wrapper(self):
        text = '```json\n{"queries":[]}\n```'
        result = _extract_json(text)
        assert result == '{"queries":[]}'

    def test_strips_generic_code_block(self):
        # code block without a json language tag
        text = '```\n{"queries":[]}\n```'
        result = _extract_json(text)
        # actual: split("```") → ['', '\n{"queries":[]}\n', '']
        # parts[1].strip() = '{"queries":[]}' starts with { → returned
        assert '{"queries":[]}' in result or result.startswith("{")

    def test_with_leading_whitespace(self):
        text = '  {"queries":[]}'
        # strip() still starts with {, no ``` → doesn't enter branch
        assert _extract_json(text) == '{"queries":[]}'

    def test_nested_with_markdown(self):
        inner = '{"queries":[{"query":"ActivityManager","rationale":"test"}]}'
        text = f"```json\n{inner}\n```"
        result = _extract_json(text)
        assert result == inner


# ─── _fallback_extract tests (synchronous) ────────────────────────────────────

class TestFallbackExtract:
    """_fallback_extract extracts keywords from natural-language text."""

    def test_extracts_code_identifier(self):
        # "ActivityManager" is a code identifier with 4+ chars
        result = _fallback_extract("ActivityManager怎么启动的")
        queries = [q["query"] for q in result]
        assert "ActivityManager" in queries

    def test_extracts_combined_keywords(self):
        # "vendor wifi settings" → combined "vendor wifi settings"
        result = _fallback_extract("vendor wifi settings")
        queries = [q["query"] for q in result]
        assert any("vendor" in q for q in queries)
        # multi-word combination should appear
        combined = [q for q in queries if " " in q]
        assert len(combined) >= 1

    def test_extracts_adjacent_pairs(self):
        # "vendor wifi" → adjacent pair "vendor wifi"
        result = _fallback_extract("vendor wifi settings")
        queries = [q["query"] for q in result]
        assert "vendor wifi" in queries or "wifi settings" in queries

    def test_extracts_single_keywords(self):
        # single words with >= 3 chars are also included
        result = _fallback_extract("vendor wifi")
        queries = [q["query"] for q in result]
        assert "vendor" in queries or "wifi" in queries

    def test_no_extractable_tokens_returns_original(self):
        # pure Chinese with no English words → returns original query
        result = _fallback_extract("这是一个测试")
        assert len(result) >= 1
        assert result[0]["query"] == "这是一个测试"
        assert result[0]["rationale"] == "original query"

    def test_max_five_results(self):
        # even with many words, at most 5 results are returned
        long_query = "alpha beta gamma delta epsilon zeta eta"
        result = _fallback_extract(long_query)
        assert len(result) <= 5

    def test_no_duplicates(self):
        # the same query token must not appear more than once
        result = _fallback_extract("ActivityManager ActivityManager")
        queries = [q["query"] for q in result]
        assert len(queries) == len(set(queries))

    def test_dotted_identifier_extracted(self):
        # dotted code identifier "persist.vendor.freeform.min_width"
        result = _fallback_extract("persist.vendor.freeform.min_width是什么")
        queries = [q["query"] for q in result]
        assert any("persist.vendor.freeform.min_width" in q for q in queries)


# ─── rewrite_query async tests ────────────────────────────────────────────────

# Standard mock response content returned by the LLM
_LLM_QUERIES = [{"query": "startBootstrapServices", "rationale": "test"}]
_LLM_RESPONSE_BODY = {
    "choices": [
        {
            "message": {
                "content": json.dumps({"queries": _LLM_QUERIES})
            }
        }
    ]
}


@pytest.mark.asyncio
class TestRewriteQuery:
    """Async tests for rewrite_query, using respx to mock LLM HTTP calls."""

    @respx.mock
    async def test_normal_llm_response(self):
        """Normal LLM response → parsed and returned as a queries list."""
        from config import NL_API_BASE
        respx.post(f"{NL_API_BASE}/chat/completions").mock(
            return_value=httpx.Response(200, json=_LLM_RESPONSE_BODY)
        )
        result = await rewrite_query("startBootstrapServices怎么调用的")
        assert isinstance(result, list)
        assert len(result) >= 1
        assert result[0]["query"] == "startBootstrapServices"
        assert result[0]["rationale"] == "test"

    @respx.mock
    async def test_llm_timeout_falls_back(self):
        """LLM timeout → degrades to _fallback_extract."""
        from config import NL_API_BASE
        respx.post(f"{NL_API_BASE}/chat/completions").mock(
            side_effect=httpx.TimeoutException("timeout")
        )
        result = await rewrite_query("ActivityManager怎么启动的")
        # fallback result is a list containing words extracted from the query
        assert isinstance(result, list)
        assert len(result) >= 1

    @respx.mock
    async def test_llm_http_error_falls_back(self):
        """LLM returns HTTP error → degrades to _fallback_extract."""
        from config import NL_API_BASE
        respx.post(f"{NL_API_BASE}/chat/completions").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        result = await rewrite_query("SystemServer启动流程")
        assert isinstance(result, list)
        assert len(result) >= 1

    @respx.mock
    async def test_llm_returns_markdown_wrapped_json(self):
        """LLM returns markdown-wrapped JSON → _extract_json strips it correctly before parsing."""
        from config import NL_API_BASE
        inner = json.dumps({"queries": _LLM_QUERIES})
        wrapped_body = {
            "choices": [
                {"message": {"content": f"```json\n{inner}\n```"}}
            ]
        }
        respx.post(f"{NL_API_BASE}/chat/completions").mock(
            return_value=httpx.Response(200, json=wrapped_body)
        )
        result = await rewrite_query("bootstrap服务启动")
        assert isinstance(result, list)
        assert len(result) >= 1
        assert result[0]["query"] == "startBootstrapServices"

    @respx.mock
    async def test_empty_query_handled(self):
        """Empty query does not raise; returns a list (may be empty or single-element)."""
        from config import NL_API_BASE
        respx.post(f"{NL_API_BASE}/chat/completions").mock(
            side_effect=httpx.TimeoutException("timeout")
        )
        result = await rewrite_query("")
        assert isinstance(result, list)

    @respx.mock
    async def test_result_has_correct_keys(self):
        """Each query item in a normal response must contain query and rationale fields."""
        from config import NL_API_BASE
        multi_queries = [
            {"query": "ActivityManager", "rationale": "class name"},
            {"query": "startActivity", "rationale": "method name"},
        ]
        body = {"choices": [{"message": {"content": json.dumps({"queries": multi_queries})}}]}
        respx.post(f"{NL_API_BASE}/chat/completions").mock(
            return_value=httpx.Response(200, json=body)
        )
        result = await rewrite_query("如何启动Activity")
        for item in result:
            assert "query" in item
            assert "rationale" in item
