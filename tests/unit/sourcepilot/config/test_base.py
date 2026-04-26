"""
config/base.py 单元测试

config 模块在 import 时从环境变量读取配置。
全局 conftest.py 在 import 前设置了 ZOEKT_URL="http://mock-zoekt:6070"、
NL_ENABLED="false"、AUDIT_ENABLED="false"，此处验证读取结果正确。
"""

import config


class TestConfigDefaults:
    """验证 conftest 设置的环境变量被正确读入 config 模块。"""

    def test_zoekt_url(self):
        # conftest 设置 ZOEKT_URL=http://mock-zoekt:6070
        assert config.ZOEKT_URL == "http://mock-zoekt:6070"

    def test_nl_enabled_false(self):
        # conftest 设置 NL_ENABLED=false → bool False
        assert config.NL_ENABLED is False

    def test_audit_enabled_false(self):
        # conftest 设置 AUDIT_ENABLED=false → bool False
        assert config.AUDIT_ENABLED is False


class TestConfigTypes:
    """验证各配置项的类型转换正确。"""

    def test_default_context_lines_is_int(self):
        assert isinstance(config.DEFAULT_CONTEXT_LINES, int)

    def test_nl_timeout_is_float(self):
        assert isinstance(config.NL_TIMEOUT, float)

    def test_nl_cache_ttl_is_int(self):
        assert isinstance(config.NL_CACHE_TTL, int)

    def test_nl_enabled_is_bool(self):
        assert isinstance(config.NL_ENABLED, bool)

    def test_audit_enabled_is_bool(self):
        assert isinstance(config.AUDIT_ENABLED, bool)

    def test_use_bm25_scoring_is_bool(self):
        assert isinstance(config.USE_BM25_SCORING, bool)


class TestConfigStringValues:
    """验证字符串类型配置项存在且为 str。"""

    def test_nl_model_is_str(self):
        assert isinstance(config.NL_MODEL, str)

    def test_nl_api_base_is_str(self):
        assert isinstance(config.NL_API_BASE, str)

    def test_nl_api_key_is_str(self):
        assert isinstance(config.NL_API_KEY, str)

    def test_mcp_auth_token_is_str(self):
        assert isinstance(config.MCP_AUTH_TOKEN, str)


class TestBooleanFalseParsing:
    """验证 "false" 字符串被解析为 bool False。"""

    def test_nl_enabled_false_parsing(self):
        # conftest 设置 NL_ENABLED="false"，期望解析为 False
        assert config.NL_ENABLED is False

    def test_audit_enabled_false_parsing(self):
        # conftest 设置 AUDIT_ENABLED="false"，期望解析为 False
        assert config.AUDIT_ENABLED is False


class TestConfigDefaultValues:
    """验证未被 conftest 覆盖的配置项有合理的默认值。"""

    def test_default_context_lines_positive(self):
        assert config.DEFAULT_CONTEXT_LINES > 0

    def test_nl_timeout_positive(self):
        assert config.NL_TIMEOUT > 0.0

    def test_nl_cache_ttl_positive(self):
        assert config.NL_CACHE_TTL > 0

    def test_nl_api_base_default(self):
        # 未设置则用 deepseek 默认地址
        assert config.NL_API_BASE == "https://api.deepseek.com/v1"

    def test_nl_model_default(self):
        assert config.NL_MODEL == "deepseek-chat"
