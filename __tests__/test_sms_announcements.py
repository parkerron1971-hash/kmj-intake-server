"""Announcements to one group, and sent later (Kevin, 2026-10-30).

POST /sms/broadcast takes a group (only that group's members, still only
those who said yes) and a send time. A later one is a
chief_scheduled_actions row of type sms_announcement that only this
endpoint writes; Chief can't schedule one, and at send time the scheduler
checks again that its author can still send announcements.
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import chief_scheduler
import sms_routing

BIZ = "7c0de000-0000-4000-8000-000000000001"
GROUP = "22222222-2222-4222-8222-222222222222"
USER = SimpleNamespace(id="admin-1")


def _gate(monkeypatch, seen=None):
    import billing_limits
    import business_access
    sink = seen if seen is not None else []
    monkeypatch.setattr(business_access, "assert_access", lambda b, u, r: sink.append(r))
    monkeypatch.setattr(billing_limits, "require_card", lambda b, k: None)


# ─── who an announcement reaches ─────────────────────────────────────

def test_one_group_is_its_members_with_a_number(monkeypatch):
    paths = []

    async def sb_get(client, path):
        paths.append(path)
        if path.startswith("/groups?"):
            return [{"id": GROUP}]
        if path.startswith("/group_members?"):
            return [{"contact_id": "c-1"}, {"contact_id": "c-2"}]
        if path.startswith("/contacts?"):
            return [{"id": "c-1", "phone": "+15550000001"}, {"id": "c-2", "phone": "+15550000002"}]
        return []

    async def said_yes(client, business_id, phones):
        return {"+15550000001"}

    import sms_alerts
    monkeypatch.setattr(sms_routing, "_sb_get", sb_get)
    monkeypatch.setattr(sms_alerts, "said_yes_to_texts", said_yes)
    contacts, yes = asyncio.run(sms_routing._bulletin_list(None, BIZ, GROUP))
    assert [c["id"] for c in contacts] == ["c-1", "c-2"] and yes == {"+15550000001"}
    assert f"/groups?id=eq.{GROUP}&business_id=eq.{BIZ}&active=eq.true" in paths[0]
    assert any(p.startswith(f"/contacts?business_id=eq.{BIZ}&id=in.(c-1,c-2)") for p in paths)


def test_a_group_that_isnt_theirs_reaches_no_one(monkeypatch):
    async def sb_get(client, path):
        return [] if path.startswith("/groups?") else [{"id": "x"}]

    monkeypatch.setattr(sms_routing, "_sb_get", sb_get)
    assert asyncio.run(sms_routing._bulletin_list(None, BIZ, GROUP)) == ([], None)
    assert asyncio.run(sms_routing._bulletin_list(None, BIZ, "not-a-uuid")) == ([], None)


# ─── sent later ──────────────────────────────────────────────────────

def _schedule(monkeypatch, send_at, group_id=None):
    seen, posted = [], []
    _gate(monkeypatch, seen)

    async def sb_post(client, path, body):
        posted.append((path, body))
        return [{"id": "sched-1", "run_at": body["run_at"]}]

    async def group_ids(client, b, g):
        return {"c-1"}

    async def announce(*a, **k):
        raise AssertionError("a later announcement must not send now")

    monkeypatch.setattr(sms_routing, "_sb_post", sb_post)
    monkeypatch.setattr(sms_routing, "_group_ids", group_ids)
    monkeypatch.setattr(sms_routing, "announce", announce)
    body = sms_routing.BroadcastBody(business_id=BIZ, message="Fall Fest is Saturday!", group_id=group_id, send_at=send_at)
    return asyncio.run(sms_routing.broadcast(body, user=USER)), posted, seen


def test_a_later_announcement_is_saved_for_the_scheduler(monkeypatch):
    when = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
    out, posted, seen = _schedule(monkeypatch, when.isoformat(), GROUP)
    assert seen == ["admin"] and out["scheduled"] is True
    [(path, row)] = posted
    assert path == "/chief_scheduled_actions"
    assert row["action"] == {"type": "sms_announcement", "message": "Fall Fest is Saturday!",
                             "group_id": GROUP, "scheduled_by": "admin-1"}
    assert datetime.fromisoformat(row["run_at"]) == when and row["business_id"] == BIZ


# Stable ids: pytest-xdist workers must collect the same names, so the
# times are made inside the test, not in the parameters.
@pytest.mark.parametrize("case", ["an_hour_ago", "ninety_days_out", "no_time_zone", "not_a_time"])
def test_a_time_that_cant_be_kept_is_refused(monkeypatch, case):
    now = datetime.now(timezone.utc)
    send_at = {
        "an_hour_ago": (now - timedelta(hours=1)).isoformat(),
        "ninety_days_out": (now + timedelta(days=90)).isoformat(),
        "no_time_zone": "2026-11-01T10:00:00",
        "not_a_time": "Saturday morning",
    }[case]
    out, posted, _ = _schedule(monkeypatch, send_at)
    assert out.status_code == 400 and not posted


def test_chief_cant_schedule_an_announcement():
    import chief_strategy_actions
    out = asyncio.run(chief_strategy_actions.handle_schedule_action(
        None, {"id": BIZ}, {"action": {"type": "sms_announcement", "message": "hi"}, "in_minutes": 5}))
    assert "unknown action" in str(out.get("result") or out)


# ─── when it's due ───────────────────────────────────────────────────

def _run(monkeypatch, role, card=True):
    import billing_limits
    import business_access
    sent = []

    async def announce(business_id, message, group_id=None):
        sent.append((business_id, message, group_id))
        return {"ok": True, "sent": 12, "not_yes": 3, "failed": 0, "skipped": 0}

    def require_card(b, k):
        if not card:
            raise Exception("no card")

    monkeypatch.setattr(business_access, "_resolve_role", lambda b, u: role)
    monkeypatch.setattr(billing_limits, "require_card", require_card)
    monkeypatch.setattr(sms_routing, "announce", announce)
    action = {"type": "sms_announcement", "message": "Fall Fest!", "group_id": GROUP, "scheduled_by": "admin-1"}
    ok, detail = asyncio.run(sms_routing.run_scheduled_announcement({"id": BIZ}, action))
    return ok, detail, sent


def test_it_goes_out_when_its_author_can_still_send_announcements(monkeypatch):
    ok, detail, sent = _run(monkeypatch, "admin")
    assert ok and sent == [(BIZ, "Fall Fest!", GROUP)]
    assert detail == "Announcement sent: 12 sent · 3 haven't said yes"


@pytest.mark.parametrize("role", [None, "member", "manager"])
def test_it_stays_unsent_when_they_no_longer_can(monkeypatch, role):
    ok, _, sent = _run(monkeypatch, role)
    assert not ok and not sent


def test_it_stays_unsent_without_a_card(monkeypatch):
    ok, _, sent = _run(monkeypatch, "owner", card=False)
    assert not ok and not sent


def test_the_scheduler_hands_it_to_its_runner_not_the_verb_registry(monkeypatch):
    import policy_engine
    import sb_clients
    patched, ran = [], []

    async def runner(biz, action):
        ran.append(action["type"])
        return True, "Announcement sent: 3 sent"

    async def quiet(*a, **k):
        return None

    def evaluate(*a, **k):
        raise AssertionError("an announcement isn't a Chief verb")

    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p, **k: [{"id": BIZ, "owner_id": "o"}])
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: patched.append(b))
    monkeypatch.setattr(sms_routing, "run_scheduled_announcement", runner)
    monkeypatch.setattr(policy_engine, "evaluate", evaluate)
    monkeypatch.setattr(chief_scheduler, "_notify_outcome", quiet)
    import audit_log
    monkeypatch.setattr(audit_log, "record", lambda *a, **k: True)
    row = {"id": "sched-1", "business_id": BIZ, "label": "Announcement: Fall Fest",
           "action": {"type": "sms_announcement", "message": "Fall Fest!", "scheduled_by": "admin-1"},
           "run_at": datetime.now(timezone.utc).isoformat()}
    asyncio.run(chief_scheduler._execute_row(row))
    assert ran == ["sms_announcement"]
    assert patched[-1]["status"] == "done"


# ─── what's waiting, and taking one back ─────────────────────────────

def test_cancel_touches_only_this_business_queued_announcement(monkeypatch):
    _gate(monkeypatch)
    reads, writes = [], []

    async def sb_get(client, path):
        reads.append(path)
        return [{"id": "sched-1"}]

    async def sb_patch(client, path, body):
        writes.append((path, body))

    monkeypatch.setattr(sms_routing, "_sb_get", sb_get)
    monkeypatch.setattr(sms_routing, "_sb_patch", sb_patch)
    sid = "33333333-3333-4333-8333-333333333333"
    out = asyncio.run(sms_routing.cancel_announcement(sid, BIZ, user=USER))
    assert out == {"ok": True}
    for part in (f"id=eq.{sid}", f"business_id=eq.{BIZ}", "status=eq.queued", "action->>type=eq.sms_announcement"):
        assert part in reads[0]
    [(path, body)] = writes
    assert body == {"status": "cancelled"} and f"business_id=eq.{BIZ}" in path and "status=eq.queued" in path


@pytest.mark.parametrize("fn", ["announcement_groups", "scheduled_announcements", "cancel_announcement", "broadcast_reach"])
def test_every_new_handler_needs_someone_who_can_send_announcements(fn):
    src = inspect.getsource(getattr(sms_routing, fn))
    assert '"admin")' in src
    gate = src.index("assert_access")
    assert gate < src.index("httpx.AsyncClient()")
