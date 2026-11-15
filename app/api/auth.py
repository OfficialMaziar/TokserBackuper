"""Authentication and setup endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_current_session, get_current_user, rate_limit, require_admin
from app.core.config import settings
from app.core.database import get_db
from app.core.security import hash_password, verify_password
from app.models import SessionToken, User
from app.schemas import ChangePasswordRequest, LoginRequest, SetupRequest, UserOut
from app.services import auth as auth_svc

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.session_secure_cookie,
        samesite="lax",
        path="/",
    )


@router.get("/status")
def auth_status(request: Request, db: Session = Depends(get_db)):
    setup_required = auth_svc.is_setup_required(db)
    user = None
    if not setup_required:
        session = auth_svc.resolve_session(db, request.cookies.get(settings.session_cookie))
        if session:
            user = session.user
    return {
        "setup_required": setup_required,
        "authenticated": user is not None,
        "user": UserOut.model_validate(user).model_dump(mode="json") if user else None,
        "csrf_token": None,
    }


@router.post("/setup")
def setup(
    payload: SetupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _=Depends(rate_limit),
):
    if not auth_svc.is_setup_required(db):
        raise HTTPException(status_code=409, detail="Setup already completed")
    auth_svc.ensure_roles(db)
    try:
        user = auth_svc.create_user(
            db,
            username=payload.username,
            password=payload.password,
            role="admin",
            email=payload.email,
            full_name=payload.full_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    token, session = auth_svc.create_session(
        db, user, ip=client_ip(request), user_agent=request.headers.get("user-agent", "")
    )
    _set_session_cookie(response, token)
    auth_svc.log_activity(db, user, "auth.setup", detail="Initial administrator created", ip=client_ip(request))
    return {
        "ok": True,
        "user": UserOut.model_validate(user).model_dump(mode="json"),
        "csrf_token": session.csrf_token,
    }


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _=Depends(rate_limit),
):
    if auth_svc.is_setup_required(db):
        raise HTTPException(status_code=409, detail="Setup required")
    user, error = auth_svc.authenticate(db, payload.username, payload.password, ip=client_ip(request))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=error)
    if user.totp_enabled:
        if not payload.totp_code:
            raise HTTPException(status_code=401, detail="Two-factor code required")
        if not _verify_totp(user, payload.totp_code):
            auth_svc.log_activity(db, user, "auth.totp_failed", detail="Invalid 2FA code", ip=client_ip(request), level="warning")
            raise HTTPException(status_code=401, detail="Invalid two-factor code")

    token, session = auth_svc.create_session(
        db, user, ip=client_ip(request), user_agent=request.headers.get("user-agent", "")
    )
    _set_session_cookie(response, token)
    return {
        "ok": True,
        "user": UserOut.model_validate(user).model_dump(mode="json"),
        "csrf_token": session.csrf_token,
        "must_change_password": user.must_change_password,
    }


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    session: SessionToken = Depends(get_current_session),
):
    auth_svc.destroy_session(db, request.cookies.get(settings.session_cookie))
    response.delete_cookie(settings.session_cookie, path="/")
    return {"ok": True}


@router.get("/me")
def me(session: SessionToken = Depends(get_current_session)):
    return {
        "user": UserOut.model_validate(session.user).model_dump(mode="json"),
        "csrf_token": session.csrf_token,
        "permissions": session.user.role.permissions if session.user.role else [],
    }


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, user.password_hash):
        auth_svc.log_activity(db, user, "auth.password_change_failed", detail="Wrong current password",
                              ip=client_ip(request), level="warning")
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    try:
        user.password_hash = hash_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    user.must_change_password = False
    db.commit()
    auth_svc.destroy_user_sessions(db, user.id, except_token=request.cookies.get(settings.session_cookie))
    auth_svc.log_activity(db, user, "auth.password_change", detail="Password changed", ip=client_ip(request))
    return {"ok": True}


@router.get("/sessions")
def list_sessions(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    current = request.cookies.get(settings.session_cookie)
    import hashlib

    current_hash = hashlib.sha256((current or "").encode()).hexdigest()
    return [
        {
            "id": s.id,
            "ip_address": s.ip_address,
            "user_agent": s.user_agent,
            "created_at": s.created_at.isoformat(),
            "last_seen_at": s.last_seen_at.isoformat(),
            "expires_at": s.expires_at.isoformat(),
            "current": s.token_hash == current_hash,
        }
        for s in user.sessions
    ]


@router.delete("/sessions/{session_id}")
def revoke_session(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    target = db.get(SessionToken, session_id)
    if target is None or target.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    db.delete(target)
    db.commit()
    return {"ok": True}


def _verify_totp(user: User, code: str) -> bool:
    """RFC 6238 TOTP verification (30s step, SHA1, 6 digits)."""
    import base64
    import hashlib
    import hmac
    import struct
    import time

    from app.core.security import decrypt_secret

    secret = decrypt_secret(user.totp_secret)
    if not secret:
        return False
    try:
        key = base64.b32decode(secret.upper() + "=" * ((8 - len(secret) % 8) % 8))
    except Exception:
        return False
    counter = int(time.time() // 30)
    for offset in (-1, 0, 1):
        msg = struct.pack(">Q", counter + offset)
        digest = hmac.new(key, msg, hashlib.sha1).digest()
        o = digest[-1] & 0x0F
        value = struct.unpack(">I", digest[o:o + 4])[0] & 0x7FFFFFFF
        if f"{value % 1000000:06d}" == code.strip():
            return True
    return False
