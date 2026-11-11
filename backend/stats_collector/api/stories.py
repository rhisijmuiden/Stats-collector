"""Stories followed over every channel.

GET    /api/stories                everyone: stories with totals per channel
POST   /api/stories                admin, editor-in-chief, editor
GET    /api/stories/{id}           everyone: items, radio slots, totals and a line per channel
PUT    /api/stories/{id}           admin, editor-in-chief, editor
DELETE /api/stories/{id}           admin, editor-in-chief, editor
GET    /api/stories/streams        everyone: radio and stream sources for radio slots

Editor names are left out for staff, as under Content.
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ContentItem, Source, Story, User
from ..security import current_user, require_role
from ..services import stories as svc
from .common import audit

router = APIRouter(prefix="/api", tags=["stories"])
can_edit = require_role("admin", "editor_in_chief", "editor")


class RadioSlot(BaseModel):
    source_id: int
    start: datetime
    end: datetime
    label: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _order(self):
        if self.end <= self.start:
            raise ValueError("end_before_start")
        return self


class StoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    item_ids: list[int] = Field(default_factory=list, max_length=500)
    excluded_ids: list[int] = Field(default_factory=list, max_length=500)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    radio: list[RadioSlot] = Field(default_factory=list, max_length=50)
    start_date: date
    end_date: date | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_before_start")
        self.keywords = [k.strip()[:100] for k in self.keywords if k.strip() and len(k.strip()) >= 3]
        return self


def _get(db: Session, story_id: int) -> Story:
    story = db.get(Story, story_id)
    if story is None:
        raise HTTPException(404, "not_found")
    return story


def _apply(db: Session, story: Story, body: StoryIn) -> None:
    ids = set(body.item_ids) | set(body.excluded_ids)
    if ids and len(set(db.execute(select(ContentItem.id).where(ContentItem.id.in_(ids))).scalars())) != len(ids):
        raise HTTPException(400, "unknown_item")
    streams = {s.id for s in db.execute(select(Source).where(Source.kind.in_(("icecast", "owncast")))).scalars()}
    if any(r.source_id not in streams for r in body.radio):
        raise HTTPException(400, "unknown_source")
    story.name = body.name
    story.description = body.description
    story.item_ids = list(dict.fromkeys(body.item_ids))
    story.excluded_ids = list(dict.fromkeys(body.excluded_ids))
    story.keywords = body.keywords
    story.radio = [
        {"source_id": r.source_id, "start": r.start.isoformat(), "end": r.end.isoformat(), "label": r.label}
        for r in body.radio
    ]
    story.start_date = body.start_date
    story.end_date = body.end_date


@router.get("/stories")
def list_stories(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    rows = db.execute(select(Story).order_by(Story.start_date.desc(), Story.id.desc())).scalars()
    return [svc.card(db, s) for s in rows]


@router.get("/stories/streams")
def streams(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    rows = db.execute(select(Source).where(Source.kind.in_(("icecast", "owncast"))).order_by(Source.name)).scalars()
    return [{"id": s.id, "name": s.name, "kind": s.kind} for s in rows]


@router.post("/stories")
def create_story(body: StoryIn, db: Session = Depends(get_db), user: User = Depends(can_edit)) -> dict:
    story = Story(created_by=user.id)
    _apply(db, story, body)
    db.add(story)
    db.commit()
    audit(db, user, "stories.create", {"id": story.id, "name": story.name})
    return svc.detail(db, story, authors=user.role != "staff")


@router.get("/stories/{story_id}")
def get_story(story_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    return svc.detail(db, _get(db, story_id), authors=user.role != "staff")


@router.put("/stories/{story_id}")
def update_story(story_id: int, body: StoryIn, db: Session = Depends(get_db), user: User = Depends(can_edit)) -> dict:
    story = _get(db, story_id)
    _apply(db, story, body)
    db.commit()
    audit(db, user, "stories.update", {"id": story.id})
    return svc.detail(db, story, authors=user.role != "staff")


@router.delete("/stories/{story_id}")
def delete_story(story_id: int, db: Session = Depends(get_db), user: User = Depends(can_edit)) -> dict:
    story = _get(db, story_id)
    db.delete(story)
    db.commit()
    audit(db, user, "stories.delete", {"id": story_id})
    return {"ok": True}
