"""The client layer's doors — the decisions that cannot be reversed later.

Three things are pinned here, and each one is cheap to get right today
and impossible to correct afterwards.

  * A client-facing surface is refused for therapists BY THE CODE.
    Until vertical_scope grew a second kind of rule, "therapists are
    out of the client arc" was true only by accident: no vertical had
    a client surface, so none was refused one. An accident is not a
    boundary, and this is the HIPAA boundary.

  * A client action carries a rule that names why it was allowed.
    audit_log.authorized_by is the difference between "a client did
    this" and "a client was permitted to do this, here is the rule",
    and the table is append-only — a row written without a rule can
    never be given one.

  * AI spend reached through a client credential names the business it
    was spent for. Before this, four call sites set billing_context and
    none was a client path, so client-surface spend landed with
    business_id NULL. spend_guard says what that means: unattributed
    spend counts toward the PLATFORM ceiling only, the one whose
    failure mode is Chief going dark for every paying practitioner.

The fourth door — audit_log.actor_type gaining 'client' — lives in
supabase/APPLY-2026-08-31-client-actor-and-identity.sql and is verified
against the live database, not here. A test asserting a CHECK constraint
this suite never talks to would only be checking that a file exists,
which is the mistake vertical_registry.KNOWN_GAPS already records
someone making.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import billing_context
import policy_engine
import vertical_scope


BIZ = "11111111-1111-1111-1111-111111111111"
CUS = "22222222-2222-2222-2222-222222222222"

_COACH = {"id": BIZ, "type": "coach", "settings": {}}
_THERAPIST = {"id": BIZ, "type": "therapist", "settings": {}}


# ─── The vertical gate ───────────────────────────────────────────────

def test_therapist_has_no_client_surface():
    assert vertical_scope.client_surface_allowed("therapist") is False
    assert vertical_scope.client_surface("therapist") == "denied"


def test_therapist_aliases_are_refused_too():
    """resolve() flattens a large alias table. A practice stamped
    'counselor' or 'lmft' is a therapist and must not get a portal
    through a synonym."""
    for alias in ("counselor", "counselling", "psychotherapy", "lcsw", "lmft"):
        assert vertical_scope.client_surface_allowed(alias) is False, alias


def test_every_other_vertical_is_allowed_by_default():
    """A vertical with no rule has no restriction. The refusal is the
    exception and has to be declared — the same posture rule_for()
    already takes."""
    import vertical_registry
    for key in vertical_registry.canonical_keys():
        if key == "therapist":
            continue
        assert vertical_scope.client_surface_allowed(key) is True, key


def test_denied_vertical_also_refuses_free_text():
    """A vertical with no surface cannot have free text on it. These are
    two refusals, and 'denied' has to answer both."""
    assert vertical_scope.client_free_text_allowed("therapist") is False
    assert vertical_scope.client_free_text_allowed("coach") is True


def test_refusal_explains_itself():
    msg = vertical_scope.client_surface_refusal("therapist")
    assert msg and "HIPAA" in msg
    # It offers what IS supported rather than only refusing.
    assert "cheduling" in msg
    assert vertical_scope.client_surface_refusal("coach") is None


# ─── The client evaluator ────────────────────────────────────────────

def test_client_action_carries_a_rule():
    v = policy_engine.evaluate_client(
        BIZ, verb="client_book_appointment", actor="client",
        customer_id=CUS, biz_row=_COACH)
    assert v.allowed is True
    assert v.rule == "client:self"


def test_client_agent_is_the_same_authority_different_authorship():
    """An agent acting on the client's instruction gets the client's
    authority. The rule says which one typed, because that is the part
    an auditor cannot reconstruct."""
    v = policy_engine.evaluate_client(
        BIZ, verb="client_book_appointment", actor="client_agent",
        customer_id=CUS, biz_row=_COACH)
    assert v.allowed is True
    assert v.rule == "client:agent"


def test_reads_are_marked_as_reads():
    v = policy_engine.evaluate_client(
        BIZ, verb="client_view_booking_config", actor="client",
        customer_id=CUS, biz_row=_COACH)
    assert v.allowed is True
    assert v.rule == "client:self:read"


def test_unknown_verb_fails_closed():
    """Drift on the client surface fails closed for the same reason it
    does on the practitioner's: a verb nobody classified is a verb
    nobody reasoned about."""
    v = policy_engine.evaluate_client(
        BIZ, verb="client_delete_everything", actor="client",
        customer_id=CUS, biz_row=_COACH)
    assert v.allowed is False
    assert v.rule == "client:unclassified"


def test_practitioner_actor_is_refused():
    """A caller passing 'user' here is reaching for the wrong evaluator,
    and getting a client rule for a practitioner action would put a
    false statement in an append-only record."""
    v = policy_engine.evaluate_client(
        BIZ, verb="client_book_appointment", actor="user",
        customer_id=CUS, biz_row=_COACH)
    assert v.allowed is False
    assert v.rule == "client:unknown_actor"


def test_therapist_is_refused_at_the_evaluator_too():
    """The gate is checked on every action, not only at enable time.
    Enablement can predate a business being reclassified."""
    v = policy_engine.evaluate_client(
        BIZ, verb="client_book_appointment", actor="client",
        customer_id=CUS, biz_row=_THERAPIST)
    assert v.allowed is False
    assert v.rule == "vertical:client_surface_denied"


def test_therapist_reads_are_refused_as_well_as_writes():
    """A refused vertical is refused the whole surface. 'Your client may
    not book but may read your service menu through the portal' is not a
    boundary anyone drew."""
    v = policy_engine.evaluate_client(
        BIZ, verb="client_view_booking_config", actor="client",
        customer_id=CUS, biz_row=_THERAPIST)
    assert v.allowed is False
    assert v.rule == "vertical:client_surface_denied"


def test_scope_check_failure_fails_closed(monkeypatch):
    """This is the HIPAA boundary. A check that cannot run is not a
    permission to proceed — the opposite of the surrounding module's
    fail-open habits, deliberately."""
    def _boom(_):
        raise RuntimeError("scope table unreachable")

    monkeypatch.setattr(vertical_scope, "client_surface_allowed", _boom)
    v = policy_engine.evaluate_client(
        BIZ, verb="client_book_appointment", actor="client",
        customer_id=CUS, biz_row=_COACH)
    assert v.allowed is False
    assert v.rule == "vertical:scope_unavailable"


def test_missing_business_or_verb_is_refused():
    assert policy_engine.evaluate_client(
        "", verb="client_book_appointment", biz_row=_COACH).allowed is False
    assert policy_engine.evaluate_client(
        BIZ, verb="", biz_row=_COACH).allowed is False


def test_paused_automations_do_not_stop_a_client():
    """A practitioner who paused their automations has paused what runs
    ON ITS OWN. They have not told their clients to stop booking, and
    usage_metering's standing promise is that bookings never stop."""
    paused = {"id": BIZ, "type": "coach",
              "settings": {"automations_paused": True}}
    v = policy_engine.evaluate_client(
        BIZ, verb="client_book_appointment", actor="client",
        customer_id=CUS, biz_row=paused)
    assert v.allowed is True
    assert v.rule == "client:self"


def test_client_verbs_are_disjoint_from_chief_verbs():
    """The two vocabularies must never collide. A verb appearing in both
    would be classified twice, by two evaluators, with no rule saying
    which one wins."""
    import action_registry
    overlap = set(policy_engine.CLIENT_VERBS) & set(action_registry.REGISTRY)
    assert not overlap, f"verb in both registries: {overlap}"


def test_every_client_verb_declares_an_effect():
    for verb, entry in policy_engine.CLIENT_VERBS.items():
        assert entry.get("effect") in ("read", "write"), verb
        assert entry.get("why"), verb


# ─── The metering hole ───────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_billing_context():
    token = billing_context._CURRENT.set(None)
    yield
    billing_context._CURRENT.reset(token)


def test_client_dependency_attributes_spend(monkeypatch):
    """The whole point: a paid call reached through a client credential
    must name the business it was spent for, or spend_guard's per-tenant
    ceiling structurally cannot see it."""
    import customer_token

    monkeypatch.setattr(customer_token, "_extract_token", lambda r: "tok")
    monkeypatch.setattr(customer_token, "verify_customer_token",
                        lambda t: {"biz": BIZ, "cus": CUS})
    monkeypatch.setattr(customer_token.sb_clients, "sb_get_as_service",
                        lambda q: [{"id": CUS, "business_id": BIZ,
                                    "email": "a@b.com", "name": "A"}])

    assert billing_context.current() is None
    ctx = customer_token.require_customer_token_dep(BIZ, request=object())
    assert ctx.customer_id == CUS
    assert billing_context.current() == BIZ


def test_refused_caller_never_names_a_tenant(monkeypatch):
    """Bookkeeping follows authorization; it does not grant it. A caller
    refused at the revocation check must not be able to name the tenant
    a later api_usage row is attributed to."""
    import customer_token
    from fastapi import HTTPException

    monkeypatch.setattr(customer_token, "_extract_token", lambda r: "tok")
    monkeypatch.setattr(customer_token, "verify_customer_token",
                        lambda t: {"biz": BIZ, "cus": CUS})
    # Step 3 fails — the customer row is gone (revocation = row delete).
    monkeypatch.setattr(customer_token.sb_clients, "sb_get_as_service",
                        lambda q: [])

    with pytest.raises(HTTPException):
        customer_token.require_customer_token_dep(BIZ, request=object())
    assert billing_context.current() is None


def test_cross_tenant_token_never_names_a_tenant(monkeypatch):
    """Step 2 — a token valid for another business. It must be refused
    BEFORE anything attributes spend to the business named in the path."""
    import customer_token
    from fastapi import HTTPException

    other = "99999999-9999-9999-9999-999999999999"
    monkeypatch.setattr(customer_token, "_extract_token", lambda r: "tok")
    monkeypatch.setattr(customer_token, "verify_customer_token",
                        lambda t: {"biz": other, "cus": CUS})

    with pytest.raises(HTTPException):
        customer_token.require_customer_token_dep(BIZ, request=object())
    assert billing_context.current() is None
