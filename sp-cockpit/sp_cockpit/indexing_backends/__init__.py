"""Indexing backend integrators — dispatch dict for zoekt/dense/structural."""
from . import zoekt, dense, structural

BACKENDS = {
    "zoekt": zoekt,
    "dense": dense,
    "structural": structural,
}

__all__ = ["BACKENDS", "zoekt", "dense", "structural"]
