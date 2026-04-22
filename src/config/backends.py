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
    "graph": {
        "enabled": False,  # 通过 GRAPH_ENABLED 环境变量控制
        "adapter": "adapters.graph.GraphAdapter",
    },
    # "feishu": {
    #     "enabled": False,
    #     "adapter": "adapters.feishu.FeishuAdapter",
    # },
}
