"""
structural_traversal — Neo4j 结构化检索遍历工具函数

提供 fulltext_search_nodes、expand_neighbors、compute_structural_score、
extract_query_entities 和 format_hit 等工具函数，供 StructuralAdapter 调用。

所有 Cypher 参数均使用参数化查询，严禁 f-string 拼接（防注入）。
"""

import re


async def fulltext_search_nodes(
    driver,
    query_terms: list[str],
    limit: int = 20,
    project: str | None = None,
) -> list[dict]:
    """全文检索 Neo4j 节点，同时查询 symbol_name_idx 和 doc_entity_idx。

    返回去重后的节点列表，每条形如：
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
                # 索引不存在时跳过（如首次使用前尚未建索引）
                pass

    return list(seen.values())


async def expand_neighbors(
    driver,
    node_ids: list[int],
    max_hops: int = 2,
    project: str | None = None,
) -> list[dict]:
    """从种子节点出发，沿关系边扩展至最多 max_hops 跳，返回到达的 File 节点信息。

    返回列表，每条形如：
        {"file_props": dict, "path_length": int, "anchor_nids": list[int]}
    """
    if not node_ids:
        return []

    cypher = """
    MATCH (seed) WHERE id(seed) IN $ids
    MATCH (seed)-[*1..$hops]-(file:File)
    WHERE $project IS NULL OR file.project = $project
    WITH file, min(length((seed)-[*]-(file))) AS dist, collect(id(seed)) AS anchors
    RETURN properties(file) AS file_props, dist AS path_length, anchors
    ORDER BY dist ASC
    LIMIT 100
    """

    results: list[dict] = []
    async with driver.session() as session:
        try:
            result = await session.run(
                cypher,
                {"ids": node_ids, "hops": max_hops, "project": project},
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
    """计算结构化检索得分。

    score = alpha * (1/path_length) + (1-alpha) * (match_count / max_match_count)
    结果归一化到 [0, 1]。
    """
    proximity = 1.0 / max(path_length, 1)
    coverage = match_count / max(max_match_count, 1)
    score = alpha * proximity + (1.0 - alpha) * coverage
    return max(0.0, min(1.0, score))


def extract_query_entities(query: str) -> list[str]:
    """从查询字符串中提取实体词元（CamelCase、snake_case、3+ 字符词）。

    返回去重后的小写词元列表，用于全文检索。
    """
    tokens: list[str] = []

    # CamelCase 词（如 ActivityManager、SurfaceFlinger）
    camel = re.findall(r"[A-Z][a-z]+(?:[A-Z][a-z]+)+", query)
    tokens.extend(camel)

    # snake_case 标识符（如 get_window_manager）
    snake = re.findall(r"[a-z]+(?:_[a-z]+)+", query)
    tokens.extend(snake)

    # 3+ 字符的字母数字词
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9]{2,}", query)
    tokens.extend(words)

    # 小写去重
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
    """将结构化遍历结果格式化为 StructuralAdapter 统一 hit dict。

    输出格式：
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
        "score": 0.0,  # 由调用方 compute_structural_score 填充
        "matched_terms": matched_terms,
    }
