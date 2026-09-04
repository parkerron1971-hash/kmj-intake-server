"""
The agent-facing MCP surface — Stage 4: writes behind a scope.

Stage 1 tests (test_mcp_server.py) are weighted toward what the surface
REFUSES, and every one of them still holds: the default caller is
read-only and sees exactly what it saw before. These tests cover the
door that opened — and are weighted the same way.

Three properties carry the weight:

  Class C is unreachable at ANY scope. Not "not offered" — refused when
  named, with the same flat message an unknown verb gets, so a refusal
  never doubles as a hint.

  A write needs the scope, and the scope needs a token. A browser session
  is a person, and a person acts through Chief.

  A write that landed is a write the practitioner can take back. Every
  successful class-A call goes through the same undo recorder a chat
  action does.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import action_registry
import mcp_server as mcp
import mcp_tokens


def _run(coro):
    return asyncio.run(coro)


def _reader(kind="token"):
    kw = {"scopes": ["read"]}
    if kind == "owner_jwt":
        kw["user_id"] = "owner-1"
    else:
        kw["business_id"] = "biz-1"
    return mcp.Caller(kind, "t", **kw)


def _writer():
    return mcp.Caller("token", "token:agent", business_id="biz-1",
                      scopes=["read", "write"], jti="j1")


@pytest.fixture
def biz(monkeypatch):
    """A resolved business, a permissive policy, and no ledger/undo I/O."""
    async def _fake_biz(client, caller):
        return {"id": "biz-1", "name": "Test Co", "type": "coach",
                "settings": {}, "owner_id": "owner-1"}
    monkeypatch.setattr(mcp, "_resolve_business", _fake_biz)
    monkeypatch.setattr(mcp, "_ledger", lambda *a, **k: None)
    monkeypatch.setattr(mcp, "_tier_allows", lambda b: True)

    import chief_of_staff
    recorded = []

    async def _record(client, biz, atype, action, result):
        recorded.append((atype, action, result))
    monkeypatch.setattr(chief_of_staff, "_record_undoable", _record)
    return {"undo": recorded}


# ─── what is offered, to whom ────────────────────────────────────────

def test_the_read_only_list_is_unchanged():
    """The Stage 1 tripwire stays the tripwire. Adding writes must not
    have moved a single read verb."""
    assert mcp.exposed_tools() == mcp.exposed_tools(allow_writes=False)
    for v in mcp.exposed_tools():
        assert action_registry.effect(v) == action_registry.READ


def test_write_tools_are_class_a_reviewed_and_never_bulk():
    """The two gates, checked against each other. Every schema'd write is
    one the registry permits (class A, not sensitive, not bulk), and the
    exposed write list is exactly that intersection."""
    offered = set(mcp.exposed_tools(allow_writes=True)) - set(mcp.exposed_tools())
    assert offered, "the write surface is empty"
    for v in offered:
        assert action_registry.effect(v) == action_registry.WRITE, v
        assert action_registry.reversibility(v) == "A", v
        assert not action_registry.is_sensitive(v), v
        assert not action_registry.is_bulk(v), v
        assert v in mcp.WRITE_TOOL_SCHEMAS, v
    for v in mcp.WRITE_TOOL_SCHEMAS:
        assert v in offered, (
            f"{v} has a write schema but the registry does not allow it "
            "on this surface — remove the schema or reclassify on purpose")


def test_the_write_surface_count_is_a_tripwire():
    """Same discipline as the read count. A write verb joining this
    surface is a decision about what somebody else's agent may change in
    a practitioner's business; make it on purpose, with a schema whose
    argument names were read off the handler.

    28 (2026-09-03, Stage 4): the first set. People (5), work (5),
    calendar (5), the practitioner's own module rows (3), offerings (2),
    drafts/memory/notes/content (7), and undo_last (1) — reads before
    writes, and nothing that sends, spends, or deletes for good.
    55 (2026-09-04, batch 2): goals and reminders (2), projects (1),
    booking configuration (4), testimonials and policies (3), email
    templates and read-marks (3), scheduled/drafts (3), offerings (1),
    contact health (1), owner notifications (1), time and balances (4),
    texting switches (2), templates and bookkeeping proposals (2).
    56 (2026-09-04, missions from a non-chat trigger): propose_mission
    (1) — drafts a plan row and runs nothing; start_mission stays class
    C and off every surface.
    """
    offered = set(mcp.exposed_tools(allow_writes=True)) - set(mcp.exposed_tools())
    assert len(offered) == 56, (
        f"write surface changed: {sorted(offered)}. If a verb was added, "
        "decide whether an outside agent should change it, write its "
        "schema from the handler, and update this count on purpose.")


def test_every_write_tool_has_a_handler():
    import chief_of_staff
    for v in mcp.WRITE_TOOL_SCHEMAS:
        assert v in chief_of_staff.ACTION_HANDLERS, f"{v}: no handler"


def test_write_schemas_are_closed_objects():
    for v, (desc, schema) in mcp.WRITE_TOOL_SCHEMAS.items():
        assert desc.strip(), v
        assert schema["type"] == "object", v
        assert schema.get("additionalProperties") is False, (
            f"{v}: inputSchema must reject unknown properties")


def test_no_write_schema_spends_the_model_by_default():
    """The verbs that draft with the model are deliberately absent, and
    draft_email is here only because its body is REQUIRED and long enough
    that the handler will not draft one itself (it drafts under 21 chars)."""
    for v in ("draft_nurture", "rewrite_draft", "run_agent", "analyze_trends",
              "run_market_research", "propose_module_from_intake",
              "plan_campaign", "generate_document", "generate_insights"):
        assert v not in mcp.WRITE_TOOL_SCHEMAS, v
    body = mcp.WRITE_TOOL_SCHEMAS["draft_email"][1]
    assert "body" in body["required"]
    assert body["properties"]["body"]["minLength"] >= 21


def test_no_write_schema_reaches_a_client():
    """Nothing that policy_engine calls client-facing is offered, at any
    scope — not even a class-A one like create_booking's neighbours."""
    import policy_engine
    for v in mcp.WRITE_TOOL_SCHEMAS:
        assert v not in policy_engine.CLIENT_FACING, v
    for v in ("cancel_booking", "reschedule_booking", "edit_draft"):
        assert v not in mcp.WRITE_TOOL_SCHEMAS, v


def test_tools_list_shows_writes_only_to_a_write_caller():
    read_names = {t["name"] for t in mcp.tool_definitions(_reader())}
    write_names = {t["name"] for t in mcp.tool_definitions(_writer())}
    assert "create_contact" not in read_names
    assert "create_contact" in write_names
    assert read_names < write_names
    assert read_names == {t["name"] for t in mcp.tool_definitions(None)}


def test_a_browser_session_is_shown_no_write_tools():
    names = {t["name"] for t in mcp.tool_definitions(_reader("owner_jwt"))}
    assert not any(mcp.is_write_tool(n) for n in names)


def test_instructions_match_the_scope():
    r = _run(mcp._handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                             _reader(), "t"))
    assert "nothing writes" in r["result"]["instructions"].lower()
    r = _run(mcp._handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                             _writer(), "t"))
    text = r["result"]["instructions"].lower()
    assert "sends anything to a client" in text
    assert "undo_last" in text


# ─── refusals ────────────────────────────────────────────────────────

@pytest.mark.parametrize("verb", ["send_sms", "create_invoice", "delete_contact",
                                  "publish_post", "approve_draft", "start_mission"])
def test_class_c_is_refused_even_with_the_write_scope(verb, biz):
    allowed, ok, msg, _ = _run(mcp._call_tool(verb, {}, _writer()))
    assert allowed is False and ok is False
    assert "not available" in msg
    assert "scope" not in msg, "a class-C refusal must not hint at a scope"


def test_bulk_verbs_are_refused_even_with_the_write_scope(biz):
    allowed, ok, msg, _ = _run(mcp._call_tool("bulk_dismiss", {}, _writer()))
    assert allowed is False and ok is False
    assert "not available" in msg


def test_a_class_a_verb_without_a_schema_is_refused(biz):
    """Reversible, permitted by the registry, and still not a tool until
    somebody has reviewed it here."""
    unreviewed = [v for v in action_registry.REGISTRY
                  if action_registry.may_expose_to_agent(v, allow_writes=True)
                  and action_registry.effect(v) == action_registry.WRITE
                  and v not in mcp.WRITE_TOOL_SCHEMAS
                  and not action_registry.is_bulk(v)]
    assert unreviewed, "every class-A verb is exposed — the floor is gone"
    allowed, ok, msg, _ = _run(mcp._call_tool(unreviewed[0], {}, _writer()))
    assert allowed is False and ok is False
    assert "not available" in msg


def test_a_read_only_token_is_told_it_needs_the_scope(biz):
    allowed, ok, msg, _ = _run(mcp._call_tool("create_contact", {"name": "x"}, _reader()))
    assert allowed is False and ok is False
    assert "write" in msg and "scope" in msg


def test_a_browser_session_cannot_write(biz):
    """A JWT is a person. People act through Chief."""
    allowed, ok, msg, _ = _run(mcp._call_tool("create_contact", {"name": "x"},
                                              _reader("owner_jwt")))
    assert allowed is False and ok is False
    assert "scope" in msg


def test_may_write_needs_a_token_not_just_the_word():
    jwt = mcp.Caller("owner_jwt", "o", user_id="u", scopes=["read", "write"])
    assert jwt.may_write is False
    tok = mcp.Caller("token", "t", business_id="b", scopes=["read", "write"])
    assert tok.may_write is True


# ─── a write that lands ──────────────────────────────────────────────

def test_a_write_dispatches_and_is_recorded_for_undo(monkeypatch, biz):
    import chief_of_staff
    seen = {}

    async def _fake(client, b, action):
        seen.update(action)
        return {"type": "create_contact", "result": "created",
                "label": "Added Ada", "contact_id": "c-1"}
    monkeypatch.setitem(chief_of_staff.ACTION_HANDLERS, "create_contact", _fake)

    allowed, ok, payload, biz_id = _run(
        mcp._call_tool("create_contact", {"name": "Ada", "type": "send_sms"}, _writer()))
    assert allowed and ok
    assert biz_id == "biz-1"
    assert seen["type"] == "create_contact", "arguments cannot rewrite the verb"
    assert payload["contact_id"] == "c-1"
    assert biz["undo"] and biz["undo"][0][0] == "create_contact"


def test_a_declined_write_is_ok_false_with_the_handlers_own_words(monkeypatch, biz):
    """'Contact not found' is not an exception and not a success. The
    model gets the sentence; the audit row gets ok=False; nothing is
    recorded as undoable."""
    import chief_of_staff

    async def _declines(client, b, action):
        return chief_of_staff._fail("create_note", "Contact c-9 not found")
    monkeypatch.setitem(chief_of_staff.ACTION_HANDLERS, "create_note", _declines)

    allowed, ok, msg, _ = _run(
        mcp._call_tool("create_note", {"contact_id": "c-9", "note": "hi"}, _writer()))
    assert allowed is True
    assert ok is False
    assert isinstance(msg, str) and msg
    assert not biz["undo"]


def test_a_failed_undo_record_does_not_unwind_the_write(monkeypatch, biz):
    import chief_of_staff

    async def _fake(client, b, action):
        return {"type": "create_task", "result": "added", "label": "x", "task_id": "t1"}
    monkeypatch.setitem(chief_of_staff.ACTION_HANDLERS, "create_task", _fake)

    async def _boom(*a, **k):
        raise RuntimeError("undo log down")
    monkeypatch.setattr(chief_of_staff, "_record_undoable", _boom)

    allowed, ok, payload, _ = _run(
        mcp._call_tool("create_task", {"title": "call Ada"}, _writer()))
    assert allowed and ok and payload["task_id"] == "t1"


def test_the_policy_engine_still_runs_unprompted(monkeypatch, biz):
    """An agent's write is unattended. A practitioner who paused their
    automations paused their agent too."""
    import chief_of_staff
    import policy_engine

    async def _fake(client, b, action):
        raise AssertionError("handler must not run when policy refuses")
    monkeypatch.setitem(chief_of_staff.ACTION_HANDLERS, "create_task", _fake)
    monkeypatch.setattr(policy_engine, "is_paused", lambda b: True)

    allowed, ok, msg, _ = _run(
        mcp._call_tool("create_task", {"title": "x"}, _writer()))
    assert allowed is False and ok is False
    assert "paused" in msg.lower()


def test_reads_still_work_for_a_write_caller(monkeypatch, biz):
    import chief_of_staff

    async def _fake(client, b, action):
        return {"type": "catch_up", "result": "quiet", "label": "Caught up"}
    monkeypatch.setitem(chief_of_staff.ACTION_HANDLERS, "catch_up", _fake)
    allowed, ok, payload, _ = _run(mcp._call_tool("catch_up", {}, _writer()))
    assert allowed and ok and payload["result"] == "quiet"
    assert not biz["undo"], "a read is never recorded as undoable"


# ─── the practitioner's door ─────────────────────────────────────────

def test_the_endpoint_no_longer_refuses_non_owner_jwts():
    """Stage 1's 403 for anyone but PLATFORM_OWNER_EMAIL is gone. The
    tenancy guarantee moved to where it always really lived: a JWT
    resolves to the business it OWNS, by owner_id, never by parameter."""
    import inspect
    src = inspect.getsource(mcp.mcp_endpoint)
    assert "restricted to the platform owner" not in src
    assert "PLATFORM_OWNER_EMAIL" not in src


def test_token_endpoints_check_ownership_not_platform_email():
    import inspect
    for fn in (mcp.mint_token, mcp.list_tokens_endpoint, mcp.revoke_token):
        src = inspect.getsource(fn)
        assert "PLATFORM_OWNER_EMAIL" not in src, fn.__name__
        assert "_owned_business" in src, fn.__name__


def test_owned_business_refuses_a_business_the_caller_does_not_own(monkeypatch):
    from fastapi import HTTPException

    async def _by_id(client, business_id):
        return {"id": business_id, "owner_id": "someone-else"}
    monkeypatch.setattr(mcp, "_business_by_id", _by_id)

    class _U:
        id = "me"
        email = "me@x.com"

    with pytest.raises(HTTPException) as e:
        _run(mcp._owned_business(None, _U(), "biz-9"))
    assert e.value.status_code == 403


def test_health_reports_the_write_surface_without_a_credential():
    r = _run(mcp.mcp_health())
    assert r["tools"] == len(mcp.exposed_tools())
    assert r["write_tools"] == len(mcp.WRITE_TOOL_SCHEMAS)
    assert r["scopes"] == ["read", "write"]
