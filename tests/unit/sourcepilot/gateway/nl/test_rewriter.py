"""
gateway/nl/rewriter.py 单元测试

覆盖正常 LLM 响应、超时降级、错误降级、JSON 提取、_fallback_extract 各分支。
使用 respx 模拟 LLM HTTP POST。
"""

import json
import pytest
import httpx
import respx

from gateway.nl.rewriter import rewrite_query, _extract_json, _fallback_extract


# ─── _extract_json 工具函数测试（同步）────────────────────────────────────────

class TestExtractJson:
    """_extract_json 从 LLM 输出中剥离 markdown 代码块包裹。"""

    def test_plain_json_passthrough(self):
        text = '{"queries":[{"query":"foo","rationale":"bar"}]}'
        assert _extract_json(text) == text

    def test_strips_json_markdown_wrapper(self):
        text = '```json\n{"queries":[]}\n```'
        result = _extract_json(text)
        assert result == '{"queries":[]}'

    def test_strips_generic_code_block(self):
        # 没有 json 语言标记的代码块
        text = '```\n{"queries":[]}\n```'
        result = _extract_json(text)
        # 原始 text 里有 ``` 但 part 不以 json 开头也不以 { 开头（空行后才是 {）
        # 实际：split("```") → ['', '\n{"queries":[]}\n', '']
        # parts[1].strip() = '{"queries":[]}' 以 { 开头 → 返回
        assert '{"queries":[]}' in result or result.startswith("{")

    def test_with_leading_whitespace(self):
        text = '  {"queries":[]}'
        # strip() 后仍以 { 开头，无 ``` 不走分支
        assert _extract_json(text) == '{"queries":[]}'

    def test_nested_with_markdown(self):
        inner = '{"queries":[{"query":"ActivityManager","rationale":"test"}]}'
        text = f"```json\n{inner}\n```"
        result = _extract_json(text)
        assert result == inner


# ─── _fallback_extract 测试（同步）────────────────────────────────────────────

class TestFallbackExtract:
    """_fallback_extract 从自然语言中提取关键词。"""

    def test_extracts_code_identifier(self):
        # "ActivityManager" 是 4+ 字符的代码标识符
        result = _fallback_extract("ActivityManager怎么启动的")
        queries = [q["query"] for q in result]
        assert "ActivityManager" in queries

    def test_extracts_combined_keywords(self):
        # "seewo wifi settings" → combined "seewo wifi settings"
        result = _fallback_extract("seewo wifi settings")
        queries = [q["query"] for q in result]
        assert any("seewo" in q for q in queries)
        # 多词组合应出现
        combined = [q for q in queries if " " in q]
        assert len(combined) >= 1

    def test_extracts_adjacent_pairs(self):
        # "seewo wifi" → adjacent pair "seewo wifi"
        result = _fallback_extract("seewo wifi settings")
        queries = [q["query"] for q in result]
        assert "seewo wifi" in queries or "wifi settings" in queries

    def test_extracts_single_keywords(self):
        # 单词 >= 3 字符也会被补充
        result = _fallback_extract("seewo wifi")
        queries = [q["query"] for q in result]
        assert "seewo" in queries or "wifi" in queries

    def test_no_extractable_tokens_returns_original(self):
        # 纯中文无英文词 → 返回原始查询
        result = _fallback_extract("这是一个测试")
        assert len(result) >= 1
        assert result[0]["query"] == "这是一个测试"
        assert result[0]["rationale"] == "original query"

    def test_max_five_results(self):
        # 即使有很多词，结果最多 5 条
        long_query = "alpha beta gamma delta epsilon zeta eta"
        result = _fallback_extract(long_query)
        assert len(result) <= 5

    def test_no_duplicates(self):
        # 同一 query 不应重复出现
        result = _fallback_extract("ActivityManager ActivityManager")
        queries = [q["query"] for q in result]
        assert len(queries) == len(set(queries))

    def test_dotted_identifier_extracted(self):
        # 含点号的代码标识符 "persist.seewo.freeform.min_width"
        result = _fallback_extract("persist.seewo.freeform.min_width是什么")
        queries = [q["query"] for q in result]
        assert any("persist.seewo.freeform.min_width" in q for q in queries)


# ─── rewrite_query 异步测试 ───────────────────────────────────────────────────

# LLM 返回的标准 mock 响应内容
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
    """rewrite_query 异步函数测试，使用 respx mock LLM HTTP 调用。"""

    @respx.mock
    async def test_normal_llm_response(self):
        """正常 LLM 响应 → 解析并返回 queries 列表。"""
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
        """LLM 超时 → 降级到 _fallback_extract。"""
        from config import NL_API_BASE
        respx.post(f"{NL_API_BASE}/chat/completions").mock(
            side_effect=httpx.TimeoutException("timeout")
        )
        result = await rewrite_query("ActivityManager怎么启动的")
        # 降级结果是列表，且包含从查询中提取的词
        assert isinstance(result, list)
        assert len(result) >= 1

    @respx.mock
    async def test_llm_http_error_falls_back(self):
        """LLM 返回 HTTP 错误 → 降级到 _fallback_extract。"""
        from config import NL_API_BASE
        respx.post(f"{NL_API_BASE}/chat/completions").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        result = await rewrite_query("SystemServer启动流程")
        assert isinstance(result, list)
        assert len(result) >= 1

    @respx.mock
    async def test_llm_returns_markdown_wrapped_json(self):
        """LLM 返回 markdown 包裹的 JSON → _extract_json 正确剥离后解析。"""
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
        """空查询不抛出异常，返回列表（可能为空或单元素）。"""
        from config import NL_API_BASE
        respx.post(f"{NL_API_BASE}/chat/completions").mock(
            side_effect=httpx.TimeoutException("timeout")
        )
        result = await rewrite_query("")
        assert isinstance(result, list)

    @respx.mock
    async def test_result_has_correct_keys(self):
        """正常响应中每个 query 项必须包含 query 和 rationale 字段。"""
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
