# __tests__/test_sunday_serving.py
#
# ChurchSavvy Planning, the member's side (sunday_serving.py,
# member_portal_serving.py). Pins:
#   * My serving shows a member only their own: asks to them, cover requests
#     to them, their coming Sundays, places offered to their team that
#     they're trained for and free for, their away days and their wish
#   * an answer: yes puts them on; can't opens the place and keeps why;
#     "I can do Nov 8" offers the next Sunday they're free; another member's
#     ask, or a Sunday that has passed, is refused
#   * an offered place: the first yes takes it, someone not trained can't
#   * a sub: only someone on the team who knows the place and is free; the
#     member stays on until the sub says yes, then the place is the sub's;
#     a no leaves it with the member; or they just tell the leader
#   * away days and how often are theirs alone, checked, and the office sees
#     the wish and the cover request
#   * the owner's preview shows the pages and saves nothing
#   * a volunteer is never a seat

import pathlib
import sys
import uuid as uuidlib

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import test_sunday_planning as tsp
from test_sunday_planning import (ANA, BIZ, JO, KENDRA, LEE, NOW, PRODUCTION, TY, api, ask, make_team, place,  # noqa: F401
                                  services, sundays, train)

import member_portal_serving as mps
import sunday_planning as sp
import sunday_serving as ss

CHURCH = {"id": BIZ, "name": "Love City Church", "settings": {}}


@pytest.fixture
def church(api):
    """Production on three Sundays (10/25, 11/1, 11/8): Sound (Kendra and Jo
    trained, Ty learning) and Slides (Ana trained)."""
    db, as_ = api
    sundays(as_, 3)
    s1, s2, s3 = (s["id"] for s in services(db))
    team = make_team(as_)
    sound, slides = place(team, "Sound"), place(team, "Slides")
    train(as_, sound, [(KENDRA, "trained"), (JO, "trained"), (TY, "learning")])
    train(as_, slides, [(ANA, "trained")])
    return db, as_, (s1, s2, s3), sound, slides


def row(db, aid):
    return next(r for r in db.t["serve_assignments"] if r["id"] == aid)


def test_my_serving_is_mine(church):
    db, as_, (s1, s2, s3), sound, slides = church
    a1 = ask(as_, s1, sound, KENDRA).json()["assignment"]["id"]
    a2 = ask(as_, s2, sound, KENDRA).json()["assignment"]["id"]
    ask(as_, s1, slides, ANA)
    as_("owner").post(f"/planning/assignments/{a2}/answer", json={"business_id": BIZ, "status": "yes"})
    offered = as_("owner").post("/planning/offer", json={"business_id": BIZ, "service_id": s3, "position_id": sound}).json()
    m = ss.mine(CHURCH, KENDRA)
    assert [a["id"] for a in m["asks"]] == [a1]
    assert [c["id"] for c in m["coming"]] == [a2]
    assert [o["id"] for o in m["open"]] == [offered["assignment"]["id"]]
    assert m["teams"] == [{"group_id": PRODUCTION, "name": "Production", "places": ["Sound"]}]
    assert m["asks"][0]["place"] == "Sound" and m["asks"][0]["team"] == "Production"
    # Ty is only learning Sound, so the offer isn't his; Ana's ask isn't Kendra's.
    assert ss.mine(CHURCH, TY)["open"] == []
    assert [a["place"] for a in ss.mine(CHURCH, ANA)["asks"]] == ["Slides"]
    # Someone on no Sunday team, asked nothing, has no My serving.
    assert ss.mine(CHURCH, LEE) is None and ss.serves(CHURCH, LEE) is False
    assert ss.serves(CHURCH, KENDRA) is True
    assert [w["id"] for w in ss.waiting(CHURCH, KENDRA)] == [a1]
    assert db.t["business_users"] == []


def test_answering_an_ask(church):
    db, as_, (s1, s2, s3), sound, _ = church
    aid = ask(as_, s1, sound, KENDRA).json()["assignment"]["id"]
    ss.answer(CHURCH, KENDRA, aid, "yes")
    assert row(db, aid)["status"] == "yes" and row(db, aid)["answered_at"]
    # Changing their answer: can't, and why (only the office sees it).
    ss.answer(CHURCH, KENDRA, aid, "no")
    ss.set_why(CHURCH, KENDRA, aid, "Working")
    assert (row(db, aid)["status"], row(db, aid)["note"]) == ("no", "Working")
    with pytest.raises(HTTPException) as e:
        ss.answer(CHURCH, JO, aid, "yes")          # not Jo's
    assert e.value.status_code == 404 and row(db, aid)["contact_id"] == KENDRA
    with pytest.raises(HTTPException) as e:
        ss.answer(CHURCH, KENDRA, aid, "maybe")
    assert e.value.status_code == 400
    # "I can't, but I can do Nov 1": the next Sunday they're free.
    aid2 = ask(as_, s2, sound, JO).json()["assignment"]["id"]
    v = ss.ask_view(CHURCH, JO, aid2)
    assert v["can_do"] and v["can_do"]["id"] == s3
    ss.answer(CHURCH, JO, aid2, "other")
    assert row(db, aid2)["note"] == "Can do Nov 8"
    ss.set_why(CHURCH, JO, aid2, "Away")
    assert row(db, aid2)["note"] == "Can do Nov 8 · Away"


def test_a_sunday_that_passed_is_refused(church, monkeypatch):
    db, as_, (s1, s2, s3), sound, _ = church
    aid = ask(as_, s1, sound, KENDRA).json()["assignment"]["id"]
    from datetime import timedelta
    monkeypatch.setattr(sp, "_now", lambda: NOW + timedelta(days=5))
    with pytest.raises(HTTPException) as e:
        ss.answer(CHURCH, KENDRA, aid, "yes")
    assert e.value.status_code == 409 and "passed" in e.value.detail


def test_on_with_you_and_the_offer(church):
    db, as_, (s1, s2, s3), sound, slides = church
    aid = ask(as_, s1, sound, KENDRA).json()["assignment"]["id"]
    ask(as_, s1, slides, ANA)
    v = ss.ask_view(CHURCH, KENDRA, aid)
    assert (v["place"], v["team"], v["status"]) == ("Sound", "Production", "asked")
    assert v["with"] == [{"name": "Ana Cruz", "place": "Slides", "status": "asked"}]
    # The offer: the first yes takes it; not trained, or the second, can't.
    off = as_("owner").post("/planning/offer", json={"business_id": BIZ, "service_id": s2, "position_id": sound}).json()["assignment"]["id"]
    with pytest.raises(HTTPException):
        ss.take(CHURCH, TY, off)
    ss.take(CHURCH, JO, off)
    assert (row(db, off)["contact_id"], row(db, off)["status"]) == (JO, "yes")
    with pytest.raises(HTTPException) as e:
        ss.take(CHURCH, KENDRA, off)
    assert e.value.status_code == 409 and "already took" in e.value.detail


def test_a_sub_covers_only_when_they_say_yes(church):
    db, as_, (s1, s2, s3), sound, _ = church
    aid = ask(as_, s2, sound, KENDRA).json()["assignment"]["id"]
    ss.answer(CHURCH, KENDRA, aid, "yes")
    tsp.away(db, JO, "2026-11-01", "2026-11-01")
    subs = {c["name"]: c for c in ss.subs(CHURCH, KENDRA, aid)}
    # Jo knows Sound but is away; Ty is learning it and free; Ana doesn't know it.
    assert set(subs) == {"Jo Park", "Ty Brooks"} and subs["Jo Park"]["ok"] is False and subs["Ty Brooks"]["ok"] is True
    with pytest.raises(HTTPException):
        ss.ask_sub(CHURCH, KENDRA, aid, JO)
    with pytest.raises(HTTPException):
        ss.ask_sub(CHURCH, KENDRA, aid, ANA)
    ss.ask_sub(CHURCH, KENDRA, aid, TY)
    assert (row(db, aid)["contact_id"], row(db, aid)["swap_to"]) == (KENDRA, TY)
    # Ty sees it to answer; the office sees who was asked to cover.
    assert [a["from"] for a in ss.mine(CHURCH, TY)["asks"]] == ["Kendra Lane"]
    sched = as_("owner").get(f"/planning/schedule?business_id={BIZ}&weeks=3").json()
    assert next(a for a in sched["assignments"] if a["id"] == aid)["swap_name"] == "Ty Brooks"
    # A no leaves Kendra on.
    ss.answer(CHURCH, TY, aid, "no")
    assert (row(db, aid)["contact_id"], row(db, aid)["swap_to"], row(db, aid)["status"]) == (KENDRA, None, "yes")
    # Asked again, a yes makes it Ty's.
    ss.ask_sub(CHURCH, KENDRA, aid, TY)
    ss.answer(CHURCH, TY, aid, "yes")
    r = row(db, aid)
    assert (r["contact_id"], r["status"], r["swap_to"], r["note"]) == (TY, "yes", None, "Covering for Kendra")
    assert ss.mine(CHURCH, KENDRA)["coming"] == []


def test_stop_asking_and_just_tell_the_leader(church):
    db, as_, (s1, s2, s3), sound, _ = church
    aid = ask(as_, s2, sound, KENDRA).json()["assignment"]["id"]
    ss.answer(CHURCH, KENDRA, aid, "yes")
    ss.ask_sub(CHURCH, KENDRA, aid, TY)
    ss.stop_sub(CHURCH, KENDRA, aid)
    assert row(db, aid)["swap_to"] is None and ss.mine(CHURCH, TY)["asks"] == []
    ss.cant_make_it(CHURCH, KENDRA, aid)
    assert (row(db, aid)["status"], row(db, aid)["note"]) == ("no", "Can't make it")


def test_away_days_and_how_often(church):
    db, as_, *_ = church
    ss.add_away(CHURCH, KENDRA, "2026-11-26", "2026-11-29")
    for bad in (("2026-11-29", "2026-11-26"), ("2026-10-01", "2026-10-02"), ("someday", "")):
        with pytest.raises(HTTPException):
            ss.add_away(CHURCH, KENDRA, *bad)
    m = ss.mine(CHURCH, KENDRA)
    assert [(a["starts_on"], a["ends_on"]) for a in m["away"]] == [("2026-11-26", "2026-11-29")]
    # Only their own comes off.
    ss.drop_away(CHURCH, JO, m["away"][0]["id"])
    assert len(db.t["serve_away"]) == 1
    ss.drop_away(CHURCH, KENDRA, m["away"][0]["id"])
    assert db.t["serve_away"] == []
    ss.set_often(CHURCH, KENDRA, "two")
    ss.set_often(CHURCH, KENDRA, "one")
    assert [(p["contact_id"], p["often"]) for p in db.t["serve_prefs"]] == [(KENDRA, "one")]
    with pytest.raises(HTTPException):
        ss.set_often(CHURCH, KENDRA, "always")
    # The office sees the wish beside the person.
    team = as_("owner").get(f"/planning/teams?business_id={BIZ}").json()["teams"][0]
    assert {p["name"]: p["often"] for p in team["people"]}["Kendra Lane"] == "one"


def test_the_switch_hides_it(church, monkeypatch):
    db, as_, (s1, s2, s3), sound, _ = church
    ask(as_, s1, sound, KENDRA)
    monkeypatch.setenv("SUNDAY_PLANNING", "off")
    assert ss.waiting(CHURCH, KENDRA) == [] and ss.serves(CHURCH, KENDRA) is False


# ─── the pages and their forms ───────────────────────────────────────


@pytest.fixture
def pages(church, monkeypatch):
    import member_portal
    import member_portal_church
    import rate_limit
    db, as_, svc, sound, slides = church
    state = {"me": {"id": KENDRA, "name": "Kendra Lane"}, "unavailable": None}

    async def signed_in(request):
        return {"business": CHURCH, "site": None}, (None if state["unavailable"] else state["me"]), state["unavailable"]

    monkeypatch.setattr(member_portal_church, "_signed_in", signed_in)
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a, **k: True)
    monkeypatch.setattr(member_portal, "_shell", lambda biz, site, title, body, **kw: body)
    app = FastAPI()
    app.include_router(mps.router)
    return db, as_, svc, sound, slides, TestClient(app), state


def test_the_forms_answer_and_say_so(pages):
    db, as_, (s1, s2, s3), sound, _, client, state = pages
    aid = ask(as_, s1, sound, KENDRA).json()["assignment"]["id"]
    r = client.post("/my/serving/answer", data={"id": aid, "ans": "yes"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/my/serving/{aid}?done=yes"
    assert row(db, aid)["status"] == "yes"
    r = client.post("/my/serving/away", data={"start": "2026-11-29", "end": "2026-11-26"}, follow_redirects=False)
    assert r.headers["location"].startswith("/my/serving?err=said&msg=")
    r = client.post("/my/serving/often", data={"often": "every"}, follow_redirects=False)
    assert r.headers["location"] == "/my/serving?done=often"
    # The owner's preview saves nothing.
    state["unavailable"] = "preview"
    r = client.post("/my/serving/answer", data={"id": aid, "ans": "no"}, follow_redirects=False)
    assert r.headers["location"] == f"/my/serving/{aid}?err=preview" and row(db, aid)["status"] == "yes"
    assert db.t["business_users"] == []


def test_the_pages_draw_the_canvas_words(pages):
    from starlette.requests import Request
    db, as_, (s1, s2, s3), sound, slides, client, state = pages
    aid = ask(as_, s2, sound, KENDRA).json()["assignment"]["id"]
    ask(as_, s2, slides, ANA)
    as_("owner").patch(f"/planning/teams/{PRODUCTION}", json={"business_id": BIZ, "call_time": "10:15"})
    req = Request({"type": "http", "query_string": b"", "headers": []})
    html = mps.render_ask(CHURCH, None, req, state["me"], ss.ask_view(CHURCH, KENDRA, aid))
    for words in ("Can you serve on <em>Sound?</em>", "Production · Pastor Kevin asked", "Be there by 10:15 AM · service at 10:30 AM",
                  "Yes, I&#x27;ll serve", "Can&#x27;t that day", "I can&#x27;t, but I can do Nov 8", "On with you", "Ana Cruz"):
        assert words in html, words
    ss.answer(CHURCH, KENDRA, aid, "yes")
    html = mps.render_ask(CHURCH, None, req, state["me"], ss.ask_view(CHURCH, KENDRA, aid))
    assert "You're on for Nov 1." in html and f"/my/serving/{aid}.ics" in html
    page = mps.render_page(CHURCH, None, req, state["me"], ss.mine(CHURCH, KENDRA))
    for words in ("My <em>serving</em>", "Sundays this year", "Coming up", "Sound · Sunday",
                  "Can't make it", "Nobody asks you on these days.", "Once a month"):
        assert words in page, words
    cal = mps.ics(CHURCH, ss.ask_view(CHURCH, KENDRA, aid))
    assert "DTSTART:20261101T161500Z" in cal and "SUMMARY:Sound · Love City Church" in cal
