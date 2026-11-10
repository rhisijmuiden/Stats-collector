"""Receives signed batches from the Stats Collector WordPress plugin (see services/wordpress.py)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import wordpress

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


@router.post("/wordpress")
async def wordpress_ingest(request: Request, db: Session = Depends(get_db)):
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > wordpress.MAX_BODY:
        return JSONResponse({"ok": False, "error": "too_large"}, status_code=413)
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > wordpress.MAX_BODY:
            return JSONResponse({"ok": False, "error": "too_large"}, status_code=413)
    try:
        source = wordpress.authenticate(
            db,
            request.headers.get("x-sc-key"),
            request.headers.get("x-sc-timestamp"),
            request.headers.get("x-sc-signature"),
            body,
        )
        try:
            payload = json.loads(body or b"{}")
        except ValueError as exc:
            raise wordpress.IngestError("bad_json") from exc
        return wordpress.ingest(db, source, payload)
    except wordpress.IngestError as exc:
        db.rollback()
        return JSONResponse({"ok": False, "error": exc.code}, status_code=exc.status)
