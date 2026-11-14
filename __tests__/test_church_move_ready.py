"""Ready for Sunday (church_move_ready.py): what is really set up in a church's
account, one line per thing its first Sunday leans on.

Kevin's preparation list, 2026-11-14: "There's no 'ready for Sunday' check."
The rules under test: a line reads the live records, never what was handed in;
a read that failed is "unknown", never "none"; nothing is written; and only
the platform owner asks.
"""
import os
import sys
from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_checkin  # noqa: E402
import church_move_in as mi  # noqa: E402
import church_move_ready as cmr  # noqa: E402
import lead_admin  # noqa: E402
import live_router  # noqa: E402
import member_portal  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OWNER = "00000000-0000-4000-8000-000000000001"
KEVIN = AuthedUser(id="00000000-0000-4000-8000-000000000008", email="kevin@solutionist.test", role="authenticated")
PASTOR = AuthedUser(id=OWNER, email="pastor@gracehill.org", role="authenticated")


class ReadyDB(FakeDB):
    """FakeDB, with pages (offset) and a table that can refuse to be read."""
    down: tuple = ()

    def get(self, path, **kw):
        table = path.lstrip("/").split("?")[0]
        if table in self.down:
            return None
        parts = path.split("&")
        offset = next((int(p.split("=")[1]) for p in parts if p.startswith("offset=")), 0)
        rows = super().get("&".join(p for p in parts if not p.startswith(("offset=", "limit="))))
        limit = next((int(p.split("=")[1]) for p in parts if p.startswith("limit=")), None)
        return rows[offset:offset + limit] if limit else rows[offset:]


def person(n, **more):
    return {"id": f"c{n:04d}", "business_id": BIZ, "email": None, "phone": None, "birthdate": None, **more}


def church(**settings):
    return {"id": BIZ, "name": "Grace Hill Church", "type": "ministry", "owner_id": OWNER,
            "stripe_account_id": None, "settings": settings}


@pytest.fixture
def db(monkeypatch):
    fake = ReadyDB(businesses=[church()], contacts=[], households=[], children=[], checkin_stations=[],
                   business_users=[], sms_numbers=[], groups=[], group_members=[], custom_modules=[],
                   module_entries=[], church_checkin_settings=[], msg_safety_officers=[], msg_member_officers=[],
                   church_move_items=[])
    fake.down = ()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(sb_clients, "sb_count_as_service",
                        lambda path: None if fake.get(path) is None else len(fake.get(path)))
    for name in ("post", "patch"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service",
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError("the check writes nothing")))
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "kevin@solutionist.test")
    monkeypatch.setattr(lead_admin, "PLATFORM_OWNER_EMAIL", "kevin@solutionist.test")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setattr(church_checkin, "_now", lambda: datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc))
    return fake


def line(biz, key):
    got = next(x for x in cmr.ready(biz)["lines"] if x["key"] == key)
    return got["state"], got["words"]


# ─── who can sign in ──────────────────────────────────────────────────

def test_nobody_on_file_is_not_yet(db):
    assert line(church(), "people") == ("not_yet", "Nobody is on file yet.")


def test_a_person_signs_in_with_an_email_or_mobile_of_their_own(db):
    db.t["contacts"] += [
        person(1, email="ada@example.com"),
        person(2, phone="(555) 010-0101"),
        person(3),                                                     # neither: no code can reach them
        person(4, email="hills@example.com"), person(5, email="Hills@Example.com"),      # a couple, one email
        person(6, email="hills@example.com", phone="555-010-0106"),    # the shared email, and a mobile of her own
        person(7, email="hills@example.com", birthdate="2018-05-01"),  # a child on a parent's email blocks nobody
        person(8, email="not an address", phone="12345"),              # neither is usable
    ]
    state, words = line(church(), "people")
    assert state == "watch"
    assert words == ("8 people on file. 3 can sign in on Sunday. 2 have no email or mobile of their own, so no "
                     "code can reach them. 2 share an email or mobile with someone else. A shared one gets no "
                     "code. 1 child under 13 doesn't sign in.")


def test_everyone_with_their_own_is_ready_and_a_long_list_is_read_in_pages(db, monkeypatch):
    monkeypatch.setattr(cmr, "PAGE", 3)
    db.t["contacts"] += [person(n, email=f"p{n}@example.com") for n in range(1, 8)]
    assert line(church(), "people") == ("ready", "7 people on file. 7 can sign in on Sunday.")


def test_a_list_that_cant_be_read_is_unknown_never_nobody(db):
    db.down = ("contacts",)
    assert line(church(), "people") == ("unknown", cmr.UNREAD_WORDS)


# ─── families, the app, giving ────────────────────────────────────────

def test_families_and_children(db):
    assert line(church(), "families")[0] == "not_yet"
    db.t["households"].append({"id": "h1", "business_id": BIZ})
    assert line(church(), "families") == (
        "watch", "1 family and 0 children. With no children on file, kids check-in has nobody to find.")
    db.t["children"] += [{"id": "k1", "business_id": BIZ, "active": True, "room": "Nursery"},
                         {"id": "k2", "business_id": BIZ, "active": False, "room": None}]
    assert line(church(), "families") == ("ready", "1 family and 1 child.")


def test_the_app_is_the_owners_switch_and_sign_in_can_be_paused(db):
    assert line(church(), "app")[0] == "not_yet"
    assert line(church(member_portal={"enabled": True}), "app") == (
        "ready", "The members' app is switched on and sign-in is open.")
    paused = line(church(member_portal={"enabled": True, "sign_in": False}), "app")
    assert paused[0] == "not_yet" and "paused" in paused[1]


def test_giving_follows_stripe_then_the_switch(db):
    assert "hasn't been started" in line(church(), "giving")[1]
    waiting = {**church(stripe={"charges_enabled": False}), "stripe_account_id": "acct_1"}
    assert line(waiting, "giving") == (
        "not_yet", "Stripe hasn't approved the church yet. Giving can't be switched on until it does.")
    approved = {**church(stripe={"charges_enabled": True}), "stripe_account_id": "acct_1"}
    assert line(approved, "giving") == ("not_yet", "Stripe has approved the church. Giving isn't switched on yet.")
    live = {**church(stripe={"charges_enabled": True}, giving={"enabled": True}), "stripe_account_id": "acct_1"}
    assert line(live, "giving")[0] == "ready"


# ─── Sunday itself ────────────────────────────────────────────────────

def test_whats_coming_up_is_the_calendar_not_the_form(db, monkeypatch):
    monkeypatch.setattr(live_router, "occasions", lambda biz: [])
    assert line(church(), "calendar")[0] == "not_yet"
    monkeypatch.setattr(live_router, "occasions", lambda biz: [
        {"id": "e1", "title": "Sunday Worship", "when": "2026-11-22"}, {"id": "e2", "title": "Youth", "when": "2026-11-25"}])
    assert line(church(), "calendar") == (
        "ready", "2 services and events on the calendar from today on. Next: Sunday Worship, Sunday, November 22.")
    monkeypatch.setattr(live_router, "occasions", lambda biz: None)
    assert line(church(), "calendar")[0] == "unknown"


def test_sunday_check_in_is_on_and_this_weeks_is_started_or_not(db, monkeypatch):
    assert line(church(), "checkin") == ("not_yet", "Sunday check-in is switched off.")
    db.t["church_checkin_settings"].append({"business_id": BIZ, "enabled": True, "weekday": 6, "start_time": "10:00",
                                            "timezone": "America/New_York"})
    monkeypatch.setattr(church_checkin, "find_occasion", lambda biz, day, made=True: {})
    assert line(church(), "checkin") == (
        "watch", "Sunday check-in is on: Sundays at 10:00 AM. This week's service (November 22) isn't started yet.")
    monkeypatch.setattr(church_checkin, "find_occasion",
                        lambda biz, day, made=True: {"id": "e1", "title": "Sunday Worship", "date": "2026-11-22"})
    assert line(church(), "checkin") == (
        "ready", "Sunday check-in is on: Sundays at 10:00 AM. This week's is started: Sunday Worship.")
    monkeypatch.setattr(church_checkin, "find_occasion", lambda biz, day, made=True: None)
    assert line(church(), "checkin")[0] == "unknown"


def test_kids_need_rooms_and_a_paired_tablet(db):
    assert line(church(), "kids") == ("watch", "No children are on file. No tablet is paired yet.")
    db.t["children"] += [{"id": "k1", "business_id": BIZ, "active": True, "room": "Nursery"},
                         {"id": "k2", "business_id": BIZ, "active": True, "room": "Elementary"},
                         {"id": "k3", "business_id": BIZ, "active": True, "room": ""}]
    assert line(church(), "kids") == (
        "not_yet", "3 children in 2 rooms (Elementary, Nursery). 1 has no room yet. No tablet is paired yet.")
    db.t["checkin_stations"] += [
        {"id": "s1", "business_id": BIZ, "paired_at": "2026-11-19T15:00:00Z", "revoked_at": None},
        {"id": "s2", "business_id": BIZ, "paired_at": None, "revoked_at": None},                    # code made, never paired
        {"id": "s3", "business_id": BIZ, "paired_at": "2026-11-01T15:00:00Z", "revoked_at": "2026-11-02T15:00:00Z"}]
    assert line(church(), "kids") == (
        "watch", "3 children in 2 rooms (Elementary, Nursery). 1 has no room yet. 1 tablet is paired.")
    db.t["children"][2]["room"] = "Nursery"
    assert line(church(), "kids")[0] == "ready"


# ─── the office ───────────────────────────────────────────────────────

def test_office_logins_invited_and_joined(db):
    assert line(church(), "logins")[0] == "not_yet"
    db.t["business_users"] += [
        {"business_id": BIZ, "status": "active", "invited_email": "ada@gracehill.org"},
        {"business_id": BIZ, "status": "invited", "invited_email": "ben@gracehill.org"},
        {"business_id": BIZ, "status": "revoked", "invited_email": "gone@gracehill.org"}]
    assert line(church(), "logins") == (
        "watch", "1 office login has joined. 1 invited and not joined yet: ben@gracehill.org.")
    db.t["business_users"][1]["status"] = "active"
    assert line(church(), "logins") == ("ready", "2 office logins have joined.")


def test_two_safety_officers_before_messaging(db):
    assert line(church(), "safety") == (
        "not_yet", "0 of 2 safety officers are named. Member messaging stays off until both are.")
    db.t["msg_safety_officers"].append({"business_id": BIZ, "user_id": OWNER})
    db.t["msg_member_officers"].append({"business_id": BIZ, "contact_id": "c0001"})
    assert line(church(), "safety") == (
        "ready", "2 safety officers are named. Member messaging is still off, and can be switched on.")
    assert line(church(messaging={"enabled": True}), "safety")[1].endswith("Member messaging is on.")
    db.down = ("msg_safety_officers",)
    assert line(church(), "safety")[0] == "unknown"


def test_the_look_is_the_brand_kit_not_the_files_handed_in(db):
    assert line(church(), "look")[0] == "not_yet"
    assert line(church(brand_kit={"logo_url": "https://x.test/logo.png"}), "look") == (
        "watch", "The logo is in. The church colour isn't set yet.")
    both = church(brand_kit={"logo_url": "https://x.test/logo.png", "colors": {"primary": "#1D4ED8"}})
    assert line(both, "look")[0] == "ready"


def test_texting_number_and_groups(db):
    assert line(church(), "texting")[0] == "watch"
    db.t["sms_numbers"] += [{"business_id": BIZ, "status": "releasing", "phone_number": "+15550109999"},
                            {"business_id": BIZ, "status": "active", "phone_number": "+15550101234"}]
    assert line(church(), "texting") == ("ready", "The church has its own texting number, ending 1234.")
    assert line(church(), "groups")[0] == "watch"
    db.t["groups"] += [{"id": "g1", "business_id": BIZ, "name": "Men", "active": True, "youth": False},
                       {"id": "g2", "business_id": BIZ, "name": "Women", "active": True, "youth": False},
                       {"id": "g3", "business_id": BIZ, "name": "Old", "active": False, "youth": False}]
    db.t["group_members"].append({"business_id": BIZ, "group_id": "g1", "contact_id": "c0001", "role": "leader"})
    assert line(church(), "groups") == ("watch", "2 groups. 1 has no leader yet.")
    db.t["group_members"].append({"business_id": BIZ, "group_id": "g2", "contact_id": "c0002", "role": "leader"})
    assert line(church(), "groups") == ("ready", "2 groups. Each one has a leader.")


# ─── the whole answer, and who may ask ────────────────────────────────

def test_every_line_answers_even_when_one_blows_up(db, monkeypatch):
    monkeypatch.setattr(member_portal, "portal_active", lambda biz: (_ for _ in ()).throw(RuntimeError("boom")))
    got = cmr.ready(church())
    assert [x["key"] for x in got["lines"]] == [k for k, _, _ in cmr.LINES] and got["total"] == 12
    assert next(x for x in got["lines"] if x["key"] == "app")["state"] == "unknown"
    assert got["ready"] + got["watch"] + got["not_yet"] + got["unknown"] == 12
    assert got["room_only"] and all(isinstance(x, str) for x in got["room_only"])


def test_only_the_platform_owner_asks_and_the_first_sunday_is_as_the_church_typed_it(db):
    db.t["church_move_items"].append({"business_id": BIZ, "item": "sunday", "state": "todo",
                                      "answers": {"first_sunday": "Sunday, November 22"}})
    app = FastAPI()
    app.include_router(mi.platform_router)
    app.dependency_overrides[require_user] = lambda: PASTOR
    assert TestClient(app).get(f"/platform/move-in/{BIZ}/ready").status_code == 403
    app.dependency_overrides[require_user] = lambda: KEVIN
    got = TestClient(app).get(f"/platform/move-in/{BIZ}/ready")
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["church"] == {"id": BIZ, "name": "Grace Hill Church"} and body["first_sunday"] == "Sunday, November 22"
    assert len(body["lines"]) == 12
    # The room read still answers at its own address, and a mark still posts.
    assert TestClient(app).get(f"/platform/move-in/{BIZ}").status_code == 200
    assert date(2026, 11, 22).weekday() == 6
