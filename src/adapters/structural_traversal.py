"""
structural_traversal — Neo4j structural retrieval traversal utilities

Provides fulltext_search_nodes, expand_neighbors, compute_structural_score,
extract_query_entities, and format_hit helper functions used by StructuralAdapter.

All Cypher parameters use parameterized queries — f-string concatenation is strictly
forbidden to prevent injection attacks.
"""

import re


async def fulltext_search_nodes(
    driver,
    query_terms: list[str],
    limit: int = 20,
    project: str | None = None,
) -> list[dict]:
    """Full-text search for Neo4j nodes, querying both symbol_name_idx and doc_entity_idx.

    Returns a deduplicated list of nodes, each of the form:
        {"nid": int, "kind": str, "props": dict, "score": float}
    """
    if not query_terms:
        return []

    q = " ".join(query_terms)
    cypher = """
    CALL db.index.fulltext.queryNodes($idx, $q)
    YIELD node, score
    WHERE $project IS NULL OR node.project = $project
    RETURN id(node) AS nid, labels(node)[0] AS kind,
           properties(node) AS props, score
    LIMIT $limit
    """

    seen: dict[int, dict] = {}
    async with driver.session() as session:
        for idx_name in ("symbol_name_idx", "doc_entity_idx"):
            try:
                result = await session.run(
                    cypher,
                    {"idx": idx_name, "q": q, "limit": limit, "project": project},
                )
                async for record in result:
                    nid = record["nid"]
                    if nid not in seen or record["score"] > seen[nid]["score"]:
                        seen[nid] = {
                            "nid": nid,
                            "kind": record["kind"],
                            "props": dict(record["props"]),
                            "score": record["score"],
                        }
            except Exception:
                # Skip if the index does not exist (e.g. before the index has been built)
                pass

    return list(seen.values())


async def expand_neighbors(
    driver,
    node_ids: list[int],
    max_hops: int = 2,
    project: str | None = None,
) -> list[dict]:
    """Starting from seed nodes, traverse relationship edges up to max_hops hops and return reached File nodes.

    Returns a list, each entry of the form:
        {"file_props": dict, "path_length": int, "anchor_nids": list[int]}
    """
    if not node_ids:
        return []

    hops = int(max_hops)
    if hops < 1 or hops > 10:
        raise ValueError(f"max_hops must be between 1 and 10, got {hops}")

    cypher = f"""
    MATCH (seed) WHERE id(seed) IN $ids
    MATCH p = (seed)-[*1..{hops}]-(file:File)
    WHERE $project IS NULL OR file.project = $project
    WITH file, min(length(p)) AS dist, collect(DISTINCT id(seed)) AS anchors
    RETURN properties(file) AS file_props, dist AS path_length, anchors
    ORDER BY dist ASC
    LIMIT 100
    """

    results: list[dict] = []
    async with driver.session() as session:
        try:
            result = await session.run(
                cypher,
                {"ids": node_ids, "project": project},
            )
            async for record in result:
                results.append(
                    {
                        "file_props": dict(record["file_props"]),
                        "path_length": record["path_length"],
                        "anchor_nids": list(record["anchors"]),
                    }
                )
        except Exception:
            pass

    return results


def compute_structural_score(
    path_length: int,
    match_count: int,
    max_match_count: int,
    alpha: float = 0.6,
) -> float:
    """Compute a structural retrieval score.

    score = alpha * (1/path_length) + (1-alpha) * (match_count / max_match_count)
    Result is normalized to [0, 1].
    """
    proximity = 1.0 / max(path_length, 1)
    coverage = match_count / max(max_match_count, 1)
    score = alpha * proximity + (1.0 - alpha) * coverage
    return max(0.0, min(1.0, score))


def extract_query_entities(query: str) -> list[str]:
    """Extract entity tokens from a query string (CamelCase, snake_case, 3+ character words).

    Returns a deduplicated list of lowercase tokens for use in full-text search.
    """
    tokens: list[str] = []

    # CamelCase words (e.g. ActivityManager, SurfaceFlinger)
    camel = re.findall(r"[A-Z][a-z]+(?:[A-Z][a-z]+)+", query)
    tokens.extend(camel)

    # snake_case identifiers (e.g. get_window_manager)
    snake = re.findall(r"[a-z]+(?:_[a-z]+)+", query)
    tokens.extend(snake)

    # Alphanumeric words of 3+ characters
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9]{2,}", query)
    tokens.extend(words)

    # Deduplicate while lowercasing
    seen: dict[str, None] = {}
    result: list[str] = []
    for t in tokens:
        lt = t.lower()
        if lt not in seen:
            seen[lt] = None
            result.append(lt)
    return result


def format_hit(
    file_node_props: dict,
    path_length: int,
    matched_terms: list[str],
) -> dict:
    """Format a structural traversal result into a unified hit dict for StructuralAdapter.

    Output format:
        {"repo": str, "path": str, "start_line": int|None,
         "end_line": int|None, "content": str, "score": float,
         "matched_terms": list[str]}
    """
    return {
        "repo": file_node_props.get("repo", ""),
        "path": file_node_props.get("path", ""),
        "start_line": file_node_props.get("start_line"),
        "end_line": file_node_props.get("end_line"),
        "content": file_node_props.get("content", ""),
        "score": 0.0,  # filled in by the caller via compute_structural_score
        "matched_terms": matched_terms,
    }
