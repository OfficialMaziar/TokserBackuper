"""User and role management (administrator only)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_admin
from app.core.database import get_db
from app.models import Role, User
from app.schemas import UserCreate, UserOut, UserUpdate
from app.services import auth as auth_svc

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("")
def list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    rows = db.scalars(select(User).order_by(User.username)).all()
    return [UserOut.model_validate(u).model_dump(mode="json") for u in rows]


@router.get("/roles")
def list_roles(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    rows = db.scalars(select(Role).order_by(Role.name)).all()
    return [{"id": r.id, "name": r.name, "description": r.description, "permissions": r.permissions} for r in rows]


@router.post("")
def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        user = auth_svc.create_user(
            db,
            username=payload.username,
            password=payload.password,
            role=payload.role,
            email=payload.email,
            full_name=payload.full_name,
            is_active=payload.is_active,
            must_change_password=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    auth_svc.log_activity(db, admin, "user.create", entity_type="user", entity_id=str(user.id),
                          detail=f"Created user '{user.username}' with role {payload.role}",
                          ip=client_ip(request))
    return UserOut.model_validate(user).model_dump(mode="json")


@router.put("/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="You cannot disable your own account")
    if user.id == admin.id and payload.role and payload.role != "admin":
        raise HTTPException(status_code=400, detail="You cannot demote your own account")

    if payload.email is not None:
        user.email = payload.email
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.role is not None:
        role = db.scalar(select(Role).where(Role.name == payload.role))
        if role is None:
            raise HTTPException(status_code=400, detail="Unknown role")
        user.role_id = role.id
    if payload.is_active is not None:
        user.is_active = payload.is_active
        if not payload.is_active:
            auth_svc.destroy_user_sessions(db, user.id)
    db.commit()
    auth_svc.log_activity(db, admin, "user.update", entity_type="user", entity_id=str(user.id),
                          detail=f"Updated user '{user.username}'", ip=client_ip(request))
    return UserOut.model_validate(user).model_dump(mode="json")


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    payload: dict,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    from app.core.security import hash_password

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    new_password = (payload or {}).get("password", "")
    try:
        user.password_hash = hash_password(new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    user.must_change_password = True
    db.commit()
    auth_svc.destroy_user_sessions(db, user.id)
    auth_svc.log_activity(db, admin, "user.reset_password", entity_type="user", entity_id=str(user.id),
                          detail=f"Reset password for '{user.username}'", ip=client_ip(request), level="warning")
    return {"ok": True}


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    admins = db.scalar(
        select(func.count(User.id)).join(Role).where(Role.name == "admin", User.is_active.is_(True))
    ) or 0
    if user.role_name == "admin" and admins <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last administrator")
    username = user.username
    db.delete(user)
    db.commit()
    auth_svc.log_activity(db, admin, "user.delete", entity_type="user", entity_id=str(user_id),
                          detail=f"Deleted user '{username}'", ip=client_ip(request), level="warning")
    return {"ok": True}
