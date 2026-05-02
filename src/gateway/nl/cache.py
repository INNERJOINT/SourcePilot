"""
Rewrite cache and high-frequency concept mapping table

- Concept map: maps high-frequency AOSP queries directly to symbols, bypassing LLM calls.
- LRU cache: caches LLM rewrite results with a 24h TTL.
"""

import hashlib
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

from config import NL_CACHE_TTL

# ─── LRU cache ───────────────────────────────────────
_cache: dict[str, tuple[float, list]] = {}

# ─── Concept mapping table ────────────────────────────
_concept_map: dict[str, list[dict]] = {}
_MAP_PATH = os.path.join(os.path.dirname(__file__), "concept_map.json")

if os.path.exists(_MAP_PATH):
    try:
        with open(_MAP_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        _concept_map = {
            concept: [{"query": sym, "rationale": "concept_map"} for sym in symbols]
            for concept, symbols in raw.items()
        }
        logger.info("Loaded concept_map.json: %d entries", len(_concept_map))
    except Exception as e:
        logger.warning("Failed to load concept_map.json: %s", e)


def _hash_key(query: str) -> str:
    return hashlib.md5(query.strip().lower().encode()).hexdigest()


def get_cached_rewrite(query: str) -> list[dict] | None:
    """
    Look up a cached rewrite result.
    Checks the concept map first, then the LRU cache.
    """
    # 1. Concept map lookup
    for concept, queries in _concept_map.items():
        if concept in query:
            logger.debug("Concept map hit: '%s'", concept)
            return queries

    # 2. LRU cache
    key = _hash_key(query)
    if key in _cache:
        ts, result = _cache[key]
        if time.time() - ts < NL_CACHE_TTL:
            return result
        del _cache[key]

    return None


def set_cached_rewrite(query: str, result: list[dict]):
    """Cache a rewrite result."""
    key = _hash_key(query)
    _cache[key] = (time.time(), result)
    # Simple LRU eviction: discard the oldest entry when the cache exceeds 1000 items
    if len(_cache) > 1000:
        oldest_key = min(_cache, key=lambda k: _cache[k][0])
        del _cache[oldest_key]
