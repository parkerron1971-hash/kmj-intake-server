"""
chief_expense_actions.py — Chief verbs for manual business expenses.

THE GAP THIS CLOSES (S10)
  `business_expenses` has a table, a 5-bucket category scheme, GL
  triggers, P&L reports and RLS — and had zero verbs. A practitioner
  could not say "log $40 for gas" without opening the Expenses screen.

GL COHERENCE — WHY THIS INSERTS A PLAIN ROW AND NOTHING ELSE
  The GL does not need to be told. `gl_enq_expenses_ins/upd` (Phase I.2
  triggers) enqueue every INSERT/UPDATE/DELETE on business_expenses into
  gl_sync_queue, and gl_engine.process_queue converges each row via
  desired_for_expense — which reads exactly amount / category /
  subcategory / vendor / date. So a Chief-logged expense flows to the
  P&L through the SAME path as a UI-logged one, provided the row shape
  matches. This module mirrors RevenueExpenses.tsx's insert shape
  (business_id, amount, category, subcategory, description, date) plus
  the `vendor` column desired_for_expense reads for its memo line.

CATEGORIES — THE 5-BUCKET SCHEME IS A CHECK CONSTRAINT
  tax | owner_pay | operating | savings | other — the same vocabulary
  RevenueExpenses.tsx hardcodes and plaid_categorization.ALL_BUCKETS
  exports (they must agree with the DB CHECK). An unknown category is
  rejected with the valid list, not guessed at — a wrong bucket feeds
  the Allocator and the tax set-aside math. Missing category defaults to
  'operating', the same default the UI form opens with.

CLOSED PERIODS
  period_lock.locked_period answers whether a date is inside a CLOSED
  accounting period. Writes that touch a locked date are REFUSED here —
  the app's soft-lock flow exists precisely to collect an audited
  override reason (period_edit_overrides), and Chief silently editing
  closed books would bypass that trail (the R3 "never silent" rule).
  The refusal names the period and points at the app flow.

CLASSIFICATION
  log_expense    — class A: creates an editable row; a wrong one is an
                   edit (or delete) away from right.
  list_expenses  — read.
  update_expense — class C single-target: edits a financial record that
                   reposts GL entries; proposal-only unprompted.
  delete_expense — class C single-target: hard delete of a financial
                   record (the GL trigger reverses its entries). Also
                   the MANUAL inverse of log_expense until the undo
                   registry (action_inverse — other ownership) rules.

  House contract: every return carries `result` + `label`; failures
  carry `"failed": True`. Timestamps in query strings use the Z form.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import sb_clients
import period_lock
from plaid_categorization import ALL_BUCKETS

logger = logging.getLogger("chief_expense_actions")

CATEGORY_LABELS = {
    "tax": "Tax", "owner_pay": "Owner Pay", "operating": "Operating",
    "savings": "Savings", "other": "Other",
}
_CATEGORY_HELP = ", ".join(ALL_BUCKETS)

# Obvious spellings only — anything cleverer belongs to the practitioner.
_CATEGORY_ALIASES = {"taxes": "tax", "ownerpay": "owner_pay", "owner": "owner_pay"}


def _fail(action_type: str, msg: str) -> Dict[str, Any]:
    return {"type": action_type, "result": f"failed: {msg}", "label": msg[:80],
            "nav": None, "failed": True}


def _nav_expenses() -> Optional[Dict[str, Any]]:
    try:
        from chief_of_staff import _nav
        return _nav("grow", "revenue")
    except Exception:
        return None


def _norm_category(raw: Any) -> Optional[str]:
    """Normalize to a bucket id, or None when it isn't one. 'Owner Pay',
    'owner_pay' and 'taxes' all land; 'groceries' does not."""
    c = str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    c = _CATEGORY_ALIASES.get(c, c)
    return c if c in ALL_BUCKETS else None


def _parse_date(raw: Any) -> Optional[str]:
    """YYYY-MM-DD or None. Rejects rather than guesses at other shapes."""
    s = str(raw or "").strip()[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _fmt_money(v: Any) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def _locked(biz_id: str, day: str) -> Optional[Dict[str, Any]]:
    return period_lock.locked_period(biz_id, day)


def _locked_msg(period: Dict[str, Any], verb_phrase: str) -> str:
    return (f"that date is in a CLOSED accounting period "
            f"({period.get('period_start')}–{period.get('period_end')}), so I "
            f"won't {verb_phrase} from chat. Closed books need an audited "
            f"override reason — use Bookkeeping → Expenses in the app, or "
            f"reopen the period first.")


async def _get_expense(biz_id: str, expense_id: str) -> Optional[Dict[str, Any]]:
    """Business-scoped fetch — an id from another business must not resolve."""
    rows = await asyncio.to_thread(
        sb_clients.sb_get_as_service,
        f"/business_expenses?id=eq.{expense_id}&business_id=eq.{biz_id}"
        f"&select=*&limit=1")
    return (rows or [None])[0]


def _describe(row: Dict[str, Any]) -> str:
    who = row.get("vendor") or row.get("description") or ""
    tail = f" ({who})" if who else ""
    cat = CATEGORY_LABELS.get(row.get("category"), row.get("category"))
    return f"{_fmt_money(row.get('amount'))} {cat} expense from {row.get('date')}{tail}"


# ─── log (class A) ───────────────────────────────────────────────────

async def handle_log_expense(client, biz, action) -> Dict[str, Any]:
    try:
        amount = round(float(action.get("amount")), 2)
    except (TypeError, ValueError):
        return _fail("log_expense", "amount must be a number")
    if amount <= 0:
        return _fail("log_expense", "amount must be greater than 0")

    raw_cat = action.get("category")
    if raw_cat in (None, ""):
        category = "operating"          # the UI form's own default
    else:
        category = _norm_category(raw_cat)
        if not category:
            return _fail("log_expense",
                         f"'{raw_cat}' isn't an expense category. The books "
                         f"use five buckets: {_CATEGORY_HELP}. Pick the one "
                         f"this belongs in (day-to-day costs are 'operating').")

    if action.get("date") in (None, ""):
        day = _today()
    else:
        day = _parse_date(action.get("date"))
        if not day:
            return _fail("log_expense", "date must be YYYY-MM-DD")

    period = await asyncio.to_thread(_locked, biz["id"], day)
    if period:
        return _fail("log_expense", _locked_msg(period, "add an expense to it"))

    # Mirror RevenueExpenses.tsx's insert shape exactly (plus vendor,
    # which desired_for_expense reads into the GL memo). The gl_sync
    # trigger picks the row up from here — do NOT post GL entries.
    payload: Dict[str, Any] = {
        "business_id": biz["id"],
        "amount": amount,
        "category": category,
        "subcategory": (action.get("subcategory") or "").strip() or None,
        "description": (action.get("note") or action.get("description") or "").strip() or None,
        "date": day,
    }
    vendor = (action.get("vendor") or "").strip()
    if vendor:
        payload["vendor"] = vendor

    rows = await asyncio.to_thread(
        sb_clients.sb_post_as_service, "/business_expenses", payload)
    row = (rows or [None])[0] if isinstance(rows, list) else rows
    if not row:
        return _fail("log_expense", "insert failed")

    cat_label = CATEGORY_LABELS[category]
    who = f" — {vendor}" if vendor else ""
    return {
        "type": "log_expense",
        "expense_id": row.get("id"),
        "result": (f"logged {_fmt_money(amount)} ({cat_label}){who} on {day}. "
                   f"It's in the books and flows to the P&L automatically."),
        "label": f"{_fmt_money(amount)} {cat_label}{who} · {day}",
        "nav": _nav_expenses(),
    }


# ─── list (read) ─────────────────────────────────────────────────────

def _month_bounds(month: str) -> Optional[Tuple[str, str]]:
    try:
        start = datetime.strptime(month.strip()[:7], "%Y-%m")
    except ValueError:
        return None
    nxt = (start.replace(year=start.year + 1, month=1) if start.month == 12
           else start.replace(month=start.month + 1))
    return start.date().isoformat(), nxt.date().isoformat()


async def handle_list_expenses(client, biz, action) -> Dict[str, Any]:
    filters = ""
    scope_bits: List[str] = []

    month = (action.get("month") or "").strip()
    if month:
        bounds = _month_bounds(month)
        if not bounds:
            return _fail("list_expenses", "month must be YYYY-MM")
        filters += f"&date=gte.{bounds[0]}&date=lt.{bounds[1]}"
        scope_bits.append(month[:7])

    raw_cat = (action.get("category") or "").strip()
    if raw_cat:
        category = _norm_category(raw_cat)
        if not category:
            return _fail("list_expenses",
                         f"'{raw_cat}' isn't an expense category — "
                         f"valid: {_CATEGORY_HELP}")
        filters += f"&category=eq.{category}"
        scope_bits.append(CATEGORY_LABELS[category])

    rows = await asyncio.to_thread(
        sb_clients.sb_get_as_service,
        f"/business_expenses?business_id=eq.{biz['id']}{filters}"
        f"&order=date.desc,created_at.desc&select=*&limit=200") or []

    scope = " · ".join(scope_bits) if scope_bits else "recent"
    if not rows:
        return {
            "type": "list_expenses",
            "result": f"no expenses on file ({scope}).",
            "label": f"No expenses ({scope})",
            "nav": _nav_expenses(),
        }

    total = round(sum(float(r.get("amount") or 0) for r in rows), 2)
    lines = []
    for r in rows[:8]:
        who = r.get("vendor") or r.get("description") or ""
        who = f" · {who}" if who else ""
        lines.append(f"{r.get('date')} · {_fmt_money(r.get('amount'))} · "
                     f"{CATEGORY_LABELS.get(r.get('category'), r.get('category'))}{who}")
    more = f" (+{len(rows) - 8} more)" if len(rows) > 8 else ""
    n = len(rows)
    return {
        "type": "list_expenses",
        "result": (f"{n} expense{'s' if n != 1 else ''} ({scope}) totaling "
                   f"{_fmt_money(total)}: " + "; ".join(lines) + more),
        "label": f"{n} expense{'s' if n != 1 else ''} · {_fmt_money(total)} ({scope})",
        "nav": _nav_expenses(),
    }


# ─── update (class C single-target) ──────────────────────────────────

async def handle_update_expense(client, biz, action) -> Dict[str, Any]:
    expense_id = (action.get("expense_id") or "").strip()
    if not expense_id:
        return _fail("update_expense",
                     "expense_id required — use list_expenses to find it")
    row = await _get_expense(biz["id"], expense_id)
    if not row:
        return _fail("update_expense", f"expense {expense_id} not found")

    patch: Dict[str, Any] = {}
    changed: List[str] = []

    if action.get("amount") is not None:
        try:
            amount = round(float(action.get("amount")), 2)
        except (TypeError, ValueError):
            return _fail("update_expense", "amount must be a number")
        if amount <= 0:
            return _fail("update_expense", "amount must be greater than 0")
        patch["amount"] = amount
        changed.append(f"amount → {_fmt_money(amount)}")

    if action.get("category") not in (None, ""):
        category = _norm_category(action.get("category"))
        if not category:
            return _fail("update_expense",
                         f"'{action.get('category')}' isn't an expense category — "
                         f"valid: {_CATEGORY_HELP}")
        patch["category"] = category
        changed.append(f"category → {CATEGORY_LABELS[category]}")

    new_day: Optional[str] = None
    if action.get("date") not in (None, ""):
        new_day = _parse_date(action.get("date"))
        if not new_day:
            return _fail("update_expense", "date must be YYYY-MM-DD")
        patch["date"] = new_day
        changed.append(f"date → {new_day}")

    for arg, col in (("subcategory", "subcategory"), ("vendor", "vendor"),
                     ("note", "description"), ("description", "description")):
        if action.get(arg) is not None and col not in patch:
            patch[col] = str(action.get(arg)).strip() or None
            changed.append(col)

    if not patch:
        return _fail("update_expense", "nothing to change — pass amount, "
                                       "category, date, vendor, or note")

    # Closed-period guard on BOTH sides of the edit: the row's current
    # date (rewriting closed books) and any new date (writing into them).
    for day, phrase in ((row.get("date"), "edit it"),
                        (new_day, "move it there")):
        if not day:
            continue
        period = await asyncio.to_thread(_locked, biz["id"], str(day)[:10])
        if period:
            return _fail("update_expense", _locked_msg(period, phrase))

    res = await asyncio.to_thread(
        sb_clients.sb_patch_as_service,
        f"/business_expenses?id=eq.{expense_id}&business_id=eq.{biz['id']}",
        patch)
    # Service PATCH prefers return=representation: success returns the
    # updated row(s); None is a transport/PostgREST error, [] means the
    # row vanished between the fetch above and now.
    if not res:
        return _fail("update_expense", "update failed")

    return {
        "type": "update_expense",
        "expense_id": expense_id,
        "result": (f"updated the {_describe(row)}: {', '.join(changed)}. "
                   f"The books adjust automatically."),
        "label": f"Updated expense — {', '.join(changed)}"[:120],
        "nav": _nav_expenses(),
    }


# ─── delete (class C single-target; the manual inverse of log_expense) ─

async def handle_delete_expense(client, biz, action) -> Dict[str, Any]:
    expense_id = (action.get("expense_id") or "").strip()
    if not expense_id:
        return _fail("delete_expense",
                     "expense_id required — use list_expenses to find it")
    row = await _get_expense(biz["id"], expense_id)
    if not row:
        return _fail("delete_expense", f"expense {expense_id} not found")

    day = str(row.get("date") or "")[:10]
    if day:
        period = await asyncio.to_thread(_locked, biz["id"], day)
        if period:
            return _fail("delete_expense", _locked_msg(period, "delete it"))

    ok = await asyncio.to_thread(
        sb_clients.sb_delete_as_service,
        f"/business_expenses?id=eq.{expense_id}&business_id=eq.{biz['id']}")
    if not ok:
        return _fail("delete_expense", "delete failed")

    return {
        "type": "delete_expense",
        "expense_id": expense_id,
        "result": (f"deleted the {_describe(row)}. Its ledger entries reverse "
                   f"automatically."),
        "label": f"Deleted {_describe(row)}"[:120],
        "nav": _nav_expenses(),
    }
