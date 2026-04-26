#!/usr/bin/env python3
"""Drop all Qdrant vectors for a given repo. Runs inside dense-indexer container."""
import json
import os
import sys

from qdrant_client import QdrantClient, models


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: dense_drop.py <repo_path>", file=sys.stderr)
        sys.exit(1)

    repo_path = sys.argv[1]
    uri = os.getenv("DENSE_VECTOR_DB_URL", "http://qdrant:6333")
    collection_name = os.getenv("DENSE_COLLECTION_NAME", "aosp_code")

    client = QdrantClient(url=uri)

    if not client.collection_exists(collection_name):
        print(json.dumps({"deleted": 0, "repo": repo_path}))
        return

    count_before = client.count(
        collection_name,
        count_filter=models.Filter(must=[
            models.FieldCondition(key="repo", match=models.MatchValue(value=repo_path))
        ]),
        exact=True,
    ).count

    client.delete(
        collection_name,
        points_selector=models.FilterSelector(filter=models.Filter(must=[
            models.FieldCondition(key="repo", match=models.MatchValue(value=repo_path))
        ])),
    )

    print(json.dumps({"deleted": count_before, "repo": repo_path}))


if __name__ == "__main__":
    main()
