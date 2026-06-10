"""Phase I.8 — Tier-2 reports (Revenue / Expense / Customer Statement)."""
from __future__ import annotations

import sys
import pathlib
from datetime import date

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import gl_engine as gl  # noqa: E402
import gl_reports_t2 as t2  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    fb.rows("businesses").append({"id": "biz1", "type": "consultant", "owner_id": "owner"})
    fb.rows("contacts").append({"id": "c1", "name": "Sarah Client", "email": "sarah@x.com", "phone": None})
    return fb


def _inv(fb, iid, total, status, *, sent="2026-06-01T00:00:00Z", paid=None,
         contact="c1", category="coaching", refund_cents=None, refunded=None,
         number=None, due="2026-06-20"):
    fb.rows("invoices").append({
        "id": iid, "business_id": "biz1", "invoice_number": number or iid.upper(),
        "total": total, "status": status, "sent_at": sent, "created_at": sent,
        "due_date": due, "paid_at": paid, "payment_method": None,
        "stripe_payment_url": "x", "refund_amount_cents": refund_cents,
        "refunded_at": refunded, "contact_id": contact, "category": category,
        "contacts": {"name": "Sarah Client", "email": "sarah@x.com"},
    })


def _expense(fb, eid, amount, *, category="operating", vendor="Acme", sub="software",
             d="2026-06-05"):
    fb.rows("business_expenses").append({
        "id": eid, "business_id": "biz1", "amount": amount, "category": category,
        "subcategory": sub, "vendor": vendor, "date": d})


def test_revenue_report_breakdowns(fake):
    fb = fake
    _inv(fb, "inv1", 400, "paid", paid="2026-06-10T00:00:00Z")
    _inv(fb, "inv2", 300, "sent", category="design")
    gl.backfill("biz1", "consultant")
    r = t2.revenue_report("biz1", "custom", "2026-06-01", "2026-06-30")
    assert r["total_revenue"] == 700.0                       # accrual: both issued
    assert r["by_account"][0]["code"] == "4000"
    assert r["by_account"][0]["amount"] == 700.0
    src = {x["source"]: x["amount"] for x in r["by_source"]}
    assert src == {"Invoiced revenue": 700.0}
    cust = {c["customer"]: c["amount"] for c in r["by_customer"]}
    assert cust == {"Sarah Client": 700.0}                   # ties to GL total
    offers = {o["offering"]: o["amount"] for o in r["by_offering"]}
    assert offers == {"coaching": 400.0, "design": 300.0}
    assert r["monthly"] == [{"month": "2026-06", "amount": 700.0}]


def test_revenue_report_refund_nets_out(fake):
    fb = fake
    _inv(fb, "inv1", 500, "paid", paid="2026-06-10T00:00:00Z",
         refund_cents=10000, refunded="2026-06-15T00:00:00Z")
    gl.backfill("biz1", "consultant")
    r = t2.revenue_report("biz1", "custom", "2026-06-01", "2026-06-30")
    assert r["total_revenue"] == 400.0                       # 500 − 100 refund
    cust = {c["customer"]: c["amount"] for c in r["by_customer"]}
    assert cust == {"Sarah Client": 400.0}                   # breakdown ties out


def test_expense_report_breakdowns(fake):
    fb = fake
    _expense(fb, "e1", 120, vendor="Adobe", sub="software")
    _expense(fb, "e2", 80, vendor="Adobe", sub="software", d="2026-05-20")
    _expense(fb, "e3", 50, category="tax", vendor="IRS", sub="estimated")
    gl.backfill("biz1", "consultant")
    r = t2.expense_report("biz1", "custom", "2026-05-01", "2026-06-30")
    assert r["total_expenses"] == 250.0
    vendors = {v["vendor"]: v["amount"] for v in r["by_vendor"]}
    assert vendors == {"Adobe": 200.0, "IRS": 50.0}
    accounts = {a["code"]: a["amount"] for a in r["by_account"]}
    assert accounts == {"5000": 200.0, "5200": 50.0}
    months = {m["month"]: m["amount"] for m in r["monthly"]}
    assert months == {"2026-05": 80.0, "2026-06": 170.0}


def test_t2_reports_exclude_closing_entries(fake):
    fb = fake
    _inv(fb, "inv1", 400, "paid", paid="2026-06-10T00:00:00Z")
    gl.backfill("biz1", "consultant")
    # Simulate a year-end closing entry (Dr income / Cr retained earnings).
    res = fb.post("/journal_entries", {"business_id": "biz1", "entry_date": "2026-06-30",
                                       "source_type": "closing", "source_id": "per1",
                                       "status": "active", "description": "close"})
    je = res[0]
    for code, dr, cr, typ in (("4000", 400, 0, "income"), ("3900", 0, 400, "equity")):
        fb.post("/ledger_entries", {"business_id": "biz1", "journal_entry_id": je["id"],
                                    "account_code": code, "account_type": typ,
                                    "source_type": "closing", "debit": dr, "credit": cr,
                                    "entry_date": "2026-06-30", "profit_first_bucket": None,
                                    "subcategory": None, "vendor": None, "memo": ""})
    r = t2.revenue_report("biz1", "custom", "2026-06-01", "2026-06-30")
    assert r["total_revenue"] == 400.0                       # closing didn't wipe it


def test_customer_statement_running_balance_and_aging(fake):
    fb = fake
    _inv(fb, "inv1", 400, "paid", paid="2026-06-10T00:00:00Z")
    _inv(fb, "inv2", 300, "overdue", sent="2026-04-01T00:00:00Z", due="2026-04-15")
    st = t2.customer_statement("biz1", "c1", "2026-06-30")
    assert st["contact"]["name"] == "Sarah Client"
    assert [l["type"] for l in st["lines"]] == ["invoice", "invoice", "payment"]
    assert st["lines"][-1]["balance"] == 300.0               # only inv2 unpaid
    assert st["totals"] == {"invoiced": 700.0, "paid": 400.0, "refunded": 0.0,
                            "balance": 300.0}
    assert st["aging"]["d61_90"] == 300.0                    # due 4/15, as-of 6/30


def test_customer_statement_refund_credit(fake):
    fb = fake
    _inv(fb, "inv1", 500, "paid", paid="2026-06-10T00:00:00Z",
         refund_cents=50000, refunded="2026-06-12T00:00:00Z")
    st = t2.customer_statement("biz1", "c1", "2026-06-30")
    assert st["totals"]["balance"] == -500.0                 # full refund = credit
    assert st["lines"][-1]["type"] == "refund"


def test_statement_customers_list(fake):
    fb = fake
    _inv(fb, "inv1", 400, "sent")
    _inv(fb, "inv2", 300, "paid", paid="2026-06-10T00:00:00Z")
    out = t2.list_statement_customers("biz1")
    assert len(out) == 1
    assert out[0]["contact_id"] == "c1" and out[0]["invoices"] == 2


def test_pdf_render_smoke_for_t2_reports(fake):
    """Catch reportlab-level errors in the three new builders."""
    pytest.importorskip("reportlab")
    import pdf_reports
    fb = fake
    _inv(fb, "inv1", 400, "paid", paid="2026-06-10T00:00:00Z")
    _expense(fb, "e1", 120)
    gl.backfill("biz1", "consultant")
    meta = pdf_reports.build_meta(business_name="Biz", settings=None,
                                  report_title="T", period_label="June 2026",
                                  basis_label="Cash Basis", currency="USD",
                                  generated_by="test")
    for key, data in (
        ("revenue", t2.revenue_report("biz1", "custom", "2026-06-01", "2026-06-30")),
        ("expenses_detail", t2.expense_report("biz1", "custom", "2026-06-01", "2026-06-30")),
        ("customer_statement", t2.customer_statement("biz1", "c1", "2026-06-30")),
    ):
        blob = pdf_reports.render(key, data, meta)
        assert blob[:4] == b"%PDF"
