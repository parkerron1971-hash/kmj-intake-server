# __tests__/test_sunday_leading.py
#
# ChurchSavvy Planning, step 7: a Sunday team's leader schedules their own
# team from the member app's Lead tab (sunday_leading.py,
# member_portal_leading.py; Kevin's call 4, canvas board 4). Pins:
#   * a leader is the church's leader of the team's group; they see their
#     team only, and someone on their team serving on another team that
#     hour shows as a clash, never as free
#   * they ask, offer, take back an ask and fill the coming Sundays for their
#     team only; another team's place is refused; a yes isn't theirs to take
#     back; taking back a fill touches only their team's asks
#   * the Lead tab offers Sundays to a team's leader and nobody else; the
#     forms say what happened, and the owner's preview saves nothing
#   * a leader is a member, never a seat

import pathlib
import sys

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from test_sunday_planning import (ANA, BIZ, JO, KENDRA, LEE, MARCUS, PRODUCTION, WELCOME, api, ask, make_team, place,  # noqa: F401
                                  services, sundays, train)

import member_portal_lead as mpl
import member_portal_leading as mpl2
import sunday_leading as sl

CHURCH = {"id": BIZ, "name": "Love City Church", "settings": {}}
MARCUS_ME = {"id": MARCUS, "name": "Marcus Hill"}


@pytest.fixture
def teams(api):
    """Production (Sound: Kendra, Jo; Slides: Marcus, Ana), led by Marcus;
    Welcome (Doors: Ana, Lee), led by Lee. Three Sundays."""
    db, as_ = api
    sundays(as_, 3)
    prod = make_team(as_)
    sound, slides = place(prod, "Sound"), place(prod, "Slides")
    doors = place(make_team(as_, gid=WELCOME, places=("Doors",)), "Doors")
    train(as_, sound, [(KENDRA, "trained"), (JO, "trained")])
    train(as_, slides, [(MARCUS, "trained"), (ANA, "trained")])
    train(as_, doors, [(ANA, "trained"), (LEE, "trained")])
    for m in db.t["group_members"]:
        if (m["group_id"], m["contact_id"]) in ((PRODUCTION, MARCUS), (WELCOME, LEE)):
            m["role"] = "leader"
    return db, as_, [s["id"] for s in services(db)], sound, slides, doors


def rows(db):
    return db.t["serve_assignments"]


def test_who_leads_and_what_they_see(teams):
    db, as_, s, sound, slides, doors = teams
    assert sl.led_teams(BIZ, MARCUS) == [{"group_id": PRODUCTION, "name": "Production"}]
    assert sl.led_teams(BIZ, KENDRA) == [] and sl.leads_a_team(BIZ, KENDRA) is False
    assert [t["name"] for t in sl.led_teams(BIZ, LEE)] == ["Welcome"]
    v = sl.team_view(CHURCH, MARCUS, PRODUCTION)
    assert [p["name"] for p in v["team"]["places"]] == ["Sound", "Slides"]
    assert len(v["services"]) == 3
    with pytest.raises(HTTPException) as e:
        sl.team_view(CHURCH, MARCUS, WELCOME)
    assert e.value.status_code == 404
    # Ana is on Welcome's Doors that Sunday: Marcus sees the clash, not a free Ana.
    ask(as_, s[0], doors, ANA)
    ana = next(c for c in sl.candidates(CHURCH, MARCUS, s[0], slides) if c["contact_id"] == ANA)
    assert ana["clash"] == "Doors" and ana["ok"] is False


def test_their_team_only(teams):
    db, as_, s, sound, slides, doors = teams
    out = sl.ask(CHURCH, MARCUS_ME, s[0], sound, 1, KENDRA)["assignment"]
    assert out["status"] == "asked" and out["asked_by"] == "Marcus Hill"
    with pytest.raises(HTTPException) as e:
        sl.ask(CHURCH, MARCUS_ME, s[0], doors, 1, ANA)
    assert e.value.status_code == 404 and "lead" in e.value.detail
    with pytest.raises(HTTPException):
        sl.offer(CHURCH, MARCUS_ME, s[0], doors, 1)
    assert sl.offer(CHURCH, MARCUS_ME, s[1], slides, 1)["assignment"]["status"] == "offered"
    # Someone not on the team can't be asked through the leader either.
    with pytest.raises(HTTPException) as e:
        sl.ask(CHURCH, MARCUS_ME, s[1], sound, 1, LEE)
    assert e.value.status_code == 409


def test_take_back_an_ask_never_a_yes(teams):
    db, as_, s, sound, slides, doors = teams
    a = sl.ask(CHURCH, MARCUS_ME, s[0], sound, 1, KENDRA)["assignment"]["id"]
    assert sl.take_back(CHURCH, MARCUS_ME, a) == {"ok": True}
    b = sl.ask(CHURCH, MARCUS_ME, s[0], sound, 1, JO)["assignment"]["id"]
    as_("owner").post(f"/planning/assignments/{b}/answer", json={"business_id": BIZ, "status": "yes"})
    with pytest.raises(HTTPException) as e:
        sl.take_back(CHURCH, MARCUS_ME, b)
    assert e.value.status_code == 409
    # Welcome's ask isn't his to take back.
    w = ask(as_, s[0], doors, LEE).json()["assignment"]["id"]
    with pytest.raises(HTTPException) as e:
        sl.take_back(CHURCH, MARCUS_ME, w)
    assert e.value.status_code == 404
    assert {r["id"] for r in rows(db)} >= {b, w}


def test_fill_and_take_it_back_their_team_only(teams):
    db, as_, s, sound, slides, doors = teams
    out = sl.fill(CHURCH, MARCUS_ME, PRODUCTION)
    filled = [r for r in rows(db) if r["id"] in out["ids"]]
    assert out["asked"] == len(filled) > 0
    assert {r["position_id"] for r in filled} <= {sound, slides}
    assert not any(r["position_id"] == doors for r in rows(db))
    # Taking it back only touches his team's asks, even if another id slips in.
    w = ask(as_, s[2], doors, LEE).json()["assignment"]["id"]
    back = sl.unfill(CHURCH, MARCUS_ME, PRODUCTION, out["ids"] + [w])
    assert back["taken_back"] == out["asked"]
    assert [r["id"] for r in rows(db)] == [w]
    with pytest.raises(HTTPException):
        sl.fill(CHURCH, MARCUS_ME, WELCOME)
    assert db.t["business_users"] == []


@pytest.fixture
def pages(teams, monkeypatch):
    import member_portal
    import member_portal_church
    import rate_limit
    state = {"me": MARCUS_ME, "unavailable": None}

    async def signed_in(request):
        return {"business": CHURCH, "site": None}, (None if state["unavailable"] else state["me"]), state["unavailable"]

    monkeypatch.setattr(member_portal_church, "_signed_in", signed_in)
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a, **k: True)
    monkeypatch.setattr(member_portal, "_shell", lambda biz, site, title, body, **kw: body)
    app = FastAPI()
    app.include_router(mpl2.router)
    return TestClient(app), state


def test_the_page_and_its_forms(teams, pages):
    import asyncio
    from starlette.requests import Request
    db, as_, s, sound, slides, doors = teams
    client, state = pages

    def page(q=b""):
        req = Request({"type": "http", "query_string": q, "headers": []})
        mpl.SUNDAYS.set(True)
        html, status = asyncio.run(mpl2.serve(req, CHURCH, None, MARCUS_ME))
        assert status == 200
        return html

    html = page()
    for words in ("Lead, <em>Marcus</em>", "Production", "Your team's Sundays", "Fill the next five Sundays",
                  "Sound", "Slides", "Nobody yet", "Find someone", "/my/lead/groups", "/my/lead/sundays"):
        assert words in html, words
    # Asking from the page: the form says so and it's on the schedule.
    r = client.post("/my/lead/sundays/ask", data={"team": PRODUCTION, "day": s[0], "place": sound, "slot": "1",
                                                   "person": KENDRA}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/my/lead/sundays?team={PRODUCTION}&day={s[0]}&done=asked"
    assert any(x["contact_id"] == KENDRA and x["position_id"] == sound for x in rows(db))
    # Another team's place: refused, in words.
    r = client.post("/my/lead/sundays/ask", data={"team": PRODUCTION, "day": s[0], "place": doors, "slot": "1",
                                                   "person": ANA}, follow_redirects=False)
    assert "err=said" in r.headers["location"]
    # The spot panel: who could take Slides.
    html = page(f"team={PRODUCTION}&day={s[0]}&spot={slides}:1".encode())
    assert "Who could take Slides" in html and "Offer it to the whole team" in html and "Ana Cruz" in html
    # Fill, then take it back from the banner.
    r = client.post("/my/lead/sundays/fill", data={"team": PRODUCTION}, follow_redirects=False)
    assert "filled=" in r.headers["location"] and "ids=" in r.headers["location"]
    # The owner's preview saves nothing.
    state["unavailable"] = "preview"
    before = len(rows(db))
    r = client.post("/my/lead/sundays/offer", data={"team": PRODUCTION, "day": s[2], "place": slides, "slot": "1"},
                    follow_redirects=False)
    assert "err=preview" in r.headers["location"] and len(rows(db)) == before


def test_the_lead_tab_offers_sundays_to_team_leaders(teams):
    mpl.SUNDAYS.set(True)
    assert "/my/lead/sundays" in mpl._seg("groups", False, False, 0, 0, 1)
    mpl.SUNDAYS.set(False)
    assert "/my/lead/sundays" not in mpl._seg("groups", True, False, 0, 0, 1)
