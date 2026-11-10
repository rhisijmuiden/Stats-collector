from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ROLES, User
from ..security import hash_password, password_problems, require_admin
from .common import audit, user_out

router = APIRouter(prefix="/api/users", tags=["users"])


class UserIn(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=200)
    role: str = "staff"
    language: str = "en"
    password: str | None = None
    is_active: bool = True


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: str | None = None
    language: str | None = None
    password: str | None = None
    is_active: bool | None = None


def _check(role: str | None, language: str | None, password: str | None) -> None:
    if role is not None and role not in ROLES:
        raise HTTPException(400, "invalid_role")
    if language is not None and language not in ("en", "nl"):
        raise HTTPException(400, "invalid_language")
    if password:
        problems = password_problems(password)
        if problems:
            raise HTTPException(400, problems[0])


def _active_admins(db: Session) -> int:
    return db.execute(
        select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))
    ).scalar_one()


@router.get("")
def list_users(db: Session = Depends(get_db), _=Depends(require_admin)) -> list[dict]:
    return [user_out(u) for u in db.execute(select(User).order_by(User.display_name)).scalars()]


@router.post("", status_code=201)
def create_user(body: UserIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    _check(body.role, body.language, body.password)
    email = body.email.lower()
    if db.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none():
        raise HTTPException(409, "email_exists")
    user = User(
        email=email,
        display_name=body.display_name,
        role=body.role,
        language=body.language,
        is_active=body.is_active,
        password_hash=hash_password(body.password) if body.password else None,
    )
    db.add(user)
    db.commit()
    audit(db, admin, "user.created", {"user_id": user.id, "role": user.role})
    return user_out(user)


@router.patch("/{user_id}")
def update_user(
    user_id: int, body: UserPatch, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "not_found")
    _check(body.role, body.language, body.password)
    demoting = user.role == "admin" and ((body.role is not None and body.role != "admin") or body.is_active is False)
    if demoting and _active_admins(db) <= 1:
        raise HTTPException(400, "last_admin")
    for field in ("display_name", "role", "language", "is_active"):
        value = getattr(body, field)
        if value is not None:
            setattr(user, field, value)
    if body.password:
        user.password_hash = hash_password(body.password)
    db.commit()
    audit(db, admin, "user.updated", {"user_id": user.id})
    return user_out(user)


@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "not_found")
    if user.id == admin.id:
        raise HTTPException(400, "cannot_delete_self")
    if user.role == "admin" and _active_admins(db) <= 1:
        raise HTTPException(400, "last_admin")
    db.delete(user)
    db.commit()
    audit(db, admin, "user.deleted", {"user_id": user_id})
    return {"ok": True}
