"""Report words in the business's voice, on the server.

Kevin, 2026-11-03: "some of the language is stuff that goes for coaching
and consultant members and stuff but not for churches."

The server half of src/core/components/bookkeeping/reports/reportWords.ts.
What the server writes into a report (account names, journal labels, the
CSV and PDF rows and titles) reads in church words for a church (vertical
ministry) or a nonprofit; a business reads exactly what it read before.
Display only: no account, entry or amount changes, so an accountant's
import still matches by account code.
"""
from __future__ import annotations

from typing import Dict, Optional
from urllib.parse import quote

BUSINESS, CHURCH, NONPROFIT = "business", "church", "nonprofit"


def voice_of(business_type: Optional[str]) -> str:
    try:
        import vertical_registry
        if vertical_registry.resolve(business_type or "") == "ministry":
            return CHURCH
    except Exception:
        pass
    try:
        import vertical_family
        if vertical_family.is_nonprofit_like(business_type):
            return NONPROFIT
    except Exception:
        pass
    return BUSINESS


def voice_for(biz: str) -> str:
    """The voice of a business by id. A read that fails reads as business:
    a label never breaks a report."""
    try:
        import sb_clients
        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{quote(str(biz), safe='')}&select=type&limit=1") or []
        return voice_of(rows[0].get("type") if rows else None)
    except Exception:
        return BUSINESS


def is_faith(voice: Optional[str]) -> bool:
    return voice in (CHURCH, NONPROFIT)


def _org(voice: Optional[str]) -> str:
    return "the Church" if voice == CHURCH else "the Organization"


# ─── Account names ──────────────────────────────────────────────────
# A church's books keep the same codes; only the names a person reads change.
# 3100/3200 hold deposits and withdrawals nobody has sorted yet (and owner
# money, which a church doesn't have), so they say that.
_FAITH_ACCOUNTS = {
    "1150": "Online gifts on the way (Stripe clearing)",
    "1160": "Gifts to deposit",
    "3000": "Opening balance (net assets)",
    "3100": "Unsorted deposits (net assets)",
    "3200": "Unsorted withdrawals (net assets)",
    "3900": "Net assets (prior years)",
    "4000": "Contributions",
    "4100": "Store & product sales",
}
_EXPENSE_LINE_OF = {"5000": "operating", "5100": "owner_pay", "5200": "tax", "5300": "savings", "5900": "other"}
_NONPROFIT_LINES = {"operating": "Programs & operations", "owner_pay": "Staff pay", "tax": "Taxes",
                    "savings": "Reserves", "other": "Other"}


def line_names(biz: str, voice: str) -> Dict[str, str]:
    """The five built-in spending lines (operating, owner_pay, tax, savings,
    other) by a church's or nonprofit's names. A line the church renamed
    keeps its own name; one still on the standard name ("Owner pay") reads
    as the church's. {} for a business."""
    if not is_faith(voice):
        return {}
    import expense_lines
    lines = dict(expense_lines.CHURCH if voice == CHURCH else _NONPROFIT_LINES)
    try:
        for key, name in expense_lines.names(biz).items():
            if key in lines and name and name != expense_lines.STANDARD.get(key):
                lines[key] = name
    except Exception:
        pass
    return lines


def account_names(biz: str, voice: Optional[str] = None) -> Dict[str, str]:
    """code -> the name this business reads, for the codes whose name
    changes. {} for a business: its chart's names stand."""
    v = voice or voice_for(biz)
    if not is_faith(v):
        return {}
    out = dict(_FAITH_ACCOUNTS)
    try:
        lines = line_names(biz, v)
        for code, key in _EXPENSE_LINE_OF.items():
            out[code] = lines[key]
    except Exception:
        pass
    return out


# ─── Journal labels ─────────────────────────────────────────────────
_FAITH_JOURNAL = {
    "Money in from the owner": "Money put in (not a gift)",
    "Owner draw": "Money taken out (not spending)",
    "Transfer in / uncategorized deposit": "Deposit not sorted yet",
    "Transfer out / income-categorized debit": "Money out, not sorted as spending",
    "Bank expense": "Paid from the bank",
    "Manual expense": "Spending entered by hand",
    "Payout deposit": "Online gifts deposited (Stripe payout)",
}
_INVOICE_JOURNAL = {
    # source_type: (a gift, a charge, not known: the lookup failed)
    "invoice_issue": ("Gift recorded", "Charge recorded", "Recorded"),
    "invoice_payment": ("Gift received", "Charge paid", "Payment received"),
    "invoice_refund": ("Gift refunded", "Charge refunded", "Refunded"),
}


def journal_label(description: str, source_type: Optional[str], voice: Optional[str],
                  is_gift: Optional[bool] = None) -> str:
    if not is_faith(voice):
        return description
    trio = _INVOICE_JOURNAL.get(source_type or "")
    if trio:
        # Not known (the gift lookup failed): a neutral church word, never
        # "Invoice", so the page reads the same everywhere.
        return trio[2] if is_gift is None else trio[0] if is_gift else trio[1]
    return _FAITH_JOURNAL.get(description, description)


# ─── Report titles and rows (CSV and PDF) ───────────────────────────
def title(report: str, default: str, voice: Optional[str]) -> str:
    if not is_faith(voice):
        return default
    org = _org(voice)
    giving = "Giving" if voice == CHURCH else "Contributions"
    return {
        "pl": "Income & Spending (Statement of Activities)",
        "balance_sheet": f"What {org} Has and Owes (Statement of Financial Position)",
        "cash_flow": "Cash In and Out (Statement of Cash Flows)",
        "revenue": f"{giving} & Income",
        "expenses_detail": "Spending",
        "ar_aging": f"Money Owed to {org}",
        "ap_aging": "Bills to Pay",
        "trends": f"{giving} Trends",
        "budget_vs_actual": "Budget vs Actual",
        "summary_1099": "1099s: Speakers & Contractors",
        "donors": "Givers" if voice == CHURCH else "Donor Report",
        "funds": "Funds: Given, Spent and Left",
    }.get(report, default)


_ROWS: Dict[str, Dict[str, str]] = {
    BUSINESS: {
        "revenue": "Revenue", "invoiced": "Invoiced", "invoiced_paid": "Invoiced (paid)",
        "refunds": "Refunds", "less_refunds": "Less refunds",
        "other_income": "Other (non-Stripe) income", "gross": "Gross Revenue",
        "expense": "Expense", "expenses": "EXPENSES", "no_expenses": "No expenses in this period",
        "total_expenses": "Total Expenses", "net": "Net", "net_income": "Net Income",
        "net_income_head": "NET INCOME", "revenue_head": "REVENUE",
        "operating_row": "Operating Activity", "operating_head": "OPERATING ACTIVITIES",
        "cash_in": "Cash from customers", "cash_out": "Cash to suppliers",
        "net_cash": "Net cash from operations",
        "assets": "Assets", "assets_head": "ASSETS", "cash": "Cash", "cash_bank": "Cash (bank balances)",
        "ar": "Accounts Receivable", "total_assets": "Total Assets",
        "clearing": "Stripe Clearing (in transit, informational)",
        "liabilities": "Liabilities", "liabilities_head": "LIABILITIES", "ap": "Accounts Payable",
        "total_liabilities": "Total Liabilities", "equity": "Equity", "equity_head": "EQUITY",
        "retained": "Retained Earnings", "total_equity": "Total Equity",
        "balanced": "✓ Balanced — Liabilities + Equity = Total Assets",
    },
}


def _faith_rows(voice: str) -> Dict[str, str]:
    org = _org(voice).lower()
    giving = "giving" if voice == CHURCH else "contributions"
    return {
        "revenue": "Income", "invoiced": "Gifts and paid charges", "invoiced_paid": "Gifts and paid charges",
        "refunds": "Refunds", "less_refunds": "Less refunds",
        "other_income": "Other money in (bank deposits)", "gross": "Total income",
        "expense": "Spending", "expenses": "SPENDING", "no_expenses": "No spending in this period",
        "total_expenses": "Total spending", "net": "Surplus", "net_income": "Surplus (or shortfall)",
        "net_income_head": "SURPLUS (OR SHORTFALL)", "revenue_head": f"{giving.upper()} & INCOME",
        "operating_row": "Day-to-day money", "operating_head": "DAY-TO-DAY MONEY",
        "cash_in": f"Cash from {giving} & income", "cash_out": "Cash paid out", "net_cash": "Net cash",
        "assets": f"What {org} has", "assets_head": f"WHAT {org.upper()} HAS",
        "cash": "Money in the bank", "cash_bank": "Money in the bank",
        "ar": f"Money owed to {org}", "total_assets": "Total",
        "clearing": "Online gifts on the way (Stripe clearing)",
        "liabilities": f"What {org} owes", "liabilities_head": f"WHAT {org.upper()} OWES",
        "ap": "Unpaid bills", "total_liabilities": "Total",
        "equity": "Net assets", "equity_head": "NET ASSETS",
        "retained": "Net assets", "total_equity": "Total net assets",
        "balanced": "✓ The books balance: what is owed plus net assets equals what it has",
    }


_ROWS[CHURCH] = _faith_rows(CHURCH)
_ROWS[NONPROFIT] = _faith_rows(NONPROFIT)


def rows(voice: Optional[str]) -> Dict[str, str]:
    """The row labels for a report export in this voice."""
    return _ROWS.get(voice or BUSINESS, _ROWS[BUSINESS])
