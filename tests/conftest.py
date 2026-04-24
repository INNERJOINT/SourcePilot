"""
全局测试配置

设置环境变量、注册 pytest markers、提供共享 fixtures。
"""
import os

import pytest

# 环境变量必须在所有应用模块 import 之前设置
os.environ.setdefault("ZOEKT_URL", "http://mock-zoekt:6070")
_TEST_PROJECTS_CONFIG = "/tmp/sourcepilot-test-projects.yaml"
os.environ.setdefault("PROJECTS_CONFIG_PATH", _TEST_PROJECTS_CONFIG)
if os.environ["PROJECTS_CONFIG_PATH"] == _TEST_PROJECTS_CONFIG:
    with open(_TEST_PROJECTS_CONFIG, "w", encoding="utf-8") as f:
        f.write(
            "projects:\n"
            "  - name: default\n"
            "    source_root: /mnt/code/ACE\n"
            "    repo_path: /mnt/code/ACE/.repo\n"
            "    index_dir: /mnt/code/ACE/.repo/.zoekt\n"
            f"    zoekt_url: {os.environ['ZOEKT_URL']}\n"
        )
os.environ.setdefault("NL_ENABLED", "false")
os.environ.setdefault("SOURCEPILOT_URL", "http://mock-sourcepilot:9000")
os.environ.setdefault("MCP_AUTH_TOKEN", "test-token-12345")
os.environ.setdefault("AUDIT_ENABLED", "false")


@pytest.fixture
def mock_zoekt_search_response():
    """Zoekt 搜索 API 的标准 mock 响应"""
    from tests.fixtures.mock_zoekt_responses import MOCK_SEARCH_RESPONSE

    return MOCK_SEARCH_RESPONSE.copy()


@pytest.fixture
def mock_empty_response():
    """Zoekt 空结果响应"""
    from tests.fixtures.mock_zoekt_responses import MOCK_EMPTY_SEARCH_RESPONSE

    return MOCK_EMPTY_SEARCH_RESPONSE.copy()


@pytest.fixture
def mock_sourcepilot_results():
    """SourcePilot API 的标准 mock 响应"""
    from tests.fixtures.mock_sourcepilot_responses import MOCK_SP_SEARCH_RESULTS

    return [item.copy() for item in MOCK_SP_SEARCH_RESULTS]
