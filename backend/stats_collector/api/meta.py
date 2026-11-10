"""Connecting a Facebook Page or Instagram account: Meta's consent screen and its callback.

GET  /api/connectors/meta/start?source=<id>   (admin) -> Facebook
GET  /api/connectors/meta/callback            (admin) <- Facebook, finds the Pages and accounts
POST /api/connectors/meta/<id>/choose         (admin) picks one when there are several
POST /api/connectors/meta/<id>/disconnect     (admin) forgets the token
"""

from __future__ import annotations

import json
import secrets
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import get_settings
from ..connectors import ConnectorError
from ..db import get_db
from ..models import Source, User
from ..security import decrypt_secret, encrypt_secret, require_admin
from ..services import collect, meta
from .common import audit
from .sources import meta_redirect_uri, source_out

router = APIRouter(prefix="/api/connectors/meta", tags=["meta"])

STATE_COOKIE = "sc_meta"
STATE_PATH = "/api/connectors/meta"
STATE_TTL = 600


def _back(result: str, source_id: int | None = None) -> RedirectResponse:
    query = result if "=" in result else f"meta_error={quote(result.split(':')[0])}"
    if source_id:
        query += f"&source={source_id}"
    resp = RedirectResponse(f"/admin/sources?{query}", status_code=303)
    resp.delete_cookie(STATE_COOKIE, path=STATE_PATH)
    return resp


def _source(db: Session, source_id: int) -> Source:
    s = db.get(Source, source_id)
    if s is None or s.kind not in meta.KINDS:
        raise HTTPException(404, "not_found")
    return s


def _soon(source_id: int) -> None:
    from ..worker import meta_soon

    meta_soon(source_id)


@router.get("/start")
def start(source: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    s = _source(db, source)
    cfg = s.config or {}
    if not cfg.get("client_id") or not collect.source_secrets(s).get("client_secret"):
        return _back("meta_app_missing", s.id)
    state = secrets.token_urlsafe(24)
    payload = {"s": state, "id": s.id, "exp": int(time.time()) + STATE_TTL}
    resp = RedirectResponse(meta.authorize_url(cfg, meta_redirect_uri(), state), 303)
    resp.set_cookie(
        STATE_COOKIE,
        encrypt_secret(json.dumps(payload)) or "",
        max_age=STATE_TTL,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        path=STATE_PATH,
    )
    return resp


@router.get("/callback")
def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_reason: str | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        payload = json.loads(decrypt_secret(request.cookies.get(STATE_COOKIE, "")) or "{}")
    except ValueError:
        payload = {}
    source_id = payload.get("id")
    if not payload or payload.get("exp", 0) < time.time() or not state or state != payload.get("s"):
        return _back("meta_state_invalid", source_id)
    if error:
        return _back("meta_access_denied" if error_reason == "user_denied" else "meta_failed", source_id)
    if not code:
        return _back("meta_failed", source_id)
    s = _source(db, int(source_id))
    try:
        token = meta.exchange_code(
            s.config or {}, collect.source_secrets(s).get("client_secret", ""), code, meta_redirect_uri()
        )
        result = meta.connect(db, s, token)
    except ConnectorError as exc:
        return _back(str(exc), s.id)
    if result.get("choose"):
        return _back("meta_choose=1", s.id)
    audit(db, admin, "sources.meta_connect", {"id": s.id, "account": result.get("account_id")})
    _soon(s.id)
    return _back("meta_connected=1", s.id)


class ChooseIn(BaseModel):
    account_id: str = Field(min_length=1, max_length=64)


@router.post("/{source_id}/choose")
def choose(source_id: int, body: ChooseIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    s = _source(db, source_id)
    try:
        result = meta.choose(db, s, body.account_id)
    except ConnectorError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(db, admin, "sources.meta_connect", {"id": s.id, "account": result["account_id"]})
    _soon(s.id)
    return source_out(db, s)


@router.post("/{source_id}/disconnect")
def disconnect(source_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    s = _source(db, source_id)
    meta.disconnect(db, s)
    audit(db, admin, "sources.meta_disconnect", {"id": s.id})
    return source_out(db, s)
