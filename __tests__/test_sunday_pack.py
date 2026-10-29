# __tests__/test_sunday_pack.py
#
# ChurchSavvy Planning, step 5: the Sunday pack in the member app
# (sunday_serving.pack / here, member_portal_serving.render_pack; canvas
# board 9). Pins:
#   * only a member's own yes opens a pack: each team they're on that day,
#     when to be there, their team's moments (its notes and everyone's),
#     the songs when their team has notes on them (title, key, parts, never
#     words), and today's order without Before and After
#   * "I'm here" only on the day, from three hours before the call time,
#     once; a place that moves to someone else starts fresh
#   * the page says it in the canvas's words, and the reminders open it

import pathlib
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from test_sunday_planning import (ANA, BIZ, JO, KENDRA, PRODUCTION, WELCOME, ZONE, api, ask, make_team, place,  # noqa: F401
                                  services, sundays, train)
from test_sunday_serving import CHURCH

import member_portal_serving as mps
import sunday_planning as sp
import sunday_serving as ss

SONG = "5c000000-0000-4000-8000-000000000002"


def local(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=ZONE).astimezone(timezone.utc)


@pytest.fixture
def church(api):
    """Oct 25 at 10:30. Production (Sound: Kendra, Jo) arrives at 9:15;
    Welcome (Doors: Ana). One place each at a service. The plan has a Before, songs, a sermon,
    and an After; Production has notes on the songs, Welcome doesn't."""
    db, as_ = api
    db.KEYS = {**db.KEYS, "serve_notes": ("service_id", "item_id", "team")}
    db.t["serve_notes"] = []
    db.t["worship_songs"] = [{"id": SONG, "business_id": BIZ, "title": "Firm Foundation", "song_key": "B",
                              "sections": [{"id": "v1", "label": "V1", "lines": ["(its words)"]}, {"id": "c", "label": "C", "lines": ["(more)"]}],
                              "arrangements": [{"id": "main", "name": "Main", "order": ["v1", "c", "c"]}]}]
    sundays(as_, 3)
    s1, s2, s3 = (s["id"] for s in services(db))
    sound = place(make_team(as_), "Sound")
    doors = place(make_team(as_, gid=WELCOME, places=("Doors",)), "Doors")
    train(as_, sound, [(KENDRA, "trained"), (JO, "trained")])
    train(as_, doors, [(KENDRA, "trained"), (ANA, "trained")])
    as_("owner").patch(f"/planning/teams/{PRODUCTION}", json={"business_id": BIZ, "call_time": "09:15"})
    services(db)[0]["items"] = [
        {"id": "s-b", "kind": "section", "title": "Before"},
        {"id": "pray", "kind": "text", "title": "Prayer with the team", "minutes": 10},
        {"id": "s-m", "kind": "section", "title": "The service"},
        {"id": "ff", "kind": "song", "song_id": SONG, "minutes": 6, "who": "Keisha leads"},
        {"id": "an", "kind": "announcement", "title": "Announcements", "minutes": 4},
        {"id": "sm", "kind": "text", "title": "What Mean These Stones?", "minutes": 40, "who": "Pastor James"},
        {"id": "s-a", "kind": "section", "title": "After"},
        {"id": "bye", "kind": "loop", "title": "Goodbye loop", "minutes": 20},
    ]
    notes = [("pray", "all", "Everyone serving today"), ("ff", PRODUCTION, "Words from verse 1"),
             ("an", WELCOME, "Connect cards out"), ("sm", PRODUCTION, "Point slides on his cue"),
             ("bye", WELCOME, "Coffee is ready")]
    for item, team, note in notes:
        db.t["serve_notes"].append({"business_id": BIZ, "service_id": s1, "item_id": item, "team": team, "note": note})
    a_sound = ask(as_, s1, sound, KENDRA).json()["assignment"]["id"]
    a_doors = ask(as_, s1, doors, ANA).json()["assignment"]["id"]
    ss.answer(CHURCH, KENDRA, a_sound, "yes")
    ss.answer(CHURCH, ANA, a_doors, "yes")
    return db, as_, (s1, s2, s3), sound, doors, a_sound, a_doors


@pytest.fixture
def pages(church, monkeypatch):
    """The member pages' router, signed in as Kendra (as test_sunday_serving)."""
    import member_portal
    import member_portal_church
    import rate_limit
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    state = {"me": {"id": KENDRA, "name": "Kendra Lane"}}

    async def signed_in(request):
        return {"business": CHURCH, "site": None}, state["me"], None

    monkeypatch.setattr(member_portal_church, "_signed_in", signed_in)
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a, **k: True)
    monkeypatch.setattr(member_portal, "_shell", lambda biz, site, title, body, **kw: body)
    app = FastAPI()
    app.include_router(mps.router)
    return TestClient(app), state


def test_the_songs_are_the_bands(church):
    """A team with notes on fewer than half the songs (the booth) gets its
    song note as a moment, not the song list."""
    db, as_, (s1, s2, s3), sound, doors, a_sound, a_doors = church
    svc = services(db)[0]
    at = next(k for k, i in enumerate(svc["items"]) if i["id"] == "ff")
    svc["items"][at + 1:at + 1] = [{"id": "gj", "kind": "song", "song_id": SONG, "minutes": 6},
                                   {"id": "nb", "kind": "song", "song_id": SONG, "minutes": 6},
                                   {"id": "iw", "kind": "song", "song_id": SONG, "minutes": 6}]
    p = ss.pack(CHURCH, KENDRA, a_sound)
    assert p["songs"] == []
    assert "Words from verse 1" in [m["note"] for m in p["moments"]]
    # Half of them (board 9's booth: Firm Foundation and the response) is still the booth's.
    add = lambda item, text: db.t["serve_notes"].append({"business_id": BIZ, "service_id": s1, "item_id": item,
                                                         "team": PRODUCTION, "note": text})
    add("iw", "Lights down for the response")
    assert ss.pack(CHURCH, KENDRA, a_sound)["songs"] == []
    # Most of them: the team's own card, every song in it.
    add("gj", "Keys alone")
    p = ss.pack(CHURCH, KENDRA, a_sound)
    assert [s["n"] for s in p["songs"]] == [1, 2, 3, 4] and "Words from verse 1" not in [m["note"] for m in p["moments"]]


def test_the_pack_is_theirs_and_says_their_sunday(church):
    db, as_, (s1, s2, s3), sound, doors, a_sound, a_doors = church
    p = ss.pack(CHURCH, KENDRA, a_sound)
    assert [r["team"] for r in p["roles"]] == ["Production"]
    assert (p["role"]["team"], p["role"]["place"], p["role"]["call"]) == ("Production", "Sound", "09:15")
    # Production has notes on the songs: the songs, with key and parts, never words.
    assert p["songs"] == [{"n": 1, "title": "Firm Foundation", "key": "B", "parts": ["V1", "C", "C"],
                           "who": "Keisha leads", "note": "Words from verse 1"}]
    assert "(its words)" not in str(p)
    # Their moments: everyone's and Production's, songs left to the songs.
    assert [(m["time"], m["note"]) for m in p["moments"]] == [("10:20", "Everyone serving today"), ("10:40", "Point slides on his cue")]
    # Today's order is the service, without Before and After.
    assert [o["title"] for o in p["order"]] == ["Firm Foundation", "Announcements", "What Mean These Stones?"]
    assert p["here_open"] is False and p["past"] is False
    # As Welcome: no song notes, so no songs; its own moments.
    w = ss.pack(CHURCH, ANA, a_doors)
    assert w["songs"] == [] and [m["note"] for m in w["moments"]] == ["Everyone serving today", "Connect cards out", "Coffee is ready"]


def test_only_their_own_yes(church):
    db, as_, (s1, s2, s3), sound, doors, a_sound, a_doors = church
    with pytest.raises(Exception) as e:
        ss.pack(CHURCH, JO, a_sound)
    assert getattr(e.value, "status_code", None) == 404
    asked = ask(as_, s2, sound, KENDRA).json()["assignment"]["id"]
    with pytest.raises(Exception) as e:
        ss.pack(CHURCH, KENDRA, asked)
    assert getattr(e.value, "status_code", None) == 404


def test_im_here_on_the_day_once(church, monkeypatch):
    db, as_, (s1, s2, s3), sound, doors, a_sound, a_doors = church
    row = lambda a: next(r for r in db.t["serve_assignments"] if r["id"] == a)
    with pytest.raises(Exception) as e:
        ss.here(CHURCH, KENDRA, a_sound)
    assert getattr(e.value, "status_code", None) == 409 and row(a_sound)["here_at"] is None
    # Sunday, 6:00: still more than three hours before the 9:15 call.
    monkeypatch.setattr(sp, "_now", lambda: local(2026, 10, 25, 6, 0))
    with pytest.raises(Exception):
        ss.here(CHURCH, KENDRA, a_sound)
    monkeypatch.setattr(sp, "_now", lambda: local(2026, 10, 25, 8, 50))
    assert ss.pack(CHURCH, KENDRA, a_sound)["here_open"] is True
    ss.here(CHURCH, KENDRA, a_sound)
    first = row(a_sound)["here_at"]
    assert first and ss.pack(CHURCH, KENDRA, a_sound)["role"]["here"] is True
    # Once: a second tap keeps the first time; Ana is still to tap.
    monkeypatch.setattr(sp, "_now", lambda: local(2026, 10, 25, 9, 5))
    ss.here(CHURCH, KENDRA, a_sound)
    assert row(a_sound)["here_at"] == first and row(a_doors)["here_at"] is None
    # After the service it's closed again.
    monkeypatch.setattr(sp, "_now", lambda: local(2026, 10, 25, 14, 0))
    assert ss.pack(CHURCH, KENDRA, a_sound)["past"] is True
    with pytest.raises(Exception):
        ss.here(CHURCH, ANA, a_doors)


def test_a_place_that_moves_starts_fresh(church, monkeypatch):
    db, as_, (s1, s2, s3), sound, doors, a_sound, a_doors = church
    row = lambda a: next(r for r in db.t["serve_assignments"] if r["id"] == a)
    row(a_sound)["here_at"] = "2026-10-25T13:50:00+00:00"
    ss.ask_sub(CHURCH, KENDRA, a_sound, JO)
    ss.answer(CHURCH, JO, a_sound, "yes")
    assert row(a_sound)["contact_id"] == JO and row(a_sound)["here_at"] is None


def test_the_page_and_its_form(church, pages):
    from starlette.requests import Request
    client, state = pages
    a_sound = church[5]
    req = Request({"type": "http", "query_string": b"", "headers": []})
    html = mps.render_pack(CHURCH, None, req, state["me"], ss.pack(CHURCH, KENDRA, a_sound))
    for words in ("Sunday, October 25 · 10:30 AM", "Kendra, here&#x27;s your Sunday", "Be there by 9:15", "Sound · Production",
                  "The songs", "1 song", "Firm Foundation", "Words from verse 1", "<i>V1</i>", "Your moments", "Production only",
                  "Point slides on his cue", "Today&#x27;s order", "Production&#x27;s group"):
        assert words in html, words
    assert "(its words)" not in html and "I&#x27;m here" not in html, "the button waits for the day"
    # Before the day the form says why and saves nothing.
    r = client.post("/my/serving/here", data={"id": a_sound}, follow_redirects=False)
    assert r.headers["location"].startswith(f"/my/serving/{a_sound}/pack?err=said&msg=")
    assert next(x for x in church[0].t["serve_assignments"] if x["id"] == a_sound)["here_at"] is None


def test_on_the_day_the_form_answers(church, pages, monkeypatch):
    from starlette.requests import Request
    client, state = pages
    a_sound = church[5]
    req = Request({"type": "http", "query_string": b"", "headers": []})
    monkeypatch.setattr(sp, "_now", lambda: local(2026, 10, 25, 8, 50))
    assert "I&#x27;m here" in mps.render_pack(CHURCH, None, req, state["me"], ss.pack(CHURCH, KENDRA, a_sound))
    r = client.post("/my/serving/here", data={"id": a_sound}, follow_redirects=False)
    assert r.headers["location"] == f"/my/serving/{a_sound}/pack?done=here"
    html = mps.render_pack(CHURCH, None, req, state["me"], ss.pack(CHURCH, KENDRA, a_sound))
    assert "You're here. Thank you!" in html and "sees you on the list." in html
