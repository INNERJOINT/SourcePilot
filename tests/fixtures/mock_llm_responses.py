"""
LLM (NL rewriter) mock response data

Mock data for NL rewriter unit tests.
"""

# Valid LLM rewrite response (JSON format)
MOCK_LLM_VALID_RESPONSE = {
    "choices": [
        {
            "message": {
                "content": '{"rewritten_query": "startBootstrapServices", "method": "llm", "confidence": 0.9}'
            }
        }
    ]
}

# Invalid LLM response (non-JSON content)
MOCK_LLM_INVALID_RESPONSE = {
    "choices": [
        {
            "message": {
                "content": "This is an invalid non-JSON response content"
            }
        }
    ]
}

# LLM timeout scenario response (use respx side_effect=httpx.TimeoutException to simulate)
MOCK_LLM_TIMEOUT_RESPONSE = None  # timeout is simulated via respx side_effect=httpx.TimeoutException

# NL classifier mock results
MOCK_CLASSIFIER_NL_RESULT = {
    "query_type": "natural_language",
    "confidence": 0.85,
    "reason": "contains natural language description"
}

MOCK_CLASSIFIER_EXACT_RESULT = {
    "query_type": "exact",
    "confidence": 0.95,
    "reason": "looks like an exact symbol name"
}
