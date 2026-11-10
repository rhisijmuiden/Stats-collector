"""Connecting a Threads account: the Threads consent screen and its callback.

GET  /api/connectors/threads/start?source=<id>   (admin) -> threads.net
GET  /api/connectors/threads/callback            (admin) <- threads.net, stores the long-lived token
POST /api/connectors/threads/<id>/disconnect     (admin) forgets the token
"""

from __future__ import annotations

import json
import secrets
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..config import get_settings
from ..connectors import ConnectorError
from ..db import get_db
from ..models import Source, User
from ..security import decrypt_secret, encrypt_secret, require_admin
from ..services import collect, threads
from .common import audit
from .sources import source_out, threads_redirect_uri

router = APIRouter(prefix="/api/connectors/threads", tags=["threads"])

STATE_COOKIE = "sc_threads"
STATE_PATH = "/api/connectors/threads"
STATE_TTL = 600


def _back(result: str, source_id: int | None = None) -> RedirectResponse:
    query = result if "=" in result else f"threads_error={quote(result.split(':')[0])}"
    if source_id:
        query += f"&source={source_id}"
    resp = RedirectResponse(f"/admin/sources?{query}", status_code=303)
    resp.delete_cookie(STATE_COOKIE, path=STATE_PATH)
    return resp


def _source(db: Session, source_id: int) -> Source:
    s = db.get(Source, source_id)
    if s is None or s.kind not in threads.KINDS:
        raise HTTPException(404, "not_found")
    return s


@router.get("/start")
def start(source: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    s = _source(db, source)
    cfg = s.config or {}
    if not cfg.get("client_id") or not collect.source_secrets(s).get("client_secret"):
        return _back("threads_app_missing", s.id)
    state = secrets.token_urlsafe(24)
    payload = {"s": state, "id": s.id, "exp": int(time.time()) + STATE_TTL}
    resp = RedirectResponse(threads.authorize_url(cfg, threads_redirect_uri(), state), 303)
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
        return _back("threads_state_invalid", source_id)
    if error:
        return _back("threads_access_denied" if error_reason == "user_denied" else "threads_failed", source_id)
    if not code:
        return _back("threads_failed", source_id)
    s = _source(db, int(source_id))
    try:
        token = threads.exchange_code(
            s.config or {}, collect.source_secrets(s).get("client_secret", ""), code, threads_redirect_uri()
        )
        result = threads.connect(db, s, token)
    except ConnectorError as exc:
        return _back(str(exc), s.id)
    audit(db, admin, "sources.threads_connect", {"id": s.id, "account": result.get("account_id")})
    from ..worker import threads_soon

    threads_soon(s.id)
    return _back("threads_connected=1", s.id)


@router.post("/{source_id}/disconnect")
def disconnect(source_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    s = _source(db, source_id)
    threads.disconnect(db, s)
    audit(db, admin, "sources.threads_disconnect", {"id": s.id})
    return source_out(db, s)
