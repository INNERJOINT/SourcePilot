"""Backend registry configuration."""

# Registered backends and their enabled status
BACKENDS = {
    "zoekt": {
        "enabled": True,
        "adapter": "adapters.zoekt.ZoektAdapter",
    },
    # "feishu": {
    #     "enabled": False,
    #     "adapter": "adapters.feishu.FeishuAdapter",
    # },
}
