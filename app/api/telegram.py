"""Telegram destination management and testing."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_permission
from app.core.database import get_db
from app.core.security import decrypt_secret, encrypt_secret, mask_secret
from app.models import TelegramDestination, User
from app.schemas import TelegramIn, TelegramOut, TelegramTestRequest
from app.services import auth as auth_svc
from app.services.telegram_service import TelegramClient, TelegramError

router = APIRouter(prefix="/api/v1/telegram", tags=["telegram"])


def _out(dest: TelegramDestination) -> dict:
    data = TelegramOut.model_validate(dest).model_dump(mode="json")
    token = decrypt_secret(dest.bot_token_enc)
    data["bot_token_masked"] = mask_secret(token, 6) if token else ""
    data["has_token"] = bool(token)
    return data


@router.get("")
def list_destinations(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("telegram:read")),
):
    rows = db.scalars(select(TelegramDestination).order_by(TelegramDestination.name)).all()
    return [_out(r) for r in rows]


@router.post("")
def create_destination(
    payload: TelegramIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("telegram:write")),
):
    if db.scalar(select(TelegramDestination).where(func.lower(TelegramDestination.name) == payload.name.lower())):
        raise HTTPException(status_code=409, detail="A destination with this name exists")
    dest = TelegramDestination(
        name=payload.name.strip(),
        bot_token_enc=encrypt_secret(payload.bot_token) if payload.bot_token else "",
        chat_id=payload.chat_id.strip(),
        enabled=payload.enabled,
        send_notifications=payload.send_notifications,
        upload_enabled=payload.upload_enabled,
    )
    db.add(dest)
    db.commit()
    db.refresh(dest)
    auth_svc.log_activity(db, user, "telegram.create", entity_type="telegram", entity_id=str(dest.id),
                          detail=f"Created Telegram destination '{dest.name}'", ip=client_ip(request))
    return _out(dest)


@router.put("/{dest_id}")
def update_destination(
    dest_id: int,
    payload: TelegramIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("telegram:write")),
):
    dest = db.get(TelegramDestination, dest_id)
    if dest is None:
        raise HTTPException(status_code=404, detail="Destination not found")
    dest.name = payload.name.strip()
    dest.chat_id = payload.chat_id.strip()
    dest.enabled = payload.enabled
    dest.send_notifications = payload.send_notifications
    dest.upload_enabled = payload.upload_enabled
    if payload.bot_token:
        dest.bot_token_enc = encrypt_secret(payload.bot_token)
    db.commit()
    auth_svc.log_activity(db, user, "telegram.update", entity_type="telegram", entity_id=str(dest.id),
                          detail=f"Updated Telegram destination '{dest.name}'", ip=client_ip(request))
    return _out(dest)


@router.delete("/{dest_id}")
def delete_destination(
    dest_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("telegram:write")),
):
    dest = db.get(TelegramDestination, dest_id)
    if dest is None:
        raise HTTPException(status_code=404, detail="Destination not found")
    from app.models import BackupJob

    in_use = db.scalar(select(func.count(BackupJob.id)).where(BackupJob.telegram_destination_id == dest_id))
    if in_use:
        raise HTTPException(status_code=409, detail=f"Destination is used by {in_use} job(s)")
    name = dest.name
    db.delete(dest)
    db.commit()
    auth_svc.log_activity(db, user, "telegram.delete", entity_type="telegram", entity_id=str(dest_id),
                          detail=f"Deleted Telegram destination '{name}'", ip=client_ip(request))
    return {"ok": True}


@router.post("/{dest_id}/test")
def test_destination(
    dest_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("telegram:read")),
):
    dest = db.get(TelegramDestination, dest_id)
    if dest is None:
        raise HTTPException(status_code=404, detail="Destination not found")
    token = decrypt_secret(dest.bot_token_enc)
    from app.utils import utcnow

    try:
        client = TelegramClient(token, dest.chat_id)
        info = client.get_me()
        dest.last_test_at = utcnow()
        dest.last_test_ok = True
        dest.last_test_message = f"Connected as @{info.get('username', 'bot')}"
        db.commit()
        return {"ok": True, "message": dest.last_test_message, "bot": {
            "id": info.get("id"), "username": info.get("username"), "first_name": info.get("first_name")
        }}
    except TelegramError as exc:
        dest.last_test_at = utcnow()
        dest.last_test_ok = False
        dest.last_test_message = str(exc)
        db.commit()
        return {"ok": False, "message": str(exc)}


@router.post("/{dest_id}/send-test")
def send_test_message(
    dest_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("telegram:read")),
):
    dest = db.get(TelegramDestination, dest_id)
    if dest is None:
        raise HTTPException(status_code=404, detail="Destination not found")
    token = decrypt_secret(dest.bot_token_enc)
    try:
        client = TelegramClient(token, dest.chat_id)
        client.send_message(
            "<b>Tokser Backup Manager</b>\nTest message — connection is working. ✅"
        )
        return {"ok": True, "message": "Test message delivered"}
    except TelegramError as exc:
        return {"ok": False, "message": str(exc)}


@router.post("/test-unsaved")
def test_unsaved(
    payload: TelegramTestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("telegram:read")),
):
    try:
        client = TelegramClient(payload.bot_token or "", payload.chat_id or "")
        info = client.get_me()
        return {"ok": True, "message": f"Connected as @{info.get('username', 'bot')}"}
    except TelegramError as exc:
        return {"ok": False, "message": str(exc)}
