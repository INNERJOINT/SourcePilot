"""
build_structural_index.py — SourcePilot 结构化索引构建脚本

用途:
    遍历 AOSP 源码目录，通过 tree-sitter 提取 Java/C++/Python 的
    文件、类、方法节点及其边关系，批量写入 Neo4j 图数据库。

用法:
    python scripts/build_structural_index.py \\
        --source-root /mnt/code/ACE/.repo/frameworks/base \\
        --languages java,cpp,python \\
        --batch-size 100

    # 重建（先清空所有节点）
    python scripts/build_structural_index.py --source-root /path/to/src --reset

    # 仅处理前 500 个文件（测试用）
    python scripts/build_structural_index.py --source-root /path/to/src --max-files 500

环境变量（可被命令行参数覆盖）:
    STRUCTURAL_NEO4J_URI      默认 bolt://localhost:7687
    STRUCTURAL_NEO4J_USER     默认 neo4j
    STRUCTURAL_NEO4J_PASSWORD 默认 sourcepilot
"""

import argparse
import os
import re as _re
import sys

# ---------------------------------------------------------------------------
# 1. Argparse — 必须在 import 重量级依赖之前，保证 --help 不因缺包而失败
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="构建 AOSP 源码 → Neo4j 结构化索引",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--source-root",
        required=True,
        help="源码根目录，例如 /mnt/code/ACE/.repo/frameworks/base",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="每批 Cypher UNWIND 写入的节点/边数量（默认 100）",
    )
    p.add_argument(
        "--languages",
        default="java,cpp,python",
        help="要解析的语言列表，逗号分隔（默认 java,cpp,python）",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="解析失败率 > 0.2 时以 exit(3) 中止",
    )
    p.add_argument(
        "--neo4j-uri",
        default=os.environ.get("STRUCTURAL_NEO4J_URI", "bolt://localhost:7687"),
        help="Neo4j Bolt URI（默认 bolt://localhost:7687）",
    )
    p.add_argument(
        "--neo4j-user",
        default=os.environ.get("STRUCTURAL_NEO4J_USER", "neo4j"),
        help="Neo4j 用户名（默认 neo4j）",
    )
    p.add_argument(
        "--neo4j-password",
        default=os.environ.get("STRUCTURAL_NEO4J_PASSWORD", "sourcepilot"),
        help="Neo4j 密码（默认 sourcepilot）",
    )
    p.add_argument(
        "--reset",
        action="store_true",
        help="构建前清空所有节点与索引",
    )
    p.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="最多处理 N 个文件（测试用保护措施）",
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
    # DocEntity LLM 提取（Pass 2）
    p.add_argument(
        "--extract-doc-entities",
        action="store_true",
        default=False,
        help="启用 Pass 2：通过 LLM 从注释中提取领域概念节点（DocEntity）",
    )
    p.add_argument(
        "--max-doc-entities",
        type=int,
        default=500,
        help="DocEntity 提取上限，超过后立即停止（默认 500）",
    )
    p.add_argument(
        "--doc-entity-llm-model",
        default=os.environ.get("NL_MODEL", ""),
        help="DocEntity 提取使用的 LLM 模型（默认 $NL_MODEL）",
    )
    p.add_argument(
        "--doc-entity-batch-size",
        type=int,
        default=10,
        help="每次并发发送给 LLM 的注释块数量（默认 10）",
    )
    return p


# ---------------------------------------------------------------------------
# 2. 延迟导入重量级依赖（tree-sitter / neo4j 驱动）
# ---------------------------------------------------------------------------


def _import_neo4j():
    try:
        from neo4j import GraphDatabase  # noqa: F401

        return GraphDatabase
    except ImportError:
        print(
            "错误: 缺少 neo4j 包，请运行: pip install neo4j",
            file=sys.stderr,
        )
        sys.exit(4)


def _import_tree_sitter_parsers(languages: list[str]):
    """
    返回 {lang: Parser} 字典。
    若 tree_sitter 或对应 grammar 包未安装，打印提示并 exit(4)。
    """
    try:
        import tree_sitter  # noqa: F401
    except ImportError:
        print(
            "错误: 缺少 tree-sitter 包，请运行: pip install tree-sitter "
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
            print(f"警告: 不支持的语言 '{lang}'，跳过", file=sys.stderr)
            continue
        try:
            mod = __import__(pkg)
            language = Language(mod.language())
            parser = Parser(language)
            parsers[lang] = parser
        except (ImportError, Exception) as exc:
            print(f"警告: 无法加载 {lang} 语法包 ({exc})，跳过", file=sys.stderr)
    return parsers


# ---------------------------------------------------------------------------
# 3. 文件扩展名 → 语言映射
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
    """返回 [(文件绝对路径, 语言)] 列表"""
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
# 4. tree-sitter 解析：提取节点与边
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
    计算结构化索引身份中的 repo/path。

    返回 (repo, repo_relative_path, repo_mode):
      - repo_mode=explicit: 来自 --repo-name
      - repo_mode=derived: 从默认约定推导（frameworks/* 或 packages/*/*）
      - repo_mode=project_root: 无法推导时使用 synthetic repo（project）
    """
    abs_root = os.path.abspath(source_root)
    abs_file = os.path.abspath(file_path)
    rel = _normalize_rel_path(os.path.relpath(abs_file, abs_root))

    if rel == "." or rel.startswith("../"):
        raise ValueError(f"文件不在 source_root 下: file={file_path}, source_root={source_root}")

    if repo_name:
        return repo_name, rel, "explicit"

    # 默认 whole-project 模式：优先按 frameworks/* 与 packages/*/* 推导 repo 边界
    parts = rel.split("/")
    if len(parts) >= 3 and parts[0] == "frameworks":
        repo = f"frameworks/{parts[1]}"
        return repo, "/".join(parts[2:]), "derived"
    if len(parts) >= 4 and parts[0] == "packages":
        repo = f"packages/{parts[1]}/{parts[2]}"
        return repo, "/".join(parts[3:]), "derived"

    # 若 source_root 本身就是 frameworks/<repo> 或 packages/<org>/<repo>，也做兼容推导
    root_parts = _normalize_rel_path(abs_root).strip("/").split("/")
    if len(root_parts) >= 2 and root_parts[-2] == "frameworks":
        return f"frameworks/{root_parts[-1]}", rel, "derived"
    if len(root_parts) >= 3 and root_parts[-3] == "packages":
        return f"packages/{root_parts[-2]}/{root_parts[-1]}", rel, "derived"

    # synthetic project-root 模式（用于无法按约定切 repo 的文件）
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
    返回:
        nodes: {"file": {...}, "classes": [...], "methods": [...]}
        edges: [{"type": "DEFINED_IN"|"MEMBER_OF"|"INHERITS"|"CALLS", ...}]
    解析失败时返回 (None, None)。
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

    # --- 通用 AST 遍历 ---
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
                # 继承关系（Java: superclass / C++: base_class_clause）
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
                # 递归处理类体
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
                # 提取签名（函数名 + 参数）
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
                # CALLS 边：扫描方法体中的调用表达式（best-effort）
                body = n.child_by_field_name("body")
                if body:
                    _extract_calls(body, mname, sig, source, edges)

        for child in n.children:
            walk(child, current_class=current_class)

    def _extract_calls(body_node, caller: str, caller_sig: str, src: bytes, out_edges: list):
        """递归提取 call_expression 中被调用的方法名"""
        for child in body_node.children:
            if child.type in ("call_expression", "method_invocation"):
                fn_node = child.child_by_field_name("function") or child.child_by_field_name("name")
                if fn_node:
                    callee_text = src[fn_node.start_byte : fn_node.end_byte].decode(
                        "utf-8", errors="replace"
                    )
                    # 取最后一段（去掉 obj. 前缀）
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
# 5. Neo4j 操作
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
    迁移前检查并确保 File 唯一性从 path 升级到 (project, repo, path)。

    流程：
      1) 检查现有 File 节点是否具备 project/repo/path（非空）
      2) 检查 (project, repo, path) 是否存在重复
      3) 创建 composite 唯一约束
      4) 删除旧 File.path 单字段唯一约束（若存在）

    若检查失败，抛出 RuntimeError 并附带 remediation 提示。
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
            "File 节点缺少 project/repo/path，无法安全迁移到复合唯一约束。"
            "请先执行 --reset 重建，或先补齐历史数据再重试。"
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
            "检测到 File 复合键重复，无法安全创建 (project,repo,path) 唯一约束。"
            f"样例: {sample}. "
            "请先执行 --reset 重建，或手动清理重复数据后重试。"
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
    # 仅在不存在时创建全文索引（SHOW INDEXES 检查）
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
    """批量写入文件/类/方法节点及边"""
    # File 节点
    files = [n["file"] for n in nodes_batch]
    session.run(
        "UNWIND $files AS f "
        "MERGE (node:File {project: f.project, repo: f.repo, path: f.path}) "
        "SET node.language = f.language, node.structural_repo_mode = f.structural_repo_mode",
        files=files,
    )
    # Class 节点
    classes = [c for n in nodes_batch for c in n["classes"]]
    if classes:
        session.run(
            "UNWIND $cls AS c "
            "MERGE (node:Class {name: c.name, path: c.path, repo: c.repo, project: c.project}) "
            "SET node.start_line = c.start_line, node.end_line = c.end_line",
            cls=classes,
        )
    # Method 节点
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

    # 边：DEFINED_IN (Class/Method → File)
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
    # 边：MEMBER_OF (Method → Class)
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
    # 边：INHERITS (Class → Class)
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
    # 边：CALLS (Method → Method, best-effort)
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
# 7. Pass 2 — DocEntity LLM 提取（仅在 --extract-doc-entities 时运行）
# ---------------------------------------------------------------------------

# Javadoc / block comment 正则（用于无 tree-sitter 时的回退）
_BLOCK_COMMENT_RE = _re.compile(
    r"/\*\*?.*?\*/|\'\'\'.*?\'\'\'",
    _re.DOTALL,
)

_DOC_ENTITY_PROMPT = (
    "请从以下代码注释中提取 1-3 词的领域概念名词短语（英文或中文均可）。"
    '只输出严格 JSON，格式：[{{"name":"概念名","concept_text":"注释原文片段"}}]。'
    "最多提取 5 个。\n\n注释内容：\n{comment}"
)


def _extract_comments_from_file(file_path: str, lang: str, parser) -> list[dict]:
    """
    提取文件中的注释块，返回 [{"text": str, "line": int}]。
    优先用 tree-sitter `comment` 节点；失败则用正则回退。
    """
    try:
        with open(file_path, "rb") as f:
            source = f.read()
    except OSError:
        return []

    comments: list[dict] = []

    # tree-sitter 方式
    if parser is not None:
        try:
            tree = parser.parse(source)

            def _walk(n):
                if n.type == "comment":
                    text = (
                        source[n.start_byte : n.end_byte].decode("utf-8", errors="replace").strip()
                    )
                    if len(text) > 20:  # 过滤单行短注释
                        comments.append({"text": text, "line": n.start_point[0] + 1})
                for child in n.children:
                    _walk(child)

            _walk(tree.root_node)
            return comments
        except Exception:
            pass

    # 正则回退
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
    同步调用 LLM，返回 [{"name": str, "concept_text": str}]。
    失败时静默返回 []。
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
            # 兼容 ```json ... ``` 包裹
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
    """批量写入 DocEntity 节点及其边"""
    if not doc_entities:
        return
    # 节点
    session.run(
        "UNWIND $ents AS e "
        "MERGE (d:DocEntity {"
        "name: e.name, source_path: e.source_path, "
        "source_repo: e.source_repo, project: e.project"
        "}) "
        "SET d.concept_text = e.concept_text, d.source_line = e.source_line",
        ents=doc_entities,
    )
    # MENTIONED_IN → File
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
    # RELATED_TO → Class/Method（name 完全匹配同文件内符号，best-effort）
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
    Pass 2: 从注释中提取 DocEntity 节点，直到达到 --max-doc-entities 上限。
    返回 (llm_calls, total_entities)。
    """

    api_key = os.environ.get("NL_API_KEY", "")
    api_base = os.environ.get("NL_API_BASE", "https://api.openai.com/v1")
    model = args.doc_entity_llm_model or os.environ.get("NL_MODEL", "gpt-4o-mini")

    if not api_key:
        print("警告: NL_API_KEY 未设置，跳过 DocEntity 提取", file=sys.stderr)
        return 0, 0

    # 按注释密度（注释字符数/文件大小）排序，优先高密度文件
    def _comment_density(item: tuple[str, str]) -> float:
        fpath, lang = item
        parser = parsers.get(lang)
        comments = _extract_comments_from_file(fpath, lang, parser)
        try:
            fsize = max(os.path.getsize(fpath), 1)
        except OSError:
            fsize = 1
        return sum(len(c["text"]) for c in comments) / fsize

    print("[Pass2] 计算注释密度排序中...", flush=True)
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

        # 按 --doc-entity-batch-size 分批发给 LLM
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
                # 关联到最近注释块的行号
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

            # 每 50 个实体写一次
            if len(entity_buf) >= 50:
                with driver.session() as session:
                    _upsert_doc_entities(session, entity_buf)
                entity_buf.clear()

    # 写入剩余
    if entity_buf:
        with driver.session() as session:
            _upsert_doc_entities(session, entity_buf)

    print(
        f"[Pass2] llm_calls={llm_calls} total_entities={total_entities}",
        flush=True,
    )
    return llm_calls, total_entities


# ---------------------------------------------------------------------------
# 8. 主流程
# ---------------------------------------------------------------------------


def main():
    args = _build_parser().parse_args()

    # 延迟导入（--help 不需要这些）
    GraphDatabase = _import_neo4j()
    languages = [lang.strip() for lang in args.languages.split(",") if lang.strip()]
    parsers = _import_tree_sitter_parsers(languages)

    # 2. Preflight: 连通性检查
    try:
        driver = GraphDatabase.driver(
            args.neo4j_uri,
            auth=(args.neo4j_user, args.neo4j_password),
        )
        with driver.session() as session:
            session.run("RETURN 1")
    except Exception as exc:
        print(f"错误: 无法连接 Neo4j ({args.neo4j_uri}): {exc}", file=sys.stderr)
        sys.exit(2)

    with driver.session() as session:
        if args.reset:
            print("⚠️  --reset: 清空所有图节点...", file=sys.stderr)
            _reset_structural(session, project=args.project_name)
        _bootstrap_schema(session)

    # 3. 收集文件
    source_root = os.path.abspath(args.source_root)
    repo = os.path.basename(source_root)
    project = args.project_name if args.project_name else repo
    files = _collect_files(source_root, languages, args.max_files)
    total = len(files)
    print(f"[0/{total}] 共发现 {total} 个源文件，开始解析...", flush=True)

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

            logging.warning("解析失败: %s", fpath)
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

    # 写入剩余
    if nodes_buf:
        with driver.session() as session:
            _upsert_batch(session, nodes_buf, edges_buf)
        total_nodes += sum(1 + len(n["classes"]) + len(n["methods"]) for n in nodes_buf)
        total_edges += len(edges_buf)

    driver.close()

    failure_rate = parse_failures / total if total else 0.0
    print(
        f"[完成] total={total} parse_failures={parse_failures} "
        f"failure_rate={failure_rate:.2%} nodes={total_nodes} edges={total_edges}",
        flush=True,
    )

    if args.strict and failure_rate > 0.2:
        print(f"错误: 解析失败率 {failure_rate:.2%} 超过 20% 阈值（--strict）", file=sys.stderr)
        sys.exit(3)

    # Pass 2: DocEntity LLM 提取（仅在 --extract-doc-entities 时运行）
    if args.extract_doc_entities:
        # 重新打开 driver（Pass 1 已关闭）
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
