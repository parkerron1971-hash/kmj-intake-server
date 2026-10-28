"""Discussions and projects (step 3 of the Class Schedule design).

The database half (discussions every classmate sees, Amens, the teacher's
star and hide, a discussion that closes, a project's steps, an answer on the
TV) was rehearsed on production in a rolled-back transaction; see
docs/MIGRATIONS.md. These guard the APPLY file and the calendar's wording.
"""
from datetime import datetime, timezone
from pathlib import Path

import academy_calendar as cal

ROOT = Path(__file__).resolve().parent.parent
SQL = (ROOT / "supabase" / "APPLY-2026-10-18-academy-discussions.sql").read_text(encoding="utf-8")


def test_students_say_amen_and_teachers_moderate_through_their_own_doors():
    assert "grant execute on function public.academy_amen(uuid, uuid, boolean) to anon, authenticated;" in SQL
    assert "revoke all on function public.academy_item_moderate(uuid, boolean, boolean) from public, anon;" in SQL
    assert "revoke all on table public.academy_item_amens from anon, authenticated;" in SQL
    assert "revoke all on function public.academy_item_answers(uuid, uuid) from public, anon, authenticated;" in SQL


def test_hidden_answers_and_your_own_never_reach_the_class():
    answers = SQL[SQL.index("create or replace function public.academy_item_answers"):SQL.index("-- The student's schedule")]
    assert "not w3.hidden" in answers and "w3.enrollment_id <> p_me" in answers


def test_a_discussion_is_always_shared_and_a_project_step_is_homework_in_its_class():
    guard = SQL[SQL.index("create or replace function public.academy_schedule_items_guard"):SQL.index("drop trigger if exists academy_schedule_items_guard")]
    assert "new.kind = 'discussion' then\n    new.shared := true" in guard
    assert "new.kind <> 'homework'" in guard and "p.course_id = new.course_id and p.kind = 'project'" in guard


def test_a_project_row_is_never_work_and_discussions_close():
    save = SQL[SQL.index("create or replace function public.academy_save_item_work"):SQL.index("-- Amen to a classmate")]
    assert "and kind <> 'project'" in save
    assert "raise exception 'This discussion has closed'" in save


def test_the_tv_answer_keeps_the_old_presenter_calls_working():
    assert "drop function if exists public.academy_present_update(uuid, integer, boolean, jsonb, boolean);" in SQL
    assert "p_end boolean default false, p_answer jsonb default null)" in SQL
    assert "grant execute on function public.academy_present_update(uuid, integer, boolean, jsonb, boolean, jsonb) to authenticated, service_role;" in SQL
    view = SQL[SQL.index("create or replace function public.academy_present_view"):]
    assert "'answer', s.answer" in view and "name" not in view.split("'answer', s.answer")[0].split("jsonb_build_object(\n    'found', true")[-1]


def test_the_calendar_says_when_a_discussion_closes():
    ics = cal.build_ics("Foundation", "3f2c9a10-1b2c-4d5e-8f90-1a2b3c4d5e6f", [],
                        [{"id": "d1", "kind": "discussion", "title": "Which verse has carried you?", "due_at": "2026-11-03T23:00:00+00:00"},
                         {"id": "h1", "kind": "homework", "title": "Pick it", "due_at": "2026-11-03T23:00:00+00:00"}],
                        now=datetime(2026, 10, 18, tzinfo=timezone.utc))
    assert "SUMMARY:Discussion closes: Which verse has carried you?" in ics.replace("\r\n ", "")
    assert "SUMMARY:Due: Pick it" in ics
