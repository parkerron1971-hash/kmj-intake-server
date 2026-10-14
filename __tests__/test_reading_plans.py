"""
test_reading_plans.py — the church reads the Bible together, a day at a time.

Pins: every plan covers its chapters exactly once, in order, with no empty
day; today's reading follows the start date; a member can tick today or
earlier, never the future; staff (owner/admin/manager) choose and stop
the plan; the Home card and the plan page say the right things.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import bible_text as bt
import reading_plans as R

BIZ = "11111111-1111-1111-1111-111111111111"
ME = "cccccccc-0000-0000-0000-00000000000c"


def _flat(key):
    return [(c, n) for day in R.schedule(key) for c, a, b in day for n in range(a, b + 1)]


@pytest.mark.parametrize("key,books", [
    ("bible-year", [c for c, _, _ in bt.BOOKS]),
    ("nt-260", [c for c, _, _ in bt.BOOKS[39:]]),
    ("gospels-30", ["MAT", "MAR", "LUK", "JOH"])])
def test_each_plan_reads_every_chapter_once_in_order(key, books):
    want = [(c, n) for c in books for n in range(1, bt.chapter_count(c) + 1)]
    assert _flat(key) == want
    assert len(R.schedule(key)) == R.PLANS[key]["days"]
    assert all(day for day in R.schedule(key))


def test_the_year_plan_is_even():
    sizes = [sum(b - a + 1 for _, a, b in day) for day in R.schedule("bible-year")]
    assert min(sizes) >= 3 and max(sizes) <= 4


def test_psalms_and_proverbs_covers_both_books():
    flat = _flat("psalms-proverbs-31")
    assert sorted(n for c, n in flat if c == "PSA") == list(range(1, 151))
    assert [n for c, n in flat if c == "PRO"] == list(range(1, 32))
    assert R.label(R.schedule("psalms-proverbs-31")[0]) == "Psalms 1–5; Proverbs 1"


def test_labels_and_links():
    assert R.label([("GEN", 1, 3)]) == "Genesis 1–3"
    assert R.label([("GEN", 50, 50), ("EXO", 1, 2)]) == "Genesis 50; Exodus 1–2"
    assert R.href([("1JO", 1, 2)]).startswith("/my/bible/")


def _biz(key="bible-year", start=None):
    start = start or date.today()
    return {"id": BIZ, "settings": {"reading_plan": {"key": key, "start": start.isoformat()}}}


def test_today_follows_the_start_date():
    t = R.today_for(_biz(start=date.today() - timedelta(days=9)))
    assert t["day"] == 10 and t["of"] == 365
    assert t["label"] == R.label(R.schedule("bible-year")[9])
    assert R.today_for(_biz(start=date.today() + timedelta(days=1))) is None   # not started
    assert R.today_for(_biz(key="gospels-30", start=date.today() - timedelta(days=30))) is None  # over
    assert R.today_for({"id": BIZ, "settings": {}}) is None
    assert R.today_for({"id": BIZ, "settings": {"reading_plan": {"key": "nope", "start": "2026-01-01"}}}) is None


def test_a_future_day_cannot_be_ticked(monkeypatch):
    plan = R.current(_biz(start=date.today() - timedelta(days=2)))     # today is day 3
    assert R.readable_upto(plan) == 3
    calls = []
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda *a, **k: calls.append(a) or [])
    assert R.mark(BIZ, ME, plan, 4, True) is False and calls == []
    assert R.mark(BIZ, ME, plan, 3, True) is True
    path, body = calls[0]
    assert path.startswith("/reading_progress?on_conflict=")
    assert body == {"business_id": BIZ, "contact_id": ME, "plan_key": "bible-year",
                    "start_date": plan["start"].isoformat(), "day": 3}
    over = R.current(_biz(key="gospels-30", start=date.today() - timedelta(days=60)))
    assert R.readable_upto(over) == 30                                    # catch up after it ends
    before = R.current(_biz(start=date.today() + timedelta(days=5)))
    assert R.readable_upto(before) == 0


def test_streak_counts_back_from_today_or_yesterday():
    assert R.streak({8, 9, 10}, 10) == 3
    assert R.streak({8, 9}, 10) == 2          # today not read yet: still counts
    assert R.streak({5, 9}, 10) == 1
    assert R.streak(set(), 10) == 0


# ─── staff choose and stop ───────────────────────────────────────────

@pytest.fixture
def staff(monkeypatch):
    state = {"role": "owner", "settings": {"giving": {"enabled": True}}, "patched": []}
    monkeypatch.setattr(R, "_role", lambda biz, user: state["role"])
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p: [{"id": BIZ, "owner_id": "o", "settings": state["settings"]}])
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda p, b: state["patched"].append((p, b)) or [b])
    return state


def test_staff_choose_a_plan_and_other_settings_survive(staff):
    out = R.choose_reading_plan({"business_id": BIZ, "plan": "nt-260", "start": date.today().isoformat()},
                                SimpleNamespace(id="u"))
    assert out["current"]["key"] == "nt-260"
    path, body = staff["patched"][0]
    assert path == f"/businesses?id=eq.{BIZ}"
    assert body["settings"]["giving"] == {"enabled": True}
    assert body["settings"]["reading_plan"]["key"] == "nt-260"


@pytest.mark.parametrize("role", ["member", "viewer", None])
def test_only_owner_admin_or_manager_choose(staff, role):
    staff["role"] = role
    with pytest.raises(HTTPException) as e:
        R.choose_reading_plan({"business_id": BIZ, "plan": "nt-260", "start": date.today().isoformat()},
                              SimpleNamespace(id="u"))
    assert e.value.status_code == 403 and staff["patched"] == []


@pytest.mark.parametrize("body", [{"plan": "nope"}, {"plan": "nt-260", "start": "soon"},
                                  {"plan": "nt-260", "start": "2020-01-01"}])
def test_bad_choices_are_refused(staff, body):
    with pytest.raises(HTTPException) as e:
        R.choose_reading_plan({"business_id": BIZ, **body}, SimpleNamespace(id="u"))
    assert e.value.status_code == 400


def test_any_seat_reads_the_catalog_and_current(staff):
    staff["role"] = "viewer"
    staff["settings"] = {"reading_plan": {"key": "gospels-30", "start": date.today().isoformat()}}
    out = R.reading_plans(BIZ, SimpleNamespace(id="u"))
    assert [p["key"] for p in out["plans"]] == list(R.PLANS)
    assert out["current"]["key"] == "gospels-30" and out["current"]["today"]["day"] == 1
    staff["role"] = None
    with pytest.raises(HTTPException):
        R.reading_plans(BIZ, SimpleNamespace(id="u"))


def test_stopping_removes_only_the_plan(staff):
    staff["settings"] = {"reading_plan": {"key": "gospels-30", "start": "2026-10-01"}, "x": 1}
    R.stop_reading_plan(BIZ, SimpleNamespace(id="u"))
    assert staff["patched"][0][1]["settings"] == {"x": 1}


# ─── member pages ────────────────────────────────────────────────────

def test_home_card_offers_read_and_tick_then_says_read():
    import member_portal_reading as M
    today = R.today_for(_biz())
    card = M.home_card(today, set())
    assert "Today's reading · Day 1 of 365" in card and "Mark as read" in card and "Genesis 1–3" in card
    card = M.home_card(today, {1})
    assert "Read today" in card and "Mark as read" not in card
    assert M.home_card(None, None) == ""


def _req(q=""):
    from starlette.requests import Request
    return Request({"type": "http", "query_string": q.encode(), "headers": [], "path": "/my/reading"})


def test_plan_page_shows_progress_and_catch_up():
    import member_portal_reading as M
    biz = dict(_biz(start=date.today() - timedelta(days=4)), name="Love City Church")   # day 5
    html = M.render_page(biz, None, _req(), {"id": ME, "name": "Ruth"}, {1, 2, 5})
    assert "3 <span" in html and "of 365 days read" in html
    assert "2 days to catch up" in html            # days 3 and 4
    assert "Day 5" in html


def test_plan_page_before_it_starts_and_with_no_plan():
    import member_portal_reading as M
    biz = dict(_biz(start=date.today() + timedelta(days=3)), name="X")
    assert "It starts" in M.render_page(biz, None, _req(), {"id": ME}, set())
    assert "hasn't started a reading plan" in M.render_page({"id": BIZ, "settings": {}, "name": "X"},
                                                          None, _req(), {"id": ME}, set())


def test_routes_are_mounted_before_the_catch_all():
    import os
    os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test")
    import kmj_intake_automation
    routes = [(getattr(r, "path", ""), getattr(r, "methods", set()) or set()) for r in kmj_intake_automation.app.routes]
    paths = [p for p, _ in routes]
    end = paths.index("/{path:path}")
    assert paths.index("/church/reading-plans") < end
    assert next(i for i, (p, m) in enumerate(routes) if p == "/my/reading" and "POST" in m) < end
