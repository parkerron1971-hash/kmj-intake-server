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
    in advance ... the designation covers only what's paid ON OR AFTER the
                   board's vote (Treas. Reg. 1.107-1(b)). Allowance paid
                   before it is taxable salary: left out of every limit,
                   counted as taxable, and kept out of Box 14 (it's Box 1)
    reported ..... the allowance paid in the year (after the vote) is the
                   W-2 Box 14 figure. It is still income for self-employment
                   (SECA) tax: a minister pays Social Security and Medicare
                   themselves

THE PAPER TRAIL (Kevin, 2026-10-31: "add these structure and rules in
there"). Each allowance carries what the IRS would ask to see, and
`paper_trail()` turns it into a checklist (done / todo / warn / later):

    board_vote ...... the vote, in writing: linked to a Board decision
    in_advance ...... nothing paid before the vote (warns with the amount)
    independent ..... the minister stepped out of the vote, and the board
                      compared the pay with similar churches (IRC 4958's
                      safe harbor for reasonable pay): minister_recused,
                      comparables_note
    credential ...... ordained, licensed or commissioned (Publication 517):
                      minister_credential, credential_detail
    se_tax .......... how self-employment tax gets paid: quarterly estimates,
                      extra withholding, or an approved Form 4361
                      (se_tax_plan); cash_salary gives an estimate of it
    fair_rental ..... the home's fair rental value, and how it was set
                      (fair_rental_basis)
    receipts ........ a receipt on each housing cost (kept in the private
                      business-documents bucket, owner only), or where
                      they're kept (receipts_kept_where)
    w2 .............. the W-2 checked once it comes (w2_checked_on)

FROM THE BANK (Kevin, 2026-10-31: "i want to know exactly based on
transaction how much has been paid out ... ask chief to go through the
transaction and help me find what was paid out and attach it to the
housing payouts"). The record is only as good as its tie to the bank:

    find ............ the year's outgoing bank rows (the accounts in the
                      books) not yet on the record, the server's count and
                      total, and the ones that repeat (same amount, same
                      description: a regular transfer). Words or an exact
                      amount narrow it. Candidates, never proof: the owner
                      says which were housing allowance
    attach .......... ties the confirmed rows to the allowance as paid, the
                      whole payment or the housing part of it (a transfer
                      that was the whole paycheck). A typed-in payment of
                      the same amount within a week is the same payment: it
                      is tied, not counted twice. One batch, all or nothing;
                      what one bank row pays never adds up past the row
    detach .......... takes exactly one batch back: what it added is
                      removed, what it tied is typed-in again as it was
    the report ...... every payment beside its bank date, description and
                      amount; what's tied to the bank, from pay runs, and
                      typed in only; a CSV for the tax preparer. It says
                      where the bank history in the app starts: a payment
                      from before then can't be tied here

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
import csv
import io
import logging
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

import bank_picks
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
CREDENTIALS = ("ordained", "licensed", "commissioned")
SE_PLANS = ("estimates", "withholding", "exempt_4361")
# The paper trail's own fields (supabase/APPLY-2026-10-31-housing-paper-trail.sql).
TRAIL_TEXT = ("comparables_note", "credential_detail", "fair_rental_basis", "receipts_kept_where")
_ALLOWANCE_SELECT = ("id,business_id,minister_name,contact_id,employee_id,tax_year,designated_amount,"
                     "designated_on,board_decision_id,fair_rental_value,notes,archived_at,created_at,updated_at,"
                     "minister_recused,comparables_note,minister_credential,credential_detail,se_tax_plan,"
                     "cash_salary,fair_rental_basis,receipts_kept_where,w2_checked_on")
_ENTRY_SELECT = ("id,allowance_id,kind,entry_date,amount,category,note,source,source_id,created_at,"
                 "receipt_path,receipt_type")
# Housing receipts sit beside the church office's check receipts in the
# private bucket, in their own folder: church_checks never serves a path
# outside its folder, so the treasurer's screens can't reach these.
RECEIPT_FOLDER = "housing-receipts"
_RECEIPT_NAME = re.compile(r"[0-9a-f]{32}\.(jpg|pdf)")
# Where Chief's receipts point: Bookkeeping's Housing tab (solutionist-studio
# #1418). An app without the tab ignores bkTab and opens Bookkeeping.
NAV = {"tab": "operate", "sub": "bookkeeping", "bkTab": "housing"}
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


def _day_or_none(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v or "").strip()[:10])
    except ValueError:
        return None


def figures(allowance: Dict[str, Any], entries: List[Dict[str, Any]],
            today: Optional[date] = None) -> Dict[str, Any]:
    """Every number the screen, Chief and the year-end statement say.
    Allowance paid before the board's vote isn't housing allowance: it is
    left out of the "paid" limit and of Box 14, and counted as taxable."""
    today = today or date.today()
    designated = _num(allowance.get("designated_amount"))
    vote = _day_or_none(allowance.get("designated_on"))
    paid = early = 0.0
    for e in entries:
        if e.get("kind") == "paid":
            paid += _num(e.get("amount"))
            on = _day_or_none(e.get("entry_date"))
            if vote and on and on < vote:
                early += _num(e.get("amount"))
    paid, early = round(paid, 2), round(early, 2)
    paid_after = round(paid - early, 2)
    spent_by = {c: 0.0 for c in SPENT_CATEGORIES}
    for e in entries:
        if e.get("kind") == "spent":
            c = e.get("category") if e.get("category") in spent_by else "other"
            spent_by[c] = round(spent_by[c] + _num(e.get("amount")), 2)
    spent = round(sum(spent_by.values()), 2)
    frv_raw = allowance.get("fair_rental_value")
    frv = None if frv_raw in (None, "") else _num(frv_raw)

    limits = [("designated", designated), ("paid", paid_after), ("spent", spent)]
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
        "paid_before_designation": early,
        "paid_since_designation": paid_after,      # the "paid" limit
        "spent": spent,
        "spent_by_category": {k: v for k, v in spent_by.items() if v},
        "fair_rental_value": frv,
        "excludable": round(excludable, 2),
        "limited_by": limited_by,
        "taxable_excess": round(max(0.0, paid - excludable), 2),
        "left_to_pay": round(max(0.0, designated - paid_after), 2),
        "box_14": paid_after,
        "final": today > date(year, 12, 31),
        "missing": missing,
    }


_LIMIT_WORDS = {"designated": "the amount the board designated",
                "paid": "the allowance actually paid since the board's vote",
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
    if f.get("paid_before_designation"):
        s += (f"{_money(f['paid_before_designation'])} of it was paid before the board's vote, so it's "
              f"salary (W-2 Box 1), not housing allowance. ")
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


# ─── The paper trail (pure) ───────────────────────────────────────────

SE_NET_SHARE = 0.9235          # Schedule SE: 92.35% of earnings is taxed
SE_SOCIAL_SECURITY = 0.124     # up to the year's wage base
SE_MEDICARE = 0.029


def _holidays(year: int) -> set:
    """The two holidays that can move an estimate's due date: Martin
    Luther King Day (third Monday of January) and DC Emancipation Day
    (April 16, observed on the Friday or Monday when it's a weekend)."""
    jan1 = date(year, 1, 1)
    mlk = jan1 + timedelta(days=(0 - jan1.weekday()) % 7 + 14)
    em = date(year, 4, 16)
    em = em - timedelta(days=1) if em.weekday() == 5 else em + timedelta(days=1) if em.weekday() == 6 else em
    return {mlk, em}


def _business_day(d: date) -> date:
    off = _holidays(d.year)
    while d.weekday() >= 5 or d in off:
        d += timedelta(days=1)
    return d


def estimate_dates(year: int) -> List[date]:
    """The four Form 1040-ES due dates for a tax year, moved past a weekend
    or holiday the way the IRS moves them."""
    return [_business_day(d) for d in (date(year, 4, 15), date(year, 6, 15), date(year, 9, 15),
                                       date(year + 1, 1, 15))]


def next_estimate(year: int, today: Optional[date] = None) -> Optional[date]:
    today = today or date.today()
    return next((d for d in estimate_dates(year) if d >= today), None)


def se_tax_estimate(allowance: Dict[str, Any], f: Dict[str, Any]) -> Optional[float]:
    """About what the minister owes in self-employment tax for the year, on
    their cash salary plus the allowance (designated, or paid if more).
    None until the salary is given. Before the deduction for half of it,
    expenses or the 0.9% over $200,000: "about"."""
    salary = allowance.get("cash_salary")
    if salary in (None, ""):
        return None
    import payroll_calc
    net = SE_NET_SHARE * (_num(salary) + max(f["designated"], f["paid"]))
    base = payroll_calc.ss_wage_base(int(f["tax_year"]))
    return round(SE_SOCIAL_SECURITY * min(net, base) + SE_MEDICARE * net, 2)


def _step(key: str, state: str, label: str, detail: str) -> Dict[str, str]:
    return {"key": key, "state": state, "label": label, "detail": detail}


def _when(d: Any) -> str:
    day = _day_or_none(d)
    return f"{day:%B} {day.day}, {day.year}" if day else "the day it was set"


def paper_trail(allowance: Dict[str, Any], entries: List[Dict[str, Any]], f: Dict[str, Any],
                today: Optional[date] = None) -> List[Dict[str, str]]:
    """What the IRS would ask to see, as a checklist. state: done, todo,
    warn (something is wrong, not just missing) or later (not due yet)."""
    today = today or date.today()
    who = allowance.get("minister_name") or "The minister"
    vote = _when(allowance.get("designated_on"))
    out: List[Dict[str, str]] = []

    if allowance.get("board_decision_id"):
        out.append(_step("board_vote", "done", "The board's vote is on record",
                         f"The amount is linked to the Board decision from {vote}."))
    else:
        out.append(_step("board_vote", "todo", "Record the board's vote",
                         "The board sets the amount in writing. Record the vote in Board & minutes and "
                         "link it here."))

    early = f.get("paid_before_designation") or 0
    if early:
        out.append(_step("in_advance", "warn", "Some was paid before the vote",
                         f"{_money(early)} was paid before the board's vote on {vote}. That part is taxable "
                         "salary, not housing allowance: it belongs in W-2 Box 1."))
    else:
        out.append(_step("in_advance", "done", "Set before it was paid",
                         f"Nothing was paid as allowance before the board's vote on {vote}."))

    recused = allowance.get("minister_recused")
    comps = (allowance.get("comparables_note") or "").strip()
    if recused is False:
        out.append(_step("independent", "warn", f"{who} voted on their own allowance",
                         "Pay, including the allowance, should be approved by board members who don't "
                         f"benefit from it. Have the board vote again without {who}, and note it here."))
    elif recused and comps:
        out.append(_step("independent", "done", "Approved without the minister, against similar churches",
                         f"{who} stepped out of the vote. Compared with: {comps}"))
    else:
        missing = [w for w, ok in ((f"that {who} stepped out of the vote", recused),
                                   ("what the board compared the pay with (similar churches' pay)", comps)) if not ok]
        out.append(_step("independent", "todo", "Approved without the minister, against similar churches",
                         "Note " + " and ".join(missing) + ". The minutes should say so when it happens; it "
                         "protects the minister and the board if the IRS asks whether the pay is reasonable."))

    cred = allowance.get("minister_credential")
    if cred in CREDENTIALS:
        detail = (allowance.get("credential_detail") or "").strip()
        out.append(_step("credential", "done", f"{who} is {cred}",
                         detail or "Paid for ministry work: the IRS's test for a housing allowance."))
    else:
        out.append(_step("credential", "todo", f"Say how {who} is a minister",
                         "Ordained, licensed or commissioned, and paid for ministry work: the IRS's test for "
                         "a housing allowance."))

    plan = allowance.get("se_tax_plan")
    est = se_tax_estimate(allowance, f)
    owed = f"About {_money(est)} for {f['tax_year']}. " if est is not None else ""
    due = next_estimate(int(f["tax_year"]), today)
    due_words = f"The next quarterly estimate is due {_when(due.isoformat())}." if due else ""
    if plan == "exempt_4361":
        out.append(_step("se_tax", "done", "Exempt from self-employment tax",
                         "On file: an approved Form 4361. The allowance is then free of that tax too."))
    elif plan == "estimates":
        out.append(_step("se_tax", "done", "Self-employment tax: quarterly estimates",
                         (owed + due_words).strip() or "Paid with Form 1040-ES each quarter."))
    elif plan == "withholding":
        out.append(_step("se_tax", "done", "Self-employment tax: extra withholding",
                         owed + "The church withholds extra federal income tax to cover it."))
    else:
        out.append(_step("se_tax", "todo", "Plan for self-employment tax",
                         "The church takes no Social Security or Medicare out of a minister's pay. "
                         f"{who} pays about 14% on salary plus allowance: the allowance is free of income "
                         "tax only. " + owed + "Pay it with quarterly estimates or ask the church to "
                         "withhold extra federal income tax. " + due_words))

    frv = f.get("fair_rental_value")
    basis = (allowance.get("fair_rental_basis") or "").strip()
    if frv is None:
        out.append(_step("fair_rental", "todo", "Set the home's fair rental value",
                         "What the home would rent for, furnished, plus utilities. It's one of the four "
                         "limits."))
    elif not basis:
        out.append(_step("fair_rental", "todo", "Note how the fair rental value was set",
                         "A realtor's letter, or a few listings for similar homes, will do."))
    else:
        out.append(_step("fair_rental", "done", "Fair rental value, with how it was set", basis))

    spent = [e for e in entries if e.get("kind") == "spent"]
    held = sum(1 for e in spent if e.get("receipt_path") or e.get("receipt"))
    where = (allowance.get("receipts_kept_where") or "").strip()
    if not spent:
        out.append(_step("receipts", "later", "Keep receipts for housing costs",
                         "Log each housing cost as it comes, with a photo of its receipt."))
    elif held == len(spent):
        out.append(_step("receipts", "done", "Every housing cost has its receipt",
                         f"{held} of {len(spent)} kept here."))
    elif where:
        out.append(_step("receipts", "done", "Receipts kept",
                         f"{held} of {len(spent)} kept here; the rest: {where}"))
    else:
        out.append(_step("receipts", "todo", "Keep receipts for housing costs",
                         f"{len(spent) - held} of {len(spent)} housing costs have no receipt here. Add a photo "
                         "of each, or note where they're kept."))

    w2 = ("Box 1 leaves out the allowance; the Social Security and Medicare boxes (3 to 6) are empty; "
          f"Box 14 shows {_money(f['box_14'])}.")
    if early:
        w2 += f" The {_money(early)} paid before the vote is in Box 1."
    if allowance.get("w2_checked_on"):
        out.append(_step("w2", "done", "W-2 checked", f"Checked {_when(allowance['w2_checked_on'])}. " + w2))
    elif f.get("final"):
        out.append(_step("w2", "todo", f"Check the {f['tax_year']} W-2", w2))
    else:
        out.append(_step("w2", "later", f"Check the W-2 in January {int(f['tax_year']) + 1}", w2))
    return out


def open_steps(trail: List[Dict[str, str]]) -> List[str]:
    return [s["label"] for s in trail if s["state"] in ("todo", "warn")]


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


def _all(path: str) -> List[Dict[str, Any]]:
    """A read that can pass 1,000 rows (PostgREST's most a read), paged."""
    import bank_picks
    try:
        return bank_picks.read_all(path, _get)
    except bank_picks.TooMany as e:
        raise Unavailable(str(e))


def entries_for(business_id: str, allowance_id: str) -> List[Dict[str, Any]]:
    return _all(f"/minister_housing_entries?business_id=eq.{_q(business_id)}"
                f"&allowance_id=eq.{_q(allowance_id)}&select={_ENTRY_SELECT}"
                f"&order=entry_date.asc,created_at.asc,id.asc")


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
    # The paper trail.
    if "minister_recused" in body:
        v = body.get("minister_recused")
        if v is not None and not isinstance(v, bool):
            raise HTTPException(400, "minister_recused must be true, false or empty")
        out["minister_recused"] = v
    for key in TRAIL_TEXT:
        if key in body:
            out[key] = " ".join(str(body.get(key) or "").split())[:1000] or None
    for key, allowed in (("minister_credential", CREDENTIALS), ("se_tax_plan", SE_PLANS)):
        if key in body:
            v = str(body.get(key) or "").strip().lower() or None
            if v and v not in allowed:
                raise HTTPException(400, f"{key} must be one of {', '.join(allowed)}")
            out[key] = v
    if "cash_salary" in body:
        v = body.get("cash_salary")
        out["cash_salary"] = None if v in (None, "") else _amount(v, allow_zero=True, what="cash_salary")
    if "w2_checked_on" in body:
        v = body.get("w2_checked_on")
        if v in (None, ""):
            out["w2_checked_on"] = None
        else:
            day = _day(v, "w2_checked_on")
            if day > date.today():
                raise HTTPException(400, "w2_checked_on can't be in the future")
            out["w2_checked_on"] = day.isoformat()
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
    if not sb_clients.sb_delete_as_service(
            f"/minister_housing_entries?id=eq.{_q(entry_id)}&business_id=eq.{_q(business_id)}"):
        raise HTTPException(503, "That didn't delete. Try again.")
    if receipt_key(business_id, rows[0].get("receipt_path")):
        import church_checks
        church_checks._storage_drop(rows[0]["receipt_path"])
    return _public_entry(rows[0])


def _public_entry(e: Dict[str, Any]) -> Dict[str, Any]:
    """An entry as the screen sees it: whether it has a receipt, never the
    storage path."""
    out = {k: v for k, v in e.items() if k not in ("receipt_path", "receipt_type")}
    out["receipt"] = e.get("receipt_type") if e.get("receipt_path") else None
    return out


# ─── Receipts (the private bucket, the owner only) ────────────────────

def receipt_key(business_id: str, path: Any) -> bool:
    """True only for a receipt path this module could have made here."""
    import storage_links
    biz = storage_links.canonical_business_id(business_id)
    if not biz or not isinstance(path, str):
        return False
    head = f"{biz}/{RECEIPT_FOLDER}/"
    return path.startswith(head) and bool(_RECEIPT_NAME.fullmatch(path[len(head):]))


def _entry_row(business_id: str, entry_id: str) -> Dict[str, Any]:
    if not _UUID.match(str(entry_id)):
        raise HTTPException(404, "entry not found")
    rows = _get(f"/minister_housing_entries?id=eq.{_q(entry_id)}&business_id=eq.{_q(business_id)}"
                f"&select={_ENTRY_SELECT}&limit=1")
    if not rows:
        raise HTTPException(404, "entry not found")
    return rows[0]


def attach_receipt(business_id: str, entry_id: str, raw: bytes) -> Dict[str, Any]:
    """A photo or PDF of one housing cost's receipt; a new one replaces the
    old. Uses the church office's receipt handling (a photo re-saved
    upright as JPEG, which drops the phone's location tags)."""
    import church_checks
    import storage_links
    row = _entry_row(business_id, entry_id)
    if row.get("kind") != "spent":
        raise HTTPException(400, "A receipt goes on a housing cost, not on allowance paid.")
    kind, data, media, ext = church_checks.prepare_receipt(raw)
    biz = storage_links.canonical_business_id(business_id)
    if not biz or not storage_links.has_service_key():
        raise HTTPException(503, storage_links.UPLOAD_NOT_CONFIGURED)
    path = f"{biz}/{RECEIPT_FOLDER}/{uuid.uuid4().hex}.{ext}"
    ok, status, body = church_checks._storage_put(path, data, media)
    if not ok:
        logger.warning("housing allowance: receipt refused %s %s", status, body[:200])
        raise HTTPException(503, storage_links.upload_refusal(status, body) if status
                            else storage_links.UPLOAD_UNREACHABLE)
    res = sb_clients.sb_patch_as_service(
        f"/minister_housing_entries?id=eq.{_q(entry_id)}&business_id=eq.{_q(business_id)}",
        {"receipt_path": path, "receipt_type": kind})
    if not res:
        church_checks._storage_drop(path)
        raise HTTPException(503, "The receipt didn't save. Try again.")
    old = row.get("receipt_path")
    if old and old != path and receipt_key(business_id, old):
        church_checks._storage_drop(old)
    return _public_entry({**row, "receipt_path": path, "receipt_type": kind})


def read_receipt(business_id: str, entry_id: str) -> Response:
    """One entry's receipt, from the server only: never a public link."""
    import church_checks
    path = _entry_row(business_id, entry_id).get("receipt_path")
    if not path or not receipt_key(business_id, path):
        raise HTTPException(404, "There's no receipt on this one.")
    data = church_checks._storage_get(path)
    if data is None:
        raise HTTPException(503, "The receipt couldn't be read just now. Try again.")
    ext = str(path).rsplit(".", 1)[-1]
    return Response(content=data, media_type="application/pdf" if ext == "pdf" else "image/jpeg", headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f'inline; filename="housing-receipt.{ext}"'})


# ─── From the bank ────────────────────────────────────────────────────

BANK_MATCH_DAYS = 7      # a typed-in payment this close, same amount, is the same payment
ATTACH_MAX = 60
FIND_ROWS = 400
SOURCE_WORDS = {"bank": "tied to a bank payment", "pay_run": "from a pay run", "manual": "typed in"}
# The bank is read the way the funds for the year read it (bank_picks.py).
_in, _bank_words = bank_picks.in_, bank_picks.words


def _bank_accounts(business_id: str) -> List[str]:
    """The accounts in the books: the Transactions screen's own."""
    return bank_picks.accounts(business_id, _get)


def bank_history_starts(business_id: str, accounts: List[str]) -> Optional[str]:
    """The first day the app has bank rows for: a payment before it can't be
    tied here, and the report says so."""
    return bank_picks.history_starts(business_id, accounts, _get)


def _bank_rows(business_id: str, accounts: List[str], year: int) -> List[Dict[str, Any]]:
    """Every cleared payment out of those accounts in the year; past the cap
    a failure, never a part passed off as the whole."""
    try:
        return bank_picks.year_rows(business_id, accounts, year, _get, "out")
    except bank_picks.TooMany:
        raise Unavailable("more bank rows than can be read at once")


def _bank_used(business_id: str, allowance_id: str) -> Tuple[Dict[str, float], set]:
    """How much of each bank row is already counted (any allowance of this
    business), and the rows this allowance already has."""
    used: Dict[str, float] = {}
    mine: set = set()
    for e in _all(f"/minister_housing_entries?business_id=eq.{_q(business_id)}&source=eq.bank"
                  "&select=allowance_id,source_id,amount&order=id.asc"):
        sid = str(e.get("source_id") or "")
        used[sid] = round(used.get(sid, 0.0) + _num(e.get("amount")), 2)
        if str(e.get("allowance_id")) == str(allowance_id):
            mine.add(sid)
    return used, mine


def _typed_twin(typed: List[Dict[str, Any]], amount: float, on: Optional[date],
                claimed: set) -> Optional[Dict[str, Any]]:
    """The typed-in payment that is this bank payment: the same amount within
    a week, the closest first."""
    if not on:
        return None
    best = None
    for e in typed:
        d = _day_or_none(e.get("entry_date"))
        if e["id"] in claimed or not d or abs(_num(e.get("amount")) - amount) > 0.005:
            continue
        gap = abs((d - on).days)
        if gap <= BANK_MATCH_DAYS and (best is None or gap < best[0]):
            best = (gap, e)
    return best[1] if best else None


def _typed(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [e for e in entries if e.get("kind") == "paid" and (e.get("source") or "manual") == "manual"]


def find_bank_payments(business_id: str, allowance_id: str, *, words: Optional[List[str]] = None,
                       amount: Any = None) -> Dict[str, Any]:
    allowance = get_allowance(business_id, allowance_id)
    year = int(allowance["tax_year"])
    accounts = _bank_accounts(business_id)
    used, mine = _bank_used(business_id, allowance_id)
    typed = _typed(entries_for(business_id, allowance_id))
    want = None if amount in (None, "") else _amount(amount)
    words = [w for w in (" ".join(str(x).split()).lower() for x in (words or [])) if w][:6]
    rows: List[Dict[str, Any]] = []
    for t in _bank_rows(business_id, accounts, year):
        tid = str(t.get("transaction_id") or "")
        a = _num(t.get("amount"))
        left = round(a - used.get(tid, 0.0), 2)
        if not tid or tid in mine or left <= 0:
            continue
        if words and not any(w in f"{t.get('name') or ''} {t.get('merchant_name') or ''}".lower() for w in words):
            continue
        if want is not None and abs(a - want) > 0.005 and abs(left - want) > 0.005:
            continue
        row = {"transaction_id": tid, "date": str(t.get("date") or "")[:10], "description": _bank_words(t),
               "amount": a}
        if left < a:
            row["left"] = left
        if t.get("excluded_from_books"):
            row["excluded"] = True
        twin = _typed_twin(typed, left, _day_or_none(row["date"]), set())
        if twin:
            row["typed_in"] = {"entry_id": twin["id"], "entry_date": str(twin.get("entry_date"))[:10]}
        rows.append(row)
    newest = sorted(rows, key=lambda r: (r["date"], r["transaction_id"]), reverse=True)
    starts = bank_history_starts(business_id, accounts)
    return {
        "allowance": allowance, "tax_year": year, "accounts": len(accounts), "history_starts": starts,
        "history_late": bool(starts and starts > f"{year}-01-01"),
        "count": len(rows), "total": round(sum(r.get("left", r["amount"]) for r in rows), 2),
        "repeats": bank_picks.repeats(rows),
        "rows": newest[:FIND_ROWS], "capped": len(newest) > FIND_ROWS,
        "typed_in": {"count": len(typed), "amount": round(sum(_num(e.get("amount")) for e in typed), 2)},
    }


def attach_bank_payments(business_id: str, user_id: Optional[str], allowance_id: str,
                         items: Any) -> Dict[str, Any]:
    """Tie confirmed bank payments to the allowance as allowance paid: all of
    them or none. Each item is {transaction_id, amount?}; no amount is the
    whole payment (what's left of it)."""
    allowance = get_allowance(business_id, allowance_id)
    year = int(allowance["tax_year"])
    if not isinstance(items, list) or not 1 <= len(items) <= ATTACH_MAX:
        raise HTTPException(400, f"Pick from 1 to {ATTACH_MAX} bank payments.")
    want: Dict[str, Optional[float]] = {}
    for it in items:
        tid = str((it or {}).get("transaction_id") or "").strip() if isinstance(it, dict) else ""
        if not _SOURCE_ID.match(tid):
            raise HTTPException(400, "Each one needs the bank payment it came from.")
        if tid in want:
            raise HTTPException(400, "The same bank payment is in the list twice.")
        part = it.get("amount")
        want[tid] = None if part in (None, "") else _amount(part, what="the housing part")
    accounts = set(_bank_accounts(business_id))
    bank = {str(t.get("transaction_id")): t for t in _get(
        f"/plaid_transactions?business_id=eq.{_q(business_id)}&transaction_id={_in(want)}"
        f"&select={bank_picks.SELECT}&limit={len(want)}")}
    used, mine = _bank_used(business_id, allowance_id)
    typed = _typed(entries_for(business_id, allowance_id))
    claimed: set = set()
    plan = []
    for tid, part in want.items():
        t = bank.get(tid)
        if not t:
            raise HTTPException(400, "One of those isn't a bank payment of this business.")
        if str(t.get("account_id") or "") not in accounts:
            # Find offers only the accounts in the books; an account left out
            # of them (a personal one) isn't the church's money.
            raise HTTPException(400, "One of those is from an account that isn't in the books.")
        a, on = _num(t.get("amount")), _day_or_none(t.get("date"))
        when, desc = str(t.get("date") or "")[:10], _bank_words(t)
        if a <= 0:
            raise HTTPException(400, f"The {_when(when)} bank row ({desc}) is money coming in, not a payment.")
        if t.get("pending"):
            raise HTTPException(400, f"The {_when(when)} payment is still pending at the bank; tie it once it clears.")
        if not on or on.year != year:
            raise HTTPException(400, f"The {_when(when)} payment is outside {year}; it belongs to that "
                                     "year's allowance.")
        if tid in mine:
            raise HTTPException(409, f"The {_when(when)} payment of {_money(a)} is already counted.")
        left = round(a - used.get(tid, 0.0), 2)
        if left <= 0:
            raise HTTPException(409, f"All of the {_when(when)} payment of {_money(a)} is already counted "
                                     "on another allowance.")
        part = left if part is None else part
        if part > left + 0.005:
            raise HTTPException(400, f"The {_when(when)} payment was {_money(a)}" + (
                f"; {_money(left)} of it is left to count." if left < a else
                "; the housing part can't be more than that."))
        twin = _typed_twin(typed, part, on, claimed)
        if twin:
            claimed.add(twin["id"])
        plan.append({"tid": tid, "date": when, "description": desc, "bank_amount": a, "amount": part,
                     "twin": twin})
    new_rows = [{
        "business_id": business_id, "allowance_id": allowance_id, "kind": "paid", "category": "allowance",
        "entry_date": p["date"], "amount": p["amount"], "source": "bank", "source_id": p["tid"],
        "note": (f"Bank: {p['description']}" + (f" (part of {_money(p['bank_amount'])})"
                                                 if p["amount"] < p["bank_amount"] else ""))[:500],
        "created_by": user_id} for p in plan if not p["twin"]]
    created: List[Dict[str, Any]] = []
    if new_rows:
        res = sb_clients.sb_post_as_service("/minister_housing_entries", new_rows)
        if not res or not isinstance(res, list) or len(res) != len(new_rows):
            raise HTTPException(503, "Those payments didn't save. Nothing was changed; try again.")
        created = res
    restore: List[Dict[str, Any]] = []
    for p in plan:
        twin = p["twin"]
        if not twin:
            continue
        res = sb_clients.sb_patch_as_service(
            f"/minister_housing_entries?id=eq.{_q(twin['id'])}&business_id=eq.{_q(business_id)}"
            "&source=eq.manual", {"source": "bank", "source_id": p["tid"], "entry_date": p["date"]})
        if not res:
            _take_back(business_id, [c["id"] for c in created], restore)
            raise HTTPException(503, "Those payments didn't save. Nothing was changed; try again.")
        restore.append({"entry_id": twin["id"], "entry_date": str(twin.get("entry_date"))[:10]})
    by_tid = {str(c.get("source_id")): c for c in created}
    attached = []
    for p in plan:
        eid = p["twin"]["id"] if p["twin"] else by_tid.get(p["tid"], {}).get("id")
        attached.append({"entry_id": eid, "transaction_id": p["tid"], "date": p["date"],
                         "description": p["description"], "amount": p["amount"],
                         "bank_amount": p["bank_amount"], "was_typed_in": bool(p["twin"])})
    return {"allowance": allowance, "attached": attached, "created_ids": [c["id"] for c in created],
            "restore": restore, "total": round(sum(p["amount"] for p in plan), 2)}


def _take_back(business_id: str, remove_ids: List[str], restore: List[Dict[str, Any]]) -> Tuple[int, int]:
    """Remove the entries a batch added and untie the ones it tied. Only
    bank-tied entries are touched: never a typed-in or pay run one."""
    removed = untied = 0
    if remove_ids:
        rows = _get(f"/minister_housing_entries?business_id=eq.{_q(business_id)}&id={_in(remove_ids)}"
                    "&source=eq.bank&select=id&limit=500")
        if rows:
            if not sb_clients.sb_delete_as_service(
                    f"/minister_housing_entries?business_id=eq.{_q(business_id)}"
                    f"&id={_in([r['id'] for r in rows])}&source=eq.bank"):
                raise HTTPException(503, "That didn't take back. Try again.")
            removed = len(rows)
    for r in restore:
        patch: Dict[str, Any] = {"source": "manual", "source_id": None}
        if _day_or_none(r.get("entry_date")):
            patch["entry_date"] = str(r["entry_date"])[:10]
        if sb_clients.sb_patch_as_service(
                f"/minister_housing_entries?id=eq.{_q(r['entry_id'])}&business_id=eq.{_q(business_id)}"
                "&source=eq.bank", patch):
            untied += 1
    return removed, untied


def detach_bank_payments(business_id: str, remove_ids: Any = None, restore: Any = None) -> Dict[str, Any]:
    """Take back what one batch did, or untie single entries (restore with
    no date keeps the entry's own)."""
    remove = [str(i) for i in (remove_ids or []) if _UUID.match(str(i))]
    back = [{"entry_id": str(r.get("entry_id")), "entry_date": r.get("entry_date")}
            for r in (restore or []) if isinstance(r, dict) and _UUID.match(str(r.get("entry_id") or ""))]
    if not remove and not back:
        raise HTTPException(400, "Say which payments to take back.")
    if len(remove) + len(back) > ATTACH_MAX * 2:
        raise HTTPException(400, "That's more than one batch.")
    removed, untied = _take_back(business_id, remove, back)
    return {"removed": removed, "untied": untied}


def sources(entries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Allowance paid by where it came from: tied to the bank, a pay run,
    typed in only."""
    out = {s: {"count": 0, "amount": 0.0} for s in SOURCES}
    for e in entries:
        if e.get("kind") != "paid":
            continue
        s = e.get("source") if e.get("source") in SOURCES else "manual"
        out[s]["count"] += 1
        out[s]["amount"] = round(out[s]["amount"] + _num(e.get("amount")), 2)
    return out


def _with_bank(business_id: str, entries: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], bool]:
    """Each bank-tied entry with its bank row (date, description, amount).
    A failed read leaves the entries as they are and says so."""
    ids = sorted({str(e["source_id"]) for e in entries if e.get("source") == "bank" and e.get("source_id")})
    if not ids:
        return entries, True
    rows: Dict[str, Dict[str, Any]] = {}
    try:
        for i in range(0, len(ids), 100):
            chunk = ids[i:i + 100]
            for t in _get(f"/plaid_transactions?business_id=eq.{_q(business_id)}&transaction_id={_in(chunk)}"
                          f"&select=transaction_id,date,name,merchant_name,amount&limit={len(chunk)}"):
                rows[str(t.get("transaction_id"))] = t
    except Unavailable:
        return entries, False
    out = []
    for e in entries:
        if e.get("source") == "bank" and e.get("source_id"):
            t = rows.get(str(e["source_id"]))
            e = {**e, "bank": ({"date": str(t.get("date") or "")[:10], "description": _bank_words(t),
                                "amount": _num(t.get("amount"))} if t else {"missing": True})}
        out.append(e)
    return out, True


def _bank_state(business_id: str) -> Optional[Dict[str, Any]]:
    try:
        accounts = _bank_accounts(business_id)
        return {"accounts": len(accounts), "history_starts": bank_history_starts(business_id, accounts)}
    except Unavailable:
        return None


def _cell(v: Any) -> Any:
    """A spreadsheet never runs a cell as a formula: a bank's description can
    start with anything."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def report_csv(business_id: str, allowance_id: str) -> Tuple[str, str]:
    """The year for the tax preparer: every entry beside its bank row, then
    the figures."""
    a = get_allowance(business_id, allowance_id)
    entries, bank_ok = _with_bank(business_id, entries_for(business_id, allowance_id))
    f = figures(a, entries)
    src = sources(entries)
    vote = _day_or_none(a.get("designated_on"))
    state = _bank_state(business_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([_cell(f"{a['minister_name']}: {a['tax_year']} housing allowance")])
    w.writerow(["Date", "Type", "Category", "Amount", "From", "Bank date", "Bank description",
                "Bank amount", "Before the board's vote", "Receipt", "Note"])
    for e in sorted(entries, key=lambda e: (str(e.get("entry_date")), str(e.get("created_at")))):
        paid = e.get("kind") == "paid"
        on = _day_or_none(e.get("entry_date"))
        b = e.get("bank") or {}
        w.writerow([
            str(e.get("entry_date") or "")[:10], "Allowance paid" if paid else "Housing cost",
            "" if paid else CATEGORY_WORDS.get(e.get("category"), "other housing costs"),
            f"{_num(e.get('amount')):.2f}", SOURCE_WORDS.get(e.get("source") or "manual", "typed in"),
            b.get("date", ""), _cell("(no longer in the bank feed)" if b.get("missing") else b.get("description", "")),
            f"{b['amount']:.2f}" if "amount" in b else "",
            ("Yes" if vote and on and on < vote else "No") if paid else "",
            "" if paid else ("Yes" if e.get("receipt_path") else "No"),
            _cell(str(e.get("note") or "")),
        ])
    w.writerow([])
    lines = [
        (f"Designated by the board ({_when(a.get('designated_on'))})", f["designated"]),
        ("Allowance paid", f["paid"]),
        ("Paid before the board's vote: taxable salary, W-2 Box 1", f["paid_before_designation"]),
        ("Paid since the vote: W-2 Box 14", f["box_14"]),
        (f"Tied to a bank payment ({src['bank']['count']})", src["bank"]["amount"]),
        (f"From pay runs ({src['pay_run']['count']})", src["pay_run"]["amount"]),
        (f"Typed in, not tied to the bank ({src['manual']['count']})", src["manual"]["amount"]),
        ("Housing costs", f["spent"]),
        ("Fair rental value", f["fair_rental_value"]),
        (f"Excludable, limited by {_LIMIT_WORDS[f['limited_by']]}", f["excludable"]),
        ("Taxable excess", f["taxable_excess"]),
    ]
    for label, n in lines:
        w.writerow(["", label, "", "" if n is None else f"{n:.2f}"])
    w.writerow([])
    if state and state.get("history_starts") and state["history_starts"] > f"{a['tax_year']}-01-01":
        w.writerow(["", f"The bank history in the app starts {_when(state['history_starts'])}: a payment "
                        "from before then can't be tied to the bank here."])
    if not bank_ok:
        w.writerow(["", "The bank rows couldn't be read just now, so the bank columns are empty."])
    w.writerow(["", CARE])
    slug = re.sub(r"[^a-z0-9]+", "-", a["minister_name"].lower()).strip("-") or "minister"
    return buf.getvalue(), f"housing-allowance-{a['tax_year']}-{slug}.csv"


def summary(business_id: str, year: Optional[int] = None) -> Dict[str, Any]:
    allowances = list_allowances(business_id)
    shown = [a for a in allowances if not year or int(a["tax_year"]) == int(year)]
    out = []
    for a in shown:
        entries, bank_ok = _with_bank(business_id, entries_for(business_id, a["id"]))
        f = figures(a, entries)
        trail = paper_trail(a, entries, f)
        out.append({**a, "figures": f, "summary": describe(a, f), "paper_trail": trail,
                    "paid_from": sources(entries), "bank_read": bank_ok,
                    "entries": [_public_entry(e) for e in entries]})
    return {"ok": True, "allowances": out, "reminders": reminders(allowances), "care": CARE,
            "bank": _bank_state(business_id) if shown else None}


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
    minister_recused: Optional[bool] = None
    comparables_note: Optional[str] = Field(default=None, max_length=1000)
    minister_credential: Optional[str] = None
    credential_detail: Optional[str] = Field(default=None, max_length=1000)
    se_tax_plan: Optional[str] = None
    cash_salary: Optional[float] = None
    fair_rental_basis: Optional[str] = Field(default=None, max_length=1000)
    receipts_kept_where: Optional[str] = Field(default=None, max_length=1000)
    w2_checked_on: Optional[str] = None


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
    return {"ok": True, "entry": _public_entry(_guard(add_entry, body.business_id, str(user.id), allowance_id,
                                                      _given(body)))}


@router.delete("/entries/{entry_id}")
def delete_housing_entry_route(entry_id: str, business_id: str = Query(...),
                               user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    require_owner(business_id, user.id)
    _guard(delete_entry, business_id, entry_id)
    return {"ok": True}


@router.post("/entries/{entry_id}/receipt")
def post_housing_receipt(entry_id: str, business_id: str = Form(...), file: UploadFile = File(...),
                         user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    require_owner(business_id, user.id)
    import church_checks
    raw = file.file.read(church_checks.RECEIPT_MAX_BYTES + 1)
    return {"ok": True, "entry": _guard(attach_receipt, business_id, entry_id, raw)}


@router.get("/entries/{entry_id}/receipt")
def get_housing_receipt(entry_id: str, business_id: str = Query(...),
                        user: AuthedUser = Depends(require_user)) -> Response:
    require_owner(business_id, user.id)
    return _guard(read_receipt, business_id, entry_id)


class BankAttachBody(BaseModel):
    business_id: str
    items: List[Dict[str, Any]] = Field(default_factory=list, max_length=ATTACH_MAX)


class BankDetachBody(BaseModel):
    business_id: str
    remove_ids: List[str] = Field(default_factory=list, max_length=ATTACH_MAX * 2)
    restore: List[Dict[str, Any]] = Field(default_factory=list, max_length=ATTACH_MAX * 2)


@router.get("/{allowance_id}/bank")
def get_housing_bank(allowance_id: str, business_id: str = Query(...), q: Optional[str] = None,
                     amount: Optional[float] = None, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The year's payments out of the bank not yet on this allowance."""
    require_owner(business_id, user.id)
    data = _guard(lambda: find_bank_payments(business_id, allowance_id, words=(q or "").split(), amount=amount))
    data.pop("allowance", None)
    return {"ok": True, **data}


@router.post("/{allowance_id}/bank")
def post_housing_bank(allowance_id: str, body: BankAttachBody,
                      user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    require_owner(body.business_id, user.id)
    done = _guard(attach_bank_payments, body.business_id, str(user.id), allowance_id, body.items)
    try:
        f: Optional[Dict[str, Any]] = figures(done["allowance"], entries_for(body.business_id, allowance_id))
    except Unavailable:
        f = None   # tied all the same: the screen re-reads, and Undo has its lists
    return {"ok": True, "attached": done["attached"], "created_ids": done["created_ids"],
            "restore": done["restore"], "total": done["total"], "figures": f}


@router.post("/bank/detach")
def post_housing_bank_detach(body: BankDetachBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    require_owner(body.business_id, user.id)
    return {"ok": True, **_guard(detach_bank_payments, body.business_id, body.remove_ids, body.restore)}


@router.get("/{allowance_id}/report.csv")
def get_housing_report(allowance_id: str, business_id: str = Query(...),
                       user: AuthedUser = Depends(require_user)) -> Response:
    require_owner(business_id, user.id)
    text, name = _guard(report_csv, business_id, allowance_id)
    return Response(content=text.encode("utf-8-sig"), media_type="text/csv; charset=utf-8", headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f'attachment; filename="{name}"'})


# ─── Chief ────────────────────────────────────────────────────────────

TOOL = {
    "name": "housing_allowance_status",
    "description": (
        "The owner's minister housing allowance records: for each minister and tax year, the "
        "amount the board designated, allowance paid so far, housing costs logged, fair rental "
        "value, the excludable amount (the least of those), any taxable excess, what's left to "
        "pay, the W-2 Box 14 figure, and the paper trail (the board's vote on record, nothing paid "
        "before it, the minister out of the vote, how they're a minister, the self-employment tax "
        "plan, how the rental value was set, receipts, the W-2 checked). Use it for 'how much of "
        "my housing allowance is left', 'what can I exclude', 'is next year's designated', 'what "
        "paperwork am I missing'. Quote its figures; never work them out yourself. Owner only."),
    "input_schema": {"type": "object", "properties": {
        "tax_year": {"type": "integer", "description": "Optional. Default: every year on record."}}},
}

FIND_TOOL = {
    "name": "find_housing_payments",
    "description": (
        "Look through this business's payments out of the bank (the accounts in the books) for a "
        "minister's housing allowance year: the ones not yet on its record, with the server's count "
        "and total, the payments that repeat (same amount, same description: a regular transfer), "
        "each one's transaction_id for attach_housing_payments, and where the bank history in the app "
        "starts. Optional words (matched against the bank's description) or an exact amount narrow it. "
        "Use it for 'find my housing payments in the bank', 'what was paid out for housing'. These are "
        "candidates by amount and timing, not proof: show them and tie only the ones the owner "
        "confirms. Owner only."),
    "input_schema": {"type": "object", "properties": {
        "words": {"type": "array", "items": {"type": "string"}, "maxItems": 6,
                  "description": "Optional: words in the bank's description (a name, 'transfer', 'zelle')."},
        "amount": {"type": "number", "description": "Optional: an exact amount, e.g. the monthly allowance."},
        "minister_name": {"type": "string", "description": "Optional, when more than one minister has one."},
        "tax_year": {"type": "integer", "description": "Optional. Default: this year."}}},
}
SHOW_ROWS = 25

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


def _trail_words(row: Dict[str, Any]) -> str:
    still = open_steps(row.get("paper_trail") or [])
    if not still:
        return " Paper trail: complete."
    return f" Paper trail, still to do: {'; '.join(still)}."


def _from_words(row: Dict[str, Any]) -> str:
    src = row.get("paid_from") or {}
    if not row["figures"]["paid"]:
        return ""
    said = [f"{_money(src[k]['amount'])} {SOURCE_WORDS[k]}" for k in ("bank", "pay_run", "manual")
            if (src.get(k) or {}).get("count")]
    return f" Of what was paid: {', '.join(said)}." if said else ""


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
        text = " ".join(r["summary"] + _from_words(r) + _trail_words(r) for r in rows)
    if data["reminders"]:
        text += " " + " ".join(data["reminders"])
    return {"type": atype, "result": text, "label": "🏠 Housing allowance",
            "allowances": [{"id": r["id"], "minister_name": r["minister_name"], "tax_year": r["tax_year"],
                            "figures": r["figures"], "paper_trail": r["paper_trail"]} for r in rows],
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
    early = ""
    vote = _day_or_none(allowance.get("designated_on"))
    if entry["kind"] == "paid" and vote and (_day_or_none(entry.get("entry_date")) or vote) < vote:
        early = (f" That's before the board's vote on {_when(allowance['designated_on'])}, so it's taxable "
                 f"salary (W-2 Box 1), not housing allowance.")
    return {"type": atype, "entry_id": entry["id"], "allowance_id": allowance["id"],
            "result": (f"Logged ${_num(entry['amount']):,.2f} of {what} on {entry['entry_date']} to "
                       f"{allowance['minister_name']}'s {allowance['tax_year']} housing allowance.{early} "
                       f"Paid since the vote {_money(f['paid_since_designation'])} of {_money(f['designated'])}; "
                       f"housing costs {_money(f['spent'])}."),
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
                                       "fair_rental_value", "board_decision_id", "notes", "minister_recused",
                                       "minister_credential", "se_tax_plan", "cash_salary", "w2_checked_on",
                                       *TRAIL_TEXT) if k in action}
    body.setdefault("tax_year", date.today().year)
    try:
        existing = [a for a in list_allowances(str(biz["id"]), int(body["tax_year"]))
                    if body.get("minister_name")
                    and a["minister_name"].lower() == str(body["minister_name"]).strip().lower()]
        if not existing and not body.get("minister_name"):
            # A paper-trail detail with no name: the year's only allowance.
            only, _ = _pick(str(biz["id"]), {"tax_year": body["tax_year"]})
            existing = [only] if only else []
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


def _short(d: Any) -> str:
    day = _day_or_none(d)
    return f"{day:%b} {day.day}" if day else str(d or "")


def _row_words(r: Dict[str, Any]) -> str:
    s = f"{_short(r['date'])} {_money(r.get('left', r['amount']))} \"{r['description']}\" id {r['transaction_id']}"
    if "left" in r:
        s += f" (what's left of {_money(r['amount'])})"
    if r.get("typed_in"):
        s += f" (same as the typed-in {_short(r['typed_in']['entry_date'])} payment)"
    if r.get("excluded"):
        s += " (excluded from the books)"
    return s


def _find_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "find_housing_payments"
    refused = _chief_gate(biz, atype)
    if refused:
        return refused
    words = action.get("words")
    words = [words] if isinstance(words, str) else words if isinstance(words, list) else None
    try:
        allowance, why = _pick(str(biz["id"]), action)
        if not allowance:
            return _fail(atype, why + ". Record the board's designation first (the amount and the day it voted)")
        data = find_bank_payments(str(biz["id"]), allowance["id"], words=words, amount=action.get("amount"))
    except HTTPException as e:
        return _fail(atype, str(e.detail))
    except Unavailable:
        return _fail(atype, "the bank rows couldn't be read just now. This is not 'none found'")
    who, year = allowance["minister_name"], data["tax_year"]
    if not data["accounts"]:
        text = ("No bank account is connected to the books, so there are no bank payments to look "
                "through. The owner can connect one under Bookkeeping, Transactions.")
    else:
        narrow = []
        if words:
            narrow.append("mentioning " + " or ".join(f'"{w}"' for w in words))
        if action.get("amount") not in (None, ""):
            narrow.append(f"of exactly {_money(_num(action['amount']))}")
        text = (f"{who}'s {year} housing allowance: {data['count']} payment(s) out of the bank "
                f"{' '.join(narrow) + ' ' if narrow else ''}aren't on its record yet, "
                f"{_money(data['total'])} in all.")
        if data["history_late"]:
            text += (f" The bank history in the app starts {_when(data['history_starts'])}, so payments before "
                     "then aren't here until the bank statements for those months are added (Bookkeeping, "
                     "Transactions, Statements); one can also be typed in from the statement (log_housing_entry).")
        if data["repeats"]:
            text += " Repeating (same amount, same description): " + "; ".join(
                f"{_money(g['amount'])} × {g['count']} ({', '.join(_short(d) for d in g['dates'])}), "
                f"\"{g['description']}\", transaction_ids {', '.join(g['transaction_ids'])}"
                for g in data["repeats"][:8]) + "."
        shown = data["rows"][:SHOW_ROWS]
        if shown:
            text += f" Newest {len(shown)} of {data['count']}: " + "; ".join(_row_words(r) for r in shown) + "."
    if data["typed_in"]["count"]:
        text += (f" Typed-in payments on the record, not tied to the bank yet: {data['typed_in']['count']} "
                 f"({_money(data['typed_in']['amount'])}).")
    return {"type": atype, "result": text, "label": "🏠 Housing payments in the bank",
            "allowance_id": allowance["id"], "count": data["count"], "total": data["total"],
            "note_for_chief": ("Candidates by amount and timing, not proof. Show them and ask which were housing "
                               "allowance; tie only the ones the owner confirms (attach_housing_payments). A "
                               "transfer that was the whole paycheck needs the housing part as its amount. "
                               "Quote the server's count and total; never add rows up yourself."),
            "nav": NAV}


def _attach_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    """Tie the bank payments the owner confirmed: one batch, one undo."""
    atype = "attach_housing_payments"
    refused = _chief_gate(biz, atype)
    if refused:
        return refused
    from chief_of_staff import _TURN_USER_ID
    items: List[Dict[str, Any]] = []
    for p in action.get("parts") or []:
        if isinstance(p, dict):
            items.append({"transaction_id": p.get("transaction_id"), "amount": p.get("amount")})
    each = action.get("amount_each")
    ids = action.get("transaction_ids")
    for tid in ([ids] if isinstance(ids, str) else ids or []):
        items.append({"transaction_id": tid, "amount": each})
    if not items:
        return _fail(atype, "say which bank payments (their transaction_ids from find_housing_payments)")
    try:
        allowance, why = _pick(str(biz["id"]), action)
        if not allowance:
            return _fail(atype, why)
        done = attach_bank_payments(str(biz["id"]), _TURN_USER_ID.get(), allowance["id"], items)
    except HTTPException as e:
        return _fail(atype, str(e.detail) + " Nothing was tied")
    except Unavailable:
        return _fail(atype, "the housing allowance records couldn't be read just now; nothing was tied")
    try:
        entries: Optional[List[Dict[str, Any]]] = entries_for(str(biz["id"]), allowance["id"])
    except Unavailable:
        entries = None   # tied all the same; only the new totals are unread
    rows = done["attached"]
    text = (f"Tied {len(rows)} bank payment(s), {_money(done['total'])}, to {allowance['minister_name']}'s "
            f"{allowance['tax_year']} housing allowance: "
            + "; ".join(f"{_short(r['date'])} {_money(r['amount'])}"
                        + (f" of {_money(r['bank_amount'])}" if r["amount"] < r["bank_amount"] else "")
                        for r in rows) + ".")
    twins = sum(1 for r in rows if r["was_typed_in"])
    if twins:
        text += f" {twins} of them were already typed in; those are now tied to their bank payment, not counted twice."
    vote = _day_or_none(allowance.get("designated_on"))
    early = [r for r in rows if vote and (_day_or_none(r["date"]) or vote) < vote]
    if early:
        text += (f" {len(early)} of them ({_money(round(sum(r['amount'] for r in early), 2))}) came before the "
                 f"board's vote on {_when(allowance['designated_on'])}, so that's taxable salary (W-2 Box 1), not "
                 "housing allowance.")
    if entries is None:
        text += " The new totals couldn't be read just now; the Housing tab will show them."
    else:
        f, src = figures(allowance, entries), sources(entries)
        text += (f" Paid since the vote {_money(f['paid_since_designation'])} of {_money(f['designated'])}; tied to "
                 f"the bank {_money(src['bank']['amount'])} of {_money(f['paid'])} paid.")
    return {"type": atype, "result": text, "label": f"🏠 Tied {len(rows)} bank payment(s) to housing",
            "allowance_id": allowance["id"], "created_ids": done["created_ids"], "restore": done["restore"],
            "attached": rows, "nav": NAV}


def _detach_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "detach_housing_payments"
    refused = _chief_gate(biz, atype)
    if refused:
        return refused
    try:
        done = detach_bank_payments(str(biz["id"]), action.get("entry_ids"), action.get("restore"))
    except HTTPException as e:
        return _fail(atype, str(e.detail))
    except Unavailable:
        return _fail(atype, "the housing allowance records couldn't be read just now; nothing changed")
    parts = []
    if done["removed"]:
        parts.append(f"removed {done['removed']} that came from the bank")
    if done["untied"]:
        parts.append(f"{done['untied']} are typed-in again, as they were")
    return {"type": atype, "result": ("Took those bank payments back: " + " and ".join(parts) + ".") if parts
            else "Nothing to take back: those payments were already changed or removed.",
            "label": "🏠 Took the bank payments back", "nav": NAV}


async def handle_find_housing_payments(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_find_sync, biz, action or {})


async def handle_attach_housing_payments(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_attach_sync, biz, action or {})


async def handle_detach_housing_payments(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_detach_sync, biz, action or {})


async def handle_housing_allowance_status(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_status_sync, biz, action or {})


async def handle_log_housing_entry(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_log_sync, biz, action or {})


async def handle_delete_housing_entry(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_delete_sync, biz, action or {})


async def handle_set_housing_allowance(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_set_sync, biz, action or {})
