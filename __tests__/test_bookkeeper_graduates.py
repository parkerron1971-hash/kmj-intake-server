"""One face, many hands, each graduating on its own — the bookkeeper
joins the Trust Track (2026-09-04).

Pins:
  * a bookkeeping category (categorize / match / exclude) that clears the
    bar is grantable, and the view says which hand it belongs to;
  * period close, journal entries and account reconciliation are never
    grantable, however well they score;
  * the trusted sweep executes a granted bookkeeping category through
    chief_bookkeeping.approve_proposal — the same call the approve
    endpoint makes — with the sweep's own identity, and audits it;
  * the live re-check stands the bookkeeper down when its ratio slips;
  * a failed execution leaves the proposal pending and is audited;
  * every grantable type names a hand and a registry verb.
"""
from __future__ import annotations

import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

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
    fb.rows("businesses").append({"id": "b1", "owner_id": "owner1", "name": "Biz", "settings": {}})
    return fb


def _resolved(fb, ptype, approved, rejected, table="chief_bookkeeping_proposals"):
    for i in range(approved):
        fb.rows(table).append({"id": f"{ptype}-a{i}", "business_id": "b1",
                               "proposal_type": ptype, "status": "approved"})
    for i in range(rejected):
        fb.rows(table).append({"id": f"{ptype}-r{i}", "business_id": "b1",
                               "proposal_type": ptype, "status": "rejected"})


def _allow(monkeypatch):
    import policy_engine
    seen = []

    def evaluate(biz, *, verb, surface, prompted, biz_row=None, user_id=None):
        seen.append((verb, surface, prompted))
        return policy_engine.Verdict(True, f"{surface}:C:unattended", "recorded", None)
    monkeypatch.setattr(policy_engine, "evaluate", evaluate)
    return seen


def _audit(monkeypatch):
    import audit_log
    rows = []
    monkeypatch.setattr(audit_log, "record", lambda *a, **k: rows.append((a, k)) or True)
    return rows


# ─── Graduation and the grant ───────────────────────────────────────────

def test_a_graduated_bookkeeping_category_is_grantable_and_names_its_hand(fake):
    _resolved(fake, "propose_categorize", 17, 3)          # 85% over 20
    _resolved(fake, "propose_followup_email", 5, 0, table="chief_proposals")
    view = rr.trust_track("b1", _u())
    cats = {c["proposal_type"]: c for c in view["categories"]}
    cat = cats["propose_categorize"]
    assert cat["graduation_candidate"] and cat["grantable"]
    assert cat["hand"] == "bookkeeper"
    assert cats["propose_followup_email"]["hand"] == "front desk"
    assert not cats["propose_followup_email"]["grantable"], "5 decisions is not 20"

    out = rr.trust_grant(rr.TrustGrantBody(business_id="b1", proposal_type="propose_categorize"), _u())
    assert out["trusted"] == ["propose_categorize"]
    biz = fake.rows("businesses")[0]
    assert biz["settings"]["autopilot"]["trusted_proposal_types"] == ["propose_categorize"]


@pytest.mark.parametrize("ptype", ["propose_period_close", "propose_journal_entry",
                                   "propose_account_reconciliation"])
def test_the_ledger_touching_categories_never_graduate_into_autonomy(fake, ptype):
    _resolved(fake, ptype, 40, 0)                          # 100% over 40
    view = rr.trust_track("b1", _u())
    cat = next(c for c in view["categories"] if c["proposal_type"] == ptype)
    assert cat["graduation_candidate"] and not cat["grantable"]
    assert cat["hand"] == "bookkeeper"
    with pytest.raises(HTTPException) as ex:
        rr.trust_grant(rr.TrustGrantBody(business_id="b1", proposal_type=ptype), _u())
    assert ex.value.status_code == 400


def test_an_ungraduated_bookkeeping_category_cannot_be_granted(fake):
    _resolved(fake, "propose_match", 10, 8)                # 56%
    with pytest.raises(HTTPException) as ex:
        rr.trust_grant(rr.TrustGrantBody(business_id="b1", proposal_type="propose_match"), _u())
    assert ex.value.status_code == 409


# ─── The sweep ──────────────────────────────────────────────────────────

def _grant(fb, *types):
    fb.rows("businesses")[0]["settings"] = {"autopilot": {"trusted_proposal_types": list(types)}}


def test_the_sweep_executes_the_bookkeepers_granted_category_through_its_own_approve(fake, monkeypatch):
    import chief_bookkeeping
    _resolved(fake, "propose_categorize", 17, 3)
    _grant(fake, "propose_categorize")
    fake.rows("chief_bookkeeping_proposals").append({
        "id": "bk-pending", "business_id": "b1", "proposal_type": "propose_categorize",
        "status": "pending", "plaid_transaction_id": "tx9", "created_at": "2026-09-01T00:00:00Z",
        "proposed": {"business_category": "Software"}})
    fake.rows("chief_proposals").append({
        "id": "cp-pending", "business_id": "b1", "proposal_type": "propose_followup_email",
        "status": "pending", "created_at": "2026-09-01T00:00:00Z", "proposed": {"subject": "x"}})
    seen = _allow(monkeypatch)
    audits = _audit(monkeypatch)
    approved = []
    monkeypatch.setattr(chief_bookkeeping, "approve_proposal",
                        lambda biz, pid, approved_by="": approved.append((biz, pid, approved_by)) or {"ok": True})
    monkeypatch.setattr(rr, "_execute_proposal",
                        lambda biz, p: pytest.fail("the ungranted front-desk category must not run"))

    rr._run_trusted_sweep_sync()

    assert approved == [("b1", "bk-pending", "chief:trusted-autonomy")]
    assert seen == [("approve_bookkeeping_proposal", "trust-track", False)], \
        "the policy engine is asked about the verb the proposal is equivalent to"
    ok_rows = [k for a, k in audits if k.get("ok")]
    assert ok_rows and ok_rows[0]["payload"]["proposal_id"] == "bk-pending"
    assert "Software" in ok_rows[0]["summary"]
    rail = fake.rows("chief_activity")
    assert rail and rail[0]["action_type"] == "trusted_propose_categorize"
    # the generic row was never touched: not granted, not executed
    assert fake.rows("chief_proposals")[0]["status"] == "pending"


def test_the_sweep_stands_the_bookkeeper_down_when_the_ratio_slips(fake, monkeypatch):
    import chief_bookkeeping
    _resolved(fake, "propose_categorize", 12, 8)           # 60% — below the bar
    _grant(fake, "propose_categorize")
    fake.rows("chief_bookkeeping_proposals").append({
        "id": "bk-pending", "business_id": "b1", "proposal_type": "propose_categorize",
        "status": "pending", "created_at": "2026-09-01T00:00:00Z", "proposed": {}})
    _allow(monkeypatch); _audit(monkeypatch)
    monkeypatch.setattr(chief_bookkeeping, "approve_proposal",
                        lambda *a, **k: pytest.fail("must stand down below the bar"))
    rr._run_trusted_sweep_sync()
    assert fake.rows("chief_bookkeeping_proposals")[-1]["status"] == "pending"
    assert fake.rows("businesses")[0]["settings"]["autopilot"]["trusted_proposal_types"] == ["propose_categorize"], \
        "the grant stays; only execution pauses"


def test_a_failed_bookkeeping_execution_stays_pending_and_is_audited(fake, monkeypatch):
    import chief_bookkeeping
    _resolved(fake, "propose_exclude", 20, 0)
    _grant(fake, "propose_exclude")
    fake.rows("chief_bookkeeping_proposals").append({
        "id": "bk-x", "business_id": "b1", "proposal_type": "propose_exclude",
        "status": "pending", "created_at": "2026-09-01T00:00:00Z", "proposed": {}})
    _allow(monkeypatch)
    audits = _audit(monkeypatch)
    monkeypatch.setattr(chief_bookkeeping, "approve_proposal",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("plaid 500")))
    rr._run_trusted_sweep_sync()
    assert fake.rows("chief_bookkeeping_proposals")[-1]["status"] == "pending"
    failed = [k for a, k in audits if k.get("ok") is False]
    assert failed and "plaid 500" in failed[0]["error"]


def test_a_refused_policy_holds_the_bookkeeper_too(fake, monkeypatch):
    import chief_bookkeeping
    import policy_engine
    _resolved(fake, "propose_match", 20, 0)
    _grant(fake, "propose_match")
    fake.rows("chief_bookkeeping_proposals").append({
        "id": "bk-m", "business_id": "b1", "proposal_type": "propose_match",
        "status": "pending", "created_at": "2026-09-01T00:00:00Z", "proposed": {}})
    monkeypatch.setattr(policy_engine, "evaluate",
                        lambda *a, **k: policy_engine.Verdict(False, "business:automations_paused", "paused", None))
    audits = _audit(monkeypatch)
    monkeypatch.setattr(chief_bookkeeping, "approve_proposal",
                        lambda *a, **k: pytest.fail("refused by policy, must not run"))
    rr._run_trusted_sweep_sync()
    assert fake.rows("chief_bookkeeping_proposals")[-1]["status"] == "pending"
    assert any(k.get("payload", {}).get("held_count") == 1 for a, k in audits)


# ─── The map itself ─────────────────────────────────────────────────────

def test_every_grantable_type_names_a_hand_and_a_registry_verb():
    import action_registry
    for t in rr.GRANTABLE_TYPES:
        assert t in rr.HAND_OF, t
        verb = rr._PROPOSAL_EQUIVALENT_VERB[t]
        assert verb in action_registry.REGISTRY, (t, verb)
    assert rr.EXECUTABLE_BOOKKEEPING_TYPES == {"propose_categorize", "propose_match", "propose_exclude"}
    assert not (rr.EXECUTABLE_BOOKKEEPING_TYPES & rr.EXECUTABLE_PROPOSAL_TYPES)


def test_the_bookkeepers_verb_is_class_c_and_the_grant_is_the_only_way_in():
    """The registry is the ceiling: a granted bookkeeping category runs a
    class-C verb unattended, exactly like a granted follow-up email runs
    draft_and_send. The policy engine records it; the practitioner's
    explicit grant is what authorised it."""
    import action_registry
    assert action_registry.reversibility("approve_bookkeeping_proposal") == "C"
    assert not action_registry.is_autonomy_eligible("approve_bookkeeping_proposal")
