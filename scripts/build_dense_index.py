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
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


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


async def fetch_file_list(adapter, repos: str, top_k: int = 5000) -> list[dict]:
    """从 Zoekt 获取 repo 的文件列表。"""
    results = await adapter.search_zoekt(
        query=f"r:{repos} .",
        top_k=top_k,
        score_threshold=0,
    )
    return results


async def fetch_and_chunk_file(adapter, repo: str, filepath: str, window_size: int, overlap: int) -> list[dict]:
    """获取文件内容并切分为 chunks。"""
    try:
        result = await adapter.fetch_file_content(repo=repo, filepath=filepath)
        content = result.get("content", "")
        # 去掉行号前缀（L123: ...）
        lines = []
        for line in content.split("\n"):
            if line.startswith("L") and ": " in line[:10]:
                lines.append(line.split(": ", 1)[1])
            else:
                lines.append(line)
        clean_content = "\n".join(lines)
        return sliding_window_chunks(clean_content, repo, filepath, window_size, overlap)
    except Exception as e:
        logger.warning("Failed to fetch %s/%s: %s", repo, filepath, e)
        return []


async def build_index(args):
    """主索引构建流程。"""
    from adapters.embedding import EmbeddingClient
    from adapters.zoekt import ZoektAdapter
    from config import DENSE_COLLECTION_NAME, DENSE_EMBEDDING_DIM, DENSE_EMBEDDING_MODEL, DENSE_EMBEDDING_URL, DENSE_VECTOR_DB_URL, ZOEKT_URL

    zoekt = ZoektAdapter(zoekt_url=ZOEKT_URL)
    embedding = EmbeddingClient(base_url=DENSE_EMBEDDING_URL, model=DENSE_EMBEDDING_MODEL)

    # 1. 获取文件列表
    logger.info("Fetching file list for repos=%s ...", args.repos)
    file_results = await fetch_file_list(zoekt, repos=args.repos)
    logger.info("Found %d file matches", len(file_results))

    # 去重：提取 unique (repo, path) 对
    seen = set()
    files = []
    for r in file_results:
        meta = r.get("metadata", {})
        repo = meta.get("repo", "")
        path = meta.get("path", "")
        key = (repo, path)
        if key not in seen and repo and path:
            seen.add(key)
            files.append({"repo": repo, "path": path})

    logger.info("Unique files to index: %d", len(files))
    if not files:
        logger.error("No files found. Check repos filter and Zoekt connectivity.")
        return

    # 2. 获取文件内容并切分
    logger.info("Fetching and chunking files (window=%d, overlap=%d) ...", args.window_size, args.overlap)
    all_chunks = []
    for i, f in enumerate(files):
        chunks = await fetch_and_chunk_file(zoekt, f["repo"], f["path"], args.window_size, args.overlap)
        all_chunks.extend(chunks)
        if (i + 1) % 100 == 0:
            logger.info("  processed %d/%d files, %d chunks so far", i + 1, len(files), len(all_chunks))

    logger.info("Total chunks: %d", len(all_chunks))
    if not all_chunks:
        logger.error("No chunks generated. Check file content retrieval.")
        return

    # 3. 批量 embedding
    logger.info("Generating embeddings (batch_size=%d) ...", args.batch_size)
    all_vectors = []
    texts = [c["content"] for c in all_chunks]
    for batch_start in range(0, len(texts), args.batch_size):
        batch_end = min(batch_start + args.batch_size, len(texts))
        batch = texts[batch_start:batch_end]
        try:
            vectors = await embedding.embed(batch)
            all_vectors.extend(vectors)
        except Exception as e:
            logger.error("Embedding failed at batch %d-%d: %s", batch_start, batch_end, e)
            # 为失败的 batch 填充零向量
            all_vectors.extend([[0.0] * DENSE_EMBEDDING_DIM] * len(batch))
        if (batch_start + args.batch_size) % (args.batch_size * 10) == 0:
            logger.info("  embedded %d/%d chunks", min(batch_end, len(texts)), len(texts))

    logger.info("Embedding complete: %d vectors", len(all_vectors))

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
        client.create_index(
            collection_name=DENSE_COLLECTION_NAME,
            field_name="vector",
            index_params={"index_type": "IVF_FLAT", "metric_type": "COSINE", "params": {"nlist": 128}},
        )
        logger.info("Created collection '%s' with IVF_FLAT index", DENSE_COLLECTION_NAME)

    # 批量插入
    insert_batch_size = 1000
    total_inserted = 0
    for batch_start in range(0, len(all_chunks), insert_batch_size):
        batch_end = min(batch_start + insert_batch_size, len(all_chunks))
        batch_data = []
        for i in range(batch_start, batch_end):
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
        try:
            client.insert(collection_name=DENSE_COLLECTION_NAME, data=batch_data)
            total_inserted += len(batch_data)
        except Exception as e:
            logger.error("Insert failed at batch %d-%d: %s", batch_start, batch_end, e)

        if (batch_start + insert_batch_size) % (insert_batch_size * 5) == 0:
            logger.info("  inserted %d/%d chunks", total_inserted, len(all_chunks))

    logger.info("Index build complete: %d chunks inserted into '%s'", total_inserted, DENSE_COLLECTION_NAME)


def main():
    parser = argparse.ArgumentParser(description="Build dense vector index for AOSP code")
    parser.add_argument("--repos", default="frameworks/base", help="Repo filter (default: frameworks/base)")
    parser.add_argument("--window-size", type=int, default=100, help="Sliding window size in lines (default: 100)")
    parser.add_argument("--overlap", type=int, default=50, help="Overlap lines (default: 50)")
    parser.add_argument("--batch-size", type=int, default=32, help="Embedding batch size (default: 32)")
    args = parser.parse_args()

    start = time.time()
    asyncio.run(build_index(args))
    elapsed = time.time() - start
    logger.info("Total time: %.1f seconds", elapsed)


if __name__ == "__main__":
    main()
