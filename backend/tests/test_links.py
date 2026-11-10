from sqlalchemy import select

from stats_collector.services.links import extract_urls, normalize_url


def test_normalize_and_extract():
    n = normalize_url
    assert n("https://www.News.example.org/2026/brug/?utm_source=fb&fbclid=x#top") == "news.example.org/2026/brug"
    assert n("http://news.example.org/2026/brug") == n("https://m.news.example.org/2026/brug/")
    assert n("https://news.example.org/?p=12&utm_medium=social") == "news.example.org?p=12"
    shim = "https://l.facebook.com/l.php?u=https%3A%2F%2Fnews.example.org%2Fa%2F%3Futm_source%3Dfb&h=AT0"
    assert n(shim) == "news.example.org/a"
    assert n("https://www.youtube.com/redirect?q=https%3A%2F%2Fnews.example.org%2Fb&v=1") == "news.example.org/b"
    assert n("") is None and n("not a url") is None
    text = "Read more: https://news.example.org/a. Also (https://news.example.org/b) and https://news.example.org/a"
    assert extract_urls(text, None) == ["https://news.example.org/a", "https://news.example.org/b"]


def _demo():
    from stats_collector.db import session_factory
    from stats_collector.services.demo import create_demo

    with session_factory()() as db:
        assert create_demo(db) > 0


def _items(kind):
    from stats_collector.db import session_factory
    from stats_collector.models import ContentItem

    with session_factory()() as db:
        return {i.external_id: i.id for i in db.execute(select(ContentItem).where(ContentItem.kind == kind)).scalars()}


def test_auto_links_detail_and_editors(admin):
    client, csrf = admin
    _demo()
    articles, posts = _items("article"), _items("post")
    # Demo: the first six Facebook posts share an article, two videos belong to one.
    detail = client.get(f"/api/content/{articles['1000']}?range=90d").json()
    linked = {x["source"]["kind"]: x for x in detail["links"]}
    assert set(linked) == {"facebook", "youtube"} and detail["can_link"]
    assert all(x["method"] == "url" for x in detail["links"])
    fb_post = linked["facebook"]["id"]
    assert client.get(f"/api/content/{fb_post}?range=90d").json()["links"][0]["id"] == articles["1000"]

    # Editors are credited with the numbers of posts that link to their articles.
    eds = client.get("/api/editors?range=90d").json()["editors"]
    social = [e["social"] for e in eds]
    # 14 linked posts and videos (Facebook, YouTube, Bluesky, Mastodon, Threads); six of them link
    # to co-written articles, which both editors get.
    assert sum(s["posts"] for s in social) == 20 and sum(s["views"] for s in social) > 0
    assert {k for s in social for k in s["by_kind"]} == {"facebook", "youtube", "bluesky", "mastodon", "threads"}
    anne = next(e for e in eds if e["name"] == "Anne de Vries")
    via = client.get(f"/api/content/top?range=90d&person={anne['id']}&via=social&sort=published").json()["items"]
    assert via and all(i["source"]["kind"] in ("facebook", "youtube") for i in via)

    # Remove an automatic link: the next automatic run leaves it out. Adding it back makes it manual.
    r = client.delete(f"/api/content/{articles['1000']}/links/{fb_post}", headers=csrf)
    assert r.status_code == 200, r.text
    from stats_collector.db import session_factory
    from stats_collector.services.links import auto_link

    with session_factory()() as db:
        auto_link(db)
    detail = client.get(f"/api/content/{articles['1000']}?range=90d").json()
    assert {x["source"]["kind"] for x in detail["links"]} == {"youtube"}
    assert client.post(f"/api/content/{fb_post}/links", json={"item_id": articles["1000"]}, headers=csrf).json()["ok"]
    with session_factory()() as db:
        auto_link(db)
    detail = client.get(f"/api/content/{articles['1000']}?range=90d").json()
    assert {x["source"]["kind"]: x["method"] for x in detail["links"]}["facebook"] == "manual"

    # Manual link between an Instagram post and an article; two articles cannot be linked.
    ig = posts["demo-ig-0"]
    found = client.get("/api/content/find?q=bakker&side=article").json()
    assert found and "bakker" in found[0]["title"].lower()
    assert client.post(f"/api/content/{ig}/links", json={"item_id": found[0]["id"]}, headers=csrf).status_code == 200
    bad = client.post(f"/api/content/{articles['1000']}/links", json={"item_id": articles["1001"]}, headers=csrf)
    assert bad.status_code == 400 and bad.json()["detail"] == "link_kinds"


def test_link_permissions(admin):
    client, csrf = admin
    _demo()
    articles, posts = _items("article"), _items("post")
    from stats_collector.db import session_factory
    from stats_collector.models import User

    with session_factory()() as db:
        db.execute(select(User)).scalars().first().role = "staff"
        db.commit()
    post = posts["demo-fb-7"]
    assert (
        client.post(f"/api/content/{post}/links", json={"item_id": articles["1002"]}, headers=csrf).status_code == 403
    )
    assert client.get(f"/api/content/{post}?range=30d").json()["can_link"] is False
