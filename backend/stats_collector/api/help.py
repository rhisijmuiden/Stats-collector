"""Serves the user manual bundled with this release (docs/manual/<lang>/*.md)."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from .. import APP_ROOT, build_info
from ..config import get_settings

router = APIRouter(prefix="/api/help", tags=["help"])
MANUAL = APP_ROOT / "docs" / "manual"
SLUG = re.compile(r"^[A-Za-z0-9-]+$")
ORDER = [
    "README",
    "dashboard",
    "dashboards",
    "content",
    "followers-and-goals",
    "installation",
    "reverse-proxy",
    "users-and-roles",
    "branding",
    "email",
    "backup",
    "updates",
    "microsoft-365",
    "owncast-icecast",
    "wordpress",
    "youtube",
    "meta",
    "troubleshooting",
]


def _title(path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def _lang_dir(lang: str):
    d = MANUAL / lang
    return d if d.is_dir() else MANUAL / "en"


def _pages_url(lang: str, slug: str) -> str:
    """URL of the same page in the versioned manual on GitHub Pages (published by the release workflow)."""
    owner, repo = get_settings().github_repo.split("/", 1)
    info = build_info()
    released = re.match(r"^\d+\.\d+\.\d+(-(rc|test)\.\d+)?$", info["version"] or "")
    version = info["version"] if released else ("test" if get_settings().default_channel == "test" else "latest")
    path = "" if slug == "README" else f"{slug}/"
    prefix = "" if lang == "en" else f"{lang}/"
    return f"https://{owner.lower()}.github.io/{repo.lower()}/{version}/{prefix}{path}"


def _github_base() -> str:
    branch = "develop" if (build_info().get("channel") or get_settings().default_channel) == "test" else "main"
    return f"https://github.com/{get_settings().github_repo}/blob/{branch}/docs/manual"


@router.get("")
def index(lang: str = "en") -> dict:
    d = _lang_dir(lang)
    files = sorted(d.glob("*.md"), key=lambda p: (ORDER.index(p.stem) if p.stem in ORDER else len(ORDER), p.stem))
    pages = [{"slug": p.stem, "title": _title(p)} for p in files]
    return {
        "lang": d.name,
        "pages": pages,
        "github": f"{_github_base()}/{d.name}/README.md",
        "pages_url": _pages_url(d.name, "README"),
    }


@router.get("/{slug}")
def page(slug: str, lang: str = "en") -> dict:
    if not SLUG.match(slug):
        raise HTTPException(404, "not_found")
    d = _lang_dir(lang)
    path = d / f"{slug}.md"
    if not path.is_file():
        raise HTTPException(404, "not_found")
    return {
        "slug": slug,
        "title": _title(path),
        "markdown": path.read_text(encoding="utf-8"),
        "github": f"{_github_base()}/{d.name}/{slug}.md",
        "pages_url": _pages_url(d.name, slug),
    }
