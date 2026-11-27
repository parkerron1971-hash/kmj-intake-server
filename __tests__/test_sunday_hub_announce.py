"""The one Sunday hub: an announcement typed once, in two places
(worship_announce_router, church_news; M-7, Kevin's decisions
church-office-1, 2026-11-27).

Pins:
  * "Also post to News" on a screens announcement posts it to News by News's
    own route: the post says when and where, and is paired with the
    announcement; asked again, the same post comes back (never two)
  * "Also show on the screens" on a News post puts it on the board by the
    board's own route, paired the other way
  * each side keeps its own permission: someone who may change the screens
    but not post News gets the announcement and a plain refusal; someone
    who may post News but not plan Sunday gets the post and a refusal
  * the board's list says each announcement's News post
  * with the switch off, neither is asked (no `news`, no `screens`)"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import church_news  # noqa: E402
import kids_router  # noqa: E402
import worship_announce_router as war  # noqa: E402
from sunday_hub_fixture import BIZ, SEATS, church  # noqa: E402,F401


@pytest.fixture
def boards(church, monkeypatch):
    church.app.include_router(war.router)
    church.app.include_router(church_news.router)
    church.db.t["worship_announcements"] = []
    church.db.t["church_posts"] = []
    monkeypatch.setattr(kids_router, "role_for", lambda biz, user: SEATS.get(str(user.id)) if biz == BIZ else None)
    import news_alerts
    monkeypatch.setattr(news_alerts, "alert_later", lambda business, row: None)
    monkeypatch.setattr(church_news, "comments_open", lambda business: True)
    return church


def _announce(c, who, **extra):
    return c.as_(who).post("/worship/announcements", json={
        "business_id": BIZ, "title": "Community Day", "when": "Sat 11 AM", "where": "The church lawn",
        "body": "Food, games and school supplies.", "event_on": "2026-10-31",
        "shows": {"room": True, "lobby": True}, **extra})


def _post(c, who, **extra):
    return c.as_(who).post("/church/news", json={"business_id": BIZ, "title": "Baptism Sunday",
                                                 "body": "Sign up by next week.", **extra})


def test_also_post_to_news(boards):
    r = _announce(boards, "planner", also_news=True)
    assert r.status_code == 200, r.text
    ann, news = r.json()["announcement"], r.json()["news"]
    post = next(p for p in boards.db.t["church_posts"] if p["id"] == news["post_id"])
    assert post["kind"] == "announcement" and post["title"] == "Community Day"
    assert post["body"] == "Sat 11 AM · The church lawn\nFood, games and school supplies."
    assert post["screen_announcement_id"] == ann["id"] and post["source"] == "office"
    # Asked again (a change saved with the box still ticked): the same post.
    again = boards.as_("planner").put(f"/worship/announcements/{ann['id']}",
                                      json={"business_id": BIZ, "title": "Community Day!", "also_news": True})
    assert again.json()["news"] == news and len(boards.db.t["church_posts"]) == 1
    listed = boards.as_("planner").get("/worship/announcements", params={"business_id": BIZ}).json()["announcements"]
    assert [a["news_post_id"] for a in listed] == [news["post_id"]]


def test_screens_but_not_news_gets_a_refusal(boards):
    # The Worship part plans (and so changes the screens) but holds no seat to post News.
    r = _announce(boards, "worship", also_news=True)
    assert r.status_code == 200 and r.json()["news"] == {"refused": war.NEWS_REFUSED}
    assert boards.db.t["church_posts"] == [] and len(boards.db.t["worship_announcements"]) == 1


def test_also_show_on_the_screens(boards):
    r = _post(boards, "planner", also_screens=True)
    assert r.status_code == 200, r.text
    aid, pid = r.json()["screens"]["announcement_id"], r.json()["post_id"]
    ann = next(a for a in boards.db.t["worship_announcements"] if a["id"] == aid)
    assert ann["title"] == "Baptism Sunday" and ann["source"] == "news" and ann["source_ref"] == pid
    listed = boards.as_("planner").get("/worship/announcements", params={"business_id": BIZ}).json()["announcements"]
    assert [a["news_post_id"] for a in listed] == [pid]
    # Ticked on the board later: the post it came from, not a second one.
    again = boards.as_("planner").put(f"/worship/announcements/{aid}", json={"business_id": BIZ, "also_news": True})
    assert again.json()["news"] == {"post_id": pid} and len(boards.db.t["church_posts"]) == 1


def test_news_but_not_the_screens_gets_a_refusal(boards):
    r = _post(boards, "carer", also_screens=True)                 # a Manager who doesn't plan Sunday
    assert r.status_code == 200 and r.json()["screens"] == {"refused": church_news.SCREENS_REFUSED}
    assert len(boards.db.t["church_posts"]) == 1 and boards.db.t["worship_announcements"] == []


def test_off_neither_is_asked(boards, monkeypatch):
    monkeypatch.setenv("SUNDAY_HUB", "off")
    r = _announce(boards, "planner", also_news=True)
    assert r.status_code == 200 and "news" not in r.json() and boards.db.t["church_posts"] == []
    r = _post(boards, "planner", also_screens=True)
    assert r.status_code == 200 and "screens" not in r.json() and len(boards.db.t["worship_announcements"]) == 1
    listed = boards.as_("planner").get("/worship/announcements", params={"business_id": BIZ}).json()["announcements"]
    assert all("news_post_id" not in a for a in listed)
