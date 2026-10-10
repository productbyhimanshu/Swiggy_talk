"""FastAPI application entrypoint — Phase 0."""

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from phases.phase_00.config import get_settings
from phases.phase_00.logging_setup import configure_logging, get_log_paths, get_logger
from phases.phase_00.services.identity import (
    IdentityMiddleware,
    clear_identity_cookie,
    current_uid_var,
)
from phases.phase_00.services.swiggy_auth import (
    ReauthRequired,
    SwiggyAuthError,
    SwiggyAuthService,
)
from phases.phase_00.services.token_store import get_token_store
from phases.phase_01.models.state import SessionOwnershipError

configure_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    log.info(
        "app_start",
        order_enabled=settings.order_enabled,
        eval_suite_passed=settings.eval_suite_passed,
        orders_allowed=settings.orders_allowed,
    )
    yield
    log.info("app_shutdown")


app = FastAPI(
    title="Swiggy Talk API",
    version="0.1.0",
    description="Conversational food ordering — Phase 0 foundation",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request to logs/swiggy-talk.log (and errors.log on 4xx/5xx)."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception(
                "http_request_failed",
                method=request.method,
                path=request.url.path,
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
            )
            raise

        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        event = "http_request"
        log_fn = log.info
        if response.status_code >= 500:
            event = "http_request_error"
            log_fn = log.error
        elif response.status_code >= 400:
            event = "http_request_client_error"
            log_fn = log.warning

        log_fn(
            event,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )
        return response


# Order matters: IdentityMiddleware must run BEFORE any route reads
# current_uid_var. Starlette runs middleware in reverse-add order, so
# add IdentityMiddleware last.
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(IdentityMiddleware)


@app.exception_handler(ReauthRequired)
async def reauth_required_handler(request: Request, exc: ReauthRequired):
    """Any Swiggy 401/419 inside the request pipeline → structured 401 for the frontend."""
    return JSONResponse(
        status_code=401,
        content={"error": "reauth_required", "detail": str(exc)},
    )


@app.exception_handler(SessionOwnershipError)
async def session_ownership_handler(request: Request, exc: SessionOwnershipError):
    """Someone's cookie tried to open a session that belongs to another cookie."""
    log.warning("session_ownership_denied", path=request.url.path)
    return JSONResponse(status_code=404, content={"error": "session_not_found"})


@app.get("/health")
async def health():
    """Liveness check."""
    s = get_settings()
    return {
        "status": "ok",
        "order_enabled": s.order_enabled,
        "eval_suite_passed": s.eval_suite_passed,
        "orders_allowed": s.orders_allowed,
        "logs": get_log_paths(),
    }


@app.get("/auth/swiggy/login")
async def swiggy_login():
    """Start OAuth for the current cookie user — redirects to Swiggy consent."""
    auth = SwiggyAuthService()
    try:
        url, _state = auth.build_authorization_url()
    except SwiggyAuthError as exc:
        log.warning("oauth_login_failed", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url)


@app.get("/auth/callback")
async def swiggy_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    """OAuth redirect — exchanges code → saves token for the current user → redirects to app."""
    if error:
        log.warning("oauth_callback_error", oauth_error=error)
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    if not code:
        log.warning("oauth_callback_missing_code")
        raise HTTPException(status_code=400, detail="Missing authorization code")

    auth = SwiggyAuthService()
    try:
        await auth.exchange_code(code, state)
        log.info("oauth_callback_success")
    except SwiggyAuthError as exc:
        log.warning("oauth_token_exchange_failed", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Land users back on the app. In dev the frontend is on :5173; in prod
    # it's served from this host.
    settings = get_settings()
    return RedirectResponse(settings.frontend_url or "/")


@app.get("/auth/status")
async def auth_status():
    """Whether THIS cookie's user has a valid token."""
    auth = SwiggyAuthService()
    uid = current_uid_var.get()
    rec = get_token_store().get(uid) if uid else None
    now = time.time()
    authenticated = bool(rec and now < (rec.expires_at - 300))
    hours_left = max(0.0, round((rec.expires_at - now) / 3600, 1)) if rec else 0.0
    return {
        "authenticated": authenticated,
        "expires_in_hours": hours_left,
        "login_url": "/auth/swiggy/login",
    }


@app.post("/auth/logout")
async def swiggy_logout(request: Request):
    """Delete this user's token AND clear the identity cookie — fresh anonymous on next load."""
    SwiggyAuthService().logout()
    response = JSONResponse({"ok": True})
    clear_identity_cookie(response, is_https=request.url.scheme == "https")
    return response
