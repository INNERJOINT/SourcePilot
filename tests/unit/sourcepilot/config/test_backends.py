"""
Unit tests for config/backends.py

Validates the BACKENDS registry structure and ZoektAdapter registration.
"""

from config.backends import BACKENDS


class TestBackendsRegistry:
    """BACKENDS dictionary structure validation."""

    def test_backends_is_dict(self):
        # BACKENDS must be a dict
        assert isinstance(BACKENDS, dict)

    def test_zoekt_key_exists(self):
        # zoekt backend must be registered
        assert "zoekt" in BACKENDS

    def test_zoekt_enabled(self):
        # zoekt is enabled by default
        assert BACKENDS["zoekt"]["enabled"] is True

    def test_zoekt_adapter_field_exists(self):
        # zoekt entry must have an adapter field
        assert "adapter" in BACKENDS["zoekt"]

    def test_zoekt_adapter_points_to_zoekt_adapter(self):
        # adapter string must point to ZoektAdapter
        assert BACKENDS["zoekt"]["adapter"] == "adapters.zoekt.ZoektAdapter"

    def test_zoekt_adapter_is_str(self):
        assert isinstance(BACKENDS["zoekt"]["adapter"], str)

    def test_no_feishu_enabled(self):
        # feishu is commented out in the code and must not be present in BACKENDS
        assert "feishu" not in BACKENDS
