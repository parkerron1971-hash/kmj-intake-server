"""
giving_deposits.py — the Sunday match: the gifts a church recorded, matched to
the bank deposits that carried them.

Kevin, 2026-10-31: everybody gives on Sunday (cash, check, card, Cash App),
each gift is recorded under the person, and the money reaches the bank over
Sunday, Monday and Tuesday; "everybody that tallied up to $650" should meet
the deposits that make $650, and Chief should recognize it. Then: "yes build
it but also make sure that chief can either do it for people, match what the
person does or verify. make sure that there is no duplicates."

    THE GIFTS ...... paid gifts (invoices.is_gift), by how they came:
                       plate ...... cash and check, grouped by the day given
                       online ..... Subsplash gifts, by the day given; the
                                    payout is their total less the fee
                                    Subsplash kept (written on each gift)
                       transfer ... Cash App, Zelle, PayPal and the like
                                    ('other', 'bank_transfer'), one by one
                     Card gifts through the app are Stripe's: their payouts
                     are matched by the payout matcher, not here
    THE DEPOSITS ... money in on the accounts in the books, still waiting for
                     an answer (no money_kind, not a Stripe payout)
    A MATCH ........ gifts and the deposit(s) that carried them; the deposits
                     add up to the gifts exactly, or (online) to the gifts less
                     the fee, which is booked as an expense (business_expenses,
                     "Giving platform fees"). The deposits become money_kind
                     'gifts': never income (the gifts are), never waiting
    NO DUPLICATES .. gift_deposit_items' primary key is (business, side, ref):
                     the database itself refuses a gift or a deposit in a
                     second match, whoever makes it; checked here first too
    THE THREE WAYS . Chief (or the screen's "Match what's clear") makes only
                     the clear matches, one batch, one undo; a person (or Chief
                     on a person's word) matches exactly the gifts and deposits
                     named; verify checks every match, whoever made it

The books (gl_engine): a non-card gift waits in 1160 Gifts to Deposit; a
matched deposit books Dr Cash, Cr 1160 for the deposit and its fee, and the
fee's expense row books Dr Operating Expenses, Cr Cash, so cash is the bank
and income is counted once. Who may: the Transactions screen's readers read
(plaid_router._require_reader, the church's finance gate and Giving wall
included); the owner alone matches and unmatches. Switched by GIVING_DEPOSITS:
off | owner | on, owner when unset. Tables:
supabase/APPLY-2026-10-31-giving-deposits.sql.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("giving_deposits")

router = APIRouter(prefix="/giving-deposits", tags=["giving-deposits"])

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_TX = re.compile(r"^[A-Za-z0-9_-]{1,120}$")

PLATE = ("cash", "check")
ONLINE = ("subsplash bank payout",)
STRIPE = ("stripe",)
PLATE_DAYS = (-1, 6)          # a plate deposit: the day before the gifts' day to six days after
ONLINE_DAYS = (0, 7)
TRANSFER_DAYS = 3
COMBO_MAX = 3
SUBSET_MAX = 4
FEE_SHARE_MAX = 0.10          # a platform keeps at most this much of a payout
CENT = 0.005
FEE_LABEL = "Giving platform fees"
NAV = {"tab": "operate", "sub": "bookkeeping", "bkTab": "giving"}

_ONLINE_WORDS = re.compile(r"subsplash", re.I)
_TRANSFER_WORDS = re.compile(r"cash ?app|moneysend|zelle|venmo|paypal", re.I)
_PLATE_WORDS = re.compile(r"brch|branch|\batm\b|\bdeposit\b|mobile dep|remote dep|counter", re.I)
_STRIPE_WORDS = re.compile(r"stripe", re.I)
_FEE_NOTE = re.compile(r"fee \$([\d,]+\.\d{2})", re.I)


class Unavailable(Exception):
    """A read or write failed: never shown as nothing."""


# ─── The switch and the gates ─────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("GIVING_DEPOSITS") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def switched_on(business_id: Any) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        import member_asks
        return member_asks.platform_church(business_id)
    return False


def ledger_gifts_wait(business_id: Any) -> bool:
    """For the ledger: does this business's non-card gift wait in 1160 Gifts to
    Deposit? Only where the Sunday match is on, since only there can a deposit
    clear it. Unlike switched_on, a read it can't make RAISES: the ledger then
    leaves the rows queued for its next run instead of re-posting every gift
    the other way on a blip."""
    m = mode()
    if m == "on":
        return True
    if m == "off":
        return False
    # "owner": the platform owner's churches, by the owner's user id (no
    # email lookup to blip on); only the church's own read can fail.
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(business_id)}&select=owner_id&limit=1")
    if not isinstance(rows, list):
        raise Unavailable("businesses")
    if not rows or not rows[0].get("owner_id"):
        return False
    from chief_of_staff import PLATFORM_OWNER_ID
    return str(rows[0]["owner_id"]) == str(PLATFORM_OWNER_ID)


def _gate(business_id: str, user: Any, *, write: bool) -> Dict[str, Any]:
    if not business_id or not _UUID.match(str(business_id)):
        raise HTTPException(400, "business_id must be a uuid")
    if not switched_on(business_id):
        raise HTTPException(404, "Not Found")
    import plaid_router
    return (plaid_router._require_owner if write else plaid_router._require_reader)(business_id, user)


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _get(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if rows is None:
        raise Unavailable(path.split("?")[0])
    return rows


def _all(path: str) -> List[Dict[str, Any]]:
    import bank_picks
    try:
        return bank_picks.read_all(path, _get)
    except bank_picks.TooMany as e:
        raise Unavailable(str(e))


def _c(v: Any) -> int:
    """Money as cents: every sum and comparison here is in whole cents."""
    try:
        return int(round(float(v or 0) * 100))
    except (TypeError, ValueError):
        return 0


def _d(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def _money(cents: int) -> str:
    return f"{'-' if cents < 0 else ''}${abs(cents) / 100:,.2f}"


def _day(d: Any) -> str:
    x = d if isinstance(d, date) else _d(d)
    return f"{x.strftime('%a %b')} {x.day}" if x else str(d or "")


# ─── Reading ──────────────────────────────────────────────────────────

def gift_kind(method: Any) -> Optional[str]:
    m = str(method or "").strip().lower()
    if m in STRIPE or "stripe" in m or "card" in m:
        return None                      # Stripe's payouts carry these
    if m in PLATE:
        return "plate"
    if m in ONLINE:
        return "online"
    return "transfer"


def deposit_channel(name: str) -> str:
    n = name or ""
    if _STRIPE_WORDS.search(n):
        return "stripe"
    if _ONLINE_WORDS.search(n):
        return "online"
    if _TRANSFER_WORDS.search(n):
        return "transfer"
    if _PLATE_WORDS.search(n):
        return "plate"
    return "other"


def gifts(business_id: str, start: date, end: date) -> List[Dict[str, Any]]:
    """Paid non-card gifts in [start, end], each with what reaches the bank."""
    import giving_records
    try:
        rows = giving_records.read_gifts(business_id, f"{start.isoformat()}T00:00:00Z",
                                         f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z")
    except HTTPException:
        raise Unavailable("invoices")
    return [g for g in (_gift_row(r) for r in rows) if g]


def _gift_row(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A paid gift as the match sees it; None for a card gift or one refunded."""
    if r.get("is_gift") is False or (r.get("status") and r.get("status") != "paid"):
        return None
    kind = gift_kind(r.get("payment_method"))
    if kind is None:
        return None
    total = _c(r.get("total")) - int(r.get("refund_amount_cents") or 0)
    if total <= 0:
        return None                          # refunded: nothing to deposit
    fee = 0
    if kind == "online":
        m = _FEE_NOTE.search(str(r.get("notes") or ""))
        fee = _c(m.group(1).replace(",", "")) if m else 0
    contact = r.get("contacts") or {}
    return {"id": str(r["id"]), "kind": kind, "date": str(r.get("paid_at") or "")[:10],
            "cents": total, "fee": min(fee, total), "method": r.get("payment_method"),
            "count": str(r["giving_count_id"]) if r.get("giving_count_id") else None,
            "giver": (contact.get("name") if isinstance(contact, dict) else None) or "No giver"}


def _dep_row(t: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A bank row as the match sees it; None when it isn't money in the books."""
    import bank_picks
    if t.get("pending") or t.get("excluded_from_books") or _c(t.get("amount")) >= 0:
        return None
    name = bank_picks.words(t)
    return {"id": str(t["transaction_id"]), "date": str(t.get("date") or "")[:10],
            "cents": -_c(t.get("amount")), "name": name, "channel": deposit_channel(name),
            "money_kind": t.get("money_kind"),
            "waiting": not t.get("money_kind") and not t.get("reconciled_to_payout_id")}


_DEP_SELECT = ("transaction_id,date,amount,name,merchant_name,money_kind,reconciled_to_payout_id,gift_match_fee,"
               "pending,excluded_from_books")


def deposits(business_id: str, start: date, end: date) -> List[Dict[str, Any]]:
    """Money in on the books' accounts, cleared, from start to end."""
    import bank_picks
    accts = bank_picks.accounts(business_id, _get)
    if not accts:
        return []
    rows = _all(f"/plaid_transactions?business_id=eq.{_q(business_id)}&account_id={bank_picks.in_(accts)}"
                f"&amount=lt.0&pending=eq.false&excluded_from_books=eq.false"
                f"&date=gte.{start.isoformat()}&date=lte.{end.isoformat()}"
                f"&select={_DEP_SELECT}&order=date.asc,transaction_id.asc")
    return [d for d in (_dep_row(t) for t in rows) if d]


def _by_ids(business_id: str, gift_ids: List[str], deposit_ids: List[str]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A match's own gifts and deposits as they are now, wherever they fall;
    one missing or no longer counted maps to None."""
    import giving_records
    gs: Dict[str, Any] = {x: None for x in gift_ids}
    ds: Dict[str, Any] = {x: None for x in deposit_ids}
    for i in range(0, len(gift_ids), 100):
        part = gift_ids[i:i + 100]
        for r in _get(f"/invoices?business_id=eq.{_q(business_id)}&id=in.({','.join(_q(x) for x in part)})"
                      f"&select={giving_records.GIFT_FIELDS},status&limit=1000"):
            gs[str(r["id"])] = _gift_row(r)
    for i in range(0, len(deposit_ids), 100):
        part = deposit_ids[i:i + 100]
        for t in _get(f"/plaid_transactions?business_id=eq.{_q(business_id)}"
                      f"&transaction_id=in.({','.join(_q(x) for x in part)})&select={_DEP_SELECT}&limit=1000"):
            ds[str(t["transaction_id"])] = _dep_row(t)
    return gs, ds


def matches(business_id: str) -> List[Dict[str, Any]]:
    ms = _all(f"/gift_deposit_matches?business_id=eq.{_q(business_id)}"
              "&select=id,kind,gifts_total,deposits_total,fee,fee_expense_id,made_by,batch_id,note,created_at"
              "&order=created_at.asc,id.asc")
    items = _all(f"/gift_deposit_items?business_id=eq.{_q(business_id)}"
                 "&select=match_id,side,ref,amount&order=match_id.asc,side.asc,ref.asc")
    by: Dict[str, Dict[str, Any]] = {str(m["id"]): {**m, "gifts": [], "deposits": []} for m in ms}
    for i in items:
        m = by.get(str(i.get("match_id")))
        if m is not None:
            m["gifts" if i.get("side") == "gift" else "deposits"].append(
                {"ref": str(i["ref"]), "cents": _c(i.get("amount"))})
    return list(by.values())


# ─── The clear matches (pure) ─────────────────────────────────────────

def _within(d: str, base: str, days: Tuple[int, int]) -> bool:
    a, b = _d(d), _d(base)
    return bool(a and b and days[0] <= (a - b).days <= days[1])


def _unique_combo(cands: List[Dict[str, Any]], target: int, sizes: Iterable[int]) -> Optional[List[Dict[str, Any]]]:
    """The one set of candidates (smallest size first) that adds to target; None
    when none does or more than one does (that's for a person)."""
    for k in sizes:
        found = [c for c in itertools.combinations(cands, k) if sum(x["cents"] for x in c) == target]
        if len(found) == 1:
            return list(found[0])
        if len(found) > 1:
            return None
    return None


def _proposal(kind: str, gs: List[Dict[str, Any]], ds: List[Dict[str, Any]], why: str) -> Dict[str, Any]:
    gross = sum(g["cents"] for g in gs)
    dep = sum(d["cents"] for d in ds)
    return {"kind": kind, "gifts": [g["id"] for g in gs], "deposits": [d["id"] for d in ds],
            "gifts_cents": gross, "deposits_cents": dep, "fee_cents": gross - dep,
            "date": min(g["date"] for g in gs), "why": why}


def plan(gs: List[Dict[str, Any]], ds: List[Dict[str, Any]],
         counts: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """The clear matches among unmatched gifts and waiting deposits. Each gift
    and each deposit is used at most once; anything ambiguous is left.
    `counts`: closed service counts by id ({name, date}), whose cash and
    checks are tried first, as one deposit slip (giving_services)."""
    used_d: set = set()
    used_g: set = set()
    out: List[Dict[str, Any]] = []

    def free(kind_ch: str) -> List[Dict[str, Any]]:
        return [d for d in ds if d["id"] not in used_d and d["channel"] == kind_ch]

    def take(p: Dict[str, Any]) -> None:
        used_g.update(p["gifts"])
        used_d.update(p["deposits"])
        out.append(p)

    def by_day(kind: str) -> List[Tuple[str, List[Dict[str, Any]]]]:
        days: Dict[str, List[Dict[str, Any]]] = {}
        for g in gs:
            if g["kind"] == kind and g["id"] not in used_g:
                days.setdefault(g["date"], []).append(g)
        return sorted(days.items())

    # A closed service count: the counters' cash and checks, as one slip.
    by_count: Dict[str, List[Dict[str, Any]]] = {}
    for g in gs:
        if g["kind"] == "plate" and g.get("count") in (counts or {}):
            by_count.setdefault(g["count"], []).append(g)
    for cid, group in sorted(by_count.items(), key=lambda kv: min(g["date"] for g in kv[1])):
        day = min(g["date"] for g in group)
        total = sum(g["cents"] for g in group)
        cands = [d for d in free("plate") if _within(d["date"], day, PLATE_DAYS)]
        combo = _unique_combo(cands, total, range(1, COMBO_MAX + 1))
        if combo:
            c = (counts or {})[cid]
            take(_proposal("plate", group, combo, f"{c.get('name') or 'The service'}, {_day(day)}: "
                                                  f"the counted cash and checks, {_money(total)}"))
    # Plate: a day's cash and check, in one to three deposits soon after.
    for day, group in by_day("plate"):
        total = sum(g["cents"] for g in group)
        cands = [d for d in free("plate") if _within(d["date"], day, PLATE_DAYS)]
        combo = _unique_combo(cands, total, range(1, COMBO_MAX + 1))
        if combo:
            take(_proposal("plate", group, combo, f"{_day(day)}'s cash and check, {_money(total)}"))
    # Two Sundays deposited together.
    days = by_day("plate")
    for (d1, g1), (d2, g2) in zip(days, days[1:]):
        if not (set(g["id"] for g in g1) | set(g["id"] for g in g2)).isdisjoint(used_g):
            continue
        if (_d(d2) - _d(d1)).days > 8:
            continue
        total = sum(g["cents"] for g in g1 + g2)
        cands = [d for d in free("plate") if _within(d["date"], d2, PLATE_DAYS)]
        combo = _unique_combo(cands, total, (1,))
        if combo:
            take(_proposal("plate", g1 + g2, combo, f"{_day(d1)} and {_day(d2)}'s cash and check together"))

    # Online: a day's gifts less their fees, in one payout within a week;
    # else a run of consecutive days paid out together.
    for day, group in by_day("online"):
        net = sum(g["cents"] - g["fee"] for g in group)
        hits = [d for d in free("online") if _within(d["date"], day, ONLINE_DAYS) and d["cents"] == net]
        if len(hits) == 1:
            take(_proposal("online", group, hits, f"{_day(day)}'s online gifts less the platform's fee"))
    for dep in sorted(free("online"), key=lambda d: d["date"]):
        days = [(day, group) for day, group in by_day("online") if _within(dep["date"], day, ONLINE_DAYS)]
        runs = []
        for i in range(len(days)):
            for j in range(i + 1, len(days)):
                run = days[i:j + 1]
                if sum(g["cents"] - g["fee"] for _, grp in run for g in grp) == dep["cents"]:
                    runs.append(run)
        if len(runs) == 1:
            group = [g for _, grp in runs[0] for g in grp]
            take(_proposal("online", group, [dep], f"online gifts {_day(runs[0][0][0])} to "
                                                   f"{_day(runs[0][-1][0])} less the platform's fee"))

    # Transfer: one gift, one deposit of the same amount within days; then a
    # deposit that carries a few gifts at once.
    tgifts = [g for g in gs if g["kind"] == "transfer" and g["id"] not in used_g]
    for g in tgifts:
        if g["id"] in used_g:
            continue
        cands = [d for d in free("transfer") if d["cents"] == g["cents"] and _within(d["date"], g["date"], (-TRANSFER_DAYS, TRANSFER_DAYS))]
        if len(cands) != 1:
            continue
        back = [x for x in tgifts if x["id"] not in used_g and x["cents"] == cands[0]["cents"]
                and _within(cands[0]["date"], x["date"], (-TRANSFER_DAYS, TRANSFER_DAYS))]
        if len(back) == 1:
            take(_proposal("transfer", [g], cands, f"{g['giver']}'s {_money(g['cents'])}"))
    for dep in sorted(free("transfer"), key=lambda d: d["date"]):
        cands = [g for g in tgifts if g["id"] not in used_g and _within(dep["date"], g["date"], (0, 7))]
        combo = _unique_combo(cands, dep["cents"], range(2, SUBSET_MAX + 1)) if len(cands) <= 12 else None
        if combo:
            take(_proposal("transfer", combo, [dep], f"{len(combo)} transfer gifts in one deposit"))
    return out


# ─── Writing a match ──────────────────────────────────────────────────

def _locked(business_id: str, day: str) -> Optional[str]:
    try:
        import period_lock
        p = period_lock.locked_period(business_id, day)
    except Exception:
        raise Unavailable("accounting_periods")
    if p:
        return f"{p.get('period_start')} to {p.get('period_end')}"
    return None


def check_match(gs: List[Dict[str, Any]], ds: List[Dict[str, Any]], taken: set) -> Tuple[Optional[str], int]:
    """Why these can't be one match (None when they can), and the fee in cents."""
    if not gs or not ds:
        return "a match needs at least one gift and one deposit", 0
    for g in gs:
        if ("gift", g["id"]) in taken:
            return f"{g['giver']}'s {_money(g['cents'])} gift on {_day(g['date'])} is already matched", 0
    for d in ds:
        if ("deposit", d["id"]) in taken or d.get("money_kind") == "gifts":
            return f"the {_money(d['cents'])} deposit on {_day(d['date'])} is already matched", 0
        if not d.get("waiting"):
            return (f"the {_money(d['cents'])} deposit on {_day(d['date'])} already has an answer "
                    "(income, a transfer, a payout...); clear it on the Transactions screen first"), 0
    gross = sum(g["cents"] for g in gs)
    dep = sum(d["cents"] for d in ds)
    online = all(g["kind"] == "online" for g in gs)
    if dep == gross:
        return None, 0
    if online and 0 < gross - dep <= gross * FEE_SHARE_MAX:
        return None, gross - dep            # the platform's fee
    if dep > gross:
        return (f"the deposits ({_money(dep)}) are more than the gifts ({_money(gross)}): "
                f"{_money(dep - gross)} of gifts may not be recorded yet"), 0
    return (f"the deposits ({_money(dep)}) are less than the gifts ({_money(gross)}): "
            f"{_money(gross - dep)} may not be deposited yet, or a gift is recorded twice"), 0


def _take_back(business_id: str, match_id: str, expense_id: Optional[str] = None) -> None:
    if not _drop(business_id, match_id, expense_id):
        raise HTTPException(503, "That match didn't finish, and part of it couldn't be taken back. It shows under "
                                 "Deposits as a match that doesn't check out; unmatch it there.")


def write_match(business_id: str, gs: List[Dict[str, Any]], ds: List[Dict[str, Any]], *, fee: int,
                made_by: str, user_id: Any, batch_id: Optional[str] = None, note: str = "") -> Dict[str, Any]:
    """One match, all or nothing: the record, its items (the primary key
    refuses a gift or deposit already in a match), the fee's expense row and
    the deposits marked 'gifts'."""
    for d in ds:
        span = _locked(business_id, d["date"])
        if span:
            raise HTTPException(409, f"the deposit on {_day(d['date'])} is in a closed month ({span}); "
                                     "reopen it to match")
    kind = gs[0]["kind"] if len({g["kind"] for g in gs}) == 1 else "mixed"
    made = sb_clients.sb_post_as_service("/gift_deposit_matches", {
        "business_id": business_id, "kind": kind, "gifts_total": sum(g["cents"] for g in gs) / 100,
        "deposits_total": sum(d["cents"] for d in ds) / 100, "fee": fee / 100, "made_by": made_by,
        "made_by_user": str(user_id) if user_id else None, "batch_id": batch_id, "note": note[:300] or None})
    m = (made[0] if isinstance(made, list) and made else made) if made else None
    if not isinstance(m, dict) or not m.get("id"):
        raise Unavailable("gift_deposit_matches")
    mid = str(m["id"])
    items = ([{"business_id": business_id, "match_id": mid, "side": "gift", "ref": g["id"], "amount": g["cents"] / 100}
              for g in gs] +
             [{"business_id": business_id, "match_id": mid, "side": "deposit", "ref": d["id"], "amount": d["cents"] / 100}
              for d in ds])
    if not sb_clients.sb_post_as_service("/gift_deposit_items", items):
        _take_back(business_id, mid)
        raise HTTPException(409, "one of those gifts or deposits was matched a moment ago; nothing changed")
    expense_id = None
    if fee:
        last = max(ds, key=lambda d: d["date"])
        ex = sb_clients.sb_post_as_service("/business_expenses", {
            "business_id": business_id, "amount": fee / 100, "category": "operating", "subcategory": FEE_LABEL,
            "vendor": "Subsplash", "date": last["date"],
            "description": f"Fees kept from the {_day(last['date'])} payout ({len(gs)} gifts)"})
        e = (ex[0] if isinstance(ex, list) and ex else ex) if ex else None
        if not isinstance(e, dict) or not e.get("id"):
            _take_back(business_id, mid)
            raise Unavailable("business_expenses")
        expense_id = str(e["id"])
        sb_clients.sb_patch_as_service(f"/gift_deposit_matches?id=eq.{_q(mid)}&business_id=eq.{_q(business_id)}",
                                       {"fee_expense_id": expense_id})
    stamp = datetime.now(timezone.utc).isoformat()
    for n, d in enumerate(sorted(ds, key=lambda d: d["date"])):
        share = fee if n == len(ds) - 1 else 0          # the fee rides on the last deposit
        res = sb_clients.sb_patch_as_service(
            f"/plaid_transactions?business_id=eq.{_q(business_id)}&transaction_id=eq.{_q(d['id'])}"
            "&money_kind=is.null&reconciled_to_payout_id=is.null",
            {"money_kind": "gifts", "gift_match_fee": share / 100, "updated_at": stamp})
        if not res:
            _take_back(business_id, mid, expense_id)
            if res is None:
                raise Unavailable("plaid_transactions")
            raise HTTPException(409, f"the deposit on {_day(d['date'])} was answered a moment ago; nothing changed")
    return {"id": mid, "kind": kind, "gifts": [g["id"] for g in gs], "deposits": [d["id"] for d in ds],
            "gifts_cents": sum(g["cents"] for g in gs), "deposits_cents": sum(d["cents"] for d in ds),
            "fee_cents": fee, "made_by": made_by}


def _drop(business_id: str, match_id: str, expense_id: Optional[str] = None) -> bool:
    """A match undone: its deposits waiting again, its fee row gone, its
    record and items gone. Each step is guarded, so running it twice is safe."""
    deps = _get(f"/gift_deposit_items?business_id=eq.{_q(business_id)}&match_id=eq.{_q(match_id)}"
                "&side=eq.deposit&select=ref")
    ok = True
    for d in deps:
        res = sb_clients.sb_patch_as_service(
            f"/plaid_transactions?business_id=eq.{_q(business_id)}&transaction_id=eq.{_q(d['ref'])}"
            "&money_kind=eq.gifts", {"money_kind": None, "gift_match_fee": 0,
                                     "updated_at": datetime.now(timezone.utc).isoformat()})
        ok = ok and res is not None
    if expense_id:
        ok = sb_clients.sb_delete_as_service(
            f"/business_expenses?id=eq.{_q(expense_id)}&business_id=eq.{_q(business_id)}") and ok
    if ok:
        ok = sb_clients.sb_delete_as_service(
            f"/gift_deposit_matches?id=eq.{_q(match_id)}&business_id=eq.{_q(business_id)}")
    return bool(ok)


def unmatch(business_id: str, match_ids: List[str]) -> Dict[str, Any]:
    have = {m["id"]: m for m in matches(business_id)}
    done, missing = 0, 0
    for mid in match_ids:
        m = have.get(str(mid))
        if not m:
            missing += 1
            continue
        if not _drop(business_id, str(mid), m.get("fee_expense_id")):
            raise Unavailable("gift_deposit_matches")
        done += 1
    return {"unmatched": done, "missing": missing}


# ─── The picture, and verifying it ────────────────────────────────────

def _window(year: Optional[int], start: Any, end: Any) -> Tuple[date, date]:
    s, e = _d(start), _d(end)
    if not (s and e):
        y = int(year or date.today().year)
        s, e = date(y, 1, 1), min(date(y, 12, 31), date.today())
    if e < s or (e - s).days > 400:
        raise HTTPException(422, "Pick a range of a year or less.")
    return s, e


def verify(business_id: str, ms: List[Dict[str, Any]], g_by: Dict[str, Dict[str, Any]],
           d_by: Dict[str, Dict[str, Any]], expenses: Dict[str, int]) -> List[Dict[str, Any]]:
    """Every match, whoever made it, against what the gifts and deposits are now."""
    out = []
    for m in ms:
        why = []
        for g in m["gifts"]:
            now = g_by.get(g["ref"])
            if now is None:
                why.append("a gift in it is gone, refunded, or changed to card")
            elif now["cents"] != g["cents"]:
                why.append(f"{now['giver']}'s gift changed from {_money(g['cents'])} to {_money(now['cents'])}")
        for d in m["deposits"]:
            now = d_by.get(d["ref"])
            if now is None:
                why.append("a deposit in it is no longer in the books")
            elif now.get("money_kind") != "gifts":
                why.append(f"the {_money(d['cents'])} deposit on {_day(now['date'])} was given another answer")
            elif now["cents"] != d["cents"]:
                why.append(f"the deposit on {_day(now['date'])} changed to {_money(now['cents'])}")
        gross = sum(g["cents"] for g in m["gifts"])
        dep = sum(d["cents"] for d in m["deposits"])
        fee = _c(m.get("fee"))
        if gross != dep + fee:
            why.append(f"the gifts ({_money(gross)}) aren't the deposits ({_money(dep)}) and the fee ({_money(fee)})")
        if fee and expenses.get(str(m.get("fee_expense_id"))) != fee:
            why.append("its fee's expense row is missing or changed")
        if why:
            out.append({"match_id": m["id"], "made_by": m.get("made_by"), "problems": why})
    return out


def _closed_counts(business_id: str, gs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """The closed service counts these gifts sit in, by id ({name, date})."""
    ids = sorted({g["count"] for g in gs if g.get("count") and g["kind"] == "plate"})
    out: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(ids), 100):
        for r in _get(f"/giving_counts?business_id=eq.{_q(business_id)}&status=eq.closed"
                      f"&id=in.({','.join(_q(x) for x in ids[i:i + 100])})&select=id,name,service_date&limit=100"):
            out[str(r["id"])] = {"name": r.get("name"), "date": str(r.get("service_date"))[:10]}
    return out


def status(business_id: str, *, year: Optional[int] = None, start: Any = None, end: Any = None) -> Dict[str, Any]:
    s, e = _window(year, start, end)
    # Two weeks early too: a Sunday's gifts before the range can ride in a
    # deposit inside it, and that match is checked against them.
    gs = gifts(business_id, s - timedelta(days=14), e)
    in_s = [g for g in gs if g["date"] >= s.isoformat()]
    ds = deposits(business_id, s - timedelta(days=3), min(e + timedelta(days=10), date.today()))
    ms = matches(business_id)
    taken = {(side, i["ref"]) for m in ms for side, key in (("gift", "gifts"), ("deposit", "deposits"))
             for i in m[key]}
    g_by = {g["id"]: g for g in gs}
    d_by = {d["id"]: d for d in ds}
    open_g = [g for g in gs if ("gift", g["id"]) not in taken]
    open_d = [d for d in ds if d["waiting"] and ("deposit", d["id"]) not in taken]
    proposals = plan(open_g, open_d, _closed_counts(business_id, open_g))
    fee_ids = [str(m["fee_expense_id"]) for m in ms if m.get("fee_expense_id")]
    expenses: Dict[str, int] = {}
    for i in range(0, len(fee_ids), 100):
        for r in _get(f"/business_expenses?business_id=eq.{_q(business_id)}&id=in.({','.join(_q(x) for x in fee_ids[i:i + 100])})"
                      "&select=id,amount&limit=1000"):
            expenses[str(r["id"])] = _c(r.get("amount"))
    in_range = [m for m in ms if any(g["ref"] in g_by for g in m["gifts"]) or any(d["ref"] in d_by for d in m["deposits"])]
    # Verify reads each match's own rows: one outside the window is never "gone".
    vg, vd = _by_ids(business_id, sorted({g["ref"] for m in in_range for g in m["gifts"] if g["ref"] not in g_by}),
                     sorted({d["ref"] for m in in_range for d in m["deposits"] if d["ref"] not in d_by}))
    g_all = {**{k: v for k, v in vg.items()}, **g_by}
    d_all = {**{k: v for k, v in vd.items()}, **d_by}
    proposed_g = {gid for p in proposals for gid in p["gifts"]}
    proposed_d = {did for p in proposals for did in p["deposits"]}
    waiting_g = [g for g in open_g if g["id"] not in proposed_g]
    giving_d = [d for d in open_d if d["id"] not in proposed_d and d["channel"] in ("plate", "online", "transfer")]
    return {
        "from": s.isoformat(), "to": e.isoformat(),
        "matched": [{**m, "gifts_cents": sum(g["cents"] for g in m["gifts"]),
                     "deposits_cents": sum(d["cents"] for d in m["deposits"]),
                     "deposit_rows": [d_all.get(d["ref"]) for d in m["deposits"] if d_all.get(d["ref"])]}
                    for m in in_range],
        "proposals": [{**p, "gift_rows": [g_by[x] for x in p["gifts"]], "deposit_rows": [d_by[x] for x in p["deposits"]]}
                      for p in proposals],
        "waiting_gifts": waiting_g, "giving_deposits": giving_d,
        "problems": verify(business_id, in_range, g_all, d_all, expenses),
        "totals": {"gifts": sum(g["cents"] for g in in_s) / 100,
                   "matched": sum(g["cents"] for m in in_range for g in m["gifts"]
                                  if g_by.get(g["ref"], {}).get("date", "") >= s.isoformat()) / 100,
                   "waiting": sum(g["cents"] for g in waiting_g) / 100},
    }


# ─── Doing it: clear matches, or exactly what a person names ──────────

def match_clear(business_id: str, user_id: Any, *, year: Optional[int] = None, start: Any = None,
                end: Any = None, made_by: str = "chief") -> Dict[str, Any]:
    st = status(business_id, year=year, start=start, end=end)
    batch = uuid.uuid4().hex
    done, skipped = [], []
    g_by = {g["id"]: g for p in st["proposals"] for g in p["gift_rows"]}
    d_by = {d["id"]: d for p in st["proposals"] for d in p["deposit_rows"]}
    for p in st["proposals"]:
        try:
            done.append(write_match(business_id, [g_by[x] for x in p["gifts"]], [d_by[x] for x in p["deposits"]],
                                    fee=p["fee_cents"], made_by=made_by, user_id=user_id, batch_id=batch,
                                    note=p["why"]))
        except HTTPException as e:
            skipped.append(f"{p['why']}: {e.detail}")
        except Unavailable:
            skipped.append(f"{p['why']}: couldn't be saved just now; ask again for it")
    return {"batch_id": batch if done else None, "matched": done, "skipped": skipped, "status": st}


def match_named(business_id: str, user_id: Any, gift_ids: List[str], deposit_ids: List[str], *,
                made_by: str = "person", note: str = "", batch_id: Optional[str] = None) -> Dict[str, Any]:
    """Exactly the gifts and deposits a person named, checked first."""
    gift_ids = [g for g in dict.fromkeys(str(x) for x in gift_ids) if _UUID.match(g)]
    deposit_ids = [d for d in dict.fromkeys(str(x) for x in deposit_ids) if _TX.match(d)]
    if not gift_ids or not deposit_ids:
        raise HTTPException(422, "Name the gifts and the deposit(s) that carried them.")
    found_g = _get(f"/invoices?business_id=eq.{_q(business_id)}&id=in.({','.join(gift_ids)})"
                   "&select=id,paid_at&limit=1000")
    days = sorted(str(r.get("paid_at") or "")[:10] for r in found_g if r.get("paid_at"))
    if len(found_g) != len(gift_ids) or not days:
        raise HTTPException(422, "Some of those gifts aren't this church's paid gifts.")
    s, e = _d(days[0]), _d(days[-1])
    gs = {g["id"]: g for g in gifts(business_id, s, e)}
    missing = [x for x in gift_ids if x not in gs]
    if missing:
        raise HTTPException(422, "Some of those gifts are card gifts (Stripe matches those), or refunded.")
    found_d = _get(f"/plaid_transactions?business_id=eq.{_q(business_id)}&transaction_id=in.({','.join(deposit_ids)})"
                   "&select=date&limit=1000")
    ddays = sorted(str(r.get("date") or "")[:10] for r in found_d)
    if len(found_d) != len(deposit_ids):
        raise HTTPException(422, "Some of those deposits aren't this church's bank rows.")
    ds = {d["id"]: d for d in deposits(business_id, _d(ddays[0]), _d(ddays[-1]))}
    if any(x not in ds for x in deposit_ids):
        raise HTTPException(422, "Some of those aren't deposits in the books (money in, cleared).")
    taken = {(side, i["ref"]) for m in matches(business_id) for side, key in (("gift", "gifts"), ("deposit", "deposits"))
             for i in m[key]}
    G, D = [gs[x] for x in gift_ids], [ds[x] for x in deposit_ids]
    why, fee = check_match(G, D, taken)
    if why:
        raise HTTPException(409, f"Not matched: {why}.")
    return write_match(business_id, G, D, fee=fee, made_by=made_by, user_id=user_id, note=note, batch_id=batch_id)


# ─── Routes ───────────────────────────────────────────────────────────

def _guard(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except Unavailable:
        raise HTTPException(503, "The giving deposits can't be read just now. If this is new, its database tables "
                                 "may not be set up yet.")


class MatchBody(BaseModel):
    business_id: str
    clear: bool = False
    year: Optional[int] = Field(default=None, ge=2000, le=2100)
    gift_ids: List[str] = Field(default_factory=list, max_length=500)
    deposit_ids: List[str] = Field(default_factory=list, max_length=20)
    note: str = Field(default="", max_length=300)


@router.get("")
def get_status(business_id: str = Query(...), year: Optional[int] = Query(None, ge=2000, le=2100),
               user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    row = _gate(business_id, user, write=False)
    return {"ok": True, "can_change": str(row.get("owner_id")) == str(user.id),
            **_guard(status, business_id, year=year)}


@router.post("/match")
def post_match(body: MatchBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _gate(body.business_id, user, write=True)
    if body.clear:
        got = _guard(match_clear, body.business_id, user.id, year=body.year, made_by="person")
        got.pop("status", None)
        return {"ok": True, **got}
    return {"ok": True, "match": _guard(match_named, body.business_id, user.id, body.gift_ids, body.deposit_ids,
                                        note=body.note)}


@router.delete("/{match_id}")
def delete_match(match_id: str, business_id: str = Query(...), user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _gate(business_id, user, write=True)
    if not _UUID.match(match_id):
        raise HTTPException(404, "That match isn't here.")
    got = _guard(unmatch, business_id, [match_id])
    if not got["unmatched"]:
        raise HTTPException(404, "That match isn't here.")
    return {"ok": True, **got}


# ─── Chief ────────────────────────────────────────────────────────────

STATUS_TOOL = {
    "name": "giving_deposits",
    "description": (
        "The Sunday match: this church's recorded gifts (cash and check by the day given, online gifts, Cash App "
        "and other transfers) against the bank deposits that carried them. Gives the matches made (and by whom), "
        "the clear matches ready to make, gifts not yet matched to a deposit, giving deposits not matched, and "
        "VERIFY: every existing match checked against what the gifts and deposits are now. Use it for 'did "
        "Sunday's giving make it to the bank', 'match the deposits', 'check the matching'. Quote its figures."),
    "input_schema": {"type": "object", "properties": {
        "year": {"type": "integer", "description": "Optional. Default: this year."}}},
}


def _fail(atype: str, msg: str) -> Dict[str, Any]:
    return {"type": atype, "result": f"Failed: {msg}", "label": msg[:80], "failed": True, "nav": NAV}


def _chief(biz: Dict[str, Any], atype: str, *, write: bool) -> Tuple[Optional[Dict[str, Any]], Any]:
    from chief_of_staff import _TURN_USER_ID
    uid = _TURN_USER_ID.get()
    if not uid:
        return _fail(atype, "the giving deposits are read only for a signed-in person who can see the books"), None
    try:
        _gate(str(biz["id"]), SimpleNamespace(id=uid), write=write)
    except HTTPException as e:
        if e.status_code == 404:
            return _fail(atype, "the Sunday match isn't switched on for this business yet"), None
        if write and e.status_code == 403 and not isinstance(e.detail, dict):
            return _fail(atype, "only the owner matches gifts to deposits"), None
        detail = e.detail.get("message") if isinstance(e.detail, dict) else e.detail
        return _fail(atype, str(detail or "this login can't see the books")), None
    return None, uid


def _status_text(st: Dict[str, Any]) -> str:
    t = st["totals"]
    bits = [f"{_money(_c(t['gifts']))} of gifts recorded (cash, check, online, transfers) from "
            f"{_day(st['from'])} to {_day(st['to'])}: {_money(_c(t['matched']))} matched to deposits"]
    if st["proposals"]:
        bits.append(f"{len(st['proposals'])} clear matches ready to make (" + "; ".join(
            f"{p['why']} → {len(p['deposits'])} deposit(s) {_money(p['deposits_cents'])}"
            + (f", fee {_money(p['fee_cents'])}" if p["fee_cents"] else "") for p in st["proposals"][:5]) + ")")
    if st["waiting_gifts"]:
        bits.append(f"{_money(_c(t['waiting']))} in {len(st['waiting_gifts'])} gifts with no clear deposit yet")
    if st["giving_deposits"]:
        bits.append(f"{len(st['giving_deposits'])} giving deposits with no clear gifts ("
                    + "; ".join(f"{_day(d['date'])} {_money(d['cents'])} {d['name'][:30]}" for d in st["giving_deposits"][:4]) + ")")
    bits.append(f"verified: {len(st['problems'])} problem(s)" if st["problems"] else "every match verified")
    return ". ".join(bits) + "."


def _status_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "giving_deposits"
    refused, _ = _chief(biz, atype, write=False)
    if refused:
        return refused
    try:
        st = status(str(biz["id"]), year=action.get("year"))
    except (Unavailable, HTTPException, ValueError, TypeError):
        return _fail(atype, "the giving deposits couldn't be read just now (if this is new, its tables may not be "
                            "set up yet). This is not 'nothing to match'")
    return {"type": atype, "result": _status_text(st), "label": "Sunday match",
            "proposals": [{k: p[k] for k in ("why", "gifts", "deposits", "gifts_cents", "deposits_cents", "fee_cents")}
                          for p in st["proposals"][:30]],
            "waiting_gifts": [{k: g[k] for k in ("id", "date", "kind", "cents", "giver")} for g in st["waiting_gifts"][:40]],
            "giving_deposits": [{k: d[k] for k in ("id", "date", "cents", "name")} for d in st["giving_deposits"][:40]],
            "problems": st["problems"][:20],
            "note_for_chief": ("Amounts are in cents. To make the clear matches, match_giving_deposits with no items. "
                               "To match what the owner says, name the gift ids and deposit ids. Report problems "
                               "plainly; never fix a person's match without asking."),
            "nav": NAV}


COLUMNS = [{"key": "date", "label": "Gifts of", "kind": "date"}, {"key": "what", "label": "What", "kind": "text"},
           {"key": "gifts", "label": "Gifts", "kind": "money"}, {"key": "deposits", "label": "Deposited", "kind": "money"},
           {"key": "fee", "label": "Fee", "kind": "money"}]


def _match_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "match_giving_deposits"
    refused, uid = _chief(biz, atype, write=True)
    if refused:
        return refused
    business_id = str(biz["id"])
    items = action.get("items")
    try:
        if isinstance(items, list) and items:
            batch = uuid.uuid4().hex
            done, skipped = [], []
            for it in items[:20]:
                if not isinstance(it, dict):
                    continue
                try:
                    m = match_named(business_id, uid, it.get("gift_ids") or [], it.get("deposit_ids") or [],
                                    made_by="person", note=str(it.get("note") or "matched on the owner's word")[:300],
                                    batch_id=batch)
                    done.append({**m, "why": str(it.get("note") or "as the owner said")})
                except HTTPException as e:
                    skipped.append(str(e.detail))
                except Unavailable:
                    skipped.append("one match couldn't be saved just now; ask again for it")
            got = {"batch_id": batch if done else None, "matched": done, "skipped": skipped}
        else:
            got = match_clear(business_id, uid, year=action.get("year"), made_by="chief")
    except (Unavailable, ValueError, TypeError):
        return _fail(atype, "the gifts or the bank couldn't be read just now, so nothing was matched")
    done = got["matched"]
    rows = [{"id": m["id"], "date": None, "what": m.get("why") or m["kind"], "gifts": m["gifts_cents"] / 100,
             "deposits": m["deposits_cents"] / 100, "fee": m["fee_cents"] / 100} for m in done]
    text = (f"Matched {len(done)} group(s) of gifts to their deposits: {_money(sum(m['gifts_cents'] for m in done))} "
            f"of gifts, {_money(sum(m['deposits_cents'] for m in done))} deposited"
            + (f", {_money(sum(m['fee_cents'] for m in done))} kept by the giving platform (booked as fees)"
               if any(m["fee_cents"] for m in done) else "") + "." if done else "Nothing was clear enough to match.")
    if got["skipped"]:
        text += " Not matched: " + "; ".join(got["skipped"][:5]) + "."
    if done:
        text += " Every match is listed and the batch can be undone as one."
    out = {"type": atype, "display": "table", "view": "giving_matched", "filter": "batch", "title": "What I matched",
           "form": "list", "columns": COLUMNS, "rows": rows[:60], "summary": {"count": len(done)},
           "result": text, "speak": text, "label": f"⛪ Matched {len(done)} deposit group(s)"[:120], "nav": NAV,
           "note_for_chief": "Say what was matched and what wasn't, plainly. Offer undo (unmatch_giving_deposits)."}
    if done:
        out["batch_id"] = got["batch_id"]
        out["match_ids"] = [m["id"] for m in done]
    if not done and got["skipped"]:
        out["failed"] = True
        out["result"] = "Failed: " + text
    return out


def _unmatch_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "unmatch_giving_deposits"
    refused, _ = _chief(biz, atype, write=True)
    if refused:
        return refused
    business_id = str(biz["id"])
    batch = str(action.get("batch_id") or "").strip()
    ids = [str(x) for x in (action.get("match_ids") or []) if _UUID.match(str(x))]
    try:
        if batch:
            if not re.fullmatch(r"[0-9a-f]{32}", batch):
                return _fail(atype, "that isn't a batch of matches I made")
            ids = [m["id"] for m in matches(business_id) if m.get("batch_id") == batch]
        if not ids:
            return _fail(atype, "there's nothing of that to unmatch; single matches come off on the Giving screen")
        got = unmatch(business_id, ids)
    except Unavailable:
        return _fail(atype, "the matches couldn't be read or changed just now; ask again to finish")
    return {"type": atype, "result": f"Unmatched {got['unmatched']} group(s): their deposits wait for an answer again "
                                     "and their gifts wait for a deposit.", "label": f"↩ Unmatched {got['unmatched']}",
            "nav": NAV}


async def handle_giving_deposits(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_status_sync, biz, action or {})


async def handle_match_giving_deposits(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_match_sync, biz, action or {})


async def handle_unmatch_giving_deposits(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_unmatch_sync, biz, action or {})
