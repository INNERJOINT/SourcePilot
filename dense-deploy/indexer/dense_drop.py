#!/usr/bin/env python3
"""Drop all Milvus vectors for a given repo. Runs inside dense-indexer container."""
import json
import os
import sys

from pymilvus import connections, Collection, utility


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: dense_drop.py <repo_path>", file=sys.stderr)
        sys.exit(1)

    repo_path = sys.argv[1]
    uri = os.getenv("DENSE_VECTOR_DB_URL", "http://milvus:19530")
    collection_name = os.getenv("DENSE_COLLECTION_NAME", "aosp_code")

    connections.connect(uri=uri)

    if not utility.has_collection(collection_name):
        print(json.dumps({"deleted": 0, "repo": repo_path}))
        return

    col = Collection(collection_name)
    expr = f'repo == "{repo_path}"'
    result = col.delete(expr)
    col.flush()

    print(json.dumps({"deleted": result.delete_count, "repo": repo_path}))


if __name__ == "__main__":
    main()
