"""Set up what a church handed in (church_move_setup.py).

Kevin, 2026-11-14: "do the not built section because that allows for it to be
setup before this pastor gets it." The rules under test: the plan is what the
button does (one pass); nothing is made twice; a church's own set-up is left
alone; a time, an age range, a name or an area that can't be read is a `cant`
in the church's own words, never a guess; only the platform owner asks.
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

import billing_limits  # noqa: E402
import brand_engine  # noqa: E402
import business_users_router as bur  # noqa: E402
import church_checkin  # noqa: E402
import church_move_in as mi  # noqa: E402
import church_move_setup as cms  # noqa: E402
import lead_admin  # noqa: E402
import messaging_router  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OWNER = "00000000-0000-4000-8000-000000000001"
SEAT = "00000000-0000-4000-8000-000000000002"
KEVIN = AuthedUser(id="00000000-0000-4000-8000-000000000008", email="kevin@solutionist.test", role="authenticated")
PASTOR = AuthedUser(id=OWNER, email="pastor@gracehill.org", role="authenticated")
MONDAY = date(2026, 11, 16)


class SetupDB(FakeDB):
    def get(self, path, **kw):
        parts = path.split("&")
        offset = next((int(p.split("=")[1]) for p in parts if p.startswith("offset=")), 0)
        # A phone lookup's wildcard filter is dropped: member_portal matches the last ten digits itself.
        return super().get("&".join(p for p in parts if not p.startswith(("offset=", "phone=like."))))[offset:]

    def post(self, path, body, prefer=None, **kw):
        table = path.lstrip("/").split("?")[0]
        if table == "church_checkin_settings":            # an upsert on business_id
            self.t[table] = [r for r in self.t[table] if r["business_id"] != body["business_id"]]
        if table == "group_members":
            self.t[table] = [r for r in self.t[table]
                             if (r["group_id"], r["contact_id"]) != (body["group_id"], body["contact_id"])]
        return super().post(path, body, prefer=prefer, **kw)


def church(**settings):
    return {"id": BIZ, "name": "Grace Hill Church", "type": "ministry", "owner_id": OWNER,
            "stripe_account_id": None, "settings": settings}


@pytest.fixture
def db(monkeypatch):
    fake = SetupDB(
        businesses=[church()], contacts=[], children=[], groups=[], group_members=[], business_users=[],
        custom_modules=[{"id": "m1", "business_id": BIZ, "archetype": "event_roster", "is_active": True,
                         "name": "Services & Events", "archetype_params": {}, "created_at": "2026-11-01T00:00:00Z"}],
        module_entries=[], church_checkin_settings=[], msg_safety_officers=[], msg_member_officers=[],
        church_move_items=[], church_move_files=[], audit_log=[])
    for name in ("get", "post", "patch"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "kevin@solutionist.test")
    monkeypatch.setattr(lead_admin, "PLATFORM_OWNER_EMAIL", "kevin@solutionist.test")
    monkeypatch.setattr(cms, "_today", lambda biz: MONDAY)
    monkeypatch.setattr(church_checkin, "_now", lambda: datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(billing_limits, "can_add_seat",
                        lambda biz, row=None: {"allowed": True, "count": 1, "limit": 8, "enforce": True})
    fake.sent = []

    async def send(biz, biz_row, row, **kw):
        fake.sent.append(kw["email"])
        return {"email_sent": True, "accept_url": "https://x.test", "church_email": None}
    monkeypatch.setattr(bur, "send_invite_email", send)
    return fake


def states(answer):
    return [(s["state"], s["what"]) for s in answer["steps"]]


def run(key, answers, files=(), do=False, biz=None):
    return cms.run(biz or church(), key, answers, list(files), do)


# ─── reading the church's words ───────────────────────────────────────

def test_days_and_times_are_read_only_where_they_cant_be_mistaken():
    assert [cms.weekday_of(x) for x in ("Sunday", "Sundays", "sun.", "Wed nights", "the weekend")] == [6, 6, 6, 2, None]
    assert [cms.clock_of(x) for x in ("10:30 AM", "9am", "6 p.m.", "18:00", "11", "12:15", "6:00", "25:00", "noon")] == \
        ["10:30", "09:00", "18:00", "18:00", "11:00", "12:15", None, None, None]
    assert cms.clock_words("09:05") == "9:05 AM" and cms.clock_words("18:00") == "6:00 PM"


def test_age_ranges_and_grades():
    assert cms.ages_of("0 to 2") == (0, 2) and cms.ages_of("3-5") == (3, 5) and cms.ages_of("birth to 2") == (0, 2)
    assert cms.ages_of("K to 5th") == (5, 10) and cms.ages_of("6th-8th grade") == (11, 13)
    assert cms.ages_of("12+") == (12, 17) and cms.ages_of("under 3") == (0, 2) and cms.ages_of("4") == (4, 4)
    assert cms.ages_of("little ones") is None and cms.ages_of("") is None and cms.ages_of("10 to 40") is None


# ─── Sunday ───────────────────────────────────────────────────────────

SUNDAY = {"services": [{"day": "Sunday", "time": "9:00 AM", "name": "Early service"},
                       {"day": "Sunday", "time": "11:00 AM", "name": "Morning worship"},
                       {"day": "Wednesday", "time": "7", "name": "Bible study"}]}


def test_services_plan_then_do_then_nothing_twice(db):
    plan, _ = run("sunday", SUNDAY)
    assert states(plan) == [
        ("will", "Switch Sunday check-in on: Sundays at 9:00 AM (Early service)."),
        ("will", "Put Early service on the calendar, Sundays at 9:00 AM: Nov 22, Nov 29, Dec 6, Dec 13."),
        ("will", "Put Morning worship on the calendar, Sundays at 11:00 AM: Nov 22, Nov 29, Dec 6, Dec 13."),
        ("cant", "“Wednesday · 7 · Bible study” on the calendar")]
    assert db.t["module_entries"] == [] and db.t["church_checkin_settings"] == []      # a plan writes nothing
    went, _ = run("sunday", SUNDAY, do=True)
    assert [s["state"] for s in went["steps"]] == ["made", "made", "made", "cant"] and went["made"] == 3
    st = db.t["church_checkin_settings"][0]
    assert (st["enabled"], st["weekday"], st["start_time"], st["title"]) == (True, 6, "09:00", "Early service")
    first = db.t["module_entries"][0]
    assert first["module_id"] == "m1" and first["created_by"] == "move_in_setup"
    assert first["data"] == {"title": "Early service", "date": "2026-11-22T09:00", "type": "service", "signups": [],
                             "_visibility": "public", "notes": "From the church's Move-in."}
    assert len(db.t["module_entries"]) == 8
    again, _ = run("sunday", SUNDAY, do=True)
    assert [s["state"] for s in again["steps"]] == ["there", "there", "there", "cant"]
    assert len(db.t["module_entries"]) == 8


def test_a_church_that_set_check_in_itself_is_left_alone_and_no_room_is_a_cant(db):
    db.t["church_checkin_settings"].append({"business_id": BIZ, "enabled": True, "weekday": 6, "start_time": "10:30",
                                            "timezone": "America/New_York"})
    db.t["custom_modules"].clear()
    plan, _ = run("sunday", SUNDAY)
    assert states(plan)[:2] == [("there", "Sunday check-in is already on: Sundays at 10:30 AM."),
                                ("cant", "Services on the calendar")]


def test_children_are_placed_by_age_and_only_the_roomless(db):
    kids = {"kids_rooms": [{"room": "Nursery", "ages": "0 to 2"}, {"room": "Elementary", "ages": "K to 5th"},
                           {"room": "The Loft", "ages": "big kids"}]}
    assert states(run("sunday", kids)[0])[-1][0] == "cant"                       # nobody on file yet
    db.t["children"] += [
        {"id": "k1", "business_id": BIZ, "active": True, "birthdate": "2025-03-01", "room": None},     # 1
        {"id": "k2", "business_id": BIZ, "active": True, "birthdate": "2018-06-01", "room": ""},       # 8
        {"id": "k3", "business_id": BIZ, "active": True, "birthdate": "2019-01-01", "room": "Blue"},   # has a room
        {"id": "k4", "business_id": BIZ, "active": True, "birthdate": None, "room": None},
        {"id": "k5", "business_id": BIZ, "active": True, "birthdate": "2012-01-01", "room": None}]     # 14: no room covers it
    plan, _ = run("sunday", kids)
    assert states(plan) == [("cant", "The Loft room"), ("will", "Place 1 child in Nursery (ages 0 to 2)."),
                            ("will", "Place 1 child in Elementary (ages 5 to 10)."), ("cant", "2 children have no room")]
    run("sunday", kids, do=True)
    assert {k["id"]: k["room"] for k in db.t["children"]} == {"k1": "Nursery", "k2": "Elementary", "k3": "Blue",
                                                              "k4": None, "k5": None}


def test_groups_are_made_once_with_a_leader_only_when_the_name_is_one_adult(db):
    db.t["contacts"] += [{"id": "c1", "business_id": BIZ, "name": "Ada Hill", "birthdate": "1980-01-01"},
                         {"id": "c2", "business_id": BIZ, "name": "Sam Reed", "birthdate": None},
                         {"id": "c3", "business_id": BIZ, "name": "Sam Reed", "birthdate": None}]
    groups = {"groups": [{"name": "Men", "leader": "ada hill", "meets": "Tuesdays, 7 pm"},
                         {"name": "Women", "leader": "Sam Reed"}, {"name": "Youth"}]}
    plan, _ = run("sunday", groups)
    assert states(plan) == [("will", "Make the group Men, led by ada hill (Tuesdays, 7 pm)."),
                            ("will", "Make the group Women."), ("will", "Make the group Youth.")]
    assert "isn't one adult on file" in plan["steps"][1]["why"]
    went, _ = run("sunday", groups, do=True)
    assert went["made"] == 3 and [g["name"] for g in db.t["groups"]] == ["Men", "Women", "Youth"]
    assert db.t["groups"][0]["meets"] == "Tuesdays, 7 pm" and db.t["groups"][0]["join_mode"] == "ask"
    assert [(m["contact_id"], m["role"]) for m in db.t["group_members"]] == [("c1", "leader")]
    assert [s["state"] for s in run("sunday", groups, do=True)[0]["steps"]] == ["there", "there", "there"]
    assert len(db.t["groups"]) == 3


# ─── office logins ────────────────────────────────────────────────────

def test_logins_are_invited_in_the_lane_the_words_point_to(db):
    db.t["business_users"].append({"business_id": BIZ, "status": "active", "invited_email": "here@gracehill.org"})
    people = {"people": [{"name": "Naiya Clark", "email": "Naiya@GraceHill.org", "looks_after": "Kids check-in"},
                         {"name": "Tom Reyes", "email": "tom@gracehill.org", "looks_after": "Giving and the budget"},
                         {"name": "Ben", "email": "here@gracehill.org", "looks_after": "the office"},
                         {"name": "Cy", "email": "", "looks_after": "media"},
                         {"name": "Dee", "email": "dee@gracehill.org", "looks_after": "a bit of everything"}]}
    plan, mail = run("logins", people)
    assert [s["state"] for s in plan["steps"]] == ["will", "cant", "there", "cant", "cant"] and mail == []
    assert plan["steps"][0]["what"] == "Invite Naiya Clark (naiya@gracehill.org) to People & Care. An email goes to them."
    assert "Admin over the whole church" in plan["steps"][1]["why"]
    went, mail = run("logins", people, do=True)
    made = [r for r in db.t["business_users"] if r["status"] == "invited"]
    assert [(r["invited_email"], r["role"], r["lane"], r["areas"], r["invited_by"]) for r in made] == [
        ("naiya@gracehill.org", "manager", "people_care", ["people_care", "kids_youth", "groups_classes"], OWNER)]
    assert went["made"] == 1 and len(mail) == 1
    import asyncio
    asyncio.run(cms.send_mail(church(), mail))
    assert db.sent == ["naiya@gracehill.org"]
    assert [s["state"] for s in run("logins", people, do=True)[0]["steps"]][0] == "there"      # never invited twice


def test_a_full_plan_invites_nobody_and_an_email_that_fails_is_said(db, monkeypatch):
    monkeypatch.setattr(billing_limits, "can_add_seat",
                        lambda biz, row=None: {"allowed": False, "count": 3, "limit": 3, "enforce": True})
    one = {"people": [{"name": "Naiya", "email": "n@gracehill.org", "looks_after": "kids"}]}
    assert states(run("logins", one)[0]) == [("cant", "Invite Naiya")]
    monkeypatch.setattr(billing_limits, "can_add_seat",
                        lambda biz, row=None: {"allowed": True, "count": 1, "limit": 3, "enforce": False})

    async def boom(*a, **k):
        raise RuntimeError("resend is down")
    monkeypatch.setattr(bur, "send_invite_email", boom)
    went, mail = run("logins", one, do=True)
    import asyncio
    asyncio.run(cms.send_mail(church(), mail))
    assert went["steps"][0]["state"] == "made" and "didn't send" in went["steps"][0]["why"]


# ─── safety officers ──────────────────────────────────────────────────

def test_officers_are_a_joined_login_or_a_pastor_with_a_role(db, monkeypatch):
    db.t["business_users"].append({"business_id": BIZ, "status": "active", "user_id": SEAT,
                                   "invited_email": "ada@gracehill.org"})
    db.t["contacts"].append({"id": "c9", "business_id": BIZ, "name": "Ray Cole", "email": "ray@example.com",
                             "phone": "555-010-0109", "birthdate": "1970-01-01"})
    monkeypatch.setattr(messaging_router, "owner_email_read", lambda uid: "pastor@gracehill.org")
    monkeypatch.setattr(messaging_router, "eligible_leaders",
                        lambda biz, owner: [{"contact_id": "c9", "name": "Ray Cole", "title": "Elder"}])
    officers = {"officers": [{"name": "Ada Hill", "contact": "Ada@GraceHill.org"},
                             {"name": "Elder Ray", "contact": "(555) 010-0109"},
                             {"name": "Someone Else", "contact": "else@example.com"}]}
    plan, _ = run("safety", officers)
    assert [s["state"] for s in plan["steps"]] == ["will", "will", "cant"]
    went, _ = run("safety", officers, do=True)
    assert [(r["user_id"], r["added_by"]) for r in db.t["msg_safety_officers"]] == [(SEAT, OWNER)]
    assert [r["contact_id"] for r in db.t["msg_member_officers"]] == ["c9"]
    assert went["made"] == 2
    two = {"officers": officers["officers"][:2]}
    after, _ = run("safety", two, do=True)
    assert [s["state"] for s in after["steps"]] == ["there", "there", "note"]        # and messaging is never switched on
    assert len(db.t["msg_safety_officers"]) == 1


# ─── the look ─────────────────────────────────────────────────────────

def test_the_colour_and_the_logo_go_into_the_brand_kit(db, monkeypatch):
    saved, uploads = {}, []
    monkeypatch.setattr(brand_engine, "save_brand_kit",
                        lambda biz, kit: (saved.update(kit), db.t["businesses"][0]["settings"].update(brand_kit=kit)))
    monkeypatch.setattr(brand_engine, "upload_asset",
                        lambda biz, variant, raw, name, media: (uploads.append((variant, raw, name, media)) or {"ok": True}))
    monkeypatch.setattr(cms, "_storage_get", lambda path: b"PNG")
    files = [{"name": "grace-logo.png", "path": f"{BIZ}/move-in/a.png", "media_type": "image/png"},
             {"name": "Easter.jpg", "path": f"{BIZ}/move-in/b.jpg", "media_type": "image/jpeg"}]
    look = {"colour": "navy", "sermons": "https://youtube.com/@gracehill"}
    plan, _ = run("look", look, files)
    assert [s["state"] for s in plan["steps"]] == ["will", "will", "note", "note"] and not saved and not uploads
    went, _ = run("look", look, files, do=True)
    assert went["made"] == 2 and saved["primary_color"] == saved["colors"]["primary"] == "#1f3a5f"
    assert uploads == [("primary", b"PNG", "grace-logo.png", "image/png")]
    # A colour the app can't wear, words that aren't a colour, and no file named like a logo.
    assert states(run("look", {"colour": "black"}, files[1:])[0])[:2] == [("cant", "The church colour"), ("cant", "The logo")]
    assert states(run("look", {"colour": "our usual"})[0]) == [("cant", "The church colour")]
    # A church that already has both is left as it is.
    kit = church(brand_kit={"logo_url": "https://x.test/l.png", "colors": {"primary": "#1D4ED8"}})
    assert [s["state"] for s in run("look", look, files, biz=kit)[0]["steps"]][:2] == ["there", "there"]


# ─── the whole answer, and who may ask ────────────────────────────────

def test_an_item_with_nothing_to_set_up_and_a_read_that_fails(db, monkeypatch):
    got, _ = run("tools", {"giving": "Tithely"})
    assert got["can"] is False and got["words"] == cms.NOTHING
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: None)
    got, _ = run("logins", {"people": [{"name": "N", "email": "n@x.org", "looks_after": "kids"}]}, do=True)
    assert got["unread"] is True and got["steps"] == [] and got["words"] == cms.UNREAD


def test_only_the_platform_owner_and_only_once_it_is_handed_in(db):
    app = FastAPI()
    app.include_router(mi.platform_router)
    app.dependency_overrides[require_user] = lambda: PASTOR
    assert TestClient(app).get(f"/platform/move-in/{BIZ}/setup/sunday").status_code == 403
    assert TestClient(app).post(f"/platform/move-in/{BIZ}/setup/sunday").status_code == 403
    app.dependency_overrides[require_user] = lambda: KEVIN
    kevin = TestClient(app)
    db.t["church_move_items"].append({"business_id": BIZ, "item": "sunday", "state": "started", "answers": SUNDAY})
    assert kevin.get(f"/platform/move-in/{BIZ}/setup/sunday").status_code == 409
    db.t["church_move_items"][0]["state"] = "handed_in"
    plan = kevin.get(f"/platform/move-in/{BIZ}/setup/sunday").json()
    assert plan["will"] == 3 and db.t["module_entries"] == []
    got = kevin.post(f"/platform/move-in/{BIZ}/setup/sunday")
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["went"]["made"] == 3 and body["after"]["will"] == 0 and body["after"]["there"] == 3
    assert len(db.t["module_entries"]) == 8
    # The mark route still answers at its own address.
    assert kevin.post(f"/platform/move-in/{BIZ}/sunday", json={"state": "checked"}).status_code == 200
