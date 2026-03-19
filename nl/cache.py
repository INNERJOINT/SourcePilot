"""
Rewrite 缓存 + 高频概念映射表

- 概念映射表：高频 AOSP 查询直接映射到符号，跳过 LLM 调用
- LRU 缓存：缓存 LLM rewrite 结果，TTL 24h
"""

import hashlib
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

NL_CACHE_TTL = int(os.getenv("NL_CACHE_TTL", "86400"))  # 默认 24h

# ─── LRU 缓存 ──────────────────────────────────────
_cache: dict[str, tuple[float, list]] = {}

# ─── 概念映射表 ────────────────────────────────────
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
    查找缓存的 rewrite 结果。
    优先检查概念映射表，再检查 LRU 缓存。
    """
    # 1. 概念映射表匹配
    for concept, queries in _concept_map.items():
        if concept in query:
            logger.debug("Concept map hit: '%s'", concept)
            return queries

    # 2. LRU 缓存
    key = _hash_key(query)
    if key in _cache:
        ts, result = _cache[key]
        if time.time() - ts < NL_CACHE_TTL:
            return result
        del _cache[key]

    return None


def set_cached_rewrite(query: str, result: list[dict]):
    """缓存 rewrite 结果。"""
    key = _hash_key(query)
    _cache[key] = (time.time(), result)
    # 简易 LRU：超过 1000 条时清理最旧的
    if len(_cache) > 1000:
        oldest_key = min(_cache, key=lambda k: _cache[k][0])
        del _cache[oldest_key]
