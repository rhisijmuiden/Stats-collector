from stats_collector.services import updates

BODY = """### Added
- Info button with update check
  NL: Info-knop
- Dutch translation
  of every screen
### Changed
- Menu moved left
### Removed
- Old page
  NL: Oude pagina
"""


def _gh(tag, pre, body=BODY, assets=True):
    v = tag.lstrip("v")
    return {
        "tag_name": tag,
        "prerelease": pre,
        "draft": False,
        "name": tag,
        "body": body,
        "html_url": "u",
        "published_at": "2026-11-10T10:00:00Z",
        "assets": [
            {"name": f"stats-collector-{v}.tar.gz", "browser_download_url": f"https://x/{v}.tgz"},
            {"name": f"stats-collector-{v}.tar.gz.sha256", "browser_download_url": f"https://x/{v}.sha"},
        ]
        if assets
        else [],
    }


def test_parse_notes_sections_and_languages():
    notes = updates.split_languages(BODY)
    assert notes["en"]["added"] == ["Info button with update check", "Dutch translation of every screen"]
    assert notes["en"]["changed"] == ["Menu moved left"]
    assert notes["en"]["removed"] == ["Old page"]
    assert notes["nl"]["added"] == ["Info-knop", "Dutch translation of every screen"]
    assert notes["nl"]["removed"] == ["Oude pagina"] and notes["nl"]["changed"] == ["Menu moved left"]


def test_dutch_falls_back_to_english():
    notes = updates.split_languages("### Fixed\n- bug")
    assert notes["nl"]["fixed"] == ["bug"]


def test_channels_and_check(monkeypatch):
    rels = [
        updates.release_from_github(i)
        for i in (
            _gh("v0.1.0", False),
            _gh("v0.2.0-rc.3", True),
            _gh("v0.2.0-rc.4", True, assets=False),
            _gh("nonsense", False),
        )
    ]
    rels = [r for r in rels if r]
    assert len(rels) == 3
    monkeypatch.setattr(updates, "build_info", lambda: {"version": "0.1.0"})
    prod = updates.check("production", rels)
    assert prod["update_available"] is False and prod["latest"]["version"] == "0.1.0"
    test = updates.check("test", sorted(rels, key=lambda r: updates.parse_version(r.version), reverse=True))
    assert test["update_available"] is True and test["latest"]["version"] == "0.2.0-rc.3"  # rc.4 has no asset
