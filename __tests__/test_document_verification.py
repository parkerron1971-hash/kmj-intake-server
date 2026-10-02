"""The check system: rendered-text auditing, the structural contract,
and the gate on the way out.

What these pin, and why each one exists:

  * The auditor reads the RENDERED document. It used to be handed
    template["sections"] — the raw source — so the money rule was
    comparing clauses that still said "{fee}", and drafted sections,
    which carry no "text" key at all, arrived as empty strings.

  * A template declares the articles every rendered copy of itself
    contains, and that declaration is PROVED per document, after
    conditional gating. This is the rule that found engagement_letter
    shipping with no payment terms whenever its fee-model select came
    through blank.

  * A figure that appears in model-written text and nowhere in the
    practitioner's inputs is invented, and stops the document.

  * Blockers stop a document at the doors (approve / PDF / e-sign),
    an owner can override, and the override is recorded.
"""
from __future__ import annotations

import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import doc_audit as da  # noqa: E402
import doc_guard  # noqa: E402
import doc_templates as dt  # noqa: E402


CREATIVE_PARAMS = {
    "scope": "A five-page marketing site",
    "deliverables": "Homepage\nFour interior pages",
    "fee": "$2,400", "fee_model": "flat_fee", "state": "MI",
    "revision_rounds": "2", "acceptance_days": "7", "abandon_days": "30",
}


def _vars(tid="creative_services_agreement", params=None, **kw):
    t = dt.TEMPLATE_INDEX[tid]
    base = dict(CREATIVE_PARAMS if tid == "creative_services_agreement" else {})
    base.update(params or {})
    return t, dt.build_vars(
        t, base, business_name=kw.get("business_name", "Halvorsen Design"),
        practitioner_name="R. Halvorsen",
        client_name=kw.get("client_name", "Walton Wellness"),
        date_str="August 22, 2026", business_type="creative")


def _audit(t, v, drafted=None):
    drafted = drafted or {}
    rendered = dt.render_sections(t, v, drafted)
    body = dt.assemble(t, v, drafted, include_review_note=False)
    return body, da.audit_document(
        body, sections=rendered, numbered=bool(t.get("numbered")),
        contract=t.get("contract"), variables=v)


def _codes(result, severity=None):
    return {f["code"] for f in result["findings"]
            if severity is None or f["severity"] == severity}


# ─── The auditor reads the rendered document ─────────────────────────

def test_render_sections_substitutes_and_gates():
    t, v = _vars()
    rendered = dt.render_sections(t, v, {})
    assert rendered, "nothing rendered"
    for s in rendered:
        assert "{" not in s["text"] or "}" not in s["text"], s["heading"]
    # Exactly one of the three mutually exclusive payment branches.
    payment = [s for s in rendered if s.get("article") == "payment"]
    assert len(payment) == 1, [s["heading"] for s in payment]


def test_money_rule_can_actually_fire_now():
    """It could not before: the clause it was handed still said {fee}."""
    t, v = _vars(params={"payment_terms": "50% ($1,200) on signing, "
                                         "balance of $1,900 at completion."})
    _body, r = _audit(t, v)
    assert "money_conflict" in _codes(r)


def test_drafted_sections_are_scanned_not_skipped():
    """They have no "text" key in the source, so they used to be
    scanned as empty strings — the least constrained prose in the
    system getting the least scrutiny."""
    t, v = _vars()
    rendered = dt.render_sections(t, v, {0: "Fee is $10 and also $20."})
    generated = [s for s in rendered if s["drafted_used"]]
    assert generated and generated[0]["text"].startswith("Fee is")


# ─── The structural contract ─────────────────────────────────────────

def test_every_template_that_declares_a_contract_keeps_it():
    """Our own paper, both fills. A rule that fires here is either wrong
    or has found a template bug."""
    for tid in dt._CONTRACTS:
        t = dt.TEMPLATE_INDEX[tid]
        for required_only in (False, True):
            params = {}
            for f in t["fields"]:
                if required_only and not f["required"]:
                    continue
                k = f["key"]
                if f["type"] == "select":
                    params[k] = f["options"][0]
                elif f["type"] == "list":
                    params[k] = "One\nTwo"
                elif any(x in k for x in ("fee", "pay", "price", "investment",
                                          "amount", "deposit", "balance")):
                    params[k] = "$2,500.00"
                elif "days" in k or "years" in k:
                    params[k] = "14"
                else:
                    params[k] = f.get("default") or f"Sample {k}"
            v = dt.build_vars(t, params, business_name="Reyes Law",
                              practitioner_name="M. Reyes",
                              client_name="D. Whitfield",
                              date_str="March 4, 2026", business_type="lawyer")
            missing = dt.verify_contract(t, dt.render_sections(t, v, {}))
            assert not missing, f"{tid} ({'required-only' if required_only else 'full'}): {missing}"


def test_a_blank_branch_select_is_caught_as_a_missing_article():
    """The engagement_letter bug, reproduced on the template that can
    still express it: no branch matches, so the article is simply not
    in the document, and nothing else in the system would say so."""
    t, v = _vars()
    v["fee_model"] = ""
    _body, r = _audit(t, v)
    assert "article_missing" in _codes(r, da.BLOCKER)
    assert any("payment terms" in f["detail"] for f in r["findings"]
               if f["code"] == "article_missing")


def test_engagement_letter_now_refuses_a_blank_fee_model():
    t = dt.TEMPLATE_INDEX["engagement_letter"]
    assert dt.validate_params(t, {"scope": "s", "fee": "$500"})
    assert not dt.validate_params(
        t, {"scope": "s", "fee": "$500", "fee_model": "hourly"})


# ─── Fact fidelity ───────────────────────────────────────────────────

def test_a_figure_the_model_invented_is_a_blocker():
    t, v = _vars()
    _body, r = _audit(t, v, drafted={
        0: "Thank you. We will deliver within 45 days for $2,600."})
    assert "invented_figure" in _codes(r, da.BLOCKER)


def test_restating_a_supplied_figure_is_not_a_finding():
    """The rule that would make the auditor useless is the one that
    fires on correct paper."""
    t, v = _vars()
    _body, r = _audit(t, v, drafted={
        0: "Thank you. The project fee is $2,400 and includes 2 rounds."})
    assert "invented_figure" not in _codes(r)


def test_an_authored_fallback_is_not_treated_as_generated():
    """A fallback is reviewed paper, held to the same standard as a
    fixed clause — only the MODEL's words are policed."""
    t, v = _vars()
    _body, r = _audit(t, v, drafted={})      # no model text at all
    assert "invented_figure" not in _codes(r)


# ─── Cross-references and parties ────────────────────────────────────

def test_a_reference_past_the_last_clause_is_flagged():
    t, v = _vars()
    body, _ = _audit(t, v)
    rendered = dt.render_sections(t, v, {})
    r = da.audit_document(body + "\n\nSee Section 94.", sections=rendered,
                          numbered=True, contract=t.get("contract"), variables=v)
    assert "cross_reference_broken" in _codes(r)


def test_a_party_edited_out_of_its_own_agreement_is_flagged():
    t, v = _vars()
    body, _ = _audit(t, v)
    rendered = dt.render_sections(t, v, {})
    r = da.audit_document(body.replace("Walton Wellness", "the client"),
                          sections=rendered, numbered=True,
                          contract=t.get("contract"), variables=v)
    assert "party_missing" in _codes(r)


def test_letters_are_not_held_to_an_instrument_shape():
    """No contract declared → the structural rules stay inert. A demand
    letter is not an agreement and must not be graded like one."""
    t = dt.TEMPLATE_INDEX["demand_letter"]
    assert not t.get("contract")
    v = dt.build_vars(t, {f["key"]: "x" for f in t["fields"]},
                      business_name="B", practitioner_name="P",
                      client_name="C", date_str="March 4, 2026")
    _body, r = _audit(t, v)
    assert "article_missing" not in _codes(r)
    assert "party_missing" not in _codes(r)


# ─── Backwards compatibility ─────────────────────────────────────────

def test_a_body_only_call_still_works():
    """Callers that have only text still get the original rules, and
    every rule needing a contract or variables stays quiet."""
    r = da.audit_document("Pay {fee} by February 30, 2026.")
    assert r["ok"]
    assert "placeholder_unfilled" in _codes(r)
    assert "date_impossible" in _codes(r)
    assert "article_missing" not in _codes(r)


# ─── The gate ────────────────────────────────────────────────────────

class _Recorder:
    def __init__(self):
        self.posted = []
        self.patched = []

    def post(self, path, body, prefer="rep"):
        self.posted.append((path, body))
        return [{"id": "e1"}]

    def patch(self, path, body):
        self.patched.append((path, body))
        return [{}]


@pytest.fixture
def rec(monkeypatch):
    r = _Recorder()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_post_as_service", r.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", r.patch)
    return r


def _blocked_row():
    t, v = _vars()
    v["fee_model"] = ""                       # drops the payment article
    body = dt.assemble(t, v, {}, include_review_note=False)
    audit = da.audit_document(
        body, sections=dt.render_sections(t, v, {}), numbered=True,
        contract=t.get("contract"), variables=v)
    return {"id": "q1", "business_id": "b1", "contact_id": "c1",
            "action_type": "document", "body": body,
            "data": {doc_guard.DATA_KEY: doc_guard.stash(
                t, v, audit, dt.render_sections(t, v, {}))}}


def test_blockers_stop_a_document_at_the_door(rec):
    row = _blocked_row()
    with pytest.raises(HTTPException) as e:
        doc_guard.require_sendable(row, business_id="b1", actor_id="u1")
    assert e.value.status_code == 409
    assert e.value.detail["error"] == "document_blocked"
    assert e.value.detail["can_override"] is True
    assert e.value.detail["blockers"] >= 1


def test_the_owner_can_override_and_it_is_recorded(rec):
    row = _blocked_row()
    doc_guard.require_sendable(row, business_id="b1", actor_id="u1",
                               override=True, door="esign")
    events = [b for p, b in rec.posted if p == "/events"]
    assert len(events) == 1
    assert events[0]["event_type"] == "document_override"
    assert events[0]["data"]["door"] == "esign"
    assert events[0]["data"]["actor_id"] == "u1"
    assert "article_missing" in events[0]["data"]["codes"]


def test_a_clean_document_passes_and_is_restamped(rec):
    t, v = _vars()
    body = dt.assemble(t, v, {}, include_review_note=False)
    audit = da.audit_document(body, sections=dt.render_sections(t, v, {}),
                              numbered=True, contract=t.get("contract"),
                              variables=v)
    row = {"id": "q2", "business_id": "b1", "contact_id": "c1",
           "action_type": "document", "body": body,
           "data": {doc_guard.DATA_KEY: doc_guard.stash(
                t, v, audit, dt.render_sections(t, v, {}))}}
    out = doc_guard.require_sendable(row, business_id="b1", actor_id="u1")
    assert da.blocking_count(out) == 0
    assert not [b for p, b in rec.posted if p == "/events"]
    assert rec.patched, "a fresh verdict should be written back"


def test_the_gate_ignores_everything_that_is_not_a_document(rec):
    """Every other action_type leaves through these same doors."""
    row = {"id": "q3", "business_id": "b1", "action_type": "email",
           "body": "Pay {fee}", "data": {}}
    assert doc_guard.require_sendable(row, business_id="b1", actor_id="u1") == {}
    assert not rec.patched and not rec.posted


def test_a_hand_edit_is_caught_on_the_way_out(rec):
    """The verdict stamped at generation describes the body as
    generated. The gate re-reads what is there NOW."""
    t, v = _vars()
    body = dt.assemble(t, v, {}, include_review_note=False)
    clean = da.audit_document(body, sections=dt.render_sections(t, v, {}),
                              numbered=True, contract=t.get("contract"),
                              variables=v)
    assert da.blocking_count(clean) == 0
    row = {"id": "q4", "business_id": "b1", "contact_id": "c1",
           "action_type": "document",
           "body": body + "\n\nBalance due: [AMOUNT TO BE CONFIRMED]",
           "data": {doc_guard.DATA_KEY: doc_guard.stash(
               t, v, clean, dt.render_sections(t, v, {}))}}
    with pytest.raises(HTTPException) as e:
        doc_guard.require_sendable(row, business_id="b1", actor_id="u1")
    assert e.value.status_code == 409


def test_summarize_never_calls_an_unchecked_document_clean():
    assert doc_guard.summarize(None)["verdict"] == "unchecked"
    assert doc_guard.summarize({})["verdict"] == "unchecked"
    assert doc_guard.summarize(
        {"ok": True, "counts": {}})["verdict"] == "verified"
    assert doc_guard.summarize(
        {"ok": True, "counts": {"blocker": 1}})["verdict"] == "blocked"
    assert doc_guard.summarize(
        {"ok": True, "counts": {"high": 2}})["verdict"] == "flagged"
