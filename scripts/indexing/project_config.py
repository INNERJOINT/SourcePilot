"""
project_config.py — canonical sparse/dense/structural project parser for indexing.

Config precedence:
  1. --config
  2. PROJECTS_CONFIG_PATH
  3. <repo>/config/projects.yaml
  4. Fallback single project from AOSP_SOURCE_ROOT
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

_PROJ_ROOT = Path(__file__).resolve().parent.parent.parent
_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_CONFIG_ENV = "PROJECTS_CONFIG_PATH"


def _default_config_path() -> Path:
    return _PROJ_ROOT / "config" / "projects.yaml"


def _raise(msg: str) -> None:
    raise ValueError(msg)


def _require_abs_path(name: str, value: str, *, project: str) -> None:
    if not value:
        _raise(f"Project {project!r}: {name} is required")
    if not os.path.isabs(value):
        _raise(f"Project {project!r}: {name} {value!r} must be an absolute path")


def _validate_name(name: str) -> None:
    if not _NAME_RE.match(name):
        _raise(
            f"Invalid project name {name!r}: must match [a-z0-9_]+ "
            "(Qdrant collection name constraint)"
        )


def _validate_include_pattern(pattern: Any, *, project: str, field: str) -> str:
    if not isinstance(pattern, str):
        _raise(f"Project {project!r}: {field} entries must be strings")
    if "\x00" in pattern or "\n" in pattern:
        _raise(f"Project {project!r}: include pattern {pattern!r} contains invalid characters")

    cleaned = pattern.strip()
    if not cleaned:
        _raise(f"Project {project!r}: include pattern cannot be empty")
    if os.path.isabs(cleaned):
        _raise(f"Project {project!r}: include pattern {cleaned!r} must be relative")

    for part in cleaned.split("/"):
        if part in {".", ".."}:
            _raise(f"Project {project!r}: include pattern {cleaned!r} contains traversal segment")

    return cleaned


def _parse_pattern_list(value: Any, *, project: str, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        _raise(f"Project {project!r}: {field} must be a list")
    return [_validate_include_pattern(item, project=project, field=field) for item in value]


def _parse_backend_section(raw: Any, *, project: str, backend: str) -> dict[str, Any]:
    field = f"{backend}_index"
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        _raise(f"Project {project!r}: {field} must be a mapping")

    normalized: dict[str, Any] = {}
    if "enabled" in raw:
        if not isinstance(raw["enabled"], bool):
            _raise(f"Project {project!r}: {field}.enabled must be boolean")
        normalized["enabled"] = raw["enabled"]

    if "include" in raw:
        normalized["include"] = _parse_pattern_list(
            raw["include"], project=project, field=f"{field}.include"
        )

    if "collection_name" in raw:
        collection = raw["collection_name"]
        if not isinstance(collection, str) or not collection.strip():
            _raise(f"Project {project!r}: {field}.collection_name must be a non-empty string")
        normalized["collection_name"] = collection.strip()

    # Sparse-specific keys
    if backend == "sparse":
        for key in ("index_dir", "zoekt_url"):
            if key in raw:
                val = raw[key]
                if not isinstance(val, str):
                    _raise(f"Project {project!r}: {field}.{key} must be a string")
                normalized[key] = val

    return normalized


def _normalize_project(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        _raise("Each project entry must be a mapping")

    name = raw.get("name")
    source_root = raw.get("source_root")
    if not isinstance(name, str) or not name:
        _raise("Project name is required")
    if not isinstance(source_root, str) or not source_root:
        _raise(f"Project {name!r}: source_root is required")

    _validate_name(name)
    _require_abs_path("source_root", source_root, project=name)

    repo_path = raw.get("repo_path", str(Path(source_root) / ".repo"))
    index_dir = raw.get("index_dir", str(Path(source_root) / ".repo" / ".zoekt"))
    zoekt_url = raw.get("zoekt_url", "http://localhost:6070")

    if not isinstance(repo_path, str):
        _raise(f"Project {name!r}: repo_path must be a string")
    if repo_path:
        _require_abs_path("repo_path", repo_path, project=name)

    if not isinstance(index_dir, str):
        _raise(f"Project {name!r}: index_dir must be a string")
    if index_dir:
        _require_abs_path("index_dir", index_dir, project=name)

    if not isinstance(zoekt_url, str):
        _raise(f"Project {name!r}: zoekt_url must be a string")

    top_collection = raw.get("collection_name", f"aosp_code_{name}")
    if not isinstance(top_collection, str) or not top_collection.strip():
        _raise(f"Project {name!r}: collection_name must be a non-empty string")

    sparse_index = _parse_backend_section(
        raw.get("sparse_index"), project=name, backend="sparse"
    )

    # sparse_index fields override top-level index_dir / zoekt_url
    if sparse_index.get("index_dir"):
        index_dir = sparse_index["index_dir"]
        _require_abs_path("sparse_index.index_dir", index_dir, project=name)
    if sparse_index.get("zoekt_url"):
        zoekt_url = sparse_index["zoekt_url"]

    return {
        "name": name,
        "source_root": source_root,
        "repo_path": repo_path,
        "index_dir": index_dir,
        "zoekt_url": zoekt_url,
        "collection_name": top_collection.strip(),
        "sub_project_globs": _parse_pattern_list(
            raw.get("sub_project_globs", []),
            project=name,
            field="sub_project_globs",
        ),
        "sparse_index": sparse_index,
        "dense_index": _parse_backend_section(
            raw.get("dense_index"), project=name, backend="dense"
        ),
        "structural_index": _parse_backend_section(
            raw.get("structural_index"), project=name, backend="structural"
        ),
    }


def _resolve_config_path(config_path: str | None = None) -> Path | None:
    if config_path is not None:
        path = Path(config_path)
        if path.exists():
            return path.resolve()
        raise FileNotFoundError(f"Config not found: {config_path}")

    env_path = os.environ.get(_CONFIG_ENV)
    if env_path:
        path = Path(env_path)
        if path.exists():
            return path.resolve()
        raise FileNotFoundError(f"Config not found: {env_path}")

    default_config = _default_config_path()
    if default_config.exists():
        return default_config.resolve()

    return None


def _from_yaml(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    if not isinstance(data, dict):
        _raise(f"Invalid config {path}: root must be a mapping")

    projects = data.get("projects", [])
    if not isinstance(projects, list):
        _raise(f"Invalid config {path}: projects must be a list")

    return [_normalize_project(raw) for raw in projects]


def _fallback() -> list[dict[str, Any]]:
    source_root = os.environ.get("AOSP_SOURCE_ROOT", "/mnt/code/ACE")
    name = Path(source_root).name.lower()
    name = re.sub(r"[^a-z0-9]", "_", name)

    return [
        _normalize_project(
            {
                "name": name,
                "source_root": source_root,
            }
        )
    ]


def _resolve_includes(
    patterns: list[str], *, source_root: str, project: str
) -> list[dict[str, str]]:
    root_path = Path(source_root)
    root_real = root_path.resolve()

    includes: list[dict[str, str]] = []
    seen_source_dirs: set[str] = set()
    seen_repo_names: set[str] = set()

    for pattern in patterns:
        matches = sorted(root_path.glob(pattern), key=lambda p: p.as_posix())
        if not matches:
            _raise(f"Project {project!r}: include pattern {pattern!r} matched no paths")

        for matched in matches:
            if not matched.is_dir():
                _raise(
                    f"Project {project!r}: include pattern {pattern!r} "
                    f"matched non-directory {matched}"
                )

            resolved = matched.resolve()
            try:
                repo_rel = resolved.relative_to(root_real)
            except ValueError as exc:
                raise ValueError(
                    f"Project {project!r}: include path {matched} resolves outside source_root"
                ) from exc

            source_dir = str(resolved)
            repo_name = repo_rel.as_posix()

            if repo_name in seen_repo_names:
                _raise(f"Project {project!r}: duplicate include repo_name {repo_name}")
            if source_dir in seen_source_dirs:
                _raise(f"Project {project!r}: duplicate include source_dir {source_dir}")

            seen_source_dirs.add(source_dir)
            seen_repo_names.add(repo_name)
            includes.append(
                {
                    "pattern": pattern,
                    "source_dir": source_dir,
                    "repo_name": repo_name,
                }
            )

    includes.sort(key=lambda item: item["repo_name"])
    return includes


def _backend_mode_and_includes(
    project: dict[str, Any], backend: str
) -> tuple[str, list[dict[str, str]]]:
    backend_cfg: dict[str, Any] = project[f"{backend}_index"]
    legacy_patterns: list[str] = project["sub_project_globs"]

    enabled = backend_cfg.get("enabled", True)
    include_present = "include" in backend_cfg
    backend_patterns: list[str] = backend_cfg.get("include", [])

    has_backend_patterns = include_present and len(backend_patterns) > 0

    if not enabled and has_backend_patterns:
        _raise(
            f"Project {project['name']!r}: {backend}_index.enabled=false cannot be combined "
            "with non-empty include"
        )

    if legacy_patterns and has_backend_patterns:
        _raise(
            f"Project {project['name']!r}: cannot mix sub_project_globs with non-empty "
            f"{backend}_index.include"
        )

    if not enabled:
        return "disabled", []

    if include_present and len(backend_patterns) == 0:
        return "disabled", []

    if has_backend_patterns:
        return "explicit", _resolve_includes(
            backend_patterns,
            source_root=project["source_root"],
            project=project["name"],
        )

    if legacy_patterns:
        return "legacy", _resolve_includes(
            legacy_patterns,
            source_root=project["source_root"],
            project=project["name"],
        )

    return "default", []


def _dense_collection_name(project: dict[str, Any]) -> str:
    dense_cfg: dict[str, Any] = project["dense_index"]
    if "collection_name" in dense_cfg:
        return dense_cfg["collection_name"]
    return project["collection_name"]


def _load_projects_with_source(
    config_path: str | None = None,
) -> tuple[list[dict[str, Any]], Path | None]:
    resolved = _resolve_config_path(config_path)
    if resolved is None:
        return _fallback(), None
    return _from_yaml(resolved), resolved


def load_projects(config_path: str | None = None) -> list[dict[str, Any]]:
    """Back-compat helper returning normalized projects."""
    projects, _ = _load_projects_with_source(config_path)
    return projects


def build_backend_config(
    backend: str,
    *,
    project: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    if backend not in {"dense", "structural", "sparse"}:
        _raise(f"Unsupported backend {backend!r}")

    projects, resolved = _load_projects_with_source(config_path)

    if project is not None:
        projects = [p for p in projects if p["name"] == project]
        if not projects:
            _raise(f"Unknown project {project!r}")

    rendered_projects: list[dict[str, Any]] = []
    for p in projects:
        mode, includes = _backend_mode_and_includes(p, backend)
        entry: dict[str, Any] = {
            "name": p["name"],
            "source_root": p["source_root"],
            "repo_path": p["repo_path"],
            "index_dir": p["index_dir"],
            "zoekt_url": p["zoekt_url"],
            "mode": mode,
            "includes": includes,
        }
        if backend == "dense":
            entry["collection_name"] = _dense_collection_name(p)
        rendered_projects.append(entry)

    return {
        "backend": backend,
        "config_path": str(resolved) if resolved is not None else None,
        "projects": rendered_projects,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render sparse/dense/structural project config JSON",
        epilog=(
            "Config precedence: --config > PROJECTS_CONFIG_PATH > config/projects.yaml > "
            "AOSP_SOURCE_ROOT fallback"
        ),
    )
    parser.add_argument("--format", choices=["json"], default="json")
    parser.add_argument("--backend", choices=["dense", "structural", "sparse"], required=True)
    parser.add_argument("--project", help="Only emit one project from the resolved config")
    parser.add_argument("--config", help="Path to projects.yaml (highest precedence)")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        payload = build_backend_config(
            args.backend,
            project=args.project,
            config_path=args.config,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print(f"ERROR: unsupported format {args.format}", file=os.sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
