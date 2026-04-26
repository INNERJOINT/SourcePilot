"""FastAPI router: /api/projects — project config endpoint."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/projects", tags=["projects"])

_SP_COCKPIT_DIR = Path(__file__).parent.parent.parent  # sp-cockpit/


def _load_projects() -> list[dict[str, Any]]:
    config_path = os.environ.get("PROJECTS_CONFIG_PATH")
    if config_path:
        path = Path(config_path)
    else:
        path = _SP_COCKPIT_DIR.parent / "config" / "projects.yaml"

    if not path.exists():
        return []

    with open(path) as f:
        data = yaml.safe_load(f)

    projects = data.get("projects", []) if data else []
    return [
        {
            "name": p.get("name", ""),
            "source_root": p.get("source_root", ""),
            "repo_path": p.get("repo_path", ""),
            "zoekt_url": p.get("zoekt_url", ""),
        }
        for p in projects
    ]


@router.get("")
async def list_projects() -> list[dict[str, Any]]:
    try:
        return _load_projects()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
