"""Phase H.3a v1.2 — PDF design system. Pure-helper tests + a full render
smoke for every report type (skips if reportlab is unavailable)."""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import pdf_reports as p


def _reportlab():
    try:
        import reportlab  # noqa: F401
        return True
    except Exception:
        return False


# ── pure helpers ────────────────────────────────────────────────────

def test_fmt_money_accounting():
    assert p.fmt_money(1825.77) == "$1,825.77"
    assert p.fmt_money(-1234.5) == "($1,234.50)"     # negatives in parens
    assert p.fmt_money(0) == "—"
    assert p.fmt_money(None) == "—"
    assert p.fmt_money(0.004) == "—"                 # rounds to zero
    assert p.fmt_money("notnum") == "—"


def test_fmt_pct():
    assert p.fmt_pct(12.3) == "+12.3%"
    assert p.fmt_pct(-5) == "-5.0%"
    assert p.fmt_pct(None) == "—"


def test_resolve_brand_default_and_set():
    d = p.resolve_brand(None)
    assert d["accent"] == p.SOLUTIONIST_ACCENT and d["logo_url"] is None
    s = p.resolve_brand({"branding": {"accent_color": "#123456", "logo_url": "http://x/l.png"}})
    assert s["accent"] == "#123456" and s["has_business_logo"] is True
    # Bad hex falls back to the Solutionist accent.
    assert p.resolve_brand({"branding": {"accent_color": "notahex"}})["accent"] == p.SOLUTIONIST_ACCENT


def test_build_meta():
    m = p.build_meta(business_name="KMJ", settings={"branding": {"accent_color": "#222"}},
                     report_title="Balance Sheet", period_label="As of June 9, 2026",
                     generated_by="kevin@x.com")
    assert m["report_title"] == "Balance Sheet"
    assert m["currency_label"] == "Amounts in USD"
    assert m["brand"]["accent"] == "#222"
    assert "/" in m["generated_at"] and (":" in m["generated_at"])


# ── full render smoke (real reportlab output) ───────────────────────

_SAMPLES = {
    "balance_sheet": {"as_of": "2026-06-09", "assets": {"cash": 5000, "accounts_receivable": 2000, "total": 7000},
                      "liabilities": {"accounts_payable": 1500, "total": 1500},
                      "equity": {"retained_earnings": 5500, "total": 5500}},
    "pl": {"range": {"from": "2026-06-01", "to": "2026-06-30"},
           "current": {"revenue": {"invoiced": 1000, "refunds": 40, "plaid_other_income": 300, "gross_revenue": 1260},
                       "expenses": {"total": 350, "by_bucket": [{"bucket": "operating", "label": "Operating", "total": 350,
                                    "pct": 100.0, "lines": [{"subcategory": "software", "amount": 150}]}]},
                       "net_income": 910},
           "comparison": {"change": {"gross_revenue": 12.5, "total_expenses": -3.0, "net_income": 20.0}}},
    "ar_aging": {"as_of": "2026-06-09", "buckets": {"current": 100, "d1_30": 0, "d31_60": 200, "d61_90": 0, "d90_plus": 300},
                 "total_outstanding": 600, "at_risk": 300, "by_contact": [{"contact": "Bob", "total": 500, "count": 2}],
                 "invoices": [{"id": "1", "invoice_number": "INV-1", "contact": "Bob", "total": 300,
                               "due_date": "2026-02-09", "bucket": "d90_plus", "days_overdue": 120}]},
    "ap_aging": {"as_of": "2026-06-09", "buckets": {"current": 2500, "d1_30": 0, "d31_60": 99, "d61_90": 0, "d90_plus": 0},
                 "total_outstanding": 2599, "at_risk": 0, "by_vendor": [{"vendor": "Rent Co", "total": 2500, "count": 1}],
                 "bills": [{"id": "b1", "vendor": "Rent Co", "amount": 2500, "due_date": "2026-06-30",
                            "bucket": "current", "days_overdue": 0}]},
    "cash_flow": {"range": {"from": "2026-06-01", "to": "2026-06-30"},
                  "operating": {"cash_from_customers": 1300, "cash_to_suppliers": 600, "net_cash_from_operations": 700},
                  "note": "Operating activities only."},
    "reconciliation": {"matched": [{"reconciled_to_payout_id": "po_1abcdef234567", "reconciled_payout_date": "2026-06-02",
                                    "amount": -1000, "name": "Stripe payout", "reconciliation_status": "auto_matched"}],
                       "unmatched_plaid": [{"date": "2026-06-07", "name": "Check deposit", "amount": -300}],
                       "unmatched_stripe": [{"arrival_date": "2026-06-03", "stripe_payout_id": "po_zzz999", "amount": 500}]},
}


@pytest.mark.skipif(not _reportlab(), reason="reportlab not installed")
@pytest.mark.parametrize("key", list(_SAMPLES.keys()))
def test_render_produces_valid_pdf(key):
    meta = p.build_meta(business_name="KMJ Creative Solutions",
                        settings={"branding": {"accent_color": "#2E5E4E"}},
                        report_title=key, period_label="As of June 9, 2026", generated_by="kevin@x.com")
    pdf = p.render(key, _SAMPLES[key], meta)
    assert pdf[:5] == b"%PDF-" and len(pdf) > 1000


@pytest.mark.skipif(not _reportlab(), reason="reportlab not installed")
def test_render_multipage_and_long_name():
    invs = [{"id": str(i), "invoice_number": f"INV-{i}", "contact": f"Client {i % 9}", "total": 100 + i,
             "due_date": "2026-03-01", "bucket": "d90_plus", "days_overdue": 100 + i} for i in range(200)]
    d = dict(_SAMPLES["ar_aging"]); d["invoices"] = invs
    meta = p.build_meta(business_name="A Very Long Business Name That Should Truncate In The Header Band",
                        settings=None, report_title="AR Aging", period_label="As of June 9, 2026",
                        generated_by="kevin@x.com", confidential=True)
    pdf = p.render("ar_aging", d, meta)
    assert pdf[:5] == b"%PDF-"


@pytest.mark.skipif(not _reportlab(), reason="reportlab not installed")
def test_render_unreachable_logo_degrades():
    meta = p.build_meta(business_name="KMJ",
                        settings={"branding": {"logo_url": "http://127.0.0.1:9/nope.png", "accent_color": "#333"}},
                        report_title="Balance Sheet", period_label="As of X", generated_by="x")
    pdf = p.render("balance_sheet", _SAMPLES["balance_sheet"], meta)
    assert pdf[:5] == b"%PDF-"      # logo fetch fails → no logo, no crash
