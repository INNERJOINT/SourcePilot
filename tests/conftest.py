"""
全局测试配置

设置环境变量、注册 pytest markers、提供共享 fixtures。
"""
import os
import pytest

# 环境变量必须在所有 import 之前设置
os.environ.setdefault("ZOEKT_URL", "http://mock-zoekt:6070")
os.environ.setdefault("NL_ENABLED", "false")
os.environ.setdefault("SOURCEPILOT_URL", "http://mock-sourcepilot:9000")
os.environ.setdefault("MCP_AUTH_TOKEN", "test-token-12345")
os.environ.setdefault("AUDIT_ENABLED", "false")

from tests.fixtures.mock_zoekt_responses import (
    MOCK_SEARCH_RESPONSE,
    MOCK_EMPTY_SEARCH_RESPONSE,
    MOCK_REPO_RESPONSE,
    MOCK_FILE_CONTENT_HTML,
)
from tests.fixtures.mock_sourcepilot_responses import (
    MOCK_SP_SEARCH_RESULTS,
    MOCK_SP_REPOS,
    MOCK_SP_FILE_CONTENT,
)


@pytest.fixture
def mock_zoekt_search_response():
    """Zoekt 搜索 API 的标准 mock 响应"""
    return MOCK_SEARCH_RESPONSE.copy()


@pytest.fixture
def mock_empty_response():
    """Zoekt 空结果响应"""
    return MOCK_EMPTY_SEARCH_RESPONSE.copy()


@pytest.fixture
def mock_sourcepilot_results():
    """SourcePilot API 的标准 mock 响应"""
    return [item.copy() for item in MOCK_SP_SEARCH_RESULTS]
