#!/usr/bin/env python3
"""
build_feishu_index.py — Feishu Lurk 知识库向量索引构建脚本

从 JSONL 文件读取 Feishu 文档，按字符滑动窗口切分后
通过 embedding 服务写入 Qdrant 向量数据库。

Usage:
    PYTHONPATH=src python scripts/indexing/feishu/build_feishu_index.py --jsonl-path docs.jsonl
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def text_sliding_window_chunks(
    content: str,
    title: str,
    url: str,
    space_id: str,
    node_token: str,
    window_size: int = 500,
    overlap: int = 100,
) -> list[dict]:
    """将文档内容按字符滑动窗口切分为 chunks。

    Args:
        content: 文档正文
        title: 文档标题
        url: 文档 URL
        space_id: 空间 ID
        node_token: 节点 token
        window_size: 窗口大小（字符数）
        overlap: 重叠字符数

    Returns:
        list of chunk dicts with metadata
    """
    if not content or not content.strip():
        return []

    step = window_size - overlap
    if step <= 0:
        step = 1

    chunks = []
    total = len(content)
    for start in range(0, total, step):
        end = min(start + window_size, total)
        chunk_text = content[start:end]

        if not chunk_text.strip():
            if end >= total:
                break
            continue

        chunks.append({
            "content": chunk_text,
            "title": title,
            "url": url,
            "space_id": space_id,
            "node_token": node_token,
            "content_hash": hashlib.md5(chunk_text.encode()).hexdigest(),
        })

        if end >= total:
            break

    return chunks


def load_documents(jsonl_path: str) -> list[dict]:
    """从 JSONL 文件加载文档列表。"""
    docs = []
    with open(jsonl_path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
                docs.append(doc)
            except json.JSONDecodeError as e:
                logger.warning("Line %d: JSON parse error: %s", lineno, e)
    return docs


async def build_index(args, collection_name: str, embedding_model: str | None = None):
    """主索引构建流程。"""
    from adapters.embedding import EmbeddingClient
    from config import DENSE_EMBEDDING_DIM, DENSE_EMBEDDING_MODEL, DENSE_EMBEDDING_URL, DENSE_VECTOR_DB_URL

    embedding = EmbeddingClient(base_url=DENSE_EMBEDDING_URL, model=embedding_model or DENSE_EMBEDDING_MODEL)

    # 1. 加载文档
    logger.info("Loading documents from %s ...", args.jsonl_path)
    docs = load_documents(args.jsonl_path)
    logger.info("Loaded %d documents", len(docs))
    if not docs:
        logger.error("No documents found in %s", args.jsonl_path)
        return

    # 2. 切分 chunks
    logger.info("Chunking documents (window=%d, overlap=%d) ...", args.window_size, args.overlap)
    all_chunks = []
    for doc in docs:
        chunks = text_sliding_window_chunks(
            content=doc.get("content", ""),
            title=doc.get("title", ""),
            url=doc.get("url", ""),
            space_id=doc.get("space_id", ""),
            node_token=doc.get("node_token", ""),
            window_size=args.window_size,
            overlap=args.overlap,
        )
        all_chunks.extend(chunks)

    logger.info("Total chunks: %d", len(all_chunks))
    if not all_chunks:
        logger.error("No chunks generated. Check document content.")
        return

    # 3. 批量 embedding（并发）
    logger.info("Generating embeddings (batch_size=%d, concurrency=%d) ...", args.batch_size, args.concurrency)
    all_vectors: list = [None] * len(all_chunks)
    texts = [c["content"] for c in all_chunks]
    sem = asyncio.Semaphore(args.concurrency)
    failed_ranges: list[tuple[int, int]] = []

    async def embed_batch(batch_start, batch_end):
        batch = [t[:1500] for t in texts[batch_start:batch_end]]
        async with sem:
            for attempt in range(3):
                try:
                    vectors = await embedding.embed(batch)
                    for i, v in enumerate(vectors):
                        all_vectors[batch_start + i] = v
                    return
                except Exception as e:
                    if attempt == 2:
                        logger.error(
                            "Embedding failed at batch %d-%d after 3 retries: %s — skipping",
                            batch_start, batch_end, e,
                        )
                        failed_ranges.append((batch_start, batch_end))
                        return
                    await asyncio.sleep(2 ** attempt)

    tasks = []
    for batch_start in range(0, len(texts), args.batch_size):
        batch_end = min(batch_start + args.batch_size, len(texts))
        tasks.append(embed_batch(batch_start, batch_end))

    chunk_size = 500
    for group_start in range(0, len(tasks), chunk_size):
        group = tasks[group_start:group_start + chunk_size]
        results = await asyncio.gather(*group, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.error("Unexpected exception from embed_batch: %s", r)
        done = min((group_start + chunk_size) * args.batch_size, len(texts))
        logger.info("  embedded %d/%d chunks (failed batches so far: %d)", done, len(texts), len(failed_ranges))

    failed_chunk_count = sum(e - s for s, e in failed_ranges)
    logger.info(
        "Embedding complete: %d/%d chunks ok, %d chunks in %d failed batches",
        len(all_chunks) - failed_chunk_count, len(all_chunks),
        failed_chunk_count, len(failed_ranges),
    )
    if failed_ranges:
        logger.warning("Failed batch ranges (first 20): %s", failed_ranges[:20])

    # 4. 写入 Qdrant
    logger.info("Writing to Qdrant (collection=%s) ...", collection_name)
    import uuid
    from qdrant_client import QdrantClient, models

    client = QdrantClient(url=DENSE_VECTOR_DB_URL)

    # 创建 collection（如果不存在）
    if not client.collection_exists(collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(size=DENSE_EMBEDDING_DIM, distance=models.Distance.COSINE),
        )
        logger.info("Created collection '%s' with HNSW index (cosine)", collection_name)

    # 批量插入（跳过 embedding 失败的 chunk）
    insert_batch_size = 1000
    total_inserted = 0
    total_skipped = 0
    for batch_start in range(0, len(all_chunks), insert_batch_size):
        batch_end = min(batch_start + insert_batch_size, len(all_chunks))
        points = []
        for i in range(batch_start, batch_end):
            if all_vectors[i] is None:
                total_skipped += 1
                continue
            chunk = all_chunks[i]
            points.append(models.PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk["content_hash"])),
                vector=all_vectors[i],
                payload={
                    "title": chunk["title"][:512],
                    "url": chunk["url"][:1024],
                    "space_id": chunk["space_id"][:128],
                    "node_token": chunk["node_token"][:128],
                    "content": chunk["content"][:65535],
                    "content_hash": chunk["content_hash"],
                },
            ))
        if not points:
            continue
        try:
            client.upsert(collection_name=collection_name, points=points)
            total_inserted += len(points)
        except Exception as e:
            logger.error("Insert failed at batch %d-%d: %s", batch_start, batch_end, e)

        if (batch_start + insert_batch_size) % (insert_batch_size * 5) == 0:
            logger.info("  inserted %d/%d chunks", total_inserted, len(all_chunks))

    logger.info(
        "Index build complete: %d inserted, %d skipped (embedding-failed), collection='%s'",
        total_inserted, total_skipped, collection_name,
    )
    if failed_ranges:
        logger.warning(
            "Build finished with %d failed embedding batches (%d chunks). Re-run to retry.",
            len(failed_ranges), failed_chunk_count,
        )


def main():
    parser = argparse.ArgumentParser(description="Build Feishu Lurk dense vector index")
    parser.add_argument("--jsonl-path", required=True, help="Path to JSONL file with Feishu documents")
    parser.add_argument("--collection-name", default="feishu_lurk_docs", help="Qdrant collection name (default: feishu_lurk_docs)")
    parser.add_argument("--window-size", type=int, default=500, help="Sliding window size in characters (default: 500)")
    parser.add_argument("--overlap", type=int, default=100, help="Overlap characters (default: 100)")
    parser.add_argument("--batch-size", type=int, default=int(os.environ.get("EMBEDDING_BATCH_SIZE", "64")), help="Embedding batch size (default: 64)")
    parser.add_argument("--concurrency", type=int, default=8, help="Concurrent embedding requests (default: 8)")
    parser.add_argument("--project-name", default=None, help="Project name for embedding model resolution")
    args = parser.parse_args()

    collection_name = args.collection_name

    # Resolve embedding model from project config
    embedding_model = None
    if args.project_name:
        try:
            from config.projects import get_project
            proj = get_project(args.project_name)
            embedding_model = proj.embedding_model
        except (ImportError, ValueError) as e:
            logger.warning("Could not resolve project '%s': %s", args.project_name, e)

    start = time.time()
    asyncio.run(build_index(args, collection_name, embedding_model))
    elapsed = time.time() - start
    logger.info("Total time: %.1f seconds", elapsed)


if __name__ == "__main__":
    main()
