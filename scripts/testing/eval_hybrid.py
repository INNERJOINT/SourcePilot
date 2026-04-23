#!/usr/bin/env python3
"""
eval_hybrid.py — 混合检索 A/B 对比评估脚本

对 5-10 个 NL 查询分别执行混合检索和纯 Zoekt 检索，输出对比结果。

Usage:
    DENSE_ENABLED=true PYTHONPATH=src python scripts/eval_hybrid.py
"""

import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# 代表性 AOSP NL 查询
EVAL_QUERIES = [
    "Android 启动时加载系统服务的流程",
    "如何注册一个新的 SystemService",
    "Activity 生命周期回调的调用顺序",
    "Binder IPC 通信的底层实现",
    "WindowManager 如何管理窗口层级",
    "PackageManager 安装 APK 的流程",
    "InputDispatcher 事件分发机制",
    "AMS 管理 Activity 栈的核心逻辑",
    "Zygote 进程 fork 新进程的过程",
    "SurfaceFlinger 合成显示帧的流程",
]


async def run_eval():
    """运行 A/B 对比评估。"""
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

        # A: 混合检索（通过 gateway）
        try:
            hybrid_results = await gateway.search(query=query, top_k=5)
        except Exception as e:
            hybrid_results = []
            logger.warning("Hybrid search failed: %s", e)

        # B: 纯 Zoekt
        try:
            zoekt_results = await zoekt.search_zoekt(query=query, top_k=5)
        except Exception as e:
            zoekt_results = []
            logger.warning("Zoekt search failed: %s", e)

        # 输出对比
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

        # Dense 独有贡献
        dense_only = hybrid_titles - zoekt_titles
        zoekt_only = zoekt_titles - hybrid_titles
        if dense_only:
            print(f"\n  Dense 独有: {len(dense_only)} results")
            for t in dense_only:
                print(f"    + {t}")
        if zoekt_only:
            print(f"\n  Zoekt 独有 (被 Dense 替换): {len(zoekt_only)} results")
            for t in zoekt_only:
                print(f"    - {t}")
        if not dense_only and not zoekt_only:
            print("\n  结果完全相同")

    print(f"\n{'=' * 80}")
    print("Evaluation complete. Review results above for relevance comparison.")
    print(f"{'=' * 80}")


def main():
    import config
    if not config.DENSE_ENABLED:
        print("WARNING: DENSE_ENABLED=false. Hybrid results will be pure Zoekt.")
        print("Set DENSE_ENABLED=true and ensure Milvus + embedding service are running.\n")

    asyncio.run(run_eval())


if __name__ == "__main__":
    main()
