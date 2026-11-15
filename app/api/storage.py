"""Storage destination management."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_permission
from app.core.database import get_db
from app.core.security import decrypt_secret, encrypt_secret
from app.models import StorageDestination, User
from app.schemas import StorageIn, StorageOut, StorageTestResult
from app.services import auth as auth_svc
from app.services.storage_backends import StorageError, build_backend

router = APIRouter(prefix="/api/v1/storage", tags=["storage"])


def _secrets(dest: StorageDestination) -> dict:
    if not dest.secrets_enc:
        return {}
    try:
        return json.loads(decrypt_secret(dest.secrets_enc) or "{}")
    except Exception:
        return {}


def _out(dest: StorageDestination) -> dict:
    data = StorageOut.model_validate(dest).model_dump(mode="json")
    data["has_secrets"] = bool(dest.secrets_enc)
    return data


@router.get("")
def list_storage(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("storage:read")),
):
    rows = db.scalars(select(StorageDestination).order_by(StorageDestination.name)).all()
    return [_out(r) for r in rows]


@router.post("")
def create_storage(
    payload: StorageIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("storage:write")),
):
    if db.scalar(select(StorageDestination).where(func.lower(StorageDestination.name) == payload.name.lower())):
        raise HTTPException(status_code=409, detail="A storage destination with this name exists")
    if payload.is_default:
        for existing in db.scalars(select(StorageDestination)).all():
            existing.is_default = False
    dest = StorageDestination(
        name=payload.name.strip(),
        storage_type=payload.storage_type.value,
        enabled=payload.enabled,
        is_default=payload.is_default,
        config=payload.config,
        secrets_enc=encrypt_secret(json.dumps(payload.secrets)) if payload.secrets else "",
    )
    db.add(dest)
    db.commit()
    db.refresh(dest)
    auth_svc.log_activity(db, user, "storage.create", entity_type="storage", entity_id=str(dest.id),
                          detail=f"Created {dest.storage_type} storage '{dest.name}'", ip=client_ip(request))
    return _out(dest)


@router.put("/{storage_id}")
def update_storage(
    storage_id: int,
    payload: StorageIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("storage:write")),
):
    dest = db.get(StorageDestination, storage_id)
    if dest is None:
        raise HTTPException(status_code=404, detail="Storage destination not found")
    duplicate = db.scalar(
        select(StorageDestination).where(
            func.lower(StorageDestination.name) == payload.name.lower(),
            StorageDestination.id != storage_id,
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="A storage destination with this name exists")
    if payload.is_default:
        for existing in db.scalars(select(StorageDestination)).all():
            existing.is_default = existing.id == storage_id
    dest.name = payload.name.strip()
    dest.storage_type = payload.storage_type.value
    dest.enabled = payload.enabled
    dest.is_default = payload.is_default
    dest.config = payload.config
    if payload.secrets:
        merged = _secrets(dest)
        merged.update({k: v for k, v in payload.secrets.items() if v})
        dest.secrets_enc = encrypt_secret(json.dumps(merged))
    db.commit()
    auth_svc.log_activity(db, user, "storage.update", entity_type="storage", entity_id=str(dest.id),
                          detail=f"Updated storage '{dest.name}'", ip=client_ip(request))
    return _out(dest)


@router.delete("/{storage_id}")
def delete_storage(
    storage_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("storage:write")),
):
    dest = db.get(StorageDestination, storage_id)
    if dest is None:
        raise HTTPException(status_code=404, detail="Storage destination not found")
    from app.models import BackupJob

    in_use = db.scalar(select(func.count(BackupJob.id)).where(BackupJob.storage_destination_id == storage_id))
    if in_use:
        raise HTTPException(status_code=409, detail=f"Storage is used by {in_use} job(s)")
    name = dest.name
    db.delete(dest)
    db.commit()
    auth_svc.log_activity(db, user, "storage.delete", entity_type="storage", entity_id=str(storage_id),
                          detail=f"Deleted storage '{name}'", ip=client_ip(request))
    return {"ok": True}


@router.post("/{storage_id}/test", response_model=StorageTestResult)
def test_storage(
    storage_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("storage:read")),
):
    dest = db.get(StorageDestination, storage_id)
    if dest is None:
        raise HTTPException(status_code=404, detail="Storage destination not found")
    try:
        backend = build_backend(dest.storage_type, dict(dest.config or {}), _secrets(dest))
        result = backend.test()
    except StorageError as exc:
        result = None
        message = str(exc)
        dest.last_test_ok = False
        dest.last_test_message = message
        from app.utils import utcnow

        dest.last_test_at = utcnow()
        db.commit()
        return StorageTestResult(ok=False, message=message)
    from app.utils import utcnow

    dest.last_test_at = utcnow()
    dest.last_test_ok = result.ok
    dest.last_test_message = result.message
    db.commit()
    return StorageTestResult(ok=result.ok, message=result.message, capacity=result.capacity)


@router.post("/test-unsaved", response_model=StorageTestResult)
def test_unsaved(
    payload: StorageIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("storage:read")),
):
    try:
        backend = build_backend(payload.storage_type.value, payload.config, payload.secrets)
        result = backend.test()
        return StorageTestResult(ok=result.ok, message=result.message, capacity=result.capacity)
    except StorageError as exc:
        return StorageTestResult(ok=False, message=str(exc))
