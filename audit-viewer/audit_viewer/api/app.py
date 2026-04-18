"""FastAPI app factory: mounts /api/* routers + serves SPA static files."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
        app.mount(
            "/",
            StaticFiles(directory=str(config.FRONTEND_DIST), html=True),
            name="spa",
        )
    else:
        log.warning("Frontend dist not found at %s — SPA not served", config.FRONTEND_DIST)

    return app
