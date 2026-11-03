"""Announcements to one group, and sent later (Kevin, 2026-10-30).

POST /sms/broadcast takes a group (only that group's members, still only
those who said yes) and a send time. A later one is a
chief_scheduled_actions row of type sms_announcement that only this
endpoint writes; Chief can't schedule one, and at send time the scheduler
checks again that its author can still send announcements.

Who sends one (church_duties, docs/CHURCH_DUTIES.md step 2): the owner or
an admin; in a church also a Manager that does the weekly text (the Office
& Leadership lane by default; refused, naming whose job it is, once it
moves away; by its areas when no lane names it; a 503 when it can't be
read). Any other business keeps its admin gate exactly, and the scheduler
checks the duty again at send time.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import chief_scheduler  # noqa: E402
import sms_routing  # noqa: E402

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


def _numbers(n, start=0):
    return [{"id": f"c-{i:05d}", "name": "", "phone": f"+1555{i:07d}"} for i in range(start, start + n)]


def test_everyone_is_every_number_not_the_first_500(monkeypatch):
    # A church with 1,300 numbers: it read `limit=500`, no order, and texted those.
    book = _numbers(1300)
    paths = []

    async def sb_get(client, path):
        paths.append(path)
        after = path.split("&id=gt.")[1] if "&id=gt." in path else ""
        rest = [c for c in book if c["id"] > after]
        return rest[:1000]

    async def said_yes(client, business_id, phones):
        return set(phones)

    import sms_alerts
    monkeypatch.setattr(sms_routing, "_sb_get", sb_get)
    monkeypatch.setattr(sms_alerts, "said_yes_to_texts", said_yes)
    contacts, yes = asyncio.run(sms_routing._bulletin_list(None, BIZ))
    assert len(contacts) == 1300 and len(yes) == 1300
    assert len(paths) == 2 and all("order=id.asc&limit=1000" in p for p in paths)
    assert "&id=gt.c-00999" in paths[1] and "limit=500" not in "".join(paths)


def test_a_page_that_fails_sends_to_no_one(monkeypatch):
    # Never "part of the list": the second page failing is the same as the first.
    book = _numbers(1000)

    async def sb_get(client, path):
        return None if "&id=gt." in path else book

    monkeypatch.setattr(sms_routing, "_sb_get", sb_get)
    assert asyncio.run(sms_routing._bulletin_list(None, BIZ)) == ([], None)


def test_a_group_past_1000_members_is_every_member(monkeypatch):
    members = [{"contact_id": f"m-{i:05d}"} for i in range(1200)]

    async def sb_get(client, path):
        if path.startswith("/groups?"):
            return [{"id": GROUP}]
        after = path.split("&contact_id=gt.")[1] if "&contact_id=gt." in path else ""
        return [m for m in members if m["contact_id"] > after][:1000]

    monkeypatch.setattr(sms_routing, "_sb_get", sb_get)
    assert len(asyncio.run(sms_routing._group_ids(None, BIZ, GROUP))) == 1200


def test_group_counts_that_cant_be_read_are_a_503_never_zero(monkeypatch):
    _gate(monkeypatch)

    async def sb_get(client, path):
        if path.startswith("/groups?"):
            return [{"id": GROUP, "name": "Youth"}]
        return None

    monkeypatch.setattr(sms_routing, "_sb_get", sb_get)
    out = asyncio.run(sms_routing.announcement_groups(BIZ, user=USER))
    assert out.status_code == 503


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


@pytest.mark.parametrize("fn", ["announcement_groups", "scheduled_announcements", "cancel_announcement",
                                "broadcast_reach", "broadcast"])
def test_every_new_handler_needs_someone_who_can_send_announcements(fn):
    src = inspect.getsource(getattr(sms_routing, fn))
    gate = src.index("_may_announce(")
    assert gate < src.index("httpx.AsyncClient()") and "assert_access" not in src
    # The gate asks for an admin first: any business but a church stops there.
    may = inspect.getsource(sms_routing._may_announce)
    assert may.index('assert_access(biz, user, "admin")') < may.index("require(biz, user, WEEKLY_TEXT)")


# ─── who does the weekly text (church_duties, docs/CHURCH_DUTIES.md step 2) ─

CHURCH = "7c0de000-0000-4000-8000-0000000000c1"
SHOP = "7c0de000-0000-4000-8000-0000000000c2"
OWNER_ID, ADMIN_ID, NAIYA_ID, TIARA_ID, MEMBER_ID, STRANGER_ID = (
    f"0f0f0f0f-0000-4000-8000-00000000000{i}" for i in range(1, 7))


def _who(uid):
    from auth_supabase import AuthedUser
    return AuthedUser(id=uid, email=None, role="authenticated")


@pytest.fixture
def office(monkeypatch):
    """A church (Love City's office: the owner, an admin, Naiya in Office &
    Leadership, Tiara in People & Care, a Member login) and a barbershop with
    the same logins, in the role tests' in-memory PostgREST."""
    import church_duties
    import sb_clients
    from test_church_roles import FakeDB

    def seats(biz):
        return [{"business_id": biz, "user_id": u, "role": r, "status": "active", "lane": ln,
                 "invited_email": f"{n}@lovecity.org"}
                for u, r, ln, n in ((ADMIN_ID, "admin", None, "admin"), (NAIYA_ID, "manager", "office_leadership", "naiya"),
                                    (TIARA_ID, "manager", "people_care", "tiara"), (MEMBER_ID, "member", None, "web"))]
    fake = FakeDB(businesses=[{"id": CHURCH, "name": "Love City Church", "type": "ministry", "owner_id": OWNER_ID,
                               "settings": {}},
                              {"id": SHOP, "name": "Fade Shop", "type": "barber", "owner_id": OWNER_ID, "settings": {}}],
                  business_users=seats(CHURCH) + seats(SHOP), church_duty_holders=[])
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.delenv("CHURCH_AREAS", raising=False)
    church_duties._CACHE.clear()
    return fake


def _may(biz, uid):
    from fastapi import HTTPException
    try:
        return sms_routing._may_announce(biz, _who(uid))
    except HTTPException as e:
        return e.status_code, e.detail


def test_in_a_church_whoever_does_the_weekly_text_sends_announcements(office):
    import church_duties
    assert [_may(CHURCH, u) for u in (OWNER_ID, ADMIN_ID, NAIYA_ID)] == ["owner", "admin", "manager"]
    assert _may(CHURCH, TIARA_ID) == (403, church_duties.refusal(CHURCH, "weekly_text"))
    assert "Office & Leadership" in _may(CHURCH, TIARA_ID)[1]
    # Below a Manager, and a stranger: the same 404 as before.
    assert _may(CHURCH, MEMBER_ID) == _may(CHURCH, STRANGER_ID) == (404, "business not found")


def test_any_other_business_keeps_its_admin_gate(office):
    assert [_may(SHOP, u) for u in (OWNER_ID, ADMIN_ID)] == ["owner", "admin"]
    for uid in (NAIYA_ID, TIARA_ID, MEMBER_ID, STRANGER_ID):
        assert _may(SHOP, uid) == (404, "business not found"), uid
    assert _may("7c0de000-0000-4000-8000-0000000000ff", OWNER_ID) == (404, "business not found")


def test_a_manager_the_weekly_text_moved_away_from_is_refused(office):
    import church_duties
    office.t["church_duty_holders"] = [{"business_id": CHURCH, "duty": "weekly_text", "user_id": TIARA_ID}]
    church_duties._CACHE.clear()
    status, detail = _may(CHURCH, NAIYA_ID)
    assert status == 403 and detail == church_duties.refusal(CHURCH, "weekly_text") and "tiara@lovecity.org's job" in detail
    assert _may(CHURCH, TIARA_ID) == "manager" and _may(CHURCH, ADMIN_ID) == "admin"


def test_a_manager_no_lane_names_keeps_the_weekly_text_its_areas_give_it(office, monkeypatch):
    import church_areas
    import church_duties
    office.t["business_users"][1]["lane"] = None             # Naiya at the church, no lane
    monkeypatch.setenv("CHURCH_AREAS", "on")
    areas = {"now": ["office"]}
    monkeypatch.setattr(church_areas, "my_areas", lambda biz, uid, role: {"areas": areas["now"], "by": "picked"})
    church_duties._CACHE.clear()
    assert _may(CHURCH, NAIYA_ID) == "manager"
    areas["now"] = ["worship_media"]
    church_duties._CACHE.clear()
    assert _may(CHURCH, NAIYA_ID)[0] == 403


def test_a_weekly_text_duty_that_cant_be_read_is_a_503_never_a_yes(office, monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p, **k: None if p.startswith("/church_duty_holders") else office.get(p, **k))
    assert _may(CHURCH, NAIYA_ID)[0] == 503
    assert _may(CHURCH, ADMIN_ID) == "admin"
    # And whether it's a church at all, the same.
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p, **k: None if "select=id,type" in p else office.get(p, **k))
    assert _may(SHOP, NAIYA_ID)[0] == 503


def test_a_church_manager_schedules_an_announcement_by_the_duty(office, monkeypatch):
    import billing_limits
    monkeypatch.setattr(billing_limits, "require_card", lambda b, k: None)
    posted = []

    async def sb_post(client, path, body):
        posted.append(body)
        return [{"id": "sched-1", "run_at": body["run_at"]}]
    monkeypatch.setattr(sms_routing, "_sb_post", sb_post)
    when = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0).isoformat()
    body = sms_routing.BroadcastBody(business_id=CHURCH, message="Fall Fest is Saturday!", send_at=when)
    out = asyncio.run(sms_routing.broadcast(body, user=_who(NAIYA_ID)))
    assert out["scheduled"] is True and posted[0]["action"]["scheduled_by"] == NAIYA_ID
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        asyncio.run(sms_routing.broadcast(body, user=_who(TIARA_ID)))
    assert e.value.status_code == 403 and len(posted) == 1


def _due(monkeypatch, biz, who):
    sent = []

    async def announce(business_id, message, group_id=None):
        sent.append(business_id)
        return {"ok": True, "sent": 4, "not_yes": 0, "failed": 0, "skipped": 0}
    import billing_limits
    monkeypatch.setattr(billing_limits, "require_card", lambda b, k: None)
    monkeypatch.setattr(sms_routing, "announce", announce)
    action = {"type": "sms_announcement", "message": "Fall Fest!", "group_id": None, "scheduled_by": who}
    ok, detail = asyncio.run(sms_routing.run_scheduled_announcement(biz, action))
    return ok, detail, sent


def test_a_scheduled_announcement_goes_while_its_author_still_does_the_weekly_text(office, monkeypatch):
    import church_duties
    church = next(b for b in office.t["businesses"] if b["id"] == CHURCH)
    shop = next(b for b in office.t["businesses"] if b["id"] == SHOP)
    ok, _, sent = _due(monkeypatch, church, NAIYA_ID)
    assert ok and sent == [CHURCH]
    # A barbershop's Manager never could; a church's Manager whose lane doesn't do it can't.
    for biz, who in ((shop, NAIYA_ID), (church, TIARA_ID)):
        ok, detail, sent = _due(monkeypatch, biz, who)
        assert not ok and not sent and "can't send announcements now" in detail
    # The weekly text moved to someone else between scheduling and sending.
    office.t["church_duty_holders"] = [{"business_id": CHURCH, "duty": "weekly_text", "user_id": TIARA_ID}]
    church_duties._CACHE.clear()
    ok, _, sent = _due(monkeypatch, church, NAIYA_ID)
    assert not ok and not sent


def test_a_scheduled_announcement_whose_duty_cant_be_read_stays_unsent(office, monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p, **k: None if p.startswith("/church_duty_holders") else office.get(p, **k))
    church = next(b for b in office.t["businesses"] if b["id"] == CHURCH)
    ok, detail, sent = _due(monkeypatch, church, NAIYA_ID)
    assert not ok and not sent and detail.startswith("Couldn't check who scheduled")
