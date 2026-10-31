"""
funds.py — funds for the year: the money in and out of the bank, placed
where it belongs.

Kevin, 2026-10-31: "if we created a fund for the year. we can place all what
was paid out or sent out aligned with that. wether it is housing pay etc...",
then "build that", wanting it "exactly based on transaction".

    a FUND ........ one year's fund: a name ("Pastoral staff", "Building",
                    "Youth"), the budget set for it (optional) and notes
    PLACED ........ a bank transaction on a fund: all of it, or a part (the
                    housing part of a paycheck). Money out or in is the bank
                    row's own sign, kept with it. What all funds hold of one
                    row never adds up past the row (checked, then written:
                    best-effort against two placements at the same instant;
                    only the owner places), and a row is on a fund once
    the FIGURES ... paid out, money in, what's left of the budget (budget less
                    paid out; over it, by how much), the balance (in less
                    out). The server adds up; the screen and Chief quote it
    the BANK ...... the accounts in the books, read the way the housing
                    allowance reads them (bank_picks): cleared rows, paged,
                    never a part passed off as the whole. Picks are
                    candidates; the owner says which belong
    HOUSING ....... a payment tied to a minister's housing allowance says so
                    in the finder, to the owner alone (the allowance is the
                    owner's), and the owner can pick them all at once

Who may: the Transactions screen's readers read (plaid_router._require_reader:
the owner, an accountant, a team seat; a church's finance gate and Giving
wall); the owner alone changes (plaid_router._require_owner). The same for
Chief, as the person talking.

Switched by FUNDS: off | owner | on, owner when unset (the platform owner's
businesses, until a Thursday flip). Tables:
supabase/APPLY-2026-10-31-funds-for-the-year.sql; before it, the routes
answer 503 and Chief says the funds aren't set up.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import os
import re
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

import bank_picks
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("funds")

router = APIRouter(prefix="/year-funds", tags=["year-funds"])

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_TX = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
_FUND_SELECT = "id,business_id,year,name,budget,notes,archived_at,created_at,updated_at"
_ITEM_SELECT = "id,fund_id,transaction_id,amount,direction,entry_date,note,created_at"
PLACE_MAX = 60
FIND_ROWS = 400
SHOW_ROWS = 25
DIRECTIONS = ("out", "in")
# Where Chief's receipts point: Bookkeeping's Funds tab. An app without the
# tab ignores bkTab and opens Bookkeeping.
NAV = {"tab": "operate", "sub": "bookkeeping", "bkTab": "funds"}


class Unavailable(Exception):
    """A read or write failed: never shown as nothing."""


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("FUNDS") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def switched_on(business_id: Any) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        import member_asks
        return member_asks.platform_church(business_id)
    return False


# ─── Reading and the gates ────────────────────────────────────────────

_q, _in, _num = bank_picks.q, bank_picks.in_, bank_picks.num


def _get(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if rows is None:
        raise Unavailable(path.split("?")[0])
    return rows


def _all(path: str) -> List[Dict[str, Any]]:
    """A read that can pass 1,000 rows, paged; past the cap, unread."""
    try:
        return bank_picks.read_all(path, _get)
    except bank_picks.TooMany as e:
        raise Unavailable(str(e))


def _gate(business_id: str, user: Any, *, write: bool) -> Dict[str, Any]:
    """The Transactions screen's own gates; 404 switched off."""
    if not business_id or not _UUID.match(str(business_id)):
        raise HTTPException(400, "business_id must be a uuid")
    if not switched_on(business_id):
        raise HTTPException(404, "Not Found")
    import plaid_router
    return (plaid_router._require_owner if write else plaid_router._require_reader)(business_id, user)


def is_owner(biz_row: Dict[str, Any], user_id: Any) -> bool:
    return bool(user_id) and str(biz_row.get("owner_id")) == str(user_id)


def list_funds(business_id: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
    path = (f"/business_funds?business_id=eq.{_q(business_id)}&archived_at=is.null"
            f"&select={_FUND_SELECT}&order=year.desc,name.asc&limit=500")
    if year:
        path += f"&year=eq.{int(year)}"
    return _get(path)


def get_fund(business_id: str, fund_id: str) -> Dict[str, Any]:
    if not _UUID.match(str(fund_id)):
        raise HTTPException(404, "fund not found")
    rows = _get(f"/business_funds?id=eq.{_q(fund_id)}&business_id=eq.{_q(business_id)}"
                f"&archived_at=is.null&select={_FUND_SELECT}&limit=1")
    if not rows:
        raise HTTPException(404, "fund not found")
    return rows[0]


def items_for(business_id: str, fund_ids: List[str]) -> List[Dict[str, Any]]:
    if not fund_ids:
        return []
    return _all(f"/business_fund_items?business_id=eq.{_q(business_id)}&fund_id={_in(fund_ids)}"
                f"&select={_ITEM_SELECT}&order=entry_date.asc,created_at.asc,id.asc")


# ─── The figures (pure) ───────────────────────────────────────────────

def figures(fund: Dict[str, Any], items: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = round(sum(_num(i.get("amount")) for i in items if i.get("direction") == "out"), 2)
    came = round(sum(_num(i.get("amount")) for i in items if i.get("direction") == "in"), 2)
    raw = fund.get("budget")
    budget = None if raw in (None, "") else _num(raw)
    return {
        "year": int(fund.get("year") or 0), "budget": budget, "paid_out": out, "money_in": came,
        "left": None if budget is None else round(max(0.0, budget - out), 2),
        "over": None if budget is None else round(max(0.0, out - budget), 2),
        "balance": round(came - out, 2),
        "count_out": sum(1 for i in items if i.get("direction") == "out"),
        "count_in": sum(1 for i in items if i.get("direction") == "in"),
    }


def _money(n: Optional[float]) -> str:
    return "not set" if n is None else f"${n:,.2f}"


def describe(fund: Dict[str, Any], f: Dict[str, Any]) -> str:
    s = f"{fund['name']}, {f['year']}: paid out {_money(f['paid_out'])} ({f['count_out']} payment(s))"
    if f["money_in"]:
        s += f", money in {_money(f['money_in'])} ({f['count_in']}), balance {_money(f['balance'])}"
    if f["budget"] is None:
        s += "; no budget set."
    elif f["over"]:
        s += f"; budget {_money(f['budget'])}, over it by {_money(f['over'])}."
    else:
        s += f"; budget {_money(f['budget'])}, {_money(f['left'])} left."
    return s


# ─── Funds: create, change, remove ────────────────────────────────────

def _clean(body: Dict[str, Any], *, partial: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if "name" in body or not partial:
        name = " ".join(str(body.get("name") or "").split())
        if not 1 <= len(name) <= 80:
            raise HTTPException(400, "Give the fund a name (up to 80 characters).")
        out["name"] = name
    if "year" in body or not partial:
        try:
            y = int(body.get("year") or date.today().year)
        except (TypeError, ValueError):
            raise HTTPException(400, "year must be a year")
        if not 2000 <= y <= 2200:
            raise HTTPException(400, "year must be a year")
        out["year"] = y
    if "budget" in body:
        v = body.get("budget")
        if v in (None, ""):
            out["budget"] = None
        else:
            try:
                n = round(float(v), 2)
            except (TypeError, ValueError):
                raise HTTPException(400, "The budget must be an amount.")
            if n < 0 or n > 1_000_000_000:
                raise HTTPException(400, "The budget can't be negative.")
            out["budget"] = n
    if "notes" in body:
        out["notes"] = str(body.get("notes") or "")[:2000]
    return out


def create_fund(business_id: str, user_id: Optional[str], body: Dict[str, Any]) -> Dict[str, Any]:
    row = _clean(body, partial=False)
    if any(f["name"].lower() == row["name"].lower() for f in list_funds(business_id, row["year"])):
        raise HTTPException(409, f"There's already a {row['year']} fund called {row['name']}.")
    now = datetime.now(timezone.utc).isoformat()
    res = sb_clients.sb_post_as_service("/business_funds", {
        **row, "business_id": business_id, "created_by": user_id, "created_at": now, "updated_at": now})
    if not res:
        raise HTTPException(503, "The fund didn't save. Try again.")
    return res[0] if isinstance(res, list) else res


def update_fund(business_id: str, fund_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    current = get_fund(business_id, fund_id)
    patch = _clean(body, partial=True)
    patch.pop("year", None)          # a fund stays in its year
    if not patch:
        return current
    if "name" in patch and patch["name"].lower() != current["name"].lower() and any(
            f["name"].lower() == patch["name"].lower() for f in list_funds(business_id, int(current["year"]))):
        raise HTTPException(409, f"There's already a {current['year']} fund called {patch['name']}.")
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = sb_clients.sb_patch_as_service(
        f"/business_funds?id=eq.{_q(fund_id)}&business_id=eq.{_q(business_id)}", patch)
    if not res:
        raise HTTPException(503, "The change didn't save. Try again.")
    return res[0] if isinstance(res, list) else {**current, **patch}


def archive_fund(business_id: str, fund_id: str) -> None:
    """Removed from the year; its placements go with it (the bank rows are
    untouched, and free to place again). Archived first: placements left
    behind by a failed delete belong to no live fund, so they hold nothing."""
    get_fund(business_id, fund_id)
    res = sb_clients.sb_patch_as_service(
        f"/business_funds?id=eq.{_q(fund_id)}&business_id=eq.{_q(business_id)}",
        {"archived_at": datetime.now(timezone.utc).isoformat()})
    if not res:
        raise HTTPException(503, "That didn't remove. Try again.")
    if not sb_clients.sb_delete_as_service(
            f"/business_fund_items?business_id=eq.{_q(business_id)}&fund_id=eq.{_q(fund_id)}"):
        logger.warning("funds: archived %s but its placements stay (they hold nothing)", fund_id)


# ─── The bank ─────────────────────────────────────────────────────────

def _used(business_id: str) -> Dict[str, Dict[str, Any]]:
    """Per bank row: how much the live funds hold, and which. A removed
    fund's placements are deleted with it; any left behind hold nothing.
    Checked here, then written: two placements at the very same moment could
    both pass, so it is best-effort against that (only the owner places)."""
    live = {str(f["id"]) for f in _get(f"/business_funds?business_id=eq.{_q(business_id)}&archived_at=is.null"
                                       "&select=id&limit=1000")}
    out: Dict[str, Dict[str, Any]] = {}
    for i in _all(f"/business_fund_items?business_id=eq.{_q(business_id)}"
                  "&select=fund_id,transaction_id,amount&order=id.asc"):
        if str(i.get("fund_id")) not in live:
            continue
        u = out.setdefault(str(i.get("transaction_id")), {"amount": 0.0, "funds": set()})
        u["amount"] = round(u["amount"] + _num(i.get("amount")), 2)
        u["funds"].add(str(i.get("fund_id")))
    return out


def _housing_rows(business_id: str) -> Optional[Dict[str, str]]:
    """Bank rows tied to a housing allowance, with whose: the owner's to see.
    None when they couldn't be read (never "none are housing"); a business
    with no housing records has none."""
    try:
        rows = _all(f"/minister_housing_entries?business_id=eq.{_q(business_id)}&source=eq.bank"
                    "&select=source_id,allowance_id&order=id.asc")
        if not rows:
            return {}
        names = {str(a["id"]): a.get("minister_name") or "the minister" for a in _get(
            f"/minister_housing_allowances?business_id=eq.{_q(business_id)}&select=id,minister_name&limit=1000")}
    except Unavailable:
        return None
    return {str(r["source_id"]): names.get(str(r.get("allowance_id")), "the minister") for r in rows
            if r.get("source_id")}


def find_bank(business_id: str, fund_id: str, *, words: Optional[List[str]] = None, amount: Any = None,
              direction: str = "out", housing_view: bool = False, housing_only: bool = False) -> Dict[str, Any]:
    fund = get_fund(business_id, fund_id)
    year = int(fund["year"])
    if direction not in DIRECTIONS:
        raise HTTPException(400, "direction must be out or in")
    want = None
    if amount not in (None, ""):
        try:
            want = round(abs(float(amount)), 2)
        except (TypeError, ValueError):
            raise HTTPException(400, "amount must be a number")
    accts = bank_picks.accounts(business_id, _get)
    used = _used(business_id)
    housing = _housing_rows(business_id) if housing_view else {}
    if housing is None:
        if housing_only:
            raise Unavailable("the housing allowance's payments couldn't be read")
        housing = {}       # no tags this time; the rows are all still here
    names = {str(f["id"]): f["name"] for f in list_funds(business_id, year)}
    words = [w for w in (" ".join(str(x).split()).lower() for x in (words or [])) if w][:6]
    rows: List[Dict[str, Any]] = []
    try:
        bank = bank_picks.year_rows(business_id, accts, year, _get, direction)
    except bank_picks.TooMany as e:
        raise Unavailable(str(e))
    for t in bank:
        tid = str(t.get("transaction_id") or "")
        a = abs(_num(t.get("amount")))
        u = used.get(tid) or {"amount": 0.0, "funds": set()}
        left = round(a - u["amount"], 2)
        if not tid or fund_id in u["funds"] or left <= 0:
            continue
        if housing_only and tid not in housing:
            continue
        if words and not any(w in f"{t.get('name') or ''} {t.get('merchant_name') or ''}".lower() for w in words):
            continue
        if want is not None and abs(a - want) > 0.005 and abs(left - want) > 0.005:
            continue
        row: Dict[str, Any] = {"transaction_id": tid, "date": str(t.get("date") or "")[:10],
                               "description": bank_picks.words(t), "amount": a}
        if left < a:
            row["left"] = left
            row["on_funds"] = sorted(names.get(f, "another fund") for f in u["funds"])
        if t.get("excluded_from_books"):
            row["excluded"] = True
        if tid in housing:
            row["housing"] = housing[tid]
        rows.append(row)
    newest = sorted(rows, key=lambda r: (r["date"], r["transaction_id"]), reverse=True)
    starts = bank_picks.history_starts(business_id, accts, _get)
    return {
        "fund": fund, "year": year, "direction": direction, "accounts": len(accts), "history_starts": starts,
        "history_late": bool(starts and starts > f"{year}-01-01"),
        "count": len(rows), "total": round(sum(r.get("left", r["amount"]) for r in rows), 2),
        "repeats": bank_picks.repeats(rows), "rows": newest[:FIND_ROWS], "capped": len(newest) > FIND_ROWS,
        "housing": [r["transaction_id"] for r in newest if r.get("housing")],
    }


def place(business_id: str, user_id: Optional[str], fund_id: str, items: Any) -> Dict[str, Any]:
    """Place bank rows on a fund: all of them or none. Each item is
    {transaction_id, amount?}; no amount is what's left of the row."""
    fund = get_fund(business_id, fund_id)
    year = int(fund["year"])
    if not isinstance(items, list) or not 1 <= len(items) <= PLACE_MAX:
        raise HTTPException(400, f"Pick from 1 to {PLACE_MAX} bank transactions.")
    want: Dict[str, Optional[float]] = {}
    for it in items:
        tid = str((it or {}).get("transaction_id") or "").strip() if isinstance(it, dict) else ""
        if not _TX.match(tid):
            raise HTTPException(400, "Each one needs the bank transaction it came from.")
        if tid in want:
            raise HTTPException(400, "The same bank transaction is in the list twice.")
        part = it.get("amount")
        if part in (None, ""):
            want[tid] = None
        else:
            try:
                n = round(float(part), 2)
            except (TypeError, ValueError):
                raise HTTPException(400, "The amount must be a number.")
            if n <= 0:
                raise HTTPException(400, "The amount must be more than zero.")
            want[tid] = n
    accts = set(bank_picks.accounts(business_id, _get))
    bank = {str(t.get("transaction_id")): t for t in _get(
        f"/plaid_transactions?business_id=eq.{_q(business_id)}&transaction_id={_in(want)}"
        f"&select={bank_picks.SELECT}&limit={len(want)}")}
    used = _used(business_id)
    plan = []
    for tid, part in want.items():
        t = bank.get(tid)
        if not t:
            raise HTTPException(400, "One of those isn't a bank transaction of this business.")
        if str(t.get("account_id") or "") not in accts:
            raise HTTPException(400, "One of those is from an account that isn't in the books.")
        signed = _num(t.get("amount"))
        a, when, desc = abs(signed), str(t.get("date") or "")[:10], bank_picks.words(t)
        on = when[:4]
        if t.get("pending"):
            raise HTTPException(400, f"The {when} transaction is still pending at the bank; place it once it clears.")
        if not a:
            raise HTTPException(400, f"The {when} transaction is for $0.00.")
        if on != str(year):
            raise HTTPException(400, f"The {when} transaction is outside {year}; it goes on that year's funds.")
        u = used.get(tid) or {"amount": 0.0, "funds": set()}
        if fund_id in u["funds"]:
            raise HTTPException(409, f"The {when} transaction of {_money(a)} is already on {fund['name']}.")
        left = round(a - u["amount"], 2)
        if left <= 0:
            raise HTTPException(409, f"All of the {when} transaction of {_money(a)} is already on other funds.")
        part = left if part is None else part
        if part > left + 0.005:
            raise HTTPException(400, f"The {when} transaction was {_money(a)}" + (
                f"; {_money(left)} of it is left to place." if left < a else "; the part can't be more than that."))
        plan.append({"tid": tid, "date": when, "description": desc, "bank_amount": a, "amount": part,
                     "direction": "out" if signed > 0 else "in"})
    rows = [{"business_id": business_id, "fund_id": fund_id, "transaction_id": p["tid"], "amount": p["amount"],
             "direction": p["direction"], "entry_date": p["date"], "placed_by": user_id,
             "note": (p["description"] + (f" (part of {_money(p['bank_amount'])})"
                                          if p["amount"] < p["bank_amount"] else ""))[:500]} for p in plan]
    res = sb_clients.sb_post_as_service("/business_fund_items", rows)
    if not res or not isinstance(res, list) or len(res) != len(rows):
        raise HTTPException(503, "Those didn't save. Nothing was changed; try again.")
    by_tid = {str(r.get("transaction_id")): r for r in res}
    placed = [{"item_id": by_tid.get(p["tid"], {}).get("id"), "transaction_id": p["tid"], "date": p["date"],
               "description": p["description"], "amount": p["amount"], "bank_amount": p["bank_amount"],
               "direction": p["direction"]} for p in plan]
    return {"fund": fund, "placed": placed, "created_ids": [r["id"] for r in res],
            "total_out": round(sum(p["amount"] for p in plan if p["direction"] == "out"), 2),
            "total_in": round(sum(p["amount"] for p in plan if p["direction"] == "in"), 2)}


def unplace(business_id: str, item_ids: Any) -> Dict[str, Any]:
    ids = [str(i) for i in (item_ids or []) if _UUID.match(str(i))]
    if not ids:
        raise HTTPException(400, "Say which to take off.")
    if len(ids) > PLACE_MAX * 2:
        raise HTTPException(400, "That's more than one batch.")
    rows = _get(f"/business_fund_items?business_id=eq.{_q(business_id)}&id={_in(ids)}&select=id&limit=500")
    if rows and not sb_clients.sb_delete_as_service(
            f"/business_fund_items?business_id=eq.{_q(business_id)}&id={_in([r['id'] for r in rows])}"):
        raise HTTPException(503, "That didn't take off. Try again.")
    return {"removed": len(rows)}


def _with_bank(business_id: str, items: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], bool]:
    """Each placed row with its bank row; a failed read leaves them bare and
    says so (the figures never hang on it)."""
    ids = sorted({str(i["transaction_id"]) for i in items if i.get("transaction_id")})
    rows: Dict[str, Dict[str, Any]] = {}
    try:
        for n in range(0, len(ids), 100):
            chunk = ids[n:n + 100]
            for t in _get(f"/plaid_transactions?business_id=eq.{_q(business_id)}&transaction_id={_in(chunk)}"
                          f"&select=transaction_id,date,name,merchant_name,amount&limit={len(chunk)}"):
                rows[str(t.get("transaction_id"))] = t
    except Unavailable:
        return items, False
    out = []
    for i in items:
        t = rows.get(str(i.get("transaction_id")))
        out.append({**i, "bank": ({"date": str(t.get("date") or "")[:10], "description": bank_picks.words(t),
                                   "amount": abs(_num(t.get("amount")))} if t else {"missing": True})})
    return out, True


def _bank_state(business_id: str) -> Optional[Dict[str, Any]]:
    try:
        accts = bank_picks.accounts(business_id, _get)
        return {"accounts": len(accts), "history_starts": bank_picks.history_starts(business_id, accts, _get)}
    except Unavailable:
        return None


def summary(business_id: str, year: int) -> Dict[str, Any]:
    funds = list_funds(business_id, year)
    items = items_for(business_id, [f["id"] for f in funds])
    out = []
    for f in funds:
        mine = [i for i in items if str(i.get("fund_id")) == str(f["id"])]
        fig = figures(f, mine)
        out.append({**f, "figures": fig, "summary": describe(f, fig)})
    total_out = round(sum(x["figures"]["paid_out"] for x in out), 2)
    return {"ok": True, "year": year, "funds": out, "paid_out": total_out,
            "money_in": round(sum(x["figures"]["money_in"] for x in out), 2), "bank": _bank_state(business_id)}


def one(business_id: str, fund_id: str) -> Dict[str, Any]:
    fund = get_fund(business_id, fund_id)
    items, bank_ok = _with_bank(business_id, items_for(business_id, [fund_id]))
    fig = figures(fund, items)
    return {"ok": True, "fund": {**fund, "figures": fig, "summary": describe(fund, fig)},
            "items": sorted(items, key=lambda i: (str(i.get("entry_date")), str(i.get("created_at"))), reverse=True),
            "bank_read": bank_ok, "bank": _bank_state(business_id)}


def _cell(v: Any) -> Any:
    """A spreadsheet never runs a cell as a formula."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def report_csv(business_id: str, fund_id: str) -> Tuple[str, str]:
    fund = get_fund(business_id, fund_id)
    items, bank_ok = _with_bank(business_id, items_for(business_id, [fund_id]))
    fig = figures(fund, items)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([_cell(f"{fund['name']}: {fund['year']}")])
    w.writerow(["Date", "Out or in", "Amount", "Bank date", "Bank description", "Bank amount", "Note"])
    for i in sorted(items, key=lambda i: (str(i.get("entry_date")), str(i.get("created_at")))):
        b = i.get("bank") or {}
        w.writerow([str(i.get("entry_date") or "")[:10], "Out" if i.get("direction") == "out" else "In",
                    f"{_num(i.get('amount')):.2f}", b.get("date", ""),
                    _cell("(no longer in the bank feed)" if b.get("missing") else b.get("description", "")),
                    f"{b['amount']:.2f}" if "amount" in b else "", _cell(str(i.get("note") or ""))])
    w.writerow([])
    for label, n in ((f"Paid out ({fig['count_out']})", fig["paid_out"]), (f"Money in ({fig['count_in']})", fig["money_in"]),
                     ("Balance (in less out)", fig["balance"]), ("Budget", fig["budget"]),
                     ("Left of the budget", fig["left"]), ("Over the budget", fig["over"])):
        w.writerow(["", label, "" if n is None else f"{n:.2f}"])
    if not bank_ok:
        w.writerow(["", "The bank rows couldn't be read just now, so the bank columns are empty."])
    slug = re.sub(r"[^a-z0-9]+", "-", fund["name"].lower()).strip("-") or "fund"
    return buf.getvalue(), f"fund-{fund['year']}-{slug}.csv"


def _guard(fn, *args):
    try:
        return fn(*args)
    except Unavailable:
        raise HTTPException(503, "The funds can't be read just now. If this is new, its database tables may not "
                                 "be set up yet.")


# ─── Routes ───────────────────────────────────────────────────────────

class FundBody(BaseModel):
    business_id: str
    name: Optional[str] = Field(default=None, max_length=80)
    year: Optional[int] = None
    budget: Optional[float] = None
    notes: Optional[str] = Field(default=None, max_length=2000)


class PlaceBody(BaseModel):
    business_id: str
    items: List[Dict[str, Any]] = Field(default_factory=list, max_length=PLACE_MAX)


class UnplaceBody(BaseModel):
    business_id: str
    item_ids: List[str] = Field(default_factory=list, max_length=PLACE_MAX * 2)


def _given(body: BaseModel) -> Dict[str, Any]:
    return {k: v for k, v in body.model_dump(exclude_unset=True).items() if k != "business_id"}


@router.get("")
def get_funds(business_id: str = Query(...), year: Optional[int] = None,
              user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _gate(business_id, user, write=False)
    data = _guard(summary, business_id, int(year or date.today().year))
    return {**data, "can_change": is_owner(biz, user.id)}


@router.post("")
def post_fund(body: FundBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _gate(body.business_id, user, write=True)
    return {"ok": True, "fund": _guard(create_fund, body.business_id, str(user.id), _given(body))}


@router.get("/{fund_id}")
def get_one_fund(fund_id: str, business_id: str = Query(...),
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _gate(business_id, user, write=False)
    return {**_guard(one, business_id, fund_id), "can_change": is_owner(biz, user.id)}


@router.patch("/{fund_id}")
def patch_fund(fund_id: str, body: FundBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _gate(body.business_id, user, write=True)
    return {"ok": True, "fund": _guard(update_fund, body.business_id, fund_id, _given(body))}


@router.delete("/{fund_id}")
def delete_fund(fund_id: str, business_id: str = Query(...),
                user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _gate(business_id, user, write=True)
    _guard(archive_fund, business_id, fund_id)
    return {"ok": True}


@router.get("/{fund_id}/bank")
def get_fund_bank(fund_id: str, business_id: str = Query(...), q: Optional[str] = None,
                  amount: Optional[float] = None, direction: str = "out", housing: bool = False,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The year's bank transactions not on this fund yet. Only the owner
    places, so only the owner looks."""
    biz = _gate(business_id, user, write=True)
    data = _guard(lambda: find_bank(business_id, fund_id, words=(q or "").split(), amount=amount,
                                    direction=direction, housing_view=is_owner(biz, user.id),
                                    housing_only=housing))
    data.pop("fund", None)
    return {"ok": True, **data}


@router.post("/{fund_id}/bank")
def post_fund_bank(fund_id: str, body: PlaceBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _gate(body.business_id, user, write=True)
    done = _guard(place, body.business_id, str(user.id), fund_id, body.items)
    done.pop("fund", None)
    return {"ok": True, **done}


@router.post("/bank/detach")
def post_fund_unplace(body: UnplaceBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _gate(body.business_id, user, write=True)
    return {"ok": True, **_guard(unplace, body.business_id, body.item_ids)}


@router.get("/{fund_id}/report.csv")
def get_fund_report(fund_id: str, business_id: str = Query(...),
                    user: AuthedUser = Depends(require_user)) -> Response:
    _gate(business_id, user, write=False)
    text, name = _guard(report_csv, business_id, fund_id)
    return Response(content=text.encode("utf-8-sig"), media_type="text/csv; charset=utf-8", headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f'attachment; filename="{name}"'})


# ─── Chief ────────────────────────────────────────────────────────────

STATUS_TOOL = {
    "name": "fund_status",
    "description": (
        "This business's funds for a year (a fund is a name like 'Pastoral staff', 'Building' or 'Youth', "
        "with a budget, and the bank transactions placed on it): for each, paid out, money in, the "
        "balance, the budget and what's left of it. Use it for 'how much is left in Youth', 'what have we "
        "paid out of the building fund', 'what funds do we have'. Quote its figures; never add them up "
        "yourself."),
    "input_schema": {"type": "object", "properties": {
        "year": {"type": "integer", "description": "Optional. Default: this year."}}},
}
FIND_TOOL = {
    "name": "find_fund_payments",
    "description": (
        "Look through this business's bank transactions of the fund's year that aren't on that fund yet "
        "(money out unless direction is in): the server's count and total, the ones that repeat (same "
        "amount, same description), each one's transaction_id for place_fund_payments, and where the bank "
        "history starts. Optional words, an exact amount, or housing (only the payments tied to a "
        "minister's housing allowance; the owner's alone). Candidates, not proof: show them and place only "
        "what the owner confirms. Owner only."),
    "input_schema": {"type": "object", "properties": {
        "fund": {"type": "string", "description": "The fund's name."},
        "year": {"type": "integer", "description": "Optional. Default: this year."},
        "words": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "amount": {"type": "number"},
        "direction": {"type": "string", "enum": list(DIRECTIONS)},
        "housing": {"type": "boolean", "description": "Only payments tied to a housing allowance."}},
        "required": ["fund"]},
}


def _fail(atype: str, msg: str) -> Dict[str, Any]:
    return {"type": atype, "result": f"Failed: {msg}", "label": msg[:80], "failed": True, "nav": NAV}


def _chief_gate(biz: Dict[str, Any], atype: str, *, write: bool) -> Tuple[Optional[Dict[str, Any]], bool]:
    """(refusal, the person talking owns the business)."""
    from chief_of_staff import _TURN_USER_ID
    uid = _TURN_USER_ID.get()
    if not uid:
        return _fail(atype, "funds are read only for a signed-in person who can see the books"), False
    try:
        row = _gate(str(biz["id"]), SimpleNamespace(id=uid), write=write)
    except HTTPException as e:
        if e.status_code == 404:
            return _fail(atype, "funds aren't switched on for this business yet"), False
        detail = e.detail.get("message") if isinstance(e.detail, dict) else e.detail
        return _fail(atype, "only the owner changes the funds" if write and e.status_code == 403
                     else str(detail or "this login can't see the books")), False
    return None, is_owner(row, uid)


def _pick(business_id: str, action: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    year = action.get("year") or date.today().year
    try:
        year = int(year)
    except (TypeError, ValueError):
        return None, "year must be a year"
    rows = list_funds(business_id, year)
    if action.get("fund_id"):
        rows = [f for f in rows if f["id"] == action["fund_id"]]
    else:
        want = " ".join(str(action.get("fund") or "").split()).lower()
        if not want:
            if not rows:
                return None, f"there are no {year} funds yet"
            return None, "say which fund (" + ", ".join(f["name"] for f in rows) + ")"
        exact = [f for f in rows if f["name"].lower() == want]
        rows = exact or [f for f in rows if want in f["name"].lower()]
    if len(rows) == 1:
        return rows[0], ""
    if not rows:
        return None, f"there's no {year} fund called {action.get('fund')}"
    return None, "more than one fund matches: say which (" + ", ".join(f["name"] for f in rows) + ")"


def _status_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "fund_status"
    refused, _ = _chief_gate(biz, atype, write=False)
    if refused:
        return refused
    try:
        year = int(action.get("year") or date.today().year)
        data = summary(str(biz["id"]), year)
    except (Unavailable, ValueError, TypeError):
        return _fail(atype, "the funds couldn't be read just now (if this is new, its tables may not be set up "
                            "yet). This is not 'no funds'")
    if not data["funds"]:
        text = f"No funds are set up for {year}. The owner can add one under Bookkeeping, Funds, or ask me to."
    else:
        text = " ".join(f["summary"] for f in data["funds"])
        text += f" All {year} funds: paid out {_money(data['paid_out'])}, money in {_money(data['money_in'])}."
    return {"type": atype, "result": text, "label": "Funds",
            "funds": [{"id": f["id"], "name": f["name"], "figures": f["figures"]} for f in data["funds"]],
            "note_for_chief": "Quote these figures; don't work them out yourself.", "nav": NAV}


def _set_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    """Make a fund, or change one's budget, name or notes."""
    atype = "set_fund"
    refused, _ = _chief_gate(biz, atype, write=True)
    if refused:
        return refused
    from chief_of_staff import _TURN_USER_ID
    biz_id = str(biz["id"])
    body = {k: action[k] for k in ("name", "year", "budget", "notes") if k in action}
    body.setdefault("year", date.today().year)
    try:
        # "fund" names one to change (its new name, if any, is "name");
        # else a fund of that name this year is changed, else it's made.
        target = None
        if action.get("fund") or action.get("fund_id"):
            target, why = _pick(biz_id, {"fund": action.get("fund"), "fund_id": action.get("fund_id"),
                                         "year": body["year"]})
            if not target:
                return _fail(atype, why)
        elif body.get("name"):
            want = " ".join(str(body["name"]).split()).lower()
            target = next((f for f in list_funds(biz_id, int(body["year"])) if f["name"].lower() == want), None)
        if target:
            row, verb = update_fund(biz_id, target["id"], body), "Changed"
        else:
            row, verb = create_fund(biz_id, _TURN_USER_ID.get(), body), "Made"
    except HTTPException as e:
        return _fail(atype, str(e.detail))
    except (Unavailable, ValueError, TypeError):
        return _fail(atype, "the funds couldn't be read just now; nothing was saved")
    budget = row.get("budget")
    return {"type": atype, "fund_id": row.get("id"),
            "result": f"{verb} the {row.get('year')} fund {row.get('name')}"
                      + (f", budget {_money(_num(budget))}." if budget not in (None, "") else ", no budget set."),
            "label": f"{verb} the fund {row.get('name')}", "nav": NAV}


def _row_words(r: Dict[str, Any]) -> str:
    s = f"{r['date']} {_money(r.get('left', r['amount']))} \"{r['description']}\" id {r['transaction_id']}"
    if "left" in r:
        s += f" (what's left of {_money(r['amount'])}; the rest is on {', '.join(r.get('on_funds') or [])})"
    if r.get("housing"):
        s += f" (tied to {r['housing']}'s housing allowance)"
    if r.get("excluded"):
        s += " (excluded from the books)"
    return s


def _find_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "find_fund_payments"
    refused, owner = _chief_gate(biz, atype, write=True)
    if refused:
        return refused
    words = action.get("words")
    words = [words] if isinstance(words, str) else words if isinstance(words, list) else None
    direction = str(action.get("direction") or "out").lower()
    try:
        fund, why = _pick(str(biz["id"]), action)
        if not fund:
            return _fail(atype, why)
        data = find_bank(str(biz["id"]), fund["id"], words=words, amount=action.get("amount"),
                         direction=direction, housing_view=owner, housing_only=bool(action.get("housing")))
    except HTTPException as e:
        return _fail(atype, str(e.detail))
    except Unavailable:
        return _fail(atype, "the bank rows couldn't be read just now. This is not 'none found'")
    if not data["accounts"]:
        text = ("No bank account is connected to the books, so there are no transactions to place. The owner "
                "can connect one under Bookkeeping, Transactions.")
    else:
        way = "out of" if direction == "out" else "into"
        text = (f"{fund['name']} ({data['year']}): {data['count']} transaction(s) {way} the bank aren't on it yet, "
                f"{_money(data['total'])} in all.")
        if data["history_late"]:
            text += f" The bank history in the app starts {data['history_starts']}; earlier ones aren't here."
        if data["repeats"]:
            text += " Repeating: " + "; ".join(
                f"{_money(g['amount'])} × {g['count']} ({', '.join(g['dates'])}), \"{g['description']}\", "
                f"transaction_ids {', '.join(g['transaction_ids'])}" for g in data["repeats"][:8]) + "."
        if data["housing"] and not action.get("housing"):
            text += f" {len(data['housing'])} of them are tied to a housing allowance (ask with housing to list them)."
        shown = data["rows"][:SHOW_ROWS]
        if shown:
            text += f" Newest {len(shown)} of {data['count']}: " + "; ".join(_row_words(r) for r in shown) + "."
    return {"type": atype, "result": text, "label": f"Bank transactions for {fund['name']}",
            "fund_id": fund["id"], "count": data["count"], "total": data["total"],
            "note_for_chief": ("Candidates, not proof. Show them and ask which belong on the fund; place only what "
                               "the owner confirms (place_fund_payments). Quote the server's count and total."),
            "nav": NAV}


def _place_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "place_fund_payments"
    refused, _ = _chief_gate(biz, atype, write=True)
    if refused:
        return refused
    from chief_of_staff import _TURN_USER_ID
    items: List[Dict[str, Any]] = [{"transaction_id": p.get("transaction_id"), "amount": p.get("amount")}
                                   for p in action.get("parts") or [] if isinstance(p, dict)]
    ids = action.get("transaction_ids")
    for tid in ([ids] if isinstance(ids, str) else ids or []):
        items.append({"transaction_id": tid, "amount": action.get("amount_each")})
    if not items:
        return _fail(atype, "say which bank transactions (their transaction_ids from find_fund_payments)")
    try:
        fund, why = _pick(str(biz["id"]), action)
        if not fund:
            return _fail(atype, why)
        done = place(str(biz["id"]), _TURN_USER_ID.get(), fund["id"], items)
    except HTTPException as e:
        return _fail(atype, str(e.detail) + " Nothing was placed")
    except Unavailable:
        return _fail(atype, "the funds couldn't be read just now; nothing was placed")
    rows = done["placed"]
    text = (f"Placed {len(rows)} bank transaction(s) on {fund['name']} ({fund['year']}): "
            + "; ".join(f"{r['date']} {_money(r['amount'])} {'out' if r['direction'] == 'out' else 'in'}"
                        + (f" of {_money(r['bank_amount'])}" if r["amount"] < r["bank_amount"] else "")
                        for r in rows) + ".")
    try:
        fig = figures(fund, items_for(str(biz["id"]), [fund["id"]]))
        text += " " + describe(fund, fig)
    except Unavailable:
        text += " The fund's new totals couldn't be read just now; the Funds tab will show them."
    return {"type": atype, "result": text, "label": f"Placed {len(rows)} on {fund['name']}",
            "fund_id": fund["id"], "created_ids": done["created_ids"], "placed": rows, "nav": NAV}


def _unplace_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "unplace_fund_payments"
    refused, _ = _chief_gate(biz, atype, write=True)
    if refused:
        return refused
    try:
        done = unplace(str(biz["id"]), action.get("item_ids"))
    except HTTPException as e:
        return _fail(atype, str(e.detail))
    except Unavailable:
        return _fail(atype, "the funds couldn't be read just now; nothing changed")
    return {"type": atype, "result": (f"Took {done['removed']} bank transaction(s) off the fund."
                                      if done["removed"] else "Nothing to take off: those were already gone."),
            "label": "Took them off the fund", "nav": NAV}


async def handle_fund_status(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_status_sync, biz, action or {})


async def handle_set_fund(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_set_sync, biz, action or {})


async def handle_find_fund_payments(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_find_sync, biz, action or {})


async def handle_place_fund_payments(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_place_sync, biz, action or {})


async def handle_unplace_fund_payments(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_unplace_sync, biz, action or {})
