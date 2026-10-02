"""An imported unsubscribe HOLDS on every bulk or automated email path.

The client-list import records `contacts.metadata.email_opt_out` when an
old tool's export says someone unsubscribed, was cleaned or bounced, or
said no to marketing. Recording it is worthless unless every sender that
mails a business's contacts in bulk or on its own asks
contact_fields.email_opted_out() first:

  • Chief's batch_email            — the opted-out contact is left out, named in the result
  • rules automations              — skipped, reason in rule_runs; a failed check holds the mail
  • a rule proposal a person approves — sent (their choice), with a note
  • autopilot                      — a nurture/growth draft to them is held for review
  • the nurture + growth sweeps    — no re-engagement draft is even written
  • a one-to-one email Chief drafts — not blocked; the draft and label say so

Transactional mail (receipts, invoices, confirmations, documents) does not
ask. Campaigns are covered in test_contact_import_fidelity.py.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import contact_fields as cf  # noqa: E402

BIZ = {"id": "biz1", "name": "Northside Cuts", "owner_id": "u1", "settings": {}}
OUT = {"email_opt_out": {"reason": "unsubscribed", "source": "import:file"}}
DANA = {"id": "c-dana", "name": "Dana", "email": "dana@x.com", "metadata": OUT}
MARCUS = {"id": "c-marcus", "name": "Marcus", "email": "marcus@x.com", "metadata": {}}


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def resend(monkeypatch):
    """Every email send, recorded instead of made."""
    import email_sender
    sent = []

    async def _send(**kw):
        sent.append(kw["to_email"])
        return {"id": f"re_{len(sent)}"}

    monkeypatch.setattr(email_sender, "send_via_resend", _send)
    monkeypatch.setattr(email_sender, "build_routed_reply_to", lambda b, c: None)
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    return sent


# ─── the one predicate ───────────────────────────────────────────────

def test_the_predicate_reads_the_imported_record_and_nothing_else():
    assert cf.email_opted_out(DANA) == "unsubscribed"
    assert cf.email_opted_out(MARCUS) is None
    assert cf.email_opted_out({"id": "x", "email": "a@x.com"}) is None   # read without metadata
    assert cf.email_opted_out({"metadata": {"email_opt_out": True}}) == "unsubscribed"
    assert cf.sms_opted_out({"metadata": {"sms_opt_out": {"reason": "texted STOP"}}}) == "texted STOP"


# ─── Chief's batch_email ─────────────────────────────────────────────

def test_batch_email_leaves_out_someone_who_unsubscribed(monkeypatch, resend):
    import chief_of_staff as cos
    selects = []

    async def _sb(client, method, path, body=None):
        if method == "GET" and path.startswith("/contacts"):
            selects.append(path)
            return [dict(DANA), dict(MARCUS), {"id": "c-kim", "name": "Kim", "email": "", "metadata": {}}]
        return []

    monkeypatch.setattr(cos, "_sb", _sb)
    res = _run(cos.handle_batch_email(None, BIZ, {
        "contact_ids": ["c-dana", "c-marcus", "c-kim"],
        "subject": "Spring special", "body": "Hi {contact_name}, 20% off this week."}))
    assert resend == ["marcus@x.com"], "the unsubscribed contact must not be mailed"
    assert "metadata" in selects[0], "a row read without metadata reads as mailable"
    assert res["sent_count"] == 1 and res["unsubscribed_count"] == 1
    assert res["unsubscribed"] == ["Dana"]
    assert "unsubscribed" in res["label"] and "unsubscribed" in res["result"]


# ─── rules automations ──────────────────────────────────────────────

RULE = {"id": "r1", "name": "Thank-you after booking", "version": 1, "conditions": [],
        "actions": [{"verb": "send_template_email",
                     "params": {"subject": "Thanks {contact_name}", "body": "See you soon"}}]}


@pytest.fixture
def rules_db(monkeypatch):
    import sb_clients
    state = {"contacts": [dict(DANA), dict(MARCUS)], "runs": [], "fail_contacts": False}

    def get(path):
        if path.startswith("/businesses"):
            return [{"id": "biz1", "name": "Northside Cuts"}]
        if path.startswith("/contacts"):
            if state["fail_contacts"]:
                return None
            if "id=eq.c-dana" in path:
                return [state["contacts"][0]]
            if "id=eq.c-marcus" in path:
                return [state["contacts"][1]]
            return []
        return []

    def post(path, body, prefer=None):
        if path.startswith("/rule_runs"):
            state["runs"].append(body)
        return [body]

    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    return state


def test_a_rules_automation_skips_an_unsubscribed_contact(rules_db, resend):
    import rules_engine
    out = rules_engine._run_rule("biz1", RULE, "booking_created",
                                 {"contact_id": "c-dana", "contact_email": "dana@x.com",
                                  "contact_name": "Dana"}, 0)
    assert resend == []
    r = out["results"][0]
    assert r["ok"] is True and r["skipped"] is True and r["reason"] == "unsubscribed"
    assert cf.UNSUBSCRIBED_NOTE in r["note"]
    # The skip is in the trust layer's "why did this happen" log.
    assert rules_db["runs"][0]["results"][0]["reason"] == "unsubscribed"
    assert out["status"] == "executed"          # skipping is correct behaviour, not an error

    rules_engine._run_rule("biz1", RULE, "booking_created",
                           {"contact_id": "c-marcus", "contact_email": "marcus@x.com",
                            "contact_name": "Marcus"}, 0)
    assert resend == ["marcus@x.com"]


def test_a_rules_automation_holds_when_the_unsubscribe_check_cannot_run(rules_db, resend):
    import rules_engine
    rules_db["fail_contacts"] = True
    out = rules_engine._run_rule("biz1", RULE, "booking_created",
                                 {"contact_id": "c-marcus", "contact_email": "marcus@x.com"}, 0)
    assert resend == []
    assert out["results"][0]["ok"] is False and out["status"] == "executed_with_errors"


def test_a_follow_up_a_person_approves_is_sent_with_a_note(rules_db, resend):
    import rules_router
    p = {"proposal_type": "propose_followup_email",
         "proposed": {"contact_id": "c-dana", "contact_email": "dana@x.com",
                      "subject": "Following up", "body": "Hi Dana"}}
    # The trusted sweep (no person approved THIS one) skips her.
    skipped = rules_router._execute_proposal("biz1", p)
    assert skipped["skipped"] is True and resend == []
    # The practitioner approving it themselves is never blocked.
    sent = rules_router._execute_proposal("biz1", p, unattended=False)
    assert resend == ["dana@x.com"] and sent["ok"] is True
    assert cf.UNSUBSCRIBED_NOTE in sent["note"]


def test_approve_passes_that_a_person_approved():
    import inspect
    import rules_router
    assert "unattended=False" in inspect.getsource(rules_router.approve)


# ─── autopilot and the drafting sweeps ───────────────────────────────

def test_autopilot_holds_a_nurture_draft_to_someone_who_unsubscribed(monkeypatch):
    import chief_of_staff as cos

    async def must_not_decide(*a, **k):
        raise AssertionError("an unsubscribed contact reached the auto-approve decision")

    monkeypatch.setattr(cos, "_should_auto_approve", must_not_decide)
    draft = {"id": "q1", "agent": "nurture", "contact_id": "c-dana"}
    assert _run(cos._process_autopilot_for_draft(None, BIZ, draft, dict(DANA))) is None

    # Read without metadata (the sweep's select): it looks the contact up.
    async def _sb(client, method, path, body=None):
        assert "metadata" in path
        return [dict(DANA)]
    monkeypatch.setattr(cos, "_sb", _sb)
    assert _run(cos._process_autopilot_for_draft(
        None, BIZ, draft, {"id": "c-dana", "name": "Dana"})) is None


def test_autopilot_holds_when_it_cannot_read_the_unsubscribe(monkeypatch):
    import chief_of_staff as cos

    async def _sb(client, method, path, body=None):
        return None

    async def must_not_decide(*a, **k):
        raise AssertionError("a failed unsubscribe read must hold the draft")

    monkeypatch.setattr(cos, "_sb", _sb)
    monkeypatch.setattr(cos, "_should_auto_approve", must_not_decide)
    assert _run(cos._process_autopilot_for_draft(
        None, BIZ, {"id": "q1", "agent": "growth", "contact_id": "c-x"}, None)) is None


def test_autopilot_still_decides_transactional_drafts(monkeypatch):
    import chief_of_staff as cos
    asked = []

    async def decide(client, biz, agent, draft, contact=None):
        asked.append(agent)
        return False, "manual_mode"

    monkeypatch.setattr(cos, "_should_auto_approve", decide)
    # A payment reminder is about their own invoice — the unsubscribe is not asked.
    _run(cos._process_autopilot_for_draft(None, BIZ, {"id": "q2", "agent": "payment",
                                                      "contact_id": "c-dana"}, dict(DANA)))
    assert asked == ["payment"]


def test_the_nurture_sweep_does_not_draft_for_someone_who_unsubscribed(monkeypatch):
    import nurture_agent
    drafted = []

    async def _sb(client, method, path, body=None):
        if method == "GET" and path.startswith("/contacts") and "status=in." in path:
            return [dict(DANA), dict(MARCUS)]
        return []

    async def one(client, business, contact, events, **kw):
        drafted.append(contact["id"])
        return {"ai_reasoning": "quiet for a while"}

    monkeypatch.setattr(nurture_agent, "_sb", _sb)
    monkeypatch.setattr(nurture_agent, "_nurture_one_contact", one)
    _run(nurture_agent._run_nurture(None, {"id": "biz1", "name": "N", "type": "barber", "settings": {}}))
    assert drafted == ["c-marcus"]


def test_the_growth_sweep_does_not_draft_for_someone_who_unsubscribed(monkeypatch):
    import growth_engine
    drafted, selects = [], []

    async def _sb(client, method, path, body=None):
        if method == "GET" and path.startswith("/contacts") and "health_score=lt.40" in path:
            selects.append(path)
            return [dict(DANA, health_score=20), dict(MARCUS, health_score=25)]
        return []

    async def none(*a, **k):
        return None

    async def draft(client, biz, c, kind=""):
        drafted.append(c["id"])
        return None

    monkeypatch.setattr(growth_engine, "_sb", _sb)
    monkeypatch.setattr(growth_engine, "_existing_draft", none)
    monkeypatch.setattr(growth_engine, "_draft_nurture_check_in", draft)
    monkeypatch.setattr(growth_engine.briefing_verticals, "outreach_restricted", lambda t: False)
    _run(growth_engine._generate_briefing_actions(None, {"id": "biz1", "name": "N", "type": "barber"}))
    assert drafted == ["c-marcus"]
    assert "metadata" in selects[0]


# ─── one-to-one: never blocked, always noted ─────────────────────────

def test_a_one_to_one_draft_says_they_unsubscribed(monkeypatch):
    import chief_of_staff as cos
    inserted = []

    async def _sb(client, method, path, body=None):
        if method == "GET" and path.startswith("/contacts"):
            return [dict(DANA)]
        if method == "POST" and path.startswith("/agent_queue"):
            inserted.append(body)
            return [{"id": "q9", **body}]
        return []

    monkeypatch.setattr(cos, "_sb", _sb)
    res = _run(cos.handle_draft_email(None, BIZ, {
        "contact_id": "c-dana", "subject": "Your fade",
        "body": "Hi Dana, your usual Thursday slot opened up if you want it."}))
    assert inserted, "the practitioner's own email is still drafted"
    assert cf.UNSUBSCRIBED_NOTE in inserted[0]["ai_reasoning"]   # shown in the approval queue
    assert cf.UNSUBSCRIBED_NOTE in res["label"]                   # what Chief narrates


def test_approving_one_email_to_them_sends_and_says_so(monkeypatch, resend):
    import chief_of_staff as cos

    async def _sb(client, method, path, body=None):
        if method == "GET" and path.startswith("/contacts"):
            assert "metadata" in path
            return [dict(DANA)]
        return []

    monkeypatch.setattr(cos, "_sb", _sb)
    out = _run(cos._send_queued_email(None, BIZ, {"id": "q1", "contact_id": "c-dana",
                                                   "subject": "Hi", "body": "Hello Dana"}))
    assert out["sent"] is True and resend == ["dana@x.com"]
    assert out["unsubscribed"] == "unsubscribed"
