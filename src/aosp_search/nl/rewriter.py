"""
LLM Query Rewrite

将自然语言问题转换为多个 Zoekt 搜索查询。
支持超时降级：LLM 调用失败时自动提取关键词。
"""

import json
import logging
import re

import httpx

from config import NL_MODEL, NL_API_KEY, NL_API_BASE, NL_TIMEOUT
from aosp_search.nl.cache import get_cached_rewrite, set_cached_rewrite

logger = logging.getLogger(__name__)

PROMPT = """你是一个 AOSP（Android Open Source Project）代码搜索助手。
用户会用自然语言描述他们想找的代码。你的任务是把用户问题转换成多个代码搜索查询。

规则：
1. 生成 3-5 个搜索查询，每个查询应从不同角度切入
2. 查询应包含：相关的类名、函数名、关键变量名、文件路径模式
3. 使用 Android/AOSP 常见命名惯例（CamelCase 类名、Android 包路径）
4. 不要猜测不确定的符号名，宁可用关键词组合
5. 优先使用具体的类名和函数名

严格输出 JSON（不要 markdown 代码块包裹）：
{"queries":[{"query":"搜索查询","rationale":"为什么这样查"}]}

用户问题：{q}"""


async def rewrite_query(query: str) -> list[dict]:
    """
    将自然语言查询改写为多个 Zoekt 搜索查询。

    Returns:
        [{"query": "...", "rationale": "..."}, ...]
    """
    # # 1. 检查缓存（含概念映射表）—— 暂时跳过，直接走 LLM
    # cached = get_cached_rewrite(query)
    # if cached:
    #     logger.info("Rewrite cache/concept_map hit for: %s", query[:50])
    #     return cached

    # 2. 调用 LLM
    try:
        async with httpx.AsyncClient(timeout=NL_TIMEOUT) as client:
            resp = await client.post(
                f"{NL_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {NL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": NL_MODEL,
                    "messages": [{"role": "user", "content": PROMPT.replace("{q}", query)}],
                    "temperature": 0.2,
                    "max_tokens": 512,
                },
            )
            resp.raise_for_status()
            resp_json = resp.json()
            logger.info("LLM raw response: %s", json.dumps(resp_json, ensure_ascii=False)[:1000])
            text = resp_json["choices"][0]["message"]["content"]

            # 兼容 LLM 可能用 ```json ... ``` 包裹
            text = _extract_json(text)
            result = json.loads(text)
            queries = result.get("queries", [])

            # if queries:
            #     set_cached_rewrite(query, queries)
            logger.info("Rewrite generated %d queries for: %s", len(queries), query[:50])
            return queries

    except Exception as e:
        logger.warning("Rewrite LLM call failed (timeout=%.1fs): %s", NL_TIMEOUT, e)
        # 3. 降级：提取关键词
        return _fallback_extract(query)


def _extract_json(text: str) -> str:
    """从 LLM 输出中提取 JSON，兼容 markdown 代码块包裹。"""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                return part
    return text


def _fallback_extract(query: str) -> list[dict]:
    """
    超时降级：从自然语言中提取代码关键词。

    策略：
    1. 提取连续的英文+数字+点+下划线片段（如 "persist.seewo.freeform.min_width"）
    2. 提取相邻英文单词的组合（如 "seewo wifi"）
    3. 补充独立关键词
    """
    queries = []
    seen = set()

    def _add(q, rationale):
        if q and q not in seen:
            seen.add(q)
            queries.append({"query": q, "rationale": rationale})

    # 1. 提取完整的代码标识符（含点号/下划线的连续串，如属性名、包名）
    code_tokens = re.findall(r'[a-zA-Z_][a-zA-Z0-9_.]{3,}', query)
    for ct in code_tokens:
        _add(ct, "code identifier")

    # 2. 去掉中文 NL 词后，提取剩余英文部分作为组合查询
    stripped = re.sub(
        r'[\u4e00-\u9fff，。？！、的是在了和与或]+', ' ', query
    ).strip()
    eng_words = [w for w in stripped.split() if re.match(r'[a-zA-Z]', w)]

    # 所有英文词的组合（如 "seewo wifi"）
    if len(eng_words) >= 2:
        combined = " ".join(eng_words)
        _add(combined, "combined keywords")

    # 相邻两两组合
    for i in range(len(eng_words) - 1):
        pair = f"{eng_words[i]} {eng_words[i+1]}"
        _add(pair, "adjacent pair")

    # 3. 独立关键词补充
    for w in eng_words:
        if len(w) >= 3:
            _add(w, "single keyword")

    # 4. 如果什么都没提取到，用原始查询
    if not queries:
        _add(query, "original query")

    queries = queries[:5]  # 最多 5 路
    logger.info("Fallback extracted %d queries: %s", len(queries), [q["query"] for q in queries])
    return queries
