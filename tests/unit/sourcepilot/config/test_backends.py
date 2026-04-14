"""
config/backends.py 单元测试

验证 BACKENDS 注册表结构和 ZoektAdapter 的注册信息。
"""

from config.backends import BACKENDS


class TestBackendsRegistry:
    """BACKENDS 字典结构验证。"""

    def test_backends_is_dict(self):
        # BACKENDS 必须是字典
        assert isinstance(BACKENDS, dict)

    def test_zoekt_key_exists(self):
        # zoekt 后端必须注册
        assert "zoekt" in BACKENDS

    def test_zoekt_enabled(self):
        # zoekt 默认启用
        assert BACKENDS["zoekt"]["enabled"] is True

    def test_zoekt_adapter_field_exists(self):
        # zoekt 条目必须有 adapter 字段
        assert "adapter" in BACKENDS["zoekt"]

    def test_zoekt_adapter_points_to_zoekt_adapter(self):
        # adapter 字符串必须指向 ZoektAdapter
        assert BACKENDS["zoekt"]["adapter"] == "adapters.zoekt.ZoektAdapter"

    def test_zoekt_adapter_is_str(self):
        assert isinstance(BACKENDS["zoekt"]["adapter"], str)

    def test_no_feishu_enabled(self):
        # feishu 在代码中被注释掉，不应存在于 BACKENDS
        assert "feishu" not in BACKENDS
