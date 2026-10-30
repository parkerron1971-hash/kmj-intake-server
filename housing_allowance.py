"""
housing_allowance.py — a minister's housing allowance, kept the way the IRS
looks at it.

Kevin, 2026-10-30: "I do have a housing allowance setup. so we need
structure for this setup in the system". On who sees it: the owner only. On
how it's paid: both ways, through the app's payroll or outside it.

THE RULES IT KEEPS (IRC §107; the minister's tax preparer has the last word,
and every summary says so):

    designated ... the church's board sets the amount IN ADVANCE, in writing.
                   The record keeps the amount, the day, and the Board
                   decision when it was recorded there (church_board)
    excludable ... the least of: the amount designated, the amount actually
                   paid as allowance, what the minister actually spent on
                   the home, and the home's fair rental value (furnished,
                   plus utilities). Whatever was paid above that is taxable
                   income
    reported ..... the allowance paid in the year is the W-2 Box 14 figure.
                   It is still income for self-employment (SECA) tax: a
                   minister pays Social Security and Medicare themselves

THE TABLES (supabase/APPLY-2026-10-30-housing-allowance.sql), server-only:

    minister_housing_allowances  one minister, one tax year
    minister_housing_entries     PAID (allowance to the minister) and SPENT
                                 (rent or mortgage, utilities, furnishings,
                                 repairs, insurance, property tax, other).
                                 Paid comes typed in, from a pay run, or from
                                 a bank row; each pay run or bank row once

Who may: the business owner alone, on the screen and through Chief. A
minister's housing costs are personal records; the board needs only the
amount, which its own decision already holds.

Switched by HOUSING_ALLOWANCE: off | owner | on, owner when unset (the
businesses the platform owner owns, until a Thursday flip). Before the
migration the routes answer 503 and Chief says the records aren't set up.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("housing_allowance")

router = APIRouter(prefix="/housing-allowance", tags=["housing-allowance"])

SPENT_CATEGORIES = ("rent_mortgage", "utilities", "furnishings", "repairs", "insurance",
                    "property_tax", "other")
CATEGORY_WORDS = {
    "allowance": "allowance paid", "rent_mortgage": "rent or mortgage", "utilities": "utilities",
    "furnishings": "furnishings", "repairs": "repairs and upkeep", "insurance": "insurance",
    "property_tax": "property tax", "other": "other housing costs",
}
SOURCES = ("manual", "pay_run", "bank")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_SOURCE_ID = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
_ALLOWANCE_SELECT = ("id,business_id,minister_name,contact_id,employee_id,tax_year,designated_amount,"
                     "designated_on,board_decision_id,fair_rental_value,notes,archived_at,created_at,updated_at")
_ENTRY_SELECT = "id,allowance_id,kind,entry_date,amount,category,note,source,source_id,created_at"
# Where Chief's receipts point. Bookkeeping until the app has its own
# Housing allowance screen (a solutionist-studio PR).
NAV = {"tab": "operate", "sub": "bookkeeping"}
CARE = ("Figures follow the IRS housing allowance rules (§107); confirm them with your tax "
        "preparer. The allowance is still counted for self-employment tax.")


class Unavailable(Exception):
    """A read or write failed: never shown as nothing."""


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("HOUSING_ALLOWANCE") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def switched_on(business_id: Any) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        import member_asks
        return member_asks.platform_church(business_id)
    return False


# ─── The figures (pure) ───────────────────────────────────────────────

def _num(v: Any) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def figures(allowance: Dict[str, Any], entries: List[Dict[str, Any]],
            today: Optional[date] = None) -> Dict[str, Any]:
    """Every number the screen, Chief and the year-end statement say."""
    today = today or date.today()
    designated = _num(allowance.get("designated_amount"))
    paid = round(sum(_num(e.get("amount")) for e in entries if e.get("kind") == "paid"), 2)
    spent_by = {c: 0.0 for c in SPENT_CATEGORIES}
    for e in entries:
        if e.get("kind") == "spent":
            c = e.get("category") if e.get("category") in spent_by else "other"
            spent_by[c] = round(spent_by[c] + _num(e.get("amount")), 2)
    spent = round(sum(spent_by.values()), 2)
    frv_raw = allowance.get("fair_rental_value")
    frv = None if frv_raw in (None, "") else _num(frv_raw)

    limits = [("designated", designated), ("paid", paid), ("spent", spent)]
    if frv is not None:
        limits.append(("fair_rental_value", frv))
    limited_by, excludable = min(limits, key=lambda kv: kv[1])
    missing = []
    if frv is None:
        missing.append("fair_rental_value")
    if not allowance.get("board_decision_id"):
        missing.append("board_decision")
    year = int(allowance.get("tax_year") or today.year)
    return {
        "tax_year": year,
        "designated": designated,
        "paid": paid,
        "spent": spent,
        "spent_by_category": {k: v for k, v in spent_by.items() if v},
        "fair_rental_value": frv,
        "excludable": round(excludable, 2),
        "limited_by": limited_by,
        "taxable_excess": round(max(0.0, paid - excludable), 2),
        "left_to_pay": round(max(0.0, designated - paid), 2),
        "box_14": paid,
        "final": today > date(year, 12, 31),
        "missing": missing,
    }


_LIMIT_WORDS = {"designated": "the amount the board designated", "paid": "the allowance actually paid",
                "spent": "what was actually spent on the home",
                "fair_rental_value": "the home's fair rental value"}


def _money(n: Optional[float]) -> str:
    return "not set" if n is None else f"${n:,.2f}"


def describe(allowance: Dict[str, Any], f: Dict[str, Any]) -> str:
    """One paragraph, in plain words, with every number."""
    who = allowance.get("minister_name") or "The minister"
    s = (f"{who}, {f['tax_year']}: designated {_money(f['designated'])} "
         f"(board, {str(allowance.get('designated_on') or '')[:10]}); paid {_money(f['paid'])}; "
         f"housing costs logged {_money(f['spent'])}; fair rental value {_money(f['fair_rental_value'])}. ")
    word = "can be" if f["final"] else "so far can be"
    s += (f"Excludable {word} {_money(f['excludable'])}, limited by {_LIMIT_WORDS[f['limited_by']]}. ")
    if f["taxable_excess"]:
        s += f"{_money(f['taxable_excess'])} of what was paid is taxable income. "
    if f["left_to_pay"] and not f["final"]:
        s += f"{_money(f['left_to_pay'])} of the designation is still to be paid this year. "
    s += f"W-2 Box 14: {_money(f['box_14'])}."
    if "fair_rental_value" in f["missing"]:
        s += " The fair rental value isn't set, so the last limit can't be checked yet."
    if "board_decision" in f["missing"]:
        s += " It isn't linked to a Board decision yet."
    return s


def reminders(allowances: List[Dict[str, Any]], today: Optional[date] = None) -> List[str]:
    """From November: next year's allowance must be designated before Jan 1."""
    today = today or date.today()
    if today.month < 11:
        return []
    have_next = {a["minister_name"].lower() for a in allowances if int(a["tax_year"]) == today.year + 1}
    out = []
    for a in allowances:
        if int(a["tax_year"]) == today.year and a["minister_name"].lower() not in have_next:
            out.append(f"{a['minister_name']}'s {today.year + 1} housing allowance isn't designated yet. "
                       f"The board needs to set it before January 1.")
    return out


# ─── Reads and writes ─────────────────────────────────────────────────

def _q(v: Any) -> str:
    from urllib.parse import quote
    return quote(str(v), safe="")


def _get(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if rows is None:
        raise Unavailable(path.split("?")[0])
    return rows


def _owner_of(business_id: str) -> Optional[str]:
    rows = _get(f"/businesses?id=eq.{_q(business_id)}&select=owner_id&limit=1")
    return str(rows[0].get("owner_id")) if rows and rows[0].get("owner_id") else None


def require_owner(business_id: str, user_id: Optional[str]) -> None:
    """403 unless this person owns the business; 404 when switched off or
    the business doesn't exist."""
    if not business_id or not _UUID.match(str(business_id)):
        raise HTTPException(400, "business_id must be a uuid")
    if not switched_on(business_id):
        raise HTTPException(404, "Not Found")
    try:
        owner = _owner_of(business_id)
    except Unavailable:
        raise HTTPException(503, "The housing allowance records can't be read just now.")
    if not owner:
        raise HTTPException(404, "business not found")
    if not user_id or str(user_id) != owner:
        raise HTTPException(403, "The housing allowance is the owner's alone.")


def _belongs(table: str, business_id: str, row_id: Optional[str], col: str = "id") -> bool:
    if not row_id:
        return True
    if not _UUID.match(str(row_id)) and table != "plaid_transactions":
        return False
    if table == "plaid_transactions" and not _SOURCE_ID.match(str(row_id)):
        return False
    rows = _get(f"/{table}?{col}=eq.{_q(row_id)}&business_id=eq.{_q(business_id)}&select={col}&limit=1")
    return bool(rows)


def list_allowances(business_id: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
    path = (f"/minister_housing_allowances?business_id=eq.{_q(business_id)}&archived_at=is.null"
            f"&select={_ALLOWANCE_SELECT}&order=tax_year.desc,minister_name.asc&limit=200")
    if year:
        path += f"&tax_year=eq.{int(year)}"
    return _get(path)


def entries_for(business_id: str, allowance_id: str) -> List[Dict[str, Any]]:
    return _get(f"/minister_housing_entries?business_id=eq.{_q(business_id)}"
                f"&allowance_id=eq.{_q(allowance_id)}&select={_ENTRY_SELECT}"
                f"&order=entry_date.asc,created_at.asc&limit=5000")


def get_allowance(business_id: str, allowance_id: str) -> Dict[str, Any]:
    if not _UUID.match(str(allowance_id)):
        raise HTTPException(404, "housing allowance not found")
    rows = _get(f"/minister_housing_allowances?id=eq.{_q(allowance_id)}&business_id=eq.{_q(business_id)}"
                f"&archived_at=is.null&select={_ALLOWANCE_SELECT}&limit=1")
    if not rows:
        raise HTTPException(404, "housing allowance not found")
    return rows[0]


def _check_links(business_id: str, body: Dict[str, Any]) -> None:
    for key, table in (("board_decision_id", "church_board_decisions"), ("contact_id", "contacts"),
                       ("employee_id", "employees")):
        if body.get(key) and not _belongs(table, business_id, body[key]):
            raise HTTPException(400, f"{key} isn't one of this business's records")


def _clean_allowance(body: Dict[str, Any], *, partial: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if "minister_name" in body or not partial:
        name = " ".join(str(body.get("minister_name") or "").split())
        if not 1 <= len(name) <= 120:
            raise HTTPException(400, "minister_name is required (up to 120 characters)")
        out["minister_name"] = name
    if "tax_year" in body or not partial:
        try:
            y = int(body.get("tax_year"))
        except (TypeError, ValueError):
            raise HTTPException(400, "tax_year must be a year")
        if not 2000 <= y <= 2200:
            raise HTTPException(400, "tax_year must be a year")
        out["tax_year"] = y
    if "designated_amount" in body or not partial:
        amt = _amount(body.get("designated_amount"), allow_zero=True, what="designated_amount")
        out["designated_amount"] = amt
    if "designated_on" in body or not partial:
        out["designated_on"] = _day(body.get("designated_on"), "designated_on").isoformat()
    if "fair_rental_value" in body:
        v = body.get("fair_rental_value")
        out["fair_rental_value"] = None if v in (None, "") else _amount(v, allow_zero=True,
                                                                        what="fair_rental_value")
    for key in ("board_decision_id", "contact_id", "employee_id"):
        if key in body:
            v = body.get(key) or None
            if v and not _UUID.match(str(v)):
                raise HTTPException(400, f"{key} must be a uuid")
            out[key] = v
    if "notes" in body:
        out["notes"] = str(body.get("notes") or "")[:2000]
    return out


def _amount(v: Any, *, allow_zero: bool = False, what: str = "amount") -> float:
    try:
        n = round(float(v), 2)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{what} must be a number")
    if n < 0 or (n == 0 and not allow_zero) or n > 10_000_000:
        raise HTTPException(400, f"{what} must be more than zero" if not allow_zero
                            else f"{what} can't be negative")
    return n


def _day(v: Any, what: str) -> date:
    try:
        return date.fromisoformat(str(v or "").strip()[:10])
    except ValueError:
        raise HTTPException(400, f"{what} must be a date (YYYY-MM-DD)")


def create_allowance(business_id: str, user_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    row = _clean_allowance(body, partial=False)
    _check_links(business_id, row)
    same = [a for a in list_allowances(business_id, row["tax_year"])
            if a["minister_name"].lower() == row["minister_name"].lower()]
    if same:
        raise HTTPException(409, f"{row['minister_name']} already has a {row['tax_year']} housing "
                                 "allowance. Change that one instead.")
    now = datetime.now(timezone.utc).isoformat()
    res = sb_clients.sb_post_as_service("/minister_housing_allowances", {
        **row, "business_id": business_id, "created_by": user_id, "created_at": now, "updated_at": now})
    if not res:
        raise HTTPException(503, "The housing allowance didn't save. Try again.")
    return res[0] if isinstance(res, list) else res


def update_allowance(business_id: str, allowance_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    current = get_allowance(business_id, allowance_id)
    patch = _clean_allowance(body, partial=True)
    if not patch:
        return current
    _check_links(business_id, patch)
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = sb_clients.sb_patch_as_service(
        f"/minister_housing_allowances?id=eq.{_q(allowance_id)}&business_id=eq.{_q(business_id)}", patch)
    if not res:
        raise HTTPException(503, "The change didn't save. Try again.")
    return res[0] if isinstance(res, list) else {**current, **patch}


def archive_allowance(business_id: str, allowance_id: str) -> None:
    get_allowance(business_id, allowance_id)
    res = sb_clients.sb_patch_as_service(
        f"/minister_housing_allowances?id=eq.{_q(allowance_id)}&business_id=eq.{_q(business_id)}",
        {"archived_at": datetime.now(timezone.utc).isoformat()})
    if not res:
        raise HTTPException(503, "That didn't save. Try again.")


def add_entry(business_id: str, user_id: str, allowance_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    allowance = get_allowance(business_id, allowance_id)
    kind = str(body.get("kind") or "").strip().lower()
    if kind not in ("paid", "spent"):
        raise HTTPException(400, "kind must be paid (allowance to the minister) or spent (housing costs)")
    category = "allowance" if kind == "paid" else str(body.get("category") or "other").strip().lower()
    if kind == "spent" and category not in SPENT_CATEGORIES:
        raise HTTPException(400, f"category must be one of {', '.join(SPENT_CATEGORIES)}")
    when = _day(body.get("entry_date") or date.today().isoformat(), "entry_date")
    if when.year != int(allowance["tax_year"]):
        raise HTTPException(400, f"That date is outside {allowance['tax_year']}; it belongs to that "
                                 "year's allowance.")
    source = str(body.get("source") or "manual").strip().lower()
    if source not in SOURCES:
        raise HTTPException(400, "source must be manual, pay_run or bank")
    source_id = body.get("source_id") or None
    if source != "manual":
        if not source_id or not _SOURCE_ID.match(str(source_id)):
            raise HTTPException(400, "a pay run or bank entry needs the row it came from")
        table = "plaid_transactions" if source == "bank" else "pay_run_items"
        col = "transaction_id" if source == "bank" else "id"
        if not _belongs(table, business_id, source_id, col):
            raise HTTPException(400, "that row isn't one of this business's")
        if _get(f"/minister_housing_entries?allowance_id=eq.{_q(allowance_id)}&source=eq.{source}"
                f"&source_id=eq.{_q(source_id)}&select=id&limit=1"):
            raise HTTPException(409, "That row is already counted.")
    else:
        source_id = None
    res = sb_clients.sb_post_as_service("/minister_housing_entries", {
        "business_id": business_id, "allowance_id": allowance_id, "kind": kind,
        "entry_date": when.isoformat(), "amount": _amount(body.get("amount")), "category": category,
        "note": str(body.get("note") or "")[:500], "source": source, "source_id": source_id,
        "created_by": user_id})
    if not res:
        raise HTTPException(503, "That didn't save. Try again.")
    return res[0] if isinstance(res, list) else res


def delete_entry(business_id: str, entry_id: str) -> Dict[str, Any]:
    if not _UUID.match(str(entry_id)):
        raise HTTPException(404, "entry not found")
    rows = _get(f"/minister_housing_entries?id=eq.{_q(entry_id)}&business_id=eq.{_q(business_id)}"
                f"&select={_ENTRY_SELECT}&limit=1")
    if not rows:
        raise HTTPException(404, "entry not found")
    if sb_clients.sb_delete_as_service(
            f"/minister_housing_entries?id=eq.{_q(entry_id)}&business_id=eq.{_q(business_id)}") is None:
        raise HTTPException(503, "That didn't delete. Try again.")
    return rows[0]


def summary(business_id: str, year: Optional[int] = None) -> Dict[str, Any]:
    allowances = list_allowances(business_id)
    shown = [a for a in allowances if not year or int(a["tax_year"]) == int(year)]
    out = []
    for a in shown:
        entries = entries_for(business_id, a["id"])
        f = figures(a, entries)
        out.append({**a, "figures": f, "summary": describe(a, f), "entries": entries})
    return {"ok": True, "allowances": out, "reminders": reminders(allowances), "care": CARE}


def _guard(fn, *args):
    try:
        return fn(*args)
    except Unavailable:
        raise HTTPException(503, "The housing allowance records can't be read just now. If this is "
                                 "new, its database tables may not be set up yet.")


# ─── Routes (owner only) ──────────────────────────────────────────────

class AllowanceBody(BaseModel):
    business_id: str
    minister_name: Optional[str] = None
    tax_year: Optional[int] = None
    designated_amount: Optional[float] = None
    designated_on: Optional[str] = None
    board_decision_id: Optional[str] = None
    fair_rental_value: Optional[float] = None
    contact_id: Optional[str] = None
    employee_id: Optional[str] = None
    notes: Optional[str] = Field(default=None, max_length=2000)


class EntryBody(BaseModel):
    business_id: str
    kind: str
    amount: float
    entry_date: Optional[str] = None
    category: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=500)
    source: Optional[str] = None
    source_id: Optional[str] = None


def _given(body: BaseModel) -> Dict[str, Any]:
    return {k: v for k, v in body.model_dump(exclude_unset=True).items() if k != "business_id"}


@router.get("")
def get_housing_allowances(business_id: str = Query(...), year: Optional[int] = None,
                           user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    require_owner(business_id, user.id)
    return _guard(summary, business_id, year)


@router.post("")
def post_housing_allowance(body: AllowanceBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    require_owner(body.business_id, user.id)
    row = _guard(create_allowance, body.business_id, str(user.id), _given(body))
    return {"ok": True, "allowance": row}


@router.patch("/{allowance_id}")
def patch_housing_allowance(allowance_id: str, body: AllowanceBody,
                            user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    require_owner(body.business_id, user.id)
    return {"ok": True, "allowance": _guard(update_allowance, body.business_id, allowance_id, _given(body))}


@router.delete("/{allowance_id}")
def delete_housing_allowance(allowance_id: str, business_id: str = Query(...),
                             user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    require_owner(business_id, user.id)
    _guard(archive_allowance, business_id, allowance_id)
    return {"ok": True}


@router.post("/{allowance_id}/entries")
def post_housing_entry(allowance_id: str, body: EntryBody,
                       user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    require_owner(body.business_id, user.id)
    return {"ok": True, "entry": _guard(add_entry, body.business_id, str(user.id), allowance_id,
                                        _given(body))}


@router.delete("/entries/{entry_id}")
def delete_housing_entry_route(entry_id: str, business_id: str = Query(...),
                               user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    require_owner(business_id, user.id)
    _guard(delete_entry, business_id, entry_id)
    return {"ok": True}


# ─── Chief ────────────────────────────────────────────────────────────

TOOL = {
    "name": "housing_allowance_status",
    "description": (
        "The owner's minister housing allowance records: for each minister and tax year, the "
        "amount the board designated, allowance paid so far, housing costs logged, fair rental "
        "value, the excludable amount (the least of those), any taxable excess, what's left to "
        "pay, and the W-2 Box 14 figure. Use it for 'how much of my housing allowance is left', "
        "'what can I exclude', 'is next year's designated'. Quote its figures; never work them "
        "out yourself. Owner only."),
    "input_schema": {"type": "object", "properties": {
        "tax_year": {"type": "integer", "description": "Optional. Default: every year on record."}}},
}

def _fail(atype: str, msg: str) -> Dict[str, Any]:
    return {"type": atype, "result": f"Failed: {msg}", "label": msg[:80], "failed": True,
            "nav": NAV}


def _chief_gate(biz: Dict[str, Any], atype: str) -> Optional[Dict[str, Any]]:
    from chief_of_staff import _TURN_USER_ID
    try:
        require_owner(str(biz["id"]), _TURN_USER_ID.get())
    except HTTPException as e:
        if e.status_code == 404:
            return _fail(atype, "the housing allowance records aren't switched on for this business yet")
        if e.status_code == 403:
            return _fail(atype, "the housing allowance is the owner's alone")
        return _fail(atype, str(e.detail))
    return None


def _pick(business_id: str, action: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """The allowance an ask means: by id, else by name and year (this year
    unless named), else the only one this year."""
    year = action.get("tax_year") or date.today().year
    try:
        year = int(year)
    except (TypeError, ValueError):
        return None, "tax_year must be a year"
    rows = list_allowances(business_id, year)
    if action.get("allowance_id"):
        rows = [a for a in rows if a["id"] == action["allowance_id"]]
    elif action.get("minister_name"):
        want = str(action["minister_name"]).strip().lower()
        rows = [a for a in rows if want in a["minister_name"].lower()]
    if len(rows) == 1:
        return rows[0], ""
    if not rows:
        return None, f"there's no {year} housing allowance recorded" + (
            f" for {action['minister_name']}" if action.get("minister_name") else "")
    return None, "more than one minister has one: say which (" + ", ".join(
        a["minister_name"] for a in rows) + ")"


def _status_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "housing_allowance_status"
    refused = _chief_gate(biz, atype)
    if refused:
        return refused
    year = action.get("tax_year")
    try:
        data = summary(str(biz["id"]), int(year) if year else None)
    except (Unavailable, ValueError, TypeError):
        return _fail(atype, "the housing allowance records couldn't be read just now (if this is new, "
                            "its tables may not be set up yet). This is not 'none recorded'")
    rows = data["allowances"]
    if not rows:
        text = ("No housing allowance is recorded" + (f" for {year}" if year else "") +
                ". The owner can add the board's designation on the Housing allowance screen, or ask "
                "me to record it.")
    else:
        text = " ".join(r["summary"] for r in rows)
    if data["reminders"]:
        text += " " + " ".join(data["reminders"])
    return {"type": atype, "result": text, "label": "🏠 Housing allowance",
            "allowances": [{"id": r["id"], "minister_name": r["minister_name"], "tax_year": r["tax_year"],
                            "figures": r["figures"]} for r in rows],
            "note_for_chief": CARE + " Quote these figures; don't work them out yourself.",
            "nav": NAV}


def _log_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "log_housing_entry"
    refused = _chief_gate(biz, atype)
    if refused:
        return refused
    from chief_of_staff import _TURN_USER_ID
    try:
        allowance, why = _pick(str(biz["id"]), action)
        if not allowance:
            return _fail(atype, why)
        entry = add_entry(str(biz["id"]), _TURN_USER_ID.get(), allowance["id"], {
            k: action.get(k) for k in ("kind", "amount", "entry_date", "category", "note")})
        f = figures(allowance, entries_for(str(biz["id"]), allowance["id"]))
    except HTTPException as e:
        return _fail(atype, str(e.detail))
    except Unavailable:
        return _fail(atype, "the housing allowance records couldn't be read just now; nothing was saved")
    what = ("allowance paid" if entry["kind"] == "paid"
            else CATEGORY_WORDS.get(entry["category"], "housing costs"))
    return {"type": atype, "entry_id": entry["id"], "allowance_id": allowance["id"],
            "result": (f"Logged ${_num(entry['amount']):,.2f} of {what} on {entry['entry_date']} to "
                       f"{allowance['minister_name']}'s {allowance['tax_year']} housing allowance. "
                       f"Paid so far {_money(f['paid'])} of {_money(f['designated'])}; housing costs "
                       f"{_money(f['spent'])}."),
            "label": f"🏠 Logged ${_num(entry['amount']):,.2f} ({what})",
            "nav": NAV}


def _delete_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "delete_housing_entry"
    refused = _chief_gate(biz, atype)
    if refused:
        return refused
    try:
        gone = delete_entry(str(biz["id"]), str(action.get("entry_id") or ""))
    except HTTPException as e:
        return _fail(atype, str(e.detail))
    except Unavailable:
        return _fail(atype, "the housing allowance records couldn't be read just now; nothing changed")
    return {"type": atype, "result": f"Removed the ${_num(gone['amount']):,.2f} entry from "
                                     f"{gone['entry_date']}.",
            "label": "🏠 Removed a housing allowance entry",
            "nav": NAV}


def _set_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    """Record the board's designation (or change this year's). Asking is the
    approval; the amount and date must be the board's own."""
    atype = "set_housing_allowance"
    refused = _chief_gate(biz, atype)
    if refused:
        return refused
    from chief_of_staff import _TURN_USER_ID
    body = {k: action.get(k) for k in ("minister_name", "tax_year", "designated_amount", "designated_on",
                                       "fair_rental_value", "board_decision_id", "notes") if k in action}
    body.setdefault("tax_year", date.today().year)
    try:
        existing = [a for a in list_allowances(str(biz["id"]), int(body["tax_year"]))
                    if body.get("minister_name")
                    and a["minister_name"].lower() == str(body["minister_name"]).strip().lower()]
        if existing:
            row = update_allowance(str(biz["id"]), existing[0]["id"], body)
            verb = "Changed"
        else:
            row = create_allowance(str(biz["id"]), _TURN_USER_ID.get(), body)
            verb = "Recorded"
    except HTTPException as e:
        return _fail(atype, str(e.detail))
    except (Unavailable, ValueError, TypeError):
        return _fail(atype, "the housing allowance records couldn't be read just now; nothing was saved")
    return {"type": atype, "allowance_id": row.get("id"),
            "result": (f"{verb} {row.get('minister_name')}'s {row.get('tax_year')} housing allowance: "
                       f"${_num(row.get('designated_amount')):,.2f}, designated "
                       f"{str(row.get('designated_on') or '')[:10]}."),
            "label": f"🏠 {verb} the {row.get('tax_year')} housing allowance",
            "nav": NAV}


async def handle_housing_allowance_status(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_status_sync, biz, action or {})


async def handle_log_housing_entry(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_log_sync, biz, action or {})


async def handle_delete_housing_entry(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_delete_sync, biz, action or {})


async def handle_set_housing_allowance(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_set_sync, biz, action or {})
