from __future__ import annotations

from datetime import UTC, timedelta

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import SetupToken, User, UserSession, utcnow
from ..security import (
    create_session,
    current_session,
    current_user,
    decrypt_secret,
    destroy_session,
    encrypt_secret,
    hash_password,
    login_limiter,
    password_problems,
    sha256,
    verify_password,
)
from ..services import settings_store
from .common import audit, user_out

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str
    totp: str | None = None


class SetupIn(BaseModel):
    token: str
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=200)
    password: str
    language: str = "en"


class ProfileIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    language: str | None = None
    theme: str | None = None


class PasswordIn(BaseModel):
    current_password: str
    new_password: str


class TotpConfirmIn(BaseModel):
    secret: str
    code: str


def _session_payload(user: User, sess: UserSession) -> dict:
    return {"user": user_out(user), "csrf_token": sess.csrf_token}


@router.get("/status")
def auth_status(db: Session = Depends(get_db)) -> dict:
    users = db.execute(select(func.count()).select_from(User)).scalar_one()
    sso = settings_store.get_section(db, "sso")
    general = settings_store.get_section(db, "general")
    return {
        "needs_setup": users == 0,
        "sso_enabled": bool(sso.get("enabled")),
        "local_login": bool(sso.get("allow_local_login", True)) or not sso.get("enabled"),
        "default_language": general.get("default_language", "en"),
    }


@router.post("/setup")
def setup(body: SetupIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    tok = db.get(SetupToken, sha256(body.token))
    now = utcnow()
    if tok is None or tok.used_at is not None or tok.expires_at.replace(tzinfo=tok.expires_at.tzinfo or UTC) < now:
        raise HTTPException(400, "setup_token_invalid")
    if db.execute(select(func.count()).select_from(User)).scalar_one() > 0:
        raise HTTPException(400, "setup_already_done")
    problems = password_problems(body.password)
    if problems:
        raise HTTPException(400, problems[0])
    user = User(
        email=body.email.lower(),
        display_name=body.display_name,
        password_hash=hash_password(body.password),
        role="admin",
        language=body.language if body.language in ("en", "nl") else "en",
    )
    db.add(user)
    tok.used_at = now
    db.commit()
    settings_store.update_section(db, "general", {"default_language": user.language})
    sess = create_session(db, user, request, response)
    audit(db, user, "setup.first_admin")
    return _session_payload(user, sess)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    ip = request.client.host if request.client else "unknown"
    key = f"{ip}:{body.email.lower()}"
    if not login_limiter.hit(key):
        raise HTTPException(429, "too_many_attempts")
    user = db.execute(select(User).where(func.lower(User.email) == body.email.lower())).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(user.password_hash, body.password):
        raise HTTPException(401, "invalid_credentials")
    sso = settings_store.get_section(db, "sso")
    if sso.get("enabled") and not sso.get("allow_local_login", True) and user.role != "admin":
        raise HTTPException(403, "local_login_disabled")
    if user.totp_secret:
        if not body.totp:
            raise HTTPException(401, "totp_required")
        secret = decrypt_secret(user.totp_secret)
        if not secret or not pyotp.TOTP(secret).verify(body.totp.strip(), valid_window=1):
            raise HTTPException(401, "totp_invalid")
    login_limiter.reset(key)
    sess = create_session(db, user, request, response)
    audit(db, user, "auth.login", {"ip": ip})
    return _session_payload(user, sess)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db), _=Depends(current_session)) -> dict:
    destroy_session(db, request, response)
    return {"ok": True}


@router.get("/me")
def me(sess: UserSession = Depends(current_session)) -> dict:
    return _session_payload(sess.user, sess)


@router.patch("/me")
def update_me(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.language is not None:
        if body.language not in ("en", "nl"):
            raise HTTPException(400, "invalid_language")
        user.language = body.language
    if body.theme is not None:
        if body.theme not in ("system", "light", "dark"):
            raise HTTPException(400, "invalid_theme")
        user.theme = body.theme
    db.commit()
    return user_out(user)


@router.post("/password")
def change_password(body: PasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(400, "invalid_credentials")
    problems = password_problems(body.new_password)
    if problems:
        raise HTTPException(400, problems[0])
    user.password_hash = hash_password(body.new_password)
    db.commit()
    audit(db, user, "auth.password_changed")
    return {"ok": True}


@router.get("/totp/setup")
def totp_setup(user: User = Depends(current_user)) -> dict:
    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="Stats Collector")
    return {"secret": secret, "otpauth_uri": uri}


@router.post("/totp/enable")
def totp_enable(body: TotpConfirmIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if not pyotp.TOTP(body.secret).verify(body.code.strip(), valid_window=1):
        raise HTTPException(400, "totp_invalid")
    user.totp_secret = encrypt_secret(body.secret)
    db.commit()
    audit(db, user, "auth.totp_enabled")
    return user_out(user)


@router.post("/totp/disable")
def totp_disable(body: PasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(400, "invalid_credentials")
    user.totp_secret = None
    db.commit()
    audit(db, user, "auth.totp_disabled")
    return user_out(user)


def create_setup_token(db: Session, hours: int = 24) -> str:
    from ..security import new_token

    token = new_token()
    db.add(SetupToken(id=sha256(token), expires_at=utcnow() + timedelta(hours=hours)))
    db.commit()
    return token
