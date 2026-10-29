"""Classes in the church member app (member_portal_classes.py): Connect ›
Classes, the next class night, the program road, one-tap join.

The database half (academy_member_classes: one member's classes, their
programs' roads, the classes they can join; service-only) was rehearsed on
production in a rolled-back transaction; see docs/MIGRATIONS.md.
"""
import asyncio
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import academy_join
import member_app_samples as samples
import member_portal as mp
import member_portal_church as mpc
import member_portal_classes as mcl

ROOT = Path(__file__).resolve().parent.parent
BIZ = "11111111-1111-1111-1111-111111111111"
ME = "66666666-6666-6666-6666-666666666666"
HOST = "first-light.mysolutionist.app"
FOUNDATION, FORMATION, FAMILY, NEW_MEMBERS = (f"c0000000-0000-4000-8000-00000000000{n}" for n in range(1, 5))
TOKEN = "70000000-0000-4000-8000-000000000001"
SOON = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()


def _data(**over):
    d = {
        "mine": [{"course_id": FOUNDATION, "title": "The Making: Foundation", "status": "active", "token": TOKEN,
                  "certificate": None, "done": 1, "total": 4, "program": "The Making", "position": 0, "teacher": "Pastor Kevin",
                  "next": {"starts_at": SOON, "minutes": 75, "live": False, "title": "Week 1", "lesson": "New Life & Identity"}}],
        "programs": [{"id": "p1", "title": "The Making", "finish_title": "Graduation", "finish_at": None, "tracks": [
            {"course_id": FOUNDATION, "title": "The Making: Foundation", "teacher": "Pastor Kevin", "starts_at": SOON, "state": "now", "token": TOKEN},
            {"course_id": FORMATION, "title": "The Making: Formation", "teacher": None, "starts_at": "2026-11-19T00:00:00+00:00", "state": "open", "token": None},
            {"course_id": FAMILY, "title": "The Making: Family", "teacher": None, "starts_at": None, "state": "later", "token": None}]}],
        "open": [{"course_id": NEW_MEMBERS, "title": "New Members Orientation", "about": "Who we are.", "lessons": 7,
                  "program": None, "position": None, "teacher": None, "starts_at": None, "opens_from": None, "drip": "none"}],
    }
    d.update(over)
    return d


class DB:
    def __init__(self):
        self.classes = _data()
        self.published = True
        self.courses = {FORMATION: {"id": FORMATION, "business_id": BIZ, "title": "The Making: Formation", "status": "published",
                                    "self_join": True, "product_id": None},
                        FAMILY: {"id": FAMILY, "business_id": BIZ, "title": "The Making: Family", "status": "draft",
                                 "self_join": True, "product_id": None}}
        self.join_state = "joined"
        self.posts, self.reads = [], []

    def get(self, path, *a, **k):
        self.reads.append(path)
        if path.startswith("/academy_courses?business_id="):
            return [{"id": FOUNDATION}] if self.published else []
        if path.startswith("/academy_courses?id=eq."):
            cid = re.search(r"id=eq\.([0-9a-f-]+)", path).group(1)
            biz = re.search(r"business_id=eq\.([0-9a-f-]+)", path).group(1)
            c = self.courses.get(cid)
            return [c] if c and c["business_id"] == biz else []
        return []

    def post(self, path, body=None, *a, **k):
        self.posts.append((path, body))
        if path == "/rpc/academy_member_classes":
            return self.classes
        if path == "/rpc/academy_public_join":
            return {"state": self.join_state, "enrollment_id": "e1", "token": None if self.join_state == "dropped" else TOKEN}
        return []


@pytest.fixture
def db(monkeypatch):
    d = DB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", d.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", d.post)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", lambda *a, **k: [])
    mcl._on_cache.clear()
    import outside_calendar
    monkeypatch.setattr(outside_calendar, "business_timezone", lambda b: "America/Chicago")
    return d


@pytest.fixture
def member(db, monkeypatch):
    biz = {"id": BIZ, "name": "First Light Church", "type": "church", "settings": {"member_portal": {"enabled": True}},
           "stripe_account_id": None}
    monkeypatch.setattr(mp, "_church_for_request", lambda req: {"business": dict(biz), "site": {"slug": "first-light"}})
    db.who = {"me": {"id": ME, "name": "Dana Wells", "email": "dana@example.com"}, "preview": False}
    monkeypatch.setattr(mp, "_session_for", lambda req, church: (
        {"claims": {}, "people": [db.who["me"]], "me": db.who["me"], "preview": db.who["preview"]}))
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a, **k: True)
    import giving_router
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: False)
    monkeypatch.setattr(mpc, "groups_for", lambda b, me: {"mine": [], "open": []})
    import church_follow_up as cfu
    monkeypatch.setattr(cfu, "roles_for", lambda b, c: [])

    async def signed_in(request):
        if db.who["preview"]:
            return {"business": biz}, None, "preview"
        return {"business": biz}, db.who["me"], False
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    told = []

    async def after(course, me, outcome):
        told.append((course["id"], outcome["state"]))
    monkeypatch.setattr(mcl, "after_join", after)
    db.told = told
    app = FastAPI()
    app.include_router(mcl.router)

    @app.get("/my/classes")
    async def _classes(request: mp.Request):
        return await mp.serve(request, "/my/classes")

    @app.get("/my/groups")
    async def _groups(request: mp.Request):
        return await mp.serve(request, "/my/groups")
    return TestClient(app, base_url=f"https://{HOST}", follow_redirects=False)


# ─── The page ────────────────────────────────────────────────────────

def test_the_member_sees_their_next_class_their_road_and_what_they_can_join(db, member):
    r = member.get("/my/classes")
    assert r.status_code == 200
    html = r.text
    assert ("academy_member_classes" in db.posts[-1][0]) and db.posts[-1][1] == {"p_business": BIZ, "p_contact": ME}
    assert 'aria-current="page">Classes</a>' in html and ">Groups</a>" in html, "Classes sits beside Groups under Connect"
    nxt = html.split('class="mb-cnext"')[1].split("</section>")[0]
    assert "Week 1 · New Life &amp; Identity" in nxt and "Pastor Kevin" in nxt
    assert f"/classroom/{TOKEN}" in nxt and "Open the lesson" in nxt
    road = html.split('class="mb-road"')[1].split("</ol>")[0]
    assert re.findall(r'data-state="(\w+)"', road) == ["now", "open", "later", "finish"]
    assert ">Foundation<" in road and ">Formation<" in road, "the program's name isn't repeated on its own road"
    assert "You&#x27;re here · 1 of 4 lessons · Pastor Kevin" in road and "Open to join · starts Nov 18" in road
    assert f'name="course_id" value="{FORMATION}"' in road, "an open track is joined right on the road"
    assert f'value="{FAMILY}"' not in road, "a track that isn't open has no Join"
    assert 'aria-valuenow="1"' in html and "1 of 4 lessons" in html
    assert f'name="course_id" value="{NEW_MEMBERS}"' in html and "Join this class" in html


def test_a_class_live_now_says_so_and_goes_straight_in(db, member):
    c = db.classes["mine"][0]
    c["next"] = {**c["next"], "live": True}
    html = member.get("/my/classes").text
    assert 'class="mb-cnext is-live"' in html and "Live now" in html and "Join the class now" in html


def test_a_failed_read_says_try_again_and_an_empty_church_says_so(db, member):
    db.classes = None
    assert "couldn't load just now" in member.get("/my/classes").text
    db.classes = _data(mine=[], programs=[], open=[])
    assert "No classes to join right now" in member.get("/my/classes").text


def test_the_owners_preview_shows_samples_where_the_church_has_none(db, member):
    db.who["preview"] = True
    db.classes = _data(mine=[], programs=[], open=[])
    html = member.get("/my/classes").text
    assert samples.WHERE["classes"].replace("&", "&amp;") in html and "Sample" in html


def test_the_classes_tab_shows_only_when_the_church_has_a_published_class(db, member):
    assert ">Classes</a>" in member.get("/my/groups").text
    db.published = False
    mcl._on_cache.clear()
    assert ">Classes</a>" not in member.get("/my/groups").text, "no empty tab for a church without classes"
    db.who["preview"] = True
    assert ">Classes</a>" in member.get("/my/groups").text, "the owner's preview always shows where classes go"


def test_whether_the_church_has_classes_is_read_once_a_minute(db):
    assert mcl.classes_on(BIZ) and mcl.classes_on(BIZ)
    assert sum(1 for p in db.reads if p.startswith("/academy_courses?business_id=")) == 1
    mcl._on_cache.clear()
    db.get = lambda *a, **k: None
    import sb_clients
    sb_clients.sb_get_as_service = db.get
    assert mcl.classes_on(BIZ) is False and BIZ not in mcl._on_cache, "a failed read isn't kept"


# ─── Joining ─────────────────────────────────────────────────────────

def _join(client, course=FORMATION):
    return client.post("/my/classes/join", data={"course_id": course})


def test_one_tap_joins_with_the_members_own_contact(db, member):
    r = _join(member)
    assert r.status_code == 303 and r.headers["location"] == "/my/classes?done=class_joined"
    assert ("/rpc/academy_public_join", {"p_course": FORMATION, "p_contact": ME}) in db.posts
    assert db.told == [(FORMATION, "joined")], "the owner is told and the link emailed, after the answer"
    db.join_state = "already"
    assert _join(member).headers["location"] == "/my/classes?done=class_already"


def test_a_closed_draft_or_other_churchs_class_is_never_joined(db, member):
    assert _join(member, FAMILY).headers["location"] == "/my/classes?err=class_closed"
    db.courses[FORMATION]["business_id"] = "22222222-2222-2222-2222-222222222222"
    assert _join(member, FORMATION).headers["location"] == "/my/classes?err=class_closed"
    assert _join(member, "not-an-id").headers["location"] == "/my/classes?err=class_closed"
    assert not any(p == "/rpc/academy_public_join" for p, _ in db.posts)


def test_taken_off_a_class_they_cant_rejoin_here_and_the_owner_hears(db, member):
    db.join_state = "dropped"
    assert _join(member).headers["location"] == "/my/classes?err=class_dropped"
    assert db.told == [(FORMATION, "dropped")]


def test_the_preview_and_a_signed_out_page_save_nothing(db, member):
    db.who["preview"] = True
    assert _join(member).headers["location"] == "/my/classes?err=preview"
    assert not any(p == "/rpc/academy_public_join" for p, _ in db.posts)


def test_the_join_page_names_its_words():
    assert mpc.DONE["class_joined"] and mpc.ERRORS["class_closed"] and mpc.ERRORS["class_dropped"]
    assert mpc._back("/my/classes", done="class_joined").headers["location"] == "/my/classes?done=class_joined"


def test_after_joining_the_link_goes_to_their_email_and_the_owner_hears_it_came_from_the_app(monkeypatch):
    sent, told = [], []

    async def send(course, name, email, outcome, again):
        sent.append((email, again))

    async def tell(course, outcome, came_from="page"):
        told.append(came_from)
    monkeypatch.setattr(academy_join, "send_class_link", send)
    monkeypatch.setattr(academy_join, "tell_owner", tell)
    course = {"id": FORMATION, "business_id": BIZ, "title": "Formation"}
    out = {"state": "joined", "token": TOKEN, "enrollment_id": "e1"}
    asyncio.run(mcl.after_join(course, {"id": ME, "name": "Dana", "email": "dana@example.com"}, out))
    asyncio.run(mcl.after_join(course, {"id": ME, "name": "Dana", "email": "+15551234567"}, out))
    assert sent == [("dana@example.com", False)], "signed in by phone: nothing to email"
    assert told == ["app", "app"]


# ─── Words and the database ──────────────────────────────────────────

def test_when_a_class_meets_reads_in_the_churchs_clock():
    now = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)  # Monday 10 AM in Chicago
    tz = "America/Chicago"
    assert mcl.when_text("2026-10-19T23:00:00+00:00", tz, now) == "Tonight at 6 PM"
    assert mcl.when_text("2026-10-19T16:30:00+00:00", tz, now) == "Today at 11:30 AM"
    assert mcl.when_text("2026-10-20T23:00:00+00:00", tz, now) == "Tomorrow at 6 PM"
    assert mcl.when_text("2026-10-22T23:00:00+00:00", tz, now) == "Thursday at 6 PM"
    assert mcl.when_text("2026-11-19T00:00:00+00:00", tz, now) == "Wed, Nov 18 at 6 PM"
    assert mcl.when_text(None, tz, now) == ""
    assert mcl.short_title("The Making: Foundation", "The Making") == "Foundation"
    assert mcl.short_title("New Members", "The Making") == "New Members"


def test_the_read_is_service_only_and_shows_published_classes_only():
    sql = (ROOT / "supabase/APPLY-2026-10-18-academy-member-classes.sql").read_text(encoding="utf-8")
    assert "revoke all on function public.academy_member_classes(uuid, uuid) from public, anon, authenticated;" in sql
    assert "grant execute on function public.academy_member_classes(uuid, uuid) to service_role;" in sql
    assert "c.status = 'published'" in sql and "e.status in ('active', 'completed')" in sql
    assert "public.academy_course_open(c)" in sql, "joinable means what the class page's form means"
    boot = (ROOT / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert boot.index("member_classes_router") < boot.index("app.include_router(public_site_router)")
