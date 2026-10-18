"""Class-night reminders (academy_reminders.py): when a class night is told,
by email and in a church's member app, once.

The database half (academy_courses.remind_live, academy_live_sessions.
reminded_at, academy_live_reminder_claim: once, published, scheduled,
reminders on, active students only, service-only) was rehearsed on
production in a rolled-back transaction; see docs/MIGRATIONS.md.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import academy_reminders as ar
import member_push

ROOT = Path(__file__).resolve().parent.parent
TZ = "America/Chicago"
BIZ = "11111111-1111-1111-1111-111111111111"


def chi(y, mo, d, h, mi=0):
    from zoneinfo import ZoneInfo
    return datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(TZ))


# ─── When ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("now, starts, want", [
    (chi(2026, 10, 22, 15, 30), chi(2026, 10, 22, 18), "tonight at 6 PM"),
    (chi(2026, 10, 22, 14, 59), chi(2026, 10, 22, 18), None),             # more than three hours out
    (chi(2026, 10, 22, 17, 40), chi(2026, 10, 22, 18), None),             # under half an hour: too late
    (chi(2026, 10, 22, 11, 0), chi(2026, 10, 22, 13, 30), "today at 1:30 PM"),
    (chi(2026, 10, 21, 18, 0), chi(2026, 10, 22, 9), "tomorrow at 9 AM"),  # a morning class: the evening before
    (chi(2026, 10, 21, 22, 0), chi(2026, 10, 22, 9), None),               # never late at night
    (chi(2026, 10, 22, 6, 30), chi(2026, 10, 22, 9), None),               # never at dawn
    (chi(2026, 10, 22, 7, 15), chi(2026, 10, 22, 9), "today at 9 AM"),    # missed the evening: early morning
    (chi(2026, 10, 21, 18, 0), chi(2026, 10, 22, 18), None),              # an evening class: not the night before
])
def test_a_class_is_told_a_few_hours_before_or_the_evening_before_a_morning_one(now, starts, want):
    assert ar.due(starts, now, TZ) == want


def test_the_email_says_when_and_what_in_plain_words():
    subject, message, pre = ar.reminder_email("Love City Church", "The Making: Foundation", "Week 1 · New Life & Identity",
                                              "tonight at 6 PM", "Dana")
    assert subject == "Tonight at 6 PM: The Making: Foundation"
    assert message.startswith("Hi Dana,\n\nYour class meets tonight at 6 PM. The Making: Foundation: Week 1 · New Life & Identity.")
    assert "press Join" in message and pre.startswith("Your class meets tonight at 6 PM.")


# ─── The sweep ───────────────────────────────────────────────────────

NOW = chi(2026, 10, 22, 15, 30).astimezone(timezone.utc)
NIGHT = {"id": "s1", "course_id": "c1", "title": "Week 1", "starts_at": chi(2026, 10, 22, 18).astimezone(timezone.utc).isoformat(),
         "teacher_name": "Pastor Kevin", "academy_lessons": {"title": "New Life & Identity"},
         "academy_courses": {"title": "The Making: Foundation", "business_id": BIZ, "status": "published", "remind_live": True}}
STUDENTS = [{"enrollment_id": "e1", "contact_id": "k1", "token": "t1", "name": "Dana Wells", "email": "dana@example.com"},
            {"enrollment_id": "e2", "contact_id": "k2", "token": "t2", "name": "Marcus Hill", "email": "+15551234567"}]


@pytest.fixture
def world(monkeypatch):
    w = {"nights": [NIGHT], "claim": {"session_id": "s1", "course_id": "c1", "students": STUDENTS}, "gets": [], "claims": [],
         "emails": [], "pushes": [], "business": [{"id": BIZ, "name": "Love City Church", "type": "church", "settings": {}}]}
    import sb_clients

    def get(path, *a, **k):
        w["gets"].append(path)
        if path.startswith("/academy_live_sessions?"):
            return w["nights"]
        if path.startswith("/businesses?"):
            return w["business"]
        return []

    def post(path, body=None, *a, **k):
        assert path == "/rpc/academy_live_reminder_claim"
        w["claims"].append(body["p_session"])
        return w["claim"]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    monkeypatch.setattr(ar, "_zone", lambda b: TZ)

    async def email(business, course_title, night, when, student, session_id):
        if "@" not in str(student.get("email")):
            return False
        w["emails"].append((student["email"], course_title, night, when, session_id))
        return True
    monkeypatch.setattr(ar, "_email", email)
    monkeypatch.setattr(member_push, "send", lambda business, kind, **k: w["pushes"].append((kind, k)) or 1)
    return w


def test_a_class_tonight_is_told_once_by_email_and_in_the_church_app(world):
    out = asyncio.run(ar.sweep_tick(NOW))
    assert out == {"nights": 1, "emails": 1, "phones": 1}
    assert world["emails"] == [("dana@example.com", "The Making: Foundation", "Week 1 · New Life & Identity", "tonight at 6 PM", "s1")]
    kind, k = world["pushes"][0]
    assert kind == "classes" and k["title"] == "Class tonight at 6 PM" and k["url"] == "/my/classes"
    assert k["contact_ids"] == ["k1", "k2"] and k["ref_id"] == "class:s1"
    q = world["gets"][0]
    assert "reminded_at=is.null" in q and "status=eq.scheduled" in q and "academy_courses.remind_live=is.true" in q
    assert "academy_courses.status=eq.published" in q and "+" not in q, "timestamps travel as Z, never a raw +"


def test_a_night_someone_else_claimed_is_left_alone(world):
    world["claim"] = None
    assert asyncio.run(ar.sweep_tick(NOW)) == {"nights": 0, "emails": 0, "phones": 0}
    assert world["emails"] == [] and world["pushes"] == []


def test_a_night_not_yet_due_is_never_claimed(world):
    assert asyncio.run(ar.sweep_tick(NOW - timedelta(hours=2)))["nights"] == 0
    assert world["claims"] == [], "claimed only when it's time, so it isn't marked and forgotten"


def test_a_business_that_cant_be_read_isnt_claimed(world):
    world["business"] = []
    asyncio.run(ar.sweep_tick(NOW))
    assert world["claims"] == [], "tried again next tick, never marked reminded with nobody told"


def test_one_failed_email_doesnt_stop_the_rest(world, monkeypatch):
    sent = []

    async def flaky(business, course_title, night, when, student, session_id):
        if student["enrollment_id"] == "e1":
            raise RuntimeError("resend down")
        sent.append(student["enrollment_id"])
        return True
    world["claim"]["students"] = STUDENTS + [{"enrollment_id": "e3", "contact_id": "k3", "token": "t3", "name": "Tasha", "email": "t@example.com"}]
    monkeypatch.setattr(ar, "_email", flaky)
    out = asyncio.run(ar.sweep_tick(NOW))
    assert sent == ["e2", "e3"] and out["phones"] == 1


def test_the_real_email_goes_to_the_student_with_their_class_link(monkeypatch):
    import email_sender
    calls = []

    async def send(**k):
        calls.append(k)
        return {}
    monkeypatch.setattr(email_sender, "send_via_resend", send)
    biz = {"id": BIZ, "name": "Love City Church", "settings": {}}
    ok = asyncio.run(ar._email(biz, "The Making: Foundation", "Week 1", "tonight at 6 PM", STUDENTS[0], "s1"))
    assert ok and calls[0]["to_email"] == "dana@example.com" and calls[0]["from_name"] == "Love City Church"
    assert calls[0]["idempotency_key"] == "class-reminder-s1-e1"
    assert "/classroom/t1" in calls[0]["body"] and "Open your class" in calls[0]["body"]
    assert not asyncio.run(ar._email(biz, "x", "", "tonight at 6 PM", STUDENTS[1], "s1")), "a phone number isn't emailed"


def test_class_nights_is_a_kind_the_church_switches_on_and_the_sweep_is_scheduled():
    assert "classes" in member_push.KIND_KEYS
    assert "classes" not in member_push.church_kinds({}), "off until the church turns it on"
    sql = (ROOT / "supabase/APPLY-2026-10-18-academy-class-reminders.sql").read_text(encoding="utf-8")
    assert "remind_live boolean not null default true" in sql
    assert "revoke all on function public.academy_live_reminder_claim(uuid) from public, anon, authenticated;" in sql
    assert "grant execute on function public.academy_live_reminder_claim(uuid) to service_role;" in sql
    assert "ls.reminded_at is null and ls.status = 'scheduled'" in sql and "c.status = 'published' and c.remind_live" in sql
    assert "e.status = 'active'" in sql
    boot = (ROOT / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert 'g("academy_class_reminders", _academy_reminders.sweep_tick)' in boot
