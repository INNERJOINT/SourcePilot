"""Verify audit-viewer venv does NOT pull in heavy indexer SDK deps.

pymilvus and neo4j-driver must live only inside indexer containers,
never in the audit-viewer Python environment (R5 from plan).
"""
import subprocess
import sys


def test_pymilvus_not_installed():
    out = subprocess.check_output(
        [sys.executable, "-m", "pip", "list", "--format=columns"],
        text=True,
    )
    pkg_names = {line.split()[0].lower() for line in out.splitlines() if line.split()}
    assert "pymilvus" not in pkg_names, (
        "pymilvus found in audit-viewer venv — it must stay inside the dense-indexer container"
    )


def test_neo4j_not_installed():
    out = subprocess.check_output(
        [sys.executable, "-m", "pip", "list", "--format=columns"],
        text=True,
    )
    pkg_names = {line.split()[0].lower() for line in out.splitlines() if line.split()}
    # neo4j driver publishes as "neo4j" on PyPI
    assert "neo4j" not in pkg_names, (
        "neo4j driver found in audit-viewer venv — it must stay inside the graph-indexer container"
    )
