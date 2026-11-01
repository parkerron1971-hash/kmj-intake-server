"""
chief_bills.py — Chief reads the Bills tab.

Kevin, 2026-11-01, after Chief made Utilities, Service Platform and Streaming
Software: "want to see if it could put under bill tab as well. it doesn't see
the bill tab." Chief answered that it had no lookup for Bills, which was true.

    THE LOOKUP ...... the bills the business owes (pending, scheduled, overdue),
                      what's due in the next 30 days, the recurring ones and
                      when each comes due next, what was paid in the last 30
                      days, and the total owed (accounts payable); each bill's
                      line by the business's own names (expense_lines) and its
                      category, so Chief can say where a bill files
    NO SIDE EFFECTS . the Bills tab makes a recurring bill's due copies and
                      marks late ones overdue when it opens; this lookup only
                      reads: a pending bill past due is SAID overdue, nothing
                      is written

Who may: the Bills tab's readers (owner, accountant, a seat with view);
switched with Chief's categories (CHIEF_BANK_SEARCH). Adding a bill from chat
and matching a bill to the bank payment that paid it come next (see the
worklog); until then Chief says so plainly.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import HTTPException

import sb_clients

OPEN = ("pending", "scheduled", "overdue")
SHOWN = 40
CAP = 2000
NAV = {"tab": "operate", "sub": "bookkeeping", "bkTab": "bills"}

TOOL = {
    "name": "bills",
    "description": (
        "The Bills tab: bills this business owes (accounts payable) with who, how much, when due and the line and "
        "category each files under; what's overdue and due in the next 30 days; the recurring bills and when each "
        "comes due next; what was paid in the last 30 days; and the total owed. Use it for 'what bills are due', "
        "'is my rent bill in there', 'what do I owe', or before saying anything about the Bills tab. Quote its "
        "figures."),
    "input_schema": {"type": "object", "properties": {}},
}


class _Unavailable(Exception):
    pass


def _get(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if rows is None:
        raise _Unavailable(path.split("?")[0])
    return rows


def _d(s: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _money(v: Any) -> str:
    return f"${float(v or 0):,.2f}"


def _gate(business_id: str) -> Optional[str]:
    import chief_transactions
    if not chief_transactions.switched_on(business_id):
        return "Bills from chat aren't switched on for this business yet."
    from chief_of_staff import _TURN_USER_ID
    uid = _TURN_USER_ID.get()
    if not uid:
        return "Bills are read only for a signed-in person who can see them."
    import bills_router
    try:
        bills_router._reader(business_id, SimpleNamespace(id=uid))
    except HTTPException as e:
        return str(e.detail if not isinstance(e.detail, dict) else e.detail.get("message") or "not allowed")
    return None


def _next_due(b: Dict[str, Any], today: date) -> Optional[date]:
    """A recurring bill's next due date on or after today (from its start),
    by the Bills tab's own rules: none once paused, cancelled or past its end
    (an end date, or a number of bills)."""
    import bills_router
    start = _d(b.get("recurrence_start") or b.get("due_date"))
    freq = b.get("recurrence_frequency")
    if not start or freq not in bills_router._FREQS or b.get("recurrence_paused") or b.get("status") == "cancelled":
        return None
    n, d = 0, start
    while d < today and n < 400:
        n += 1
        d = bills_router._step(start, freq, n)
    end_type, end_val = b.get("recurrence_end_type") or "never", b.get("recurrence_end_value")
    if end_type == "on_date" and _d(end_val) and d > _d(end_val):
        return None
    if end_type == "after_count":
        try:
            if n >= int(end_val):
                return None
        except (TypeError, ValueError):
            pass
    return d


def status(business_id: str) -> Dict[str, Any]:
    atype = "bills"
    refused = _gate(business_id)
    if refused:
        return {"type": atype, "result": f"Failed: {refused}", "label": "Bills", "failed": True, "nav": NAV}
    import expense_lines
    today = datetime.now(timezone.utc).date()
    try:
        rows = _get(f"/bills?business_id=eq.{quote(business_id, safe='')}"
                    "&select=id,vendor_name,amount,category,subcategory,status,due_date,paid_at,paid_amount,"
                    "is_recurring,recurrence_frequency,recurrence_start,recurrence_paused,recurrence_parent_id,"
                    f"recurrence_end_type,recurrence_end_value&order=due_date.desc.nullsfirst&limit={CAP}")
    except _Unavailable:
        return {"type": atype, "result": "Failed: the bills couldn't be read just now. This is not 'no bills'.",
                "label": "Bills", "failed": True, "nav": NAV}
    cut = len(rows) >= CAP                           # read newest first, so a cap drops the oldest
    rows.sort(key=lambda b: (b.get("due_date") is None, str(b.get("due_date") or "")))   # shown by due date
    names = expense_lines.names(business_id)
    # A bill under a saved category on a line of the business's own shows on
    # that line, as the Profit & Loss shows it (expense_lines.present).
    import expense_categories as ec
    try:
        own = {ec.key_of(c["name"]): c["line"] for c in ec.categories(business_id) if c.get("line") in names}
    except Exception:
        own = {}

    def line(b: Dict[str, Any]) -> str:
        key = own.get(ec.key_of(b.get("subcategory"))) if b.get("subcategory") else None
        on = names.get(key or b.get("category") or "operating") or "Operating"
        return f"{on}, {b['subcategory']}" if b.get("subcategory") else on

    templates = [b for b in rows if b.get("is_recurring") and not b.get("recurrence_parent_id")
                 and b.get("status") != "cancelled"]
    # A recurring bill's template is its first copy (due on its start): owed like any other.
    owed = [b for b in rows if (b.get("status") or "pending") in OPEN]
    late = [b for b in owed if b.get("status") == "overdue" or ((_d(b.get("due_date")) or today) < today)]
    soon = [b for b in owed if b not in late and _d(b.get("due_date")) and _d(b.get("due_date")) <= today + timedelta(days=30)]
    paid = [b for b in rows if b.get("status") == "paid" and _d(b.get("paid_at")) and
            _d(b.get("paid_at")) >= today - timedelta(days=30)]
    total = round(sum(float(b.get("amount") or 0) for b in owed), 2)

    def row(b: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": b["id"], "vendor": b.get("vendor_name"), "amount": float(b.get("amount") or 0),
                "due": b.get("due_date"), "line": line(b), "overdue": b in late}
    repeat = [{"vendor": b.get("vendor_name"), "amount": float(b.get("amount") or 0),
               "every": b.get("recurrence_frequency"), "paused": bool(b.get("recurrence_paused")),
               "next_due": (lambda d: d.isoformat() if d else None)(_next_due(b, today)), "line": line(b)}
              for b in templates]
    if not rows:
        text = "The Bills tab is empty: no bills are entered, so nothing is owed there (accounts payable $0.00)."
    else:
        text = (f"{len(owed)} bill(s) owed, {_money(total)} in all; {len(late)} overdue, {len(soon)} due in the next "
                f"30 days; {len(templates)} recurring; {len(paid)} paid in the last 30 days.")
        if late:
            text += " Overdue: " + "; ".join(f"{b.get('vendor_name')} {_money(b.get('amount'))} (due {b.get('due_date')})"
                                             for b in late[:6]) + "."
        if soon:
            text += " Coming up: " + "; ".join(f"{b.get('vendor_name')} {_money(b.get('amount'))} on {b.get('due_date')}"
                                               for b in soon[:6]) + "."
    if cut:
        text += f" Only the newest {CAP} bills were read, so the oldest aren't counted here."
    return {"type": atype, "label": f"Bills · {len(owed)} owed", "result": text, "nav": NAV,
            "owed": [row(b) for b in owed[:SHOWN]], "recurring": repeat[:SHOWN], "total_owed": total,
            "overdue": len(late), "due_30_days": len(soon), "paid_30_days": len(paid),
            "note_for_chief": (
                "This is the Bills tab: bills owed, separate from the bank payments filed under categories. A bill "
                "can file under one of the business's categories (its line and name). Adding a bill from chat isn't "
                "here yet: say it's added on the Bills tab (Bookkeeping, Bills, New bill), where the category box "
                "offers their saved categories. Don't suggest entering a bill for something already paid from the "
                "bank and filed: the bank payment is already in the books.")}


async def handle_bills(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(status, str(biz["id"]))
