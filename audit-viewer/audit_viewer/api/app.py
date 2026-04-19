"""FastAPI app factory: mounts /api/* routers + serves SPA static files."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import config
from . import events, health, search, stats, trace

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="Audit Viewer", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api")
    app.include_router(stats.router, prefix="/api")
    app.include_router(events.router, prefix="/api")
    app.include_router(trace.router, prefix="/api")
    app.include_router(search.router, prefix="/api")

    if config.FRONTEND_DIST.exists():
        index_html = config.FRONTEND_DIST / "index.html"

        # /assets/* and other built asset subdirs — served verbatim
        assets_dir = config.FRONTEND_DIST / "assets"
        if assets_dir.exists():
            app.mount(
                "/assets",
                StaticFiles(directory=str(assets_dir)),
                name="assets",
            )

        # SPA fallback: any non-/api path -> index.html so BrowserRouter deep
        # links (/trace/<id>, /events, ...) survive refresh.
        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str) -> FileResponse:  # pragma: no cover - trivial
            candidate = config.FRONTEND_DIST / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index_html)
    else:
        log.warning("Frontend dist not found at %s — SPA not served", config.FRONTEND_DIST)

    return app
