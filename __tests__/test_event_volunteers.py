"""An event's volunteers, the engine (event_volunteers.py, sunday_planning.py,
serve_dates.needed; docs/EVENT_VOLUNTEERS.md, step S2). Kevin, 2026-11-20:
"when a event is made there should be questions asked normal service
volunteers or special volunteers. this is needed so people can request for an
amount of volunteers for their event", then "go" on the proposal.

Pins, each one broken on purpose once to see its test go red:
  * the gate table (section 5): the owner, an Admin and the serve_schedule
    holder ask straight on; another Manager and an office Member login wait;
    a Viewer is the part's refusal; a Member login that doesn't work the
    office is refused; only whoever schedules the teams answers
  * every 400 and 409 of 6.1 to 6.4, in the spec's words
  * the double yes: the claim lands only while the ask waits, so a second
    yes is a 409 and one event date is made
  * the switch (off | owner | on, and only where event dates are open) and
    the migration (ready): closed or before it, the routes 404, nothing
    selects worship_services.needs, nothing is a 500; the switch never hides
    what is there
  * Sunday afternoons (6.9) and typed dates becoming events (6.8)
  * notices (7.1, 7.2): told once from the ask's own ledger, held through
    quiet hours, a failed send let go and told by the sweep, never twice

The readers of an event date's numbers (6.5) are test_event_volunteers_readers."""
from __future__ import annotations

import copy
import os
import sys
import uuid as uuidlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import business_access  # noqa: E402
import business_marketing  # noqa: E402
import church_duties as cd  # noqa: E402
import church_schedule_tell as cst  # noqa: E402
import church_spaces  # noqa: E402
import event_volunteers as evv  # noqa: E402
import member_asks  # noqa: E402
import member_push  # noqa: E402
import sb_clients  # noqa: E402
import serve_dates as sd  # noqa: E402
import sunday_planning as sp  # noqa: E402
import worship_team as wt  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_sunday_planning import (ANA, BIZ, JO, KENDRA, LEE, MARCUS, NOW, OTHER, OWNER_EMAIL, PRODUCTION,  # noqa: E402
                                  WELCOME, ZONE, FakeDb)
from test_volunteers_door import DUTIES  # noqa: E402

WHO = ("owner", "admin", "laquesha", "shapretta", "tiara", "member", "outsider", "viewer", "stranger")
PEOPLE = {n: AuthedUser(id=f"u-{n}", email=f"{n}@lovecity.org", role="authenticated") for n in WHO}
PEOPLE["owner"] = AuthedUser(id="u-owner", email=OWNER_EMAIL, role="authenticated")
SEATS = {"u-owner": "owner", "u-admin": "admin", "u-laquesha": "manager", "u-shapretta": "manager",
         "u-tiara": "manager", "u-member": "member", "u-outsider": "member", "u-viewer": "viewer"}
NAMES = {"u-admin": "Dee Grant", "u-laquesha": "Laquesha Brown", "u-shapretta": "Shapretta Mills",
         "u-tiara": "Tiara Cole", "u-member": "Mo Bell", "u-outsider": "Ollie Sun", "u-viewer": "Vic Lane"}
MOD, MOD2 = "55555555-5555-4555-8555-555555555555", "56565656-5656-4565-8565-565656565656"
# Services & Events at Love City (made up). NOW is Wednesday 21 October 2026,
# 10 AM in Chicago; Sunday services are on 10/25 and 11/1 at 10:30.
E_LOCK, E_BARE, E_PAST, E_FAR, E_SUN_PM, E_SUN_AM, E_THEIRS, E_OUT = (
    f"e1000000-0000-4000-8000-{n:012d}" for n in range(1, 9))
ENTRIES = [
    (E_LOCK, BIZ, {"title": "Youth Lock-in", "date": "2026-10-30T18:00", "location": "Fellowship hall",
                   "_roles": [{"id": "chap", "label": "Chaperones", "needed": 3, "kids": True},
                              {"id": "grill", "label": "Grill", "needed": 1, "open": True}],
                   "signups": [{"name": "Ana Cruz", "contact_id": ANA, "role": "chap", "status": "yes"},
                               {"name": "Lee Ford", "role": "grill"},
                               {"name": "Guest", "role": "Attending"}]}),
    (E_BARE, BIZ, {"title": "Saturday clean-up", "date": "2026-10-24", "location": "The lot"}),
    (E_PAST, BIZ, {"title": "Prayer walk", "date": "2026-10-20T18:00"}),
    (E_FAR, BIZ, {"title": "Summer picnic", "date": "2027-06-05T12:00"}),
    (E_SUN_PM, BIZ, {"title": "Fellowship dinner", "date": "2026-10-25T17:00", "location": "The hall"}),
    (E_SUN_AM, BIZ, {"title": "Sunday worship", "date": "2026-10-25T11:30"}),
    (E_THEIRS, OTHER, {"title": "Their night", "date": "2026-10-30T19:00"}),
    (E_OUT, BIZ, {"title": "Outreach night", "date": "2026-10-22T19:00", "location": "The park"}),
]


class EvDb(FakeDb):
    """FakeDb, plus the request table's one live ask an event (the partial
    unique index: PostgREST's 409, code 23505) and last_error()."""

    def __init__(self):
        super().__init__()
        self.err = None

    def post(self, path, body, prefer=None, **kw):
        self.err = None
        table = path.lstrip("/").partition("?")[0]
        if table == "event_volunteer_requests":
            for b in (body if isinstance(body, list) else [body]):
                if b.get("entry_id") and b.get("status") in evv.LIVE and any(
                        r.get("entry_id") == b["entry_id"] and r.get("status") in evv.LIVE for r in self.t[table]):
                    self.err = {"status": 409, "code": "23505", "message": "event_volunteer_requests_one_live"}
                    return None
        got = super().post(path, body, prefer, **kw)
        if table == "event_volunteer_requests" and isinstance(got, list):
            for r in self.t[table]:
                r.setdefault("created_at", NOW.isoformat())
        return got


@pytest.fixture
def church(monkeypatch):
    db = EvDb()
    db.t["businesses"][0].update(type="ministry", name="Love City Church")
    db.t["businesses"].append({"id": OTHER, "name": "Other Church", "owner_id": "u-else", "type": "ministry",
                               "settings": {}})
    db.t["business_users"] = [{"business_id": BIZ, "user_id": u, "role": r, "status": "active", "name": NAMES.get(u, ""),
                               "contact_id": None, "invited_email": f"{u[2:]}@lovecity.org", "lane": None,
                               "areas": None} for u, r in SEATS.items() if u != "u-owner"]
    db.t["worship_team"] = []
    db.t["custom_modules"] = [{"id": MOD, "business_id": BIZ, "name": "Services & Events", "archetype": "event_roster",
                               "is_active": True, "archetype_params": {}, "created_at": "2026-01-01T00:00:00+00:00"}]
    db.t["module_entries"] = [{"id": i, "business_id": b, "module_id": MOD, "status": "active", "data": copy.deepcopy(d),
                               "created_at": NOW.isoformat()} for i, b, d in ENTRIES]
    db.t["event_volunteer_requests"] = []
    db.t["serve_notes"] = []
    for name, fn in (("sb_get_as_service", db.get), ("sb_post_as_service", db.post),
                     ("sb_patch_as_service", db.patch), ("sb_delete_as_service", db.delete)):
        monkeypatch.setattr(sb_clients, name, fn)
    monkeypatch.setattr(sb_clients, "last_error", lambda: db.err)
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", OWNER_EMAIL)
    for k, v in (("SUNDAY_PLANNING", "on"), ("CHURCH_EVENT_VOLUNTEERS", "on"), ("EVENT_VOLUNTEERS", "on")):
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("CHURCHSAVVY_BILLING", raising=False)
    monkeypatch.setattr(sd, "_FORCE", True)
    monkeypatch.setattr(evv, "_FORCE", True)
    monkeypatch.setattr(wt, "role_of", lambda biz, uid: SEATS.get(uid) if biz == BIZ else None)
    monkeypatch.setattr(business_access, "_resolve_role", lambda biz, uid: SEATS.get(str(uid)) if biz == BIZ else None)
    monkeypatch.setattr(business_marketing, "business_tz", lambda row: ZONE)
    monkeypatch.setattr(sp, "_now", lambda: NOW)
    monkeypatch.setattr(evv, "_now", lambda: NOW)
    monkeypatch.setattr(member_asks, "platform_church", lambda biz: False)
    monkeypatch.setattr(church_spaces, "_office", lambda biz, uid, role: uid != "u-outsider")

    def fake_standing(biz, uid):
        role = SEATS.get(str(uid))
        if role in ("owner", "admin"):
            return {"church": True, "role": role, "lanes": [], "duties": cd.ALL}
        held = DUTIES.get(str(uid), set()) if role == "manager" else set()
        return {"church": True, "role": role, "lanes": [], "duties": frozenset(held)}
    monkeypatch.setattr(cd, "standing", fake_standing)
    monkeypatch.setitem(sp._no_column, "at", 0.0)
    # Notices: each office login's push and email, recorded; handed on at once.
    told = []
    sends = {"ok": True}

    def to_login(ch, uid, **kw):
        told.append({"uid": uid, **kw})
        return {"rang": 1, "mailed": 0} if sends["ok"] else {"rang": 0, "mailed": 0}
    monkeypatch.setattr(cst, "to_login", to_login)
    monkeypatch.setattr(member_push, "_later", lambda fn, *a, **k: fn(*a, **k))
    quiet = {"on": False}
    monkeypatch.setattr(member_push, "quiet_hour", lambda biz, now=None: quiet["on"])
    who = {"user": PEOPLE["owner"]}
    app = FastAPI()
    for r in (sp.router, evv.router):
        app.include_router(r)
    app.dependency_overrides[require_user] = lambda: who["user"]
    client = TestClient(app)

    def as_(name):
        who["user"] = PEOPLE[name]
        return client

    # Two Sundays; ChurchSavvy's Production (Sound: Kendra) and Volunteers'
    # Welcome: Greeter (1 on a Sunday: Jo, Lee) and Usher (2: Marcus, Ana).
    assert as_("owner").post("/planning/sundays", json={"business_id": BIZ, "count": 2}).status_code == 200
    s1, s2 = (s["id"] for s in sorted(db.t["worship_services"], key=lambda s: s["starts_at"]))
    places = {}
    for gid, names, people in ((PRODUCTION, ["Sound"], {"Sound": [KENDRA]}),
                               (WELCOME, ["Greeter", "Usher"], {"Greeter": [JO, LEE], "Usher": [MARCUS, ANA]})):
        r = as_("owner").post("/planning/teams", json={"business_id": BIZ, "group_id": gid, "places": names})
        assert r.status_code == 200, r.text
        for p in r.json()["team"]["places"]:
            places[p["name"]] = p["id"]
            assert as_("owner").put(f"/planning/positions/{p['id']}/people", json={
                "business_id": BIZ, "people": [{"contact_id": x, "level": "trained"} for x in people[p["name"]]]
            }).status_code == 200
    assert as_("owner").patch(f"/planning/positions/{places['Usher']}",
                              json={"business_id": BIZ, "needed": 2}).status_code == 200
    import types
    return types.SimpleNamespace(db=db, as_=as_, s1=s1, s2=s2, sound=places["Sound"], greeter=places["Greeter"],
                                 usher=places["Usher"], told=told, sends=sends, quiet=quiet)


def ask(c, who="shapretta", entry=E_LOCK, needs=None, **extra):
    return c.as_(who).post(f"/church/event-volunteers/{entry}/request", json={
        "business_id": BIZ, "needs": needs if needs is not None else {c.greeter: 2}, **extra})


def asked(c, who="shapretta", entry=E_LOCK, needs=None, **extra):
    r = ask(c, who, entry, needs, **extra)
    assert r.status_code == 200, r.text
    return r.json()


def answer(c, rid, said="yes", who="laquesha", **extra):
    return c.as_(who).post(f"/planning/requests/{rid}/answer", json={"business_id": BIZ, "answer": said, **extra})


def rows(c):
    return c.db.t["event_volunteer_requests"]


def event_dates(c, entry=None):
    return [s for s in c.db.t["worship_services"] if s.get("kind") == "event" and s.get("archived_at") is None
            and (entry is None or s.get("event_entry_id") == entry)]


def status(c, who):
    r = c.as_(who).get(f"/church/event-volunteers/status?business_id={BIZ}")
    assert r.status_code == 200, r.text
    return r.json()


def clear(c):
    c.db.t["event_volunteer_requests"] = []
    c.db.t["worship_services"] = [s for s in c.db.t["worship_services"] if s.get("kind") != "event"]
    c.told.clear()


# ─── who may do what (section 5) ─────────────────────────────────────


def test_the_gate_table(church):
    c = church
    # Straight on: the owner, an Admin, the serve_schedule holder. The date is
    # made at once with these numbers, and the ask is on.
    for who, name in (("owner", "Pastor Kevin"), ("admin", "Dee"), ("laquesha", "Laquesha")):
        got = asked(c, who)
        assert got["request"]["status"] == "on", who
        assert got["request"]["asked_by_name"] == name and got["request"]["decided_by_name"] == name
        d = event_dates(c, E_LOCK)
        assert len(d) == 1 and d[0]["needs"] == {c.greeter: 2} and got["date"]["id"] == d[0]["id"], who
        assert got["request"]["service_id"] == d[0]["id"]
        st = status(c, who)
        assert (st["can_ask"], st["can_schedule"]) == (True, True), who
        clear(c)
    # Waiting: any other Manager, and a Member login that works the office.
    for who in ("shapretta", "tiara", "member"):
        got = asked(c, who)
        assert got["request"]["status"] == "waiting" and got["date"] is None, who
        assert event_dates(c, E_LOCK) == [], who
        st = status(c, who)
        assert (st["can_ask"], st["can_schedule"]) == (True, False), who
        # They can't answer, even their own.
        r = answer(c, got["request"]["id"], who=who)
        assert r.status_code == 403, (who, r.text)
        clear(c)
    # A Viewer reads and never asks: the part's refusal.
    r = ask(c, "viewer")
    assert r.status_code == 403 and r.json()["detail"] == wt.REFUSED["serve"]
    assert status(c, "viewer")["can_ask"] is False
    assert c.as_("viewer").get(f"/church/event-volunteers/{E_LOCK}?business_id={BIZ}").status_code == 200
    # A Member login that doesn't work the office, and a stranger.
    r = ask(c, "outsider")
    assert r.status_code == 403 and r.json()["detail"] == evv.NOT_OFFICE
    assert c.as_("outsider").get(f"/church/event-volunteers/{E_LOCK}?business_id={BIZ}").status_code == 403
    assert ask(c, "stranger").status_code == 404
    assert c.as_("stranger").get(f"/church/event-volunteers/{E_LOCK}?business_id={BIZ}").status_code == 404
    assert rows(c) == []


def test_only_whoever_schedules_the_teams_answers(church):
    c = church
    rid = asked(c)["request"]["id"]
    for who in ("shapretta", "tiara", "viewer"):
        r = answer(c, rid, who=who)
        assert r.status_code == 403, who
    assert answer(c, rid, who="stranger").status_code == 404
    assert c.as_("tiara").get(f"/planning/requests?business_id={BIZ}").status_code == 403
    assert c.as_("viewer").put(f"/planning/dates/{c.s1}/needs", json={"business_id": BIZ, "needs": None}).status_code == 403
    assert rows(c)[0]["status"] == "waiting"
    for who in ("owner", "admin", "laquesha"):
        assert c.as_(who).get(f"/planning/requests?business_id={BIZ}").status_code == 200, who


# ─── asking: every refusal (6.1) ─────────────────────────────────────


def test_asking_refusals_in_their_words(church):
    c = church

    def no(code, words, entry=E_LOCK, who="shapretta", **body):
        r = ask(c, who, entry, **body)
        assert r.status_code == code and words in r.json()["detail"], (entry, body, r.text)

    no(400, "Give the event a start time first", E_BARE)
    no(400, "The Prayer walk has already happened", E_PAST)
    no(400, "The Summer picnic is more than 6 months away", E_FAR)
    no(400, "That's during Sunday's service. Sunday services are already on Who serves when.", E_SUN_AM)
    no(404, "isn't in Services & Events", E_THEIRS)
    no(400, "That event id isn't valid", "nope")
    no(400, "Tick at least one place, or untick Our regular serving teams.", needs={})
    no(400, "Sound isn't one of the Volunteers' places", needs={c.sound: 1})
    no(400, "That place isn't one of the Volunteers' places", needs={str(uuidlib.uuid4()): 1})
    no(400, "That place isn't one of the Volunteers' places", needs={"greeters": 1})
    for bad in (0, 51, True, 2.5, "2"):
        no(400, "Give Greeter a number from 1 to 50", needs={c.greeter: bad})
    no(400, "60 places at most", needs={str(uuidlib.uuid4()): 1 for _ in range(61)})
    no(400, "Keep the note to 300 letters", note="x" * 301)
    assert rows(c) == []
    # The note is plain text, its spaces kept to one.
    got = asked(c, note="  Ten  youth,\n two leaders  ")
    assert got["request"]["note"] == "Ten youth, two leaders"
    # A second live ask, from anyone: refused before anything is written
    # (the database's one live ask an event is the second guard, below).
    posts = []
    real_post = sb_clients.sb_post_as_service
    try:
        sb_clients.sb_post_as_service = lambda path, *a, **k: posts.append(path) or real_post(path, *a, **k)
        no(409, "This event already asked for volunteers. Change the numbers on it instead.")
        no(409, "This event already asked for volunteers.", who="laquesha")
    finally:
        sb_clients.sb_post_as_service = real_post
    assert posts == []
    # Two at once: both read no ask, and the database's one live ask an
    # event (23505) says no to the second, before any date is made.
    real = evv.live_request
    try:
        evv.live_request = lambda biz, eid: None
        no(409, "This event already asked for volunteers.", who="laquesha")
    finally:
        evv.live_request = real
    assert len(rows(c)) == 1 and event_dates(c) == [], "the straight-on date isn't made when the ask can't be"


def test_an_event_already_on_who_serves_when(church):
    c = church
    # Made the November 17 way: picked from Services & Events, with no ask.
    r = c.as_("laquesha").post("/planning/dates", json={"business_id": BIZ, "entry_id": E_LOCK})
    assert r.status_code == 200, r.text
    r = ask(c)
    assert r.status_code == 409
    assert r.json()["detail"] == "This event is already on Who serves when. Laquesha can change its numbers there."
    # With nobody holding the duty, the words say so plainly.
    DUTIES_ = dict(DUTIES)
    try:
        DUTIES["u-laquesha"] = {"events"}
        r = ask(c)
        assert r.json()["detail"] == ("This event is already on Who serves when. Whoever schedules the teams can "
                                      "change its numbers there.")
    finally:
        DUTIES.clear()
        DUTIES.update(DUTIES_)


def test_straight_on_that_cant_make_the_date_leaves_no_ask(church):
    c = church
    # Thirty event dates still to come: the most a church has (make_date's rule holds here too).
    for n in range(sp.MAX_EVENT_DATES):
        c.db.t["worship_services"].append({"id": str(uuidlib.uuid4()), "business_id": BIZ, "title": f"Night {n}",
                                           "starts_at": "2026-11-05T00:00:00+00:00", "kind": "event",
                                           "archived_at": None, "is_template": False, "items": []})
    r = ask(c, "laquesha")
    assert r.status_code == 400 and "30 event dates still to come" in r.json()["detail"]
    assert rows(c) == [] and event_dates(c, E_LOCK) == [], "never half of one"
    # Waiting needs no date yet: it can still be asked.
    assert asked(c, "shapretta")["request"]["status"] == "waiting"


def test_changing_and_taking_back_an_ask(church):
    c = church
    got = asked(c, "shapretta")
    path = f"/church/event-volunteers/{E_LOCK}/request"
    # Only the one who asked, or whoever schedules the teams.
    r = c.as_("tiara").patch(path, json={"business_id": BIZ, "needs": {c.greeter: 1}})
    assert r.status_code == 403 and "Shapretta" in r.json()["detail"]
    assert c.as_("tiara").delete(f"{path}?business_id={BIZ}").status_code == 403
    r = c.as_("shapretta").patch(path, json={"business_id": BIZ, "needs": {c.greeter: 1, c.usher: 3}, "note": "More"})
    assert r.status_code == 200 and r.json()["request"]["needs"] == {c.greeter: 1, c.usher: 3}
    r = c.as_("laquesha").patch(path, json={"business_id": BIZ, "note": "Thanks"})
    assert r.status_code == 200 and r.json()["request"]["note"] == "Thanks"
    assert c.as_("shapretta").patch(path, json={"business_id": BIZ}).status_code == 400
    r = c.as_("shapretta").patch(path, json={"business_id": BIZ, "needs": {c.sound: 1}})
    assert r.status_code == 400 and "Sound isn't one of the Volunteers' places" in r.json()["detail"]
    # Taken back while it waits; then the event may ask again.
    r = c.as_("shapretta").delete(f"{path}?business_id={BIZ}")
    assert r.status_code == 200 and r.json()["request"]["status"] == "withdrawn"
    assert c.as_("shapretta").delete(f"{path}?business_id={BIZ}").status_code == 404
    got = asked(c, "shapretta")
    assert answer(c, got["request"]["id"]).status_code == 200
    # On: the organizer changes nothing here (refused before any write), and
    # it comes off Who serves when instead.
    writes = []
    real_patch = sb_clients.sb_patch_as_service
    try:
        sb_clients.sb_patch_as_service = lambda path, *a, **k: writes.append(path) or real_patch(path, *a, **k)
        r = c.as_("shapretta").patch(path, json={"business_id": BIZ, "needs": {c.greeter: 1}})
    finally:
        sb_clients.sb_patch_as_service = real_patch
    assert r.status_code == 409 and r.json()["detail"] == "It's on the schedule now. Ask Laquesha to change the numbers."
    assert not [w for w in writes if "event_volunteer_requests" in w]
    r = c.as_("laquesha").patch(path, json={"business_id": BIZ, "needs": {c.greeter: 1}})
    assert r.status_code == 409 and r.json()["detail"] == "It's on the schedule now. Change its numbers on Who serves when."
    r = c.as_("shapretta").delete(f"{path}?business_id={BIZ}")
    assert r.status_code == 409 and r.json()["detail"] == "Take it off Who serves when instead."
    assert [x["status"] for x in rows(c)] == ["withdrawn", "on"]


# ─── answering (6.2, 6.3) ────────────────────────────────────────────


def test_whoever_schedules_the_teams_sees_the_asks(church, monkeypatch):
    c = church
    monkeypatch.setenv("SUPABASE_URL", "https://sb.test")
    folder = f"https://sb.test/storage/v1/object/public/business-assets/{BIZ}/event-flyers/{E_LOCK}/"
    entry = next(e for e in c.db.t["module_entries"] if e["id"] == E_LOCK)
    # S3: the copies are named for their artwork (flyer_of pins the event's folder and the names).
    entry["data"]["_flyer"] = {"url": folder + "a7700000-0000-4000-8000-0000000000aa.jpg", "thumb": folder + "a7700000-0000-4000-8000-0000000000aa-thumb.jpg", "w": 1600, "h": 900}
    asked(c, "shapretta", needs={c.usher: 3, c.greeter: 2}, note="Ten youth")
    asked(c, "member", entry=E_OUT, needs={c.greeter: 1})
    got = c.as_("laquesha").get(f"/planning/requests?business_id={BIZ}").json()["requests"]
    assert [g["title"] for g in got] == ["Outreach night", "Youth Lock-in"], "soonest event first"
    lock = got[1]
    assert (lock["day"], lock["time"], lock["place"], lock["asked_by_name"], lock["note"]) == (
        "Friday, Oct 30", "6:00 PM", "Fellowship hall", "Shapretta", "Ten youth")
    assert lock["places"] == [
        {"place_id": c.greeter, "name": "Greeter", "team": "Welcome", "n": 2, "sunday": 1},
        {"place_id": c.usher, "name": "Usher", "team": "Welcome", "n": 3, "sunday": 2}]
    assert lock["flyer_thumb"] == folder + "a7700000-0000-4000-8000-0000000000aa-thumb.jpg" and lock["entry_id"] == E_LOCK
    assert lock["special"] == [{"label": "Chaperones", "needed": 3, "filled": 1},
                               {"label": "Grill", "needed": 1, "filled": 1}], "labels and numbers, no names"
    assert "Ana" not in str(lock["special"])
    # A flyer that isn't the church's own is no flyer.
    entry["data"]["_flyer"]["thumb"] = "https://elsewhere.test/a.jpg"
    got = c.as_("laquesha").get(f"/planning/requests?business_id={BIZ}").json()["requests"]
    assert got[1]["flyer_thumb"] is None
    # Answered ones stay a week, newest first after the waiting ones.
    answer(c, got[0]["id"], "no", note="Not that week")
    got = c.as_("laquesha").get(f"/planning/requests?business_id={BIZ}").json()["requests"]
    assert [(g["title"], g["status"]) for g in got] == [("Youth Lock-in", "waiting"), ("Outreach night", "declined")]
    rows(c)[1]["decided_at"] = (NOW - timedelta(days=8)).isoformat()
    assert [g["title"] for g in c.as_("laquesha").get(f"/planning/requests?business_id={BIZ}").json()["requests"]] == \
        ["Youth Lock-in"]


def test_yes_makes_the_event_date_with_the_numbers(church):
    c = church
    rid = asked(c, needs={c.greeter: 2, c.usher: 1})["request"]["id"]
    r = answer(c, rid, needs={c.greeter: 3})
    assert r.status_code == 200, r.text
    d = event_dates(c, E_LOCK)
    assert len(d) == 1 and d[0]["needs"] == {c.greeter: 3}
    assert (d[0]["title"], d[0]["place"], d[0]["starts_at"]) == ("Youth Lock-in", "Fellowship hall",
                                                                 "2026-10-30T23:00:00+00:00")
    row = rows(c)[0]
    assert (row["status"], row["service_id"], row["needs"], row["decided_by_name"]) == ("on", d[0]["id"],
                                                                                         {c.greeter: 3}, "Laquesha")
    # Its numbers are checked like an ask's.
    rid2 = asked(c, entry=E_OUT)["request"]["id"]
    r = answer(c, rid2, needs={c.sound: 1})
    assert r.status_code == 400 and "Sound isn't one of the Volunteers' places" in r.json()["detail"]
    assert answer(c, rid2, "maybe").status_code == 400
    assert rows(c)[1]["status"] == "waiting"


def test_no_needs_a_note_and_the_event_may_ask_again(church):
    c = church
    rid = asked(c)["request"]["id"]
    r = answer(c, rid, "no")
    assert r.status_code == 400 and r.json()["detail"] == "Say why, so Shapretta knows what to do next."
    r = answer(c, rid, "no", note="The teams are at the retreat that weekend.")
    assert r.status_code == 200 and r.json()["request"]["status"] == "declined"
    assert event_dates(c) == []
    r = answer(c, rid)
    assert r.status_code == 409 and r.json()["detail"] == "Already answered by Laquesha."
    pic = c.as_("shapretta").get(f"/church/event-volunteers/{E_LOCK}?business_id={BIZ}").json()
    assert pic["request"]["decided_note"] == "The teams are at the retreat that weekend."
    assert asked(c)["request"]["status"] == "waiting", "a no is final; the event may ask again"


def test_two_yeses_at_once_make_one_event_date(church, monkeypatch):
    c = church
    rid = asked(c)["request"]["id"]
    real = c.db.patch
    raced = {"done": False}

    def patch(path, body):
        # Dee pressed yes a moment sooner: the row stopped waiting between
        # Laquesha's read and her claim.
        if not raced["done"] and "status=eq.waiting" in path and body.get("status") == "on":
            raced["done"] = True
            rows(c)[0].update(status="on", decided_by="u-admin", decided_by_name="Dee", decided_at=NOW.isoformat())
        return real(path, body)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    r = answer(c, rid)
    assert r.status_code == 409 and r.json()["detail"] == "Already answered by Dee."
    assert event_dates(c) == [], "the second yes made nothing"
    # And one after the other: the second is told who answered.
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", real)
    clear(c)
    rid = asked(c)["request"]["id"]
    assert answer(c, rid, who="admin").status_code == 200
    r = answer(c, rid, who="laquesha")
    assert r.status_code == 409 and r.json()["detail"] == "Already answered by Dee."
    assert len(event_dates(c)) == 1


def test_a_yes_that_cant_make_the_date_leaves_the_ask_waiting(church):
    c = church
    rid = asked(c)["request"]["id"]
    # Add an event date won't put it on another way while it waits.
    r = c.as_("laquesha").post("/planning/dates", json={"business_id": BIZ, "entry_id": E_LOCK})
    assert r.status_code == 409 and r.json()["detail"] == ("This event already asked for volunteers. Answer its ask "
                                                           "on Who serves when instead.")
    assert event_dates(c) == []
    # One made another way all the same (a date from before the ask's table).
    c.db.t["worship_services"].append({"id": str(uuidlib.uuid4()), "business_id": BIZ, "title": "Youth Lock-in",
                                       "starts_at": "2026-10-30T23:00:00+00:00", "kind": "event", "place": "",
                                       "event_entry_id": E_LOCK, "archived_at": None, "is_template": False,
                                       "items": []})
    r = answer(c, rid)
    assert r.status_code == 409 and r.json()["detail"] == "That event is already on Who serves when."
    row = rows(c)[0]
    assert (row["status"], row["decided_by"], row["service_id"], row["needs"]) == ("waiting", None, None, {c.greeter: 2})
    assert len(event_dates(c)) == 1


def test_an_event_that_already_happened_is_cancelled(church):
    c = church
    rid = asked(c)["request"]["id"]
    entry = next(e for e in c.db.t["module_entries"] if e["id"] == E_LOCK)
    entry["data"]["date"] = "2026-10-20T18:00"
    r = answer(c, rid)
    assert r.status_code == 409 and r.json()["detail"] == "The Youth Lock-in has already happened."
    assert rows(c)[0]["status"] == "cancelled" and event_dates(c) == []
    # And one taken off Services & Events.
    entry["data"]["date"] = "2026-10-30T18:00"
    rid = asked(c)["request"]["id"]
    entry["status"] = "archived"
    r = answer(c, rid)
    assert r.status_code == 409 and "isn't in Services & Events anymore" in r.json()["detail"]
    assert rows(c)[1]["status"] == "cancelled"


# ─── a date's numbers on Who serves when (6.4) ───────────────────────


def test_changing_a_dates_numbers(church):
    c = church
    rid = asked(c, needs={c.greeter: 2, c.usher: 2})["request"]["id"]
    sid = answer(c, rid).json()["date"]["id"]

    def put(needs, who="laquesha"):
        return c.as_(who).put(f"/planning/dates/{sid}/needs", json={"business_id": BIZ, "needs": needs})

    a = c.as_("laquesha").post("/planning/ask", json={"business_id": BIZ, "service_id": sid, "position_id": c.usher,
                                                      "slot": 2, "contact_id": ANA})
    assert a.status_code == 200, a.text
    o = c.as_("laquesha").post("/planning/offer", json={"business_id": BIZ, "service_id": sid,
                                                        "position_id": c.greeter, "slot": 2})
    assert o.status_code == 200, o.text
    r = put({c.greeter: 2, c.usher: 1})
    assert r.status_code == 409 and r.json()["detail"] == "Someone was asked for Usher 2. Take that ask back first."
    r = put({c.greeter: 2})
    assert r.status_code == 409 and r.json()["detail"] == "Someone was asked for Usher 2. Take that ask back first."
    r = put({c.usher: 2, c.sound: 1})
    assert r.status_code == 400 and "Sound isn't one of the Volunteers' places" in r.json()["detail"]
    # Lowering Greeter takes its open spot (offered to the team) with it.
    r = put({c.greeter: 1, c.usher: 2})
    assert r.status_code == 200 and r.json()["needed"] == {c.greeter: 1, c.usher: 2}
    assert [x["position_id"] for x in c.db.t["serve_assignments"] if x["service_id"] == sid] == [c.usher]
    assert event_dates(c)[0]["needs"] == {c.greeter: 1, c.usher: 2}
    assert rows(c)[0]["needs"] == {c.greeter: 1, c.usher: 2}, "the ask that made it reads the truth"
    # Back to the Sunday numbers (the API keeps it; the page doesn't offer it).
    r = put(None)
    assert r.status_code == 200 and r.json()["needed"] == {c.greeter: 1, c.usher: 2}
    assert event_dates(c)[0]["needs"] is None and rows(c)[0]["needs"] == {c.greeter: 1, c.usher: 2}
    # Only an event date: never a Sunday.
    assert c.as_("laquesha").put(f"/planning/dates/{c.s1}/needs", json={"business_id": BIZ, "needs": None}).status_code == 404
    assert c.as_("shapretta").put(f"/planning/dates/{sid}/needs", json={"business_id": BIZ, "needs": None}).status_code == 403
    assert c.as_("laquesha").put(f"/planning/dates/{sid}/needs", json={"business_id": BIZ}).status_code == 400


# ─── the switch and the migration ────────────────────────────────────


def test_the_switch(church, monkeypatch):
    c = church
    rid = asked(c)["request"]["id"]
    monkeypatch.setenv("EVENT_VOLUNTEERS", "off")
    assert status(c, "laquesha") == {"enabled": False, "ready": True, "can_ask": False, "can_schedule": False,
                                     "teams": [], "holders": []}
    assert ask(c, entry=E_OUT).status_code == 404
    assert c.as_("shapretta").patch(f"/church/event-volunteers/{E_LOCK}/request",
                                    json={"business_id": BIZ, "note": "x"}).status_code == 404
    assert answer(c, rid).status_code == 404
    assert c.as_("laquesha").get(f"/planning/requests?business_id={BIZ}").status_code == 404
    assert c.as_("laquesha").get(f"/planning/schedule?business_id={BIZ}").json()["requests_waiting"] == 0
    # It never hides what is there, and a waiting ask can always be taken back.
    assert c.as_("shapretta").get(f"/church/event-volunteers/{E_LOCK}?business_id={BIZ}").status_code == 200
    r = c.as_("shapretta").delete(f"/church/event-volunteers/{E_LOCK}/request?business_id={BIZ}")
    assert r.status_code == 200
    # owner (the default): the platform owner's own church, or login.
    monkeypatch.delenv("EVENT_VOLUNTEERS")
    assert evv.mode() == "owner"
    assert ask(c, "shapretta").status_code == 404
    assert status(c, "owner")["enabled"] is True
    monkeypatch.setattr(member_asks, "platform_church", lambda biz: biz == BIZ)
    assert ask(c, "shapretta").status_code == 200
    # Only where event dates are open too: an ask's yes makes one.
    monkeypatch.setenv("EVENT_VOLUNTEERS", "on")
    monkeypatch.setenv("CHURCH_EVENT_VOLUNTEERS", "off")
    assert ask(c, "shapretta", entry=E_OUT).status_code == 404
    assert evv.open_for(BIZ) is False
    monkeypatch.setenv("CHURCH_EVENT_VOLUNTEERS", "on")
    monkeypatch.setenv("EVENT_VOLUNTEERS", "yes please")
    assert evv.mode() == "off" and evv.open_for(BIZ) is False


def test_before_the_migration_nothing_selects_needs_and_nothing_breaks(church, monkeypatch):
    c = church
    rid = asked(c)["request"]["id"]
    sid = answer(c, rid).json()["date"]["id"]
    monkeypatch.setattr(evv, "_FORCE", False)
    seen = []
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: seen.append(path) or real(path))
    assert status(c, "laquesha")["enabled"] is False
    for path in (f"/church/event-volunteers/{E_LOCK}?business_id={BIZ}", f"/planning/requests?business_id={BIZ}"):
        assert c.as_("laquesha").get(path).status_code == 404, path
    assert ask(c, entry=E_OUT).status_code == 404
    assert answer(c, rid).status_code == 404
    assert c.as_("laquesha").put(f"/planning/dates/{sid}/needs", json={"business_id": BIZ, "needs": None}).status_code == 404
    j = c.as_("laquesha").get(f"/planning/schedule?business_id={BIZ}&weeks=2").json()
    assert j["requests_waiting"] == 0
    c.as_("laquesha").get(f"/planning/candidates?business_id={BIZ}&service_id={sid}&position_id={c.greeter}")
    import re
    assert seen and not [p for p in seen if re.search(r"[,=]needs(&|,|$)", p) or "event_volunteer_requests" in p]
    # Applied: the reads select it.
    monkeypatch.setattr(evv, "_FORCE", True)
    seen.clear()
    c.as_("laquesha").get(f"/planning/schedule?business_id={BIZ}&weeks=2")
    assert any("worship_services" in p and ",needs" in p for p in seen)
    assert sd.fields() == ",kind,place,event_entry_id,needs"


def test_the_column_and_table_are_asked_about_once(monkeypatch):
    calls = []
    monkeypatch.setattr(evv, "_FORCE", None)
    monkeypatch.setenv("SUPABASE_URL", "https://sb.test")
    for missing in ({"status": 400, "code": "42703", "message": "column worship_services.needs does not exist"},
                    {"status": 404, "code": "PGRST205", "message": "Could not find the table"},
                    {"status": 404, "code": "42P01", "message": "relation does not exist"}):
        monkeypatch.setattr(evv, "_STATE", {"yes": None, "at": 0.0})
        calls.clear()
        table_missing = missing["code"] != "42703"
        monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: calls.append(path) or (
            [] if table_missing and "worship_services" in path else None))
        monkeypatch.setattr(sb_clients, "last_error", lambda m=missing: m)
        assert evv.ready() is False and evv.ready() is False, missing
        assert len(calls) == (2 if table_missing else 1), "kept for a minute"
    # Applied: both answer, and that is kept.
    monkeypatch.setattr(evv, "_STATE", {"yes": None, "at": 0.0})
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: calls.append(path) or [])
    assert evv.ready() is True
    # A blip later keeps what was known.
    monkeypatch.setattr(evv, "_STATE", {"yes": True, "at": 0.0})
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: None)
    monkeypatch.setattr(sb_clients, "last_error", lambda: {"status": 503, "code": "", "message": "down"})
    assert evv.ready() is True
    # No database to ask: not there.
    monkeypatch.delenv("SUPABASE_URL")
    monkeypatch.setattr(evv, "_STATE", {"yes": None, "at": 0.0})
    assert evv.ready() is False


# ─── the picture (6.11) and the status ───────────────────────────────


def test_the_status_says_what_the_new_event_questions_need(church):
    st = status(church, "shapretta")
    assert st["enabled"] is True and st["ready"] is True and st["holders"] == ["Laquesha"]
    assert st["teams"] == [{"group_id": WELCOME, "name": "Welcome", "places": [
        {"id": church.greeter, "name": "Greeter", "needed": 1}, {"id": church.usher, "name": "Usher", "needed": 2}]}]
    assert "Sound" not in str(st), "ChurchSavvy's places are never an event's"


def test_the_events_volunteer_picture(church, monkeypatch):
    c = church
    path = f"/church/event-volunteers/{E_LOCK}?business_id={BIZ}"
    pic = c.as_("shapretta").get(path).json()
    assert pic["request"] is None and pic["date"] is None and pic["teams"] == []
    assert pic["special"] == [
        {"role_id": "chap", "label": "Chaperones", "needed": 3, "kids": True, "open": False,
         # S3: a kids role's people say whether their check is current
         # (church_serving.cleared), for a login that reads who's cleared.
         "people": [{"name": "Ana Cruz", "contact_id": ANA, "checked": False, "check": "No check on file"}]},
        {"role_id": "grill", "label": "Grill", "needed": 1, "kids": False, "open": True,
         "people": [{"name": "Lee Ford"}]}]
    assert pic["counts"] == {"all": 4, "yes": 2, "teams_needed": 0, "teams_yes": 0, "special_needed": 4,
                             "special_yes": 2}
    assert pic["flyer"] is None and pic["serve_minutes"] == 120
    # Waiting: the asked numbers, every slot open and pending.
    asked(c, needs={c.greeter: 2})
    pic = c.as_("shapretta").get(path).json()
    assert pic["request"]["status"] == "waiting" and pic["date"] is None
    # Change and take back are offered to whoever the server lets do them: the
    # one who asked and whoever schedules the teams, never another login or a Viewer.
    assert {who: c.as_(who).get(path).json()["request"]["can_change"]
            for who in ("shapretta", "laquesha", "owner", "tiara", "viewer")} == {
        "shapretta": True, "laquesha": True, "owner": True, "tiara": False, "viewer": False}
    assert pic["teams"] == [{"place_id": c.greeter, "name": "Greeter", "team": "Welcome", "needed": 2, "pending": True,
                             "slots": [{"slot": 1, "state": "open"}, {"slot": 2, "state": "open"}]}]
    assert pic["counts"]["teams_needed"] == 2 and pic["counts"]["all"] == 6
    # On: each slot as it stands, with names for whoever reads Who serves when.
    sid = answer(c, pic["request"]["id"]).json()["date"]["id"]
    c.as_("laquesha").post("/planning/ask", json={"business_id": BIZ, "service_id": sid, "position_id": c.greeter,
                                                  "slot": 2, "contact_id": JO})
    pic = c.as_("shapretta").get(path).json()
    assert pic["date"] == {"service_id": sid, "starts_at": "2026-10-30T23:00:00+00:00", "needs": {c.greeter: 2}}
    assert pic["teams"] == [{"place_id": c.greeter, "name": "Greeter", "team": "Welcome", "needed": 2,
                             "slots": [{"slot": 1, "state": "open"}, {"slot": 2, "state": "asked", "name": "Jo Park"}]}]
    # A login that can't read Who serves when gets the states without names.
    monkeypatch.setenv("SUNDAY_PLANNING", "owner")
    pic = c.as_("owner").get(path).json()
    assert pic["teams"][0]["slots"][1] == {"slot": 2, "state": "asked", "name": "Jo Park"}
    monkeypatch.setattr(sp, "open_to", lambda user: False)
    pic = c.as_("shapretta").get(path).json()
    assert pic["teams"][0]["slots"][1] == {"slot": 2, "state": "asked"}
    # The office's helper minutes, kept within 15 to 720.
    entry = next(e for e in c.db.t["module_entries"] if e["id"] == E_LOCK)
    for given, want in ((90, 90), (5, 15), (9000, 720), ("60", 120), (True, 120)):
        entry["data"]["_serve_minutes"] = given
        assert c.as_("shapretta").get(path).json()["serve_minutes"] == want, given


def test_the_flyer_is_checked_on_every_read(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://sb.test/")
    base = f"https://sb.test/storage/v1/object/public/business-assets/{BIZ}/event-flyers/{E_LOCK}/"
    # S3: the event's own folder and the copies' names, pinned (flyer_of takes the entry too).
    f = "a7700000-0000-4000-8000-0000000000aa"
    good = {"url": base + f + ".jpg", "thumb": base + f + "-thumb.jpg", "w": 1600, "h": 900, "artwork_id": f, "at": "now"}
    assert evv.flyer_of({"_flyer": good}, BIZ, E_LOCK) == {"url": base + f + ".jpg", "thumb": base + f + "-thumb.jpg",
                                                           "w": 1600, "h": 900}
    assert evv.flyer_of({"_flyer": good}, BIZ.upper(), E_LOCK) is not None
    for bad in ({"url": "https://evil.test/f.jpg"}, {"thumb": base.replace(BIZ, OTHER) + "t.jpg"},
                {"url": base + "../../x.jpg"}, {"url": base + 'f.jpg" onerror="x'}, {"url": base},
                {"w": 0}, {"h": 8001}, {"w": True}, {"w": "1600"}, {"thumb": None}):
        assert evv.flyer_of({"_flyer": {**good, **bad}}, BIZ, E_LOCK) is None, bad
    for data in (None, {}, {"_flyer": "x"}, {"_flyer": []}, "nope"):
        assert evv.flyer_of(data, BIZ, E_LOCK) is None
    assert evv.flyer_of({"_flyer": good}, OTHER, E_LOCK) is None and evv.flyer_of({"_flyer": good}, "nope", E_LOCK) is None
    assert evv.flyer_of({"_flyer": good}, BIZ, E_OUT) is None, "another event's flyer"
    monkeypatch.delenv("SUPABASE_URL")
    assert evv.flyer_of({"_flyer": good}, BIZ, E_LOCK) is None


# ─── Sunday afternoons (6.9) and typed dates (6.8) ───────────────────


def test_a_sunday_afternoon_event_date(church, monkeypatch):
    c = church

    def add(**body):
        return c.as_("laquesha").post("/planning/dates", json={"business_id": BIZ, "title": "Fellowship dinner",
                                                                "day": "2026-10-25", "time": "17:00", **body})
    r = add(time="11:30")
    assert r.status_code == 400 and r.json()["detail"] == sp.SUNDAY_CLASH
    r = add(time="08:45")
    assert r.status_code == 400 and r.json()["detail"] == sp.SUNDAY_CLASH, "before the service too"
    r = add(time="12:30")
    assert r.status_code == 200 and r.json()["date"]["weekday"] == "Sunday"
    # From Services & Events: the afternoon one is offered, the morning one isn't.
    clear(c)
    c.db.t["module_entries"] = [e for e in c.db.t["module_entries"] if e["data"].get("_visibility") != "private"]
    got = [e["title"] for e in c.as_("laquesha").get(f"/planning/events?business_id={BIZ}").json()["events"]]
    assert "Fellowship dinner" in got and "Sunday worship" not in got
    assert asked(c, "laquesha", entry=E_SUN_PM)["date"]["day"] == "2026-10-25"
    # Its words carry its title, never Sunday's service.
    import member_portal_serving as mps
    import sunday_serving_alerts as ssa
    at = datetime(2026, 10, 25, 17, 0, tzinfo=ZONE)
    assert ssa._day(at, True) == "Sunday, Oct 25" and ssa._for("Fellowship dinner", at, True) == " for Fellowship dinner"
    assert ssa._day(at) == "Oct 25" and ssa._for("Fellowship dinner", at) == ""
    assert mps._occasion(at, "Fellowship dinner", True) == "Sunday, Oct 25 · Fellowship dinner"
    assert mps._starts(at, True, True) == "Starts at 5:00 PM" and mps._starts(at, True) == "Service at 5:00 PM"
    # With the switch closed, a Sunday is Add the next five Sundays', as before.
    monkeypatch.setenv("EVENT_VOLUNTEERS", "off")
    r = add(title="Another dinner")
    assert r.status_code == 400 and "Add the next five Sundays" in r.json()["detail"]
    assert "Fellowship dinner" not in [
        e["title"] for e in c.as_("laquesha").get(f"/planning/events?business_id={BIZ}").json()["events"]]


def test_a_typed_date_becomes_an_event(church, monkeypatch):
    c = church
    c.db.t["custom_modules"].insert(0, {"id": MOD2, "business_id": BIZ, "name": "Classes", "archetype": "event_roster",
                                        "is_active": True, "archetype_params": {"title_field": "name"},
                                        "created_at": "2026-05-01T00:00:00+00:00"})

    def add(**body):
        return c.as_("laquesha").post("/planning/dates", json={
            "business_id": BIZ, "title": "Prayer night", "day": "2026-10-29", "time": "19:00", "place": "Chapel",
            **body})
    before = len(c.db.t["module_entries"])
    r = add()
    assert r.status_code == 200, r.text
    made = r.json()["event"]
    assert made and made["module_id"] == MOD, "the church's first events room: the oldest"
    entry = next(e for e in c.db.t["module_entries"] if e["id"] == made["entry_id"])
    assert entry["data"] == {"title": "Prayer night", "date": "2026-10-29T19:00", "location": "Chapel",
                             "_visibility": "private", "signups": [], "_roles": []}
    assert entry["status"] == "active" and entry["business_id"] == BIZ
    assert r.json()["date"]["event_entry_id"] == made["entry_id"]
    # The entry can't be written: nothing is.
    real = c.db.post

    def no_entries(path, body, prefer=None, **kw):
        return None if path.startswith("/module_entries") else real(path, body, prefer, **kw)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", no_entries)
    r = add(title="Choir night")
    assert r.status_code == 503 and not [s for s in event_dates(c) if s["title"] == "Choir night"]

    # The date can't be written: the entry comes back out.
    def no_dates(path, body, prefer=None, **kw):
        return None if path.startswith("/worship_services") else real(path, body, prefer, **kw)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", no_dates)
    r = add(title="Choir night")
    assert r.status_code == 503 and len(c.db.t["module_entries"]) == before + 1
    monkeypatch.setattr(sb_clients, "sb_post_as_service", real)
    # No events room: typed-only, as before.
    c.db.t["custom_modules"] = []
    r = add(title="Men's breakfast", day="2026-10-31", time="08:00")
    assert r.status_code == 200 and r.json()["event"] is None and r.json()["date"]["event_entry_id"] is None
    # The switch closed: typed-only too.
    c.db.t["custom_modules"] = [{"id": MOD, "business_id": BIZ, "archetype": "event_roster", "is_active": True,
                                 "archetype_params": {}, "created_at": "2026-01-01T00:00:00+00:00"}]
    monkeypatch.setenv("EVENT_VOLUNTEERS", "off")
    r = add(title="Youth game night", day="2026-11-04")
    assert r.status_code == 200 and r.json()["event"] is None
    assert len(c.db.t["module_entries"]) == before + 1


# ─── notices (7.1, 7.2) ──────────────────────────────────────────────


def test_whoever_schedules_the_teams_is_told_of_an_ask_once(church):
    c = church
    got = asked(c, needs={c.greeter: 2, c.usher: 1})
    assert [t["uid"] for t in c.told] == ["u-laquesha"]
    t = c.told[0]
    assert t["title"] == "Shapretta asked for volunteers"
    assert t["text"].startswith("Shapretta asked for volunteers for the Youth Lock-in, Friday, Oct 30, 6:00 PM: "
                                "2 on Greeter and 1 on Usher.")
    assert "Open Who serves when to answer." in t["body"] and "—" not in str(t)
    assert rows(c)[0]["told_at"] == NOW.isoformat()
    # Told once: a second try, and the sweep, send nothing.
    church_row = evv._business(BIZ)
    assert evv.tell_ask(church_row, rows(c)[0], now=NOW) == "none"
    # Another replica holding the row as it was before it was told: its claim
    # finds the ledger marked, and nothing goes.
    assert evv.tell_ask(church_row, {**rows(c)[0], "told_at": None}, now=NOW) == "taken" and len(c.told) == 1
    later = NOW + timedelta(minutes=10)
    assert evv.sweep_tick(later)["told"] == 0 and len(c.told) == 1
    # Taken back by the one who asked: they hear that too, straight after.
    c.as_("shapretta").delete(f"/church/event-volunteers/{E_LOCK}/request?business_id={BIZ}")
    assert [(x["uid"], x["title"]) for x in c.told[1:]] == [("u-laquesha", "Shapretta took back the ask for the Youth Lock-in")]
    assert got["request"]["id"]


def test_a_failed_send_is_told_by_the_sweep_and_quiet_hours_hold(church):
    c = church
    c.sends["ok"] = False
    asked(c)
    assert rows(c)[0]["told_at"] is None, "nothing went: the claim is let go"
    c.sends["ok"] = True
    assert evv.sweep_tick(NOW + timedelta(seconds=30))["told"] == 0, "too new: the write's own send goes first"
    c.quiet["on"] = True
    assert evv.sweep_tick(NOW + timedelta(minutes=15))["held"] == 1 and rows(c)[0]["told_at"] is None
    c.quiet["on"] = False
    n = len(c.told)
    assert evv.sweep_tick(NOW + timedelta(minutes=30))["told"] == 1
    assert len(c.told) == n + 1 and rows(c)[0]["told_at"] is not None
    assert evv.sweep_tick(NOW + timedelta(minutes=45))["told"] == 0 and len(c.told) == n + 1, "never twice"


def test_the_organizer_hears_the_answer_once(church):
    c = church
    rid = asked(c, needs={c.greeter: 2, c.usher: 4})["request"]["id"]
    c.told.clear()
    answer(c, rid, needs={c.greeter: 2, c.usher: 3})
    assert [t["uid"] for t in c.told] == ["u-shapretta"]
    assert c.told[0]["body"] == "Laquesha put the Youth Lock-in on the schedule, with 3 on Usher instead of 4. " \
                                "Asks go out to the teams."
    assert rows(c)[0]["answer_told_at"] == NOW.isoformat()
    assert evv.sweep_tick(NOW + timedelta(minutes=10))["answers"] == 0 and len(c.told) == 1
    # A no, with the note, to the organizer; a failed send waits for the sweep.
    clear(c)
    rid = asked(c, entry=E_OUT)["request"]["id"]
    c.told.clear()
    c.sends["ok"] = False
    answer(c, rid, "no", note="Every greeter is at the retreat.")
    assert rows(c)[0]["answer_told_at"] is None
    c.sends["ok"] = True
    assert evv.sweep_tick(NOW + timedelta(minutes=10))["answers"] == 1
    last = c.told[-1]
    assert last["uid"] == "u-shapretta" and last["text"].startswith(
        "Laquesha can't staff the Outreach night with the teams: “Every greeter is at the retreat.”")
    # The sweep, which can't know what changed, says the numbers it went on with.
    clear(c)
    rid = asked(c)["request"]["id"]
    c.sends["ok"] = False
    answer(c, rid)
    c.sends["ok"] = True
    evv.sweep_tick(NOW + timedelta(minutes=10))
    assert c.told[-1]["body"] == "Laquesha put the Youth Lock-in on the schedule with 2 on Greeter. Asks go out to the teams."


def test_straight_on_tells_the_holders_but_never_the_one_who_did_it(church):
    c = church
    asked(c, "laquesha")
    assert c.told == [], "Laquesha holds the duty and did it herself"
    assert rows(c)[0]["told_at"] is not None and rows(c)[0]["answer_told_at"] is not None
    clear(c)
    asked(c, "owner", needs={c.usher: 1})
    assert [t["uid"] for t in c.told] == ["u-laquesha"]
    assert c.told[0]["title"] == "Pastor Kevin put the Youth Lock-in on Who serves when"
    assert c.told[0]["body"] == "Friday, Oct 30: 1 on Usher."
    # Nobody holds the duty: the owner hears of an ask (and not of their own).
    clear(c)
    DUTIES_ = dict(DUTIES)
    try:
        DUTIES["u-laquesha"] = {"events"}
        asked(c, "shapretta")
        assert [t["uid"] for t in c.told] == ["u-owner"]
        clear(c)
        asked(c, "owner")
        assert c.told == []
    finally:
        DUTIES.clear()
        DUTIES.update(DUTIES_)


def test_notices_go_quiet_with_the_switch_and_for_a_sample_church(church, monkeypatch):
    c = church
    c.sends["ok"] = False
    asked(c)
    c.sends["ok"] = True
    monkeypatch.setenv("EVENT_VOLUNTEERS", "off")
    seen = []
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: seen.append(path) or real(path))
    assert evv.sweep_tick(NOW + timedelta(minutes=30)) == {"churches": 0, "told": 0, "answers": 0, "held": 0,
                                                            "unsent": 0, "mended": 0}
    assert seen == [], "not one read with the switch off"
    monkeypatch.setenv("EVENT_VOLUNTEERS", "on")
    import sample_church
    monkeypatch.setattr(sample_church, "skip", lambda row: True)
    assert evv.sweep_tick(NOW + timedelta(minutes=30))["told"] == 0 and rows(c)[0]["told_at"] is None


def test_every_refusal_says_what_to_do_next(church):
    """Plain church words: no system words, no em-dashes."""
    import re
    words = [v for k, v in vars(evv).items() if k.isupper() and isinstance(v, str) and " " in v]
    words.append(sp.SUNDAY_CLASH)
    for w in words:
        assert "—" not in w and not re.search(r"\b(request|entry|module|service_id|null|404|error)\b", w), w


# ─── the review's fixes ──────────────────────────────────────────────


def test_taking_the_date_off_closes_its_ask(church, monkeypatch):
    c = church
    sid = asked(c, "laquesha")["date"]["id"]
    # The ask's row can't be closed: the date stays, and it is said plainly.
    real = c.db.patch
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body, **k: None if path.startswith("/event_volunteer_requests") else real(path, body))
    r = c.as_("laquesha").delete(f"/planning/dates/{sid}?business_id={BIZ}")
    assert r.status_code == 503 and len(event_dates(c, E_LOCK)) == 1 and rows(c)[0]["status"] == "on"
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", real)
    r = c.as_("laquesha").delete(f"/planning/dates/{sid}?business_id={BIZ}")
    assert r.status_code == 200 and event_dates(c, E_LOCK) == []
    assert rows(c)[0]["status"] == "cancelled", "never on with no date"
    pic = c.as_("shapretta").get(f"/church/event-volunteers/{E_LOCK}?business_id={BIZ}").json()
    assert pic["request"]["status"] == "cancelled" and pic["date"] is None
    # The event may ask again, and nobody was told of the take-off.
    assert c.told == [] and asked(c, "laquesha")["request"]["status"] == "on"


def _thirty_dates(c):
    for n in range(sp.MAX_EVENT_DATES):
        c.db.t["worship_services"].append({"id": str(uuidlib.uuid4()), "business_id": BIZ, "title": f"Night {n}",
                                           "starts_at": "2026-11-05T00:00:00+00:00", "kind": "event",
                                           "archived_at": None, "is_template": False, "items": []})


def test_straight_on_whose_undo_fails_is_mended_without_a_word(church, monkeypatch):
    c = church
    _thirty_dates(c)
    real = c.db.delete
    monkeypatch.setattr(sb_clients, "sb_delete_as_service",
                        lambda path: False if path.startswith("/event_volunteer_requests") else real(path))
    r = ask(c, "owner")
    assert r.status_code == 400 and "30 event dates" in r.json()["detail"]
    assert [(x["status"], x["service_id"]) for x in rows(c)] == [("on", None)], "left on: the undo failed"
    assert c.told == [], "no notice for an ask that is on with no date"
    later = NOW + timedelta(minutes=5)
    got = evv.sweep_tick(later)
    assert got["mended"] == 1 and rows(c)[0]["status"] == "cancelled" and c.told == []
    assert evv.sweep_tick(later + timedelta(minutes=15))["told"] == 0 and c.told == []


def test_a_yes_whose_release_fails_waits_again_after_the_sweep(church, monkeypatch):
    c = church
    rid = asked(c)["request"]["id"]
    c.told.clear()
    _thirty_dates(c)
    real = c.db.patch
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body, **k: None if body.get("status") == "waiting" else real(path, body))
    r = answer(c, rid)
    assert r.status_code == 400
    assert (rows(c)[0]["status"], rows(c)[0]["service_id"]) == ("on", None)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", real)
    assert evv.tell_answer(evv._business(BIZ), rows(c)[0], now=NOW) == "none", "on with no date: nothing to say"
    assert evv.tell_ask(evv._business(BIZ), {**rows(c)[0], "decided_by": rows(c)[0]["asked_by"], "told_at": None},
                        now=NOW) == "none" and c.told == []
    assert evv.sweep_tick(NOW + timedelta(minutes=5))["mended"] == 1
    row = rows(c)[0]
    assert (row["status"], row["decided_by"], row["needs"]) == ("waiting", None, {c.greeter: 2})
    assert c.told == [], "the organizer is never told it went on"


def test_a_date_made_is_never_a_503(church, monkeypatch):
    c = church
    real = c.db.patch

    def no_link(path, body, **k):
        return None if "service_id" in body and len(body) == 1 else real(path, body)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", no_link)
    r = ask(c, "owner")
    assert r.status_code == 200, r.text
    sid = r.json()["date"]["id"]
    assert r.json()["request"]["service_id"] == sid and len(event_dates(c, E_LOCK)) == 1
    assert [t["uid"] for t in c.told] == ["u-laquesha"], "it is on: Laquesha hears so"
    assert rows(c)[0]["service_id"] is None
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", real)
    assert evv.sweep_tick(NOW + timedelta(minutes=5))["mended"] == 1 and rows(c)[0]["service_id"] == sid
    # The answer's yes the same way.
    clear(c)
    rid = asked(c, entry=E_OUT)["request"]["id"]
    c.told.clear()
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", no_link)
    r = answer(c, rid)
    assert r.status_code == 200 and r.json()["date"]["id"] == event_dates(c, E_OUT)[0]["id"]
    assert [t["uid"] for t in c.told] == ["u-shapretta"]


def test_a_lost_answer_from_the_database_is_mended(church, monkeypatch):
    c = church
    real = c.db.post

    def lost(path, body, prefer=None, **kw):
        got = real(path, body, prefer, **kw)
        return None if path.startswith("/event_volunteer_requests") else got
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lost)
    r = ask(c, "owner")
    assert r.status_code == 503 and [(x["status"], x["service_id"]) for x in rows(c)] == [("on", None)]
    assert event_dates(c) == [] and c.told == []
    monkeypatch.setattr(sb_clients, "sb_post_as_service", real)
    assert evv.sweep_tick(NOW + timedelta(minutes=5))["mended"] == 1 and rows(c)[0]["status"] == "cancelled"
    assert asked(c, "owner")["request"]["status"] == "on", "the event may ask again"
    # A yes whose claim came back lost: it waits again after the sweep.
    clear(c)
    rid = asked(c, entry=E_OUT)["request"]["id"]
    c.told.clear()
    real_patch = c.db.patch

    def lost_claim(path, body, **k):
        got = real_patch(path, body)
        return None if body.get("status") == "on" else got
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lost_claim)
    assert answer(c, rid).status_code == 503 and rows(c)[0]["status"] == "on"
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", real_patch)
    assert evv.sweep_tick(NOW + timedelta(minutes=5))["mended"] == 1 and rows(c)[0]["status"] == "waiting"
    assert c.told == []


def test_an_unplanned_sunday_keeps_the_usual_service_times(church):
    c = church

    def add(day, at, title="Fellowship lunch"):
        return c.as_("laquesha").post("/planning/dates", json={"business_id": BIZ, "title": title, "day": day,
                                                                "time": at})
    # Nov 15 isn't planned; the church's Sundays are at 10:30.
    assert not [s for s in c.db.t["worship_services"] if s["starts_at"].startswith("2026-11-15")]
    r = add("2026-11-15", "10:30")
    assert r.status_code == 400 and r.json()["detail"] == sp.SUNDAY_CLASH
    assert add("2026-11-15", "11:45").status_code == 400
    assert add("2026-11-15", "15:00").status_code == 200
    # From Services & Events, the ask, and straight on: the same rule.
    unplanned = "e1000000-0000-4000-8000-000000000099"
    c.db.t["module_entries"].append({"id": unplanned, "business_id": BIZ, "module_id": MOD, "status": "active",
                                     "created_at": NOW.isoformat(),
                                     "data": {"title": "Baptism class", "date": "2026-11-15T11:00"}})
    got = [e["title"] for e in c.as_("laquesha").get(f"/planning/events?business_id={BIZ}").json()["events"]]
    assert "Baptism class" not in got and "Fellowship dinner" in got
    for who in ("shapretta", "laquesha"):
        r = ask(c, who, entry=unplanned)
        assert r.status_code == 400 and r.json()["detail"] == sp.SUNDAY_CLASH, who
    # The usual times are the church's own: a 9 AM church refuses 9:30, not 11:30.
    for s in c.db.t["worship_services"]:
        if s.get("kind") != "event":
            local = datetime.fromisoformat(s["starts_at"]).astimezone(ZONE).replace(hour=9, minute=0)
            s["starts_at"] = local.astimezone(timezone.utc).isoformat()
    assert [t.strftime("%H:%M") for t in sp.usual_sunday_times(BIZ, ZONE)] == ["09:00"]
    assert add("2026-11-22", "09:30", "Choir").status_code == 400
    assert add("2026-11-22", "11:30", "Choir").status_code == 200
    # With no Sunday at all, Add the next five Sundays' 10:30.
    for s in c.db.t["worship_services"]:
        if s.get("kind") != "event":
            s["archived_at"] = NOW.isoformat()
    assert [t.strftime("%H:%M") for t in sp.usual_sunday_times(BIZ, ZONE)] == ["10:30"]
    assert add("2026-11-29", "11:00", "Hymn sing").status_code == 400
    assert add("2026-11-29", "13:00", "Hymn sing").status_code == 200


def test_the_answer_sees_the_sunday_rule_and_says_its_own_words(church):
    c = church
    rid = asked(c)["request"]["id"]
    entry = next(e for e in c.db.t["module_entries"] if e["id"] == E_LOCK)
    entry["data"]["date"] = "2026-11-15T10:45"
    r = answer(c, rid)
    assert r.status_code == 409 and r.json()["detail"] == sp.SUNDAY_CLASH and rows(c)[0]["status"] == "waiting"
    entry["data"]["date"] = "2027-06-05T18:00"
    r = answer(c, rid)
    assert r.status_code == 404
    assert r.json()["detail"] == "The Youth Lock-in isn't coming up in Services & Events anymore."
    assert rows(c)[0]["status"] == "waiting" and event_dates(c) == []


def test_an_ask_that_lands_while_the_numbers_change(church, monkeypatch):
    c = church
    sid = asked(c, "laquesha", needs={c.greeter: 1, c.usher: 2})["date"]["id"]
    real = c.db.patch

    def racing(path, body, **k):
        if path.startswith("/worship_services") and body.get("needs") == {c.greeter: 1, c.usher: 1}:
            # Someone asked Ana for Usher 2 between the check and the write.
            c.db.t["serve_assignments"].append({"id": str(uuidlib.uuid4()), "business_id": BIZ, "service_id": sid,
                                                "position_id": c.usher, "slot": 2, "contact_id": ANA,
                                                "status": "asked", "notified_at": None, "note": "", "swap_to": None})
        return real(path, body)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", racing)
    r = c.as_("laquesha").put(f"/planning/dates/{sid}/needs",
                              json={"business_id": BIZ, "needs": {c.greeter: 1, c.usher: 1}})
    assert r.status_code == 409 and r.json()["detail"] == "Someone was asked for Usher 2. Take that ask back first."
    assert event_dates(c, E_LOCK)[0]["needs"] == {c.greeter: 1, c.usher: 2}, "the numbers go back"
    assert rows(c)[0]["needs"] == {c.greeter: 1, c.usher: 2}
