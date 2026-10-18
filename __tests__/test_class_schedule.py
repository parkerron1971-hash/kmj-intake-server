"""The class schedule (step 2 of the Class Schedule design).

The database half (academy_schedule_items, academy_item_work, the
student's schedule, saving work, the teacher's reply, the one "finished"
rule) was rehearsed on production in a rolled-back transaction; see
docs/MIGRATIONS.md. These cover the calendar feed a student's phone
subscribes to, the APPLY file's guards, and the business export.
"""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import academy_calendar as cal
import account_lifecycle as al

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "3f2c9a10-1b2c-4d5e-8f90-1a2b3c4d5e6f"
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)

SESSIONS = [
    {"id": "s1", "title": "Week 2 class", "starts_at": "2026-10-29T23:00:00+00:00", "duration_minutes": 90, "status": "scheduled"},
    {"id": "s0", "title": "Called off", "starts_at": "2026-10-22T23:00:00+00:00", "duration_minutes": 60, "status": "cancelled"},
]
ITEMS = [
    {"id": "h1", "kind": "homework", "title": "Write your story; three sentences, no more",
     "details": "Before, how you met Him, since.", "due_at": "2026-10-28T23:00:00+00:00"},
    {"id": "g1", "kind": "gathering", "title": "Serve day", "details": "", "place": "1084 Allen Ave, Fort Worth",
     "starts_at": "2026-10-31T14:00:00+00:00"},
    {"id": "h9", "kind": "homework", "title": "No week yet", "due_at": None},
]


def _ics():
    return cal.build_ics("The Making: Foundation", TOKEN, SESSIONS, ITEMS, now=NOW)


def test_the_calendar_carries_class_nights_due_dates_and_gatherings():
    ics = _ics()
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert ics.count("BEGIN:VEVENT") == 3  # the called-off class and the undated item stay off
    assert "UID:live-s1@mysolutionist.app" in ics and "DTSTART:20261029T230000Z" in ics and "DTEND:20261030T003000Z" in ics
    assert "UID:due-h1@mysolutionist.app" in ics and "DTEND:20261028T230000Z" in ics
    assert "UID:gathering-g1@mysolutionist.app" in ics and "DTSTART:20261031T140000Z" in ics
    assert "X-WR-CALNAME:The Making: Foundation" in ics


def test_text_is_escaped_and_long_lines_fold():
    ics = _ics()
    assert "SUMMARY:Due: Write your story\\; three sentences\\, no more" in ics
    assert "LOCATION:1084 Allen Ave\\, Fort Worth" in ics
    for line in ics.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75, line
    long = cal.build_ics("Clase", TOKEN, [], [{"id": "x", "kind": "homework", "title": "Lee Juan " + "ñ" * 60,
                                                "due_at": "2026-10-28T23:00:00+00:00"}], now=NOW)
    unfolded = long.replace("\r\n ", "")
    assert "SUMMARY:Due: Lee Juan " + "ñ" * 60 in unfolded  # never split inside a character


def test_every_event_opens_the_students_own_classroom():
    assert f"URL:https://system.mysolutionist.app/classroom/{TOKEN}" in _ics().replace("\r\n ", "")


def _client(monkeypatch, loaded):
    monkeypatch.setattr(cal, "_load", lambda token: loaded)
    app = FastAPI()
    app.include_router(cal.router)
    return TestClient(app)


def test_the_feed_answers_with_a_calendar_that_is_never_cached(monkeypatch):
    r = _client(monkeypatch, ("Foundation", SESSIONS, ITEMS)).get(f"/academy-calendar/{TOKEN}.ics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert r.headers["cache-control"] == "no-store" and "BEGIN:VEVENT" in r.text


def test_a_bad_or_inactive_link_is_a_bare_404(monkeypatch):
    client = _client(monkeypatch, None)
    assert client.get(f"/academy-calendar/{TOKEN}.ics").status_code == 404
    assert client.get("/academy-calendar/not-a-link.ics").status_code == 404


def test_only_a_published_class_with_both_reads_makes_a_calendar(monkeypatch):
    import sb_clients
    rows = {"course": [{"academy_courses": {"title": "Foundation", "status": "published"}}]}
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, redact=False: rows["course"])
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda path, body, prefer=None, redact=False: [] if "student_live" in path else {"items": ITEMS})
    title, sessions, items = cal._load(TOKEN)
    assert title == "Foundation" and items == ITEMS and sessions == []
    rows["course"] = [{"academy_courses": {"title": "Foundation", "status": "draft"}}]
    assert cal._load(TOKEN) is None
    rows["course"] = []
    assert cal._load(TOKEN) is None
    rows["course"] = [{"academy_courses": {"title": "Foundation", "status": "published"}}]
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda path, body, prefer=None, redact=False: None)
    assert cal._load(TOKEN) is None


def test_the_feed_is_mounted_before_the_public_site():
    src = (ROOT / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert src.index("app.include_router(academy_calendar_router)") < src.index("app.include_router(public_site_router)")
    assert "/academy-calendar/{token}.ics" in {r.path for r in cal.router.routes}


# ─── The APPLY file's guards ─────────────────────────────────────────

SQL = (ROOT / "supabase" / "APPLY-2026-10-18-academy-schedule.sql").read_text(encoding="utf-8")


def test_students_reach_their_schedule_only_through_their_class_link():
    assert "revoke all on table public.academy_schedule_items from anon;" in SQL
    assert "revoke all on table public.academy_item_work from anon;" in SQL
    assert "grant execute on function public.academy_classroom_schedule(uuid) to anon, authenticated;" in SQL
    assert "grant execute on function public.academy_save_item_work(uuid, uuid, boolean, text, integer) to anon, authenticated;" in SQL
    assert "revoke all on function public.academy_items_done(uuid) from public, anon, authenticated;" in SQL
    assert "revoke all on function public.academy_enrollment_settle(uuid, boolean) from public, anon, authenticated;" in SQL


def test_one_rule_decides_finished_and_ticking_never_undoes_it():
    assert SQL.count("public.academy_enrollment_settle(e.id)") == 1  # finishing a lesson may reopen, as it always could
    assert "public.academy_enrollment_settle(e.id, false)" in SQL      # an item never undoes a teacher's "finished"
    assert "and public.academy_items_done(p_enrollment)" in SQL


def test_drafts_never_reach_students_and_a_lessons_quiz_stays_in_the_lesson():
    assert SQL.count("i.status = 'published'") >= 2
    assert "'quiz'" not in SQL


def test_the_schedule_goes_out_with_the_business_and_is_not_restored_onto_new_ids():
    assert "academy_schedule_items" in al.BUSINESS_CHILD_TABLES
    assert al.BUSINESS_CHILD_TABLES.index("academy_schedule_items") < al.BUSINESS_CHILD_TABLES.index("academy_lessons")
    assert "academy_schedule_items" in al._IMPORT_SKIP
