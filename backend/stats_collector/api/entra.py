"""Microsoft 365 sign-in endpoints: /api/auth/entra/start and /api/auth/entra/callback."""

from __future__ import annotations

import json
import logging
import secrets
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import User
from ..security import create_session, decrypt_secret, encrypt_secret
from ..services import entra, settings_store
from .common import audit

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth/entra", tags=["auth"])

STATE_COOKIE = "sc_entra"
STATE_TTL = 600


def redirect_uri() -> str:
    return get_settings().public_url.rstrip("/") + "/api/auth/entra/callback"


def _fail(code: str) -> RedirectResponse:
    resp = RedirectResponse(f"/login?sso_error={quote(code.split(':')[0])}", status_code=303)
    resp.delete_cookie(STATE_COOKIE, path="/api/auth/entra")
    return resp


def _safe_next(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value


@router.get("/start")
def start(next: str | None = None, login_hint: str | None = None, db: Session = Depends(get_db)):
    cfg = settings_store.get_section(db, "sso")
    try:
        entra.check_config(cfg, decrypt_secret(cfg.get("client_secret_enc")))
        verifier, challenge = entra.pkce_pair()
        state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        url = entra.authorize_url(cfg, redirect_uri(), state, nonce, challenge, login_hint)
    except entra.EntraError as exc:
        return _fail(str(exc))
    payload = {"s": state, "n": nonce, "v": verifier, "next": _safe_next(next), "exp": int(time.time()) + STATE_TTL}
    resp = RedirectResponse(url, status_code=303)
    resp.set_cookie(
        STATE_COOKIE,
        encrypt_secret(json.dumps(payload)) or "",
        max_age=STATE_TTL,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        path="/api/auth/entra",
    )
    return resp


def _upsert_user(db: Session, cfg: dict, ident: dict, role: str) -> tuple[User | None, str | None]:
    user = db.execute(select(User).where(User.external_id == ident["external_id"])).scalar_one_or_none()
    if user is None and ident["email"]:
        user = db.execute(select(User).where(func.lower(User.email) == ident["email"])).scalar_one_or_none()
        if user is not None:
            # Same e-mail address as an existing account: link it. A local account keeps its
            # password and its role (it is the break-glass admin); it can now also use Microsoft.
            user.external_id = ident["external_id"]
    if user is None:
        if not ident["email"]:
            return None, "sso_no_email"
        user = User(
            email=ident["email"],
            display_name=ident["name"][:200],
            role=role,
            auth_provider="entra",
            external_id=ident["external_id"],
            language=settings_store.get_section(db, "general").get("default_language", "en"),
        )
        db.add(user)
        db.flush()
        return user, None
    if not user.is_active:
        return None, "account_disabled"
    if user.auth_provider == "entra":
        user.role = role
        if ident["name"]:
            user.display_name = ident["name"][:200]
    return user, None


@router.get("/callback")
def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
             db: Session = Depends(get_db)):
    if error:
        return _fail(f"sso_{error}")
    raw = decrypt_secret(request.cookies.get(STATE_COOKIE))
    try:
        saved = json.loads(raw) if raw else None
    except ValueError:
        saved = None
    if not saved or saved.get("exp", 0) < time.time() or not state or not secrets.compare_digest(saved["s"], state):
        return _fail("sso_state_invalid")
    if not code:
        return _fail("sso_no_code")
    cfg = settings_store.get_section(db, "sso")
    client_secret = decrypt_secret(cfg.get("client_secret_enc"))
    try:
        entra.check_config(cfg, client_secret)
        tokens = entra.exchange_code(cfg, client_secret or "", code, saved["v"], redirect_uri())
        claims = entra.validate_id_token(cfg, tokens.get("id_token") or "", saved["n"])
    except entra.EntraError as exc:
        log.warning("Microsoft sign-in failed: %s", exc)
        return _fail(str(exc))
    groups = entra.group_ids(claims, tokens.get("access_token"))
    role = entra.resolve_role(cfg, groups, [str(r) for r in claims.get("roles") or []])
    ident = entra.identity(claims)
    user, problem = _upsert_user(db, cfg, ident, role)
    if user is None:
        db.rollback()
        return _fail(problem or "sso_failed")
    db.commit()
    resp = RedirectResponse(saved.get("next") or "/", status_code=303)
    resp.delete_cookie(STATE_COOKIE, path="/api/auth/entra")
    create_session(db, user, request, resp)
    audit(db, user, "auth.login_entra", {"ip": request.client.host if request.client else None, "role": user.role})
    return resp
