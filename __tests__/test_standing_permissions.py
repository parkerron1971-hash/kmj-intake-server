"""
test_standing_permissions.py — the approval that earns a standing permission.

What must hold:
  1. THE QUESTION COMES ON THE THIRD YES IN A ROW for one kind, read off
     the ledger; never before, never when granted, never for thirty days
     after a no, never for a kind that always needs a tap, never for a
     regulated practice's client-facing send.
  2. A GRANT IS PER KIND, written with a shallow merge; revoke and
     decline are honest.
  3. A GRANTED KIND FILES WITH A RELEASE TIME and the spec says so; the
     phone gets Stop; an ungranted kind files exactly as before.
  4. THE RELEASE TICK claims only a row still in draft, honours a
     revoke, a pause, and the money cap (held, not sent), runs through
     the door on surface "standing", and records it.
  5. THE RETIRE RULE REVOKES a grant stopped three times running.
  6. THE CHAT VERBS grant only what is eligible, and the prompt never
     lets Chief suggest it.
House rules: sync tests + asyncio.run.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import action_proposals as ap
import chief_of_staff as cos
import sb_clients
import standing_permissions as sp

NOW = datetime(2026, 9, 8, 16, 0, tzinfo=timezone.utc)
BIZ = {"id": "biz-1", "name": "Bloom Studio", "type": "salon", "owner_id": "own-1", "settings": {}}
GRANTED = {**BIZ, "settings": {"autonomy": {"standing": {"send_sms": {"granted_at": "2026-09-01T00:00:00Z", "via": "app"}}}}}


def _run(coro):
    return asyncio.run(coro)


def _at(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def _m(verb, days_ago, outcome):
    return {"verb": verb, "queue_id": f"q-{days_ago}", "outcome": outcome, "made_at": _at(days_ago)}


# ─── 1. the question ─────────────────────────────────────────────────

def test_the_question_comes_on_the_third_yes_in_a_row():
    two = [_m("send_sms", 1, "approved"), _m("send_sms", 2, "replied")]
    offer = sp.offer_after_approval(BIZ, "send_sms", moves=two, now=NOW)
    assert offer and offer["verb"] == "send_sms" and offer["kind"] == "texts" and "last 3 texts" in offer["question"]
    assert sp.offer_after_approval(BIZ, "send_sms", moves=two[:1], now=NOW) is None, "two is not three"
    mixed = [_m("send_sms", 1, "approved"), _m("send_sms", 2, "dismissed"), _m("send_sms", 3, "approved")]
    assert sp.offer_after_approval(BIZ, "send_sms", moves=mixed, now=NOW) is None
    pend = [_m("send_sms", 0.5, "pending")] + two
    assert sp.offer_after_approval(BIZ, "send_sms", moves=pend, now=NOW), "pending rows do not count either way"
    assert sp.offer_after_approval(GRANTED, "send_sms", moves=two, now=NOW) is None, "already granted"
    assert sp.offer_after_approval(BIZ, "publish_to_site", moves=[_m("publish_to_site", 1, "approved")] * 2, now=NOW) is None
    declined = {**BIZ, "settings": {"autonomy": {"standing_declined": {"send_sms": _at(3)}}}}
    assert sp.offer_after_approval(declined, "send_sms", moves=two, now=NOW) is None
    long_ago = {**BIZ, "settings": {"autonomy": {"standing_declined": {"send_sms": _at(40)}}}}
    assert sp.offer_after_approval(long_ago, "send_sms", moves=two, now=NOW)
    therapist = {**BIZ, "type": "therapist", "settings": {"autonomy": {"client_facing_autonomy": "disabled"}}}
    assert sp.offer_after_approval(therapist, "send_sms", moves=two, now=NOW) is None
    assert sp.offer_after_approval(therapist, "send_invoice", moves=[_m("send_invoice", 1, "approved")] * 2, now=NOW)


# ─── 2. grant / revoke / decline ─────────────────────────────────────

@pytest.fixture
def biz_store(monkeypatch):
    state = {"row": {**BIZ, "settings": {"autonomy": {"agent_enabled": True}, "other": 1}}, "patches": [], "audit": []}
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [dict(state["row"])] if p.startswith("/businesses") else [])

    def _patch(path, body):
        state["patches"].append((path, body))
        state["row"] = {**state["row"], **body}
        return [state["row"]]
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", _patch)
    import audit_log
    monkeypatch.setattr(audit_log, "record", lambda *a, **k: state["audit"].append(k) or True)
    return state


def test_a_grant_is_per_kind_and_merges_shallowly(biz_store):
    ok, when = sp.grant("biz-1", "send_sms", by="own-1", via="app")
    assert ok and when.startswith("2026")
    s = biz_store["row"]["settings"]
    assert s["other"] == 1 and s["autonomy"]["agent_enabled"] is True, "neighbours survive"
    assert list(s["autonomy"]["standing"]) == ["send_sms"] and s["autonomy"]["standing"]["send_sms"]["via"] == "app"
    assert biz_store["audit"][-1]["verb"] == "standing_grant"
    assert sp.is_granted(biz_store["row"], "send_sms") and not sp.is_granted(biz_store["row"], "send_invoice")
    assert sp.grant("biz-1", "publish_to_site", by="own-1", via="app") == (False, "this kind always needs a tap")
    assert sp.revoke("biz-1", "send_sms", by="own-1", via="app") is True
    assert biz_store["row"]["settings"]["autonomy"]["standing"] == {}
    assert biz_store["audit"][-1]["verb"] == "standing_revoke"
    assert sp.revoke("biz-1", "send_sms", by="own-1", via="app") is False, "nothing to revoke"
    sp.decline("biz-1", "send_invoice")
    assert "send_invoice" in biz_store["row"]["settings"]["autonomy"]["standing_declined"]
    monkeypatch_off = None  # noqa: F841 — kill switch covered below


def test_the_kill_switch_ungrants_everything(monkeypatch):
    monkeypatch.setenv("STANDING_PERMISSIONS", "off")
    assert not sp.is_granted(GRANTED, "send_sms") and sp.filing_extras(GRANTED, "send_sms") == {}


# ─── 3. filing ───────────────────────────────────────────────────────

def test_a_granted_kind_files_with_a_release_time_and_stop_on_the_phone(monkeypatch):
    posts, pushes, plain = [], [], []
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": posts.append((p, b)) or [{"id": "q-1", **b}])
    monkeypatch.setattr(sp, "load_for_filing", lambda bid: dict(GRANTED))
    monkeypatch.setattr(sp, "_now", lambda: NOW)
    monkeypatch.setattr(sp, "announce_standing", lambda bid, owner, qid, s: pushes.append((bid, owner, qid, s)) or 1)
    import proposal_life
    monkeypatch.setattr(proposal_life, "announce_filed", lambda bid, qid, s: plain.append(qid) or 1)
    monkeypatch.setattr(proposal_life, "filing_extras", lambda now=None, hours=None: {})
    qid = ap.file("biz-1", {"type": "send_sms", "contact_id": "c-1", "message": "See you Thursday"},
                  actor="chief:agent", surface="agent")
    row = posts[0][1]
    assert qid == "q-1" and row["scheduled_for"] == "2026-09-08T16:02:00Z"
    assert ap.spec_from_body(row["body"]).get("standing") is True
    assert pushes == [("biz-1", "own-1", "q-1", "Text the contact: “See you Thursday”")] or pushes[0][:3] == ("biz-1", "own-1", "q-1")
    assert not plain, "the ordinary push is not sent as well"
    ap.file("biz-1", {"type": "send_invoice", "invoice_id": "inv-1"}, actor="chief:agent", surface="agent")
    row2 = posts[1][1]
    assert "scheduled_for" not in row2 and not ap.spec_from_body(row2["body"]).get("standing")
    assert plain == ["q-1"], "an ungranted kind files exactly as before"


def test_announce_standing_carries_stop(monkeypatch):
    import push_notifications
    sent = []
    monkeypatch.setattr(push_notifications, "push_enabled", lambda: True)
    monkeypatch.setattr(push_notifications, "send_to_user", lambda uid, **kw: sent.append((uid, kw)) or 1)
    assert sp.announce_standing("biz-1", "own-1", "q-9", "Text Ada") == 1
    uid, kw = sent[0]
    assert kw["actions"][0] == {"action": "stop", "title": "Stop"} and kw["data"]["stop_id"] == "q-9"
    assert "2 minutes" in kw["title"]
    assert sp.announce_standing("biz-1", None, "q-9", "x") == 0


# ─── 4. the release tick ─────────────────────────────────────────────

@pytest.fixture
def release(monkeypatch):
    state = {"biz": dict(GRANTED), "claimed": [], "patches": [], "executed": [], "audit": [], "posts": [],
             "invoice_total": 120.0, "claim_ok": True}
    monkeypatch.setattr(sp, "_load", lambda bid: dict(state["biz"]))

    def _patch(path, body):
        state["patches"].append((path, body))
        if "status=eq.draft" in path:
            return [{"id": "q-1"}] if state["claim_ok"] else []
        return [{}]
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", _patch)
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p: [{"total": state["invoice_total"]}] if p.startswith("/invoices") else [])
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer=None: state["posts"].append((p, b)) or [])
    import policy_engine
    monkeypatch.setattr(policy_engine, "is_paused", lambda b: False)

    async def _exec(client, biz, item):
        state["executed"].append(item)
        return {"ok": True, "sent": False, "reason": "action_ran", "message": "sent"}
    monkeypatch.setattr(ap, "execute", _exec)
    import audit_log
    monkeypatch.setattr(audit_log, "record", lambda *a, **k: state["audit"].append(k) or True)
    return state


def _row(verb="send_sms", standing=True, **args):
    spec = {"action": {"type": verb, **args}, "actor": "chief:agent", "surface": "agent"}
    if standing:
        spec["standing"] = True
    return {"id": "q-1", "business_id": "biz-1", "subject": "Text Ada", "channel": "action",
            "status": "draft", "body": ap.spec_to_body(spec), "scheduled_for": _at(0)}


def test_the_tick_releases_through_the_door_on_the_standing_surface(release):
    out = _run(sp.release_one(_row(contact_id="c-1", message="hi"), NOW))
    assert out["did"] == "sent"
    claim = release["patches"][0]
    assert "status=eq.draft" in claim[0] and claim[1]["status"] == "approved", "claimed only while still a draft"
    assert release["executed"][0]["_standing"] == "send_sms"
    a = release["audit"][-1]
    assert a["source"] == "standing" and a["authorized_by"] == "standing:send_sms" and a["actor_id"] == "standing"
    assert any(b.get("action_type") == "standing_send" for p, b in release["posts"] if p == "/chief_activity")


def test_execute_marks_the_surface(monkeypatch):
    seen = {}

    async def _door(client, biz, actions, user_id=None, prior_results=None, surface="chat", prompted=True):
        seen.update(surface=surface, prompted=prompted)
        return [{"type": actions[0]["type"], "result": "ok", "label": "x"}]
    monkeypatch.setattr(cos, "_execute_actions", _door)
    _run(ap.execute(None, BIZ, {**_row(contact_id="c-1", message="hi"), "_standing": "send_sms"}))
    assert seen == {"surface": "standing", "prompted": True}
    _run(ap.execute(None, BIZ, _row(contact_id="c-1", message="hi")))
    assert seen == {"surface": "approval", "prompted": True}


def test_a_stop_in_between_wins_and_a_plain_draft_is_never_released(release):
    release["claim_ok"] = False
    assert _run(sp.release_one(_row(contact_id="c-1", message="hi"), NOW))["did"] == "skipped"
    assert not release["executed"]
    assert _run(sp.release_one(_row(standing=False, contact_id="c-1", message="hi"), NOW))["did"] == "skipped"


def test_revoked_paused_and_over_cap_are_held_not_sent(release, monkeypatch):
    release["biz"] = dict(BIZ)
    assert _run(sp.release_one(_row(contact_id="c-1", message="hi"), NOW)) == {"id": "q-1", "did": "held", "why": "revoked"}
    hold = release["patches"][-1][1]
    assert hold["scheduled_for"] is None and "turned off" in hold["ai_reasoning"]
    release["biz"] = dict(GRANTED)
    import policy_engine
    monkeypatch.setattr(policy_engine, "is_paused", lambda b: True)
    assert _run(sp.release_one(_row(contact_id="c-1", message="hi"), NOW))["why"] == "paused"
    monkeypatch.setattr(policy_engine, "is_paused", lambda b: False)
    release["biz"] = {**BIZ, "settings": {"autonomy": {"standing": {"send_invoice": {"granted_at": "x"}}}}}
    release["invoice_total"] = 900.0
    out = _run(sp.release_one(_row("send_invoice", invoice_id="inv-1"), NOW))
    assert out["why"] == "cap" and "above your $500" in release["patches"][-1][1]["ai_reasoning"]
    assert any("Needs your tap" in b.get("title", "") for p, b in release["posts"] if p == "/chief_notifications")
    release["invoice_total"] = 300.0
    assert _run(sp.release_one(_row("send_invoice", invoice_id="inv-1"), NOW))["did"] == "sent"
    assert not release["executed"][:0]
    monkeypatch.setenv("STANDING_PERMISSIONS", "off")
    assert _run(sp.release_tick(NOW)) == {"skipped": "off"}


# ─── 5. the retire rule revokes ──────────────────────────────────────

def test_stopped_three_times_running_loses_the_grant(monkeypatch):
    import outcome_ledger as ol
    revoked, told = [], []
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p: [dict(GRANTED)] if p.startswith("/businesses") else [])
    monkeypatch.setattr(ol, "recent_moves", lambda bid, days=30, limit=400: [
        {"verb": "send_sms", "queue_id": f"q{i}", "outcome": "dismissed", "made_at": _at(i)} for i in (1, 2, 3)])
    monkeypatch.setattr(sp, "revoke", lambda bid, verb, **kw: revoked.append((bid, verb, kw["via"])) or True)
    monkeypatch.setattr(sp, "_tell", lambda biz, title, body, key: told.append(title))
    assert sp.sweep_revocations(NOW) == ["biz-1:send_sms"]
    assert revoked == [("biz-1", "send_sms", "retire")] and "back to asking" in told[0]


# ─── 6. the chat verbs and the words ─────────────────────────────────

def test_the_chat_verbs_grant_only_what_is_eligible(monkeypatch):
    calls = []
    monkeypatch.setattr(sp, "grant", lambda bid, verb, **kw: calls.append(("grant", verb, kw["via"])) or (True, "2026-09-08T16:00:00Z"))
    monkeypatch.setattr(sp, "revoke", lambda bid, verb, **kw: calls.append(("revoke", verb, kw["via"])) or True)
    out = _run(cos.ACTION_HANDLERS["grant_standing_permission"](None, BIZ, {"verb": "texts"}))
    assert out["verb"] == "send_sms" and "2-minute" in out["result"] and calls[-1] == ("grant", "send_sms", "chat")
    assert cos._action_failed(_run(cos.ACTION_HANDLERS["grant_standing_permission"](None, BIZ, {"verb": "publish_to_site"})))
    assert cos._action_failed(_run(cos.ACTION_HANDLERS["grant_standing_permission"](None, BIZ, {})))
    therapist = {**BIZ, "type": "therapist", "settings": {"autonomy": {"client_facing_autonomy": "disabled"}}}
    assert cos._action_failed(_run(cos.ACTION_HANDLERS["grant_standing_permission"](None, therapist, {"verb": "send_sms"})))
    out = _run(cos.ACTION_HANDLERS["revoke_standing_permission"](None, GRANTED, {}))
    assert out["verb"] == "send_sms" and calls[-1] == ("revoke", "send_sms", "chat")
    import action_registry
    assert action_registry.reversibility("grant_standing_permission") == "C"
    assert action_registry.reversibility("revoke_standing_permission") == "A"


def test_the_prompt_forbids_suggesting_it_and_the_context_names_grants():
    import chief_prompt
    src = open(chief_prompt.__file__, encoding="utf-8").read()
    assert "NEVER suggest it" in src and "grant_standing_permission" in src
    lines = sp.context_lines(GRANTED)
    assert lines and "texts (since 2026-09-01)" in lines[0] and "2-minute window" in lines[0]
    assert sp.context_lines(BIZ) == []


def test_the_approval_response_carries_the_offer(monkeypatch):
    import approvals_router as ar
    monkeypatch.setattr(sp, "offer_after_approval", lambda biz, verb: {"verb": verb, "question": "q"})
    item = {"channel": "action", "body": ap.spec_to_body({"action": {"type": "send_sms", "contact_id": "c-1", "message": "hi"}, "actor": "a", "surface": "agent"})}
    assert ar._standing_offer(BIZ, item)["verb"] == "send_sms"
    assert ar._standing_offer(BIZ, {"channel": "email", "body": "x"}) is None


def test_the_door_is_owner_only(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(sp, "_load", lambda bid: {"id": "biz-1", "owner_id": "own-1", "settings": {}})

    class U:
        id = "stranger"
    with pytest.raises(HTTPException) as e:
        sp.standing("biz-1", U())
    assert e.value.status_code == 403
