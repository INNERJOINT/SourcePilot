"""Backend registry configuration."""

# Registered backends and their enabled status
BACKENDS = {
    "zoekt": {
        "enabled": True,
        "adapter": "adapters.zoekt.ZoektAdapter",
    },
    "dense": {
        "enabled": False,  # controlled by the DENSE_ENABLED environment variable
        "adapter": "adapters.dense.DenseAdapter",
    },
    "structural": {
        "enabled": False,  # controlled by the STRUCTURAL_ENABLED environment variable
        "adapter": "adapters.structural.StructuralAdapter",
    },
    # "feishu": {
    #     "enabled": False,
    #     "adapter": "adapters.feishu.FeishuAdapter",
    # },
}
