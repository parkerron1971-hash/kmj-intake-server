"""Every reader of an event date's own numbers (docs/EVENT_VOLUNTEERS.md 6.5):
serve_dates.needed(service, place) is the one rule. An event date with
{Greeter: 2} shows two Greeter slots and no Usher slot everywhere a slot is
counted, a place it doesn't name can't be asked, offered or filled, and an
event date with no numbers (needs null, how every date made before them
reads) needs each place's Sunday number.

The readers: Who serves when (the board, the schedule, who could take a place,
asking, offering, filling), the member's ask page (sunday_serving.ask_view), a
team leader's Sundays (member_portal_leading), The week (church_week), My
week's "4 of 6 for Thursday's Outreach night" (church_work_checks), and the
readers of the Sunday plans alone (the leaders note and the weekly letter,
church_leaders_note._sunday_places; the monthly report), which never see an
event date but count through the same rule."""
from __future__ import annotations

import os
import re
import sys
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_week as cw  # noqa: E402
import church_work_checks as cwc  # noqa: E402
import event_volunteers as evv  # noqa: E402
import serve_dates as sd  # noqa: E402
import sunday_planning as sp  # noqa: E402
import sunday_serving as ss  # noqa: E402
from test_church_week import THU, WEEK, NURSERY, CHECKIN, LOTS, app, db, card, week  # noqa: E402,F401
from test_event_volunteers import E_LOCK, E_OUT, asked, church  # noqa: E402,F401
from test_sunday_planning import ANA, BIZ, JO, LEE, NOW, WELCOME, ZONE  # noqa: E402

CHURCH = {"id": BIZ, "name": "Love City Church", "settings": {}}


def test_the_rule():
    greeter, usher = {"id": "g", "needed": 1}, {"id": "u", "needed": 2}
    event = {"kind": "event", "needs": {"g": 2}}
    assert (sd.needed(event, greeter), sd.needed(event, usher)) == (2, 0)
    for plain in ({"kind": "event", "needs": None}, {"kind": "service"}, {}, None):
        assert (sd.needed(plain, greeter), sd.needed(plain, usher)) == (1, 2), plain
    assert sd.needed(None, {"id": "x", "needed": None}) == 1
    assert sd.needed({"needs": {"g": True}}, greeter) == 0 and sd.needed({"needs": {"g": "x"}}, greeter) == 0


def _lock(c, needs=None):
    """The Youth Lock-in on Who serves when with these numbers, straight on."""
    return asked(c, "laquesha", needs=needs or {c.greeter: 2})["date"]["id"]


def test_who_serves_when_counts_the_event_dates_own_numbers(church):
    c = church
    sid = _lock(c)
    j = c.as_("laquesha").get(f"/planning/schedule?business_id={BIZ}&weeks=2").json()
    svc = {s["id"]: s for s in j["services"]}
    assert svc[sid]["needs"] == {c.greeter: 2}
    assert svc[sid]["needed"] == {c.greeter: 2, c.usher: 0}, "ChurchSavvy's Sound never serves it"
    assert svc[c.s1]["needed"] == {c.sound: 1, c.greeter: 1, c.usher: 2}
    # Who could take a place it doesn't need: nobody.
    def cands(pid):
        return c.as_("laquesha").get(f"/planning/candidates?business_id={BIZ}&service_id={sid}&position_id={pid}").json()
    assert cands(c.usher)["candidates"] == [] and len(cands(c.greeter)["candidates"]) == 4, "the team's people"
    # Asked, offered or filled: never the place it doesn't need.
    def put(path, pid, **body):
        return c.as_("laquesha").post(path, json={"business_id": BIZ, "service_id": sid, "position_id": pid, **body})
    for path, body in (("/planning/ask", {"contact_id": ANA}), ("/planning/offer", {})):
        r = put(path, c.usher, **body)
        assert r.status_code == 409 and r.json()["detail"] == "Usher isn't needed for the Youth Lock-in.", path
    assert put("/planning/ask", c.greeter, contact_id=JO, slot=2).status_code == 200
    r = put("/planning/ask", c.greeter, contact_id=LEE, slot=3)
    assert r.status_code == 400 and "that many spots" in r.json()["detail"]
    filled = c.as_("laquesha").post("/planning/fill", json={"business_id": BIZ, "weeks": 2}).json()
    on_event = sorted((r["position_id"], r["slot"]) for r in c.db.t["serve_assignments"] if r["service_id"] == sid)
    assert on_event == [(c.greeter, 1), (c.greeter, 2)], "two Greeter slots and no Usher"
    assert filled["asked"] >= 1
    # An event date with no numbers (the November 17 way): the Sunday numbers.
    old = c.as_("laquesha").post("/planning/dates", json={"business_id": BIZ, "entry_id": E_OUT}).json()["date"]
    j = c.as_("laquesha").get(f"/planning/schedule?business_id={BIZ}&weeks=2").json()
    assert next(s for s in j["services"] if s["id"] == old["id"])["needed"] == {c.greeter: 1, c.usher: 2}
    assert old["needs"] is None


def test_the_members_ask_page_shows_the_event_dates_places(church):
    c = church
    sid = _lock(c)
    aid = c.as_("laquesha").post("/planning/ask", json={"business_id": BIZ, "service_id": sid, "position_id": c.greeter,
                                                        "slot": 2, "contact_id": JO}).json()["assignment"]["id"]
    v = ss.ask_view(CHURCH, JO, aid)
    assert [(w["place"], w["status"]) for w in v["with"]] == [("Greeter", "open")], "the other Greeter, no Usher"
    # A Sunday's still lists every place at its Sunday number.
    sun = c.as_("laquesha").post("/planning/ask", json={"business_id": BIZ, "service_id": c.s1, "position_id": c.greeter,
                                                        "contact_id": LEE}).json()["assignment"]["id"]
    assert [w["place"] for w in ss.ask_view(CHURCH, LEE, sun)["with"]] == ["Usher", "Usher"]


def test_a_team_leaders_sundays_show_the_event_dates_places(church, monkeypatch):
    import member_portal
    import member_portal_leading as mpl
    import sunday_leading as sl
    c = church
    sid = _lock(c)
    monkeypatch.setattr(member_portal, "_shell", lambda biz, site, title, body, **kw: body)
    c.db.t["group_members"].append({"business_id": BIZ, "group_id": WELCOME, "contact_id": LEE, "role": "leader"})
    v = sl.team_view(CHURCH, LEE, WELCOME)
    req = Request({"type": "http", "query_string": b"", "headers": []})
    me = {"id": LEE, "name": "Lee Ford"}
    teams = sl.led_teams(BIZ, LEE)

    def spots(day):
        html = mpl.render(CHURCH, None, req, me, teams, v, day=day, spot="", cands=None)
        return re.findall(r'<span class="ti">([^<]+)</span>', html), html
    got, html = spots(sid)
    assert got == ["Greeter 1", "Greeter 2"], "two Greeter slots and no Usher"
    assert "2 open" in html
    got, _ = spots(c.s1)
    assert got == ["Greeter", "Usher 1", "Usher 2"]


def test_the_week_counts_the_event_dates_own_numbers(app, db, monkeypatch):
    monkeypatch.setattr(evv, "_FORCE", True)
    for k in ("EVENT_VOLUNTEERS", "CHURCH_EVENT_VOLUNTEERS"):
        monkeypatch.setenv(k, "on")
    db.t["event_volunteer_requests"] = []
    thu = next(s for s in db.t["worship_services"] if s["id"] == THU)
    thu["needs"] = {NURSERY: 1, LOTS: 3}
    body = week(app, "sunny")
    kids = next(s for s in card(body, "Kids")["services"] if s["service_id"] == THU)
    lot = next(s for s in card(body, "Parking Team")["services"] if s["service_id"] == THU)
    assert [(r["place"], r["slot"]) for r in kids["rows"]] == [("Nursery", 1)], "no second Nursery, no Check-in"
    assert [(r["place"], r["slot"]) for r in lot["rows"]] == [("Lot", 1), ("Lot", 2), ("Lot", 3)]
    assert body["requests_waiting"] == 0
    # needs null: the Sunday numbers, as before.
    thu["needs"] = None
    body = week(app, "sunny")
    kids = next(s for s in card(body, "Kids")["services"] if s["service_id"] == THU)
    assert [(r["place"], r["slot"]) for r in kids["rows"]] == [("Nursery", 1), ("Nursery", 2), ("Check-in", 1)]
    assert CHECKIN
    # The band: the events' asks still waiting.
    hope = thu["business_id"]
    db.t["event_volunteer_requests"] += [{"id": f"7e900000-0000-4000-8000-00000000000{i}", "business_id": hope,
                                          "status": s} for i, s in enumerate(("waiting", "waiting", "on"))]
    assert week(app, "sunny")["requests_waiting"] == 2
    assert WEEK


def test_my_week_counts_the_event_dates_own_numbers(church):
    c = church
    asked(c, "laquesha", entry=E_OUT, needs={c.greeter: 2})
    biz = next(b for b in c.db.t["businesses"] if b["id"] == BIZ)
    got = cwc.week_job(cwc.Ctx(biz, NOW, ZONE), "serve_schedule", NOW.astimezone(ZONE).date())
    assert got["text"].endswith(", and 0 of 2 for Thursday's Outreach night"), got
    assert "0 of 3 places on Sunday's volunteer teams" in got["text"], "Sunday: Greeter 1 and Usher 2"


def test_the_readers_of_the_sunday_plans_count_through_the_same_rule(church, monkeypatch):
    """The leaders note and the weekly letter (church_leaders_note): they read
    the Sunday plans alone (plans_only), so an event date never reaches them;
    a plan with numbers would count by them."""
    import church_leaders_note as cln
    c = church
    sid = _lock(c)
    from datetime import datetime, time, timedelta
    lo = datetime.combine(date(2026, 10, 19), time(0), tzinfo=ZONE)
    plans = cln._plans(BIZ, lo, lo + timedelta(days=14), ZONE)
    assert sid not in [p["id"] for p in plans] and len(plans) == 2
    got = cln._sunday_places(BIZ, [{**plans[0], "id": sid, "needs": {c.greeter: 2}}])
    assert got[0]["open"] == 2 and got[0]["teams"] == [("Welcome", {"Greeter": 2})], "two Greeters, no Usher"
    got = cln._sunday_places(BIZ, plans[:1])
    assert got[0]["open"] == 4 and got[0]["teams"][-1] == ("Welcome", {"Greeter": 1, "Usher": 2})
    # Selected once the column is there.
    seen = []
    import sb_clients
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: seen.append(path) or real(path))
    cln._plans(BIZ, lo, lo + timedelta(days=14), ZONE)
    assert any(",needs" in p for p in seen if p.startswith("/worship_services"))


def test_the_monthly_report_counts_sundays_through_the_same_rule(rdb, monkeypatch):
    import business_access
    import church_monthly_report as cmr
    from auth_supabase import AuthedUser, require_user
    from test_church_monthly_report import EMAIL, JESS, _lines
    monkeypatch.setattr(sd, "_FORCE", True)
    monkeypatch.setattr(evv, "_FORCE", True)
    monkeypatch.setattr(business_access, "_resolve_role", lambda b, u: "manager")
    a = FastAPI()
    a.include_router(cmr.router)
    a.dependency_overrides[require_user] = lambda: AuthedUser(id=JESS, email=EMAIL[JESS], role="authenticated")
    client = TestClient(a)

    def lines():
        r = client.get(f"/church/monthly-report?business_id={rdb.t['businesses'][0]['id']}")
        assert r.status_code == 200, r.text
        got = _lines(r.json())
        return got["serving_filled"], got["serving_open"]
    before = lines()
    biz = rdb.t["businesses"][0]["id"]
    rdb.t["worship_services"].append({"id": "ws-ev", "business_id": biz, "archived_at": None, "is_template": False,
                                      "kind": "event", "needs": {"pos1": 5},
                                      "starts_at": "2026-10-15T23:00:00+00:00"})
    assert lines() == before, "an event date is never one of the Sunday plans"


from test_church_monthly_report import rdb  # noqa: E402,F401
