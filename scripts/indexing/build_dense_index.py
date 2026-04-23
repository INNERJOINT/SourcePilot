#!/usr/bin/env python3
"""
build_dense_index.py — 向量索引构建脚本

从 Zoekt 获取 frameworks/base 的文件列表，滑动窗口 chunk 分割后
通过 embedding 服务写入 Milvus 向量数据库。

Usage:
    PYTHONPATH=src python scripts/build_dense_index.py [--repos frameworks/base] [--batch-size 32]
"""

import argparse
import asyncio
import hashlib
import logging
import os
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SOURCE_EXTENSIONS = {
    ".java", ".kt", ".py", ".c", ".cc", ".cpp", ".h", ".hpp",
    ".aidl", ".rs", ".go",
}


def sliding_window_chunks(
    content: str,
    repo: str,
    path: str,
    window_size: int = 100,
    overlap: int = 50,
) -> list[dict]:
    """将文件内容按滑动窗口切分为 chunks。

    Args:
        content: 文件全文
        repo: 仓库名
        path: 文件路径
        window_size: 窗口大小（行数）
        overlap: 重叠行数

    Returns:
        list of chunk dicts with metadata
    """
    lines = content.split("\n")
    total = len(lines)
    if total == 0:
        return []

    chunks = []
    step = window_size - overlap
    if step <= 0:
        step = 1

    for start in range(0, total, step):
        end = min(start + window_size, total)
        chunk_lines = lines[start:end]
        chunk_text = "\n".join(chunk_lines)

        if not chunk_text.strip():
            continue

        # 推断语言
        lang = _infer_language(path)

        chunks.append({
            "content": chunk_text,
            "repo": repo,
            "path": path,
            "start_line": start + 1,
            "end_line": end,
            "language": lang,
            "content_hash": hashlib.md5(chunk_text.encode()).hexdigest(),
        })

        if end >= total:
            break

    return chunks


def _infer_language(path: str) -> str:
    """从文件扩展名推断语言。"""
    ext_map = {
        ".java": "java",
        ".kt": "kotlin",
        ".py": "python",
        ".c": "c",
        ".cc": "cpp",
        ".cpp": "cpp",
        ".h": "c",
        ".hpp": "cpp",
        ".xml": "xml",
        ".json": "json",
        ".mk": "makefile",
        ".bp": "blueprint",
        ".aidl": "aidl",
        ".rs": "rust",
        ".go": "go",
    }
    for ext, lang in ext_map.items():
        if path.endswith(ext):
            return lang
    return "unknown"


def scan_source_files(source_dir: str, repo: str) -> list[dict]:
    """扫描本地目录，返回源码文件列表。"""
    files = []
    for root, _dirs, filenames in os.walk(source_dir):
        for fname in filenames:
            ext = os.path.splitext(fname)[1]
            if ext not in SOURCE_EXTENSIONS:
                continue
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, source_dir)
            files.append({"repo": repo, "path": rel, "full_path": full})
    return files


def read_and_chunk_file(entry: dict, window_size: int, overlap: int) -> list[dict]:
    """读取本地文件并切分为 chunks。"""
    try:
        with open(entry["full_path"], encoding="utf-8", errors="replace") as f:
            content = f.read()
        return sliding_window_chunks(content, entry["repo"], entry["path"], window_size, overlap)
    except Exception as e:
        logger.warning("Failed to read %s: %s", entry["full_path"], e)
        return []


async def build_index(args, collection_name: str):
    """主索引构建流程。"""
    from adapters.embedding import EmbeddingClient
    from config import DENSE_COLLECTION_NAME, DENSE_EMBEDDING_DIM, DENSE_EMBEDDING_MODEL, DENSE_EMBEDDING_URL, DENSE_VECTOR_DB_URL

    DENSE_COLLECTION_NAME = collection_name  # override with resolved name

    embedding = EmbeddingClient(base_url=DENSE_EMBEDDING_URL, model=DENSE_EMBEDDING_MODEL)

    # 1. 扫描本地文件
    logger.info("Scanning source files in %s ...", args.source_dir)
    files = scan_source_files(args.source_dir, repo=args.repo_name)
    logger.info("Found %d source files", len(files))
    if not files:
        logger.error("No source files found in %s", args.source_dir)
        return

    # 2. 切分 chunks
    logger.info("Chunking files (window=%d, overlap=%d) ...", args.window_size, args.overlap)
    all_chunks = []
    for i, f in enumerate(files):
        chunks = read_and_chunk_file(f, args.window_size, args.overlap)
        all_chunks.extend(chunks)
        if (i + 1) % 500 == 0:
            logger.info("  processed %d/%d files, %d chunks so far", i + 1, len(files), len(all_chunks))

    logger.info("Total chunks: %d", len(all_chunks))
    if not all_chunks:
        logger.error("No chunks generated. Check file content retrieval.")
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
                        logger.error("Embedding failed at batch %d-%d after 3 retries: %s — skipping", batch_start, batch_end, e)
                        failed_ranges.append((batch_start, batch_end))
                        return
                    await asyncio.sleep(2 ** attempt)

    tasks = []
    for batch_start in range(0, len(texts), args.batch_size):
        batch_end = min(batch_start + args.batch_size, len(texts))
        tasks.append(embed_batch(batch_start, batch_end))

    # 分组执行并报告进度；return_exceptions 防止单任务异常冲掉整组
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

    # 4. 写入 Milvus
    logger.info("Writing to Milvus (collection=%s) ...", DENSE_COLLECTION_NAME)
    from pymilvus import CollectionSchema, DataType, FieldSchema, MilvusClient

    client = MilvusClient(uri=DENSE_VECTOR_DB_URL)

    # 创建 collection（如果不存在）
    collections = client.list_collections()
    if DENSE_COLLECTION_NAME not in collections:
        schema = CollectionSchema(fields=[
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=DENSE_EMBEDDING_DIM),
            FieldSchema(name="repo", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="path", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="start_line", dtype=DataType.INT32),
            FieldSchema(name="end_line", dtype=DataType.INT32),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="language", dtype=DataType.VARCHAR, max_length=32),
            FieldSchema(name="content_hash", dtype=DataType.VARCHAR, max_length=32),
        ])
        client.create_collection(
            collection_name=DENSE_COLLECTION_NAME,
            schema=schema,
        )
        # 创建向量索引
        index_params = client.prepare_index_params()
        index_params.add_index(field_name="vector", index_type="IVF_FLAT", metric_type="COSINE", params={"nlist": 128})
        client.create_index(collection_name=DENSE_COLLECTION_NAME, index_params=index_params)
        logger.info("Created collection '%s' with IVF_FLAT index", DENSE_COLLECTION_NAME)

    # 批量插入（跳过 embedding 失败的 chunk）
    insert_batch_size = 1000
    total_inserted = 0
    total_skipped = 0
    for batch_start in range(0, len(all_chunks), insert_batch_size):
        batch_end = min(batch_start + insert_batch_size, len(all_chunks))
        batch_data = []
        for i in range(batch_start, batch_end):
            if all_vectors[i] is None:
                total_skipped += 1
                continue
            chunk = all_chunks[i]
            batch_data.append({
                "vector": all_vectors[i],
                "repo": chunk["repo"],
                "path": chunk["path"],
                "start_line": chunk["start_line"],
                "end_line": chunk["end_line"],
                "content": chunk["content"][:65535],
                "language": chunk["language"],
                "content_hash": chunk["content_hash"],
            })
        if not batch_data:
            continue
        try:
            client.insert(collection_name=DENSE_COLLECTION_NAME, data=batch_data)
            total_inserted += len(batch_data)
        except Exception as e:
            logger.error("Insert failed at batch %d-%d: %s", batch_start, batch_end, e)

        if (batch_start + insert_batch_size) % (insert_batch_size * 5) == 0:
            logger.info("  inserted %d/%d chunks", total_inserted, len(all_chunks))

    # Flush to persist data
    client.flush(DENSE_COLLECTION_NAME)
    logger.info("Flushed collection")

    logger.info(
        "Index build complete: %d inserted, %d skipped (embedding-failed), collection='%s'",
        total_inserted, total_skipped, DENSE_COLLECTION_NAME,
    )
    if failed_ranges:
        logger.warning(
            "Build finished with %d failed embedding batches (%d chunks). Re-run on this repo to retry.",
            len(failed_ranges), failed_chunk_count,
        )


def main():
    parser = argparse.ArgumentParser(description="Build dense vector index for AOSP code")
    parser.add_argument("--source-dir", default="/mnt/code/ACE/frameworks/base", help="Local source directory to index")
    parser.add_argument("--repo-name", default="frameworks/base", help="Repo name stored in metadata (default: frameworks/base)")
    parser.add_argument("--window-size", type=int, default=30, help="Sliding window size in lines (default: 30)")
    parser.add_argument("--overlap", type=int, default=10, help="Overlap lines (default: 10)")
    parser.add_argument("--batch-size", type=int, default=32, help="Embedding batch size (default: 32)")
    parser.add_argument("--concurrency", type=int, default=8, help="Concurrent embedding requests (default: 8)")
    parser.add_argument("--project-name", default=None, help="Project name for collection naming (e.g. 'ace' → collection 'aosp_code_ace')")
    parser.add_argument("--collection-name", default=None, help="Override Milvus collection name")
    args = parser.parse_args()

    # Resolve collection name
    if args.collection_name:
        collection_name = args.collection_name
    elif args.project_name:
        collection_name = f"aosp_code_{args.project_name}"
    else:
        from config import DENSE_COLLECTION_NAME
        collection_name = DENSE_COLLECTION_NAME

    start = time.time()
    asyncio.run(build_index(args, collection_name))
    elapsed = time.time() - start
    logger.info("Total time: %.1f seconds", elapsed)


if __name__ == "__main__":
    main()
