"""Wall Designer: what a live wall shows, as screens of blocks on a 12 x 8 grid.

A design is a list of screens that take turns on the TV. Each screen has a name, a time on screen,
a background and blocks. A block sits on the grid (x, y, w, h in cells) and has a type and settings:

  header   wall title, live dot and clock
  kpi      one big figure (live audience, views, interactions or followers) with a trend
  tiles    a tile per channel (or glow bars, or a list)
  chart    line, area, bars or donut per channel
  race     today's best items racing by views
  goals    progress to the goals marked for the walls
  risers   items that gained most views in the last hour
  ticker   a scrolling line with the best items
  msg      your own text

`channels` is a list of source ids; empty means every channel of the wall. A wall without a design
of its own (design is None) shows the standard screens chosen with `layout`, built from the same
blocks (see `standard`), so the wall page has one way of drawing.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

COLS, ROWS = 12, 8
TYPES = ("header", "kpi", "tiles", "chart", "race", "goals", "risers", "ticker", "msg")
VIZ: dict[str, tuple[str, ...]] = {
    "header": ("",),
    "kpi": ("numline", "number", "gauge"),
    "tiles": ("tiles", "bars3d", "list"),
    "chart": ("area", "line", "bars", "donut"),
    "race": ("race", "list"),
    "goals": ("bar", "rings"),
    "risers": ("",),
    "ticker": ("",),
    "msg": ("",),
}
COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
MAX_VERSIONS = 30


class Block(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    type: Literal["header", "kpi", "tiles", "chart", "race", "goals", "risers", "ticker", "msg"]
    x: int = Field(ge=0, lt=COLS)
    y: int = Field(ge=0, lt=ROWS)
    w: int = Field(ge=1, le=COLS)
    h: int = Field(ge=1, le=ROWS)
    title: str = Field(default="", max_length=120)
    metric: Literal["live", "views", "interactions", "followers"] = "views"
    channels: list[int] = Field(default_factory=list, max_length=50)
    period: Literal["hour", "today", "7d", "30d"] = "today"
    viz: str = Field(default="", max_length=16)
    color: str = Field(default="auto", max_length=7)
    trend: bool = True
    countup: bool = True
    editors: bool = True
    rows: int = Field(default=8, ge=1, le=10)
    text: str = Field(default="", max_length=200)
    sub: str = Field(default="", max_length=300)

    @field_validator("color")
    @classmethod
    def _color(cls, v: str) -> str:
        if v != "auto" and not COLOR.match(v):
            raise ValueError("invalid_color")
        return v

    @model_validator(mode="after")
    def _fit(self) -> Block:
        if self.x + self.w > COLS or self.y + self.h > ROWS:
            raise ValueError("block_outside_grid")
        if self.viz not in VIZ[self.type]:
            self.viz = VIZ[self.type][0]
        return self


class Screen(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=60)
    seconds: int = Field(default=30, ge=10, le=300)
    background: Literal["neon", "aurora", "plain"] = "neon"
    blocks: list[Block] = Field(default_factory=list, max_length=40)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not KEY.match(v):
            raise ValueError("invalid_screen_key")
        return v


class Design(BaseModel):
    screens: list[Screen] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def _unique(self) -> Design:
        if len({s.id for s in self.screens}) != len(self.screens):
            raise ValueError("duplicate_screen_key")
        return self


def _b(id_: str, type_: str, x: int, y: int, w: int, h: int, **kw) -> dict:
    return Block(id=id_, type=type_, x=x, y=y, w=w, h=h, **kw).model_dump()  # type: ignore[arg-type]


def overview_screen(seconds: int = 30) -> dict:
    """Neon pulse: three big numbers, a tile per channel and a ticker with the best items."""
    return {
        "id": "overview",
        "name": "Overview",
        "seconds": seconds,
        "background": "neon",
        "blocks": [
            _b("header", "header", 0, 0, 12, 1),
            _b("live", "kpi", 0, 1, 4, 2, metric="live", period="hour"),
            _b("views", "kpi", 4, 1, 4, 2, metric="views"),
            _b("inter", "kpi", 8, 1, 4, 2, metric="interactions"),
            _b("tiles", "tiles", 0, 3, 12, 4),
            _b("ticker", "ticker", 0, 7, 12, 1),
        ],
    }


def stories_screen(seconds: int = 30, editors: bool = True) -> dict:
    """Story race: today's best items in a race, views today, rising fastest and the goals."""
    return {
        "id": "stories",
        "name": "Top stories",
        "seconds": seconds,
        "background": "neon",
        "blocks": [
            _b("header", "header", 0, 0, 12, 1),
            _b("race", "race", 0, 1, 8, 7, editors=editors),
            _b("views", "kpi", 8, 1, 4, 2, metric="views", viz="number"),
            _b("risers", "risers", 8, 3, 4, 2, rows=4),
            _b("goals", "goals", 8, 5, 4, 3, rows=3),
        ],
    }


def standard(layout: str, seconds: int = 30, editors: bool = True) -> dict:
    """The screens a wall shows without a design of its own."""
    screens = {
        "overview": [overview_screen(seconds)],
        "stories": [stories_screen(seconds, editors)],
    }.get(layout, [overview_screen(seconds), stories_screen(seconds, editors)])
    return {"screens": screens}


def templates() -> dict:
    return {"overview": overview_screen(), "stories": stories_screen()}


def effective(wall) -> dict:
    """The design the TVs show: the wall's own, else the standard screens."""
    if wall.design:
        try:
            return Design.model_validate(wall.design).model_dump()
        except ValueError:  # an old or broken design must not take the wall down
            pass
    return standard(wall.layout or "rotate", int(wall.rotate_seconds or 30), bool(wall.show_authors))
