"""The Monday leaders note (church_leaders_note.py). Kevin, 2026-10-27, the
leadership plan: every Monday the office sends one short note to all the
church's leaders (this week, what's needed, one win), drafted from the
church's own data, read over, and sent.

Pins:
  * who: the owner, admins and managers; a member or a viewer seat is
    refused, so is another church's login, and (Who sees what on) a
    manager who doesn't work the Office
  * a business that isn't a church, and the switch (off, owner, on)
  * the draft, from the church's rows: the days on its own clock (across
    the clocks changing), a plan and its own occasion said once, a room
    folded into the gathering it was booked for, a rental without its
    renter, an invite-only occasion left out, the groups meeting; what's
    needed: the Sunday places still open by team, an event's roles, people
    in follow-up with no one (a count). The win is blank
  * who gets it: the All group leaders room, one email an address, and the
    names of those with no email
  * once a week, on the church's Monday-start week; the week frees itself
    only when nothing went; the other settings keys are never touched; a
    send someone else made in between is never overwritten
  * a failed read is a 503, never an empty note
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_leaders_note as cln  # noqa: E402
import member_portal_messaging as mpm  # noqa: E402
import rate_limit  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_church_roles import FakeDB, _cmp  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
SHOP = "33333333-3333-4333-8333-333333333333"
NAMES = ("owner", "admin", "clerk", "deacon", "watcher", "stranger", "other_owner", "other_clerk", "shop_owner")
PEOPLE = {n: AuthedUser(id=f"00000000-0000-4000-8000-{i:012d}", email=f"{n}@lovecity.org", role="authenticated")
          for i, n in enumerate(NAMES, start=1)}
ID = {n: u.id for n, u in PEOPLE.items()}
NY = ZoneInfo("America/New_York")
# Monday, October 26, 2026, 10:00 AM in New York. The clocks go back at
# 2 AM on Sunday, November 1: the week straddles it.
T0 = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)

C = {k: f"cccccccc-0000-4000-8000-{n:012d}" for n, k in enumerate(
    ("hayes", "moore", "price", "reed", "ellis", "grant", "kim", "theirs"), start=1)}
SUNDAY = "dddddddd-0000-4000-8000-000000000001"
PROD, WELCOME, SMALL, YOUNG = (f"eeeeeeee-0000-4000-8000-00000000000{n}" for n in range(1, 5))
SOUND, SLIDES, GREETER = (f"ffffffff-0000-4000-8000-00000000000{n}" for n in range(1, 4))
ROSTER = "abababab-0000-4000-8000-000000000001"
SANCT, HALL = "acacacac-0000-4000-8000-000000000001", "acacacac-0000-4000-8000-000000000002"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _json(row, col):
    """settings->church_leaders_note->>id, read the way PostgREST does."""
    base, *path = re.split(r"->>?", col)
    v = row.get(base)
    for k in path:
        v = v.get(k) if isinstance(v, dict) else None
    return v


class NoteDB(FakeDB):
    """The shared fake, plus JSON-path filters and a read that can be made
    to fail."""

    def _match(self, row, filters):
        plain = []
        for f in filters:
            if f[0] != "or" and "->" in f[0]:
                if not _cmp({"v": _json(row, f[0])}, "v", f[1], f[2]):
                    return False
            else:
                plain.append(f)
        return super()._match(row, plain)

    def get(self, path, **kw):
        table = path.lstrip("/").split("?")[0]
        if table in self.failing:
            return None
        return super().get(path, **kw)


def _entry(title, when, **data):
    return {"id": f"entry-{title}", "business_id": BIZ, "module_id": ROSTER, "status": "active",
            "data": {"title": title, "date": when, **data}}


@pytest.fixture
def db(monkeypatch):
    seats = (("admin", "admin", BIZ), ("clerk", "manager", BIZ), ("deacon", "member", BIZ), ("watcher", "viewer", BIZ),
             ("other_clerk", "manager", OTHER))
    fake = NoteDB(
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": ID["owner"],
                     "settings": {"practitioner_name": "Pastor Kevin", "news": {"celebrate": "ask"},
                                  "brand_kit": {"colors": {"primary": "#7A3E9D"}}}},
                    {"id": OTHER, "name": "Grace Chapel", "type": "ministry", "owner_id": ID["other_owner"], "settings": {}},
                    {"id": SHOP, "name": "Fade Shop", "type": "barber", "owner_id": ID["shop_owner"], "settings": {}}],
        business_users=[{"business_id": b, "user_id": ID[n], "role": r, "status": "active", "invited_email": f"{n}@lovecity.org"}
                        for n, r, b in seats],
        contacts=[{"id": C["hayes"], "business_id": BIZ, "name": "Darnell Hayes", "email": "darnell@example.com"},
                  {"id": C["moore"], "business_id": BIZ, "name": "Dana Moore", "email": "dana@example.com"},
                  {"id": C["price"], "business_id": BIZ, "name": "Noah Price", "email": None},
                  {"id": C["reed"], "business_id": BIZ, "name": "Pastor Reed", "email": "reed@example.com"},
                  {"id": C["ellis"], "business_id": BIZ, "name": "Mia Ellis", "email": "not an email"},
                  # Shares the Moores' address: one email reaches both.
                  {"id": C["grant"], "business_id": BIZ, "name": "Sam Moore", "email": "DANA@example.com"},
                  {"id": C["kim"], "business_id": BIZ, "name": "Kim Lee", "email": "clerk@lovecity.org"},
                  {"id": C["theirs"], "business_id": OTHER, "name": "Grace Leader", "email": "grace@example.com"}],
        worship_services=[
            # Sunday, 10:30 AM after the clocks go back (EST, UTC-5).
            {"id": SUNDAY, "business_id": BIZ, "title": "Sunday service", "archived_at": None, "is_template": False,
             "starts_at": _iso(datetime(2026, 11, 1, 10, 30, tzinfo=NY))},
            {"id": "old", "business_id": BIZ, "title": "Archived", "archived_at": "2026-10-01", "is_template": False,
             "starts_at": _iso(datetime(2026, 10, 30, 19, 0, tzinfo=NY))},
            {"id": "tpl", "business_id": BIZ, "title": "Template", "archived_at": None, "is_template": True,
             "starts_at": _iso(datetime(2026, 10, 29, 19, 0, tzinfo=NY))},
            {"id": "next", "business_id": BIZ, "title": "Next Sunday", "archived_at": None, "is_template": False,
             "starts_at": _iso(datetime(2026, 11, 8, 10, 30, tzinfo=NY))},
            {"id": "theirs", "business_id": OTHER, "title": "Grace service", "archived_at": None, "is_template": False,
             "starts_at": _iso(datetime(2026, 11, 1, 11, 0, tzinfo=NY))}],
        custom_modules=[{"id": ROSTER, "business_id": BIZ, "name": "Services & Events", "archetype": "event_roster",
                         "is_active": True, "archetype_params": {"roles": [{"id": "cook", "label": "Cook", "needed": 2}]}}],
        module_entries=[
            _entry("Men’s breakfast", "2026-10-31T08:00", location="Fellowship hall",
                   signups=[{"contact_id": C["hayes"], "role": "cook", "status": "yes"}]),
            _entry("Sunday service", "2026-11-01T10:30", type="service", _roles=[]),
            _entry("Fall cleanup day", "2026-10-28", _roles=[]),
            _entry("Pastor’s counsel", "2026-10-29T15:00", _visibility="invite", _invited=[C["reed"]], _roles=[]),
            _entry("Christmas play", "2026-12-20", _roles=[])],
        church_spaces=[{"id": SANCT, "business_id": BIZ, "name": "Sanctuary"},
                       {"id": HALL, "business_id": BIZ, "name": "Fellowship hall"}],
        church_space_bookings=[
            {"id": "b1", "business_id": BIZ, "space_id": SANCT, "title": "Sunday service", "status": "booked", "kind": "event",
             "start_at": _iso(datetime(2026, 11, 1, 10, 0, tzinfo=NY)), "end_at": _iso(datetime(2026, 11, 1, 12, 0, tzinfo=NY))},
            {"id": "b2", "business_id": BIZ, "space_id": HALL, "title": "Johnson family meal", "status": "booked", "kind": "event",
             "start_at": _iso(datetime(2026, 10, 29, 18, 0, tzinfo=NY)), "end_at": _iso(datetime(2026, 10, 29, 20, 0, tzinfo=NY))},
            {"id": "b3", "business_id": BIZ, "space_id": HALL, "title": "Smith wedding reception", "status": "booked",
             "kind": "rental", "start_at": _iso(datetime(2026, 10, 30, 16, 0, tzinfo=NY)),
             "end_at": _iso(datetime(2026, 10, 30, 22, 0, tzinfo=NY))},
            {"id": "b4", "business_id": BIZ, "space_id": HALL, "title": "Asked, not approved", "status": "requested",
             "kind": "event", "start_at": _iso(datetime(2026, 10, 27, 9, 0, tzinfo=NY)),
             "end_at": _iso(datetime(2026, 10, 27, 10, 0, tzinfo=NY))}],
        groups=[{"id": SMALL, "business_id": BIZ, "name": "Men’s group", "active": True, "kind": "group",
                 "meet_day": 1, "meet_time": "19:00:00", "meet_every": 1},
                # Every other week, counted from a Thursday that puts it off this week.
                {"id": YOUNG, "business_id": BIZ, "name": "Young adults", "active": True, "kind": "group",
                 "meet_day": 3, "meet_time": "19:00:00", "meet_every": 2, "meet_from": "2026-10-22"},
                {"id": PROD, "business_id": BIZ, "name": "Production", "active": True, "kind": "team", "meet_day": None},
                {"id": WELCOME, "business_id": BIZ, "name": "Welcome", "active": True, "kind": "team", "meet_day": None}],
        serve_teams=[{"business_id": BIZ, "group_id": PROD, "sort": 0}, {"business_id": BIZ, "group_id": WELCOME, "sort": 1}],
        serve_positions=[
            {"id": SOUND, "business_id": BIZ, "group_id": PROD, "name": "Sound", "needed": 1, "active": True, "sort": 0},
            {"id": SLIDES, "business_id": BIZ, "group_id": PROD, "name": "Slides", "needed": 1, "active": True, "sort": 1},
            {"id": GREETER, "business_id": BIZ, "group_id": WELCOME, "name": "Greeter", "needed": 2, "active": True, "sort": 0}],
        serve_assignments=[
            {"business_id": BIZ, "service_id": SUNDAY, "position_id": SOUND, "slot": 1, "status": "yes"},
            {"business_id": BIZ, "service_id": SUNDAY, "position_id": SLIDES, "slot": 1, "status": "offered"},
            {"business_id": BIZ, "service_id": SUNDAY, "position_id": GREETER, "slot": 1, "status": "asked"}],
        church_follow_ups=[{"business_id": BIZ, "status": "open", "leader_contact_id": None},
                           {"business_id": BIZ, "status": "handed_back", "leader_contact_id": C["hayes"]},
                           {"business_id": BIZ, "status": "open", "leader_contact_id": C["reed"]},
                           {"business_id": BIZ, "status": "done", "leader_contact_id": None}],
    )
    fake.failing = set()
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    fake.room = {BIZ: [{"contact_id": C[k], "role": "leader"} for k in ("hayes", "moore", "price", "reed", "ellis", "grant")],
                 OTHER: [{"contact_id": C["theirs"], "role": "leader"}]}
    monkeypatch.setattr(mpm, "leaders_room_people", lambda biz: fake.room.get(biz, []) if fake.room is not None else None)
    monkeypatch.setenv("CHURCH_LEADERS_NOTE", "on")
    monkeypatch.setenv("CHURCH_AREAS", "off")
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "owner@lovecity.org")
    fake.now = T0
    monkeypatch.setattr(cln, "_now", lambda: fake.now)
    monkeypatch.setattr(cln, "_zone", lambda biz: NY)
    monkeypatch.setattr(rate_limit, "_buckets", {})
    fake.sent = []
    fake.fail_to = set()

    def deliver(biz, to, name, subject, html, key):
        if to in fake.fail_to or "*" in fake.fail_to:
            raise RuntimeError("Resend said no")
        fake.sent.append({"to": to, "name": name, "subject": subject, "html": html, "key": key})
    monkeypatch.setattr(cln, "deliver", deliver)
    return fake


def client(name) -> TestClient:
    app = FastAPI()
    app.include_router(cln.router)
    app.dependency_overrides[require_user] = lambda: PEOPLE[name]
    return TestClient(app)


def ok(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()


def page(who="clerk", biz=BIZ):
    return client(who).get(f"/church/leaders-note?business_id={biz}")


def status(who="clerk", biz=BIZ):
    return ok(client(who).get(f"/church/leaders-note/status?business_id={biz}"))["enabled"]


def send(who="clerk", biz=BIZ, subject="Leaders, the week of October 26", text="This week\nSunday service\n\nOne win\nA family came back."):
    return client(who).post("/church/leaders-note/send", json={"business_id": biz, "subject": subject, "text": text})


def note(db, biz=BIZ):
    return next(b for b in db.t["businesses"] if b["id"] == biz)["settings"].get(cln.KEY)


# ─── Who ──────────────────────────────────────────────────────────────

def test_the_owner_an_admin_and_a_manager_get_the_note_and_nobody_else_does(db):
    for who in ("owner", "admin", "clerk"):
        assert status(who) is True, who
        ok(page(who))
    for who in ("deacon", "watcher", "stranger"):
        assert status(who) is False, who
        assert page(who).status_code == 404, who
        assert send(who).status_code == 404, who
    # Another church's manager can't reach this church's note, nor send it.
    assert status("other_clerk", BIZ) is False
    assert page("other_clerk", BIZ).status_code == 404
    assert send("other_clerk", BIZ).status_code == 404
    assert not db.sent and note(db) is None


def test_a_manager_who_doesnt_work_the_office_is_refused_while_who_sees_what_is_on(db, monkeypatch):
    import church_areas
    monkeypatch.setenv("CHURCH_AREAS", "on")
    areas = {"areas": ["worship_media"]}
    monkeypatch.setattr(church_areas, "my_areas", lambda biz, uid, role: areas)
    assert status("clerk") is False
    assert page("clerk").status_code == 403
    assert send("clerk").status_code == 403
    assert status("admin") is True          # admins work every area
    areas["areas"] = ["worship_media", "office"]
    assert status("clerk") is True
    areas["areas"] = None                   # the whole church
    assert status("clerk") is True
    monkeypatch.setattr(church_areas, "my_areas", lambda biz, uid, role: None)
    assert page("clerk").status_code == 503   # couldn't read their areas: never a yes


def test_a_business_that_isnt_a_church_has_no_leaders_note(db):
    assert status("shop_owner", SHOP) is False
    r = page("shop_owner", SHOP)
    assert r.status_code == 404 and "churches" in r.json()["detail"]


def test_the_switch(db, monkeypatch):
    monkeypatch.setenv("CHURCH_LEADERS_NOTE", "off")
    assert status("owner") is False and page("owner").status_code == 404 and send("owner").status_code == 404
    monkeypatch.setenv("CHURCH_LEADERS_NOTE", "owner")    # the platform owner alone (owner@lovecity.org)
    assert status("owner") is True and status("clerk") is False and status("admin") is False
    ok(page("owner"))
    assert page("clerk").status_code == 404
    monkeypatch.delenv("CHURCH_LEADERS_NOTE")              # unset is owner
    assert cln.mode() == "owner" and status("clerk") is False
    monkeypatch.setenv("CHURCH_LEADERS_NOTE", "sideways")  # nonsense is off
    assert cln.mode() == "off" and status("owner") is False
    monkeypatch.setenv("CHURCH_LEADERS_NOTE", "on")
    assert status("clerk") is True


# ─── The draft ────────────────────────────────────────────────────────

def test_the_draft_is_the_churchs_own_week_from_its_rows(db):
    d = ok(page())
    assert d["church"] == "Love City Church"
    assert d["week"] == {"monday": "2026-10-26", "words": "the week of October 26"}
    assert d["days"]["from"] == "2026-10-26" and d["days"]["to"] == "2026-11-01"
    assert d["draft"]["subject"] == "Leaders, the week of October 26"
    assert d["draft"]["week"] == (
        "Wednesday, October 28\nAll day · Fall cleanup day\n\n"
        "Thursday, October 29\n6:00 PM · Fellowship hall: Johnson family meal\n\n"
        "Friday, October 30\n4:00 PM · Fellowship hall: booked for a rental\n\n"
        "Saturday, October 31\n8:00 AM · Men’s breakfast · Fellowship hall\n\n"
        # 10:30 AM on the church's clock after the clocks go back; the
        # Sanctuary booked for it is its place, and its occasion isn't said twice.
        "Sunday, November 1\n10:30 AM · Sunday service · Sanctuary\n\n"
        "A group meeting: Men’s group (Tuesday).")
    week = d["draft"]["week"]
    for kept_out in ("Smith", "Asked, not approved", "Pastor’s counsel", "Christmas play", "Archived", "Template",
                     "Next Sunday", "Grace", "Young adults"):
        assert kept_out not in week, kept_out
    assert d["draft"]["needed"] == (
        "Sunday service, Sunday, November 1: 2 places are still open. Production: Slides. Welcome: Greeter. "
        "1 person was asked and hasn’t answered yet.\n\n"
        "Men’s breakfast, Saturday, October 31: Cook needs 1 more.\n\n"
        "2 people in follow-up have no one to reach out to them yet. If you can take one, let the office know.")
    assert d["draft"]["win"] == ""
    assert d["counts"] == {"calendar": 5, "groups": 1, "open_places": 2, "roles": 1, "no_one": 2}
    # The joined text: each part under its heading, the empty win left out.
    assert d["text"] == f"This week\n{d['draft']['week']}\n\nWhat’s needed\n{d['draft']['needed']}"
    assert d["last"] is None and d["sent_this_week"] is False
    assert d["next_send"]["day"] == "2026-11-02"


def test_a_quiet_week_is_an_empty_part_never_an_invented_one(db):
    for t in ("worship_services", "module_entries", "church_space_bookings", "groups", "serve_assignments",
              "church_follow_ups"):
        db.t[t] = []
    d = ok(page())
    assert d["draft"]["week"] == "" and d["draft"]["needed"] == "" and d["text"] == ""
    assert d["counts"] == {"calendar": 0, "groups": 0, "open_places": 0, "roles": 0, "no_one": 0}


def test_every_place_filled_says_nothing_about_sunday(db):
    db.t["serve_assignments"] += [
        {"business_id": BIZ, "service_id": SUNDAY, "position_id": GREETER, "slot": 2, "status": "yes"}]
    for a in db.t["serve_assignments"]:
        a["status"] = "yes"
    d = ok(page())
    assert "Sunday service, Sunday" not in d["draft"]["needed"]
    assert d["counts"]["open_places"] == 0


def test_a_failed_read_is_a_503_never_an_empty_note(db):
    for t in ("worship_services", "module_entries", "church_space_bookings", "groups", "serve_positions",
              "church_follow_ups", "contacts"):
        db.failing = {t}
        r = page()
        assert r.status_code == 503, t
        assert "couldn't" in r.json()["detail"], t
    db.failing = set()
    db.room = None      # the leaders room couldn't be read
    assert page().status_code == 503
    assert send().status_code == 503 and not db.sent and note(db) is None


# ─── Who gets it ──────────────────────────────────────────────────────

def test_it_goes_to_the_leaders_room_one_email_an_address_and_says_who_has_none(db):
    d = ok(page())
    assert d["recipients"] == {"leaders": 6, "reach": 3, "no_email": ["Mia Ellis", "Noah Price"]}
    r = ok(send())
    assert sorted(x["to"] for x in db.sent) == ["dana@example.com", "darnell@example.com", "reed@example.com"]
    assert r["sent"] == 3 and r["no_email"] == ["Mia Ellis", "Noah Price"] and r["failed"] == [] and r["recorded"]
    assert "grace@example.com" not in {x["to"] for x in db.sent}      # another church's leader
    # Each email has its own key; a retry of one send never goes twice.
    assert len({x["key"] for x in db.sent}) == 3
    assert all(x["subject"] == "Leaders, the week of October 26" for x in db.sent)


def test_the_email_sets_each_heading_apart_and_escapes_what_was_typed(db):
    ok(send(text="This week\nSunday, November 1\n10:30 AM · Sunday service\n\nWhat’s needed\n<b>Ushers</b> & greeters"
                 "\n\nOne win\nSee https://lovecity.org/story"))
    html = db.sent[0]["html"]
    assert html.count("text-transform:uppercase") == 3 and "border-left:3px solid #7A3E9D" in html
    assert "<b>Sunday, November 1</b>" in html
    assert "&lt;b&gt;Ushers&lt;/b&gt; &amp; greeters" in html and "<b>Ushers</b>" not in html
    assert '<a href="https://lovecity.org/story"' in html
    assert "You’re getting this because you lead at Love City Church." in html


def test_no_one_with_an_email_is_refused_before_the_week_is_taken(db):
    db.room[BIZ] = [{"contact_id": C["price"], "role": "leader"}]
    r = send()
    assert r.status_code == 409 and "email" in r.json()["detail"]
    assert note(db) is None and not db.sent
    assert ok(page())["recipients"] == {"leaders": 1, "reach": 0, "no_email": ["Noah Price"]}


def test_an_email_that_fails_is_named_and_the_rest_still_go(db):
    db.fail_to = {"reed@example.com"}
    r = ok(send())
    assert r["sent"] == 2 and r["failed"] == ["Pastor Reed"]
    assert note(db)["failed"] == ["Pastor Reed"] and note(db)["sent"] == 2


# ─── Once a week ──────────────────────────────────────────────────────

def test_once_a_week_and_the_last_send_is_kept_without_touching_other_settings(db):
    r = ok(send("clerk"))
    assert r["last"]["by_name"] == "Kim Lee" and r["last"]["sent"] == 3
    assert r["last"]["sent_words"] == "Monday, October 26 at 10:00 AM"
    kept = note(db)
    assert kept["week"] == "2026-10-26" and kept["state"] == "sent" and kept["by"] == ID["clerk"]
    assert kept["text"].startswith("This week") and kept["subject"] == "Leaders, the week of October 26"
    settings = next(b for b in db.t["businesses"] if b["id"] == BIZ)["settings"]
    assert settings["news"] == {"celebrate": "ask"} and settings["practitioner_name"] == "Pastor Kevin"
    d = ok(page("admin"))
    assert d["sent_this_week"] is True and d["last"]["text"] == kept["text"]
    # A second send that week, by anyone, is refused in plain words; nothing goes.
    db.sent.clear()
    db.now = T0 + timedelta(days=4, hours=8)        # Friday evening
    again = send("admin")
    assert again.status_code == 409
    assert "already went out" in again.json()["detail"] and "Monday, November 2" in again.json()["detail"]
    assert not db.sent
    # Sunday night is still that week on the church's clock (UTC is Monday already).
    db.now = datetime(2026, 11, 2, 4, 30, tzinfo=timezone.utc)     # 11:30 PM Sunday in New York
    assert send("owner").status_code == 409
    # Monday, it's a new week.
    db.now = datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc)
    r = ok(send("owner"))
    assert r["last"]["by_name"] == "Pastor Kevin" and note(db)["week"] == "2026-11-02"


def test_when_nothing_went_the_week_is_free_again(db):
    db.fail_to = {"*"}
    r = send()
    assert r.status_code == 503 and "nothing was sent" in r.json()["detail"]
    assert note(db) is None
    db.fail_to = set()
    assert ok(send())["sent"] == 3
    # After a week that did go, a failed one puts the last week's back.
    first = note(db)
    db.now = T0 + timedelta(days=7)
    db.fail_to = {"*"}
    assert send().status_code == 503
    assert note(db) == first


def test_a_send_someone_else_made_in_between_is_never_overwritten(db):
    theirs = {"id": "theirs", "week": "2026-10-26", "state": "sending", "sent_at": _iso(T0), "by_name": "Someone"}
    # Expecting nothing there, but someone else's send is: no write.
    biz = next(b for b in db.t["businesses"] if b["id"] == BIZ)
    biz["settings"][cln.KEY] = theirs
    assert cln.swap(BIZ, None, {"id": "mine", "week": "2026-10-26"}) is False
    assert note(db) == theirs
    # The write itself is filtered on the id it expects (the database's own
    # check, not only the read before it).
    biz["settings"][cln.KEY] = {"id": "older"}
    assert sb_clients.sb_patch_as_service(f"/businesses?id=eq.{BIZ}&settings->{cln.KEY}->>id=eq.other",
                                          {"settings": {}}) == []
    assert cln.swap(BIZ, "older", {"id": "mine"}) is True and note(db) == {"id": "mine"}


def test_tries_are_held_to_a_few_an_hour(db):
    ok(send())
    for _ in range(3):
        assert send().status_code == 409
    assert send().status_code == 429


def test_a_subject_and_some_words_are_needed(db):
    assert send(subject=" ").status_code == 400
    assert send(text="  ").status_code == 400
    assert send(text="x" * (cln.TEXT_MAX + 1)).status_code == 400
    assert note(db) is None and not db.sent


def test_the_joined_text_matches_the_apps(db):
    assert cln.compose({"week": "a", "needed": "", "win": " b "}) == "This week\na\n\nOne win\nb"
    assert cln.compose({"week": "", "needed": "", "win": ""}) == ""
