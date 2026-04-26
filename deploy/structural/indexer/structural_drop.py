#!/usr/bin/env python3
"""Delete all structural index nodes for a given repo. Runs inside structural-indexer container."""
import json
import os
import sys

from neo4j import GraphDatabase


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: structural_drop.py <repo_path>", file=sys.stderr)
        sys.exit(1)

    repo_path = sys.argv[1]
    uri = os.getenv("STRUCTURAL_NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("STRUCTURAL_NEO4J_USER", "neo4j")
    password = os.getenv("STRUCTURAL_NEO4J_PASSWORD", "sourcepilot")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session() as session:
        result = session.run(
            "MATCH (n {repo: $repo}) DETACH DELETE n RETURN count(n) AS deleted",
            repo=repo_path,
        )
        record = result.single()
        deleted = record["deleted"] if record else 0

    driver.close()
    print(json.dumps({"deleted": deleted, "repo": repo_path}))


if __name__ == "__main__":
    main()
