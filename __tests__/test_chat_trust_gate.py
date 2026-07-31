"""
test_chat_trust_gate.py — the class-C gate on the live chat path, and the
failure-detection seam it depends on.

WHAT WAS BROKEN
  1. _execute_actions ran ANY verb the first-pass LLM emitted without ever
     consulting action_registry — the registry was enforced at the MCP
     surface and the autopilot import guard, never in chat.
  2. _action_failed tested startswith("Failed:") while real emitters said
     "failed: …", "couldn't undo …", "error: …" — and _fail() itself had
     dropped the prefix entirely (Arc 4 voice pass) — so failed actions
     were audited (ok=true) and narrated as successes.
  3. The two check_module_scope guards failed OPEN.

Every test here asserts on observable behavior: which handlers ran, what
rows would have been written, what the returned dicts contain. Nothing
asserts against comments or prose.
"""
import asyncio

import pytest

import action_registry
import chief_of_staff as cos
import chief_undo_actions


def _biz(autopilot=None):
    settings = {}
    if autopilot is not None:
        settings["autopilot"] = autopilot
    return {"id": "biz-1", "owner_id": "user-1", "name": "Test Biz",
            "type": "coach", "settings": settings}


def _sb_recorder(routes=None):
    """A fake chief_of_staff._sb that records calls and answers from a
    {prefix: response} table (first matching prefix wins)."""
    calls = []

    async def fake_sb(client, method, path, body=None):
        calls.append((method, path, body))
        for (m, prefix), resp in (routes or {}).items():
            if method == m and path.startswith(prefix):
                return resp(body) if callable(resp) else resp
        return []

    return fake_sb, calls


# ─────────────────────────────────────────────────────────────────────
# The gate: bulk class-C queues under manual autopilot
# ─────────────────────────────────────────────────────────────────────

def test_batch_email_queues_drafts_under_manual_autopilot(monkeypatch):
    fake_sb, calls = _sb_recorder({
        ("GET", "/contacts"): [
            {"id": "c1", "name": "Ann", "email": "ann@x.com"},
            {"id": "c2", "name": "Bo", "email": "bo@x.com"},
        ],
        ("POST", "/agent_queue"): lambda body: [{"id": f"q{i}"} for i in range(len(body))],
    })
    monkeypatch.setattr(cos, "_sb", fake_sb)

    async def must_not_run(client, biz, action):
        raise AssertionError("batch_email handler must not execute under manual autopilot")
    monkeypatch.setitem(cos.ACTION_HANDLERS, "batch_email", must_not_run)

    out = asyncio.run(cos._execute_actions(None, _biz({"overall": "manual"}), [{
        "type": "batch_email", "contact_ids": ["c1", "c2"],
        "subject": "Hi {contact_name}", "body": "News from {business_name}",
    }]))

    assert len(out) == 1
    r = out[0]
    # IRONCLAD shape: both keys present, and this is a success (a queued
    # draft is the intended outcome, not a failure).
    assert isinstance(r.get("result"), str) and r.get("label")
    assert not cos._action_failed(r)
    assert "queued" in r["result"].lower()

    posts = [b for (m, p, b) in calls if m == "POST" and p.startswith("/agent_queue")]
    assert len(posts) == 1
    rows = posts[0]
    assert len(rows) == 2
    assert all(row["status"] == "draft" for row in rows)          # ApprovalQueue reads these
    assert all(row["business_id"] == "biz-1" for row in rows)
    assert rows[0]["subject"] == "Hi Ann"                          # personalization preserved
    assert "News from Test Biz" in rows[0]["body"]


def test_batch_email_executes_under_full_autopilot(monkeypatch):
    fake_sb, _calls = _sb_recorder()
    monkeypatch.setattr(cos, "_sb", fake_sb)

    ran = {}

    async def stub(client, biz, action):
        ran["called"] = True
        return {"type": "batch_email", "result": "sent 2 of 2",
                "label": "Batch email", "nav": None}
    monkeypatch.setitem(cos.ACTION_HANDLERS, "batch_email", stub)

    out = asyncio.run(cos._execute_actions(
        None, _biz({"per_team": {"nurture": "full"}}), [{
            "type": "batch_email", "contact_ids": ["c1", "c2"],
            "subject": "Hi", "body": "Hello there",
        }]))

    assert ran.get("called") is True
    assert out[0]["result"] == "sent 2 of 2"


def test_bulk_approve_refused_under_manual_autopilot(monkeypatch):
    fake_sb, _calls = _sb_recorder()
    monkeypatch.setattr(cos, "_sb", fake_sb)

    async def must_not_run(client, biz, action):
        raise AssertionError("bulk_approve must not execute under manual autopilot")
    monkeypatch.setitem(cos.ACTION_HANDLERS, "bulk_approve", must_not_run)

    out = asyncio.run(cos._execute_actions(None, _biz(), [
        {"type": "bulk_approve", "filter": "all"},
    ]))

    r = out[0]
    assert cos._action_failed(r)
    assert r["result"].startswith("Failed:")
    assert r.get("label")
    # It points at the surface built for this.
    assert "approval queue" in (r["result"] + r["label"]).lower()


def test_bulk_approve_executes_under_full_autopilot(monkeypatch):
    fake_sb, _calls = _sb_recorder()
    monkeypatch.setattr(cos, "_sb", fake_sb)

    ran = {}

    async def stub(client, biz, action):
        ran["called"] = True
        return {"type": "bulk_approve", "result": "approved 3 of 3",
                "label": "Bulk approved", "nav": None}
    monkeypatch.setitem(cos.ACTION_HANDLERS, "bulk_approve", stub)

    out = asyncio.run(cos._execute_actions(None, _biz({"overall": "full"}), [
        {"type": "bulk_approve", "filter": "all"},
    ]))
    assert ran.get("called") is True
    assert out[0]["result"] == "approved 3 of 3"


# ─────────────────────────────────────────────────────────────────────
# Single-target class C stays immediate; class A is never gated
# ─────────────────────────────────────────────────────────────────────

def test_single_target_class_c_executes_immediately(monkeypatch):
    fake_sb, _calls = _sb_recorder()
    monkeypatch.setattr(cos, "_sb", fake_sb)

    ran = {}

    async def stub(client, biz, action):
        ran["called"] = True
        return {"type": "send_sms", "result": "sent", "label": "SMS", "nav": None}
    monkeypatch.setitem(cos.ACTION_HANDLERS, "send_sms", stub)

    out = asyncio.run(cos._execute_actions(None, _biz(), [
        {"type": "send_sms", "contact_id": "c1", "message": "hi"},
    ]))
    assert ran.get("called") is True
    assert out[0]["result"] == "sent"


def test_class_c_per_turn_cap(monkeypatch):
    fake_sb, _calls = _sb_recorder()
    monkeypatch.setattr(cos, "_sb", fake_sb)

    count = {"n": 0}

    async def sms_stub(client, biz, action):
        count["n"] += 1
        return {"type": "send_sms", "result": "sent", "label": "SMS", "nav": None}
    monkeypatch.setitem(cos.ACTION_HANDLERS, "send_sms", sms_stub)

    note_ran = {}

    async def note_stub(client, biz, action):
        note_ran["called"] = True
        return {"type": "create_note", "result": "noted", "label": "Note", "nav": None}
    monkeypatch.setitem(cos.ACTION_HANDLERS, "create_note", note_stub)

    actions = [{"type": "send_sms", "contact_id": f"c{i}", "message": "hi"}
               for i in range(4)]
    actions.append({"type": "create_note", "content": "x"})

    out = asyncio.run(cos._execute_actions(None, _biz(), actions))

    assert count["n"] == cos.CLASS_C_TURN_CAP == 3     # only 3 of the 4 ran
    fourth = out[3]
    assert cos._action_failed(fourth)
    assert fourth["result"].startswith("Failed:")
    assert fourth.get("label")
    # The cap is for SENSITIVE verbs only — class A still runs afterward.
    assert note_ran.get("called") is True
    assert out[4]["result"] == "noted"


# ─────────────────────────────────────────────────────────────────────
# Fail CLOSED
# ─────────────────────────────────────────────────────────────────────

def test_gate_fails_closed_when_registry_lookup_raises(monkeypatch):
    fake_sb, _calls = _sb_recorder()
    monkeypatch.setattr(cos, "_sb", fake_sb)

    def boom(verb):
        raise RuntimeError("registry down")
    monkeypatch.setattr(action_registry, "classification", boom)

    ran = {}

    async def stub(client, biz, action):
        ran["called"] = True
        return {"type": "send_sms", "result": "sent", "label": "SMS", "nav": None}
    monkeypatch.setitem(cos.ACTION_HANDLERS, "send_sms", stub)

    out = asyncio.run(cos._execute_actions(None, _biz({"overall": "full"}), [
        {"type": "send_sms", "contact_id": "c1", "message": "hi"},
    ]))

    assert "called" not in ran                      # nothing executed
    r = out[0]
    assert cos._action_failed(r)
    assert r["result"].startswith("Failed:")
    assert r.get("label")


def test_gate_fails_closed_on_registry_drift(monkeypatch):
    """A verb with a live handler but NO registry entry is held, not run
    (default-deny, same doctrine as the registry's own accessors)."""
    fake_sb, _calls = _sb_recorder()
    monkeypatch.setattr(cos, "_sb", fake_sb)

    monkeypatch.setattr(action_registry, "classification", lambda verb: None)

    async def stub(client, biz, action):
        raise AssertionError("an unclassified verb must not execute")
    monkeypatch.setitem(cos.ACTION_HANDLERS, "send_sms", stub)

    out = asyncio.run(cos._execute_actions(None, _biz(), [
        {"type": "send_sms", "contact_id": "c1", "message": "hi"},
    ]))
    assert cos._action_failed(out[0])
    assert out[0]["result"].startswith("Failed:")
    assert out[0].get("label")


# ─────────────────────────────────────────────────────────────────────
# _action_failed accepts every real failure spelling
# ─────────────────────────────────────────────────────────────────────

def test_action_failed_accepts_all_failure_spellings():
    assert cos._action_failed({"result": "Failed: nope"})
    assert cos._action_failed({"result": "failed: nope"})                 # old undo _fail
    assert cos._action_failed({"result": "couldn't undo “create_note” — x"})
    assert cos._action_failed({"result": "error: boom"})                  # old record_edit_pattern
    # _fail()'s friendly copy carries the machine flag instead of a prefix.
    assert cos._action_failed(
        {"result": "I couldn't complete that just now — try again in a moment.",
         "failed": True})


def test_action_failed_rejects_successes():
    assert not cos._action_failed({"result": "queued 3 drafts for approval"})
    assert not cos._action_failed({"result": "Sent to a@b.c (PDF)", "ok": True})
    assert not cos._action_failed({"result": "sent 5 of 5"})
    assert not cos._action_failed({"result": "observed"})
    assert not cos._action_failed({})
    assert not cos._action_failed(None)


def test_fail_helper_is_detected_as_failure():
    """The real _fail() output — the ~40-call-site seam — must register as
    a failure even though its visible copy has no 'Failed:' prefix."""
    r = cos._fail("update_offering", "patch failed: boom")
    assert cos._action_failed(r)
    assert r.get("label")
    # The voice rule survives: no raw technicals in the visible copy.
    assert "boom" not in r["result"]


def test_undo_fail_emits_capital_failed_prefix():
    r = chief_undo_actions._fail("undo_last", "no handler for the inverse")
    assert r["result"].startswith("Failed:")
    assert cos._action_failed(r)
    assert r.get("label")


def test_failed_undo_reports_failure_and_stays_undoable(monkeypatch):
    """The audited bug: a failed inverse used to come back as 'couldn't
    undo …' which startswith('Failed:') missed → ok=true in audit_log and
    a success narration. Now it must read as a failure AND leave the
    undo-log row untouched."""
    async def fake_recent(client, biz):
        return {"id": "row-1", "action_type": "create_note",
                "action_json": {}, "result_json": {}}
    monkeypatch.setattr(chief_undo_actions, "_most_recent", fake_recent)
    monkeypatch.setattr(chief_undo_actions.action_inverse, "build_inverse",
                        lambda verb, a, r: {"type": "forget", "target": "x"})

    async def failing_inverse(client, biz, action):
        return cos._fail("forget", "delete failed: 500")
    monkeypatch.setitem(cos.ACTION_HANDLERS, "forget", failing_inverse)

    fake_sb, calls = _sb_recorder()
    monkeypatch.setattr(cos, "_sb", fake_sb)

    out = asyncio.run(chief_undo_actions.handle_undo_last(None, _biz(), {}))

    assert out["result"].startswith("Failed:")
    assert cos._action_failed(out)
    assert out.get("label")
    # The row was NOT marked undone.
    assert not [c for c in calls if c[0] == "PATCH"]


# ─────────────────────────────────────────────────────────────────────
# Scope guards fail CLOSED
# ─────────────────────────────────────────────────────────────────────

def test_ensure_module_scope_guard_fails_closed(monkeypatch):
    import vertical_scope

    def boom(*a, **k):
        raise RuntimeError("scope service down")
    monkeypatch.setattr(vertical_scope, "check_module_scope", boom)

    fake_sb, calls = _sb_recorder()
    monkeypatch.setattr(cos, "_sb", fake_sb)

    out = asyncio.run(cos.handle_ensure_module(None, _biz(), {
        "module_name": "Clinical Notes",
    }))

    assert out["result"].startswith("Failed:")
    assert cos._action_failed(out)
    assert out.get("label")
    assert not calls          # no lookup, no create — nothing touched the DB


def test_accept_module_spec_scope_guard_fails_closed(monkeypatch):
    import sb_clients

    def boom(*a, **k):
        raise RuntimeError("spec fetch down")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", boom)

    import module_spec_generator

    def must_not_materialize(*a, **k):
        raise AssertionError("materialize_spec must not run when the guard can't")
    monkeypatch.setattr(module_spec_generator, "materialize_spec", must_not_materialize)

    out = asyncio.run(cos.handle_accept_module_spec(None, _biz(), {
        "spec_id": "spec-1",
    }))

    assert out["result"].startswith("Failed:")
    assert cos._action_failed(out)
    assert out.get("label")


# ─── every action module's _fail carries the machine-readable flag ────

def test_all_fail_helpers_carry_failed_flag():
    """The verification audit found two _fail helpers (bookkeeping,
    contract) that never got the "failed": True seam — their failures
    were narrated and audited as successes. This sweeps every
    chief_*_actions module so a new one can't ship without the flag."""
    import importlib, pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    mods = sorted(p.stem for p in root.glob("chief_*_actions.py"))
    assert mods, "no chief action modules found"
    missing = []
    for name in mods:
        mod = importlib.import_module(name)
        fail = getattr(mod, "_fail", None)
        if fail is None:
            continue  # module has no local failure helper
        out = fail("probe_verb", "probe message")
        if out.get("failed") is not True and not str(
            out.get("result", "")
        ).lower().startswith(("failed:", "couldn't ", "error:")):
            missing.append(name)
    assert not missing, f"_fail without detectable failure marker: {missing}"
