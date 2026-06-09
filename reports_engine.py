"""
reports_engine.py — Phase H.3a — Reports suite on existing data.

Single source of truth for bookkeeping report math (P&L, AR Aging, Cash Flow
operating, Balance Sheet lite). Pure-Python computation over three sources:
  - invoices            (canonical AR — native table: total $, paid_at, status,
                         contact_id, due_date, refund_amount_cents)
  - plaid_transactions  (Plaid sign: amount<0 = inflow/deposit, >0 = outflow)
  - business_expenses   (manual entries — amount $, 5-bucket category, subcategory)

Chart of accounts is HYBRID (F12): 5-bucket primary rollup + business_subcategory
line items. All reads are service-role + explicit business_id (Chief/Phase-G
pattern). excluded_from_books Plaid rows are omitted everywhere.

Fnew-B note: every H.3a report derives from invoices + Plaid bank data +
business_expenses. NONE call the Stripe API, so no Stripe cache / >90-day
history concern arises here. (That surfaces in H.3b / 1099.)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, date as _date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import sb_clients
import plaid_categorization

logger = logging.getLogger("reports_engine")

BUCKET_ORDER = ["tax", "owner_pay", "operating", "savings", "other"]
BUCKET_LABELS = {
    "tax": "Tax", "owner_pay": "Owner Pay", "operating": "Operating",
    "savings": "Savings", "other": "Other",
}

# AR Aging outstanding rule (ruled): not paid + not cancelled/paid + not fully refunded.
_OUTSTANDING_EXCLUDED_STATUSES = ("cancelled", "paid")


def _today() -> _date:
    return datetime.now(timezone.utc).date()


def _d(s: str) -> Optional[_date]:
    try:
        y, m, dd = (int(p) for p in s.split("-"))
        return _date(y, m, dd)
    except Exception:
        return None


# ─── Period boundaries (inline calls documented) ─────────────────────

def period_bounds(period: str, custom_from: Optional[str] = None,
                  custom_to: Optional[str] = None) -> Tuple[_date, _date]:
    """Return (start, end) inclusive dates for a named period.
    Quarters are calendar quarters (Q1=Jan-Mar … Q4=Oct-Dec)."""
    today = _today()
    y = today.year
    if period == "custom":
        s = _d(custom_from or "") or today.replace(month=1, day=1)
        e = _d(custom_to or "") or today
        return (s, e)
    if period == "this_month":
        return (today.replace(day=1), today)
    if period == "last_month":
        first_this = today.replace(day=1)
        end_prev = first_this - timedelta(days=1)
        return (end_prev.replace(day=1), end_prev)
    if period == "this_quarter":
        q = (today.month - 1) // 3
        start = _date(y, q * 3 + 1, 1)
        return (start, today)
    if period == "last_quarter":
        q = (today.month - 1) // 3
        start_this = _date(y, q * 3 + 1, 1)
        end_prev = start_this - timedelta(days=1)
        pq = (end_prev.month - 1) // 3
        return (_date(end_prev.year, pq * 3 + 1, 1), end_prev)
    if period == "last_year":
        return (_date(y - 1, 1, 1), _date(y - 1, 12, 31))
    # this_year / ytd
    return (_date(y, 1, 1), today)


def comparison_bounds(start: _date, end: _date, comparison: str) -> Tuple[_date, _date]:
    """'previous' = the immediately preceding window of equal length;
    'last_year' = the same window shifted back one year."""
    if comparison == "last_year":
        try:
            return (start.replace(year=start.year - 1), end.replace(year=end.year - 1))
        except ValueError:  # Feb 29 → Feb 28
            return (start - timedelta(days=365), end - timedelta(days=365))
    length = (end - start).days
    prev_end = start - timedelta(days=1)
    return (prev_end - timedelta(days=length), prev_end)


def _iso(d: _date) -> str:
    return d.isoformat()


def _pct_change(cur: float, prev: float) -> Optional[float]:
    """Graceful: None when prior is zero (avoids NaN/inf — stop condition)."""
    if prev == 0:
        return None
    return round((cur - prev) / abs(prev) * 100.0, 1)


# ─── Shared data access ──────────────────────────────────────────────

def _included_account_ids(biz: str) -> List[str]:
    rows = sb_clients.sb_get_as_service(
        f"/plaid_accounts?business_id=eq.{biz}"
        f"&included_in_bookkeeping=eq.true&deleted_at=is.null&select=account_id"
    ) or []
    return [r["account_id"] for r in rows if r.get("account_id")]


def _cash_on_hand(biz: str) -> float:
    rows = sb_clients.sb_get_as_service(
        f"/plaid_accounts?business_id=eq.{biz}&type=eq.depository"
        f"&included_in_bookkeeping=eq.true&deleted_at=is.null&select=last_balance"
    ) or []
    return round(sum(float(r.get("last_balance") or 0) for r in rows), 2)


def _plaid_tx_in_period(biz: str, start: _date, end: _date) -> List[Dict[str, Any]]:
    """Included, not-excluded, settled Plaid transactions in [start, end]."""
    included = _included_account_ids(biz)
    if not included:
        return []
    acct = "account_id=in.(" + ",".join(included) + ")"
    return sb_clients.sb_get_as_service(
        f"/plaid_transactions?business_id=eq.{biz}&{acct}"
        f"&excluded_from_books=eq.false&pending=eq.false"
        f"&date=gte.{_iso(start)}&date=lte.{_iso(end)}"
        f"&select=amount,business_category,business_subcategory,"
        f"plaid_category_primary,plaid_category_detail,reconciled_to_payout_id&limit=5000"
    ) or []


def _paid_invoices_in_period(biz: str, start: _date, end: _date) -> List[Dict[str, Any]]:
    end_excl = end + timedelta(days=1)
    return sb_clients.sb_get_as_service(
        f"/invoices?business_id=eq.{biz}&status=eq.paid"
        f"&paid_at=gte.{_iso(start)}&paid_at=lt.{_iso(end_excl)}"
        f"&select=total,paid_at,refund_amount_cents,refunded_at&limit=5000"
    ) or []


def _outstanding_invoices(biz: str) -> List[Dict[str, Any]]:
    """Apply the ruled outstanding rule. PostgREST handles paid_at/status;
    the column-to-column refund check is finished in Python."""
    rows = sb_clients.sb_get_as_service(
        f"/invoices?business_id=eq.{biz}"
        f"&paid_at=is.null&status=not.in.({','.join(_OUTSTANDING_EXCLUDED_STATUSES)})"
        f"&select=id,invoice_number,total,due_date,status,refund_amount_cents,"
        f"created_at,contact_id,contacts(name)&limit=5000"
    ) or []
    out = []
    for r in rows:
        total = float(r.get("total") or 0)
        refund_cents = r.get("refund_amount_cents")
        if refund_cents is not None and float(refund_cents) >= total * 100:
            continue  # fully refunded
        out.append(r)
    return out


# ═══════════════════════════════════════════════════════════════════
# P&L
# ═══════════════════════════════════════════════════════════════════

def _pl_for_window(biz: str, start: _date, end: _date) -> Dict[str, Any]:
    # ── Revenue ──
    inv = _paid_invoices_in_period(biz, start, end)
    invoiced = round(sum(float(i.get("total") or 0) for i in inv), 2)
    # Refunds that landed in this window reduce revenue.
    refunds = 0.0
    end_excl = end + timedelta(days=1)
    for i in inv:
        rc, ra = i.get("refund_amount_cents"), i.get("refunded_at")
        if rc and ra:
            rad = _d((ra or "")[:10])
            if rad and start <= rad <= end:
                refunds += float(rc) / 100.0
    refunds = round(refunds, 2)

    txs = _plaid_tx_in_period(biz, start, end)
    # Non-Stripe income: bank inflows (amount<0) that are income-categorized
    # and NOT already represented by a Stripe payout (reconciled_to_payout_id).
    # (External-invoice overlap is resolved in H.2 — documented v1 limitation.)
    plaid_income = 0.0
    for t in txs:
        a = float(t.get("amount") or 0)
        if a < 0 and not t.get("reconciled_to_payout_id") and plaid_categorization.is_income_category(
                t.get("plaid_category_primary"), t.get("plaid_category_detail")):
            plaid_income += -a
    plaid_income = round(plaid_income, 2)
    gross_revenue = round(invoiced - refunds + plaid_income, 2)

    # ── Expenses (hybrid: 5-bucket → subcategory line items) ──
    buckets: Dict[str, Dict[str, Any]] = {
        b: {"bucket": b, "label": BUCKET_LABELS[b], "total": 0.0, "lines": {}} for b in BUCKET_ORDER
    }

    def _add(bucket: str, sub: Optional[str], amt: float):
        b = bucket if bucket in buckets else "other"
        buckets[b]["total"] += amt
        key = (sub or "—").strip() or "—"
        buckets[b]["lines"][key] = buckets[b]["lines"].get(key, 0.0) + amt

    # Plaid outflows = expenses.
    for t in txs:
        a = float(t.get("amount") or 0)
        if a > 0 and not plaid_categorization.is_income_category(
                t.get("plaid_category_primary"), t.get("plaid_category_detail")):
            bucket = t.get("business_category") or plaid_categorization.map_plaid_to_bucket(
                t.get("plaid_category_primary"), t.get("plaid_category_detail"))
            _add(bucket, t.get("business_subcategory"), a)

    # Manual expenses.
    exp = sb_clients.sb_get_as_service(
        f"/business_expenses?business_id=eq.{biz}"
        f"&date=gte.{_iso(start)}&date=lte.{_iso(end)}"
        f"&select=amount,category,subcategory&limit=5000"
    ) or []
    for e in exp:
        _add(e.get("category") or "other", e.get("subcategory"), float(e.get("amount") or 0))

    total_expenses = round(sum(b["total"] for b in buckets.values()), 2)
    expense_breakdown = []
    for b in BUCKET_ORDER:
        bk = buckets[b]
        if bk["total"] == 0 and not bk["lines"]:
            continue
        expense_breakdown.append({
            "bucket": b, "label": bk["label"], "total": round(bk["total"], 2),
            "pct": round(bk["total"] / total_expenses * 100, 1) if total_expenses else 0.0,
            "lines": sorted(
                [{"subcategory": k, "amount": round(v, 2)} for k, v in bk["lines"].items()],
                key=lambda x: -x["amount"]),
        })

    net_income = round(gross_revenue - total_expenses, 2)
    return {
        "revenue": {
            "invoiced": invoiced, "refunds": refunds,
            "plaid_other_income": plaid_income, "gross_revenue": gross_revenue,
        },
        "expenses": {"total": total_expenses, "by_bucket": expense_breakdown},
        "net_income": net_income,
    }


def profit_and_loss(biz: str, period: str, comparison: Optional[str] = None,
                    custom_from: Optional[str] = None, custom_to: Optional[str] = None) -> Dict[str, Any]:
    start, end = period_bounds(period, custom_from, custom_to)
    cur = _pl_for_window(biz, start, end)
    out: Dict[str, Any] = {
        "ok": True, "report": "pl", "period": period,
        "range": {"from": _iso(start), "to": _iso(end)},
        "current": cur,
    }
    if comparison:
        cs, ce = comparison_bounds(start, end, comparison)
        prev = _pl_for_window(biz, cs, ce)
        out["comparison"] = {
            "label": comparison, "range": {"from": _iso(cs), "to": _iso(ce)},
            "data": prev,
            "change": {
                "gross_revenue": _pct_change(cur["revenue"]["gross_revenue"], prev["revenue"]["gross_revenue"]),
                "total_expenses": _pct_change(cur["expenses"]["total"], prev["expenses"]["total"]),
                "net_income": _pct_change(cur["net_income"], prev["net_income"]),
            },
        }
    return out


# ═══════════════════════════════════════════════════════════════════
# AR Aging
# ═══════════════════════════════════════════════════════════════════

def ar_aging(biz: str, as_of: Optional[str] = None) -> Dict[str, Any]:
    asof = _d(as_of or "") or _today()
    rows = _outstanding_invoices(biz)
    buckets = {"current": 0.0, "d1_30": 0.0, "d31_60": 0.0, "d61_90": 0.0, "d90_plus": 0.0}
    by_contact: Dict[str, Dict[str, Any]] = {}

    def _bucket_for(due: Optional[_date]) -> str:
        if not due or due >= asof:
            return "current"
        days = (asof - due).days
        if days <= 30:
            return "d1_30"
        if days <= 60:
            return "d31_60"
        if days <= 90:
            return "d61_90"
        return "d90_plus"

    invoices_out = []
    for r in rows:
        total = float(r.get("total") or 0)
        due = _d(r.get("due_date") or "")
        b = _bucket_for(due)
        buckets[b] += total
        name = ((r.get("contacts") or {}) or {}).get("name") or "—"
        cg = by_contact.setdefault(name, {"contact": name, "total": 0.0, "count": 0})
        cg["total"] += total
        cg["count"] += 1
        invoices_out.append({
            "id": r.get("id"), "invoice_number": r.get("invoice_number"),
            "contact": name, "total": round(total, 2), "due_date": r.get("due_date"),
            "status": r.get("status"), "bucket": b,
            "days_overdue": (asof - due).days if (due and due < asof) else 0,
        })

    total_outstanding = round(sum(buckets.values()), 2)
    at_risk = round(buckets["d61_90"] + buckets["d90_plus"], 2)
    return {
        "ok": True, "report": "ar_aging", "as_of": _iso(asof),
        "buckets": {k: round(v, 2) for k, v in buckets.items()},
        "total_outstanding": total_outstanding, "at_risk": at_risk,
        "by_contact": sorted(by_contact.values(), key=lambda x: -x["total"]),
        "invoices": sorted(invoices_out, key=lambda x: -x["days_overdue"]),
    }


# ═══════════════════════════════════════════════════════════════════
# Cash Flow (operating only)
# ═══════════════════════════════════════════════════════════════════

def cash_flow(biz: str, period: str, custom_from: Optional[str] = None,
              custom_to: Optional[str] = None) -> Dict[str, Any]:
    start, end = period_bounds(period, custom_from, custom_to)
    txs = _plaid_tx_in_period(biz, start, end)
    # All bank inflows = cash from customers (Stripe payouts + external pmts +
    # other income — true bank-level "cash in", no Stripe API needed).
    cash_in = round(sum(-float(t.get("amount") or 0) for t in txs if float(t.get("amount") or 0) < 0), 2)
    cash_out = round(sum(float(t.get("amount") or 0) for t in txs if float(t.get("amount") or 0) > 0), 2)
    return {
        "ok": True, "report": "cash_flow", "period": period,
        "range": {"from": _iso(start), "to": _iso(end)},
        "operating": {
            "cash_from_customers": cash_in,
            "cash_to_suppliers": cash_out,
            "net_cash_from_operations": round(cash_in - cash_out, 2),
        },
        "note": "Operating activities only. Investing + financing land in v1.5.",
    }


# ═══════════════════════════════════════════════════════════════════
# Balance Sheet (lite)
# ═══════════════════════════════════════════════════════════════════

def balance_sheet(biz: str, as_of: Optional[str] = None) -> Dict[str, Any]:
    asof = _d(as_of or "") or _today()
    cash = _cash_on_hand(biz)  # current balance snapshot (historical balance is v1.5)
    ar = round(sum(float(r.get("total") or 0) for r in _outstanding_invoices(biz)), 2)
    ap = 0.0  # placeholder until H.1
    total_assets = round(cash + ar, 2)
    total_liabilities = round(ap, 2)
    equity = round(total_assets - total_liabilities, 2)
    return {
        "ok": True, "report": "balance_sheet", "as_of": _iso(asof),
        "assets": {"cash": cash, "accounts_receivable": ar, "total": total_assets},
        "liabilities": {"accounts_payable": ap, "total": total_liabilities},
        "equity": {"retained_earnings": equity, "total": equity},
        "note": "Lite: Cash + AR − AP. AP arrives with H.1; fixed assets / loans / "
                "equity tracking in v1.5. Cash is the latest balance snapshot.",
    }


# ─── Dispatch (used by the export endpoint) ──────────────────────────

def run_report(biz: str, report: str, *, period: str = "this_month",
               as_of: Optional[str] = None, comparison: Optional[str] = None,
               custom_from: Optional[str] = None, custom_to: Optional[str] = None) -> Dict[str, Any]:
    if report == "pl":
        return profit_and_loss(biz, period, comparison, custom_from, custom_to)
    if report == "ar_aging":
        return ar_aging(biz, as_of)
    if report == "cash_flow":
        return cash_flow(biz, period, custom_from, custom_to)
    if report == "balance_sheet":
        return balance_sheet(biz, as_of)
    raise ValueError(f"unknown report {report}")
