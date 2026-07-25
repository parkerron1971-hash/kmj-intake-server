"""P0.3 — Chief contract verbs.

Thin wrappers over contract_agent, so these defend the WRAPPER contract, not
the proposal voice or the PDF styling:
  • result + label on every return, including every failure path,
  • a contract names a counterparty — ambiguity is a question, never a guess,
  • the fallback body (model returned nothing) is SURFACED, not passed off
    as finished voice work,
  • the draft is targetable by approve_draft (queue_id rides on the result),
  • exceptions from the engine are contained, not propagated into the turn,
  • no send_for_signature verb exists, and nothing here sends.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import chief_contract_actions as cca

BIZ = {"id": "biz1", "name": "Webb Legal", "settings": {"practitioner_name": "Dana"}}
CONTACT = {"id": "c1", "name": "Marcus Webb", "email": "m@example.com",
           "metadata": {}, "role": "Founder"}

DRAFTED = {"contact_id": "c1", "contact_name": "Marcus Webb",
           "subject": "Engagement Letter", "body": "Dear Marcus, here are the terms...",
           "queue_id": "q9"}


def _sb(monkeypatch, router):
    """Route sb_get_as_service by URL fragment."""
    monkeypatch.setattr(cca.sb_clients, "sb_get_as_service", router)


def _run(coro):
    return asyncio.run(coro)


# ─── contact resolution: a contract needs a counterparty ──────────────

def test_no_name_asks_who(monkeypatch):
    _sb(monkeypatch, lambda q: [])
    out = _run(cca.handle_draft_contract(None, BIZ, {}))
    assert out["result"] and out["label"]
    assert "who" in out["result"].lower()


def test_unknown_name_is_refused_not_guessed(monkeypatch):
    _sb(monkeypatch, lambda q: [])
    out = _run(cca.handle_draft_contract(None, BIZ, {"contact_name": "Nobody"}))
    assert "couldn't find" in out["result"]
    assert out["label"]


def test_ambiguous_name_asks_which_and_names_them(monkeypatch):
    both = [{"id": "c1", "name": "Marcus Webb"}, {"id": "c2", "name": "Marcus Reed"}]
    _sb(monkeypatch, lambda q: both if "contacts?" in q else [])
    out = _run(cca.handle_draft_contract(None, BIZ, {"contact_name": "Marcus"}))
    assert "Multiple contacts match" in out["result"]
    assert "Marcus Webb" in out["result"] and "Marcus Reed" in out["result"]
    assert out["label"]


def test_bad_contact_id_is_refused(monkeypatch):
    _sb(monkeypatch, lambda q: [])
    out = _run(cca.handle_draft_contract(None, BIZ, {"contact_id": "nope"}))
    assert "couldn't find that contact" in out["result"]


# ─── draft_contract ───────────────────────────────────────────────────

def _draft_env(monkeypatch, drafted=DRAFTED, prior=False):
    def router(q):
        if "/contacts?" in q:
            return [CONTACT]
        if "agent=eq.contract" in q:
            return [{"id": "old"}] if prior else []
        return []
    _sb(monkeypatch, router)

    import contract_agent as ca

    async def fake_draft(client, biz, contact, events, history, dry_run=False):
        return drafted
    monkeypatch.setattr(ca, "_draft_proposal", fake_draft)


def test_draft_returns_queue_id_so_approve_draft_can_target_it(monkeypatch):
    _draft_env(monkeypatch)
    out = _run(cca.handle_draft_contract(None, BIZ, {"contact_name": "Marcus"}))
    assert out["type"] == "draft_contract"
    assert out["result"] and out["label"]
    assert out["queue_id"] == "q9"          # the draft→approve_draft chain
    assert "Marcus Webb" in out["label"]
    assert out["used_fallback_language"] is False


def test_draft_nothing_is_sent(monkeypatch):
    """The verb creates a draft. If this ever starts sending, the trust
    model changes and the prompt copy becomes a lie."""
    _draft_env(monkeypatch)
    out = _run(cca.handle_draft_contract(None, BIZ, {"contact_name": "Marcus"}))
    assert "sent" not in out["result"].lower()
    assert out["nav"] == {"tab": "operate", "sub": "queue"}


def test_existing_draft_is_reported_not_silently_skipped(monkeypatch):
    """The bulk endpoint skips a contact who already has a draft. Asked by
    name, we draft anyway — but the practitioner is told."""
    _draft_env(monkeypatch, prior=True)
    out = _run(cca.handle_draft_contract(None, BIZ, {"contact_name": "Marcus"}))
    assert "already" in out["result"]
    assert out["queue_id"] == "q9"


def test_fallback_wording_is_surfaced_not_passed_off(monkeypatch):
    """contract_agent substitutes a generic body when the model returns
    nothing, and the row looks identical. If we don't flag it, the reply
    calls a stub 'your engagement letter'."""
    stub = dict(DRAFTED, body=("Hi Marcus,\n\nThank you for your interest in working "
                               "with Webb Legal. I'd love to discuss how we can help."))
    _draft_env(monkeypatch, drafted=stub)
    out = _run(cca.handle_draft_contract(None, BIZ, {"contact_name": "Marcus"}))
    assert out["used_fallback_language"] is True
    assert "generic" in out["result"]
    assert "generic wording" in out["label"]


def test_engine_exception_is_contained(monkeypatch):
    _draft_env(monkeypatch)
    import contract_agent as ca

    async def boom(*a, **k):
        raise RuntimeError("anthropic exploded")
    monkeypatch.setattr(ca, "_draft_proposal", boom)

    out = _run(cca.handle_draft_contract(None, BIZ, {"contact_name": "Marcus"}))
    assert out["result"] and out["label"]
    assert "couldn't draft" in out["result"]


def test_draft_returning_none_is_a_clean_failure(monkeypatch):
    _draft_env(monkeypatch, drafted=None)
    out = _run(cca.handle_draft_contract(None, BIZ, {"contact_name": "Marcus"}))
    assert out["result"] and out["label"]


# ─── contract_pdf ─────────────────────────────────────────────────────

ROW = {"id": "q9", "subject": "Engagement Letter",
       "body": "Dear Marcus, here are the terms...", "contact_id": "c1"}


def _pdf_env(monkeypatch, row=ROW, build=None, upload=None):
    def router(q):
        if "/contacts?" in q:
            return [CONTACT]
        if "/agent_queue?" in q:
            return [row] if row else []
        return []
    _sb(monkeypatch, router)

    import contract_agent as ca
    monkeypatch.setattr(ca, "_build_pdf", build or (lambda **kw: b"%PDF-1.4 fake"))

    async def fake_upload(client, data, biz_id, contact_id):
        return "https://sb.example.com/proposals/x.pdf"
    monkeypatch.setattr(ca, "_upload_pdf_to_supabase", upload or fake_upload)


def test_pdf_renders_the_existing_draft(monkeypatch):
    _pdf_env(monkeypatch)
    out = _run(cca.handle_contract_pdf(None, BIZ, {"contact_name": "Marcus"}))
    assert out["type"] == "contract_pdf"
    assert out["result"] and out["label"]
    assert out["pdf_url"].endswith(".pdf")
    assert out["size_bytes"] > 0
    assert out["queue_id"] == "q9"


def test_pdf_without_a_draft_offers_to_draft_one(monkeypatch):
    _pdf_env(monkeypatch, row=None)
    out = _run(cca.handle_contract_pdf(None, BIZ, {"contact_name": "Marcus"}))
    assert "no contract draft" in out["result"]
    assert out["label"]


def test_pdf_of_an_empty_draft_is_refused(monkeypatch):
    _pdf_env(monkeypatch, row=dict(ROW, body="   "))
    out = _run(cca.handle_contract_pdf(None, BIZ, {"contact_name": "Marcus"}))
    assert "empty" in out["result"]
    assert out["label"]


def test_pdf_missing_reportlab_gives_a_human_answer(monkeypatch):
    def no_reportlab(**kw):
        raise ImportError("No module named 'reportlab'")
    _pdf_env(monkeypatch, build=no_reportlab)
    out = _run(cca.handle_contract_pdf(None, BIZ, {"contact_name": "Marcus"}))
    assert out["result"] and out["label"]
    assert "isn't available" in out["result"]
    assert "reportlab" not in out["result"]      # not a stack trace at the practitioner


def test_pdf_upload_failure_does_not_claim_success(monkeypatch):
    async def bad_upload(client, data, biz_id, contact_id):
        return None
    _pdf_env(monkeypatch, upload=bad_upload)
    out = _run(cca.handle_contract_pdf(None, BIZ, {"contact_name": "Marcus"}))
    assert "couldn't store it" in out["result"]
    assert "pdf_url" not in out


def test_pdf_build_exception_is_contained(monkeypatch):
    def boom(**kw):
        raise RuntimeError("reportlab blew up")
    _pdf_env(monkeypatch, build=boom)
    out = _run(cca.handle_contract_pdf(None, BIZ, {"contact_name": "Marcus"}))
    assert out["result"] and out["label"]
    assert "couldn't build that PDF" in out["result"]


# ─── the registry contract ────────────────────────────────────────────

def test_verbs_are_registered_and_signature_verb_is_not():
    """draft_contract + contract_pdf are callable. send_for_signature must
    NOT exist: there is no e-signature provider in this service, and a verb
    by that name would promise the practitioner an executed document while
    delivering an email."""
    import chief_of_staff as cos
    assert "draft_contract" in cos.ACTION_HANDLERS
    assert "contract_pdf" in cos.ACTION_HANDLERS
    assert "send_for_signature" not in cos.ACTION_HANDLERS
    assert not any("signature" in v for v in cos.ACTION_HANDLERS)


def test_every_return_path_carries_result_and_label():
    """The standing rule: a handler return missing result/label blanks the
    app (toLowerCase on undefined). _fail is the shared failure path."""
    out = cca._fail("draft_contract", "nope")
    assert out["result"] == "nope"
    assert out["label"] and out["type"] == "draft_contract"
