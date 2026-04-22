#!/usr/bin/env python3
"""Count Milvus vectors for a given repo. Prints {"count": N} JSON. Runs inside dense-indexer container."""
import json
import os
import sys

from pymilvus import connections, Collection, utility


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: dense_count.py <repo_path>", file=sys.stderr)
        sys.exit(1)

    repo_path = sys.argv[1]
    uri = os.getenv("DENSE_VECTOR_DB_URL", "http://milvus:19530")
    collection_name = os.getenv("DENSE_COLLECTION_NAME", "aosp_code")

    connections.connect(uri=uri)

    if not utility.has_collection(collection_name):
        print(json.dumps({"count": 0}))
        return

    col = Collection(collection_name)
    col.load()
    result = col.query(
        expr=f'repo == "{repo_path}"',
        output_fields=["id"],
        limit=16384,
    )
    print(json.dumps({"count": len(result)}))


if __name__ == "__main__":
    main()
