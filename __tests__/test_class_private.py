"""A private class (Kevin 2026-11-08, training one leader toward ordination:
"i will only be doing this with her so i believe private access").

"Only people you add" closes the sign-up form and nothing else. A private class
is also on no public page, offered to nobody, read by no office login, not
counted in Services & Events, and never a milestone the office drafts. Its one
student still gets in, by their class link and in the member app.
"""
import asyncio
import re
from pathlib import Path
from unittest import mock

import academy_class_nights as nights
import academy_join as aj
import chief_door_actions as cda
import church_roles
import member_portal_classes as mcl
import public_site as ps
import site_doors

ROOT = Path(__file__).resolve().parent.parent
SQL = (ROOT / "supabase" / "APPLY-2026-11-08-academy-private-class.sql").read_text(encoding="utf-8")

BIZ = "009e9a2c-3e81-4bfc-a92a-205a8806aa99"
COURSE = "c480f7f0-740d-4c78-9578-12f7e0150102"
MEMBER = "11111111-2222-4333-8444-555555555555"
OPEN = {"status": "published", "self_join": True, "product_id": None}


# ─── the one rule for "open to join" ──────────────────────────────────

def test_a_private_class_is_never_open_to_join():
    assert aj.join_open(OPEN)
    assert not aj.join_open({**OPEN, "private": True}), "even with self_join on, it takes no sign-ups"


def test_the_join_paths_read_the_column_the_rule_needs():
    with mock.patch("sb_clients.sb_get_as_service", return_value=[]) as get:
        aj._course(COURSE)
    assert "private" in get.call_args[0][0].split("select=")[1]
    with mock.patch("sb_clients.sb_get_as_service", return_value=[{**OPEN, "id": COURSE, "private": True}]) as get:
        ok, code, _ = mcl.join_class(BIZ, {"id": MEMBER}, COURSE)
    assert "private" in get.call_args[0][0].split("select=")[1]
    assert (ok, code) == (False, "class_closed"), "one tap in the member app can't get in either"


def test_the_database_says_the_same_rule():
    open_fn = SQL[SQL.index("create or replace function public.academy_course_open"):]
    assert "and not c.private" in open_fn[:open_fn.index("$$;")]


# ─── the website ──────────────────────────────────────────────────────

def _site(monkeypatch, path):
    seen = []

    async def fake_sb(client, p):
        seen.append(p)
        return []

    async def fake_brand(client, biz):
        return "Love City Church", "#C2125F", {}, {}

    monkeypatch.setattr(ps, "_sb_service", fake_sb)
    monkeypatch.setattr(ps, "_academy_brand", fake_brand)
    monkeypatch.setattr(ps, "_academy_skin", lambda *a: ("#C2125F", ""))
    monkeypatch.setattr(ps, "_academy_zone", lambda biz: "America/Chicago")
    monkeypatch.setattr(ps, "_inject_brand_meta", lambda html, biz: html)
    try:
        asyncio.run(ps._serve_academy(None, BIZ, path, standalone=False))
    except Exception:  # noqa: BLE001  the page's own 404 is fine here; the read is what's held
        pass
    return [p for p in seen if p.startswith("/academy_courses")]


def test_the_class_list_never_reads_a_private_class(monkeypatch):
    (read, *_) = _site(monkeypatch, "/academy")
    assert "status=eq.published" in read and "private=is.false" in read


def test_a_private_classs_own_page_is_not_found(monkeypatch):
    (read, *_) = _site(monkeypatch, f"/academy/{COURSE}")
    assert f"id=eq.{COURSE}" in read and "private=is.false" in read


def test_a_private_class_opens_no_courses_door_on_the_site():
    calls = []
    with mock.patch.object(site_doors, "_rows", side_effect=lambda p: calls.append(p) or []):
        site_doors.door_facts(BIZ)
    read = next(p for p in calls if p.startswith("/academy_courses"))
    assert "private=is.false" in read


# ─── the member app ───────────────────────────────────────────────────

def test_a_private_class_alone_never_turns_the_tab_on_for_everyone():
    mcl._on_cache.clear()
    with mock.patch("sb_clients.sb_get_as_service", return_value=[]) as get:
        assert mcl.classes_on(BIZ) is False
    assert "private=is.false" in get.call_args[0][0]


def test_its_student_still_gets_the_tab():
    mcl._on_cache.clear()

    def get(path, *a, **k):
        return [{"id": "e1"}] if path.startswith("/academy_enrollments") else []
    with mock.patch("sb_clients.sb_get_as_service", side_effect=get):
        assert mcl.tab_on(BIZ, {"id": MEMBER}) is True
    mcl._on_cache.clear()
    with mock.patch("sb_clients.sb_get_as_service", return_value=[]):
        assert mcl.tab_on(BIZ, {"id": MEMBER}) is False, "anyone else doesn't"


def test_a_failed_read_or_no_member_is_no_tab():
    mcl._on_cache.clear()
    with mock.patch("sb_clients.sb_get_as_service", return_value=None):
        assert mcl.tab_on(BIZ, {"id": MEMBER}) is False
    mcl._on_cache.clear()
    with mock.patch("sb_clients.sb_get_as_service", return_value=[]) as get:
        assert mcl.tab_on(BIZ, None) is False and mcl.tab_on(BIZ, {"id": "not-a-uuid"}) is False
    assert not any("academy_enrollments" in c[0][0] for c in get.call_args_list), "nothing odd reaches the query"


# ─── the office ───────────────────────────────────────────────────────

def _night(private):
    return {"id": "s1", "academy_courses": {"title": "Ordination Training", "business_id": BIZ, "private": private}}


def test_a_private_night_is_marked_counted_with_no_occasion():
    with mock.patch("church_follow_up.is_church", return_value=True), \
            mock.patch.object(nights, "_occasion", return_value=(True, "occ-1")) as occasion, \
            mock.patch("sb_clients.sb_post_as_service", return_value={"counted": 0}) as post:
        nights._count({"id": BIZ}, _night(True))
    occasion.assert_not_called()
    assert post.call_args[0][1] == {"p_session": "s1", "p_entry": None}, "never again in the tick, and in no room"


def test_any_other_class_night_at_a_church_still_counts():
    with mock.patch("church_follow_up.is_church", return_value=True), \
            mock.patch.object(nights, "_occasion", return_value=(True, "occ-1")) as occasion, \
            mock.patch("sb_clients.sb_post_as_service", return_value={"counted": 2}) as post:
        assert nights._count({"id": BIZ}, _night(False)) == 2
    occasion.assert_called_once()
    assert post.call_args[0][1]["p_entry"] == "occ-1"


def test_the_sweep_reads_whether_a_night_is_private():
    assert "academy_courses!inner(title,business_id,private)" in nights.SESSION_FIELDS


def test_the_role_library_never_offers_a_private_class():
    calls = []
    with mock.patch.object(church_roles, "_rows", side_effect=lambda p: calls.append(p) or []):
        assert church_roles._classes(BIZ) == []
    assert "private=is.false" in calls[0]


# ─── Chief's words ────────────────────────────────────────────────────

def _publish(course):
    async def ctx(client, method, path, body=None, **kw):
        if method == "GET" and path.startswith("/academy_courses"):
            return [course]
        if method == "GET" and path.startswith("/academy_lessons"):
            return [{"title": "Week 1", "content": "x" * 400, "video_url": "", "resource_url": "", "learning_design": {}}]
        return [body]
    with mock.patch.object(cda.sb_clients, "sb_as_current_context", side_effect=ctx), \
            mock.patch.object(cda, "_site_origin", return_value="https://church.org"), \
            mock.patch.object(cda, "course_readiness", return_value=[]):
        return asyncio.run(cda.handle_publish_course(None, {"id": BIZ}, {"course": course["id"]}))


def test_publishing_a_private_class_never_says_it_is_on_the_website():
    out = _publish({"id": COURSE, "title": "Ordination Training", "description": "", "status": "draft", "private": True})
    assert out["url"] is None and "https://church.org" not in out["result"]
    assert "private" in out["result"] and "only the people you add" in out["result"]


def test_publishing_any_other_class_still_gives_its_page():
    out = _publish({"id": COURSE, "title": "New Members", "description": "", "status": "draft", "private": False})
    assert out["url"] == f"https://church.org/academy/{COURSE}" and "is published at" in out["result"]


# ─── the migration ────────────────────────────────────────────────────

def _policy(name, table):
    m = re.search(rf"create policy {name} on public\.{table} .*?;", SQL, re.S)
    assert m, f"{name} on {table}"
    return m.group(0)


def test_off_by_default_so_no_class_changes_until_its_owner_says():
    assert "add column if not exists private boolean not null default false" in SQL


def test_every_table_an_office_login_can_read_stops_at_a_private_class():
    # Who can really read what is held on a real Postgres: academy_private_db.mjs.
    assert "not private" in _policy("tenant_member_read", "academy_courses")
    for table in ("academy_lessons", "academy_enrollments"):
        assert "not public.academy_course_private(course_id)" in _policy("tenant_member_read", table)
    items = _policy("academy_schedule_items_read", "academy_schedule_items")
    assert "public.academy_can_teach(course_id)" in items, "teachers keep it"
    assert "not public.academy_course_private(course_id)" in items


def test_each_policy_is_dropped_before_it_is_made_so_it_can_run_twice():
    for name, table in (("tenant_member_read", "academy_courses"), ("tenant_member_read", "academy_lessons"),
                        ("tenant_member_read", "academy_enrollments"),
                        ("academy_schedule_items_read", "academy_schedule_items")):
        assert f"drop policy if exists {name} on public.{table};" in SQL


def test_the_cross_table_check_goes_through_a_definer_helper():
    # docs/RLS_MODEL.md rule 2: an EXISTS inlined in a policy is how 42P17 got in.
    helper = SQL[SQL.index("create or replace function public.academy_course_private"):]
    assert "security definer" in helper[:helper.index("$$")]
    assert "set search_path" in helper[:helper.index("$$")]
    assert "revoke all on function public.academy_course_private(uuid) from public, anon;" in SQL
    for name, table in (("tenant_member_read", "academy_lessons"), ("tenant_member_read", "academy_enrollments"),
                        ("academy_schedule_items_read", "academy_schedule_items")):
        assert "exists" not in _policy(name, table).lower()


def test_the_migration_is_one_transaction():
    assert SQL.count("\nbegin;\n") == 1 and SQL.rstrip().endswith("commit;")
