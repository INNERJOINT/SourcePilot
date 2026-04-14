"""
LLM (NL rewriter) mock 响应数据

用于 NL rewriter 单元测试的 mock 数据。
"""

# 有效的 LLM 改写响应（JSON 格式）
MOCK_LLM_VALID_RESPONSE = {
    "choices": [
        {
            "message": {
                "content": '{"rewritten_query": "startBootstrapServices", "method": "llm", "confidence": 0.9}'
            }
        }
    ]
}

# 无效的 LLM 响应（非 JSON 内容）
MOCK_LLM_INVALID_RESPONSE = {
    "choices": [
        {
            "message": {
                "content": "这是一个无效的非JSON响应内容"
            }
        }
    ]
}

# LLM 超时场景的响应数据（用于配合 respx 模拟超时）
MOCK_LLM_TIMEOUT_RESPONSE = None  # 超时通过 respx side_effect=httpx.TimeoutException 模拟

# NL 分类器 mock 结果
MOCK_CLASSIFIER_NL_RESULT = {
    "query_type": "natural_language",
    "confidence": 0.85,
    "reason": "包含自然语言描述"
}

MOCK_CLASSIFIER_EXACT_RESULT = {
    "query_type": "exact",
    "confidence": 0.95,
    "reason": "看起来是精确的符号名称"
}
