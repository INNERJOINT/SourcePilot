"""
Unit tests for config/base.py

The config module reads settings from environment variables at import time.
The global conftest.py sets ZOEKT_URL="http://mock-zoekt:6070",
NL_ENABLED="false", and AUDIT_ENABLED="false" before import; these tests verify
those values are read correctly.
"""

import config


class TestConfigDefaults:
    """Verify that environment variables set by conftest are read correctly into the config module."""

    def test_zoekt_url(self):
        # conftest sets ZOEKT_URL=http://mock-zoekt:6070
        assert config.ZOEKT_URL == "http://mock-zoekt:6070"

    def test_nl_enabled_false(self):
        # conftest sets NL_ENABLED=false → bool False
        assert config.NL_ENABLED is False

    def test_audit_enabled_false(self):
        # conftest sets AUDIT_ENABLED=false → bool False
        assert config.AUDIT_ENABLED is False


class TestConfigTypes:
    """Verify that each config value is converted to the correct type."""

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
    """Verify that string config values exist and are of type str."""

    def test_nl_model_is_str(self):
        assert isinstance(config.NL_MODEL, str)

    def test_nl_api_base_is_str(self):
        assert isinstance(config.NL_API_BASE, str)

    def test_nl_api_key_is_str(self):
        assert isinstance(config.NL_API_KEY, str)

    def test_mcp_auth_token_is_str(self):
        assert isinstance(config.MCP_AUTH_TOKEN, str)


class TestBooleanFalseParsing:
    """Verify that the string "false" is parsed as bool False."""

    def test_nl_enabled_false_parsing(self):
        # conftest sets NL_ENABLED="false", expected to parse as False
        assert config.NL_ENABLED is False

    def test_audit_enabled_false_parsing(self):
        # conftest sets AUDIT_ENABLED="false", expected to parse as False
        assert config.AUDIT_ENABLED is False


class TestConfigDefaultValues:
    """Verify that config values not overridden by conftest have sensible defaults."""

    def test_default_context_lines_positive(self):
        assert config.DEFAULT_CONTEXT_LINES > 0

    def test_nl_timeout_positive(self):
        assert config.NL_TIMEOUT > 0.0

    def test_nl_cache_ttl_positive(self):
        assert config.NL_CACHE_TTL > 0

    def test_nl_api_base_default(self):
        # falls back to the deepseek default when not set
        assert config.NL_API_BASE == "https://api.deepseek.com/v1"

    def test_nl_model_default(self):
        assert config.NL_MODEL == "deepseek-chat"
