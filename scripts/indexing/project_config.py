"""
project_config.py — Load multi-AOSP project configuration.

Priority:
  1. Explicit config_path argument
  2. $PROJ_ROOT/config/projects.yaml  (PROJ_ROOT = two dirs up from this file)
  3. Fallback: single project from AOSP_SOURCE_ROOT env var
"""

import os
import re
from pathlib import Path

import yaml

_PROJ_ROOT = Path(__file__).resolve().parent.parent.parent
_NAME_RE = re.compile(r"^[a-z0-9_]+$")


def _validate(project: dict) -> None:
    name = project.get("name", "")
    if not _NAME_RE.match(name):
        raise ValueError(
            f"Invalid project name {name!r}: must match [a-z0-9_]+ "
            "(Milvus collection name constraint)"
        )
    source_root = project.get("source_root", "")
    if not os.path.isabs(source_root):
        raise ValueError(
            f"Project {name!r}: source_root {source_root!r} must be an absolute path"
        )


def _normalize(raw: dict) -> dict:
    name = raw["name"]
    return {
        "name": name,
        "source_root": raw["source_root"],
        "collection_name": raw.get("collection_name", f"aosp_code_{name}"),
        "sub_project_globs": raw.get("sub_project_globs", []),
    }


def _from_yaml(path: Path) -> list[dict]:
    with open(path) as fh:
        data = yaml.safe_load(fh)
    projects = data.get("projects", [])
    result = []
    for raw in projects:
        proj = _normalize(raw)
        _validate(proj)
        result.append(proj)
    return result


def _fallback() -> list[dict]:
    source_root = os.environ.get("AOSP_SOURCE_ROOT", "/mnt/code/ACE")
    name = Path(source_root).name.lower()
    # sanitize: replace non-alphanumeric with underscore
    name = re.sub(r"[^a-z0-9]", "_", name)
    proj = _normalize({"name": name, "source_root": source_root})
    _validate(proj)
    return [proj]


def load_projects(config_path: str | None = None) -> list[dict]:
    """Return list of project dicts, each with name/source_root/collection_name/sub_project_globs."""
    if config_path is not None:
        p = Path(config_path)
        if p.exists():
            return _from_yaml(p)
        raise FileNotFoundError(f"Config not found: {config_path}")

    default = _PROJ_ROOT / "config" / "projects.yaml"
    if default.exists():
        return _from_yaml(default)

    return _fallback()


if __name__ == "__main__":
    import json

    print(json.dumps(load_projects(), indent=2))
