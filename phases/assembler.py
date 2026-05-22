"""Wire completed phase modules into one FastAPI application."""

from fastapi import FastAPI

from phases.phase_00.main import app as phase_00_app
from phases.phase_01.routes.session import router as session_router
from phases.phase_02.routes.classify import router as classify_router
from phases.phase_07.router import router as chat_router


def build_app() -> FastAPI:
    """Return the live app — extend here as later phases add routers."""
    app = phase_00_app
    app.include_router(session_router)
    app.include_router(classify_router)
    app.include_router(chat_router)
    return app
