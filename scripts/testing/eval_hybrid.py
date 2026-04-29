#!/usr/bin/env python3
"""
eval_hybrid.py — Hybrid retrieval A/B comparison evaluation script

Runs hybrid retrieval and pure Zoekt retrieval for 5-10 NL queries, outputs comparison results.

Usage:
    DENSE_ENABLED=true PYTHONPATH=src python scripts/eval_hybrid.py
"""

import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Representative AOSP NL queries
EVAL_QUERIES = [
    "How Android loads system services during boot",
    "How to register a new SystemService",
    "Call order of Activity lifecycle callbacks",
    "Low-level implementation of Binder IPC communication",
    "How WindowManager manages window layer hierarchy",
    "PackageManager APK installation flow",
    "InputDispatcher event dispatch mechanism",
    "Core logic of AMS managing the Activity stack",
    "Zygote process forking a new process",
    "SurfaceFlinger frame composition and display flow",
]


async def run_eval():
    """Run A/B comparison evaluation."""
    from adapters.zoekt import ZoektAdapter
    from config import ZOEKT_URL
    from gateway import gateway

    zoekt = ZoektAdapter(zoekt_url=ZOEKT_URL)

    print("=" * 80)
    print("Hybrid RAG A/B Evaluation")
    print("=" * 80)

    for i, query in enumerate(EVAL_QUERIES):
        print(f"\n{'─' * 80}")
        print(f"Query {i + 1}: {query}")
        print(f"{'─' * 80}")

        # A: Hybrid retrieval (via gateway)
        try:
            hybrid_results = await gateway.search(query=query, top_k=5)
        except Exception as e:
            hybrid_results = []
            logger.warning("Hybrid search failed: %s", e)

        # B: Pure Zoekt
        try:
            zoekt_results = await zoekt.search_zoekt(query=query, top_k=5)
        except Exception as e:
            zoekt_results = []
            logger.warning("Zoekt search failed: %s", e)

        # Output comparison
        print("\n  [A] Hybrid (Zoekt + Dense):")
        hybrid_titles = set()
        for j, r in enumerate(hybrid_results[:5]):
            title = r.get("title", "?")
            source = r.get("metadata", {}).get("source", "zoekt")
            score = r.get("score", 0)
            marker = " ★" if source == "dense" else ""
            print(f"    {j + 1}. [{score:.4f}]{marker} {title}")
            hybrid_titles.add(title)

        print("\n  [B] Pure Zoekt:")
        zoekt_titles = set()
        for j, r in enumerate(zoekt_results[:5]):
            title = r.get("title", "?")
            score = r.get("score", 0)
            print(f"    {j + 1}. [{score:.4f}] {title}")
            zoekt_titles.add(title)

        # Dense-only contributions
        dense_only = hybrid_titles - zoekt_titles
        zoekt_only = zoekt_titles - hybrid_titles
        if dense_only:
            print(f"\n  Dense-only: {len(dense_only)} results")
            for t in dense_only:
                print(f"    + {t}")
        if zoekt_only:
            print(f"\n  Zoekt-only (displaced by Dense): {len(zoekt_only)} results")
            for t in zoekt_only:
                print(f"    - {t}")
        if not dense_only and not zoekt_only:
            print("\n  Results are identical")

    print(f"\n{'=' * 80}")
    print("Evaluation complete. Review results above for relevance comparison.")
    print(f"{'=' * 80}")


def main():
    import config
    if not config.DENSE_ENABLED:
        print("WARNING: DENSE_ENABLED=false. Hybrid results will be pure Zoekt.")
        print("Set DENSE_ENABLED=true and ensure Qdrant + embedding service are running.\n")

    asyncio.run(run_eval())


if __name__ == "__main__":
    main()
