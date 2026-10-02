"""
test_chief_week.py — Chief's week is counted, not guessed.

What must hold:
  1. THE SENTENCES COME FROM THE COUNTS: moves this week only, drafts
     sent / replied / dismissed, tasks done, assignments done / out of
     time / still working, what is waiting, minutes — and an empty
     week says so and sends nothing.
  2. MONDAY DELIVERS ONCE per business per ISO week, as a notification,
     an activity row and a push; a business with the agent off and an
     empty ledger is skipped.
  3. THE DOOR IS OWNER-ONLY.
  4. THE SITE SAYS IT: three compare rows and one FAQ answer, with the
     filter counts kept honest.
House rules: sync tests + asyncio.run.
"""
from __future__ import annotations

import asyncio
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import chief_week as cw
import sb_clients

NOW = datetime(2026, 9, 14, 13, 30, tzinfo=timezone.utc)   # a Monday


def _run(coro):
    return asyncio.run(coro)


def _at(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def _m(verb, days_ago, **over):
    base = {"verb": verb, "made_at": _at(days_ago), "outcome": "done", "queue_id": None, "target_type": None}
    base.update(over)
    return base


# ─── 1. the sentences ────────────────────────────────────────────────

def test_the_sentences_come_from_the_counts():
    moves = [
        _m("send_sms", 1, queue_id="q1", outcome="approved"),
        _m("send_sms", 2, queue_id="q2", outcome="replied"),
        _m("send_sms", 3, queue_id="q3", outcome="dismissed"),
        _m("send_invoice", 4, queue_id="q4", outcome="pending"),
        _m("create_task", 1, target_type="task", outcome="completed"),
        _m("create_task", 2, target_type="task", outcome="ignored"),
        _m("create_task", 3, target_type="task", outcome="pending"),
        _m("create_note", 1), _m("create_note", 2), _m("create_note", 5),
        _m("remember", 6),
        _m("create_note", 12),   # last week: not counted
    ]
    assignments = [
        {"title": "Fill Thursday", "status": "completed", "updated_at": _at(2), "progress": {"label": "6 of 6 sessions on the calendar"}},
        {"title": "Five new leads", "status": "expired", "updated_at": _at(1), "progress": {"label": "3 of 5 new contacts"}},
        {"title": "Get invoice 12 paid", "status": "active", "progress": {"label": "not paid yet"}},
        {"title": "Old one", "status": "completed", "updated_at": _at(20), "progress": {}},
    ]
    r = cw.compose(moves, assignments, waiting=2, now=NOW)
    assert r["moves"] == 11 and r["proposals"]["filed"] == 4 and r["tasks"] == {"set": 3, "completed": 1, "ignored": 1}
    assert r["by_verb"] == {"create_note": 3, "remember": 1}
    assert r["minutes_saved"] == 4 * 6 + 3 * 3 + 3 * 2 + 1
    first = r["lines"][0]
    assert first.startswith("This week Chief made 11 moves on its own: ")
    assert "drafted 4 messages and sends for you (2 you sent, 1 got a reply, 1 you dismissed)" in first
    assert "set 3 tasks (1 done, 1 slipped past due)" in first and "left 3 notes" in first
    assert "Done: Fill Thursday — 6 of 6 sessions on the calendar." in r["lines"]
    assert "Out of time: Five new leads — 3 of 5 new contacts." in r["lines"]
    assert "Still working: Get invoice 12 paid — not paid yet." in r["lines"]
    assert "2 things are waiting on your tap in the Approval Queue." in r["lines"]
    assert r["lines"][-1] == f"About {r['minutes_saved']} minutes you did not have to spend."
    assert r["assignments"]["done"] == ["Fill Thursday"] and r["assignments"]["out_of_time"] == ["Five new leads"]
    assert r["spoken"] == " ".join(r["lines"]) and r["empty"] is False


def test_an_empty_week_says_so_and_is_empty():
    r = cw.compose([], [], waiting=0, now=NOW)
    assert r["lines"] == ["This week Chief made no moves on its own."] and r["empty"] is True
    r2 = cw.compose([], [{"title": "x", "status": "active", "progress": None}], waiting=0, now=NOW)
    assert r2["empty"] is False and "Still working: x — not measured yet." in r2["lines"]
    one = cw.compose([_m("send_sms", 1, queue_id="q", outcome="pending")], [], waiting=1, now=NOW)
    assert "drafted 1 message or send for you" in one["lines"][0]
    assert "1 thing is waiting on your tap" in one["spoken"]


# ─── 2. Monday ───────────────────────────────────────────────────────

@pytest.fixture
def monday(monkeypatch):
    state = {"posts": [], "pushed": [], "sent_keys": set()}

    def _get(path):
        if path.startswith("/chief_notifications"):
            key = path.split("dedup_key=eq.")[1].split("&")[0]
            return [{"id": "n"}] if key in state["sent_keys"] else []
        return []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)

    def _post(path, body, prefer=None):
        state["posts"].append((path, body))
        if path == "/chief_notifications":
            state["sent_keys"].add(body["action_payload"]["dedup_key"])
        return [{}]
    monkeypatch.setattr(sb_clients, "sb_post_as_service", _post)
    import push_notifications
    monkeypatch.setattr(push_notifications, "send_to_user", lambda uid, **kw: state["pushed"].append((uid, kw)) or 1)
    return state


def test_monday_delivers_once_per_week(monday):
    biz = {"id": "biz-1", "owner_id": "own-1", "settings": {"autonomy": {"agent_enabled": True}}}
    report = cw.compose([_m("create_note", 1)], [], waiting=1, now=NOW)
    assert cw.deliver(biz, report, NOW) is True
    kinds = [(p, b.get("type") or b.get("action_type")) for p, b in monday["posts"]]
    assert ("/chief_notifications", "reminder") in kinds and ("/chief_activity", "chief_week") in kinds
    note = monday["posts"][0][1]
    assert note["title"] == "Chief's week: 1 move, 1 waiting on you" and note["action_payload"]["dedup_key"] == "chief_week:2026-W38"
    assert monday["pushed"][0][0] == "own-1" and monday["pushed"][0][1]["tag"] == "chief-week"
    assert cw.deliver(biz, report, NOW) is False, "the same week is not sent twice"
    assert cw.deliver(biz, cw.compose([], [], 0, now=NOW), NOW) is False, "an empty week sends nothing"


def test_the_tick_skips_a_quiet_business_with_the_agent_off(monkeypatch, monday):
    on = {"id": "b-on", "owner_id": "o1", "settings": {"autonomy": {"agent_enabled": True}}}
    off = {"id": "b-off", "owner_id": "o2", "settings": {}}
    monkeypatch.setattr(cw, "_candidates", lambda: [on, off])
    monkeypatch.setattr(cw, "build", lambda bid, days=7, now=None:
                        cw.compose([_m("create_note", 1)] if bid == "b-on" else [], [], 0, now=NOW))
    out = _run(cw.weekly_tick(NOW))
    assert out == {"looked": 1, "sent": 1}
    monkeypatch.setenv("CHIEF_WEEK", "off")
    assert _run(cw.weekly_tick(NOW)) == {"skipped": "off"}


def test_build_degrades_to_empty_without_the_tables(monkeypatch):
    import chief_assignments
    import outcome_ledger

    def _boom(*a, **k):
        raise RuntimeError("no table")
    monkeypatch.setattr(outcome_ledger, "recent_moves", _boom)
    monkeypatch.setattr(chief_assignments, "recent_rows", _boom)
    monkeypatch.setattr(cw, "_waiting", _boom)
    assert cw.build("biz-1", now=NOW)["empty"] is True


# ─── 3. the door ─────────────────────────────────────────────────────

def test_the_door_is_owner_only(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [{"id": "biz-1", "owner_id": "own-1"}])

    class U:
        id = "stranger"
    with pytest.raises(HTTPException) as e:
        cw.week("biz-1", 7, U())
    assert e.value.status_code == 403


# ─── 4. the site ─────────────────────────────────────────────────────

def test_the_site_says_it():
    import marketing_pages as mp
    compare = mp.render_compare() if hasattr(mp, "render_compare") else ""
    faq = mp.render_faq()
    assert "Give Chief an assignment" in compare and "fill Thursday" in compare
    assert "Chief asks before it spends" in compare and "Yes, do that" in compare
    assert "week, every Monday" in compare
    assert "What does Chief do while I" in faq and "one tap" in faq
    # the filter counts stay honest
    everything = int(re.search(r"Everything<span>(\d+)</span>", faq).group(1))
    assert everything == faq.count('<details class="faq-item"')
    how = int(re.search(r"How it works<span>(\d+)</span>", faq).group(1))
    assert how == faq.count('data-g="how"')
