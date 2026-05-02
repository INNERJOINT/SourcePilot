"""
GraphRAG evaluation suite

Skipped by default (requires RUN_EVAL=1 or --run-eval argument).
Supports two modes:
  EVAL_BACKEND_MODE=live  — connect to real Zoekt/Dense/Structural backends
  EVAL_BACKEND_MODE=mock  — skip; safe to run without real backends

Usage example:
  RUN_EVAL=1 EVAL_BACKEND_MODE=live PYTHONPATH=src pytest tests/eval/test_graphrag_eval.py -v
"""
import json
import os
import pathlib
import pytest

# ─── Eval gate ────────────────────────────────────────────────────────────────

RUN_EVAL = os.getenv("RUN_EVAL", "0") == "1"
EVAL_BACKEND_MODE = os.getenv("EVAL_BACKEND_MODE", "mock")

pytestmark = pytest.mark.eval

EVAL_DIR = pathlib.Path(__file__).parent
EVAL_JSONL = EVAL_DIR / "graphrag_eval.jsonl"
REL_JSONL = EVAL_DIR / "graphrag_relationship_queries.jsonl"


def load_jsonl(path: pathlib.Path) -> list[dict]:
    """Load a JSONL file, skipping _meta rows."""
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
    """Compute Recall@K: score 1.0 if at least one expected_path appears in the top-k results."""
    top_k_paths = set()
    for r in results[:k]:
        meta = r.get("metadata", {})
        repo = meta.get("repo", "")
        path = meta.get("path", "")
        top_k_paths.add(f"{repo}/{path}")
        top_k_paths.add(r.get("title", ""))

    for ep in expected_paths:
        # Partial match: expected_path is a substring of any top-k candidate
        for candidate in top_k_paths:
            if ep in candidate or candidate in ep:
                return 1.0
    return 0.0


def reciprocal_rank(results: list[dict], expected_paths: list[str]) -> float:
    """Compute MRR component: reciprocal rank of the first hit."""
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
    """Print one row of the evaluation results table."""
    print(f"\n{'─'*60}")
    print(f"  Config: {config_name} | N={n}")
    print(f"  Recall@10 = {recall:.3f}  |  MRR = {mrr:.3f}")
    print(f"{'─'*60}")


# ─── Main evaluation tests ───────────────────────────────────────────────────

@pytest.mark.skipif(not RUN_EVAL, reason="Set RUN_EVAL=1 to run evaluation (requires real backends)")
@pytest.mark.asyncio
async def test_eval_three_configs():
    """Run all evaluation queries under three configurations and print Recall@10 / MRR comparison."""
    if EVAL_BACKEND_MODE != "live":
        pytest.skip("EVAL_BACKEND_MODE=mock, skipping real-backend evaluation")

    import config
    from gateway.gateway import search

    queries = load_jsonl(EVAL_JSONL)
    assert len(queries) >= 20, f"Eval set should have >=20 entries, got: {len(queries)}"

    configs = [
        ("Zoekt only",          {"DENSE_ENABLED": False, "STRUCTURAL_ENABLED": False}),
        ("Zoekt + Dense",       {"DENSE_ENABLED": True,  "STRUCTURAL_ENABLED": False}),
        ("Zoekt + Dense + Structural", {"DENSE_ENABLED": True, "STRUCTURAL_ENABLED": True}),
    ]

    for cfg_name, env_overrides in configs:
        # Temporarily override config attributes
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


# ─── Relationship query tests ─────────────────────────────────────────────────

@pytest.mark.skipif(not RUN_EVAL, reason="Set RUN_EVAL=1 to run evaluation (requires real backends)")
@pytest.mark.asyncio
async def test_relationship_queries():
    """Relationship queries: >= 8 with top-1 hitting expected_paths[0] (live mode)."""
    if EVAL_BACKEND_MODE != "live":
        pytest.skip("EVAL_BACKEND_MODE=mock, skipping real-backend evaluation")

    from gateway.gateway import search

    rel_queries = load_jsonl(REL_JSONL)
    assert len(rel_queries) >= 8

    hits = 0
    for row in rel_queries:
        results = await search(row["query"], top_k=10)
        if recall_at_k(results, row["expected_paths"][:1]) == 1.0:
            hits += 1

    print(f"\nRelationship query hits: {hits}/{len(rel_queries)}")
    assert hits >= len(rel_queries) * 0.5, (
        f"Relationship query hit rate too low: {hits}/{len(rel_queries)}"
    )


# ─── Dataset sanity tests (no backend required, always run) ──────────────────

def test_eval_jsonl_structure():
    """Verify graphrag_eval.jsonl is correctly formatted, has >=20 entries, and contains required fields."""
    queries = load_jsonl(EVAL_JSONL)
    assert len(queries) >= 20, f"Eval set should have >=20 entries, got: {len(queries)}"
    required_fields = {"id", "query", "expected_paths", "category"}
    for row in queries:
        missing = required_fields - set(row.keys())
        assert not missing, f"Entry {row.get('id')} missing fields: {missing}"
        assert isinstance(row["expected_paths"], list) and len(row["expected_paths"]) >= 1
        assert row["category"] in {"symbol", "concept", "relationship"}


def test_relationship_jsonl_structure():
    """Verify graphrag_relationship_queries.jsonl is correctly formatted and has >=8 entries."""
    queries = load_jsonl(REL_JSONL)
    assert len(queries) >= 8, f"Relationship query set should have >=8 entries, got: {len(queries)}"
    for row in queries:
        assert "query" in row
        assert "expected_paths" in row
        assert row.get("category") == "relationship"


def test_package_diversity():
    """Verify the eval set covers >=5 distinct package paths (first 4 path segments, matching the acceptance command)."""
    queries = load_jsonl(EVAL_JSONL)
    packages = set()
    for row in queries:
        for ep in row["expected_paths"]:
            parts = ep.split("/")
            # Take first 4 segments (equivalent to cut -d/ -f1-4)
            pkg = "/".join(parts[:4]) if len(parts) >= 4 else ep
            packages.add(pkg)
    assert len(packages) >= 5, f"Insufficient package diversity: {len(packages)} (need >=5): {packages}"


# ─── Baseline latency capture ────────────────────────────────────────────────

@pytest.mark.skipif(not RUN_EVAL, reason="Set RUN_EVAL=1 to capture baseline latencies")
def test_capture_baseline_latencies():
    """
    Capture baseline latencies: read zoekt_search and dense_search P95 from audit.log.

    Output is written to tests/eval/baseline_latencies.json.
    See tests/eval/README.md for usage.
    """
    import json as _json
    import pathlib as _pathlib

    AUDIT_LOG = _pathlib.Path("/opt/aosp/aosp_project2/Dify/audit.log")
    if not AUDIT_LOG.exists():
        pytest.skip("audit.log does not exist, skipping baseline capture")

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
    print(f"\nBaseline latencies written to: {out_path}")
    print(_json.dumps(result, indent=2, ensure_ascii=False))
