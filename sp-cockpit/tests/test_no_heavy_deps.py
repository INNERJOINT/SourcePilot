"""Verify sp-cockpit does NOT declare heavy indexer SDK deps.

pymilvus and neo4j-driver must live only inside indexer containers,
never in sp-cockpit's own dependency list (R5 from plan).

Note: the shared dev venv may have these installed for other projects,
so we check the declared dependencies in pyproject.toml, not pip list.
"""
from pathlib import Path

import tomllib


def _get_all_declared_deps() -> set[str]:
    """Read all declared deps (core + optional) from sp-cockpit's pyproject.toml."""
    toml_path = Path(__file__).parent.parent / "pyproject.toml"
    data = tomllib.loads(toml_path.read_text())
    deps: list[str] = list(data.get("project", {}).get("dependencies", []))
    for extras in data.get("project", {}).get("optional-dependencies", {}).values():
        deps.extend(extras)
    # Normalize: take package name before any version specifier
    return {d.split("[")[0].split(">")[0].split("<")[0].split("=")[0].split("!")[0].strip().lower()
            for d in deps}


def test_pymilvus_not_declared():
    deps = _get_all_declared_deps()
    assert "pymilvus" not in deps, (
        "pymilvus declared in sp-cockpit pyproject.toml — it must stay inside the dense-indexer container"
    )


def test_neo4j_not_declared():
    deps = _get_all_declared_deps()
    assert "neo4j" not in deps, (
        "neo4j driver declared in sp-cockpit pyproject.toml — it must stay inside the structural-indexer container"
    )
