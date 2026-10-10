"""Wire completed phase modules into one FastAPI application."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from phases.phase_00.main import app as phase_00_app
from phases.phase_01.routes.session import router as session_router
from phases.phase_02.routes.classify import router as classify_router
from phases.phase_07.router import router as chat_router
from phases.phase_09.router import router as cart_router
from phases.phase_11.routes.schedule import router as schedule_router
from phases.phase_13.routes.place_order import router as order_router

_FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
_API_PREFIXES = ("api", "auth", "health", "docs", "redoc", "openapi.json")


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built React app from FastAPI (same origin, so /api calls just work)."""
    index_file = _FRONTEND_DIST / "index.html"
    if not index_file.exists():
        return  # local dev: Vite serves the frontend on :5173

    assets_dir = _FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/", include_in_schema=False)
    async def spa_root():
        return FileResponse(index_file)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # Never mask a missing API route with the SPA shell.
        if full_path.split("/", 1)[0] in _API_PREFIXES:
            raise HTTPException(status_code=404)
        candidate = (_FRONTEND_DIST / full_path).resolve()
        if candidate.is_file() and _FRONTEND_DIST in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index_file)


def build_app() -> FastAPI:
    """Return the live app — extend here as later phases add routers."""
    app = phase_00_app
    app.include_router(session_router)
    app.include_router(classify_router)
    app.include_router(chat_router)
    app.include_router(cart_router)
    app.include_router(schedule_router)
    app.include_router(order_router)
    _mount_frontend(app)  # must stay last: catch-all route
    return app
