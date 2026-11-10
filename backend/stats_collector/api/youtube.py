"""Connecting a YouTube channel: Google consent screen and its callback.

GET /api/connectors/youtube/start?source=<id>   (admin) -> Google
GET /api/connectors/youtube/callback            (admin) <- Google, stores the refresh token
POST /api/connectors/youtube/<id>/disconnect    (admin) revokes and forgets the token
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
from ..services import collect, youtube
from .common import audit
from .sources import source_out, youtube_redirect_uri

router = APIRouter(prefix="/api/connectors/youtube", tags=["youtube"])

STATE_COOKIE = "sc_youtube"
STATE_PATH = "/api/connectors/youtube"
STATE_TTL = 600


def _back(error: str | None = None, source_id: int | None = None) -> RedirectResponse:
    query = f"yt_error={quote(error.split(':')[0])}" if error else "yt_connected=1"
    if source_id:
        query += f"&source={source_id}"
    resp = RedirectResponse(f"/admin/sources?{query}", status_code=303)
    resp.delete_cookie(STATE_COOKIE, path=STATE_PATH)
    return resp


def _source(db: Session, source_id: int) -> Source:
    s = db.get(Source, source_id)
    if s is None or s.kind != "youtube":
        raise HTTPException(404, "not_found")
    return s


@router.get("/start")
def start(source: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    s = _source(db, source)
    cfg = s.config or {}
    if not cfg.get("client_id") or not collect.source_secrets(s).get("client_secret"):
        return _back("yt_client_missing", s.id)
    verifier, challenge = youtube.pkce_pair()
    state = secrets.token_urlsafe(24)
    payload = {"s": state, "v": verifier, "id": s.id, "exp": int(time.time()) + STATE_TTL}
    resp = RedirectResponse(youtube.authorize_url(cfg["client_id"], youtube_redirect_uri(), state, challenge), 303)
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
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        payload = json.loads(decrypt_secret(request.cookies.get(STATE_COOKIE, "")) or "{}")
    except ValueError:
        payload = {}
    source_id = payload.get("id")
    if not payload or payload.get("exp", 0) < time.time() or not state or state != payload.get("s"):
        return _back("yt_state_invalid", source_id)
    if error:
        return _back("yt_access_denied" if error == "access_denied" else f"yt_failed: {error}", source_id)
    if not code:
        return _back("yt_failed", source_id)
    s = _source(db, int(source_id))
    try:
        token = youtube.exchange_code(
            (s.config or {}).get("client_id", ""),
            collect.source_secrets(s).get("client_secret", ""),
            code,
            payload["v"],
            youtube_redirect_uri(),
        )
        channel = youtube.connect(db, s, token)
    except ConnectorError as exc:
        return _back(str(exc), s.id)
    audit(db, admin, "sources.youtube_connect", {"id": s.id, "channel": channel.get("channel_id")})
    from ..worker import youtube_soon

    youtube_soon(s.id)
    return _back(None, s.id)


@router.post("/{source_id}/disconnect")
def disconnect(source_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    s = _source(db, source_id)
    youtube.disconnect(db, s)
    audit(db, admin, "sources.youtube_disconnect", {"id": s.id})
    return source_out(db, s)
