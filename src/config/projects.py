"""
Multi-project configuration for AOSP Code Search.

Loads project definitions from config/projects.yaml. Each project represents
an independent AOSP checkout with its own Zoekt webserver instance.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectConfig:
    """Configuration for a single AOSP project."""

    name: str
    source_root: str
    repo_path: str
    index_dir: str
    zoekt_url: str
    dense_collection_name: str = ""


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_CONFIG_PATH_ENV = "PROJECTS_CONFIG_PATH"
_DEFAULT_CONFIG_REL = "config/projects.yaml"

_projects_cache: list[ProjectConfig] | None = None


def _find_config_path() -> Path:
    """Resolve the projects config file path."""
    env_path = os.getenv(_CONFIG_PATH_ENV)
    if env_path:
        return Path(env_path)
    # Walk up from this file to find the project root (where config/ lives)
    here = Path(__file__).resolve()
    for parent in [here.parent.parent.parent, Path.cwd()]:
        candidate = parent / _DEFAULT_CONFIG_REL
        if candidate.exists():
            return candidate
    return Path.cwd() / _DEFAULT_CONFIG_REL


def load_projects(config_path: str | Path | None = None) -> list[ProjectConfig]:
    """Load project definitions from YAML config.

    Falls back to a single project derived from environment variables
    (ZOEKT_URL, ZOEKT_INDEX_PATH, ZOEKT_REPO_PATH) when no config file exists.
    """
    global _projects_cache
    if _projects_cache is not None and config_path is None:
        return _projects_cache

    path = Path(config_path) if config_path else _find_config_path()

    if not path.exists():
        logger.info("Projects config not found at %s — falling back to env vars", path)
        projects = _fallback_from_env()
        if config_path is None:
            _projects_cache = projects
        return projects

    # Lazy import: PyYAML may not be available everywhere
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not installed — falling back to env vars")
        projects = _fallback_from_env()
        if config_path is None:
            _projects_cache = projects
        return projects

    with open(path) as f:
        data = yaml.safe_load(f)

    if not data or "projects" not in data:
        raise ValueError(f"Invalid projects config: 'projects' key missing in {path}")

    raw_projects = data["projects"]
    if not isinstance(raw_projects, list) or len(raw_projects) == 0:
        raise ValueError(f"Invalid projects config: 'projects' must be a non-empty list in {path}")

    projects = []
    seen_names: set[str] = set()
    for entry in raw_projects:
        name = entry.get("name")
        if not name:
            raise ValueError(f"Project entry missing 'name' in {path}")
        if name in seen_names:
            raise ValueError(f"Duplicate project name '{name}' in {path}")
        seen_names.add(name)

        source_root = entry.get("source_root", "")
        repo_path = entry.get("repo_path", "")
        index_dir = entry.get("index_dir", "")
        zoekt_url = entry.get("zoekt_url", "")

        if not zoekt_url:
            raise ValueError(f"Project '{name}' missing 'zoekt_url' in {path}")

        dense_collection_name = ""
        dense_index = entry.get("dense_index")
        if isinstance(dense_index, dict):
            dense_collection_name = dense_index.get("collection_name", "") or ""

        if not dense_collection_name:
            dense_collection_name = entry.get("collection_name", "") or f"aosp_code_{name}"

        projects.append(
            ProjectConfig(
                name=name,
                source_root=source_root,
                repo_path=repo_path,
                index_dir=index_dir,
                zoekt_url=zoekt_url,
                dense_collection_name=dense_collection_name,
            )
        )

    if config_path is None:
        _projects_cache = projects
    return projects


def _fallback_from_env() -> list[ProjectConfig]:
    """Create a single-project config from legacy environment variables."""
    from config.base import ZOEKT_URL

    zoekt_index_path = os.getenv("ZOEKT_INDEX_PATH", "")
    zoekt_repo_path = os.getenv("ZOEKT_REPO_PATH", "")
    aosp_source_root = os.getenv("AOSP_SOURCE_ROOT", "")

    return [
        ProjectConfig(
            name="default",
            source_root=aosp_source_root,
            repo_path=zoekt_repo_path,
            index_dir=zoekt_index_path,
            zoekt_url=ZOEKT_URL,
            dense_collection_name=os.getenv("DENSE_COLLECTION_NAME", "aosp_code_default"),
        )
    ]


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------


def get_project(name: str) -> ProjectConfig:
    """Look up a project by name. Raises ValueError if not found."""
    projects = load_projects()
    for p in projects:
        if p.name == name:
            return p
    available = [p.name for p in projects]
    raise ValueError(f"Unknown project '{name}'. Available: {available}")


def get_default_project() -> ProjectConfig:
    """Return the first (default) project."""
    projects = load_projects()
    return projects[0]


def list_project_names() -> list[str]:
    """Return all configured project names."""
    return [p.name for p in load_projects()]


def list_projects() -> list[dict]:
    """Return all projects as dicts (for API responses)."""
    return [
        {
            "name": p.name,
            "source_root": p.source_root,
            "repo_path": p.repo_path,
            "index_dir": p.index_dir,
            "zoekt_url": p.zoekt_url,
        }
        for p in load_projects()
    ]


def reload_projects() -> list[ProjectConfig]:
    """Force reload from disk (clear cache)."""
    global _projects_cache
    _projects_cache = None
    return load_projects()
