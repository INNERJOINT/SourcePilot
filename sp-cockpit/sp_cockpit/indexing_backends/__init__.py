"""Indexing backend integrators — dispatch dict for zoekt/dense/graph."""
from . import zoekt, dense, graph

BACKENDS = {
    "zoekt": zoekt,
    "dense": dense,
    "graph": graph,
}

__all__ = ["BACKENDS", "zoekt", "dense", "graph"]
