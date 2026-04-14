"""
Gateway 管道集成测试

直接调用 gateway.search()，以 respx mock Zoekt HTTP 响应，
验证完整的内部管道（classify → search / NL pipeline → fusion → rerank）。
"""
import pytest
import respx
import httpx

import config
from gateway import gateway


# ─── Zoekt mock 数据 ──────────────────────────────────────

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
                "content": '{"queries":[{"query":"SystemServer startBootstrapServices","rationale":"直接方法名"},{"query":"startBootstrapServices java","rationale":"语言过滤"}]}'
            }
        }
    ]
}


# ─── 精确查询管道测试 ──────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_exact_query_pipeline():
    """精确查询（无 NL 关键词）走直接 Zoekt 路径，返回结果列表"""
    respx.get(f"{config.ZOEKT_URL}/search").mock(
        return_value=httpx.Response(200, json=ZOEKT_SEARCH_RESPONSE)
    )

    results = await gateway.search("SystemServer")

    assert isinstance(results, list)
    assert len(results) > 0
    # 第一个结果包含 Zoekt 返回的信息
    first = results[0]
    assert "title" in first
    assert "score" in first
    assert "metadata" in first
    assert first["metadata"]["repo"] == "frameworks/base"


@pytest.mark.asyncio
@respx.mock
async def test_exact_query_uses_direct_zoekt_path():
    """NL_ENABLED=False 时，所有查询都走直接 Zoekt 路径，不调用 LLM"""
    zoekt_mock = respx.get(f"{config.ZOEKT_URL}/search").mock(
        return_value=httpx.Response(200, json=ZOEKT_SEARCH_RESPONSE)
    )
    # LLM 端点不应被调用
    llm_mock = respx.post(f"{config.NL_API_BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json=LLM_REWRITE_RESPONSE)
    )

    original_nl_enabled = config.NL_ENABLED
    try:
        config.NL_ENABLED = False
        results = await gateway.search("怎么启动 SystemServer")
    finally:
        config.NL_ENABLED = original_nl_enabled

    assert isinstance(results, list)
    # LLM 不应被调用
    assert not llm_mock.called


@pytest.mark.asyncio
@respx.mock
async def test_nl_query_pipeline_with_mocked_llm():
    """NL 查询（含中文）走 NL 管道：LLM 改写 → 并行 Zoekt → 融合 → rerank"""
    # 模拟 LLM 改写
    respx.post(f"{config.NL_API_BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json=LLM_REWRITE_RESPONSE)
    )
    # 模拟 Zoekt 搜索（并行多路都返回相同结果）
    respx.get(f"{config.ZOEKT_URL}/search").mock(
        return_value=httpx.Response(200, json=ZOEKT_SEARCH_RESPONSE)
    )

    original_nl_enabled = config.NL_ENABLED
    try:
        config.NL_ENABLED = True
        results = await gateway.search("怎么启动SystemServer")
    finally:
        config.NL_ENABLED = original_nl_enabled

    assert isinstance(results, list)
    # NL 管道应该返回结果（融合后去重）
    assert len(results) > 0


@pytest.mark.asyncio
@respx.mock
async def test_empty_results_returns_empty_list():
    """Zoekt 返回空 FileMatches 时，gateway.search 返回空列表"""
    respx.get(f"{config.ZOEKT_URL}/search").mock(
        return_value=httpx.Response(200, json=ZOEKT_EMPTY_RESPONSE)
    )

    results = await gateway.search("不存在的符号xyz123abc")

    assert isinstance(results, list)
    assert len(results) == 0


@pytest.mark.asyncio
@respx.mock
async def test_search_with_lang_filter():
    """带语言过滤的搜索，Zoekt 请求包含 lang: 前缀"""
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
    """带仓库过滤的搜索，Zoekt 请求包含 r: 前缀"""
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
    """config.NL_ENABLED=False 时，即使查询是自然语言，也走精确路径"""
    respx.get(f"{config.ZOEKT_URL}/search").mock(
        return_value=httpx.Response(200, json=ZOEKT_EMPTY_RESPONSE)
    )
    # 不 mock LLM，如果被调用会导致连接错误
    original = config.NL_ENABLED
    try:
        config.NL_ENABLED = False
        # 即使是中文 NL 查询，也只走 Zoekt 直接搜索
        results = await gateway.search("如何在 AOSP 中启动一个 Activity")
    finally:
        config.NL_ENABLED = original

    assert isinstance(results, list)
