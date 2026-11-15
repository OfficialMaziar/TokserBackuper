"""Shared FastAPI dependencies: auth, CSRF, rate limiting, permissions."""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import csrf_tokens_match
from app.models import SessionToken, User
from app.services.auth import has_permission, resolve_session, touch_session

# ---------------------------------------------------------------------------
# Rate limiting (in-process sliding window per client IP)
# ---------------------------------------------------------------------------
_WINDOWS: dict[str, deque[float]] = defaultdict(deque)
_RATE_LOCK = __import__("threading").Lock()


def client_ip(request: Request) -> str:
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real = request.headers.get("x-real-ip")
        if real:
            return real.strip()
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request) -> None:
    ip = client_ip(request)
    now = time.monotonic()
    window = 60.0
    limit = settings.rate_limit_per_minute
    with _RATE_LOCK:
        bucket = _WINDOWS[ip]
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please slow down.",
            )
        bucket.append(now)


def get_current_session(
    request: Request, db: Session = Depends(get_db)
) -> SessionToken:
    token = request.cookies.get(settings.session_cookie)
    if not token:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
    session = resolve_session(db, token)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    touch_session(db, session)
    return session


def get_current_user(
    session: SessionToken = Depends(get_current_session),
) -> User:
    return session.user


def require_permission(permission: str):
    def _dep(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission}",
            )
        return user

    return _dep


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role_name != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return user


def verify_csrf(request: Request, session: SessionToken = Depends(get_current_session)) -> None:
    """Enforce CSRF for state-changing cookie-authenticated requests."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if request.headers.get("authorization", "").lower().startswith("bearer "):
        return  # token auth is not vulnerable to CSRF
    supplied = request.headers.get(settings.csrf_header) or request.headers.get("x-csrf-token")
    if not csrf_tokens_match(supplied, session.csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
