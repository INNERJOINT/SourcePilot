#!/usr/bin/env python3
"""
_project_config.py — Zoekt-only legacy helper for reading config/projects.yaml.

Usage:
    python3 scripts/indexing/_project_config.py --list
    python3 scripts/indexing/_project_config.py --all
    python3 scripts/indexing/_project_config.py --project <name>

Output format (one block per project, blank-line separated):
    NAME=<name>
    REPO_PATH=<repo_path>
    INDEX_DIR=<index_dir>
    ZOEKT_URL=<zoekt_url>

--list outputs one project name per line.

Dense and structural scope resolution use scripts/indexing/project_config.py instead.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


_CONFIG_PATH_ENV = "PROJECTS_CONFIG_PATH"
_DEFAULT_CONFIG_REL = "config/projects.yaml"


def _find_config_path() -> Path:
    """Resolve the projects config file, searching upward from this script."""
    env_path = os.getenv(_CONFIG_PATH_ENV)
    if env_path:
        return Path(env_path)
    here = Path(__file__).resolve()
    # Try project root (two levels up: scripts/indexing/ -> project root)
    for candidate_root in [here.parent.parent.parent, Path.cwd()]:
        candidate = candidate_root / _DEFAULT_CONFIG_REL
        if candidate.exists():
            return candidate
    return Path.cwd() / _DEFAULT_CONFIG_REL


def _shell_quote(value: str) -> str:
    """Wrap value in single quotes, escaping any embedded single quotes."""
    return "'" + value.replace("'", "'\\''") + "'"


def _load_projects(config_path: Path) -> list[dict]:
    if not config_path.exists():
        print(f"ERROR: config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    try:
        import yaml
    except ImportError:
        print("ERROR: PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        data = yaml.safe_load(f)

    if not data or "projects" not in data:
        print(f"ERROR: 'projects' key missing in {config_path}", file=sys.stderr)
        sys.exit(1)

    projects = data["projects"]
    if not isinstance(projects, list) or len(projects) == 0:
        print(f"ERROR: 'projects' must be a non-empty list in {config_path}", file=sys.stderr)
        sys.exit(1)

    return projects


def _print_project(entry: dict) -> None:
    """Print shell-eval-safe lines for one project entry."""
    name = entry.get("name", "")
    repo_path = entry.get("repo_path", "")
    index_dir = entry.get("index_dir", "")
    zoekt_url = entry.get("zoekt_url", "")

    # sparse_index overrides top-level fields
    sparse_index = entry.get("sparse_index")
    if isinstance(sparse_index, dict):
        if sparse_index.get("index_dir"):
            index_dir = sparse_index["index_dir"]
        if sparse_index.get("zoekt_url"):
            zoekt_url = sparse_index["zoekt_url"]

    print(f"NAME={_shell_quote(name)}")
    print(f"REPO_PATH={_shell_quote(repo_path)}")
    print(f"INDEX_DIR={_shell_quote(index_dir)}")
    print(f"ZOEKT_URL={_shell_quote(zoekt_url)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Output project config as shell-eval-safe lines.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--project", metavar="NAME", help="Output info for a single project")
    group.add_argument("--all", action="store_true", help="Output info for all projects")
    group.add_argument("--list", action="store_true", help="List project names (one per line)")
    args = parser.parse_args()

    config_path = _find_config_path()
    projects = _load_projects(config_path)

    if args.list:
        for entry in projects:
            print(entry.get("name", ""))
        return

    if args.all:
        for i, entry in enumerate(projects):
            if i > 0:
                print()
            _print_project(entry)
        return

    # --project <name>
    matches = [e for e in projects if e.get("name") == args.project]
    if not matches:
        available = [e.get("name", "") for e in projects]
        print(f"ERROR: unknown project '{args.project}'. Available: {available}", file=sys.stderr)
        sys.exit(1)
    _print_project(matches[0])


if __name__ == "__main__":
    main()
