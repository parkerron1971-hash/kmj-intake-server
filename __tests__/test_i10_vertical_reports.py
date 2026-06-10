"""Phase I.10 — Tier-4 vertical compliance reports."""
from __future__ import annotations

import sys
import pathlib

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import gl_engine as gl  # noqa: E402
import gl_reports_t4 as t4  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    return fb


def _trust_tx(fb, tid, amount, *, contact=None, d="2026-06-05"):
    fb.rows("plaid_transactions").append({
        "transaction_id": tid, "business_id": "law1", "account_id": "trust_a",
        "amount": amount, "date": d, "pending": False, "excluded_from_books": False,
        "name": "Wire", "merchant_name": None, "business_category": None,
        "business_subcategory": None, "plaid_category_primary": None,
        "plaid_category_detail": None, "reconciled_to_payout_id": None,
        "trust_contact_id": contact})


def test_trust_reconciliation_three_way_and_subbalances(fake):
    fb = fake
    fb.rows("businesses").append({"id": "law1", "type": "lawyer", "owner_id": "o"})
    fb.rows("plaid_accounts").append({
        "account_id": "trust_a", "business_id": "law1", "type": "depository",
        "included_in_bookkeeping": True, "is_trust_account": True,
        "deleted_at": None, "last_balance": 600.0, "name": "IOLTA", "mask": "1234"})
    _trust_tx(fb, "t1", -1000, contact="c1")   # deposit for client c1
    _trust_tx(fb, "t2", 400, contact="c1")     # disbursement for c1
    _trust_tx(fb, "t3", -200, contact=None)    # untagged deposit... bank 600 → plug -200
    gl.backfill("law1", "lawyer")
    out = t4.trust_reconciliation("law1")
    tw = out["three_way"]
    assert tw["gl_trust_cash"] == 600.0 == tw["client_funds_liability"]
    assert tw["bank_trust_balance"] == 600.0
    assert tw["ledger_in_balance"] and tw["matches_bank"]
    clients = {c["trust_contact_id"]: c for c in out["by_client"]}
    assert clients["c1"]["deposits"] == 1000.0
    assert clients["c1"]["disbursements"] == 400.0
    assert clients["c1"]["balance"] == 600.0
    assert clients[None]["balance"] == 200.0           # untagged surfaced
    assert out["opening_plug"] == -200.0               # bank 600 vs activity 800
    assert len(out["activity"]) == 3


def test_donor_report_restricted_split(fake):
    fb = fake
    fb.rows("businesses").append({"id": "np1", "type": "nonprofit", "owner_id": "o"})
    fb.rows("contacts").append({"id": "d1", "name": "Big Donor", "email": "d@x.com"})
    for iid, total, cat in (("g1", 1000, "restricted"), ("g2", 250, "general")):
        fb.rows("invoices").append({
            "id": iid, "business_id": "np1", "total": total, "status": "paid",
            "paid_at": "2026-06-05T00:00:00Z", "sent_at": "2026-06-01T00:00:00Z",
            "created_at": "2026-06-01T00:00:00Z", "due_date": "2026-06-10",
            "payment_method": "check", "stripe_payment_url": None,
            "refund_amount_cents": None, "refunded_at": None, "category": cat,
            "contact_id": "d1", "contacts": {"name": "Big Donor", "email": "d@x.com"}})
    gl.backfill("np1", "nonprofit")
    out = t4.donor_report("np1", "custom", "2026-06-01", "2026-06-30")
    assert out["total_gifts"] == 1250.0
    assert out["restricted_gifts"] == 1000.0
    assert out["unrestricted_gifts"] == 250.0
    assert out["donors"][0]["donor"] == "Big Donor"
    # GL split ties out: restricted invoice booked to 4200 (I.10 mechanic).
    assert out["gl_split"]["restricted_4200"] == 1000.0
    assert out["gl_split"]["unrestricted"] == 250.0


def test_restricted_routing_is_nonprofit_only(fake):
    fb = fake
    inv = {"id": "i1", "total": 100, "status": "sent", "sent_at": "2026-06-01T00:00:00Z",
           "created_at": None, "due_date": None, "payment_method": None,
           "stripe_payment_url": "x", "refund_amount_cents": None, "refunded_at": None,
           "category": "restricted"}
    np_specs = gl.desired_for_invoice(inv, "nonprofit")
    assert any(l["code"] == "4200" for s in np_specs for l in s["lines"])
    barber_specs = gl.desired_for_invoice(inv, "barber")
    assert all(l["code"] != "4200" for s in barber_specs for l in s["lines"])
    assert any(l["code"] == "4000" for s in barber_specs for l in s["lines"])


def test_prep_990_packet_and_sme_flags(fake):
    fb = fake
    fb.rows("businesses").append({"id": "np1", "type": "nonprofit", "owner_id": "o"})
    fb.rows("invoices").append({
        "id": "g1", "business_id": "np1", "total": 500, "status": "paid",
        "paid_at": "2026-03-05T00:00:00Z", "sent_at": "2026-03-01T00:00:00Z",
        "created_at": "2026-03-01T00:00:00Z", "due_date": "2026-03-10",
        "payment_method": "check", "stripe_payment_url": None,
        "refund_amount_cents": None, "refunded_at": None, "category": "restricted",
        "contact_id": None})
    fb.rows("business_expenses").append({
        "id": "e1", "business_id": "np1", "amount": 120, "category": "operating",
        "subcategory": None, "vendor": "V", "date": "2026-04-02"})
    gl.backfill("np1", "nonprofit")
    out = t4.prep_990("np1", 2026)
    contrib = {c["code"]: c["amount"] for c in out["contributions"]}
    assert contrib["4200"] == 500.0
    fx = {f["bucket"]: f["amount"] for f in out["functional_expenses"]}
    assert fx["operating"] == 120.0
    assert out["change_in_net_assets"] == 380.0
    assert any("Functional expense" in f for f in out["sme_flags"])
    assert any(n["code"] == "3300" for n in out["net_assets"])  # always listed


def test_bank_reconciliation_computed_balances(fake):
    fb = fake
    fb.rows("businesses").append({"id": "b1", "type": "consultant", "owner_id": "o"})
    fb.rows("plaid_accounts").append({
        "account_id": "a1", "business_id": "b1", "type": "depository",
        "included_in_bookkeeping": True, "is_trust_account": False,
        "deleted_at": None, "last_balance": 1000.0, "name": "Checking", "mask": "9999"})
    rows = fb.rows("plaid_transactions")
    # In-period: +500 deposit, −200 withdrawal. After period: +300 deposit.
    rows.append({"transaction_id": "x1", "business_id": "b1", "account_id": "a1",
                 "amount": -500, "date": "2026-06-10", "pending": False,
                 "excluded_from_books": False})
    rows.append({"transaction_id": "x2", "business_id": "b1", "account_id": "a1",
                 "amount": 200, "date": "2026-06-12", "pending": False,
                 "excluded_from_books": False})
    rows.append({"transaction_id": "x3", "business_id": "b1", "account_id": "a1",
                 "amount": -300, "date": "2026-07-02", "pending": False,
                 "excluded_from_books": False})
    out = t4.bank_reconciliation("b1", "custom", "2026-06-01", "2026-06-30")
    a = out["accounts"][0]
    assert a["ending_balance"] == 700.0      # current 1000 − post-period +300
    assert a["deposits"] == 500.0 and a["withdrawals"] == 200.0
    assert a["beginning_balance"] == 400.0   # 700 − (500 − 200)
    assert out["operating_ending_total"] == 700.0


def test_audit_trail_report(fake):
    fb = fake
    fb.rows("period_edit_overrides").append({
        "id": "o1", "business_id": "b1", "source_type": "invoice", "source_id": "i1",
        "override_reason": "client corrected the amount", "override_by_role": "owner",
        "override_at": "2026-06-08T12:00:00Z", "accounting_period_id": None})
    out = t4.audit_trail("b1")
    assert out["count"] == 1
    assert out["entries"][0]["reason"] == "client corrected the amount"


def test_pdf_render_smoke_t4(fake):
    pytest.importorskip("reportlab")
    import pdf_reports
    meta = pdf_reports.build_meta(business_name="B", settings=None, report_title="T",
                                  period_label="2026", basis_label="Cash Basis",
                                  currency="USD", generated_by="smoke")
    samples = {
        "trust_reconciliation": {"three_way": {"gl_trust_cash": 1, "client_funds_liability": 1,
                                               "bank_trust_balance": 1, "ledger_in_balance": True,
                                               "matches_bank": True},
                                 "by_client": [{"client": "A", "deposits": 2, "disbursements": 1,
                                                "balance": 1}],
                                 "activity": [{"date": "2026-06-01", "description": "Wire",
                                               "type": "deposit", "client": "A", "amount": 2}],
                                 "opening_plug": 0, "note": "n"},
        "donors": {"total_gifts": 3, "restricted_gifts": 1, "unrestricted_gifts": 2,
                   "donors": [{"donor": "D", "gifts": 1, "total": 3, "restricted": 1}],
                   "note": "n"},
        "prep_990": {"year": 2026, "contributions": [{"code": "4200", "name": "R", "amount": 1}],
                     "functional_expenses": [{"bucket": "operating", "amount": 1}],
                     "net_assets": [{"code": "3300", "name": "NA", "balance": 0}],
                     "change_in_net_assets": 0, "sme_flags": ["flag"]},
        "bank_reconciliation": {"accounts": [{"name": "C", "mask": "1", "is_trust_account": False,
                                              "beginning_balance": 1, "deposits": 2,
                                              "withdrawals": 1, "ending_balance": 2,
                                              "reconciling_items": {"pending_count": 0,
                                                                    "excluded_count": 0}}],
                                "gl_cash": {"operating_1000": 2, "trust_1200": 0},
                                "operating_ending_total": 2, "note": "n"},
        "audit_trail": {"entries": [{"at": "2026-06-08T12:00:00Z", "source_type": "invoice",
                                     "source_id": "i1", "by_role": "owner", "reason": "r"}]},
    }
    for k, d in samples.items():
        assert pdf_reports.render(k, d, meta)[:4] == b"%PDF", k
