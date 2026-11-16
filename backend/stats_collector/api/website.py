"""Website overview (WordPress plugin): readers now, searches, campaigns, scroll depth, production and
what kind of article does well.

GET /api/website?range=&source=   everyone; editor names only for Admin and Editor-in-chief
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..security import current_user
from ..services import website as svc
from .content import SEES_ALL, Range, period

router = APIRouter(prefix="/api", tags=["website"])


@router.get("/website")
def website(
    range: Range = "7d",
    source: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    start, end, _, _ = period(db, range)
    data = svc.overview(db, start, end, source, show_people=user.role in SEES_ALL)
    return {"range": range, "start": start.isoformat(), "end": end.isoformat(), **data}
