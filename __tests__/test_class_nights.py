"""Class nights after they end (academy_class_nights.py; the live room's
"I'm in the room", the teacher's marks and "Send tonight's slides to who
wasn't here" in academy_live_router.py).

Kevin 2026-10-18, asked whether online class nights count toward a
church's attendance: "Count class nights". The database half
(academy_live_count_night: once, only an ended night, only that night's own
occasion, never a first-time visitor, online / self / staff; who missed it;
service-only) was rehearsed on production in a rolled-back transaction; see
docs/MIGRATIONS.md.
"""
import asyncio
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import academy_class_nights as cn  # noqa: E402
import academy_live_router as live  # noqa: E402
from test_academy_live import COURSE, SID, STUDENT, access, client, env, input  # noqa: E402,F401

ROOT = Path(__file__).resolve().parent.parent
BIZ = "11111111-1111-1111-1111-111111111111"
NOW = datetime(2026, 10, 22, 23, 40, tzinfo=timezone.utc)  # 6:40 PM in Chicago
NIGHT = {"id": "s1", "course_id": "c1", "title": "Week 1", "starts_at": "2026-10-22T23:00:00Z",
         "started_at": "2026-10-22T23:02:00Z", "ended_at": "2026-10-23T00:05:00Z", "send_missed": False,
         "missed_sent_at": None, "counted_at": None, "academy_lessons": {"title": "New Life & Identity"},
         "academy_courses": {"title": "The Making: Foundation", "business_id": BIZ}}
CHURCH = {"id": BIZ, "name": "Love City Church", "type": "church", "settings": {}, "owner_id": "o1"}
ROSTER = {"id": "m-services", "name": "Services & Events", "archetype_params": {}}


# ─── Words ───────────────────────────────────────────────────────────

def test_a_night_is_named_by_its_title_and_lesson_once_each():
    assert cn.night_name(NIGHT) == "Week 1 · New Life & Identity"
    assert cn.night_name({"title": "New Life & Identity", "academy_lessons": {"title": "New life & identity"}}) == "New Life & Identity"
    assert cn.occasion_title("The Making: Foundation", "Week 1") == "The Making: Foundation · Week 1"


def test_the_missed_email_says_what_and_where_in_plain_words():
    subject, message, pre = cn.missed_email("The Making: Foundation", "Week 1 · New Life & Identity", "Tasha")
    assert subject == "The slides from The Making: Foundation: Week 1 · New Life & Identity"
    assert message.startswith("Hi Tasha,\n\nWe missed you at The Making: Foundation: Week 1 · New Life & Identity.")
    assert "slides and the lesson are in your class" in message and pre.endswith("The slides are in your class.")


# ─── The sweep ───────────────────────────────────────────────────────

@pytest.fixture
def world(monkeypatch):
    w = {"count": [NIGHT], "send": [], "business": [CHURCH], "entries": [], "roster": [ROSTER], "posts": [],
         "counted": [], "claim": None, "released": [], "emails": [], "fail_entries": False}
    import academy_reminders
    import church_checkin
    import sb_clients

    def get(path, *a, **k):
        if path.startswith("/academy_live_sessions?") and "counted_at=is.null" in path:
            return w["count"]
        if path.startswith("/academy_live_sessions?") and "send_missed=is.true" in path:
            return w["send"]
        if path.startswith("/businesses?"):
            return w["business"]
        if path.startswith("/module_entries?"):
            if w["fail_entries"]:
                return None
            sid = re.search(r"_class_session=eq\.([^&]+)", path).group(1)
            return [{"id": e["id"]} for e in w["entries"] if e["data"].get("_class_session") == sid]
        return []

    def post(path, body=None, *a, **k):
        w["posts"].append(path)
        if path == "/module_entries":
            row = {"id": f"occ-{len(w['entries']) + 1}", **body}
            w["entries"].append(row)
            return [row]
        if path == "/rpc/academy_live_count_night":
            w["counted"].append((body["p_session"], body["p_entry"]))
            return {"session_id": body["p_session"], "counted": 2 if body["p_entry"] else 0}
        if path == "/rpc/academy_live_missed_claim":
            got, w["claim"] = w["claim"], None
            return got
        if path == "/rpc/academy_live_missed_release":
            w["released"].append(body["p_session"])
            return None
        raise AssertionError(path)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    monkeypatch.setattr(church_checkin, "_roster", lambda b: w["roster"])
    monkeypatch.setattr(academy_reminders, "_zone", lambda b: "America/Chicago")
    monkeypatch.setattr(cn, "RETRY_WAITS", (0, 0))

    async def email(business, course_title, night, student, session_id):
        if "@" not in str(student.get("email")):
            return False
        w["emails"].append((student["email"], course_title, night, session_id))
        return True
    monkeypatch.setattr(cn, "_email", email)
    return w


def test_a_church_class_night_becomes_its_own_private_occasion_and_is_counted(world):
    out = asyncio.run(cn.sweep_tick(NOW))
    assert out == {"nights": 1, "counted": 2, "emails": 0}
    (occ,) = world["entries"]
    d = occ["data"]
    assert occ["module_id"] == "m-services" and occ["created_by"] == "class_night" and occ["business_id"] == BIZ
    assert d["title"] == "The Making: Foundation · Week 1 · New Life & Identity" and d["type"] == "class"
    assert d["_visibility"] == "private", "never on the public events page or a member's own"
    assert d["date"] == "2026-10-22T18:02", "the night on the church's own clock"
    assert d["_class_session"] == "s1" and "_checkin_day" not in d, "never Sunday check-in's own occasion"
    assert world["counted"] == [("s1", occ["id"])]


def test_an_occasion_already_made_is_used_again(world):
    world["entries"].append({"id": "occ-0", "data": {"_class_session": "s1"}})
    asyncio.run(cn.sweep_tick(NOW))
    assert world["counted"] == [("s1", "occ-0")] and len(world["entries"]) == 1


def test_any_other_business_is_marked_counted_with_no_occasion(world):
    world["business"] = [dict(CHURCH, type="coaching")]
    asyncio.run(cn.sweep_tick(NOW))
    assert world["entries"] == [] and world["counted"] == [("s1", None)]


def test_a_church_without_services_and_events_has_nothing_to_count_into(world):
    world["roster"] = []
    asyncio.run(cn.sweep_tick(NOW))
    assert world["entries"] == [] and world["counted"] == [("s1", None)]


def test_an_unread_room_or_clock_is_tried_again_never_marked(world, monkeypatch):
    world["fail_entries"] = True
    asyncio.run(cn.sweep_tick(NOW))
    assert world["counted"] == []
    world["fail_entries"] = False
    import academy_reminders
    monkeypatch.setattr(academy_reminders, "_zone", lambda b: None)
    asyncio.run(cn.sweep_tick(NOW))
    assert world["counted"] == [] and world["entries"] == []
    world["business"] = []
    asyncio.run(cn.sweep_tick(NOW))
    assert world["counted"] == []


def test_the_slides_go_to_who_missed_it_only_when_the_teacher_asked(world):
    asyncio.run(cn.sweep_tick(NOW))
    assert "/rpc/academy_live_missed_claim" not in world["posts"]
    asked = dict(NIGHT, counted_at="2026-10-23T00:10:00Z", send_missed=True)
    world["count"], world["send"] = [], [asked]
    world["claim"] = {"session_id": "s1", "students": [
        {"enrollment_id": "e3", "contact_id": "k3", "token": "t3", "name": "Tasha Hill", "email": "tasha@example.com"},
        {"enrollment_id": "e6", "contact_id": "k6", "token": "t6", "name": "Paul", "email": "+15551234567"}]}
    out = asyncio.run(cn.sweep_tick(NOW))
    assert out["emails"] == 1 and out["counted"] == 0, "counted once already: not counted again"
    assert world["emails"] == [("tasha@example.com", "The Making: Foundation", "Week 1 · New Life & Identity", "s1")]


def test_a_send_outage_unmarks_the_emails_so_the_next_tick_tries_again(world, monkeypatch):
    world["count"], world["send"] = [], [dict(NIGHT, counted_at="x", send_missed=True)]
    world["claim"] = {"session_id": "s1", "students": [{"enrollment_id": "e3", "token": "t3", "name": "T", "email": "t@example.com"}]}

    async def down(*a, **k):
        raise RuntimeError("resend down")
    monkeypatch.setattr(cn, "_email", down)
    asyncio.run(cn.sweep_tick(NOW))
    assert world["released"] == ["s1"]


def test_a_failed_email_is_tried_again_and_a_night_some_heard_stays_marked(world, monkeypatch, caplog):
    two = [{"enrollment_id": "e3", "token": "t3", "name": "Tasha", "email": "t@example.com"},
           {"enrollment_id": "e4", "token": "t4", "name": "Lee", "email": "l@example.com"}]
    world["count"], world["send"] = [], [dict(NIGHT, counted_at="x", send_missed=True)]
    tries = []

    async def hiccup(business, course_title, night, student, session_id):
        tries.append(student["enrollment_id"])
        if student["enrollment_id"] == "e3" and tries.count("e3") == 1:
            raise RuntimeError("resend hiccup")
        return True
    monkeypatch.setattr(cn, "_email", hiccup)
    world["claim"] = {"session_id": "s1", "students": two}
    assert asyncio.run(cn.sweep_tick(NOW))["emails"] == 2 and tries == ["e3", "e4", "e3"]
    assert world["released"] == []

    async def lee_only(business, course_title, night, student, session_id):
        if student["enrollment_id"] == "e3":
            raise RuntimeError("refused")
        return True
    monkeypatch.setattr(cn, "_email", lee_only)
    world["claim"] = {"session_id": "s1", "students": two}
    with caplog.at_level("WARNING"):
        assert asyncio.run(cn.sweep_tick(NOW))["emails"] == 1
    assert world["released"] == [], "un-marking would send Lee a second copy past the idempotency window"
    assert "1 of 2 missed-class emails not sent" in caplog.text


def test_the_real_email_goes_to_the_student_with_their_class_link(monkeypatch):
    import email_sender
    calls = []

    async def send(**k):
        calls.append(k)
        return {}
    monkeypatch.setattr(email_sender, "send_via_resend", send)
    student = {"enrollment_id": "e3", "token": "t3", "name": "Tasha Hill", "email": "tasha@example.com"}
    ok = asyncio.run(cn._email(CHURCH, "The Making: Foundation", "Week 1", student, "s1"))
    assert ok and calls[0]["to_email"] == "tasha@example.com" and calls[0]["from_name"] == "Love City Church"
    assert calls[0]["idempotency_key"] == "class-missed-s1-e3"
    assert "/classroom/t3" in calls[0]["body"] and "Open your class" in calls[0]["body"]
    assert not asyncio.run(cn._email(CHURCH, "x", "", dict(student, email="+15551234567"), "s1"))


# ─── The room: "I'm in the room", the teacher's marks, the ask ───────

def test_a_student_says_they_are_in_the_room(client, monkeypatch):
    db = AsyncMock(side_effect=[access(), None])
    monkeypatch.setattr(live, "db", db)
    r = client.post("/academy-live", json=input("here"))
    assert r.status_code == 200 and r.json() == {"ok": True, "room": True}
    method, path, body = db.call_args_list[1].args[1:4]
    assert method == "POST" and path.startswith("/academy_live_here?on_conflict=session_id,enrollment_id")
    assert body == {"session_id": SID, "enrollment_id": STUDENT[8:], "marked_by": "self"}, "their own link, never a name they typed"


@pytest.mark.parametrize("state", ["scheduled", "ended", "cancelled"])
def test_in_the_room_only_while_the_class_is_on(client, monkeypatch, state):
    monkeypatch.setattr(live, "db", AsyncMock(return_value=access(status=state, starts_at="2020-01-01T00:00:00Z")))
    assert client.post("/academy-live", json=input("here")).status_code == 409


def test_a_teacher_marks_and_unmarks_a_student_of_this_class_only(client, monkeypatch):
    db = AsyncMock(side_effect=[access(teacher=True), [{"id": STUDENT[8:]}], None])
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=input("mark", on=True)).json() == {"ok": True, "room": True}
    assert db.call_args_list[2].args[3]["marked_by"] == "teacher"
    db = AsyncMock(side_effect=[access(teacher=True), [{"id": STUDENT[8:]}], None])
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=input("mark", on=False)).json() == {"ok": True, "room": False}
    assert db.call_args_list[2].args[1] == "DELETE"
    db = AsyncMock(side_effect=[access(teacher=True), []])
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=input("mark", on=True)).status_code == 403
    assert "course_id=eq." + COURSE in db.call_args_list[1].args[2]


@pytest.mark.parametrize("action", ["mark", "missed"])
def test_students_cannot_mark_or_send(client, monkeypatch, action):
    db = AsyncMock(return_value=access())
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=input(action, on=True)).status_code == 403
    assert db.await_count == 1


@pytest.mark.parametrize("body", [input("mark"), input("mark", on="yes"), input("missed"),
                                  input("mark", on=True, identity="teacher_" + SID)])
def test_a_mark_or_an_ask_needs_a_yes_or_no_and_a_student(client, monkeypatch, body):
    db = AsyncMock()
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=body).status_code == 400
    db.assert_not_called()


def test_the_teacher_asks_for_the_slides_during_or_after_class(client, monkeypatch):
    for state in ("live", "ended"):
        db = AsyncMock(side_effect=[access(teacher=True, status=state), [{"send_missed": True, "missed_sent_at": None}]])
        monkeypatch.setattr(live, "db", db)
        r = client.post("/academy-live", json=input("missed", on=True))
        assert r.status_code == 200 and r.json()["send_missed"] is True
        method, path, body = db.call_args_list[1].args[1:4]
        assert method == "PATCH" and "missed_sent_at=is.null" in path and body == {"send_missed": True}
    # Once sent it stays sent: the answer is read back.
    db = AsyncMock(side_effect=[access(teacher=True, status="ended"), [], [{"send_missed": True, "missed_sent_at": "2026-10-23T00:10:00Z"}]])
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=input("missed", on=False)).json()["missed_sent_at"]
    monkeypatch.setattr(live, "db", AsyncMock(return_value=access(teacher=True, status="cancelled")))
    assert client.post("/academy-live", json=input("missed", on=True)).status_code == 409


def test_the_roster_says_who_is_in_the_room_and_whether_the_slides_go_out(client, monkeypatch):
    db = AsyncMock(side_effect=[access(teacher=True), [{"id": STUDENT[8:], "contact_id": "k1"}, {"id": "e2", "contact_id": "k2"}],
                                [{"id": "k1", "name": "Dana Wells"}, {"id": "k2", "name": "Marcus Hill"}],
                                [{"enrollment_id": "e2", "marked_by": "self"}], [{"send_missed": True, "missed_sent_at": None}]])
    monkeypatch.setattr(live, "db", db)
    got = client.post("/academy-live", json=input("roster")).json()
    assert got["students"] == [{"identity": STUDENT, "name": "Dana Wells", "room": None},
                               {"identity": "student_e2", "name": "Marcus Hill", "room": "self"}]
    assert got["send_missed"] is True and got["missed_sent_at"] is None


# ─── The database, the job ───────────────────────────────────────────

def test_the_migration_counts_once_never_a_first_time_visitor_and_is_service_only():
    sql = (ROOT / "supabase/APPLY-2026-10-18-academy-class-nights.sql").read_text(encoding="utf-8")
    for fn in ("academy_live_count_night(uuid, uuid)", "academy_live_missed_claim(uuid)", "academy_live_missed_release(uuid)"):
        assert f"revoke all on function public.{fn} from public, anon, authenticated;" in sql
        assert f"grant execute on function public.{fn} to service_role;" in sql
    assert "where id = p_session and status = 'ended' and counted_at is null" in sql
    assert "false, coalesce(s.started_at, s.starts_at)" in sql, "first_time is false: a class never makes a visitor"
    assert "case h.marked_by when 'teacher' then 'staff' when 'self' then 'self' else 'online' end" in sql
    assert "on conflict (entry_id, contact_id) where contact_id is not null do nothing" in sql
    assert "m.data->>'_class_session' = p_session::text" in sql, "only the night's own occasion"
    assert "e.status = 'active' and e.enrolled_at <= coalesce(s.ended_at, now())" in sql
    assert "revoke all on public.academy_live_here from public, anon, authenticated;" in sql
    assert "'room', exists" in sql and "'counted', s.entry_id is not null" in sql
    boot = (ROOT / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert 'g("academy_class_nights", _academy_class_nights.sweep_tick)' in boot
