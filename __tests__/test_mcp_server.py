"""
The agent-facing MCP surface — Stage 1.

This is the first endpoint in the system a non-practitioner can call, so
the tests are weighted toward what it REFUSES rather than what it returns.

Two properties carry most of the weight:

  The tool list is DERIVED, never held. `may_expose_to_agent()` is the
  authorization decision; a second hand-maintained list would drift, and
  that drift would be a security bug rather than a tidiness one.

  There is no remapper. Inside Chief an unrecognised verb is routed to
  `chief_action_reasoner` and reinterpreted into safe primitives — right
  there, wrong here. An agent asking for an unknown tool is mistaken or
  probing; either way it gets an error.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import action_registry
import mcp_server as mcp
import rate_limit


class _User:
    def __init__(self, email="kmjcreativesolution@gmail.com", uid="owner-1"):
        self.email = email
        self.id = uid


def _caller(kind="owner_jwt", **kw):
    """The normalised caller the dispatch path takes. Build 3 replaced the
    raw AuthedUser with this so a scoped token and an owner JWT reach the
    same code by the same shape."""
    kw.setdefault("scopes", ["read"])
    if kind == "owner_jwt":
        kw.setdefault("user_id", "owner-1")
    return mcp.Caller(kind, "owner", **kw)


def _rpc(method, params=None, req_id=1):
    m = {"jsonrpc": "2.0", "method": method}
    if req_id is not None:
        m["id"] = req_id
    if params is not None:
        m["params"] = params
    return m


def _run(coro):
    return asyncio.run(coro)


# ─── the tool list is derived ────────────────────────────────────────

def test_tool_list_comes_from_the_registry():
    """If these ever disagree, something is hand-maintaining a list."""
    assert mcp.exposed_tools() == sorted(
        v for v in action_registry.REGISTRY if action_registry.may_expose_to_agent(v))


def test_every_exposed_verb_has_a_schema():
    """MCP requires machine-readable JSON Schema per tool. A verb that
    becomes exposable without one must fail HERE, not ship as a tool whose
    arguments a client cannot construct."""
    missing = [v for v in mcp.exposed_tools() if v not in mcp.TOOL_SCHEMAS]
    assert not missing, (
        f"agent-exposable verbs with no inputSchema: {missing}. "
        f"Add them to mcp_server.TOOL_SCHEMAS.")


def test_no_schema_describes_a_verb_that_is_not_exposed():
    """The reverse drift: a schema left behind after a verb was reclassified
    would advertise a tool that is refused at call time."""
    stale = [v for v in mcp.TOOL_SCHEMAS if not action_registry.may_expose_to_agent(v)]
    assert not stale, f"schemas for non-exposed verbs: {stale}"


def test_the_exposed_read_verbs_and_nothing_else():
    """The literal count is the POINT, not an accident.

    Exposure is derived — any verb classified `read` in action_registry
    lands on the agent surface automatically. That is convenient and it is
    also how a surface widens without anyone deciding to widen it. This
    number is the tripwire: add a read verb and this fails, forcing a
    deliberate call about whether an outside agent should see it.

    It has already earned its keep once — `check_balance` (17) tripped it,
    and the answer was yes, because contact_deep_dive already exposes a
    superset of the same person's data.

    Bump this ONLY together with a TOOL_SCHEMAS entry and a reason.
    """
    tools = mcp.exposed_tools()
    assert len(tools) == 17, (
        f"agent-facing surface changed: {sorted(tools)}. If a verb was "
        "added, decide whether an outside caller should see it, give it a "
        "TOOL_SCHEMAS entry, and update this count on purpose.")
    for verb in tools:
        assert action_registry.effect(verb) == action_registry.READ


def test_ui_verbs_are_never_offered():
    """An off-app caller has no UI to drive."""
    names = {t["name"] for t in mcp.tool_definitions()}
    for verb in ("navigate", "open_calendar", "open_documents",
                 "set_chat_window", "set_timer"):
        assert verb not in names


def test_class_c_verbs_are_never_offered():
    names = {t["name"] for t in mcp.tool_definitions()}
    c_verbs = [v for v in action_registry.REGISTRY
               if action_registry.reversibility(v) == "C"]
    assert c_verbs
    for verb in c_verbs:
        assert verb not in names, f"{verb} is class C and must never be exposed"


def test_tool_definitions_are_well_formed():
    for t in mcp.tool_definitions():
        assert t["name"] and t["description"].strip()
        assert t["inputSchema"]["type"] == "object"
        # additionalProperties must be closed, or a caller can smuggle
        # arguments the handler was never reviewed against.
        assert t["inputSchema"].get("additionalProperties") is False, (
            f"{t['name']}: inputSchema must reject unknown properties")


# ─── refusal ─────────────────────────────────────────────────────────

def test_unknown_tool_is_an_error_not_a_remap():
    """The property this surface exists to hold. Inside Chief an unknown
    verb gets reinterpreted by chief_action_reasoner; here it must not."""
    allowed, ok, msg, _biz = _run(mcp._call_tool("definitely_not_a_verb", {}, _caller()))
    assert allowed is False, "an unknown tool is REFUSED, not merely failed"
    assert ok is False
    assert "not available" in msg


@pytest.mark.parametrize("verb", ["send_sms", "create_invoice", "delete_contact",
                                  "publish_post", "mark_invoice_paid"])
def test_class_c_verbs_are_refused_at_call_time(verb):
    """Not merely absent from the list — refused if asked for directly.
    A client that hardcodes a name must not get further than one that
    reads the list."""
    allowed, ok, msg, _biz = _run(mcp._call_tool(verb, {}, _caller()))
    assert allowed is False, "refused at authorization, before any execution"
    assert ok is False
    assert "not available" in msg


@pytest.mark.parametrize("verb", ["navigate", "set_timer"])
def test_ui_verbs_are_refused_at_call_time(verb):
    allowed, ok, _msg, _biz = _run(mcp._call_tool(verb, {}, _caller()))
    assert allowed is False and ok is False


def test_write_verbs_are_refused_even_though_they_are_class_a(monkeypatch):
    """Class A is autonomy-eligible for CHIEF. That is a different question
    from whether an outside agent may call it, and the default answer is no."""
    allowed, ok, _msg, _biz = _run(mcp._call_tool("create_contact", {"name": "x"}, _caller()))
    assert allowed is False and ok is False


# ─── JSON-RPC protocol ───────────────────────────────────────────────

def test_initialize_returns_protocol_and_capabilities():
    r = _run(mcp._handle_rpc(_rpc("initialize"), _caller(), "owner"))
    assert r["result"]["protocolVersion"] == mcp.PROTOCOL_VERSION
    assert "tools" in r["result"]["capabilities"]
    assert r["result"]["serverInfo"]["name"] == mcp.SERVER_NAME


def test_initialize_instructions_state_the_read_only_posture():
    r = _run(mcp._handle_rpc(_rpc("initialize"), _caller(), "owner"))
    text = r["result"]["instructions"].lower()
    assert "read" in text
    assert "nothing writes" in text or "cannot do it" in text


def test_initialized_notification_gets_no_reply():
    """Notifications have no id and, per JSON-RPC, no response."""
    r = _run(mcp._handle_rpc(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}, _caller(), "owner"))
    assert r is None


def test_ping():
    r = _run(mcp._handle_rpc(_rpc("ping"), _caller(), "owner"))
    assert r["result"] == {}


def test_tools_list_shape():
    """Asserts the RPC returns what exposed_tools() says it should.

    This used to hardcode the count a second time, which meant adding one
    read verb failed in two places for one reason. The tripwire belongs in
    test_the_exposed_read_verbs_and_nothing_else, which exists to force that
    decision; here we only care that the RPC agrees with it and that the
    shape is right.
    """
    r = _run(mcp._handle_rpc(_rpc("tools/list"), _caller(), "owner"))
    tools = r["result"]["tools"]
    assert len(tools) == len(mcp.exposed_tools())
    assert {"name", "description", "inputSchema"} <= set(tools[0])


def test_unknown_method_is_method_not_found():
    r = _run(mcp._handle_rpc(_rpc("tools/destroy"), _caller(), "owner"))
    assert r["error"]["code"] == mcp.METHOD_NOT_FOUND


def test_tools_call_requires_a_name():
    r = _run(mcp._handle_rpc(_rpc("tools/call", {"arguments": {}}), _caller(), "owner"))
    assert r["error"]["code"] == mcp.INVALID_PARAMS


def test_tools_call_rejects_non_object_arguments():
    r = _run(mcp._handle_rpc(
        _rpc("tools/call", {"name": "catch_up", "arguments": "nope"}), _caller(), "owner"))
    assert r["error"]["code"] == mcp.INVALID_PARAMS


def test_forbidden_tool_returns_a_json_rpc_error():
    r = _run(mcp._handle_rpc(
        _rpc("tools/call", {"name": "send_sms", "arguments": {}}), _caller(), "owner"))
    assert r["error"]["code"] == mcp.TOOL_FORBIDDEN


def test_handler_exceptions_do_not_leak_internals(monkeypatch):
    """An untrusted caller must not learn table names, ids or query
    fragments from an error message."""
    async def _boom(name, arguments, caller):
        raise RuntimeError("relation public.contacts business_id=eq.abc123 failed")
    monkeypatch.setattr(mcp, "_call_tool", _boom)
    r = _run(mcp._handle_rpc(
        _rpc("tools/call", {"name": "catch_up", "arguments": {}}), _caller(), "owner"))
    assert r["error"]["code"] == mcp.INTERNAL_ERROR
    blob = json.dumps(r)
    for leak in ("contacts", "business_id", "abc123", "relation"):
        assert leak not in blob


# ─── dispatch bypasses the remapper ──────────────────────────────────

def test_dispatch_goes_straight_to_action_handlers(monkeypatch):
    """Proves the handler is called directly. If this ever routed through
    _execute_actions it would inherit the reasoner remap branch."""
    import chief_of_staff
    calls = []

    async def _fake_handler(client, biz, action):
        calls.append(action)
        return {"result": "ok", "label": "Caught up"}

    monkeypatch.setitem(chief_of_staff.ACTION_HANDLERS, "catch_up", _fake_handler)

    async def _fake_biz(client, caller):
        return {"id": "biz-1", "name": "Test Co"}
    monkeypatch.setattr(mcp, "_resolve_business", _fake_biz)

    allowed, ok, payload, biz_id = _run(mcp._call_tool("catch_up", {}, _caller()))
    assert allowed and ok and payload["result"] == "ok"
    assert biz_id == "biz-1", "the resolved business must reach the audit trail"
    assert calls[0]["type"] == "catch_up", "handler must receive its own verb"


def test_arguments_cannot_override_the_verb(monkeypatch):
    """`type` is set AFTER the caller's arguments are copied in, so a
    caller cannot smuggle a different verb through the arguments object."""
    import chief_of_staff
    seen = {}

    async def _fake_handler(client, biz, action):
        seen.update(action)
        return {"result": "ok", "label": "x"}

    monkeypatch.setitem(chief_of_staff.ACTION_HANDLERS, "catch_up", _fake_handler)

    async def _fake_biz(client, caller):
        return {"id": "biz-1"}
    monkeypatch.setattr(mcp, "_resolve_business", _fake_biz)

    _run(mcp._call_tool("catch_up", {"type": "send_sms", "message": "hi"}, _caller()))
    assert seen["type"] == "catch_up", "the caller must not be able to rewrite `type`"


def test_no_business_resolved_is_a_refusal_not_a_crash(monkeypatch):
    async def _none(client, caller):
        return None
    monkeypatch.setattr(mcp, "_resolve_business", _none)
    allowed, ok, msg, biz_id = _run(mcp._call_tool("catch_up", {}, _caller()))
    assert ok is False and "business" in msg
    assert allowed is True, (
        "authorization PASSED — it failed at resolution. Conflating the two "
        "would make a config problem look like an attack in the audit trail.")
    assert biz_id is None


# ─── the limiter fails closed ────────────────────────────────────────

def test_mcp_bucket_exists_and_is_tighter_than_chief():
    assert "mcp" in rate_limit._LIMITS
    mcp_max, _ = rate_limit._LIMITS["mcp"]
    chief_max, _ = rate_limit._LIMITS["chief"]
    assert mcp_max <= chief_max


def test_allow_strict_fails_closed(monkeypatch):
    """Every other bucket fails OPEN — right for a practitioner, wrong for
    an agent that may be looping or holding a stolen credential."""
    def _boom(bucket, key):
        raise RuntimeError("limiter exploded")
    monkeypatch.setattr(rate_limit, "_check", _boom)
    assert rate_limit.allow_strict("mcp", "someone") is False
    assert rate_limit.allow("chief", "someone") is True, (
        "the practitioner buckets must keep failing open")


def test_allow_strict_still_enforces_the_limit(monkeypatch):
    monkeypatch.setattr(rate_limit, "_LIMITS", {**rate_limit._LIMITS, "mcp": (2, 60)})
    rate_limit._buckets.clear()
    assert rate_limit.allow_strict("mcp", "k") is True
    assert rate_limit.allow_strict("mcp", "k") is True
    assert rate_limit.allow_strict("mcp", "k") is False


# ─── audit ───────────────────────────────────────────────────────────

def test_audit_records_argument_names_never_values(caplog):
    """An audit trail must not become a second copy of the data it audits."""
    import logging
    with caplog.at_level(logging.INFO, logger="mcp_server"):
        mcp._audit(actor="owner", tool="recall_conversation", ok=True,
                   duration_ms=12, business_id="biz-1",
                   arg_keys=["query"])
    assert "recall_conversation" in caplog.text
    assert "query" in caplog.text


def test_every_tools_call_is_audited(monkeypatch, caplog):
    import logging
    async def _ok(name, arguments, caller):
        return True, {"result": "ok", "label": "x"}
    monkeypatch.setattr(mcp, "_call_tool", _ok)
    with caplog.at_level(logging.INFO, logger="mcp_server"):
        _run(mcp._handle_rpc(
            _rpc("tools/call", {"name": "catch_up", "arguments": {}}), _caller(), "owner"))
    assert "[audit]" in caplog.text


def test_refusals_are_audited_too(caplog):
    """A refused call is the one you most want a record of."""
    import logging
    with caplog.at_level(logging.INFO, logger="mcp_server"):
        _run(mcp._handle_rpc(
            _rpc("tools/call", {"name": "send_sms", "arguments": {}}), _caller(), "owner"))
    assert "[audit]" in caplog.text and "ok=False" in caplog.text


# ─── kill switch ─────────────────────────────────────────────────────

def test_kill_switch(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "off")
    assert mcp.enabled() is False
    monkeypatch.setenv("MCP_ENABLED", "on")
    assert mcp.enabled() is True


# ─── agent_runs (Build 2) ────────────────────────────────────────────

def _capture_rows(monkeypatch):
    """Intercept the agent_runs write."""
    rows = []
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda path, body, prefer=None: rows.append((path, body)))
    return rows


def test_audit_writes_an_agent_runs_row(monkeypatch):
    rows = _capture_rows(monkeypatch)
    mcp._audit(actor="owner@x.com", actor_user_id="u1", tool="catch_up",
               allowed=True, ok=True, duration_ms=42, business_id="biz-1",
               arg_keys=["limit"])
    assert len(rows) == 1
    path, body = rows[0]
    assert path == "/agent_runs"
    assert body["tool"] == "catch_up" and body["surface"] == "mcp"
    assert body["allowed"] is True and body["ok"] is True
    assert body["business_id"] == "biz-1" and body["actor_user_id"] == "u1"
    assert body["arg_keys"] == ["limit"]


def test_audit_never_records_argument_values(monkeypatch):
    """The property the table exists to protect. An audit trail that stores
    values becomes a second copy of the data it audits — held longer, under
    weaker scrutiny, and outside every deletion path."""
    rows = _capture_rows(monkeypatch)
    mcp._audit(actor="owner@x.com", tool="recall_conversation", allowed=True,
               ok=True, duration_ms=5, arg_keys=["query"])
    body = rows[0][1]
    assert body["arg_keys"] == ["query"]
    blob = json.dumps(body)
    assert "SECRET" not in blob
    # arg_keys is text[], not jsonb — there is nowhere convenient to put a
    # value even by accident.
    assert isinstance(body["arg_keys"], list)
    assert all(isinstance(k, str) for k in body["arg_keys"])


def test_audit_distinguishes_refused_from_failed(monkeypatch):
    """`allowed` and `ok` answer different questions. Collapsing them would
    lose the distinction a reader of this table most needs."""
    rows = _capture_rows(monkeypatch)
    mcp._audit(actor="a", tool="send_sms", allowed=False, ok=False, duration_ms=1)
    mcp._audit(actor="a", tool="catch_up", allowed=True, ok=False, duration_ms=9)
    refused, failed = rows[0][1], rows[1][1]
    assert refused["allowed"] is False and refused["ok"] is False
    assert failed["allowed"] is True and failed["ok"] is False


def test_audit_truncates_error_text(monkeypatch):
    """A reason, not a traceback — exception text here routinely carries
    table names, ids and query fragments."""
    rows = _capture_rows(monkeypatch)
    mcp._audit(actor="a", tool="catch_up", allowed=True, ok=False,
               duration_ms=1, error="x" * 2000)
    assert len(rows[0][1]["error"]) <= 300


def test_audit_failure_is_never_fatal(monkeypatch, caplog):
    """An audit write that could take down the surface it audits would be a
    worse bug than the one it guards against."""
    import logging, sb_clients
    def _boom(*a, **k):
        raise RuntimeError("supabase down")
    monkeypatch.setattr(sb_clients, "sb_post_as_service", _boom)
    with caplog.at_level(logging.INFO, logger="mcp_server"):
        mcp._audit(actor="a", tool="catch_up", allowed=True, ok=True, duration_ms=1)
    assert "[audit]" in caplog.text, "the log line must land even when the DB write fails"
    assert "non-fatal" in caplog.text


def test_endpoint_refusals_are_recorded(monkeypatch):
    """A non-owner reaching this endpoint and a caller hitting the limiter
    both happen BEFORE a tool is named. They used to leave no trace, and
    they are the two rows most worth having."""
    rows = _capture_rows(monkeypatch)
    mcp._audit(actor="stranger@x.com", tool="(endpoint)", allowed=False,
               ok=False, duration_ms=0, error="non-owner caller")
    body = rows[0][1]
    assert body["allowed"] is False
    assert body["tool"] == "(endpoint)"
    assert body["business_id"] is None, "no business is resolved before refusal"


def test_migration_declares_arg_keys_as_text_array():
    """text[] not jsonb, so a value has nowhere convenient to go."""
    sql = pathlib.Path(__file__).resolve().parent.parent.joinpath(
        "supabase/APPLY-2026-07-28-agent-runs.sql").read_text(encoding="utf-8")
    ddl = "\n".join(line.split("--")[0] for line in sql.splitlines())
    table = ddl.split("CREATE TABLE IF NOT EXISTS public.agent_runs")[1].split(");")[0]
    assert "arg_keys      text[]" in table or "arg_keys text[]" in table.replace("  ", " ")
    assert "allowed" in table and "ok" in table


def test_migration_has_rls_on_and_no_policies():
    sql = pathlib.Path(__file__).resolve().parent.parent.joinpath(
        "supabase/APPLY-2026-07-28-agent-runs.sql").read_text(encoding="utf-8")
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "CREATE POLICY" not in sql, "service-role only, like the table it models"


def test_migration_revokes_the_table_grants():
    """RLS-with-no-policies is a consequence of absence; a revoked grant is
    a decision.

    Supabase grants SELECT on public tables to anon/authenticated by
    default. With RLS on and no policies those roles get zero rows — safe
    today, but only because no policy exists. Add one permissive policy
    later, for any reason, and the standing grant makes it public in the
    same breath. restricted_module_access_log revokes; so must this."""
    sql = pathlib.Path(__file__).resolve().parent.parent.joinpath(
        "supabase/APPLY-2026-07-28-agent-runs.sql").read_text(encoding="utf-8")
    ddl = "\n".join(line.split("--")[0] for line in sql.splitlines())
    assert "REVOKE ALL ON public.agent_runs FROM anon, authenticated" in ddl
    # Found while verifying agent_runs: Feed 2's table had the same gap.
    assert "REVOKE ALL ON public.vertical_knowledge FROM anon, authenticated" in ddl
