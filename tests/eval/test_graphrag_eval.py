"""
GraphRAG 评测套件

默认跳过 (需要 RUN_EVAL=1 或 --run-eval 参数)。
支持两种模式:
  EVAL_BACKEND_MODE=live  — 连接真实 Zoekt/Dense/Structural 后端
  EVAL_BACKEND_MODE=mock  — 跳过，无真实后端时安全运行

运行示例:
  RUN_EVAL=1 EVAL_BACKEND_MODE=live PYTHONPATH=src pytest tests/eval/test_graphrag_eval.py -v
"""
import json
import os
import pathlib
import pytest

# ─── Eval 门控 ────────────────────────────────────────────────────────────────

RUN_EVAL = os.getenv("RUN_EVAL", "0") == "1"
EVAL_BACKEND_MODE = os.getenv("EVAL_BACKEND_MODE", "mock")

pytestmark = pytest.mark.eval

EVAL_DIR = pathlib.Path(__file__).parent
EVAL_JSONL = EVAL_DIR / "graphrag_eval.jsonl"
REL_JSONL = EVAL_DIR / "graphrag_relationship_queries.jsonl"


def load_jsonl(path: pathlib.Path) -> list[dict]:
    """加载 JSONL 文件，跳过 _meta 行。"""
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if "_meta" in obj:
                continue
            rows.append(obj)
    return rows


def recall_at_k(results: list[dict], expected_paths: list[str], k: int = 10) -> float:
    """计算 Recall@K：expected_paths 中至少一条在 top-k 结果中出现则得分 1.0。"""
    top_k_paths = set()
    for r in results[:k]:
        meta = r.get("metadata", {})
        repo = meta.get("repo", "")
        path = meta.get("path", "")
        top_k_paths.add(f"{repo}/{path}")
        top_k_paths.add(r.get("title", ""))

    for ep in expected_paths:
        # 支持部分匹配：expected_path 是 top-k 任一结果的子串
        for candidate in top_k_paths:
            if ep in candidate or candidate in ep:
                return 1.0
    return 0.0


def reciprocal_rank(results: list[dict], expected_paths: list[str]) -> float:
    """计算 MRR 分量：返回首个命中位置的倒数。"""
    for rank, r in enumerate(results, start=1):
        meta = r.get("metadata", {})
        repo = meta.get("repo", "")
        path = meta.get("path", "")
        candidate = f"{repo}/{path}"
        title = r.get("title", "")
        for ep in expected_paths:
            if ep in candidate or candidate in ep or ep in title or title in ep:
                return 1.0 / rank
    return 0.0


def _print_table(config_name: str, recall: float, mrr: float, n: int):
    """打印评测结果表格行。"""
    print(f"\n{'─'*60}")
    print(f"  配置: {config_name} | N={n}")
    print(f"  Recall@10 = {recall:.3f}  |  MRR = {mrr:.3f}")
    print(f"{'─'*60}")


# ─── 主评测测试 ───────────────────────────────────────────────────────────────

@pytest.mark.skipif(not RUN_EVAL, reason="设置 RUN_EVAL=1 运行评测 (需要真实后端)")
@pytest.mark.asyncio
async def test_eval_three_configs():
    """对三种配置运行所有评测查询，打印 Recall@10 和 MRR 对比表。"""
    if EVAL_BACKEND_MODE != "live":
        pytest.skip("EVAL_BACKEND_MODE=mock，跳过真实后端评测")

    import config
    from gateway.gateway import search

    queries = load_jsonl(EVAL_JSONL)
    assert len(queries) >= 20, f"评测集应有 >=20 条，实际: {len(queries)}"

    configs = [
        ("Zoekt only",          {"DENSE_ENABLED": False, "STRUCTURAL_ENABLED": False}),
        ("Zoekt + Dense",       {"DENSE_ENABLED": True,  "STRUCTURAL_ENABLED": False}),
        ("Zoekt + Dense + Structural", {"DENSE_ENABLED": True, "STRUCTURAL_ENABLED": True}),
    ]

    for cfg_name, env_overrides in configs:
        # 临时覆盖 config 属性
        original = {k: getattr(config, k) for k in env_overrides}
        for k, v in env_overrides.items():
            setattr(config, k, v)

        recalls, rrs = [], []
        try:
            for row in queries:
                try:
                    results = await search(row["query"], top_k=10)
                    recalls.append(recall_at_k(results, row["expected_paths"]))
                    rrs.append(reciprocal_rank(results, row["expected_paths"]))
                except Exception as e:
                    recalls.append(0.0)
                    rrs.append(0.0)
        finally:
            for k, v in original.items():
                setattr(config, k, v)

        avg_recall = sum(recalls) / len(recalls) if recalls else 0.0
        avg_mrr = sum(rrs) / len(rrs) if rrs else 0.0
        _print_table(cfg_name, avg_recall, avg_mrr, len(queries))


# ─── 关系查询测试 ─────────────────────────────────────────────────────────────

@pytest.mark.skipif(not RUN_EVAL, reason="设置 RUN_EVAL=1 运行评测 (需要真实后端)")
@pytest.mark.asyncio
async def test_relationship_queries():
    """关系查询：>=8 条中 top-1 命中 expected_paths[0]（live 模式）。"""
    if EVAL_BACKEND_MODE != "live":
        pytest.skip("EVAL_BACKEND_MODE=mock，跳过真实后端评测")

    from gateway.gateway import search

    rel_queries = load_jsonl(REL_JSONL)
    assert len(rel_queries) >= 8

    hits = 0
    for row in rel_queries:
        results = await search(row["query"], top_k=10)
        if recall_at_k(results, row["expected_paths"][:1]) == 1.0:
            hits += 1

    print(f"\n关系查询命中: {hits}/{len(rel_queries)}")
    assert hits >= len(rel_queries) * 0.5, (
        f"关系查询命中率过低: {hits}/{len(rel_queries)}"
    )


# ─── 集合健全性测试（不依赖后端，始终运行） ──────────────────────────────────

def test_eval_jsonl_structure():
    """验证 graphrag_eval.jsonl 格式正确，条目数 >=20，包含必要字段。"""
    queries = load_jsonl(EVAL_JSONL)
    assert len(queries) >= 20, f"评测集应有 >=20 条，实际: {len(queries)}"
    required_fields = {"id", "query", "expected_paths", "category"}
    for row in queries:
        missing = required_fields - set(row.keys())
        assert not missing, f"条目 {row.get('id')} 缺少字段: {missing}"
        assert isinstance(row["expected_paths"], list) and len(row["expected_paths"]) >= 1
        assert row["category"] in {"symbol", "concept", "relationship"}


def test_relationship_jsonl_structure():
    """验证 graphrag_relationship_queries.jsonl 格式正确，条目数 >=8。"""
    queries = load_jsonl(REL_JSONL)
    assert len(queries) >= 8, f"关系查询集应有 >=8 条，实际: {len(queries)}"
    for row in queries:
        assert "query" in row
        assert "expected_paths" in row
        assert row.get("category") == "relationship"


def test_package_diversity():
    """验证评测集涵盖 >=5 个不同包路径（cut -d/ -f1-4，与验收命令一致）。"""
    queries = load_jsonl(EVAL_JSONL)
    packages = set()
    for row in queries:
        for ep in row["expected_paths"]:
            parts = ep.split("/")
            # 取前4段（等价于 cut -d/ -f1-4）
            pkg = "/".join(parts[:4]) if len(parts) >= 4 else ep
            packages.add(pkg)
    assert len(packages) >= 5, f"包多样性不足：{len(packages)} 个 (需要 >=5): {packages}"


# ─── 基线延迟采集 ────────────────────────────────────────────────────────────

@pytest.mark.skipif(not RUN_EVAL, reason="设置 RUN_EVAL=1 运行基线延迟采集")
def test_capture_baseline_latencies():
    """
    采集基线延迟：从 audit.log 读取 zoekt_search 和 dense_search 的 P95。

    输出写入 tests/eval/baseline_latencies.json。
    见 tests/eval/README.md 了解用途。
    """
    import json as _json
    import pathlib as _pathlib

    AUDIT_LOG = _pathlib.Path("/mnt/code/T2/Dify/audit.log")
    if not AUDIT_LOG.exists():
        pytest.skip("audit.log 不存在，跳过基线采集")

    latencies: dict[str, list[float]] = {"zoekt_search": [], "dense_search": [], "structural_search": []}
    with open(AUDIT_LOG) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = _json.loads(line)
                stage = obj.get("stage", "")
                duration_ms = obj.get("duration_ms")
                if stage in latencies and isinstance(duration_ms, (int, float)):
                    latencies[stage].append(float(duration_ms))
            except Exception:
                continue

    result = {}
    for stage, vals in latencies.items():
        if vals:
            vals_sorted = sorted(vals)
            p95_idx = int(len(vals_sorted) * 0.95)
            result[stage] = {
                "count": len(vals_sorted),
                "p50_ms": vals_sorted[len(vals_sorted) // 2],
                "p95_ms": vals_sorted[min(p95_idx, len(vals_sorted) - 1)],
                "max_ms": vals_sorted[-1],
            }
        else:
            result[stage] = {"count": 0}

    out_path = EVAL_DIR / "baseline_latencies.json"
    out_path.write_text(_json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\n基线延迟已写入: {out_path}")
    print(_json.dumps(result, indent=2, ensure_ascii=False))
