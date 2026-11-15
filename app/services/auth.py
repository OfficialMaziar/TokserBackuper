"""Authentication, sessions, RBAC and audit logging."""
from __future__ import annotations

import hashlib
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    generate_token,
    hash_password,
    new_csrf_token,
    password_needs_rehash,
    utcnow,
    verify_password,
)
from app.models import ActivityLog, LoginAttempt, Role, SessionToken, User
from app.utils import ensure_utc

log = get_logger(__name__)

ROLE_PERMISSIONS: dict[str, list[str]] = {
    "admin": ["*"],
    "operator": [
        "jobs:read", "jobs:write", "jobs:run",
        "backups:read", "backups:write", "backups:restore", "backups:delete",
        "sources:read", "sources:write",
        "storage:read", "telegram:read", "telegram:write",
        "notifications:read", "monitoring:read", "logs:read", "dashboard:read",
    ],
    "viewer": [
        "jobs:read", "backups:read", "sources:read", "storage:read",
        "telegram:read", "notifications:read", "monitoring:read",
        "logs:read", "dashboard:read",
    ],
}


def ensure_roles(db: Session) -> None:
    existing = {r.name for r in db.scalars(select(Role)).all()}
    for name, perms in ROLE_PERMISSIONS.items():
        if name not in existing:
            db.add(Role(name=name, description=name.title(), permissions=perms))
    db.commit()


def has_permission(user: User, permission: str) -> bool:
    if not user or not user.role:
        return False
    perms = user.role.permissions or []
    return "*" in perms or permission in perms


def is_setup_required(db: Session) -> bool:
    return db.scalar(select(func.count(User.id))) == 0


def create_user(
    db: Session,
    *,
    username: str,
    password: str,
    role: str = "viewer",
    email: str = "",
    full_name: str = "",
    is_active: bool = True,
    must_change_password: bool = False,
) -> User:
    username = username.strip()
    if db.scalar(select(User).where(func.lower(User.username) == username.lower())):
        raise ValueError("Username already exists")
    role_obj = db.scalar(select(Role).where(Role.name == role))
    if role_obj is None:
        raise ValueError(f"Unknown role: {role}")
    user = User(
        username=username,
        email=email.strip(),
        full_name=full_name.strip(),
        password_hash=hash_password(password),
        role_id=role_obj.id,
        is_active=is_active,
        must_change_password=must_change_password,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def authenticate(
    db: Session, username: str, password: str, ip: str = ""
) -> tuple[User | None, str]:
    """Return (user, error_reason). Handles lockout and audit logging."""
    username = (username or "").strip()
    user = db.scalar(select(User).where(func.lower(User.username) == username.lower()))

    if user is None:
        _record_attempt(db, username, ip, False, "unknown_user")
        return None, "Invalid username or password"

    now = utcnow()
    locked_until = ensure_utc(user.locked_until)
    if locked_until and locked_until > now:
        _record_attempt(db, username, ip, False, "locked")
        return None, "Account temporarily locked. Try again later."

    if not user.is_active:
        _record_attempt(db, username, ip, False, "inactive")
        return None, "Account is disabled"

    if not verify_password(password, user.password_hash):
        user.failed_attempts += 1
        if user.failed_attempts >= settings.login_max_attempts:
            user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
            user.failed_attempts = 0
            _record_attempt(db, username, ip, False, "locked_out")
            db.commit()
            return None, "Too many failed attempts. Account locked."
        db.commit()
        _record_attempt(db, username, ip, False, "bad_password")
        return None, "Invalid username or password"

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    user.last_login_ip = ip
    db.commit()
    _record_attempt(db, username, ip, True, "")
    return user, ""


def create_session(db: Session, user: User, ip: str = "", user_agent: str = "") -> tuple[str, SessionToken]:
    token = generate_token(32)
    session = SessionToken(
        user_id=user.id,
        token_hash=_token_hash(token),
        csrf_token=new_csrf_token(),
        ip_address=ip,
        user_agent=(user_agent or "")[:255],
        expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return token, session


def resolve_session(db: Session, token: str | None) -> SessionToken | None:
    if not token:
        return None
    session = db.scalar(select(SessionToken).where(SessionToken.token_hash == _token_hash(token)))
    if session is None:
        return None
    expires = ensure_utc(session.expires_at)
    if expires is None or expires <= utcnow():
        db.delete(session)
        db.commit()
        return None
    if not session.user or not session.user.is_active:
        return None
    return session


def touch_session(db: Session, session: SessionToken, min_interval_seconds: int = 300) -> None:
    """Update ``last_seen_at`` at most once per ``min_interval_seconds``.

    Writing on every request would turn each page load into a database write.
    """
    now = utcnow()
    last = ensure_utc(session.last_seen_at)
    if last is not None and (now - last).total_seconds() < min_interval_seconds:
        return
    session.last_seen_at = now
    db.commit()


def destroy_session(db: Session, token: str | None) -> None:
    if not token:
        return
    session = db.scalar(select(SessionToken).where(SessionToken.token_hash == _token_hash(token)))
    if session:
        db.delete(session)
        db.commit()


def destroy_user_sessions(db: Session, user_id: int, except_token: str | None = None) -> int:
    keep_hash = _token_hash(except_token) if except_token else None
    sessions = db.scalars(select(SessionToken).where(SessionToken.user_id == user_id)).all()
    removed = 0
    for s in sessions:
        if keep_hash and s.token_hash == keep_hash:
            continue
        db.delete(s)
        removed += 1
    db.commit()
    return removed


def purge_expired_sessions(db: Session) -> int:
    sessions = db.scalars(select(SessionToken)).all()
    now = utcnow()
    removed = 0
    for s in sessions:
        expires = ensure_utc(s.expires_at)
        if expires is None or expires <= now:
            db.delete(s)
            removed += 1
    if removed:
        db.commit()
    return removed


def _record_attempt(db: Session, username: str, ip: str, success: bool, reason: str) -> None:
    db.add(LoginAttempt(username=username[:64], ip_address=ip[:64], success=success, reason=reason))
    if not success:
        db.add(
            ActivityLog(
                username=username[:64],
                action="auth.login_failed",
                entity_type="user",
                entity_id=username[:64],
                detail=reason,
                ip_address=ip[:64],
                level="warning",
            )
        )
    else:
        db.add(
            ActivityLog(
                username=username[:64],
                action="auth.login",
                entity_type="user",
                entity_id=username[:64],
                detail="Login successful",
                ip_address=ip[:64],
            )
        )
    db.commit()


def log_activity(
    db: Session,
    user: User | None,
    action: str,
    *,
    entity_type: str = "",
    entity_id: str = "",
    detail: str = "",
    ip: str = "",
    level: str = "info",
) -> None:
    db.add(
        ActivityLog(
            user_id=user.id if user else None,
            username=user.username if user else "system",
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            detail=detail[:4000],
            ip_address=ip[:64],
            level=level,
        )
    )
    db.commit()
