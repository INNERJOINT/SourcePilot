"""Backend registry configuration."""

# Registered backends and their enabled status
BACKENDS = {
    "zoekt": {
        "enabled": True,
        "adapter": "adapters.zoekt.ZoektAdapter",
    },
    "dense": {
        "enabled": False,  # 通过 DENSE_ENABLED 环境变量控制
        "adapter": "adapters.dense.DenseAdapter",
    },
    "structural": {
        "enabled": False,  # 通过 STRUCTURAL_ENABLED 环境变量控制
        "adapter": "adapters.structural.StructuralAdapter",
    },
    # "feishu": {
    #     "enabled": False,
    #     "adapter": "adapters.feishu.FeishuAdapter",
    # },
}
