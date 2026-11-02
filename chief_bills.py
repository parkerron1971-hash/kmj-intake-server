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

Who may: the Bills tab's readers (owner, accountant, a seat with view; in a
church the owner, an Admin or the accountant); switched with Chief's
categories (CHIEF_BANK_SEARCH). Adding and removing: the Bills tab's writers
(bills_router._writer: the owner, or a church's Admin seat).

STEP 3 (2026-11-01), Chief adds bills:
    ADD ............. add_bill: a one-time or recurring bill, under a saved
                      category (its spelling and line) or a line; the owner's
                      own words, filed at once, one undo (remove_bill)
    RECURRING ....... starts on its next due date, today or later: a start in
                      the past is moved forward a step at a time, so the Bills
                      tab never makes copies for months already paid from the
                      bank (each would count a second time until matched)
    ALREADY PAID .... a one-time bill a bank payment already fits is added,
                      and the reply offers the match (bill_payments) so it
                      counts once
    SUGGESTIONS ..... could_be_bills: payees paid about monthly from the bank
                      (3+ times in 4 months, gaps of 25-35 days, amounts within
                      20%), not a recurring bill yet: the amount, the next due
                      date and how they were filed
    REMOVE .......... remove_bill: a bill still owed and never matched (and a
                      recurring one's owed copies); the closed-month lock
                      applies; anything paid stays
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

    # Bills step 2: an owed bill with one plain bank payment that paid it.
    try:
        import bill_payments
        paid_by = bill_payments.suggestions(business_id, owed[:SHOWN])
    except Exception as e:                           # a suggestion never breaks the lookup
        print(f"[chief_bills] bank suggestions skipped for {business_id}: {e}")
        paid_by = {}

    def row(b: Dict[str, Any]) -> Dict[str, Any]:
        out = {"id": b["id"], "vendor": b.get("vendor_name"), "amount": float(b.get("amount") or 0),
               "due": b.get("due_date"), "line": line(b), "overdue": b in late}
        hit = paid_by.get(str(b["id"]))
        if hit:
            out["looks_paid_by"] = {k: hit[k] for k in ("transaction_id", "date", "description", "amount")}
        return out
    try:
        maybe = could_be_bills(business_id, templates, today)
    except Exception as e:                           # a suggestion never breaks the lookup
        print(f"[chief_bills] recurring suggestions skipped for {business_id}: {e}")
        maybe = []
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
        if paid_by:
            text += (f" {len(paid_by)} owed bill(s) look already paid from the bank (see looks_paid_by): matching "
                     "them makes each count once.")
        if soon:
            text += " Coming up: " + "; ".join(f"{b.get('vendor_name')} {_money(b.get('amount'))} on {b.get('due_date')}"
                                               for b in soon[:6]) + "."
    if maybe:
        text += (f" {len(maybe)} payee(s) are paid about monthly from the bank but aren't a recurring bill yet "
                 "(see could_be_bills).")
    if cut:
        text += f" Only the newest {CAP} bills were read, so the oldest aren't counted here."
    return {"type": atype, "label": f"Bills · {len(owed)} owed", "result": text, "nav": NAV,
            "owed": [row(b) for b in owed[:SHOWN]], "recurring": repeat[:SHOWN], "total_owed": total,
            "overdue": len(late), "due_30_days": len(soon), "paid_30_days": len(paid), "could_be_bills": maybe,
            "note_for_chief": (
                "This is the Bills tab: bills owed, separate from the bank payments filed under categories. A bill "
                "can file under one of the business's categories (its line and name). Add one with add_bill when the "
                "owner asks. could_be_bills are payees paid about monthly from the bank: offer each as a recurring "
                "bill starting at its next_due (never a past date), under how it was filed; ask first. Where a bill "
                "has looks_paid_by, offer to match it (match_bill_payment) so it counts once; ask first. Never enter "
                "a bill for a payment already made and filed unless it's then matched.")}


async def handle_bills(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(status, str(biz["id"]))


# ─── Step 3: Chief adds bills ────────────────────────────────────────

MONTHLY = (25, 35)
SPREAD = 0.20
LOOKBACK = 124


def could_be_bills(business_id: str, templates: List[Dict[str, Any]], today: date) -> List[Dict[str, Any]]:
    """Payees paid about monthly from the bank that aren't a recurring bill yet."""
    import bank_picks
    import bill_payments
    accts = bank_picks.accounts(business_id, _get)
    if not accts:
        return []
    rows = bank_picks.read_all(
        f"/plaid_transactions?business_id=eq.{quote(business_id, safe='')}&account_id={bank_picks.in_(accts)}"
        f"&amount=gt.0&pending=eq.false&excluded_from_books=eq.false&money_kind=is.null"
        f"&date=gte.{(today - timedelta(days=LOOKBACK)).isoformat()}"
        "&select=transaction_id,date,name,merchant_name,amount,business_category,business_subcategory"
        "&order=date.asc,transaction_id.asc", _get)
    covered = [bill_payments._tokens(t.get("vendor_name")) for t in templates]
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for t in rows:
        k = bank_picks.payee_key(bank_picks.words(t))
        if k:
            groups.setdefault(k, []).append(t)
    out = []
    for k, g in groups.items():
        if len(g) < 3:
            continue
        days = sorted(_d(t.get("date")) for t in g if _d(t.get("date")))
        gaps = [(b - a).days for a, b in zip(days, days[1:])]
        if not gaps or not all(MONTHLY[0] <= x <= MONTHLY[1] for x in gaps):
            continue
        amounts = sorted(float(t.get("amount") or 0) for t in g)
        mid = amounts[len(amounts) // 2]
        if mid <= 0 or any(abs(a - mid) > mid * SPREAD for a in amounts):
            continue
        if any(c & bill_payments._tokens(k) for c in covered):
            continue
        last = g[-1]
        nxt = days[-1]
        import bills_router
        n = 0
        while nxt < today and n < 24:
            n += 1
            nxt = bills_router._step(days[-1], "monthly", n)
        out.append({"payee": bank_picks.words(last), "payee_key": k, "times": len(g),
                    "amount": float(last.get("amount") or 0), "every": "monthly", "next_due": nxt.isoformat(),
                    "category": last.get("business_subcategory"), "line": last.get("business_category")})
    return sorted(out, key=lambda x: -x["times"])[:10]


def _owner_gate(business_id: str) -> Optional[str]:
    import chief_transactions
    if not chief_transactions.switched_on(business_id):
        return "Bills from chat aren't switched on for this business yet."
    from chief_of_staff import _TURN_USER_ID
    uid = _TURN_USER_ID.get()
    if not uid:
        return "Bills are added only by a signed-in person who keeps the books."
    import bills_router
    try:
        bills_router._writer(business_id, SimpleNamespace(id=uid))
    except HTTPException:
        return "Only the owner, or a church's Admin, adds or removes bills, the same as on the Bills tab."
    return None


def _matches_bank(business_id: str) -> bool:
    """Whether the person talking may match a bill to the bank (bill_payments:
    the owner alone, the same as on the Bills tab). Only they are shown a
    bank payment that fits a new bill."""
    from chief_of_staff import _TURN_USER_ID
    import bills_router
    try:
        bills_router._owner(business_id, SimpleNamespace(id=_TURN_USER_ID.get()))
    except HTTPException:
        return False
    return True


def _fail(atype: str, msg: str) -> Dict[str, Any]:
    return {"type": atype, "result": f"Failed: {msg}", "label": msg[:80], "failed": True, "nav": NAV}


def add_sync(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """Chief: a bill the owner asked for, in their words."""
    atype = "add_bill"
    refused = _owner_gate(business_id)
    if refused:
        return _fail(atype, refused)
    import bills_router
    import expense_lines
    vendor = " ".join(str(action.get("vendor") or "").split())[:120]
    try:
        amount = round(float(action.get("amount")), 2)
    except (TypeError, ValueError):
        amount = 0.0
    due = _d(action.get("due_date"))
    every = str(action.get("every") or "").strip().lower() or None
    if not vendor or amount <= 0 or not due:
        return _fail(atype, "say who it's to, how much and when it's due")
    if every and every not in bills_router._FREQS:
        return _fail(atype, f"a recurring bill repeats {', '.join(bills_router._FREQS)}")
    today = datetime.now(timezone.utc).date()
    moved = None
    if every and due < today:                      # never copies for months already paid
        start, n = due, 0
        while due < today and n < 400:
            n += 1
            due = bills_router._step(start, every, n)
        moved = start
    try:
        ls = expense_lines.lines(business_id)
        line = expense_lines.find(ls, action.get("line")) if action.get("line") else None
        bucket = (line or {}).get("base") or "operating"
        bucket, sub = bills_router._saved_category(business_id, bucket, action.get("category"))
        if bucket not in bills_router._BUCKETS:
            bucket = "operating"
        payload = {
            "business_id": business_id, "vendor_name": vendor, "amount": amount,
            "description": (str(action.get("description") or "").strip() or None),
            "category": bucket, "subcategory": (str(sub).strip() or None) if sub else None,
            "due_date": due.isoformat(), "status": "pending", "is_recurring": bool(every),
            "recurrence_frequency": every, "recurrence_start": due.isoformat() if every else None,
            "recurrence_end_type": "never" if every else None, "recurrence_end_value": None,
            "recurrence_index": 0, "is_1099_eligible": False, "notes": None}
        made = sb_clients.sb_post_as_service("/bills", payload)
        row = (made[0] if isinstance(made, list) and made else made) if made else None
        if not isinstance(row, dict) or not row.get("id"):
            return _fail(atype, "the bill didn't save; nothing was added")
    except _Unavailable:
        return _fail(atype, "the bills couldn't be read just now; nothing was added")
    on = expense_lines.said(ls, bucket) + (f", {payload['subcategory']}" if payload["subcategory"] else "")
    text = (f"Added a {every} bill: {vendor}, {_money(amount)}, next due {due.isoformat()}, under {on}."
            if every else f"Added a bill: {vendor}, {_money(amount)}, due {due.isoformat()}, under {on}.")
    if moved:
        text += (f" It starts on {due.isoformat()}, not {moved.isoformat()}: the months before are already paid from "
                 "the bank, and copies for them would count twice.")
    out = {"type": atype, "result": text + " One undo removes it.", "label": f"🧾 {vendor} {_money(amount)}",
           "bill_id": str(row["id"]), "nav": NAV}
    # One-time or the first copy of a recurring bill: a bank payment that
    # already fits is offered for the match, so it never counts twice.
    try:
        import bill_payments
        fit = (bill_payments.clear_one(bill_payments.candidates(business_id, row))
               if _matches_bank(business_id) else None)
    except Exception:
        fit = None
    if fit:
        out["looks_paid_by"] = {k: fit[k] for k in ("transaction_id", "date", "description", "amount")}
        out["result"] += (f" It looks already paid by the {_money(fit['amount'])} bank payment on {fit['date']} "
                          f"({fit['description']}): offer to match it so it counts once.")
    return out


def remove_sync(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """Chief: a bill still owed and never matched goes (and a recurring one's
    owed copies); anything paid stays."""
    atype = "remove_bill"
    refused = _owner_gate(business_id)
    if refused:
        return _fail(atype, refused)
    bid = str(action.get("bill_id") or "").strip()
    if not bid:
        return _fail(atype, "say which bill (its bill_id from the bills lookup)")
    from chief_of_staff import _TURN_USER_ID
    import period_lock
    q = quote(business_id, safe="")
    try:
        rows = _get(f"/bills?id=eq.{quote(bid, safe='')}&business_id=eq.{q}"
                    "&select=id,vendor_name,amount,status,created_at,paid_transaction_id,is_recurring&limit=1")
        if not rows:
            return _fail(atype, "that bill isn't here any more")
        b = rows[0]
        if (b.get("status") or "pending") not in OPEN or b.get("paid_transaction_id"):
            return _fail(atype, f"the {b.get('vendor_name')} bill is {b.get('status')}, so it stays (paid bills are "
                                "the books' record)")
        kids = _get(f"/bills?business_id=eq.{q}&recurrence_parent_id=eq.{quote(bid, safe='')}"
                    "&select=id,status,created_at,paid_transaction_id&limit=500") if b.get("is_recurring") else []
        gone = [b] + [k for k in kids if (k.get("status") or "pending") in OPEN and not k.get("paid_transaction_id")]
        for g in gone:
            period_lock.guard(business_id, str(g.get("created_at") or "")[:10], source_type="bill",
                              source_id=str(g["id"]), reason=None, override_by=str(_TURN_USER_ID.get() or ""),
                              pre=g, post=None)
        done = 0
        for g in reversed(gone):                     # copies first, the bill last
            if not sb_clients.sb_delete_as_service(f"/bills?id=eq.{quote(str(g['id']), safe='')}&business_id=eq.{q}"
                                                   "&paid_transaction_id=is.null"):
                return _fail(atype, (f"only {done} of the {len(gone)} owed copies came out before a delete failed; "
                                     "the bill itself is still there, so ask again to finish") if done else
                             "the bill didn't delete just now; nothing changed, so ask again")
            done += 1
    except HTTPException as e:
        detail = e.detail.get("message") if isinstance(e.detail, dict) else e.detail
        return _fail(atype, str(detail or "that month is closed"))
    except _Unavailable:
        return _fail(atype, "the bills couldn't be read just now; nothing was removed")
    kept = len(kids) - (len(gone) - 1)
    text = f"Removed the {b.get('vendor_name')} bill ({_money(b.get('amount'))})"
    text += f" and its {len(gone) - 1} owed copies" if len(gone) > 1 else ""
    text += f"; {kept} paid copies stay as the record." if kept else "."
    return {"type": atype, "result": text, "label": f"🗑 {b.get('vendor_name')}", "nav": NAV}


async def handle_add_bill(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(add_sync, str(biz["id"]), action or {})


async def handle_remove_bill(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(remove_sync, str(biz["id"]), action or {})
