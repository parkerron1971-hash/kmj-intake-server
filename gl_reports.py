"""
gl_reports.py — Phase I.4 — reports computed from the General Ledger.

The GL is now the authoritative source for P&L, Balance Sheet, and Cash Flow
(AR/AP *Aging* stays a subledger report — aging needs per-invoice/bill due
dates that a control account doesn't carry — but both now validate against
the GL control-account balance). Response shapes are IDENTICAL to
reports_engine.py so the frontend + PDF builders consume either engine; the
router adds "source": "gl" | "source_tables".

Effective lines: every computation runs over ledger lines belonging to
ACTIVE, NON-REVERSAL journal entries. A reversed original (status='reversed')
and its mirror (is_reversal=true) are both excluded, so edited/deleted source
rows never distort magnitudes — the active repost alone represents truth.
Closing entries (source_type='closing') are active and DO flow into the
trial balance / balance sheet (correct post-close accounting) but are
excluded from P&L by its source-type filters.

New GL-native reports: Trial Balance, General Ledger detail (running
balances), Journal Entries log.
"""
from __future__ import annotations

import logging
from datetime import date as _date
from typing import Any, Dict, List, Optional, Set, Tuple

import sb_clients
import gl_engine
import reports_engine  # single source for period math + labels

logger = logging.getLogger("gl_reports")

BUCKET_ORDER = reports_engine.BUCKET_ORDER
BUCKET_LABELS = reports_engine.BUCKET_LABELS

_INCOME_CODES = gl_engine._INCOME_CODES
_EXPENSE_CODES = gl_engine._EXPENSE_CODES


# ─── Effective lines ─────────────────────────────────────────────────

def gl_active(biz: str) -> bool:
    """A business is GL-active once it has any active journal entry."""
    rows = sb_clients.sb_get_as_service(
        f"/journal_entries?business_id=eq.{biz}&status=eq.active&select=id&limit=1") or []
    return bool(rows)


def effective_lines(biz: str) -> List[Dict[str, Any]]:
    """Ledger lines of ACTIVE, NON-REVERSAL journal entries only."""
    jes = sb_clients.sb_get_as_service(
        f"/journal_entries?business_id=eq.{biz}"
        f"&select=id,status,is_reversal&limit=100000") or []
    # Missing status (pre-I.2 rows / DB default not echoed) counts as active.
    active: Set[str] = {j["id"] for j in jes
                        if (j.get("status") or "active") == "active"
                        and not j.get("is_reversal")}
    return [l for l in gl_engine.read_ledger(biz) if l.get("journal_entry_id") in active]


def _in_window(l: Dict[str, Any], start: _date, end: _date) -> bool:
    d = gl_engine._d(l.get("entry_date"))
    return bool(d and start <= d <= end)


def _net(lines, code: str, *, normal: str = "debit",
         upto: Optional[_date] = None) -> float:
    s = 0.0
    for l in lines:
        if l["account_code"] != code:
            continue
        if upto is not None:
            d = gl_engine._d(l.get("entry_date"))
            if d and d > upto:
                continue
        s += float(l["debit"]) - float(l["credit"])
    return round(s if normal == "debit" else -s, 2)


# ═══════════════════════════════════════════════════════════════════
# P&L (cash basis — parity with reports_engine shape)
# ═══════════════════════════════════════════════════════════════════

def _pl_window(lines: List[Dict[str, Any]], start: _date, end: _date) -> Dict[str, Any]:
    invoiced = refunds = plaid_income = 0.0
    buckets: Dict[str, Dict[str, Any]] = {
        b: {"bucket": b, "label": BUCKET_LABELS[b], "total": 0.0, "lines": {}}
        for b in BUCKET_ORDER
    }
    for l in lines:
        if not _in_window(l, start, end):
            continue
        st, code = l["source_type"], l["account_code"]
        cr, dr = float(l["credit"]), float(l["debit"])
        if st == "invoice_payment" and code == "1100":
            invoiced += cr
        elif st == "invoice_refund" and code in _INCOME_CODES:
            refunds += dr
        elif st == "plaid_transaction" and code in _INCOME_CODES:
            plaid_income += cr
        elif st in ("expense", "plaid_transaction") and code in _EXPENSE_CODES:
            bucket = l.get("profit_first_bucket") or "other"
            b = buckets.get(bucket) or buckets["other"]
            b["total"] += dr
            key = (l.get("subcategory") or "—").strip() or "—"
            b["lines"][key] = b["lines"].get(key, 0.0) + dr

    invoiced, refunds = round(invoiced, 2), round(refunds, 2)
    plaid_income = round(plaid_income, 2)
    gross = round(invoiced - refunds + plaid_income, 2)
    total_expenses = round(sum(b["total"] for b in buckets.values()), 2)

    breakdown = []
    for b in BUCKET_ORDER:
        bk = buckets[b]
        if bk["total"] == 0 and not bk["lines"]:
            continue
        breakdown.append({
            "bucket": b, "label": bk["label"], "total": round(bk["total"], 2),
            "pct": round(bk["total"] / total_expenses * 100, 1) if total_expenses else 0.0,
            "lines": sorted(
                [{"subcategory": k, "amount": round(v, 2)} for k, v in bk["lines"].items()],
                key=lambda x: -x["amount"]),
        })
    return {
        "revenue": {"invoiced": invoiced, "refunds": refunds,
                    "plaid_other_income": plaid_income, "gross_revenue": gross},
        "expenses": {"total": total_expenses, "by_bucket": breakdown},
        "net_income": round(gross - total_expenses, 2),
    }


def gl_profit_and_loss(biz: str, period: str, comparison: Optional[str] = None,
                       custom_from: Optional[str] = None,
                       custom_to: Optional[str] = None) -> Dict[str, Any]:
    start, end = reports_engine.period_bounds(period, custom_from, custom_to)
    lines = effective_lines(biz)
    cur = _pl_window(lines, start, end)
    out: Dict[str, Any] = {
        "ok": True, "report": "pl", "period": period,
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "current": cur,
    }
    if comparison:
        cs, ce = reports_engine.comparison_bounds(start, end, comparison)
        prev = _pl_window(lines, cs, ce)
        out["comparison"] = {
            "label": comparison, "range": {"from": cs.isoformat(), "to": ce.isoformat()},
            "data": prev,
            "change": {
                "gross_revenue": reports_engine._pct_change(
                    cur["revenue"]["gross_revenue"], prev["revenue"]["gross_revenue"]),
                "total_expenses": reports_engine._pct_change(
                    cur["expenses"]["total"], prev["expenses"]["total"]),
                "net_income": reports_engine._pct_change(
                    cur["net_income"], prev["net_income"]),
            },
        }
    return out


# ═══════════════════════════════════════════════════════════════════
# Balance Sheet (parity totals; Stripe Clearing surfaced informationally)
# ═══════════════════════════════════════════════════════════════════

def gl_balance_sheet(biz: str, as_of: Optional[str] = None) -> Dict[str, Any]:
    asof = gl_engine._d(as_of or "") or reports_engine._today()
    lines = effective_lines(biz)
    cash = _net(lines, "1000", upto=asof)
    ar = _net(lines, "1100", upto=asof)
    ap = _net(lines, "2000", normal="credit", upto=asof)
    clearing = _net(lines, "1150", upto=asof)
    total_assets = round(cash + ar, 2)          # parity with H.3a lite (clearing informational)
    total_liabilities = round(ap, 2)
    equity = round(total_assets - total_liabilities, 2)
    return {
        "ok": True, "report": "balance_sheet", "as_of": asof.isoformat(),
        "assets": {"cash": cash, "accounts_receivable": ar, "total": total_assets,
                   "stripe_clearing": clearing},
        "liabilities": {"accounts_payable": ap, "total": total_liabilities},
        "equity": {"retained_earnings": equity, "total": equity},
        "note": "From the General Ledger. Stripe Clearing shows customer payments in "
                "transit to your bank (informational; folded into assets when accrual "
                "view lands). Cash is the latest balance snapshot.",
    }


# ═══════════════════════════════════════════════════════════════════
# Cash Flow (operating; plaid-sourced cash lines — parity with H.3a)
# ═══════════════════════════════════════════════════════════════════

def gl_cash_flow(biz: str, period: str, custom_from: Optional[str] = None,
                 custom_to: Optional[str] = None) -> Dict[str, Any]:
    start, end = reports_engine.period_bounds(period, custom_from, custom_to)
    cash_in = cash_out = 0.0
    for l in effective_lines(biz):
        if l["account_code"] != "1000" or l["source_type"] != "plaid_transaction":
            continue
        if not _in_window(l, start, end):
            continue
        cash_in += float(l["debit"])
        cash_out += float(l["credit"])
    return {
        "ok": True, "report": "cash_flow", "period": period,
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "operating": {
            "cash_from_customers": round(cash_in, 2),
            "cash_to_suppliers": round(cash_out, 2),
            "net_cash_from_operations": round(cash_in - cash_out, 2),
        },
        "note": "Operating activities only, from the General Ledger (bank-level cash "
                "movements). Investing + financing land in v1.5.",
    }


# ═══════════════════════════════════════════════════════════════════
# Trial Balance (NEW — GL-native)
# ═══════════════════════════════════════════════════════════════════

_TYPE_ORDER = {"asset": 0, "liability": 1, "equity": 2, "income": 3, "expense": 4}


def _account_meta(biz: str) -> Dict[str, Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/chart_of_accounts?business_id=eq.{biz}"
        f"&select=code,name,type,normal_balance&limit=500") or []
    return {r["code"]: r for r in rows}


def trial_balance_report(biz: str, as_of: Optional[str] = None) -> Dict[str, Any]:
    asof = gl_engine._d(as_of or "") or reports_engine._today()
    meta = _account_meta(biz)
    agg: Dict[str, Dict[str, float]] = {}
    for l in effective_lines(biz):
        d = gl_engine._d(l.get("entry_date"))
        if d and d > asof:
            continue
        a = agg.setdefault(l["account_code"], {"debits": 0.0, "credits": 0.0})
        a["debits"] += float(l["debit"])
        a["credits"] += float(l["credit"])

    accounts = []
    tot_dr = tot_cr = 0.0
    for code in sorted(agg.keys()):
        m = meta.get(code) or {}
        dr, cr = round(agg[code]["debits"], 2), round(agg[code]["credits"], 2)
        tot_dr += dr
        tot_cr += cr
        normal = m.get("normal_balance") or ("debit" if (m.get("type") in ("asset", "expense")) else "credit")
        bal = round(dr - cr, 2) if normal == "debit" else round(cr - dr, 2)
        accounts.append({
            "code": code, "name": m.get("name") or code, "type": m.get("type") or "—",
            "normal_balance": normal, "debits": dr, "credits": cr, "balance": bal,
        })
    accounts.sort(key=lambda a: (_TYPE_ORDER.get(a["type"], 9), a["code"]))
    diff = round(tot_dr - tot_cr, 2)
    return {
        "ok": True, "report": "trial_balance", "as_of": asof.isoformat(),
        "accounts": accounts,
        "totals": {"debits": round(tot_dr, 2), "credits": round(tot_cr, 2),
                   "difference": diff, "balanced": abs(diff) < 0.01},
    }


# ═══════════════════════════════════════════════════════════════════
# General Ledger detail (NEW — per-account lines + running balance)
# ═══════════════════════════════════════════════════════════════════

_GL_DETAIL_CAP = 300   # lines per account in one response (note truncation)


def general_ledger_report(biz: str, account_code: Optional[str] = None,
                          date_from: Optional[str] = None,
                          date_to: Optional[str] = None) -> Dict[str, Any]:
    start = gl_engine._d(date_from or "") or _date(2000, 1, 1)
    end = gl_engine._d(date_to or "") or reports_engine._today()
    meta = _account_meta(biz)
    lines = effective_lines(biz)

    by_account: Dict[str, List[Dict[str, Any]]] = {}
    opening: Dict[str, float] = {}
    for l in lines:
        code = l["account_code"]
        if account_code and code != account_code:
            continue
        d = gl_engine._d(l.get("entry_date"))
        if not d:
            continue
        if d < start:
            opening[code] = opening.get(code, 0.0) + float(l["debit"]) - float(l["credit"])
        elif d <= end:
            by_account.setdefault(code, []).append(l)

    accounts = []
    for code in sorted(set(list(by_account.keys()) + list(opening.keys()))):
        m = meta.get(code) or {}
        normal = m.get("normal_balance") or ("debit" if (m.get("type") in ("asset", "expense")) else "credit")
        sign = 1 if normal == "debit" else -1
        open_bal = round(sign * opening.get(code, 0.0), 2)
        rows = sorted(by_account.get(code, []), key=lambda x: (x.get("entry_date") or "", x.get("journal_entry_id") or ""))
        truncated = len(rows) > _GL_DETAIL_CAP
        running = open_bal
        entries = []
        for l in rows[:_GL_DETAIL_CAP]:
            running = round(running + sign * (float(l["debit"]) - float(l["credit"])), 2)
            entries.append({
                "date": l.get("entry_date"), "source_type": l.get("source_type"),
                "memo": l.get("memo") or l.get("subcategory") or "",
                "vendor": l.get("vendor"), "debit": float(l["debit"]),
                "credit": float(l["credit"]), "running_balance": running,
            })
        accounts.append({
            "code": code, "name": m.get("name") or code, "type": m.get("type") or "—",
            "opening_balance": open_bal, "closing_balance": running,
            "entries": entries, "truncated": truncated,
        })
    accounts.sort(key=lambda a: (_TYPE_ORDER.get(a["type"], 9), a["code"]))
    return {
        "ok": True, "report": "general_ledger",
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "accounts": accounts,
    }


# ═══════════════════════════════════════════════════════════════════
# Journal Entries log (NEW)
# ═══════════════════════════════════════════════════════════════════

def journal_report(biz: str, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    capped = max(1, min(int(limit), 200))
    jes = sb_clients.sb_get_as_service(
        f"/journal_entries?business_id=eq.{biz}"
        f"&order=entry_date.desc,created_at.desc"
        f"&select=id,entry_date,description,source_type,status,is_reversal"
        f"&limit={capped + 1}&offset={int(offset)}") or []
    has_more = len(jes) > capped
    jes = jes[:capped]
    line_map: Dict[str, List[Dict[str, Any]]] = {}
    if jes:
        ids = ",".join(j["id"] for j in jes)
        lines = sb_clients.sb_get_as_service(
            f"/ledger_entries?journal_entry_id=in.({ids})"
            f"&select=journal_entry_id,account_code,debit,credit,memo&limit=5000") or []
        for l in lines:
            line_map.setdefault(l["journal_entry_id"], []).append(
                {"account_code": l["account_code"], "debit": float(l["debit"]),
                 "credit": float(l["credit"]), "memo": l.get("memo") or ""})
    entries = []
    for j in jes:
        entries.append({
            "id": j["id"], "date": j.get("entry_date"),
            "description": j.get("description") or "", "source_type": j.get("source_type"),
            "status": j.get("status"), "is_reversal": bool(j.get("is_reversal")),
            "lines": sorted(line_map.get(j["id"], []), key=lambda x: -x["debit"]),
        })
    return {"ok": True, "report": "journal", "entries": entries, "has_more": has_more}


# ═══════════════════════════════════════════════════════════════════
# AR/AP control validation (aging stays subledger; GL validates totals)
# ═══════════════════════════════════════════════════════════════════

def gl_control(biz: str) -> Dict[str, Any]:
    lines = effective_lines(biz)
    return {
        "ar": _net(lines, "1100"),
        "ap": _net(lines, "2000", normal="credit"),
    }
