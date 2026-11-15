"""FastAPI application entry point."""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import BASE_DIR, APP_NAME, APP_VERSION, settings
from app.core.database import get_db, init_db, session_scope
from app.core.logging import get_logger, setup_logging
from app.api import auth as auth_api
from app.api import backups as backups_api
from app.api import dashboard as dashboard_api
from app.api import jobs as jobs_api
from app.api import settings as settings_api
from app.api import storage as storage_api
from app.api import telegram as telegram_api
from app.api import users as users_api
from app.api.deps import client_ip, rate_limit
from app.services import auth as auth_svc
from app.services.notifications import ensure_default_settings
from app.services.scheduler import start_scheduler, stop_scheduler

setup_logging()
log = get_logger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATE_DIR = Path(__file__).parent / "templates"


def bootstrap() -> None:
    """Prepare the database and default records. Safe to run repeatedly."""
    init_db()
    with session_scope() as db:
        auth_svc.ensure_roles(db)
        ensure_default_settings(db)

        # Apply overrides saved from the Settings page so they survive restarts.
        from app.services.runtime_settings import apply_overrides

        apply_overrides(db)
        from app.models import Server, StorageDestination

        from sqlalchemy import select

        if db.scalar(select(Server).where(Server.is_local.is_(True))) is None:
            import socket

            db.add(Server(name="local", hostname=socket.gethostname(), is_local=True, status="online"))
        if db.scalar(select(StorageDestination).where(StorageDestination.is_default.is_(True))) is None:
            db.add(
                StorageDestination(
                    name="Local Backups",
                    storage_type="local",
                    enabled=True,
                    is_default=True,
                    config={"path": settings.backup_dir},
                )
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap()
    if settings.scheduler_enabled:
        start_scheduler()
    log.info("%s v%s started on %s:%s", APP_NAME, APP_VERSION, settings.host, settings.port)
    try:
        yield
    finally:
        stop_scheduler()
        log.info("Application shutdown complete")


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Enterprise-grade Linux backup and recovery management platform by TokserTeam.",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; font-src 'self' data:; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        if settings.session_secure_cookie:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


class RequestTimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Process-Time"] = f"{(time.perf_counter() - start) * 1000:.1f}ms"
        return response


class HostValidationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if settings.allowed_hosts:
            host = request.headers.get("host", "").split(":")[0]
            if host and host not in settings.allowed_hosts:
                return JSONResponse({"detail": "Invalid host header"}, status_code=400)
        return await call_next(request)


# Endpoints that establish a session and therefore cannot carry a CSRF token.
CSRF_EXEMPT = {"/api/v1/auth/login", "/api/v1/auth/setup"}


class CSRFMiddleware(BaseHTTPMiddleware):
    """Reject cookie-authenticated state-changing requests without a valid
    CSRF token. Bearer-token requests are exempt (not CSRF-vulnerable)."""

    async def dispatch(self, request: Request, call_next):
        if (
            request.method in {"GET", "HEAD", "OPTIONS"}
            or not request.url.path.startswith("/api/")
            or request.url.path in CSRF_EXEMPT
        ):
            return await call_next(request)
        if request.headers.get("authorization", "").lower().startswith("bearer "):
            return await call_next(request)

        token = request.cookies.get(settings.session_cookie)
        if not token:
            # No session cookie: authentication will fail on its own.
            return await call_next(request)

        supplied = request.headers.get(settings.csrf_header) or request.headers.get("x-csrf-token")
        from app.core.database import SessionLocal
        from app.core.security import csrf_tokens_match
        from app.services.auth import resolve_session

        db = SessionLocal()
        try:
            session = resolve_session(db, token)
            if session is None:
                return await call_next(request)
            if not csrf_tokens_match(supplied, session.csrf_token):
                return JSONResponse({"detail": "Invalid CSRF token"}, status_code=403)
        finally:
            db.close()
        return await call_next(request)


app.add_middleware(CSRFMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestTimingMiddleware)
app.add_middleware(HostValidationMiddleware)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---------------------------------------------------------------------------
# API routers
# ---------------------------------------------------------------------------
app.include_router(auth_api.router)
app.include_router(dashboard_api.router)
app.include_router(jobs_api.router)
app.include_router(jobs_api.sources_router)
app.include_router(backups_api.router)
app.include_router(backups_api.restore_router)
app.include_router(storage_api.router)
app.include_router(telegram_api.router)
app.include_router(users_api.router)
app.include_router(settings_api.router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    if exc.status_code == 401:
        return RedirectResponse("/login", status_code=302)
    return HTMLResponse(
        f"<h1>{exc.status_code}</h1><p>{exc.detail}</p><a href='/'>Back to dashboard</a>",
        status_code=exc.status_code,
    )


# ---------------------------------------------------------------------------
# Server-rendered pages
# ---------------------------------------------------------------------------
PAGES = {
    "login": "login.html",
    "setup": "setup.html",
    "": "app.html",
    "dashboard": "app.html",
    "jobs": "app.html",
    "jobs/new": "app.html",
    "jobs/edit": "app.html",
    "sources": "app.html",
    "backups": "app.html",
    "backups/detail": "app.html",
    "restore": "app.html",
    "storage": "app.html",
    "telegram": "app.html",
    "notifications": "app.html",
    "schedules": "app.html",
    "monitoring": "app.html",
    "logs": "app.html",
    "users": "app.html",
    "security": "app.html",
    "settings": "app.html",
    "api-docs": "app.html",
    "about": "app.html",
}


def _render(name: str) -> HTMLResponse:
    path = TEMPLATE_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Page not found")
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return _render("login.html")


@app.get("/setup", response_class=HTMLResponse)
def setup_page():
    return _render("setup.html")


@app.get("/favicon.ico")
def favicon():
    icon = STATIC_DIR / "images" / "favicon.svg"
    if icon.exists():
        return FileResponse(str(icon), media_type="image/svg+xml")
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/", response_class=HTMLResponse)
def index():
    return _render("app.html")


@app.get("/{page:path}", response_class=HTMLResponse)
def spa_page(page: str):
    """Serve the single-page app shell for all client-side routes."""
    if page.startswith("api/") or page.startswith("static/"):
        raise HTTPException(status_code=404, detail="Not found")
    if page in {"login", "setup"}:
        return _render(f"{page}.html")
    return _render("app.html")


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        proxy_headers=settings.trust_proxy_headers,
    )
