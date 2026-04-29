"""
build_structural_index.py — SourcePilot structural index builder

Purpose:
    Walk an AOSP source directory, extract Java/C++/Python file, class,
    and method nodes plus their edge relationships via tree-sitter,
    and batch-write them into a Neo4j graph database.

Usage:
    python scripts/build_structural_index.py \\
        --source-root /opt/aosp/aosp_project/.repo/frameworks/base \\
        --languages java,cpp,python \\
        --batch-size 100

    # Rebuild (clear all nodes first)
    python scripts/build_structural_index.py --source-root /path/to/src --reset

    # Process only the first 500 files (for testing)
    python scripts/build_structural_index.py --source-root /path/to/src --max-files 500

Environment variables (can be overridden by command-line arguments):
    STRUCTURAL_NEO4J_URI      default bolt://localhost:7687
    STRUCTURAL_NEO4J_USER     default neo4j
    STRUCTURAL_NEO4J_PASSWORD default sourcepilot
"""

import argparse
import os
import re as _re
import sys

# ---------------------------------------------------------------------------
# 1. Argparse — must come before heavy imports so --help works even if deps are missing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Build AOSP source -> Neo4j structural index",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--source-root",
        required=True,
        help="Source root directory, e.g. /opt/aosp/aosp_project/.repo/frameworks/base",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of nodes/edges per Cypher UNWIND batch (default 100)",
    )
    p.add_argument(
        "--languages",
        default="java,cpp,python",
        help="Comma-separated list of languages to parse (default java,cpp,python)",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Abort with exit(3) when parse failure rate > 0.2",
    )
    p.add_argument(
        "--neo4j-uri",
        default=os.environ.get("STRUCTURAL_NEO4J_URI", "bolt://localhost:7687"),
        help="Neo4j Bolt URI (default bolt://localhost:7687)",
    )
    p.add_argument(
        "--neo4j-user",
        default=os.environ.get("STRUCTURAL_NEO4J_USER", "neo4j"),
        help="Neo4j username (default neo4j)",
    )
    p.add_argument(
        "--neo4j-password",
        default=os.environ.get("STRUCTURAL_NEO4J_PASSWORD", "sourcepilot"),
        help="Neo4j password (default sourcepilot)",
    )
    p.add_argument(
        "--reset",
        action="store_true",
        help="Clear all nodes and indexes before building",
    )
    p.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Process at most N files (safety limit for testing)",
    )
    p.add_argument(
        "--project-name",
        default=None,
        help="Project tag for per-project isolation",
    )
    p.add_argument(
        "--repo-name",
        default=None,
        help=(
            "Repository label stored on File.repo (e.g. frameworks/base). "
            "When omitted, default mode derives repo from frameworks/* and packages/*/* "
            "or falls back to synthetic project-root repo."
        ),
    )
    # DocEntity LLM extraction (Pass 2)
    p.add_argument(
        "--extract-doc-entities",
        action="store_true",
        default=False,
        help="Enable Pass 2: extract domain concept nodes (DocEntity) from comments via LLM",
    )
    p.add_argument(
        "--max-doc-entities",
        type=int,
        default=500,
        help="DocEntity extraction cap; stops immediately when reached (default 500)",
    )
    p.add_argument(
        "--doc-entity-llm-model",
        default=os.environ.get("NL_MODEL", ""),
        help="LLM model used for DocEntity extraction (default $NL_MODEL)",
    )
    p.add_argument(
        "--doc-entity-batch-size",
        type=int,
        default=10,
        help="Number of comment blocks sent to the LLM per concurrent call (default 10)",
    )
    return p


# ---------------------------------------------------------------------------
# 2. Lazy-import heavy dependencies (tree-sitter / neo4j driver)
# ---------------------------------------------------------------------------


def _import_neo4j():
    try:
        from neo4j import GraphDatabase  # noqa: F401

        return GraphDatabase
    except ImportError:
        print(
            "Error: missing neo4j package, please run: pip install neo4j",
            file=sys.stderr,
        )
        sys.exit(4)


def _import_tree_sitter_parsers(languages: list[str]):
    """
    Return a {lang: Parser} dict.
    If tree_sitter or the corresponding grammar package is not installed,
    print an error and exit(4).
    """
    try:
        import tree_sitter  # noqa: F401
    except ImportError:
        print(
            "Error: missing tree-sitter package, please run: pip install tree-sitter "
            "tree-sitter-java tree-sitter-cpp tree-sitter-python",
            file=sys.stderr,
        )
        sys.exit(4)

    from tree_sitter import Language, Parser

    parsers: dict = {}
    lang_pkg_map = {
        "java": ("tree_sitter_java", "java"),
        "cpp": ("tree_sitter_cpp", "cpp"),
        "python": ("tree_sitter_python", "python"),
    }
    for lang in languages:
        pkg, lang_name = lang_pkg_map.get(lang, (None, None))
        if pkg is None:
            print(f"Warning: unsupported language '{lang}', skipping", file=sys.stderr)
            continue
        try:
            mod = __import__(pkg)
            language = Language(mod.language())
            parser = Parser(language)
            parsers[lang] = parser
        except (ImportError, Exception) as exc:
            print(f"Warning: failed to load {lang} grammar package ({exc}), skipping", file=sys.stderr)
    return parsers


# ---------------------------------------------------------------------------
# 3. File extension -> language mapping
# ---------------------------------------------------------------------------

EXT_TO_LANG: dict[str, str] = {
    ".java": "java",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
    ".py": "python",
}


def _collect_files(
    source_root: str, languages: list[str], max_files: int | None
) -> list[tuple[str, str]]:
    """Return a list of [(absolute_file_path, language)]."""
    results: list[tuple[str, str]] = []
    lang_set = set(languages)
    for dirpath, _, filenames in os.walk(source_root):
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            lang = EXT_TO_LANG.get(ext)
            if lang and lang in lang_set:
                results.append((os.path.join(dirpath, fname), lang))
                if max_files and len(results) >= max_files:
                    return results
    return results


# ---------------------------------------------------------------------------
# 4. tree-sitter parsing: extract nodes and edges
# ---------------------------------------------------------------------------


def _normalize_rel_path(path: str) -> str:
    return path.replace(os.sep, "/")


def _derive_repo_and_path(
    file_path: str,
    source_root: str,
    project: str,
    repo_name: str | None = None,
) -> tuple[str, str, str]:
    """
    Compute the repo/path for the structural index identity.

    Returns (repo, repo_relative_path, repo_mode):
      - repo_mode=explicit: from --repo-name
      - repo_mode=derived: inferred from default conventions (frameworks/* or packages/*/*)
      - repo_mode=project_root: synthetic repo (project) used when conventions do not apply
    """
    abs_root = os.path.abspath(source_root)
    abs_file = os.path.abspath(file_path)
    rel = _normalize_rel_path(os.path.relpath(abs_file, abs_root))

    if rel == "." or rel.startswith("../"):
        raise ValueError(f"File is not under source_root: file={file_path}, source_root={source_root}")

    if repo_name:
        return repo_name, rel, "explicit"

    # Default whole-project mode: prefer deriving repo boundary from frameworks/* and packages/*/*
    parts = rel.split("/")
    if len(parts) >= 3 and parts[0] == "frameworks":
        repo = f"frameworks/{parts[1]}"
        return repo, "/".join(parts[2:]), "derived"
    if len(parts) >= 4 and parts[0] == "packages":
        repo = f"packages/{parts[1]}/{parts[2]}"
        return repo, "/".join(parts[3:]), "derived"

    # If source_root itself is frameworks/<repo> or packages/<org>/<repo>, also derive compatibly
    root_parts = _normalize_rel_path(abs_root).strip("/").split("/")
    if len(root_parts) >= 2 and root_parts[-2] == "frameworks":
        return f"frameworks/{root_parts[-1]}", rel, "derived"
    if len(root_parts) >= 3 and root_parts[-3] == "packages":
        return f"packages/{root_parts[-2]}/{root_parts[-1]}", rel, "derived"

    # Synthetic project-root mode (for files that cannot be split into repos by convention)
    return project, rel, "project_root"


def _extract_nodes_edges(
    file_path: str,
    lang: str,
    parser,
    source_root: str,
    project: str,
    repo_name: str | None = None,
) -> tuple[dict, list]:
    """
    Returns:
        nodes: {"file": {...}, "classes": [...], "methods": [...]}
        edges: [{"type": "DEFINED_IN"|"MEMBER_OF"|"INHERITS"|"CALLS", ...}]
    Returns (None, None) on parse failure.
    """
    try:
        with open(file_path, "rb") as f:
            source = f.read()
    except OSError:
        return None, None

    try:
        tree = parser.parse(source)
    except Exception:
        return None, None

    try:
        repo, repo_rel_path, repo_mode = _derive_repo_and_path(
            file_path=file_path,
            source_root=source_root,
            project=project,
            repo_name=repo_name,
        )
    except ValueError:
        return None, None

    file_node = {
        "path": repo_rel_path,
        "repo": repo,
        "language": lang,
        "project": project,
        "structural_repo_mode": repo_mode,
    }
    classes: list[dict] = []
    methods: list[dict] = []
    edges: list[dict] = []

    root = tree.root_node

    # --- Generic AST traversal ---
    def node_text(n) -> str:
        return source[n.start_byte : n.end_byte].decode("utf-8", errors="replace")

    def walk(n, current_class: str | None = None):
        # Java / C++ class / struct
        if n.type in ("class_declaration", "struct_specifier", "class_specifier"):
            name_node = n.child_by_field_name("name")
            if name_node:
                cname = node_text(name_node)
                cls = {
                    "name": cname,
                    "path": repo_rel_path,
                    "repo": repo,
                    "start_line": n.start_point[0] + 1,
                    "end_line": n.end_point[0] + 1,
                    "project": project,
                }
                classes.append(cls)
                edges.append(
                    {
                        "type": "DEFINED_IN",
                        "from": cname,
                        "from_label": "Class",
                        "from_path": repo_rel_path,
                        "from_repo": repo,
                        "to_path": repo_rel_path,
                        "to_repo": repo,
                        "project": project,
                    }
                )
                # Inheritance (Java: superclass / C++: base_class_clause)
                for child in n.children:
                    if child.type in ("superclass", "base_class_clause"):
                        for sc in child.children:
                            if sc.type in ("type_identifier", "identifier"):
                                edges.append(
                                    {
                                        "type": "INHERITS",
                                        "from": cname,
                                        "from_repo": repo,
                                        "from_path": repo_rel_path,
                                        "from_label": "Class",
                                        "to": node_text(sc),
                                        "to_label": "Class",
                                        "project": project,
                                    }
                                )
                # Recurse into class body
                for child in n.children:
                    walk(child, current_class=cname)
                return

        # Java method / C++ function / Python function/method
        if n.type in (
            "method_declaration",
            "function_definition",
            "function_declarator",
            "constructor_declaration",
        ):
            name_node = n.child_by_field_name("name") or n.child_by_field_name("declarator")
            if name_node:
                mname = node_text(name_node)
                # Extract signature (function name + parameters)
                params_node = n.child_by_field_name("parameters")
                sig = mname + (node_text(params_node) if params_node else "()")
                method = {
                    "name": mname,
                    "path": repo_rel_path,
                    "repo": repo,
                    "start_line": n.start_point[0] + 1,
                    "end_line": n.end_point[0] + 1,
                    "signature": sig,
                    "project": project,
                }
                methods.append(method)
                edges.append(
                    {
                        "type": "DEFINED_IN",
                        "from": mname,
                        "from_signature": sig,
                        "from_label": "Method",
                        "from_path": repo_rel_path,
                        "from_repo": repo,
                        "to_path": repo_rel_path,
                        "to_repo": repo,
                        "project": project,
                    }
                )
                if current_class:
                    edges.append(
                        {
                            "type": "MEMBER_OF",
                            "from": mname,
                            "from_signature": sig,
                            "from_label": "Method",
                            "from_path": repo_rel_path,
                            "from_repo": repo,
                            "to": current_class,
                            "to_label": "Class",
                            "to_path": repo_rel_path,
                            "to_repo": repo,
                            "project": project,
                        }
                    )
                # CALLS edges: scan call expressions in method body (best-effort)
                body = n.child_by_field_name("body")
                if body:
                    _extract_calls(body, mname, sig, source, edges)

        for child in n.children:
            walk(child, current_class=current_class)

    def _extract_calls(body_node, caller: str, caller_sig: str, src: bytes, out_edges: list):
        """Recursively extract callee method names from call_expression nodes."""
        for child in body_node.children:
            if child.type in ("call_expression", "method_invocation"):
                fn_node = child.child_by_field_name("function") or child.child_by_field_name("name")
                if fn_node:
                    callee_text = src[fn_node.start_byte : fn_node.end_byte].decode(
                        "utf-8", errors="replace"
                    )
                    # Take the last segment (strip obj. prefix)
                    callee = callee_text.rsplit(".", 1)[-1]
                    out_edges.append(
                        {
                            "type": "CALLS",
                            "from": caller,
                            "from_signature": caller_sig,
                            "from_label": "Method",
                            "from_path": repo_rel_path,
                            "from_repo": repo,
                            "to": callee,
                            "to_label": "Method",
                            "project": project,
                        }
                    )
            _extract_calls(child, caller, caller_sig, src, out_edges)

    walk(root)
    return {"file": file_node, "classes": classes, "methods": methods}, edges


# ---------------------------------------------------------------------------
# 5. Neo4j operations
# ---------------------------------------------------------------------------

SCHEMA_CYPHER = [
    "CREATE INDEX class_name IF NOT EXISTS FOR (c:Class) ON (c.name)",
    "CREATE INDEX method_name IF NOT EXISTS FOR (m:Method) ON (m.name)",
    "CREATE INDEX node_project IF NOT EXISTS FOR (f:File) ON (f.project)",
    "CREATE INDEX file_repo IF NOT EXISTS FOR (f:File) ON (f.repo)",
    "CREATE INDEX class_project IF NOT EXISTS FOR (c:Class) ON (c.project)",
    "CREATE INDEX method_project IF NOT EXISTS FOR (m:Method) ON (m.project)",
]

FULLTEXT_INDEX_NAME = "symbol_name_idx"
DOC_ENTITY_INDEX_NAME = "doc_entity_idx"


def _preflight_file_identity_constraints(session):
    """
    Pre-migration check: ensure File uniqueness is upgraded from path to (project, repo, path).

    Steps:
      1) Verify existing File nodes have non-empty project/repo/path
      2) Check for (project, repo, path) duplicates
      3) Create composite unique constraint
      4) Drop the old File.path single-field unique constraint (if present)

    Raises RuntimeError with remediation hints on check failure.
    """
    missing = session.run(
        "MATCH (f:File) "
        "WHERE f.project IS NULL OR f.repo IS NULL OR f.path IS NULL "
        "   OR trim(toString(f.project)) = '' "
        "   OR trim(toString(f.repo)) = '' "
        "   OR trim(toString(f.path)) = '' "
        "RETURN count(f) AS cnt"
    ).single()["cnt"]
    if missing > 0:
        raise RuntimeError(
            "File nodes are missing project/repo/path; cannot safely migrate to composite "
            "unique constraint. Run --reset to rebuild, or backfill historical data first."
        )

    dup = session.run(
        "MATCH (f:File) "
        "WITH f.project AS project, f.repo AS repo, f.path AS path, count(*) AS c "
        "WHERE c > 1 "
        "RETURN project, repo, path, c "
        "ORDER BY c DESC LIMIT 5"
    ).data()
    if dup:
        sample = "; ".join(f"({d['project']}, {d['repo']}, {d['path']}) x{d['c']}" for d in dup)
        raise RuntimeError(
            "Detected duplicate File composite keys; cannot safely create (project,repo,path) "
            f"unique constraint. Samples: {sample}. "
            "Run --reset to rebuild, or manually deduplicate before retrying."
        )

    session.run(
        "CREATE CONSTRAINT file_project_repo_path IF NOT EXISTS "
        "FOR (f:File) REQUIRE (f.project, f.repo, f.path) IS UNIQUE"
    )

    constraints = session.run(
        "SHOW CONSTRAINTS YIELD name, labelsOrTypes, properties "
        "WHERE 'File' IN labelsOrTypes RETURN name, properties"
    ).data()
    for c in constraints:
        props = c.get("properties") or []
        if c.get("name") == "file_path" or props == ["path"]:
            session.run(f"DROP CONSTRAINT {c['name']} IF EXISTS")


def _bootstrap_schema(session):
    _preflight_file_identity_constraints(session)
    for stmt in SCHEMA_CYPHER:
        session.run(stmt)
    # Create fulltext indexes only if they do not already exist (checked via SHOW INDEXES)
    existing = {rec["name"] for rec in session.run("SHOW INDEXES YIELD name")}
    if FULLTEXT_INDEX_NAME not in existing:
        session.run(
            f"CREATE FULLTEXT INDEX {FULLTEXT_INDEX_NAME} IF NOT EXISTS "
            "FOR (n:Class|Method) ON EACH [n.name]"
        )
    if DOC_ENTITY_INDEX_NAME not in existing:
        session.run(
            f"CREATE FULLTEXT INDEX {DOC_ENTITY_INDEX_NAME} IF NOT EXISTS "
            "FOR (n:DocEntity) ON EACH [n.name, n.concept_text]"
        )


def _reset_structural(session, project=None):
    if project:
        session.run(
            "CALL { MATCH (n {project: $project}) "
            "WITH n LIMIT 10000 DETACH DELETE n "
            "} IN TRANSACTIONS OF 10000 ROWS",
            project=project,
        )
    else:
        session.run("MATCH (n) DETACH DELETE n")


def _upsert_batch(session, nodes_batch: list[dict], edges_batch: list[dict]):
    """Batch-write File/Class/Method nodes and their edges."""
    # File nodes
    files = [n["file"] for n in nodes_batch]
    session.run(
        "UNWIND $files AS f "
        "MERGE (node:File {project: f.project, repo: f.repo, path: f.path}) "
        "SET node.language = f.language, node.structural_repo_mode = f.structural_repo_mode",
        files=files,
    )
    # Class nodes
    classes = [c for n in nodes_batch for c in n["classes"]]
    if classes:
        session.run(
            "UNWIND $cls AS c "
            "MERGE (node:Class {name: c.name, path: c.path, repo: c.repo, project: c.project}) "
            "SET node.start_line = c.start_line, node.end_line = c.end_line",
            cls=classes,
        )
    # Method nodes
    methods = [m for n in nodes_batch for m in n["methods"]]
    if methods:
        session.run(
            "UNWIND $mth AS m "
            "MERGE (node:Method {"
            "name: m.name, signature: m.signature, path: m.path, "
            "repo: m.repo, project: m.project"
            "}) "
            "SET node.start_line = m.start_line, node.end_line = m.end_line",
            mth=methods,
        )

    # Edges: DEFINED_IN (Class/Method -> File)
    defined_in = [e for e in edges_batch if e["type"] == "DEFINED_IN"]
    if defined_in:
        for e in defined_in:
            if e["from_label"] == "Method":
                session.run(
                    "MATCH (src:Method {"
                    "name: $from_name, signature: $from_signature, "
                    "project: $project, repo: $from_repo, path: $from_path"
                    "}) "
                    "MATCH (f:File {project: $project, repo: $to_repo, path: $to_path}) "
                    "MERGE (src)-[:DEFINED_IN]->(f)",
                    from_name=e["from"],
                    from_signature=e["from_signature"],
                    from_repo=e["from_repo"],
                    from_path=e["from_path"],
                    to_repo=e["to_repo"],
                    to_path=e["to_path"],
                    project=e.get("project"),
                )
            else:
                session.run(
                    "MATCH (src:Class {"
                    "name: $from_name, project: $project, "
                    "repo: $from_repo, path: $from_path"
                    "}) "
                    "MATCH (f:File {project: $project, repo: $to_repo, path: $to_path}) "
                    "MERGE (src)-[:DEFINED_IN]->(f)",
                    from_name=e["from"],
                    from_repo=e["from_repo"],
                    from_path=e["from_path"],
                    to_repo=e["to_repo"],
                    to_path=e["to_path"],
                    project=e.get("project"),
                )
    # Edges: MEMBER_OF (Method -> Class)
    member_of = [e for e in edges_batch if e["type"] == "MEMBER_OF"]
    if member_of:
        for e in member_of:
            session.run(
                "MATCH (m:Method {"
                "name: $mname, signature: $msig, project: $project, repo: $mrepo, path: $mpath"
                "}) "
                "MATCH (c:Class {name: $cname, project: $project, repo: $crepo, path: $cpath}) "
                "MERGE (m)-[:MEMBER_OF]->(c)",
                mname=e["from"],
                msig=e["from_signature"],
                mrepo=e["from_repo"],
                mpath=e["from_path"],
                cname=e["to"],
                crepo=e["to_repo"],
                cpath=e["to_path"],
                project=e.get("project"),
            )
    # Edges: INHERITS (Class -> Class)
    inherits = [e for e in edges_batch if e["type"] == "INHERITS"]
    if inherits:
        for e in inherits:
            session.run(
                "MATCH (child:Class {"
                "name: $child, project: $project, repo: $child_repo, path: $child_path"
                "}) "
                "WITH child "
                "OPTIONAL MATCH (parent:Class {"
                "name: $parent, project: $project, repo: $child_repo"
                "}) "
                "WITH child, parent WHERE parent IS NOT NULL "
                "MERGE (child)-[:INHERITS]->(parent)",
                child=e["from"],
                child_repo=e["from_repo"],
                child_path=e["from_path"],
                parent=e["to"],
                project=e.get("project"),
            )
    # Edges: CALLS (Method -> Method, best-effort)
    calls = [e for e in edges_batch if e["type"] == "CALLS"]
    if calls:
        for e in calls:
            session.run(
                "MATCH (caller:Method {"
                "name: $caller, signature: $caller_sig, "
                "project: $project, repo: $caller_repo, path: $caller_path"
                "}) "
                "WITH caller "
                "OPTIONAL MATCH (callee:Method {"
                "name: $callee, project: $project, repo: $caller_repo"
                "}) "
                "WITH caller, callee WHERE callee IS NOT NULL "
                "MERGE (caller)-[:CALLS]->(callee)",
                caller=e["from"],
                caller_sig=e["from_signature"],
                caller_repo=e["from_repo"],
                caller_path=e["from_path"],
                callee=e["to"],
                project=e.get("project"),
            )


# ---------------------------------------------------------------------------
# 7. Pass 2 — DocEntity LLM extraction (runs only with --extract-doc-entities)
# ---------------------------------------------------------------------------

# Javadoc / block comment regex (fallback when tree-sitter is unavailable)
_BLOCK_COMMENT_RE = _re.compile(
    r"/\*\*?.*?\*/|\'\'\'.*?\'\'\'",
    _re.DOTALL,
)

_DOC_ENTITY_PROMPT = (
    "Extract 1-3 word domain concept noun phrases from the following code comments "
    "(English or Chinese). "
    'Output strict JSON only, format: [{{"name":"concept_name","concept_text":"original comment snippet"}}]. '
    "Extract at most 5.\n\nComment content:\n{comment}"
)


def _extract_comments_from_file(file_path: str, lang: str, parser) -> list[dict]:
    """
    Extract comment blocks from a file, returning [{"text": str, "line": int}].
    Prefers tree-sitter `comment` nodes; falls back to regex on failure.
    """
    try:
        with open(file_path, "rb") as f:
            source = f.read()
    except OSError:
        return []

    comments: list[dict] = []

    # tree-sitter approach
    if parser is not None:
        try:
            tree = parser.parse(source)

            def _walk(n):
                if n.type == "comment":
                    text = (
                        source[n.start_byte : n.end_byte].decode("utf-8", errors="replace").strip()
                    )
                    if len(text) > 20:  # Filter out short single-line comments
                        comments.append({"text": text, "line": n.start_point[0] + 1})
                for child in n.children:
                    _walk(child)

            _walk(tree.root_node)
            return comments
        except Exception:
            pass

    # Regex fallback
    try:
        text_str = source.decode("utf-8", errors="replace")
        for m in _BLOCK_COMMENT_RE.finditer(text_str):
            snippet = m.group(0).strip()
            if len(snippet) > 20:
                line = text_str[: m.start()].count("\n") + 1
                comments.append({"text": snippet, "line": line})
    except Exception:
        pass
    return comments


def _call_llm_for_entities(
    comment_text: str,
    model: str,
    api_key: str,
    api_base: str,
    timeout: float = 15.0,
) -> list[dict]:
    """
    Synchronously call the LLM, returning [{"name": str, "concept_text": str}].
    Silently returns [] on failure.
    """
    import json as _json

    import httpx as _httpx

    prompt = _DOC_ENTITY_PROMPT.format(comment=comment_text[:800])
    try:
        with _httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f"{api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 256,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            # Handle ```json ... ``` wrapping
            if "```" in content:
                for part in content.split("```"):
                    part = part.strip().lstrip("json").strip()
                    if part.startswith("["):
                        content = part
                        break
            entities = _json.loads(content)
            if isinstance(entities, list):
                return [e for e in entities if isinstance(e, dict) and "name" in e]
    except Exception:
        pass
    return []


def _upsert_doc_entities(session, doc_entities: list[dict]):
    """Batch-write DocEntity nodes and their edges."""
    if not doc_entities:
        return
    # Nodes
    session.run(
        "UNWIND $ents AS e "
        "MERGE (d:DocEntity {"
        "name: e.name, source_path: e.source_path, "
        "source_repo: e.source_repo, project: e.project"
        "}) "
        "SET d.concept_text = e.concept_text, d.source_line = e.source_line",
        ents=doc_entities,
    )
    # MENTIONED_IN -> File
    session.run(
        "UNWIND $ents AS e "
        "MATCH (d:DocEntity {"
        "name: e.name, source_path: e.source_path, "
        "source_repo: e.source_repo, project: e.project"
        "}) "
        "MATCH (f:File {project: e.project, repo: e.source_repo, path: e.source_path}) "
        "MERGE (d)-[:MENTIONED_IN]->(f)",
        ents=doc_entities,
    )
    # RELATED_TO -> Class/Method (exact name match within the same file, best-effort)
    session.run(
        "UNWIND $ents AS e "
        "MATCH (d:DocEntity {"
        "name: e.name, source_path: e.source_path, "
        "source_repo: e.source_repo, project: e.project"
        "}) "
        "OPTIONAL MATCH (c:Class {"
        "name: e.name, path: e.source_path, "
        "repo: e.source_repo, project: e.project"
        "}) "
        "OPTIONAL MATCH (m:Method {"
        "name: e.name, path: e.source_path, "
        "repo: e.source_repo, project: e.project"
        "}) "
        "FOREACH (_ IN CASE WHEN c IS NOT NULL THEN [1] ELSE [] END | "
        "  MERGE (d)-[:RELATED_TO]->(c)) "
        "FOREACH (_ IN CASE WHEN m IS NOT NULL THEN [1] ELSE [] END | "
        "  MERGE (d)-[:RELATED_TO]->(m))",
        ents=doc_entities,
    )


def _run_doc_entity_pass(
    files: list[tuple[str, str]],
    parsers: dict,
    args,
    driver,
    source_root: str,
    project: str,
    repo_name: str | None,
):
    """
    Pass 2: extract DocEntity nodes from comments until --max-doc-entities cap is reached.
    Returns (llm_calls, total_entities).
    """

    api_key = os.environ.get("NL_API_KEY", "")
    api_base = os.environ.get("NL_API_BASE", "https://api.openai.com/v1")
    model = args.doc_entity_llm_model or os.environ.get("NL_MODEL", "gpt-4o-mini")

    if not api_key:
        print("Warning: NL_API_KEY not set, skipping DocEntity extraction", file=sys.stderr)
        return 0, 0

    # Sort by comment density (comment chars / file size), prioritizing high-density files
    def _comment_density(item: tuple[str, str]) -> float:
        fpath, lang = item
        parser = parsers.get(lang)
        comments = _extract_comments_from_file(fpath, lang, parser)
        try:
            fsize = max(os.path.getsize(fpath), 1)
        except OSError:
            fsize = 1
        return sum(len(c["text"]) for c in comments) / fsize

    print("[Pass2] Computing comment density ranking...", flush=True)
    ranked = sorted(files, key=_comment_density, reverse=True)

    llm_calls = 0
    total_entities = 0
    entity_buf: list[dict] = []
    cap = args.max_doc_entities

    for fpath, lang in ranked:
        if total_entities >= cap:
            break
        parser = parsers.get(lang)
        comments = _extract_comments_from_file(fpath, lang, parser)
        if not comments:
            continue

        # Send to LLM in batches of --doc-entity-batch-size
        for i in range(0, len(comments), args.doc_entity_batch_size):
            if total_entities >= cap:
                break
            batch = comments[i : i + args.doc_entity_batch_size]
            combined_text = "\n\n---\n\n".join(c["text"] for c in batch)
            try:
                repo, repo_rel_path, _repo_mode = _derive_repo_and_path(
                    file_path=fpath,
                    source_root=source_root,
                    project=project,
                    repo_name=repo_name,
                )
            except ValueError:
                continue
            entities = _call_llm_for_entities(combined_text, model, api_key, api_base)
            llm_calls += 1

            for ent in entities:
                if total_entities >= cap:
                    break
                # Associate with the line number of the nearest comment block
                source_line = batch[0]["line"] if batch else 0
                entity_buf.append(
                    {
                        "name": ent.get("name", ""),
                        "concept_text": ent.get("concept_text", ""),
                        "source_path": repo_rel_path,
                        "source_repo": repo,
                        "source_line": source_line,
                        "project": project,
                    }
                )
                total_entities += 1

            # Flush every 50 entities
            if len(entity_buf) >= 50:
                with driver.session() as session:
                    _upsert_doc_entities(session, entity_buf)
                entity_buf.clear()

    # Write remaining
    if entity_buf:
        with driver.session() as session:
            _upsert_doc_entities(session, entity_buf)

    print(
        f"[Pass2] llm_calls={llm_calls} total_entities={total_entities}",
        flush=True,
    )
    return llm_calls, total_entities


# ---------------------------------------------------------------------------
# 8. Main flow
# ---------------------------------------------------------------------------


def main():
    args = _build_parser().parse_args()

    # Lazy imports (--help does not need these)
    GraphDatabase = _import_neo4j()
    languages = [lang.strip() for lang in args.languages.split(",") if lang.strip()]
    parsers = _import_tree_sitter_parsers(languages)

    # 2. Preflight: connectivity check
    try:
        driver = GraphDatabase.driver(
            args.neo4j_uri,
            auth=(args.neo4j_user, args.neo4j_password),
        )
        with driver.session() as session:
            session.run("RETURN 1")
    except Exception as exc:
        print(f"Error: cannot connect to Neo4j ({args.neo4j_uri}): {exc}", file=sys.stderr)
        sys.exit(2)

    with driver.session() as session:
        if args.reset:
            print("WARNING: --reset: clearing all graph nodes...", file=sys.stderr)
            _reset_structural(session, project=args.project_name)
        _bootstrap_schema(session)

    # 3. Collect files
    source_root = os.path.abspath(args.source_root)
    repo = os.path.basename(source_root)
    project = args.project_name if args.project_name else repo
    files = _collect_files(source_root, languages, args.max_files)
    total = len(files)
    print(f"[0/{total}] Found {total} source files, starting parse...", flush=True)

    nodes_buf: list[dict] = []
    edges_buf: list[dict] = []
    parse_failures = 0
    total_nodes = 0
    total_edges = 0

    for i, (fpath, lang) in enumerate(files, 1):
        parser = parsers.get(lang)
        if parser is None:
            parse_failures += 1
            continue

        nodes, edges = _extract_nodes_edges(
            file_path=fpath,
            lang=lang,
            parser=parser,
            source_root=source_root,
            project=project,
            repo_name=args.repo_name,
        )
        if nodes is None:
            import logging

            logging.warning("Parse failed: %s", fpath)
            parse_failures += 1
            continue

        nodes_buf.append(nodes)
        edges_buf.extend(edges or [])

        if len(nodes_buf) >= args.batch_size:
            with driver.session() as session:
                _upsert_batch(session, nodes_buf, edges_buf)
            total_nodes += sum(1 + len(n["classes"]) + len(n["methods"]) for n in nodes_buf)
            total_edges += len(edges_buf)
            nodes_buf.clear()
            edges_buf.clear()

        if i % 500 == 0:
            print(
                f"[{i}/{total}] processed_files={i} parse_failures={parse_failures} "
                f"nodes={total_nodes} edges={total_edges}",
                flush=True,
            )

    # Write remaining
    if nodes_buf:
        with driver.session() as session:
            _upsert_batch(session, nodes_buf, edges_buf)
        total_nodes += sum(1 + len(n["classes"]) + len(n["methods"]) for n in nodes_buf)
        total_edges += len(edges_buf)

    driver.close()

    failure_rate = parse_failures / total if total else 0.0
    print(
        f"[Done] total={total} parse_failures={parse_failures} "
        f"failure_rate={failure_rate:.2%} nodes={total_nodes} edges={total_edges}",
        flush=True,
    )

    if args.strict and failure_rate > 0.2:
        print(f"Error: parse failure rate {failure_rate:.2%} exceeds 20% threshold (--strict)", file=sys.stderr)
        sys.exit(3)

    # Pass 2: DocEntity LLM extraction (runs only with --extract-doc-entities)
    if args.extract_doc_entities:
        # Reopen driver (Pass 1 already closed it)
        driver2 = GraphDatabase.driver(
            args.neo4j_uri,
            auth=(args.neo4j_user, args.neo4j_password),
        )
        _run_doc_entity_pass(
            files,
            parsers,
            args,
            driver2,
            source_root=source_root,
            project=project,
            repo_name=args.repo_name,
        )
        driver2.close()


if __name__ == "__main__":
    main()
