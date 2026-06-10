"""Phase I.5 — Chief GL integration: analyzers + approve execution, end-to-end
against the in-memory Supabase fake (real backfilled ledger)."""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest

from test_i2_gl_sync import FakeSB
import gl_engine as gl
import gl_reports as glr
import chief_bookkeeping as cb


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    fb.rows("businesses").append({"id": "biz1", "type": "consultant", "owner_id": "owner"})
    fb.rows("plaid_accounts").append({
        "account_id": "acc1", "business_id": "biz1", "type": "depository",
        "included_in_bookkeeping": True, "deleted_at": None, "last_balance": 5000})
    fb.t["invoices"] = [{"id": "inv1", "business_id": "biz1", "total": 1000, "status": "paid",
                         "paid_at": "2026-06-01T00:00:00Z", "sent_at": "2026-05-20T00:00:00Z",
                         "created_at": "2026-05-20T00:00:00Z", "due_date": "2026-06-01",
                         "payment_method": "Stripe", "stripe_payment_url": "x",
                         "refund_amount_cents": None, "refunded_at": None}]
    gl.backfill("biz1", "consultant")
    return fb


def test_no_proposals_when_books_match_bank(fake):
    # Backfill plugs Cash to the bank snapshot → no drift, no closed year.
    assert cb.analyze_gl("biz1") == []


def test_reconciliation_proposal_on_drift_and_approve_fixes(fake):
    fb = fake
    # Bank balance moves (new deposit at the bank, queue not yet drained).
    fb.rows("plaid_accounts")[0]["last_balance"] = 6200
    created = cb.analyze_gl("biz1")
    assert len(created) == 1 and created[0]["proposal_type"] == "propose_account_reconciliation"
    assert created[0]["proposed"]["drift"] == 1200.0
    # Re-analyze → no duplicate while pending.
    assert cb.analyze_gl("biz1") == []
    # Approve → process_queue + opening true-up → GL Cash == bank again.
    out = cb.approve_proposal("biz1", created[0]["id"], approved_by="owner")
    assert out["executed"] == "propose_account_reconciliation"
    assert gl.gl_cash(glr.effective_lines("biz1")) == 6200
    # Trial balance still $0.
    assert gl.trial_balance(glr.effective_lines("biz1"))["difference"] == 0.0
    # Drift resolved → analyzer stays quiet.
    assert cb.analyze_gl("biz1") == []


def test_obe_reclass_proposed_after_year_close_and_approve_posts(fake):
    fb = fake
    # Close the year (creates the closed-year precondition).
    fb.rows("accounting_periods").append({
        "id": "yr", "business_id": "biz1", "period_type": "year",
        "period_start": "2026-01-01", "period_end": "2026-12-31", "status": "open"})
    gl.close_period("biz1", "yr", closed_by="owner")
    obe_before = glr._net(glr.effective_lines("biz1"), "3000", normal="credit")
    assert abs(obe_before) >= 0.01      # opening plug exists in this dataset
    created = cb.analyze_gl("biz1")
    je = next(p for p in created if p["proposal_type"] == "propose_journal_entry")
    # Proposed lines are balanced.
    deb = sum(l["debit"] for l in je["proposed"]["lines"])
    cred = sum(l["credit"] for l in je["proposed"]["lines"])
    assert round(deb - cred, 2) == 0.0
    # Approve → OBE zeroed into Owner's Equity; trial balance still $0.
    out = cb.approve_proposal("biz1", je["id"], approved_by="owner")
    assert out["executed"] == "propose_journal_entry"
    lines = glr.effective_lines("biz1")
    assert glr._net(lines, "3000", normal="credit") == 0.0
    assert gl.trial_balance(lines)["difference"] == 0.0


def test_unbalanced_manual_entry_rejected(fake):
    import sb_clients
    res = sb_clients.sb_post_as_service("/chief_bookkeeping_proposals", {
        "business_id": "biz1", "proposal_type": "propose_journal_entry", "status": "pending",
        "proposed": {"description": "bad", "lines": [
            {"code": "3000", "debit": 100, "credit": 0},
            {"code": "3100", "debit": 0, "credit": 50}]},
    })
    pid = res[0]["id"]
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        cb.approve_proposal("biz1", pid, approved_by="owner")
    assert e.value.status_code == 400


def test_gl_context_lines_present(fake):
    ctx = cb._gl_context_lines("biz1")
    assert any("GENERAL LEDGER" in l for l in ctx)
    assert any("Trial balance: balanced" in l for l in ctx)
    # Tight: the GL block stays small (prompt-budget discipline).
    assert len(ctx) <= 5
