"""Passwords, sessions, CSRF, secret encryption and role checks."""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import ROLES, User, UserSession, utcnow

SESSION_COOKIE = "sc_session"
CSRF_HEADER = "X-CSRF-Token"

_hasher = PasswordHasher()  # Argon2id with library defaults (RFC 9106 low-memory profile)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < 12:
        problems.append("password_too_short")
    return problems


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


# --- secret encryption ------------------------------------------------------------------------------


def _fernet() -> Fernet:
    key = hashlib.sha256(("sc-secrets:" + get_settings().secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None


# --- login rate limiting ----------------------------------------------------------------------------


class RateLimiter:
    def __init__(self, limit: int, window_s: int):
        self.limit = limit
        self.window = window_s
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True

    def reset(self, key: str) -> None:
        self.hits.pop(key, None)


login_limiter = RateLimiter(limit=10, window_s=300)


# --- sessions ---------------------------------------------------------------------------------------


def create_session(db: Session, user: User, request: Request, response: Response) -> UserSession:
    token = new_token()
    settings = get_settings()
    sess = UserSession(
        id=sha256(token),
        user_id=user.id,
        csrf_token=new_token(),
        expires_at=utcnow() + timedelta(hours=settings.session_hours),
        ip=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:400],
    )
    db.add(sess)
    user.last_login_at = utcnow()
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return sess


def destroy_session(db: Session, request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        sess = db.get(UserSession, sha256(token))
        if sess:
            db.delete(sess)
            db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


def _as_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def current_session(request: Request, db: Session = Depends(get_db)) -> UserSession:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not_authenticated")
    sess = db.execute(select(UserSession).where(UserSession.id == sha256(token))).scalar_one_or_none()
    if sess is None or _as_aware(sess.expires_at) < utcnow() or not sess.user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not_authenticated")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        sent = request.headers.get(CSRF_HEADER, "")
        if not secrets.compare_digest(sent, sess.csrf_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "csrf_failed")
    return sess


def current_user(sess: UserSession = Depends(current_session)) -> User:
    return sess.user


def require_role(*roles: str):
    for r in roles:
        assert r in ROLES, r

    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
        return user

    return dep


require_admin = require_role("admin")
