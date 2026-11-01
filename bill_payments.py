"""
bill_payments.py — a bill matched to the bank payment that paid it (Bills,
step 2 of 3).

Kevin, 2026-11-01: the categories Chief made should work under the Bills tab
too. Before Chief adds bills (step 3), a bill and the bank payment that paid
it must count once:

    WHY ............. a bill books Dr expense / Cr AP when entered; "Mark paid"
                      books Dr AP / Cr cash. The bank payment for it, filed
                      under a category, books Dr expense / Cr cash too. So the
                      ledger took the cash out twice (and an accrual view
                      counted the expense twice). The cash-basis P&L, the
                      default, ignores bills, so reports weren't doubled
    THE MATCH ....... the bill is paid by that bank row (bills.paid_transaction_id;
                      one bank row pays one bill: a unique index). The ledger
                      then books a bill_settle on the payment date, Dr AP / Cr
                      the bill's expense, instead of a second cash leg
                      (gl_engine.desired_for_bill). The bank row stays the
                      cash payment and its filing stands: the expense counts
                      once on either basis, accounts payable clears, cash
                      goes out once
    THE BANK ROW .... still waiting for an answer: it takes the bill's line and
                      category. Already filed: left as filed. It must be money
                      out, in the books, and not owner/transfer/gift money
    CANDIDATES ...... money out within 20 days before to 45 after the bill's
                      due date (or entry), not already paying a bill; scored by
                      the amount (exact, or within 10%) and the payee's words
                      against the vendor's. CLEAR: exactly one exact-amount
                      row in the window, or one exact-amount row whose payee
                      matches the vendor
    UNMATCH ......... the bill is owed again (overdue if past due); the bank
                      row keeps its filing

Who may: the owner (bills_router._owner); switched with Chief's categories
(CHIEF_BANK_SEARCH). Migration: supabase/APPLY-2026-11-01-bill-bank-payments.sql.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, require_user

router = APIRouter(prefix="/bills", tags=["bills"])

OPEN = ("pending", "scheduled", "overdue")
BEFORE_DAYS = 20
AFTER_DAYS = 45
NEAR = 0.10
NAV = {"tab": "operate", "sub": "bookkeeping", "bkTab": "bills"}
_STOP = {"the", "and", "inc", "llc", "co", "corp", "company", "payment", "pymt", "bill", "online", "debit", "card",
         "purchase", "pos", "ach", "web", "autopay", "recurring", "services", "service"}


class Unavailable(Exception):
    pass


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _get(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if rows is None:
        raise Unavailable(path.split("?")[0])
    return rows


def _d(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _money(v: Any) -> str:
    return f"${float(v or 0):,.2f}"


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _tokens(s: Any) -> set:
    return {w for w in re.split(r"[^a-z0-9]+", str(s or "").lower()) if len(w) >= 3 and w not in _STOP}


def switched_on(business_id: str) -> bool:
    import chief_transactions
    return bool(chief_transactions.switched_on(business_id))


# ─── Reads ───────────────────────────────────────────────────────────

def bill(business_id: str, bill_id: str) -> Optional[Dict[str, Any]]:
    rows = _get(f"/bills?id=eq.{_q(bill_id)}&business_id=eq.{_q(business_id)}"
                "&select=id,vendor_name,amount,category,subcategory,status,due_date,created_at,paid_at,paid_amount,"
                "paid_via,paid_transaction_id&limit=1")
    return rows[0] if rows else None


def _paying(business_id: str) -> Dict[str, str]:
    """bank row -> the bill it paid."""
    rows = _get(f"/bills?business_id=eq.{_q(business_id)}&paid_transaction_id=not.is.null"
                "&select=id,paid_transaction_id&limit=5000")
    return {str(r["paid_transaction_id"]): str(r["id"]) for r in rows}


def _window(b: Dict[str, Any]) -> Tuple[date, date]:
    anchor = _d(b.get("due_date")) or _d(b.get("created_at")) or _today()
    return anchor - timedelta(days=BEFORE_DAYS), anchor + timedelta(days=AFTER_DAYS)


def _money_out(business_id: str, start: date, end: date) -> List[Dict[str, Any]]:
    import bank_picks
    accts = bank_picks.accounts(business_id, _get)
    if not accts:
        return []
    return bank_picks.read_all(
        f"/plaid_transactions?business_id=eq.{_q(business_id)}&account_id={bank_picks.in_(accts)}"
        f"&amount=gt.0&pending=eq.false&excluded_from_books=eq.false&money_kind=is.null"
        f"&date=gte.{start.isoformat()}&date=lte.{end.isoformat()}"
        "&select=transaction_id,date,name,merchant_name,amount,business_category,business_subcategory"
        "&order=date.asc,transaction_id.asc", _get)


def score(b: Dict[str, Any], t: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """How well a bank row fits a bill, or None when it can't be its payment."""
    import bank_picks
    want, got = float(b.get("amount") or 0), float(t.get("amount") or 0)
    if want <= 0 or got <= 0:
        return None
    exact = abs(want - got) < 0.005
    near = abs(want - got) <= want * NEAR
    payee = bool(_tokens(b.get("vendor_name")) & _tokens(bank_picks.words(t)))
    if not (exact or (near and payee)):
        return None
    anchor = _d(b.get("due_date")) or _d(b.get("created_at")) or _today()
    return {"transaction_id": t["transaction_id"], "date": t.get("date"), "description": bank_picks.words(t),
            "amount": got, "exact": exact, "payee": payee, "days_off": abs(((_d(t.get("date")) or anchor) - anchor).days),
            "filed": t.get("business_subcategory") or t.get("business_category")}


def candidates(business_id: str, b: Dict[str, Any], rows: Optional[List[Dict[str, Any]]] = None,
               paying: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """The bank rows that could have paid this bill, the best first."""
    start, end = _window(b)
    rows = _money_out(business_id, start, end) if rows is None else [
        r for r in rows if start <= (_d(r.get("date")) or start) <= end]
    paying = _paying(business_id) if paying is None else paying
    out = []
    for t in rows:
        if paying.get(str(t["transaction_id"])) not in (None, str(b["id"])):
            continue
        s = score(b, t)
        if s:
            out.append(s)
    return sorted(out, key=lambda s: (not s["exact"], not s["payee"], s["days_off"]))


def clear_one(cands: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The one candidate plain enough to match without asking."""
    exact = [c for c in cands if c["exact"]]
    if len(exact) == 1:
        return exact[0]
    named = [c for c in exact if c["payee"]]
    return named[0] if len(named) == 1 else None


# ─── The match ───────────────────────────────────────────────────────

def match(business_id: str, bill_id: str, transaction_id: str) -> Dict[str, Any]:
    """{ok, bill, row, changes} or {ok: False, said}. Guarded: the bill must be
    owed (or paid by hand, never from the bank yet) and the row money out in
    the books, not paying another bill."""
    b = bill(business_id, bill_id)
    if not b:
        return {"ok": False, "said": "That bill isn't here any more."}
    if b.get("paid_transaction_id"):
        return {"ok": False, "said": f"The {b.get('vendor_name')} bill is already matched to a bank payment."}
    status = b.get("status") or "pending"
    if status not in OPEN and not (status == "paid" and (b.get("paid_via") or "manual") == "manual"):
        return {"ok": False, "said": f"The {b.get('vendor_name')} bill is {status}, so it has no payment to match."}
    rows = _get(f"/plaid_transactions?business_id=eq.{_q(business_id)}&transaction_id=eq.{_q(transaction_id)}"
                "&select=transaction_id,account_id,date,name,merchant_name,amount,pending,excluded_from_books,"
                "money_kind,business_category,business_subcategory&limit=1")
    t = rows[0] if rows else None
    import bank_picks
    if not t or str(t.get("account_id")) not in set(bank_picks.accounts(business_id, _get)):
        return {"ok": False, "said": "That bank payment isn't in your books."}
    if float(t.get("amount") or 0) <= 0 or t.get("pending") or t.get("excluded_from_books") or t.get("money_kind"):
        return {"ok": False, "said": "Only money out that's in your books (not a transfer, the owner's money or a "
                                     "gift deposit) can pay a bill."}
    if _paying(business_id).get(str(transaction_id)):
        return {"ok": False, "said": "That bank payment already paid another bill."}
    stamp = datetime.now(timezone.utc).isoformat()
    before = {k: b.get(k) for k in ("status", "paid_at", "paid_amount", "paid_via", "paid_transaction_id")}
    after = {"status": "paid", "paid_at": f"{t['date']}T12:00:00+00:00", "paid_amount": float(t["amount"]),
             "paid_via": "bank", "paid_transaction_id": str(transaction_id)}
    res = sb_clients.sb_patch_as_service(
        f"/bills?id=eq.{_q(bill_id)}&business_id=eq.{_q(business_id)}&paid_transaction_id=is.null"
        f"&status=eq.{_q(status)}", {**after, "updated_at": stamp})
    if res is None:
        raise Unavailable("bills")
    if isinstance(res, list) and not res:
        return {"ok": False, "said": f"The {b.get('vendor_name')} bill changed a moment ago; look again."}
    changes = [{"table": "bills", "id": str(bill_id), "before": before, "after": after}]
    # A row still waiting for an answer takes the bill's line and category.
    if not t.get("business_category"):
        filed = {"business_category": b.get("category") or "operating", "business_subcategory": b.get("subcategory")}
        r2 = sb_clients.sb_patch_as_service(
            f"/plaid_transactions?business_id=eq.{_q(business_id)}&transaction_id=eq.{_q(transaction_id)}"
            "&business_category=is.null", filed)
        if isinstance(r2, list) and r2:
            changes.append({"table": "plaid_transactions", "id": str(transaction_id),
                            "before": {"business_category": None, "business_subcategory": t.get("business_subcategory")},
                            "after": filed})
    return {"ok": True, "bill": b, "row": t, "changes": changes}


def unmatch(business_id: str, bill_id: str, before: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The bill owed again (or back as it was, with `before` from the match);
    the bank row keeps its filing."""
    b = bill(business_id, bill_id)
    if not b or not b.get("paid_transaction_id"):
        return {"ok": False, "said": "That bill isn't matched to a bank payment."}
    due = _d(b.get("due_date"))
    back = dict(before) if before else {
        "status": "overdue" if due and due < _today() else "pending",
        "paid_at": None, "paid_amount": None, "paid_via": None}
    back["paid_transaction_id"] = None
    res = sb_clients.sb_patch_as_service(
        f"/bills?id=eq.{_q(bill_id)}&business_id=eq.{_q(business_id)}"
        f"&paid_transaction_id=eq.{_q(b['paid_transaction_id'])}",
        {**back, "updated_at": datetime.now(timezone.utc).isoformat()})
    if res is None:
        raise Unavailable("bills")
    if isinstance(res, list) and not res:
        return {"ok": False, "said": "That bill changed a moment ago; look again."}
    return {"ok": True, "bill": b}


# ─── Routes (the Bills tab) ──────────────────────────────────────────

class MatchBody(BaseModel):
    business_id: str
    transaction_id: str = Field(max_length=200)


class UnmatchBody(BaseModel):
    business_id: str


def _gate(business_id: str, user: Any) -> None:
    import bills_router
    bills_router._owner(business_id, user)
    if not switched_on(business_id):
        raise HTTPException(403, "Matching bills to the bank isn't switched on for this business yet.")


@router.get("/{bill_id}/bank-matches")
def get_matches(bill_id: str, biz: str = Query(...), user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _gate(biz, user)
    try:
        b = bill(biz, bill_id)
        if not b:
            raise HTTPException(404, "That bill isn't here any more.")
        cands = candidates(biz, b)
    except Unavailable:
        raise HTTPException(503, "The bank payments can't be read just now.")
    clear = clear_one(cands)
    return {"ok": True, "candidates": cands[:10], "clear": clear["transaction_id"] if clear else None}


@router.post("/{bill_id}/bank-match")
def post_match(bill_id: str, body: MatchBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _gate(body.business_id, user)
    try:
        got = match(body.business_id, bill_id, body.transaction_id)
    except Unavailable:
        raise HTTPException(503, "The match didn't save. Try again.")
    if not got["ok"]:
        raise HTTPException(409, got["said"])
    return {"ok": True, "said": f"The {got['bill'].get('vendor_name')} bill is paid by the {_money(got['row']['amount'])} "
                                f"bank payment on {got['row']['date']}. It counts once in your books."}


@router.post("/{bill_id}/bank-unmatch")
def post_unmatch(bill_id: str, body: UnmatchBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _gate(body.business_id, user)
    try:
        got = unmatch(body.business_id, bill_id)
    except Unavailable:
        raise HTTPException(503, "That didn't save. Try again.")
    if not got["ok"]:
        raise HTTPException(409, got["said"])
    return {"ok": True, "said": f"The {got['bill'].get('vendor_name')} bill is owed again; the bank payment keeps "
                                "its filing."}


# ─── Chief ───────────────────────────────────────────────────────────

def _chief_gate(business_id: str) -> Optional[str]:
    if not switched_on(business_id):
        return "Matching bills to the bank isn't switched on for this business yet."
    from chief_of_staff import _TURN_USER_ID
    uid = _TURN_USER_ID.get()
    if not uid:
        return "Bills are matched only for a signed-in owner."
    import bills_router
    try:
        bills_router._owner(business_id, SimpleNamespace(id=uid))
    except HTTPException:
        return "Only the owner matches bills to the bank, the same as on the Bills tab."
    return None


def _fail(atype: str, msg: str) -> Dict[str, Any]:
    return {"type": atype, "result": f"Failed: {msg}", "label": msg[:80], "failed": True, "nav": NAV}


def suggestions(business_id: str, owed: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """bill id -> its clear bank payment, for the bills lookup. One read."""
    if not owed:
        return {}
    wins = [_window(b) for b in owed]
    rows = _money_out(business_id, min(w[0] for w in wins), max(w[1] for w in wins))
    paying = _paying(business_id)
    out = {}
    for b in owed:
        c = clear_one(candidates(business_id, b, rows, paying))
        if c:
            out[str(b["id"])] = c
    return out


def match_sync(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """Chief: "items": [{bill_id, transaction_id}] the owner confirmed, or
    "clear": true for every owed bill with one plain bank payment."""
    atype = "match_bill_payment"
    refused = _chief_gate(business_id)
    if refused:
        return _fail(atype, refused)
    try:
        pairs: List[Tuple[str, str]] = []
        if action.get("clear") is True:
            owed = _get(f"/bills?business_id=eq.{_q(business_id)}&status=in.({','.join(OPEN)})"
                        "&paid_transaction_id=is.null&select=id,vendor_name,amount,due_date,created_at&limit=500")
            pairs = [(bid, c["transaction_id"]) for bid, c in suggestions(business_id, owed).items()]
            # One bank row can only pay one bill: a row two bills both want is asked about, not taken.
            seen: Dict[str, int] = {}
            for _, tid in pairs:
                seen[tid] = seen.get(tid, 0) + 1
            pairs = [p for p in pairs if seen[p[1]] == 1]
        else:
            for it in action.get("items") or []:
                if isinstance(it, dict) and it.get("bill_id") and it.get("transaction_id"):
                    pairs.append((str(it["bill_id"]), str(it["transaction_id"])))
        if not pairs:
            return {"type": atype, "label": "Nothing to match", "nav": NAV,
                    "result": "No bill has one plain bank payment to match; nothing changed."}
        done, problems, changes = [], [], []
        for bid, tid in pairs[:50]:
            got = match(business_id, bid, tid)
            if got["ok"]:
                done.append({"bill_id": bid, "vendor": got["bill"].get("vendor_name"), "amount": got["row"]["amount"],
                             "date": got["row"]["date"], "before": got["changes"][0]["before"]})
                changes += got["changes"]
            else:
                problems.append(got["said"])
    except Unavailable:
        return _fail(atype, "the bills or the bank couldn't be read just now; nothing more changed")
    if not done:
        return _fail(atype, "; ".join(problems[:5]) or "nothing matched")
    text = (f"Matched {len(done)} bill(s) to the bank payments that paid them: "
            + "; ".join(f"{d['vendor']} {_money(d['amount'])} on {d['date']}" for d in done[:10])
            + ". Each counts once in the books now.")
    if problems:
        text += " Not matched: " + "; ".join(problems[:5]) + "."
    return {"type": atype, "label": f"🧾 {len(done)} bill(s) matched", "result": text + " One undo takes them back.",
            "batch_id": uuid.uuid4().hex, "matched": done, "changes": changes, "nav": NAV}


def unmatch_sync(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "unmatch_bill_payment"
    refused = _chief_gate(business_id)
    if refused:
        return _fail(atype, refused)
    items = [m for m in action.get("matched") or [] if isinstance(m, dict) and m.get("bill_id")] or \
            [{"bill_id": str(b)} for b in action.get("bill_ids") or []]
    if not items:
        return _fail(atype, "say which bill (bill_ids), or undo a match right after making it")
    back, problems = [], []
    try:
        for m in items[:50]:
            got = unmatch(business_id, m["bill_id"], m.get("before"))
            (back if got["ok"] else problems).append(got.get("bill", {}).get("vendor_name") if got["ok"] else got["said"])
    except Unavailable:
        return _fail(atype, "the bills couldn't be saved just now; ask again to finish")
    if not back:
        return _fail(atype, "; ".join(problems[:5]))
    text = f"Took back {len(back)} match(es): " + ", ".join(str(v) for v in back[:10]) + " are as they were before."
    if problems:
        text += " Not taken back: " + "; ".join(problems[:5]) + "."
    return {"type": atype, "label": f"↩ {len(back)} bill(s)", "result": text, "nav": NAV}


async def handle_match_bill_payment(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(match_sync, str(biz["id"]), action or {})


async def handle_unmatch_bill_payment(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(unmatch_sync, str(biz["id"]), action or {})
