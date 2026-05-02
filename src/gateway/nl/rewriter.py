"""
LLM Query Rewrite

Converts natural-language questions into multiple Zoekt search queries.
Supports timeout fallback: automatically extracts keywords when the LLM call fails.
"""

import json
import logging
import re

import httpx

from config import NL_MODEL, NL_API_KEY, NL_API_BASE, NL_TIMEOUT
from gateway.nl.cache import get_cached_rewrite, set_cached_rewrite

logger = logging.getLogger(__name__)

PROMPT = """You are an AOSP (Android Open Source Project) code search assistant.
The user will describe in natural language the code they are looking for. Your task is to convert
the user's question into multiple code search queries.

Rules:
1. Generate 3-5 search queries, each approaching from a different angle.
2. Queries should include: relevant class names, function names, key variable names, file path patterns.
3. Use Android/AOSP common naming conventions (CamelCase class names, Android package paths).
4. Do not guess uncertain symbol names — prefer keyword combinations instead.
5. Prioritize specific class names and function names.

Output strict JSON (do not wrap in markdown code blocks):
{"queries":[{"query":"search query","rationale":"why this query"}]}

User question: {q}"""


async def rewrite_query(query: str) -> list[dict]:
    """
    Rewrite a natural-language query into multiple Zoekt search queries.

    Returns:
        [{"query": "...", "rationale": "..."}, ...]
    """
    # # 1. Check cache (includes concept map) — temporarily skipped, going straight to LLM
    # cached = get_cached_rewrite(query)
    # if cached:
    #     logger.info("Rewrite cache/concept_map hit for: %s", query[:50])
    #     return cached

    # 2. Call the LLM
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

            # Handle LLM response potentially wrapped in ```json ... ```
            text = _extract_json(text)
            result = json.loads(text)
            queries = result.get("queries", [])

            # if queries:
            #     set_cached_rewrite(query, queries)
            logger.info("Rewrite generated %d queries for: %s", len(queries), query[:50])
            return queries

    except Exception as e:
        logger.warning("Rewrite LLM call failed (timeout=%.1fs): %s", NL_TIMEOUT, e)
        # 3. Fallback: extract keywords
        return _fallback_extract(query)


def _extract_json(text: str) -> str:
    """Extract JSON from LLM output, handling markdown code block wrapping."""
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
    Timeout fallback: extract code keywords from natural language.

    Strategy:
    1. Extract contiguous English+digit+dot+underscore segments
       (e.g. "persist.vendor.freeform.min_width").
    2. Combine adjacent English words (e.g. "vendor wifi").
    3. Supplement with individual keywords.
    """
    queries = []
    seen = set()

    def _add(q, rationale):
        if q and q not in seen:
            seen.add(q)
            queries.append({"query": q, "rationale": rationale})

    # 1. Extract complete code identifiers (dot/underscore-separated strings,
    #    e.g. property names, package names)
    code_tokens = re.findall(r'[a-zA-Z_][a-zA-Z0-9_.]{3,}', query)
    for ct in code_tokens:
        _add(ct, "code identifier")

    # 2. Strip Chinese NL words and extract remaining English parts as a combined query
    stripped = re.sub(
        r'[\u4e00-\u9fff，。？！、的是在了和与或]+', ' ', query
    ).strip()
    eng_words = [w for w in stripped.split() if re.match(r'[a-zA-Z]', w)]

    # All English words combined (e.g. "vendor wifi")
    if len(eng_words) >= 2:
        combined = " ".join(eng_words)
        _add(combined, "combined keywords")

    # Adjacent word pairs
    for i in range(len(eng_words) - 1):
        pair = f"{eng_words[i]} {eng_words[i+1]}"
        _add(pair, "adjacent pair")

    # 3. Supplement with individual keywords
    for w in eng_words:
        if len(w) >= 3:
            _add(w, "single keyword")

    # 4. If nothing was extracted, use the original query
    if not queries:
        _add(query, "original query")

    queries = queries[:5]  # max 5 lanes
    logger.info("Fallback extracted %d queries: %s", len(queries), [q["query"] for q in queries])
    return queries
