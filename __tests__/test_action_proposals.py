"""Class C through a tool: propose, a person approves, then it runs.

Pinned:
  * the reviewed set is class C, never bulk, never a write tool, and no
    class C verb name is a tool anywhere (exposed_tools is untouched);
  * a proposal validates its arguments and refuses a raw recipient;
  * the queue body round-trips, and re-validates on the way out;
  * the tool loop offers propose_* only off the chat turn, files one row
    per call, spends the write budget, and refuses on the chat turn;
  * the connector lists propose_* for a write key only, refuses a read
    key by scope, and files for a write key without running anything;
  * Approve runs the action through the door prompted, on surface
    "approval", and the label says whether it went through.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import action_proposals as ap
import action_registry
import chief_tool_loop as ctl
import mcp_server as mcp
import sb_clients

BIZ = {"id": "biz-1", "name": "Bloom", "owner_id": "own-1", "settings": {}}


def _run(coro):
    return asyncio.run(coro)


# ─── The set ────────────────────────────────────────────────────────────

def test_every_proposal_is_class_c_not_bulk_and_not_a_write_tool():
    assert ap.PROPOSALS, "the reviewed set is empty"
    for name, (verb, desc, schema) in ap.PROPOSALS.items():
        assert name == f"propose_{verb}"
        assert action_registry.reversibility(verb) == "C", verb
        assert not action_registry.is_bulk(verb), verb
        assert verb not in mcp.WRITE_TOOL_SCHEMAS, verb
        assert "PROPOSE" in desc and "approv" in desc.lower(), name
        assert schema["additionalProperties"] is False


def test_no_class_c_verb_is_a_tool_anywhere():
    for verb in ap.verbs():
        assert verb not in mcp.exposed_tools(allow_writes=True)
        assert verb not in [t["name"] for t in ctl.write_tool_definitions()]


# ─── Validation ─────────────────────────────────────────────────────────

def test_action_for_validates_and_refuses_a_raw_recipient():
    a = ap.action_for("propose_send_sms", {"contact_name": " Maria ", "message": "See you Tuesday "})
    assert a == {"type": "send_sms", "contact_name": "Maria", "message": "See you Tuesday"}
    with pytest.raises(ValueError, match="raw number"):
        ap.action_for("propose_send_sms", {"to": "+12165550100", "message": "hi"})
    with pytest.raises(ValueError, match="needs message"):
        ap.action_for("propose_send_sms", {"contact_name": "Maria"})
    with pytest.raises(ValueError, match="contact_id or contact_name"):
        ap.action_for("propose_send_sms", {"message": "hi"})
    with pytest.raises(ValueError, match="320"):
        ap.action_for("propose_send_sms", {"contact_name": "M", "message": "x" * 321})
    with pytest.raises(ValueError, match="does not take"):
        ap.action_for("propose_send_invoice", {"invoice_id": "i", "amount": 5})
    with pytest.raises(ValueError, match="not a proposal tool"):
        ap.action_for("send_sms", {"message": "hi"})


def test_the_body_round_trips_and_revalidates():
    action = ap.action_for("propose_mark_invoice_paid", {"invoice_id": "inv-1", "payment_method": "cash"})
    body = ap.spec_to_body({"action": action, "actor": "agent:claude", "surface": "agent"})
    assert body.startswith("Mark invoice inv-1 paid (cash)")
    assert "Nothing has happened yet" in body
    spec = ap.spec_from_body(body)
    assert spec["action"] == action and spec["actor"] == "agent:claude"
    # a hand-edited body cannot widen what an approval runs
    widened = body.replace('"invoice_id":"inv-1"', '"invoice_id":"inv-1","to":"+1"')
    assert ap.spec_from_body(widened) is None
    assert ap.spec_from_body(body.replace('"type":"mark_invoice_paid"', '"type":"delete_contact"')) is None
    assert ap.spec_from_body("nothing") is None


def test_file_writes_one_draft_on_the_action_channel(monkeypatch):
    posts = []
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": posts.append((p, b)) or [{"id": "q-1", **b}])
    qid = ap.file("biz-1", {"type": "send_sms", "contact_id": "c-1", "message": "hi"},
                  actor="chief:agent", surface="agent")
    assert qid == "q-1"
    path, row = posts[0]
    assert path == "/agent_queue"
    assert row["channel"] == "action" and row["action_type"] == "chief_action"
    assert row["status"] == "draft" and row["contact_id"] == "c-1" and row["agent"] == "chief"
    assert ap.spec_from_body(row["body"])["action"]["message"] == "hi"
    with pytest.raises(ValueError):
        ap.file("biz-1", {"type": "create_contact", "name": "x"}, actor="a", surface="agent")


# ─── The tool loop ──────────────────────────────────────────────────────

def _proposal_names(tools):
    # two READ tools are also named propose_* (voice rule, brand kit); only
    # the reviewed set counts here
    return [t["name"] for t in tools if t["name"] in ap.PROPOSALS]


def test_the_loop_offers_proposals_off_the_chat_turn_only():
    ctl.reset_turn(True)
    assert _proposal_names(ctl.tool_definitions_for_turn(True)) == []
    ctl.reset_turn(True, surface="agent", prompted=False)
    assert "propose_send_sms" in _proposal_names(ctl.tool_definitions_for_turn(True))
    ctl.reset_turn(False, surface="agent", prompted=False)
    assert _proposal_names(ctl.tool_definitions_for_turn(False)) == []
    ctl.reset_turn(False)


def test_on_the_chat_turn_a_proposal_is_refused_and_nothing_is_filed(monkeypatch):
    monkeypatch.setattr(ap, "file", lambda *a, **k: pytest.fail("must not file on the chat turn"))
    ctl.reset_turn(True)
    err, text = _run(ctl.execute_tool_use(None, BIZ, "propose_send_sms",
                                          {"contact_name": "Maria", "message": "hi"}))
    assert err and "[ACTION:]" in text
    ctl.reset_turn(False)


def test_the_standing_agent_files_a_proposal_and_spends_the_write_budget(monkeypatch):
    filed = []
    monkeypatch.setattr(ap, "file", lambda biz, action, **k: filed.append((biz, action, k)) or "q-7")

    async def turn():
        # contextvars do not flow back out of asyncio.run — the whole turn
        # lives in one coroutine, as it does in production
        ctl.reset_turn(True, surface="agent", prompted=False)
        err, text = await ctl.execute_tool_use(None, BIZ, "propose_send_sms",
                                               {"contact_name": "Maria", "message": "See you Tuesday"})
        taken = ctl.writes_this_turn()
        err2, text2 = await ctl.execute_tool_use(None, BIZ, "propose_send_sms", {"to": "+1", "message": "x"})
        return err, text, taken, err2, text2
    err, text, taken, err2, text2 = _run(turn())
    assert not err and "q-7" in text and "Nothing has been sent" in text
    assert filed == [("biz-1", {"type": "send_sms", "contact_name": "Maria", "message": "See you Tuesday"},
                      {"actor": "chief:agent", "surface": "agent"})]
    assert taken and taken[0]["proposed"] and taken[0]["queue_id"] == "q-7"
    assert taken[0]["result"] == "proposed" and taken[0]["label"]
    # bad arguments are a readable error, not a row
    assert err2 and "raw number" in text2 and len(filed) == 1
    ctl.reset_turn(False)


# ─── The connector ──────────────────────────────────────────────────────

def _caller(write: bool):
    return mcp.Caller("token", "agent:claude", user_id="u-1", business_id="biz-1",
                      scopes=["read", "write"] if write else ["read"], jti="j-1")


def test_the_connector_lists_proposals_for_a_write_key_only():
    names_w = [t["name"] for t in mcp.tool_definitions(_caller(True))]
    names_r = [t["name"] for t in mcp.tool_definitions(_caller(False))]
    assert "propose_send_sms" in names_w and "send_sms" not in names_w
    assert not [n for n in names_r if n in ap.PROPOSALS]
    assert len(mcp.tool_definitions(None)) == len(mcp.exposed_tools())


def test_a_read_key_is_refused_by_scope_and_a_write_key_files_without_running(monkeypatch):
    allowed, ok, payload, _ = _run(mcp._call_tool("propose_send_sms", {"contact_name": "M", "message": "hi"},
                                                  _caller(False)))
    assert (allowed, ok) == (False, False) and "write" in payload and "scope" in payload

    async def resolve(client, caller):
        return BIZ
    monkeypatch.setattr(mcp, "_resolve_business", resolve)
    monkeypatch.setattr(mcp, "_tier_allows", lambda biz: True)
    ledger = []
    monkeypatch.setattr(mcp, "_ledger", lambda *a, **k: ledger.append((a[1], k)))
    filed = []
    monkeypatch.setattr(ap, "file", lambda biz, action, **k: filed.append((biz, action, k)) or "q-9")
    import chief_of_staff
    monkeypatch.setitem(chief_of_staff.ACTION_HANDLERS, "send_sms",
                        lambda *a, **k: pytest.fail("a proposal must never run the verb"))
    allowed, ok, payload, bid = _run(mcp._call_tool("propose_send_sms",
                                                    {"contact_name": "M", "message": "hi"}, _caller(True)))
    assert (allowed, ok, bid) == (True, True, "biz-1")
    assert payload["proposed"] and payload["queue_id"] == "q-9" and "Nothing has been sent" in payload["note"]
    assert filed[0][2] == {"actor": "agent:agent:claude", "surface": "agent"}
    assert ledger[-1][1]["ok"] and ledger[-1][1]["reason"] == "proposal:filed"
    # the verb itself is still the flat refusal
    allowed, ok, payload, _ = _run(mcp._call_tool("send_sms", {"message": "hi"}, _caller(True)))
    assert not allowed and "not available" in payload


# ─── Approval runs it ───────────────────────────────────────────────────

def _item(action):
    return {"id": "q-3", "business_id": "biz-1", "channel": "action", "action_type": "chief_action",
            "subject": ap.describe(action),
            "body": ap.spec_to_body({"action": action, "actor": "agent:claude", "surface": "agent"}),
            "status": "draft"}


def test_approve_runs_the_action_through_the_door_prompted(monkeypatch):
    import chief_of_staff as cos
    calls = []

    async def _sb(client, method, path, body=None):
        calls.append((method, path))
        return []
    monkeypatch.setattr(cos, "_sb", _sb)
    ran = []

    async def door(client, biz, actions, user_id=None, prior_results=None, surface="chat", prompted=True):
        ran.append((actions, surface, prompted, user_id))
        return [{"type": "send_sms", "result": "sent", "label": "📱 Sent to Maria"}]
    monkeypatch.setattr(cos, "_execute_actions", door)
    action = {"type": "send_sms", "contact_name": "Maria", "message": "hi"}
    delivery = _run(cos._do_approve_one(None, BIZ, _item(action)))
    assert ran == [([action], "approval", True, "own-1")]
    assert delivery["ok"] and delivery["sent"] is False and delivery["reason"] == "action_ran"
    assert cos._approve_label("x", delivery) == "✓ Approved and done: 📱 Sent to Maria"
    assert calls[0] == ("PATCH", "/agent_queue?id=eq.q-3"), "marked approved first, as every approval is"


def test_a_failed_run_is_an_honest_label_and_an_unreadable_proposal_never_runs(monkeypatch):
    import chief_of_staff as cos

    async def _sb(client, method, path, body=None):
        return []
    monkeypatch.setattr(cos, "_sb", _sb)

    async def door(client, biz, actions, **k):
        return [cos._fail("send_sms", "no phone on file")]
    monkeypatch.setattr(cos, "_execute_actions", door)
    action = {"type": "send_sms", "contact_name": "Maria", "message": "hi"}
    delivery = _run(cos._do_approve_one(None, BIZ, _item(action)))
    assert delivery["ok"] is False and delivery["reason"] == "action_failed"
    assert "did not go through" in cos._approve_label("Text Maria", delivery)

    monkeypatch.setattr(cos, "_execute_actions",
                        lambda *a, **k: pytest.fail("an unreadable proposal must not run"))
    item = {**_item(action), "body": "garbage"}
    delivery = _run(cos._do_approve_one(None, BIZ, item))
    assert delivery["ok"] is False and delivery["reason"] == "action_spec_invalid"
