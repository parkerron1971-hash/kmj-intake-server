"""How lessons open: a class can run together from a start date.

academy_courses.opens_from is when week 1 opens for everyone; each later
lesson opens a week after (or its own days after, on a custom schedule).
Empty, lessons count from the day each person joins, as before. The
database rule (academy_lesson_unlock, in the APPLY file) was rehearsed on
production in a rolled-back transaction; these cover the Python copy the
older /learn pages use, and the class page's one line about it.
"""
import asyncio
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import academy_join as aj
import public_site as ps

ROOT = Path(__file__).resolve().parent.parent
BIZ = "009e9a2c-3e81-4bfc-a92a-205a8806aa99"
COURSE = "c480f7f0-740d-4c78-9578-12f7e0150102"


def _iso(dt: datetime) -> str:
    return dt.isoformat()


NOW = datetime.now(timezone.utc)
JOINED_TODAY = _iso(NOW - timedelta(minutes=5))


def test_together_counts_from_the_start_date_so_late_joiners_catch_up():
    started = _iso(NOW - timedelta(days=8))
    opens = [ps._learn_unlock("weekly", i, 0, JOINED_TODAY, started) for i in range(4)]
    assert opens[0] is None and opens[1] is None  # weeks 1 and 2 have passed
    assert opens[2] is not None and opens[3] is not None
    assert abs((opens[2] - (NOW + timedelta(days=6))).total_seconds()) < 120


def test_before_the_start_date_even_week_one_waits():
    starts = NOW + timedelta(days=2)
    first = ps._learn_unlock("weekly", 0, 0, JOINED_TODAY, _iso(starts))
    assert first is not None and abs((first - starts).total_seconds()) < 1


def test_without_a_start_date_lessons_count_from_the_day_each_person_joins():
    assert ps._learn_unlock("weekly", 0, 0, JOINED_TODAY) is None
    assert ps._learn_unlock("weekly", 1, 0, JOINED_TODAY, None) is not None
    assert ps._learn_unlock("weekly", 1, 0, _iso(NOW - timedelta(days=8)), None) is None


def test_all_at_once_ignores_a_start_date():
    assert all(ps._learn_unlock("none", i, 0, JOINED_TODAY, _iso(NOW + timedelta(days=9))) is None for i in range(4))


def test_its_own_schedule_counts_each_lessons_days_from_the_start_date():
    started = _iso(NOW - timedelta(days=3))
    assert ps._learn_unlock("custom", 1, 2, JOINED_TODAY, started) is None
    assert ps._learn_unlock("custom", 1, 7, JOINED_TODAY, started) is not None


def test_six_pm_stays_six_pm_after_daylight_saving_ends(monkeypatch):
    # Thursdays 6 PM in Chicago from Oct 22: week 3 (Nov 5) opens at 6 PM CST,
    # which is midnight UTC, not 11 PM.
    class Then(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(ps, "datetime", Then)
    week3 = ps._learn_unlock("weekly", 2, 0, "2026-10-01T00:00:00+00:00",
                             "2026-10-22T23:00:00+00:00", "America/Chicago")
    assert week3.astimezone(timezone.utc) == datetime(2026, 11, 6, 0, 0, tzinfo=timezone.utc)
    without_zone = ps._learn_unlock("weekly", 2, 0, "2026-10-01T00:00:00+00:00", "2026-10-22T23:00:00+00:00")
    assert without_zone == datetime(2026, 11, 5, 23, 0, tzinfo=timezone.utc)


def test_the_database_rule_says_the_same():
    sql = (ROOT / "supabase" / "APPLY-2026-10-18-academy-opens-from.sql").read_text(encoding="utf-8")
    assert "add column if not exists opens_from timestamptz" in sql
    assert "add column if not exists opens_tz text" in sql
    assert "create or replace function public.academy_lesson_unlock" in sql
    assert "p_course.drip_mode in ('weekly', 'custom') and p_course.opens_from is not null" in sql
    assert "at time zone coalesce(p_course.opens_tz, 'UTC')" in sql
    assert "create trigger academy_course_tz_check" in sql


# ─── The class page's line ───────────────────────────────────────────

def _chicago(monkeypatch):
    monkeypatch.setitem(sys.modules, "outside_calendar",
                        types.SimpleNamespace(business_timezone=lambda biz: "America/Chicago"))


def test_the_class_page_says_when_a_together_class_starts_in_the_churchs_time(monkeypatch):
    _chicago(monkeypatch)
    starts = datetime(2030, 10, 24, 23, 0, tzinfo=timezone.utc)  # 6 PM in Chicago
    note = aj.release_note(BIZ, {"drip_mode": "weekly", "opens_from": starts.isoformat()})
    assert note.startswith("One lesson a week, together, from ") and "October 24 at 6 PM" in note


def test_once_it_has_started_the_page_invites_people_to_catch_up(monkeypatch):
    _chicago(monkeypatch)
    note = aj.release_note(BIZ, {"drip_mode": "weekly", "opens_from": "2020-10-22T23:00:00+00:00"})
    assert note == ("One lesson a week, together, since Thursday, October 22. "
                    "Join now and the weeks so far are open to catch up.")


def test_the_page_uses_the_zone_the_class_was_set_in(monkeypatch):
    monkeypatch.setitem(sys.modules, "outside_calendar",
                        types.SimpleNamespace(business_timezone=lambda biz: "America/Chicago"))
    note = aj.release_note(BIZ, {"drip_mode": "weekly", "opens_from": "2030-10-24T23:00:00+00:00",
                                 "opens_tz": "America/New_York"})
    assert "October 24 at 7 PM" in note


def test_the_other_ways_read_as_they_did():
    assert aj.release_note(BIZ, {"drip_mode": "none"}) == "Everything is available the moment you join."
    assert aj.release_note(BIZ, {"drip_mode": "weekly"}) == "New material unlocks each week after you join."
    assert aj.release_note(BIZ, {"drip_mode": "custom", "opens_from": None}).startswith("Material unlocks")
    assert aj.release_note(BIZ, {"drip_mode": "none", "opens_from": "2030-10-24T23:00:00+00:00"}).startswith("Everything")


def test_the_class_page_carries_the_line(monkeypatch):
    _chicago(monkeypatch)
    course = {"id": COURSE, "title": "Foundation", "description": "", "status": "published",
              "drip_mode": "weekly", "opens_from": "2030-10-24T23:00:00+00:00",
              "product_id": None, "self_join": True}

    async def fake_sb(client, path):
        if path.startswith("/academy_courses"):
            assert "opens_from" in path
            return [course]
        if path.startswith("/academy_lessons"):
            return [{"title": "New Life & Identity", "duration_minutes": 45, "lesson_type": "text"}]
        return []

    async def fake_brand(client, biz):
        return "Love City Church", "#C2125F", {}, {}

    monkeypatch.setattr(ps, "_sb_service", fake_sb)
    monkeypatch.setattr(ps, "_academy_brand", fake_brand)
    monkeypatch.setattr(ps, "_academy_skin", lambda *a: ("#C2125F", ""))
    monkeypatch.setattr(ps, "_inject_brand_meta", lambda html, biz: html)
    monkeypatch.setattr(aj, "next_class_line", lambda biz, cid: "")
    page = asyncio.run(ps._serve_academy(None, BIZ, f"/academy/{COURSE}", standalone=False)).body.decode()
    assert "One lesson a week, together, from " in page and "October 24 at 6 PM" in page
