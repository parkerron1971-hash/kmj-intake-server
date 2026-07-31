"""
test_chief_campaign_actions.py — the campaign verbs (S10 gap-close), and
the property that matters most: the chat trust gate CATCHES launch_campaign.

campaigns had a full product surface and zero Chief verbs. The new verbs
reuse the router's extracted cores, so these tests check three seams:

  1. The GATE — launch_campaign is registry bulk class C. Under manual
     (and smart) autopilot the gate must hold it BEFORE the handler runs;
     under full nurture autopilot it runs. Asserted on observable
     behavior: whether the (stubbed) handler executed, and what result
     dict came back.
  2. The HANDLERS — result + label on every path (the toLowerCase
     contract), business-scoped campaign resolution, honest copy (a plan
     says DRAFT/nothing sends; a launch names the audience size).
  3. The CORES — launch refuses non-launchable states and empty
     audiences with the same HTTPExceptions the endpoint always raised.

Nothing here asserts against comments or prose in the source.
"""
import asyncio

import pytest
from fastapi import HTTPException

import action_registry
import chief_campaign_actions as cca
import chief_of_staff as cos


def _biz(autopilot=None):
    settings = {}
    if autopilot is not None:
        settings["autopilot"] = autopilot
    return {"id": "biz-1", "owner_id": "user-1", "name": "Test Biz",
            "type": "coach", "settings": settings}


# ─────────────────────────────────────────────────────────────────────
# Registry classification (the contract everything else consults)
# ─────────────────────────────────────────────────────────────────────

def test_campaign_verbs_are_classified_as_specified():
    assert action_registry.effect("campaign_status") == action_registry.READ
    assert not action_registry.is_sensitive("campaign_status")
    assert action_registry.reversibility("plan_campaign") == "A"
    assert action_registry.reversibility("launch_campaign") == "C"
    assert action_registry.is_bulk("launch_campaign")
    assert action_registry.reversibility("pause_campaign") == "C"
    assert not action_registry.is_bulk("pause_campaign")


def test_launch_campaign_is_never_autonomy_eligible():
    assert not action_registry.is_autonomy_eligible("launch_campaign")
    assert not action_registry.is_autonomy_eligible("launch_campaign",
                                                    granted_scope=True)


# ─────────────────────────────────────────────────────────────────────
# THE GATE — launch_campaign under the bulk class-C rules
# ─────────────────────────────────────────────────────────────────────

def test_launch_campaign_is_held_under_manual_autopilot(monkeypatch):
    """The wave-1 gate must catch launch_campaign: the handler NEVER runs
    when nurture autopilot is manual, and the held result points at the
    Campaigns review surface with both result and label present."""
    async def must_not_run(client, biz, action):
        raise AssertionError("launch_campaign must not execute under manual autopilot")
    monkeypatch.setitem(cos.ACTION_HANDLERS, "launch_campaign", must_not_run)

    out = asyncio.run(cos._execute_actions(None, _biz({"overall": "manual"}), [{
        "type": "launch_campaign", "name": "Spring rebook",
    }]))

    assert len(out) == 1
    r = out[0]
    assert isinstance(r.get("result"), str) and r.get("label")
    assert cos._action_failed(r)               # held = did NOT happen
    assert r.get("failed") is True
    assert "campaigns" in (r.get("result") or "").lower()
    assert (r.get("nav") or {}).get("tab") == "grow"
    assert (r.get("nav") or {}).get("sub") == "campaigns"


def test_launch_campaign_is_held_under_smart_autopilot(monkeypatch):
    """smart is not full — a bulk send still waits for a human."""
    async def must_not_run(client, biz, action):
        raise AssertionError("launch_campaign must not execute under smart autopilot")
    monkeypatch.setitem(cos.ACTION_HANDLERS, "launch_campaign", must_not_run)

    out = asyncio.run(cos._execute_actions(
        None, _biz({"per_team": {"nurture": "smart"}}), [{
            "type": "launch_campaign", "campaign_id": "camp-1",
        }]))
    assert cos._action_failed(out[0])
    assert out[0].get("label")


def test_launch_campaign_executes_under_full_nurture_autopilot(monkeypatch):
    ran = {}

    async def stub(client, biz, action):
        ran["called"] = True
        return {"type": "launch_campaign", "result": "launched 'X' to 3 people",
                "label": "Launched 'X' to 3 people", "nav": None}
    monkeypatch.setitem(cos.ACTION_HANDLERS, "launch_campaign", stub)

    out = asyncio.run(cos._execute_actions(
        None, _biz({"per_team": {"nurture": "full"}}), [{
            "type": "launch_campaign", "name": "X",
        }]))
    assert ran.get("called") is True
    assert out[0]["result"] == "launched 'X' to 3 people"


def test_pause_campaign_runs_immediately_even_under_manual(monkeypatch):
    """Single-target class C: the ask is the approval. Pausing is the
    protective direction and must not wait on an approval queue."""
    ran = {}

    async def stub(client, biz, action):
        ran["called"] = True
        return {"type": "pause_campaign", "result": "paused 'X'",
                "label": "Paused 'X'", "nav": None}
    monkeypatch.setitem(cos.ACTION_HANDLERS, "pause_campaign", stub)

    out = asyncio.run(cos._execute_actions(None, _biz({"overall": "manual"}), [{
        "type": "pause_campaign", "name": "X",
    }]))
    assert ran.get("called") is True
    assert not cos._action_failed(out[0])


# ─────────────────────────────────────────────────────────────────────
# Handlers — result + label everywhere, business-scoped resolution
# ─────────────────────────────────────────────────────────────────────

_CAMPS = [
    {"id": "camp-1", "business_id": "biz-1", "name": "Spring rebook",
     "status": "draft", "sent_total": 0,
     "touches": [{"channel": "email", "offset_days": 0, "body": "hi"}]},
    {"id": "camp-2", "business_id": "biz-1", "name": "Spring cleanup",
     "status": "running", "sent_total": 7,
     "touches": [{"channel": "email", "offset_days": 0, "body": "hi",
                  "completed_at": "2026-07-30T00:00:00Z"},
                 {"channel": "sms", "offset_days": 3, "body": "yo"}]},
]


def _patch_list(monkeypatch, rows=None):
    monkeypatch.setattr(cca.cr, "list_campaigns_core",
                        lambda biz_id, limit=50: [dict(r) for r in (rows if rows is not None else _CAMPS)])


def test_plan_campaign_result_is_honest_about_being_a_draft(monkeypatch):
    async def fake_core(biz, goal, audience):
        return {"campaign": {"id": "camp-9", "name": "Win-back",
                             "touches": [{"channel": "email"}, {"channel": "email"}]},
                "audience_preview": {"count": 12, "emailable": 10, "textable": 4,
                                     "sample": ["Ann"]}}
    monkeypatch.setattr(cca.cr, "plan_campaign_core", fake_core)

    r = asyncio.run(cca.handle_plan_campaign(None, _biz(), {
        "goal": "win back quiet clients", "audience": "silent", "days_silent": 60}))
    assert isinstance(r.get("result"), str) and r.get("label")
    assert not cos._action_failed(r)
    assert "DRAFT" in r["result"]
    assert "nothing sends" in r["result"].lower()
    assert "12" in r["result"]
    assert "not sent" in r["label"].lower()
    assert r.get("campaign_id") == "camp-9"


def test_plan_campaign_surfaces_billing_402_as_failure(monkeypatch):
    async def fake_core(biz, goal, audience):
        raise HTTPException(402, {"error": "out_of_units",
                                  "message": "You're out of AI actions."})
    monkeypatch.setattr(cca.cr, "plan_campaign_core", fake_core)

    r = asyncio.run(cca.handle_plan_campaign(None, _biz(), {"goal": "x"}))
    assert cos._action_failed(r)
    assert r.get("label")
    assert "out of AI actions" in r["result"]


def test_launch_handler_reports_audience_size(monkeypatch):
    _patch_list(monkeypatch)

    def fake_launch(biz, camp, start_at=None):
        assert camp["id"] == "camp-1"
        return {"campaign": {"id": "camp-1", "name": "Spring rebook",
                             "status": "running"},
                "audience_preview": {"count": 43, "emailable": 38,
                                     "textable": 20, "sample": []}}
    monkeypatch.setattr(cca.cr, "launch_campaign_core", fake_launch)

    r = asyncio.run(cca.handle_launch_campaign(None, _biz(), {"name": "rebook"}))
    assert not cos._action_failed(r)
    assert r["label"] == "Launched 'Spring rebook' to 43 people"
    assert "43 people" in r["result"]


def test_launch_handler_translates_core_409(monkeypatch):
    _patch_list(monkeypatch)

    def fake_launch(biz, camp, start_at=None):
        raise HTTPException(409, "This audience is empty right now — nothing to send.")
    monkeypatch.setattr(cca.cr, "launch_campaign_core", fake_launch)

    r = asyncio.run(cca.handle_launch_campaign(None, _biz(), {"campaign_id": "camp-1"}))
    assert cos._action_failed(r)
    assert r.get("label")
    assert "audience is empty" in r["result"]


def test_campaign_resolution_is_business_scoped(monkeypatch):
    """An id that exists on ANOTHER business must not resolve — the
    lookup goes through the business-scoped list, never a bare load."""
    _patch_list(monkeypatch)   # biz-1's campaigns only
    r = asyncio.run(cca.handle_launch_campaign(None, _biz(), {
        "campaign_id": "camp-of-someone-else"}))
    assert cos._action_failed(r)
    assert "not found" in r["result"]
    assert r.get("label")


def test_ambiguous_name_asks_which(monkeypatch):
    _patch_list(monkeypatch)
    r = asyncio.run(cca.handle_pause_campaign(None, _biz(), {"name": "Spring"}))
    assert cos._action_failed(r)
    assert "Spring rebook" in r["result"] and "Spring cleanup" in r["result"]


def test_pause_handler_success(monkeypatch):
    _patch_list(monkeypatch)
    monkeypatch.setattr(cca.cr, "pause_campaign_core",
                        lambda camp: {"id": "camp-2", "name": "Spring cleanup",
                                      "status": "paused"})
    r = asyncio.run(cca.handle_pause_campaign(None, _biz(), {"name": "cleanup"}))
    assert not cos._action_failed(r)
    assert r["label"] == "Paused 'Spring cleanup'"
    assert "7 messages" in r["result"]


def test_campaign_status_lists_all(monkeypatch):
    _patch_list(monkeypatch)
    r = asyncio.run(cca.handle_campaign_status(None, _biz(), {}))
    assert not cos._action_failed(r)
    assert "2 campaigns" in r["result"]
    assert "Spring rebook" in r["result"]
    assert "1 running" in r["label"]


def test_campaign_status_empty_state_is_not_a_dead_end(monkeypatch):
    _patch_list(monkeypatch, rows=[])
    r = asyncio.run(cca.handle_campaign_status(None, _biz(), {}))
    assert not cos._action_failed(r)
    assert r.get("label")
    assert "draft" in r["result"].lower()   # tells them what to say next


def test_campaign_status_detail_reads_the_ledger(monkeypatch):
    _patch_list(monkeypatch)
    monkeypatch.setattr(cca.cr, "_campaign_results", lambda camp: {
        "emails_sent": 5, "texts_sent": 2, "people_reached": 5,
        "replies_since_launch": 1, "bookings_since_launch": 0,
        "sends_by_touch": {0: 5}})
    r = asyncio.run(cca.handle_campaign_status(None, _biz(), {"name": "cleanup"}))
    assert not cos._action_failed(r)
    assert "5 emails" in r["result"] and "2 texts" in r["result"]
    assert "not claimed attribution" in r["result"]


# ─────────────────────────────────────────────────────────────────────
# Cores — the launch check-list still refuses what it always refused
# ─────────────────────────────────────────────────────────────────────

def _no_billing(monkeypatch):
    import billing_limits
    monkeypatch.setattr(billing_limits, "require_live_access", lambda b: None)


def test_launch_core_refuses_completed_campaign(monkeypatch):
    import campaigns_router as cr
    _no_billing(monkeypatch)
    with pytest.raises(HTTPException) as ei:
        cr.launch_campaign_core(_biz(), {"id": "c", "business_id": "biz-1",
                                         "status": "completed", "touches": []})
    assert ei.value.status_code == 409


def test_launch_core_refuses_empty_audience(monkeypatch):
    import campaigns_router as cr
    _no_billing(monkeypatch)
    monkeypatch.setattr(cr, "_resolve_audience", lambda biz_id, aud: [])
    with pytest.raises(HTTPException) as ei:
        cr.launch_campaign_core(_biz(), {
            "id": "c", "business_id": "biz-1", "status": "draft",
            "touches": [{"channel": "email", "offset_days": 0, "body": "hi"}]})
    assert ei.value.status_code == 409
    assert "empty" in str(ei.value.detail)


def test_pause_core_refuses_non_running(monkeypatch):
    import campaigns_router as cr
    with pytest.raises(HTTPException) as ei:
        cr.pause_campaign_core({"id": "c", "status": "draft"})
    assert ei.value.status_code == 409
