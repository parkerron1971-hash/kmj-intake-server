"""Phase I.1 — General Ledger — generator balance + GL↔H.3a reconciliation.

The reconciliation test runs the GL engine AND the H.3a reports engine over an
IDENTICAL synthetic KMJ-like dataset and asserts they agree to the cent. This
is the in-session proxy for the I.1b smoke gate (which runs against real data).
"""
from __future__ import annotations

import sys
import pathlib
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import gl_engine as gl
import reports_engine as re_


# ── A synthetic, self-consistent money dataset ──────────────────────
#   Cash on hand 5,000. One paid invoice (Stripe), one unpaid invoice,
#   one refund, one manual expense, one bill (unpaid), one paid bill,
#   plaid: a payout deposit, a non-Stripe income inflow, an expense debit.
TODAY = re_._today()
INVOICES = [
    {"id": "inv_paid", "total": 1000, "status": "paid", "paid_at": "2026-06-01T00:00:00Z",
     "sent_at": "2026-05-20T00:00:00Z", "created_at": "2026-05-20T00:00:00Z", "due_date": "2026-06-01",
     "payment_method": "Stripe", "stripe_payment_url": "https://x", "refund_amount_cents": None, "refunded_at": None},
    {"id": "inv_open", "total": 600, "status": "sent", "paid_at": None,
     "sent_at": "2026-06-02T00:00:00Z", "created_at": "2026-06-02T00:00:00Z", "due_date": "2026-06-20",
     "payment_method": None, "stripe_payment_url": "https://x", "refund_amount_cents": None, "refunded_at": None},
    {"id": "inv_ref", "total": 400, "status": "paid", "paid_at": "2026-06-03T00:00:00Z",
     "sent_at": "2026-05-25T00:00:00Z", "created_at": "2026-05-25T00:00:00Z", "due_date": "2026-06-03",
     "payment_method": "Stripe", "stripe_payment_url": "https://x", "refund_amount_cents": 4000, "refunded_at": "2026-06-05T00:00:00Z"},
]
EXPENSES = [{"id": "exp1", "amount": 150, "category": "operating", "subcategory": "software",
             "vendor": "SaaS", "date": "2026-06-04"}]
BILLS = [
    {"id": "bill_open", "vendor_name": "Rent Co", "amount": 2500, "category": "operating",
     "status": "pending", "due_date": "2026-06-30", "created_at": "2026-06-01T00:00:00Z",
     "paid_at": None, "paid_amount": None},
    {"id": "bill_paid", "vendor_name": "Utility", "amount": 200, "category": "operating",
     "status": "paid", "due_date": "2026-06-05", "created_at": "2026-06-01T00:00:00Z",
     "paid_at": "2026-06-06T00:00:00Z", "paid_amount": 200},
]
PLAID = [
    {"transaction_id": "px_payout", "amount": -1000, "date": "2026-06-02", "business_category": None,
     "business_subcategory": None, "plaid_category_primary": "INCOME", "plaid_category_detail": None,
     "reconciled_to_payout_id": "po_1"},
    {"transaction_id": "px_income", "amount": -300, "date": "2026-06-07", "business_category": None,
     "business_subcategory": None, "plaid_category_primary": "INCOME", "plaid_category_detail": "INCOME_WAGES",
     "reconciled_to_payout_id": None},
    {"transaction_id": "px_exp", "amount": 250, "date": "2026-06-08", "business_category": "operating",
     "business_subcategory": "fuel", "plaid_category_primary": "TRANSPORTATION", "plaid_category_detail": None,
     "reconciled_to_payout_id": None},
]
CASH_ON_HAND = 5000.0


# ── Minimal PostgREST filter simulator (so H.3a's filter-reliant queries are
#    applied the same way the real DB would — makes the GL↔H.3a comparison real)
def _num(x):
    try:
        return float(x)
    except Exception:
        return None


def _passes(row, col, op, target):
    if op in ("is", "not.is"):       # null checks
        isnull = row.get(col) is None
        return isnull if op == "is" else (not isnull)
    val = row.get(col)
    if val is None:
        return True                  # missing column → constraint not applicable
    if op == "in":
        return str(val) in target.strip("()").split(",")
    if op == "not.in":
        return str(val) not in target.strip("()").split(",")
    if target in ("true", "false"):
        return (bool(val) is (target == "true")) if op == "eq" else (bool(val) is not (target == "true"))
    nv, nt = _num(val), _num(target)
    if nv is not None and nt is not None:
        return {"eq": nv == nt, "neq": nv != nt, "gte": nv >= nt, "lte": nv <= nt,
                "lt": nv < nt, "gt": nv > nt}.get(op, True)
    sv, stt = str(val), str(target)
    return {"eq": sv == stt, "neq": sv != stt, "gte": sv >= stt, "lte": sv <= stt,
            "lt": sv < stt, "gt": sv > stt}.get(op, True)


def _apply(rows, path):
    q = path.split("?", 1)[1] if "?" in path else ""
    constraints = []
    for part in q.split("&"):
        if "=" not in part:
            continue
        col, rest = part.split("=", 1)
        if col in ("select", "limit", "order", "on_conflict"):
            continue
        if rest.startswith("not.is."):
            constraints.append((col, "not.is", None))
        elif rest.startswith("is."):
            constraints.append((col, "is", None))
        elif rest.startswith("not.in."):
            constraints.append((col, "not.in", rest[len("not.in."):]))
        elif rest.startswith("in."):
            constraints.append((col, "in", rest[len("in."):]))
        elif "." in rest:
            op, target = rest.split(".", 1)
            constraints.append((col, op, target))
    return [r for r in rows if all(_passes(r, c, o, t) for c, o, t in constraints)]


def _route(path: str):
    if path.startswith("/invoices"):
        return _apply(INVOICES, path)
    if path.startswith("/business_expenses"):
        return _apply(EXPENSES, path)
    if path.startswith("/bills"):
        return _apply(BILLS, path)
    if "type=eq.depository" in path:
        return [{"last_balance": CASH_ON_HAND}]
    if path.startswith("/plaid_accounts"):
        return [{"account_id": "acc1"}]
    if path.startswith("/plaid_transactions"):
        return _apply(PLAID, path)
    return []


@pytest.fixture
def mocked(monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _route)


def _gen_lines():
    return gl._lines_from_specs(gl.generate_entries(gl._fetch_sources("biz1")))


def test_every_journal_entry_balances(mocked):
    specs = gl.generate_entries(gl._fetch_sources("biz1"))
    for s in specs:
        deb = round(sum(l["debit"] for l in s["lines"]), 2)
        cred = round(sum(l["credit"] for l in s["lines"]), 2)
        assert deb == cred, f"{s['source_type']} unbalanced: {deb} != {cred}"


def test_trial_balance_is_zero(mocked):
    tb = gl.trial_balance(_gen_lines())
    assert tb["difference"] == 0.0


def test_gl_cash_equals_bank_snapshot(mocked):
    # Opening-balance plug forces GL Cash to the current bank balance.
    assert gl.gl_cash(_gen_lines()) == CASH_ON_HAND


def test_gl_matches_h3a_reports(mocked):
    """The crux: GL (cash-basis, from ledger) == H.3a engine, to the cent."""
    lines = _gen_lines()
    start, end = date(2000, 1, 1), TODAY

    gl_pl = gl.gl_pl_cash_basis(lines, start, end)
    h_pl = re_.profit_and_loss("biz1", "custom", None, start.isoformat(), end.isoformat())["current"]
    assert gl_pl["revenue"] == h_pl["revenue"]["gross_revenue"]
    assert gl_pl["expenses"] == h_pl["expenses"]["total"]
    assert gl_pl["net_income"] == h_pl["net_income"]

    assert gl.gl_ar(lines) == re_.ar_aging("biz1")["total_outstanding"]
    assert gl.gl_ap(lines) == re_.ap_aging("biz1")["total_outstanding"]
    assert gl.gl_cash(lines) == re_.balance_sheet("biz1")["assets"]["cash"]


def test_backfill_idempotent_skips_existing(monkeypatch):
    import sb_clients
    # All source reads route normally; journal_entries already has every key.
    specs = gl.generate_entries(gl._fetch_sources_stub())  # built below
    keys = {(s["source_type"], s["source_id"]) for s in specs}

    def _get(path):
        if path.startswith("/journal_entries"):
            return [{"source_type": st, "source_id": sid} for st, sid in keys]
        if path.startswith("/chart_of_accounts"):
            return [{"id": f"a_{c[0]}", "code": c[0]} for c in gl.COA_SEED]
        return _route(path)

    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda *a, **k: pytest.fail("idempotent backfill must not insert"))
    out = gl.backfill("biz1", "consultant")
    assert out["journal_entries_created"] == 0 and out["skipped_existing"] > 0


# helper used by the idempotency test (same dataset, no DB)
def _fetch_sources_stub():
    return {"invoices": INVOICES, "expenses": EXPENSES, "bills": BILLS,
            "plaid": PLAID, "cash_on_hand": CASH_ON_HAND}


gl._fetch_sources_stub = _fetch_sources_stub  # type: ignore
