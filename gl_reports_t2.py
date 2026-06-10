"""
gl_reports_t2.py — Phase I.8 — Tier-2 reports on the General Ledger.

Revenue Report      — GL income accounts, drill-down by source / customer /
                      offering category / month. Customer + offering rows are
                      enriched from the invoices source table using the SAME
                      issue-date + refund rules as gl_engine.desired_for_invoice,
                      so they tie out to the GL income numbers.
Expense Report      — GL expense accounts, drill-down by account / vendor /
                      subcategory / month (vendor + subcategory live on
                      ledger lines since I.4 — pure GL, no source joins).
Customer Statement  — per-contact invoice/payment/refund history with running
                      balance + aging. Source-table report (works pre-GL).

Closing entries ("closing" + reversals) are structural — they zero income/
expense into Retained Earnings at year end — and are excluded from both
drill-down reports so a December report isn't wiped out by its own close.

Sales Tax Report is DEFERRED: invoicing has no tax capture anywhere (no
tax_rate/tax_amount fields, nothing posts to 2100 Sales Tax Payable), so the
report has no data source. Prerequisite is an invoicing tax feature — a
product ruling, surfaced to Kevin in the I.8 ship report.
"""
from __future__ import annotations

import logging
from datetime import date as _date
from typing import Any, Dict, List, Optional

import sb_clients
import gl_engine
import gl_reports
import reports_engine

logger = logging.getLogger("gl_reports_t2")

# code → display name, from the COA seed (single source of truth).
ACCOUNT_NAMES: Dict[str, str] = {
    c[0]: c[1] for c in (gl_engine.COA_SEED + gl_engine.COA_LAWYER_EXTRA
                         + gl_engine.COA_NONPROFIT_EXTRA)
}

# Structural source types excluded from revenue/expense drill-downs.
_STRUCTURAL = ("closing", "opening_balance", "trust_opening_balance")

_SOURCE_LABELS = {
    "invoice_issue": "Invoiced revenue",
    "invoice_refund": "Refunds",
    "plaid_transaction": "Bank-detected income",
}


def _is_structural(st: str) -> bool:
    return any(st == b or st == f"{b}_reversal" for b in _STRUCTURAL)


def _base_source(st: str) -> str:
    return st[:-len("_reversal")] if st.endswith("_reversal") else st


def _window_lines(biz: str, start: _date, end: _date) -> List[Dict[str, Any]]:
    return [l for l in gl_reports.effective_lines(biz)
            if gl_reports._in_window(l, start, end)
            and not _is_structural(str(l.get("source_type") or ""))]


def _month_key(l: Dict[str, Any]) -> str:
    return str(l.get("entry_date") or "")[:7]


def _issue_date(inv: Dict[str, Any]) -> Optional[_date]:
    """Mirror gl_engine.desired_for_invoice's issue-date rule exactly."""
    return (gl_engine._d(inv.get("sent_at")) or gl_engine._d(inv.get("created_at"))
            or gl_engine._d(inv.get("due_date")))


# ─── Revenue Report ──────────────────────────────────────────────────

def revenue_report(biz: str, period: str = "this_month",
                   custom_from: Optional[str] = None,
                   custom_to: Optional[str] = None) -> Dict[str, Any]:
    start, end = reports_engine.period_bounds(period, custom_from, custom_to)
    lines = _window_lines(biz, start, end)

    by_account: Dict[str, Dict[str, Any]] = {}
    by_source: Dict[str, float] = {}
    monthly: Dict[str, float] = {}
    total = 0.0
    for l in lines:
        if l.get("account_type") != "income":
            continue
        net = round(float(l["credit"]) - float(l["debit"]), 2)
        code = l["account_code"]
        acc = by_account.setdefault(code, {
            "code": code, "name": ACCOUNT_NAMES.get(code, code), "amount": 0.0})
        acc["amount"] = round(acc["amount"] + net, 2)
        src = _base_source(str(l.get("source_type") or ""))
        label = _SOURCE_LABELS.get(src, src or "Other")
        by_source[label] = round(by_source.get(label, 0.0) + net, 2)
        monthly[_month_key(l)] = round(monthly.get(_month_key(l), 0.0) + net, 2)
        total = round(total + net, 2)

    # Customer + offering drill-down from the invoices source table, using
    # the GL's own issue/refund dating so the breakdown ties to the totals.
    invoices = sb_clients.sb_get_as_service(
        f"/invoices?business_id=eq.{biz}"
        f"&status=in.({','.join(gl_engine._INVOICE_ISSUE_STATUSES)})"
        f"&select=id,invoice_number,total,status,category,sent_at,created_at,due_date,"
        f"paid_at,refund_amount_cents,refunded_at,contact_id,contacts(name)&limit=10000") or []
    by_customer: Dict[str, Dict[str, Any]] = {}
    by_offering: Dict[str, Dict[str, Any]] = {}
    for inv in invoices:
        amt = float(inv.get("total") or 0)
        if amt <= 0:
            continue
        issued = _issue_date(inv)
        in_win = bool(issued and start <= issued <= end)
        rc = inv.get("refund_amount_cents")
        refund = round(float(rc) / 100.0, 2) if rc and float(rc) > 0 else 0.0
        rdate = gl_engine._d(inv.get("refunded_at")) or gl_engine._d(inv.get("paid_at"))
        refund_in_win = bool(refund and rdate and start <= rdate <= end)
        if not in_win and not refund_in_win:
            continue
        name = ((inv.get("contacts") or {}) or {}).get("name") or "(no contact)"
        offering = inv.get("category") or "(uncategorized)"
        delta = round((amt if in_win else 0.0) - (refund if refund_in_win else 0.0), 2)
        c = by_customer.setdefault(name, {"customer": name, "amount": 0.0, "invoices": 0})
        c["amount"] = round(c["amount"] + delta, 2)
        c["invoices"] += 1 if in_win else 0
        o = by_offering.setdefault(offering, {"offering": offering, "amount": 0.0, "invoices": 0})
        o["amount"] = round(o["amount"] + delta, 2)
        o["invoices"] += 1 if in_win else 0

    return {
        "ok": True, "report": "revenue", "period": period,
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "total_revenue": total,
        "by_account": sorted(by_account.values(), key=lambda x: -x["amount"]),
        "by_source": [{"source": k, "amount": v}
                      for k, v in sorted(by_source.items(), key=lambda kv: -kv[1])],
        "by_customer": sorted(by_customer.values(), key=lambda x: -x["amount"]),
        "by_offering": sorted(by_offering.values(), key=lambda x: -x["amount"]),
        "monthly": [{"month": m, "amount": monthly[m]} for m in sorted(monthly)],
    }


# ─── Expense Report ──────────────────────────────────────────────────

def expense_report(biz: str, period: str = "this_month",
                   custom_from: Optional[str] = None,
                   custom_to: Optional[str] = None) -> Dict[str, Any]:
    start, end = reports_engine.period_bounds(period, custom_from, custom_to)
    lines = _window_lines(biz, start, end)

    by_account: Dict[str, Dict[str, Any]] = {}
    by_vendor: Dict[str, Dict[str, Any]] = {}
    by_subcategory: Dict[str, float] = {}
    monthly: Dict[str, float] = {}
    total = 0.0
    for l in lines:
        if l.get("account_type") != "expense":
            continue
        net = round(float(l["debit"]) - float(l["credit"]), 2)
        code = l["account_code"]
        acc = by_account.setdefault(code, {
            "code": code, "name": ACCOUNT_NAMES.get(code, code),
            "bucket": l.get("profit_first_bucket"), "amount": 0.0})
        acc["amount"] = round(acc["amount"] + net, 2)
        vendor = l.get("vendor") or "(no vendor)"
        v = by_vendor.setdefault(vendor, {"vendor": vendor, "amount": 0.0, "entries": 0})
        v["amount"] = round(v["amount"] + net, 2)
        v["entries"] += 1 if net > 0 else 0
        sub = l.get("subcategory") or "(none)"
        by_subcategory[sub] = round(by_subcategory.get(sub, 0.0) + net, 2)
        monthly[_month_key(l)] = round(monthly.get(_month_key(l), 0.0) + net, 2)
        total = round(total + net, 2)

    return {
        "ok": True, "report": "expenses_detail", "period": period,
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "total_expenses": total,
        "by_account": sorted(by_account.values(), key=lambda x: -x["amount"]),
        "by_vendor": sorted(by_vendor.values(), key=lambda x: -x["amount"]),
        "by_subcategory": [{"subcategory": k, "amount": v}
                           for k, v in sorted(by_subcategory.items(), key=lambda kv: -kv[1])],
        "monthly": [{"month": m, "amount": monthly[m]} for m in sorted(monthly)],
    }


# ─── Customer Statement ──────────────────────────────────────────────

def list_statement_customers(biz: str) -> List[Dict[str, Any]]:
    """Contacts that have at least one non-draft invoice (statement targets)."""
    rows = sb_clients.sb_get_as_service(
        f"/invoices?business_id=eq.{biz}&contact_id=not.is.null"
        f"&status=not.in.(draft,cancelled)"
        f"&select=contact_id,contacts(name,email)&limit=10000") or []
    seen: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        cid = r.get("contact_id")
        c = (r.get("contacts") or {}) or {}
        if not cid:
            continue
        e = seen.setdefault(cid, {"contact_id": cid, "name": c.get("name") or "—",
                                  "email": c.get("email"), "invoices": 0})
        e["invoices"] += 1
    return sorted(seen.values(), key=lambda x: (x["name"] or "").lower())


def customer_statement(biz: str, contact_id: str,
                       as_of: Optional[str] = None) -> Dict[str, Any]:
    asof = gl_engine._d(as_of) or gl_engine._today()
    crows = sb_clients.sb_get_as_service(
        f"/contacts?id=eq.{contact_id}&select=id,name,email,phone&limit=1") or []
    contact = crows[0] if crows else {"id": contact_id, "name": "—", "email": None}

    invoices = sb_clients.sb_get_as_service(
        f"/invoices?business_id=eq.{biz}&contact_id=eq.{contact_id}"
        f"&status=not.in.(draft,cancelled)"
        f"&select=id,invoice_number,total,status,sent_at,created_at,due_date,paid_at,"
        f"refund_amount_cents,refunded_at&limit=5000") or []

    events: List[Dict[str, Any]] = []
    invoiced = paid = refunded = 0.0
    for inv in invoices:
        amt = float(inv.get("total") or 0)
        if amt <= 0:
            continue
        num = inv.get("invoice_number") or str(inv.get("id"))[:8]
        d_issue = _issue_date(inv)
        if d_issue and d_issue <= asof:
            events.append({"date": d_issue.isoformat(), "type": "invoice",
                           "ref": num, "description": "Invoice issued", "amount": amt})
            invoiced = round(invoiced + amt, 2)
        d_paid = gl_engine._d(inv.get("paid_at"))
        if (inv.get("status") or "").lower() == "paid" and d_paid and d_paid <= asof:
            events.append({"date": d_paid.isoformat(), "type": "payment",
                           "ref": num, "description": "Payment received", "amount": -amt})
            paid = round(paid + amt, 2)
        rc = inv.get("refund_amount_cents")
        if rc and float(rc) > 0:
            r_amt = round(float(rc) / 100.0, 2)
            d_ref = gl_engine._d(inv.get("refunded_at")) or d_paid
            if d_ref and d_ref <= asof:
                events.append({"date": d_ref.isoformat(), "type": "refund",
                               "ref": num, "description": "Refund issued", "amount": -r_amt})
                refunded = round(refunded + r_amt, 2)

    events.sort(key=lambda e: (e["date"], 0 if e["type"] == "invoice" else 1))
    bal = 0.0
    for e in events:
        bal = round(bal + e["amount"], 2)
        e["balance"] = bal

    # Aging for THIS contact's outstanding invoices (same buckets as AR Aging).
    aging = {"current": 0.0, "d1_30": 0.0, "d31_60": 0.0, "d61_90": 0.0, "d90_plus": 0.0}
    for inv in invoices:
        if inv.get("paid_at") or (inv.get("status") or "").lower() in ("paid",):
            continue
        amt = float(inv.get("total") or 0)
        rc = inv.get("refund_amount_cents")
        if amt <= 0 or (rc is not None and float(rc) >= amt * 100):
            continue
        due = gl_engine._d(inv.get("due_date"))
        if not due or due >= asof:
            aging["current"] = round(aging["current"] + amt, 2)
        else:
            days = (asof - due).days
            k = "d1_30" if days <= 30 else "d31_60" if days <= 60 \
                else "d61_90" if days <= 90 else "d90_plus"
            aging[k] = round(aging[k] + amt, 2)

    return {
        "ok": True, "report": "customer_statement", "as_of": asof.isoformat(),
        "contact": {"id": contact.get("id"), "name": contact.get("name"),
                    "email": contact.get("email"), "phone": contact.get("phone")},
        "lines": events,
        "totals": {"invoiced": invoiced, "paid": paid, "refunded": refunded,
                   "balance": bal},
        "aging": aging,
    }


def statement_email(business_name: str, contact_name: str,
                    data: Dict[str, Any]) -> tuple:
    """(subject, body) for emailing a statement to the client."""
    bal = (data.get("totals") or {}).get("balance") or 0.0
    subject = f"Your account statement from {business_name}"
    if bal > 0:
        bal_line = (f"Your current balance is ${bal:,.2f}. You can pay any open "
                    f"invoice using the payment link on the invoice itself.")
    elif bal < 0:
        bal_line = f"Your account shows a credit of ${abs(bal):,.2f} in your favor."
    else:
        bal_line = "Your account is fully settled — thank you!"
    body = (
        f"Hi {contact_name or 'there'},\n\n"
        f"Attached is your account statement from {business_name} as of "
        f"{data.get('as_of')}. It lists every invoice, payment, and refund on "
        f"your account, with a running balance.\n\n"
        f"{bal_line}\n\n"
        f"If anything looks off, just reply to this email and we'll sort it "
        f"out together.\n\n"
        f"Warmly,\n{business_name}"
    )
    return subject, body
