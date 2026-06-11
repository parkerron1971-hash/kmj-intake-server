"""Arc 20 Phase B PR1 — cache-split system prompt + Tier 1 rules engine +
the rule→proposal convergence."""
from __future__ import annotations

import sys
import pathlib
from datetime import datetime, timezone, timedelta

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import rules_engine as re_  # noqa: E402
import rules_router as rr  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


def _u(uid="owner1"):
    return type("U", (), {"id": uid})()


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    monkeypatch.delenv("RULES_ENGINE", raising=False)
    fb.rows("businesses").append({"id": "b1", "owner_id": "owner1", "name": "Biz",
                                  "settings": {}})
    return fb


def _rule(fb, **over):
    r = {"id": "r1", "business_id": "b1", "name": "Welcome new clients",
         "rationale": "every new contact gets tagged + I get notified",
         "enabled": True, "trigger_type": "contact_created",
         "trigger_config": {}, "conditions": [], "version": 1,
         "actions": [{"verb": "apply_tag", "params": {"tag": "new-client"}},
                     {"verb": "notify_practitioner",
                      "params": {"message": "New contact: {{name}}"}}]}
    r.update(over)
    fb.rows("practitioner_rules").append(r)
    return r


# ─── Cache split (Part 1) ────────────────────────────────────────────

def test_system_prompt_splits_stable_then_dynamic():
    import chief_of_staff as cos
    ctx = {"business": {"id": "b1", "name": "Biz",
                        "settings": {"practitioner_name": "Kevin"},
                        "voice_profile": {}},
           "queue": [], "sessions": [], "events": [], "insights": [],
           "modules": [], "module_counts": {}, "at_risk": [],
           "contacts_lookup": [], "contacts": [], "invoices": [],
           "products": [], "memories": [], "notifications": [],
           "contacts_total": 0, "emails_recent": [], "email_replies": [],
           "auto_recent": [], "payments": [], "agent_drafts": [],
           "bookings": [], "tasks": [], "goals": []}
    import collections
    ctx = collections.defaultdict(lambda: [], ctx)   # absorb future ctx keys
    s1 = cos._build_system_prompt(ctx, False, session_context="STATE A")
    s2 = cos._build_system_prompt(ctx, False, session_context="STATE B")
    assert "[[CHIEF_CACHE_SPLIT]]" in s1
    stable1 = s1.split("[[CHIEF_CACHE_SPLIT]]")[0]
    stable2 = s2.split("[[CHIEF_CACHE_SPLIT]]")[0]
    # THE quality gate: the cacheable prefix is byte-identical across calls
    # with different dynamic state, and the state lives in the tail.
    assert stable1 == stable2
    assert "STATE A" in s1.split("[[CHIEF_CACHE_SPLIT]]")[1]
    assert "STATE A" not in stable1
    # The stable prefix carries the heavy operating manual (the token win).
    assert "YOU ARE THE CENTRAL ORCHESTRATOR" in stable1
    assert len(stable1) > len(s1.split("[[CHIEF_CACHE_SPLIT]]")[1])


# ─── Validation (closed grammar) ─────────────────────────────────────

def test_validate_rejects_outside_grammar():
    bad = {"name": "x", "rationale": "y", "trigger_type": "rm_rf",
           "conditions": [{"field": "a", "op": "regex", "value": ".*"}],
           "actions": [{"verb": "execute_code", "params": {}}]}
    errs = re_.validate_rule(bad)
    assert any("Unknown trigger" in e for e in errs)
    assert any("Unknown condition operator" in e for e in errs)
    assert any("Unknown action" in e for e in errs)
    # Unknown PARAMS are rejected too (no forward-smuggling).
    sneaky = {"name": "x", "rationale": "y", "trigger_type": "contact_created",
              "conditions": [],
              "actions": [{"verb": "apply_tag",
                           "params": {"tag": "ok", "sql": "DROP TABLE"}}]}
    assert any("unknown parameter" in e for e in re_.validate_rule(sneaky))
    # Rationale is mandatory (trust layer).
    no_why = {"name": "x", "rationale": "", "trigger_type": "contact_created",
              "conditions": [], "actions": [{"verb": "apply_tag", "params": {"tag": "t"}}]}
    assert any("audit answer" in e for e in re_.validate_rule(no_why))


# ─── Execution + audit ───────────────────────────────────────────────

def test_rule_fires_executes_and_logs(fake):
    fb = fake
    _rule(fb)
    fb.rows("contacts").append({"id": "c9", "business_id": "b1", "name": "Sarah",
                                "tags": []})
    out = re_.on_event("b1", "contact_created",
                       {"contact_id": "c9", "name": "Sarah",
                        "contact_email": "s@x.com"})
    assert out and out[0]["status"] == "executed"
    assert fb.rows("contacts")[0]["tags"] == ["new-client"]
    notif = fb.rows("chief_notifications")[0]
    assert notif["body"] == "New contact: Sarah"          # data-only interpolation
    run = fb.rows("rule_runs")[0]
    assert run["status"] == "executed" and run["event_type"] == "contact_created"
    assert run["rule_id"] == "r1"                          # audit: which rule, why


def test_conditions_gate_and_trace(fake):
    fb = fake
    _rule(fb, conditions=[{"field": "source", "op": "equals", "value": "website"}])
    out = re_.on_event("b1", "contact_created",
                       {"contact_id": "c1", "name": "X", "source": "referral"})
    assert out[0]["status"] == "skipped_conditions"
    trace = fb.rows("rule_runs")[0]["condition_trace"]
    assert trace[0]["matched"] is False and trace[0]["actual"] == "referral"


def test_kill_switches(fake, monkeypatch):
    fb = fake
    _rule(fb)
    # Business pause.
    fb.rows("businesses")[0]["settings"] = {"automations_paused": True}
    assert re_.on_event("b1", "contact_created", {"name": "X"}) == []
    fb.rows("businesses")[0]["settings"] = {}
    # Platform kill switch.
    monkeypatch.setenv("RULES_ENGINE", "off")
    assert re_.on_event("b1", "contact_created", {"name": "X"}) == []


def test_cross_business_unrepresentable(fake):
    """A rule in b1 acting on a contact id that belongs to ANOTHER business
    must not touch it — the executor pins business_id in the query."""
    fb = fake
    _rule(fb, actions=[{"verb": "apply_tag", "params": {"tag": "stolen"}}])
    fb.rows("contacts").append({"id": "cx", "business_id": "OTHER", "name": "Vic",
                                "tags": []})
    out = re_.on_event("b1", "contact_created", {"contact_id": "cx", "name": "Vic"})
    assert out[0]["status"] == "executed_with_errors"
    assert fb.rows("contacts")[0]["tags"] == []            # untouched


# ─── Convergence: rule action = Chief proposal ───────────────────────

def test_proposal_verb_lands_in_chief_proposals_and_approval_executes(fake):
    fb = fake
    _rule(fb, actions=[{"verb": "propose_contact_tag", "params": {"tag": "vip"}}])
    fb.rows("contacts").append({"id": "c9", "business_id": "b1", "name": "Sarah",
                                "tags": []})
    re_.on_event("b1", "contact_created", {"contact_id": "c9", "name": "Sarah"})
    props = fb.rows("chief_proposals")
    assert len(props) == 1
    p = props[0]
    assert p["proposal_type"] == "propose_contact_tag"
    assert p["source"] == "rule:r1"                        # provenance
    assert p["status"] == "pending"
    assert fb.rows("contacts")[0]["tags"] == []            # NOT executed yet
    # Approval through the generic proposals surface executes it + captures
    # the learning signal (same flow as Chief's own proposals).
    out = rr.approve(p["id"], rr.ResolveBody(business_id="b1"), _u())
    assert out["ok"] and out["result"]["ok"]
    assert fb.rows("contacts")[0]["tags"] == ["vip"]
    assert fb.rows("chief_proposals")[0]["status"] == "approved"
    assert fb.rows("chief_learning_signals")[0]["override_reason"] == "approved"


def test_chain_depth_and_self_retrigger_guard(fake):
    fb = fake
    _rule(fb)
    # Depth at the cap → nothing runs.
    assert re_.on_event("b1", "contact_created", {"name": "X"},
                        _provenance={"depth": 3}) == []
    # An event whose provenance is THIS rule never re-triggers it.
    out = re_.on_event("b1", "contact_created", {"name": "X"},
                       _provenance={"origin_rule": "r1", "depth": 1})
    assert out == []


# ─── Router CRUD + dry run ───────────────────────────────────────────

def test_router_create_validates_and_dry_run_previews(fake):
    fb = fake
    body = rr.RuleBody(name="Overdue nudge", rationale="chase overdue invoices",
                       trigger_type="invoice_overdue",
                       trigger_config={"days_overdue": 14},
                       conditions=[{"field": "total", "op": "greater_than", "value": 100}],
                       actions=[{"verb": "propose_followup_email",
                                 "params": {"subject": "Invoice {{invoice_number}}",
                                            "body": "Hi {{contact_name}} — gentle nudge."}}])
    out = rr.create_rule("b1", body, _u())
    assert out["ok"] and out["rule"]["trigger_type"] == "invoice_overdue"
    with pytest.raises(HTTPException):
        rr.create_rule("b1", rr.RuleBody(name="", rationale="", trigger_type="nope",
                                         actions=[]), _u())
    test = rr.dry_run("b1", rr.TestBody(
        rule=body.model_dump(),
        sample_event={"invoice_number": "INV-7", "total": 250,
                      "contact_name": "Sam"}), _u())
    assert test["would_fire"] is True
    assert test["action_preview"][0]["rendered_params"]["subject"] == "Invoice INV-7"
    with pytest.raises(HTTPException):
        rr.list_rules("b1", _u("intruder"))


def test_overdue_tick_fires_for_window(fake):
    fb = fake
    _rule(fb, trigger_type="invoice_overdue", trigger_config={"days_overdue": 7},
          actions=[{"verb": "notify_practitioner",
                    "params": {"message": "{{invoice_number}} is {{days_overdue}}d overdue"}}])
    due = (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()
    fb.rows("invoices").append({"id": "i1", "business_id": "b1", "paid_at": None,
                                "status": "sent", "due_date": due,
                                "invoice_number": "INV-9", "total": 300,
                                "contact_id": "c1",
                                "contacts": {"name": "Sam", "email": "sam@x.com"}})
    import asyncio
    asyncio.run(re_.overdue_tick())
    assert fb.rows("chief_notifications")[0]["body"] == "INV-9 is 7d overdue"
