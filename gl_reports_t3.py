"""
gl_reports_t3.py — Phase I.9 — Tier-3 analytical reports on the GL.

Budget vs Actual    — practitioner-set monthly budgets (business_budgets
                      table) vs GL actuals; where no explicit expense budget
                      exists, the Profit-First allocator percentages
                      (settings.revenue_allocator) derive a target from
                      actual revenue, labeled as such.
Cash Flow Forecast  — trend-aware: mean ± stdev of trailing monthly GL cash
                      flows projects 30/60/90-day positions with a
                      confidence band; scheduled AR (open invoices due in
                      the horizon) and AP (open bills due) listed alongside,
                      NOT silently folded into the trend.
Profitability       — contribution by customer + offering: revenue (I.8
                      logic) minus overhead allocated PROPORTIONALLY to
                      revenue share. v1 method is explicit in the response:
                      expenses carry no per-offering/per-client tagging
                      anywhere in the system yet, so true direct-cost
                      margins are impossible — SURFACED as a fork (expense
                      tagging feature ruling). Proportional contribution
                      still ranks customers/offerings honestly by dollars.
Trends              — trailing-12-month revenue/expense/net + seasonality
                      (average by calendar month over full history) +
                      momentum (last 3 months vs the prior 3).
"""
from __future__ import annotations

import logging
import math
from datetime import date as _date, timedelta
from typing import Any, Dict, List, Optional

import sb_clients
import gl_engine
import gl_reports
import gl_reports_t2
import reports_engine

logger = logging.getLogger("gl_reports_t3")

BUDGET_CATEGORIES = ("revenue", "operating", "owner_pay", "tax", "savings", "other")
_EXP_CODE_TO_CAT = {v: k for k, v in gl_engine._BUCKET_TO_EXPENSE.items()}


def _month_iter(start: _date, end: _date):
    cur = start.replace(day=1)
    while cur <= end:
        yield cur
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)


def _month_key(d: _date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


# ─── Budgets (storage) ───────────────────────────────────────────────

def list_budgets(biz: str, year: int, month: int) -> List[Dict[str, Any]]:
    return sb_clients.sb_get_as_service(
        f"/business_budgets?business_id=eq.{biz}&year=eq.{year}&month=eq.{month}"
        f"&select=id,category,amount&order=category.asc") or []


def upsert_budgets(biz: str, year: int, month: int,
                   entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Set the month's budget rows (one per category). Idempotent upsert."""
    existing = {r["category"]: r for r in list_budgets(biz, year, month)}
    written = 0
    for e in entries:
        cat = e.get("category")
        if cat not in BUDGET_CATEGORIES:
            continue
        amt = round(float(e.get("amount") or 0), 2)
        cur = existing.get(cat)
        if cur:
            sb_clients.sb_patch_as_service(
                f"/business_budgets?id=eq.{cur['id']}", {"amount": amt})
        else:
            sb_clients.sb_post_as_service("/business_budgets", {
                "business_id": biz, "year": year, "month": month,
                "category": cat, "amount": amt}, prefer=None)
        written += 1
    return {"ok": True, "written": written}


def _budgets_in_window(biz: str, start: _date, end: _date) -> Dict[str, float]:
    """Sum budgets per category across the months overlapping the window."""
    months = list(_month_iter(start, end))
    if not months:
        return {}
    wanted = {(m.year, m.month) for m in months}
    years = ",".join(str(y) for y in sorted({m.year for m in months}))
    rows = sb_clients.sb_get_as_service(
        f"/business_budgets?business_id=eq.{biz}&year=in.({years})"
        f"&select=year,month,category,amount&limit=2000") or []
    out: Dict[str, float] = {}
    for r in rows:
        if (int(r.get("year") or 0), int(r.get("month") or 0)) not in wanted:
            continue
        c = r.get("category")
        out[c] = round(out.get(c, 0.0) + float(r.get("amount") or 0), 2)
    return out


def _allocator_pcts(biz_row: Dict[str, Any]) -> Dict[str, float]:
    """Profit-First allocator percentages from settings (0-100 each)."""
    settings = biz_row.get("settings") or {}
    alloc = settings.get("revenue_allocator") or {}
    fin = settings.get("financial") or {}
    out: Dict[str, float] = {}
    for cat in ("operating", "owner_pay", "savings"):
        v = alloc.get(cat)
        if v is not None:
            try:
                out[cat] = float(v)
            except Exception:
                pass
    tax = fin.get("tax_rate")
    if tax is not None:
        try:
            out["tax"] = float(tax)
        except Exception:
            pass
    return out


def budget_vs_actual(biz: str, biz_row: Dict[str, Any], period: str = "this_month",
                     custom_from: Optional[str] = None,
                     custom_to: Optional[str] = None) -> Dict[str, Any]:
    start, end = reports_engine.period_bounds(period, custom_from, custom_to)
    lines = gl_reports_t2._window_lines(biz, start, end)

    actual_rev = 0.0
    actual_exp: Dict[str, float] = {}
    for l in lines:
        if l.get("account_type") == "income":
            actual_rev = round(actual_rev + float(l["credit"]) - float(l["debit"]), 2)
        elif l.get("account_type") == "expense":
            cat = _EXP_CODE_TO_CAT.get(l["account_code"], "other")
            actual_exp[cat] = round(actual_exp.get(cat, 0.0)
                                    + float(l["debit"]) - float(l["credit"]), 2)

    budgets = _budgets_in_window(biz, start, end)
    pcts = _allocator_pcts(biz_row)
    n_months = len(list(_month_iter(start, end)))

    rows: List[Dict[str, Any]] = []
    rev_budget = budgets.get("revenue")
    rows.append({
        "category": "revenue", "label": "Revenue",
        "actual": actual_rev, "budget": rev_budget,
        "budget_source": "set" if rev_budget is not None else None,
        "variance": round(actual_rev - rev_budget, 2) if rev_budget is not None else None,
    })
    for cat in ("operating", "owner_pay", "tax", "savings", "other"):
        actual = actual_exp.get(cat, 0.0)
        budget = budgets.get(cat)
        source = "set" if budget is not None else None
        if budget is None and cat in pcts and actual_rev > 0:
            budget = round(actual_rev * pcts[cat] / 100.0, 2)
            source = "profit_first"  # derived from allocator % × actual revenue
        rows.append({
            "category": cat, "label": cat.replace("_", " ").title(),
            "actual": actual, "budget": budget, "budget_source": source,
            # Expenses: positive variance = OVER budget (worth attention).
            "variance": round(actual - budget, 2) if budget is not None else None,
        })

    return {
        "ok": True, "report": "budget_vs_actual", "period": period,
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "months_in_window": n_months,
        "rows": rows,
        "has_any_budget": bool(budgets),
        "allocator_pcts": pcts,
    }


# ─── Cash Flow Forecast ──────────────────────────────────────────────

def cash_flow_forecast(biz: str) -> Dict[str, Any]:
    today = gl_engine._today()
    lines = gl_reports.effective_lines(biz)

    # Trailing monthly net cash flows (1000), excluding the opening plug and
    # the current partial month.
    flows: Dict[str, float] = {}
    for l in lines:
        if l["account_code"] != "1000":
            continue
        if str(l.get("source_type") or "").startswith("opening_balance"):
            continue
        k = str(l.get("entry_date") or "")[:7]
        flows[k] = round(flows.get(k, 0.0) + float(l["debit"]) - float(l["credit"]), 2)
    cur_key = _month_key(today)
    hist = sorted((k, v) for k, v in flows.items() if k < cur_key)[-6:]
    values = [v for _, v in hist]
    n = len(values)
    mean = round(sum(values) / n, 2) if n else 0.0
    if n >= 2:
        var = sum((v - mean) ** 2 for v in values) / (n - 1)
        stdev = round(math.sqrt(var), 2)
    else:
        stdev = 0.0

    current_cash = gl_engine.gl_cash(lines)

    # Scheduled, dated items — listed alongside the trend, not folded in.
    open_invoices = sb_clients.sb_get_as_service(
        f"/invoices?business_id=eq.{biz}&paid_at=is.null"
        f"&status=in.(sent,viewed,overdue)"
        f"&select=total,due_date&limit=5000") or []
    open_bills = sb_clients.sb_get_as_service(
        f"/bills?business_id=eq.{biz}&status=not.in.(paid,cancelled,draft)"
        f"&select=amount,due_date&limit=5000") or []

    def _due_within(rows, key, days):
        cutoff = today + timedelta(days=days)
        s = 0.0
        for r in rows:
            d = gl_engine._d(r.get("due_date"))
            if d and d <= cutoff:
                s += float(r.get(key) or 0)
        return round(s, 2)

    horizons = []
    for days in (30, 60, 90):
        f = days / 30.0
        trend = round(mean * f, 2)
        band = round(stdev * math.sqrt(f), 2)
        projected = round(current_cash + trend, 2)
        horizons.append({
            "days": days,
            "projected": projected,
            "low": round(projected - band, 2),
            "high": round(projected + band, 2),
            "scheduled_ar_in": _due_within(open_invoices, "total", days),
            "scheduled_ap_out": _due_within(open_bills, "amount", days),
        })

    return {
        "ok": True, "report": "cash_forecast",
        "as_of": today.isoformat(),
        "current_cash": current_cash,
        "monthly_history": [{"month": k, "net_flow": v} for k, v in hist],
        "trend": {"mean_monthly_flow": mean, "stdev": stdev, "months_used": n},
        "horizons": horizons,
        "method": ("Trend from the last "
                   f"{n} full months of GL cash activity (mean ± 1σ band). "
                   "Open invoices/bills due in each horizon are shown "
                   "separately — collection timing is yours to judge."),
    }


# ─── Profitability (customer + offering contribution) ────────────────

def profitability(biz: str, period: str = "this_year",
                  custom_from: Optional[str] = None,
                  custom_to: Optional[str] = None) -> Dict[str, Any]:
    rev = gl_reports_t2.revenue_report(biz, period, custom_from, custom_to)
    exp = gl_reports_t2.expense_report(biz, period, custom_from, custom_to)
    total_rev = float(rev.get("total_revenue") or 0)
    total_exp = float(exp.get("total_expenses") or 0)

    def _with_contribution(rows, label_key):
        out = []
        for r in rows:
            amount = float(r.get("amount") or 0)
            share = (amount / total_rev) if total_rev > 0 else 0.0
            overhead = round(total_exp * share, 2)
            out.append({
                label_key: r.get(label_key), "revenue": round(amount, 2),
                "revenue_share_pct": round(share * 100, 1),
                "allocated_overhead": overhead,
                "contribution": round(amount - overhead, 2),
            })
        return out

    return {
        "ok": True, "report": "profitability", "period": period,
        "range": rev.get("range"),
        "total_revenue": round(total_rev, 2),
        "total_expenses": round(total_exp, 2),
        "net_income": round(total_rev - total_exp, 2),
        "by_customer": _with_contribution(rev.get("by_customer") or [], "customer"),
        "by_offering": _with_contribution(rev.get("by_offering") or [], "offering"),
        "method": ("Overhead is allocated proportionally to revenue share — "
                   "expenses aren't tagged to offerings or clients yet, so "
                   "true direct-cost margins aren't possible. Contribution "
                   "dollars still rank customers and offerings honestly."),
        "needs_gl": bool(rev.get("needs_gl")),
    }


# ─── Time-based trends ───────────────────────────────────────────────

def trends(biz: str) -> Dict[str, Any]:
    today = gl_engine._today()
    lines = [l for l in gl_reports.effective_lines(biz)
             if not gl_reports_t2._is_structural(str(l.get("source_type") or ""))]

    rev_m: Dict[str, float] = {}
    exp_m: Dict[str, float] = {}
    for l in lines:
        k = str(l.get("entry_date") or "")[:7]
        if not k:
            continue
        if l.get("account_type") == "income":
            rev_m[k] = round(rev_m.get(k, 0.0) + float(l["credit"]) - float(l["debit"]), 2)
        elif l.get("account_type") == "expense":
            exp_m[k] = round(exp_m.get(k, 0.0) + float(l["debit"]) - float(l["credit"]), 2)

    # Trailing 12 months (including current).
    months: List[str] = []
    cur = today.replace(day=1)
    for _ in range(12):
        months.append(_month_key(cur))
        cur = (cur - timedelta(days=1)).replace(day=1)
    months.reverse()
    series = [{"month": m, "revenue": rev_m.get(m, 0.0), "expenses": exp_m.get(m, 0.0),
               "net": round(rev_m.get(m, 0.0) - exp_m.get(m, 0.0), 2)} for m in months]

    # Seasonality: average revenue by calendar month over ALL history.
    by_cal: Dict[int, List[float]] = {}
    for k, v in rev_m.items():
        try:
            mnum = int(k[5:7])
        except Exception:
            continue
        by_cal.setdefault(mnum, []).append(v)
    seasonality = [{"month_num": m,
                    "avg_revenue": round(sum(vs) / len(vs), 2),
                    "samples": len(vs)}
                   for m, vs in sorted(by_cal.items())]

    # Momentum: last 3 full months vs the prior 3.
    full = [m for m in months if m < _month_key(today)]
    last3 = full[-3:]
    prior3 = full[-6:-3]
    def _avg(keys, src):
        vals = [src.get(k, 0.0) for k in keys]
        return round(sum(vals) / len(vals), 2) if vals else 0.0
    momentum = {
        "revenue_last3_avg": _avg(last3, rev_m),
        "revenue_prior3_avg": _avg(prior3, rev_m),
        "revenue_change_pct": reports_engine._pct_change(_avg(last3, rev_m), _avg(prior3, rev_m)),
        "expenses_last3_avg": _avg(last3, exp_m),
        "expenses_prior3_avg": _avg(prior3, exp_m),
        "expenses_change_pct": reports_engine._pct_change(_avg(last3, exp_m), _avg(prior3, exp_m)),
    }

    return {"ok": True, "report": "trends", "as_of": today.isoformat(),
            "monthly": series, "seasonality": seasonality, "momentum": momentum}
