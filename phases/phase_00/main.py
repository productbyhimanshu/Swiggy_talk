"""FastAPI application entrypoint — Phase 0."""

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from phases.phase_00.config import get_settings
from phases.phase_00.logging_setup import configure_logging, get_log_paths, get_logger
from phases.phase_00.services.swiggy_auth import SwiggyAuthError, SwiggyAuthService

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


app.add_middleware(RequestLoggingMiddleware)


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
    """Start OAuth — redirects browser to Swiggy consent UI."""
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
    """OAuth redirect handler — exchanges code for tokens."""
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

    return HTMLResponse(
        """
        <!DOCTYPE html>
        <html>
        <head><title>Swiggy Talk — Connected</title></head>
        <body style="font-family: system-ui; padding: 2rem;">
          <h1>Swiggy connected</h1>
          <p>OAuth complete. Tokens saved locally. You can close this tab.</p>
          <p>Test: <code>GET /auth/status</code> or run <code>scripts/swiggy_smoke.py</code></p>
        </body>
        </html>
        """
    )


@app.get("/auth/status")
async def auth_status():
    """Check whether a valid Swiggy token is stored."""
    auth = SwiggyAuthService()
    bundle = auth.load_tokens()
    if bundle is None:
        return {"authenticated": False, "login_url": "/auth/swiggy/login"}
    return {
        "authenticated": not bundle.is_expired(),
        "expires_at": bundle.expires_at,
        "scope": bundle.scope,
        "login_url": "/auth/swiggy/login",
    }


@app.post("/auth/logout")
async def auth_logout():
    """Clear stored tokens."""
    SwiggyAuthService().clear_tokens()
    return {"ok": True}
