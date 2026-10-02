"""
bookkeeping_close.py — Close the month: one checklist, six checks, in order.

  GET  /bookkeeping/close?biz=<id>&month=YYYY-MM
  POST /bookkeeping/close/statement   each account's statement ending balance
  POST /bookkeeping/close/reviewed    "I looked over the month"
  POST /bookkeeping/close/lock        close the month

Month-end work used to live in three places: the Reconciliation tab (Stripe
payouts against bank deposits), Admin → Periods (the lock) and the Bank
Reconciliation report (balances). None of them said what was left. This is
the one checklist, per month:

  1 sync        the bank synced after the month's last day, and the ledger
                posted every one of the month's rows
  2 money_in    every deposit is explained: moves between your own accounts
                confirmed, Stripe deposits matched to a payout (or answered),
                every other deposit answered
  3 categorize  every other row has a category
  4 statement   each account's statement ending balance agrees with the
                balance the books expect on the last day
  5 look        the practitioner looked over the month: money in, money out,
                the biggest changes from the month before
  6 close       the month is locked. It's the same close as Admin → Periods:
                manager role, plan gate, two signatures when that's on

Steps 1–3 are computed from the bank rows. Steps 4 and 5 are answers, kept
on the month's period row (accounting_periods.close_checklist, from
APPLY-2026-10-02-close-checklist.sql). Until that column exists they read
as not done, and saving them answers 409. GET never writes: a month with no
period row reads as open, and the first save creates the row.
"""
from __future__ import annotations

import logging
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user
import bank_money
import bookkeeping_overview as bo
from bookkeeping_overview import SourceFailed, _amt, _day, _d, _get, _get_all, _money, _ts

logger = logging.getLogger("bookkeeping_close")

router = APIRouter(prefix="/bookkeeping/close", tags=["bookkeeping"])

STEP_KEYS = ("sync", "money_in", "categorize", "statement", "look", "close")
_MONTH = re.compile(r"(\d{4})-(0[1-9]|1[0-2])")
_BALANCE_TYPES = ("depository", "credit")
_SETTLED_RECON = bo._MATCHED + ("ignored",)


# ─── Does accounting_periods.close_checklist exist yet? ──────────────
# bank_money's rule: cache only a definite answer (2xx, or 400 42703), and
# read anything else as "not yet" without caching it.

_PROBE_TTL = 300.0
_probe: Dict[str, Any] = {"at": 0.0, "ok": False}


def _probe_now() -> Optional[bool]:
    import httpx
    try:
        resp = httpx.get(f"{sb_clients.sb_url()}/rest/v1/accounting_periods?select=close_checklist&limit=1",
                         headers=sb_clients.sb_headers_service(), timeout=10.0)
    except Exception:
        return None
    if resp.status_code < 300:
        return True
    if resp.status_code == 400 and "42703" in resp.text:
        return False
    return None


def checklist_supported() -> bool:
    now = time.monotonic()
    if _probe["at"] and now - _probe["at"] < _PROBE_TTL:
        return _probe["ok"]
    found = _probe_now()
    if found is not None:
        _probe.update(at=now, ok=found)
    return found is True


def _period_cols(supported: bool) -> str:
    return ("id,period_start,period_end,status,closed_at,closed_via,reopened_at,reopened_reason"
            + (",close_checklist" if supported else ""))


# ─── Small helpers ───────────────────────────────────────────────────

def parse_month(s: Optional[str]) -> date:
    m = _MONTH.fullmatch(s or "")
    if not m:
        raise HTTPException(400, "month must look like 2026-08")
    return date(int(m.group(1)), int(m.group(2)), 1)


def month_end(start: date) -> date:
    return bo._add_months(start, 1) - timedelta(days=1)


def _name(start: date) -> str:
    return bo._MONTH_NAME[start.month]


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _cap_word(n: int) -> str:
    w = bo.number_word(n)
    return w[:1].upper() + w[1:]


_STRIPE_TRANSFER = re.compile(r"^stripe\s*-?\s*transfer\b", re.I)


def display_name(t: Dict[str, Any]) -> str:
    """The name a sentence can hold: "a Stripe transfer" for Stripe's
    payout reference, Title Case for a bank that shouts (the frontend's
    prettyName rule)."""
    raw = bo.tx_name(t).split(" , ")[0].strip()
    if not raw:
        return "a bank transaction"
    if _STRIPE_TRANSFER.match(raw):
        return "a Stripe transfer"
    if raw == raw.upper() and re.search(r"[A-Z]{3}", raw):
        return re.sub(r"\b([a-z])", lambda m: m.group(1).upper(), raw.lower())
    return raw


def _checklist(period: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    c = (period or {}).get("close_checklist")
    return c if isinstance(c, dict) else {}


def expected_ending(account: Dict[str, Any], rows_after: List[Dict[str, Any]]) -> Optional[float]:
    """The balance the bank should show on the month's last day: today's
    balance, less every settled row since. Rows the books leave out still
    moved the bank's balance, so excluded rows count here. A deposit is a
    negative Plaid amount. On a credit card a positive amount adds to
    what's owed."""
    bal = account.get("last_balance")
    if bal is None:
        return None
    try:
        bal = float(bal)
    except (TypeError, ValueError):
        return None
    after = sum(_amt(t) for t in rows_after)
    if account.get("type") == "credit":
        return round(bal - after, 2)
    return round(bal + after, 2)


def _explained(t: Dict[str, Any]) -> bool:
    """A deposit needs nothing more: matched to a payout, set aside, or
    answered (a money_kind or a category)."""
    return (t.get("reconciliation_status") in _SETTLED_RECON
            or bool(t.get("reconciled_to_payout_id"))
            or not bank_money.needs_category(t))


# ─── The six checks for one month ────────────────────────────────────

def sync_step(m_start: date, m_end: date, today: date, items: List[Dict[str, Any]],
              included: List[Dict[str, Any]], month_rows: List[Dict[str, Any]],
              posted_ids: Optional[set], ledger_active: bool) -> Dict[str, Any]:
    name = _name(m_start)
    item_ids = {a.get("item_id") for a in included}
    live = [i for i in items if i.get("item_id") in item_ids]
    base = {"key": "sync", "title": f"The bank is synced past {name} {m_end.day}"}
    if not live:
        return {**base, "done": False, "action": None,
                "detail": "No bank is connected to these books yet."}
    if m_end >= today:
        return {**base, "done": False, "action": None,
                "detail": f"{name} isn’t over yet. It can close after {_day(m_end)}."}
    # A revoked connection never syncs again. Months it reached are fine;
    # a later month can't be complete while its accounts are still in the
    # books, and a sync won't help, so it's named.
    def past_end(i: Dict[str, Any]) -> bool:
        s = _ts(i.get("last_sync_at"))
        return bool(s and s.date() > m_end)
    revoked = [i for i in live if i.get("status") == "revoked"]
    # The same bank account in the books twice counts every row twice;
    # nothing after this step can be trusted until one copy is out.
    twice = bo.accounts_linked_twice(included)
    if twice:
        why = (f"from an old {revoked[0].get('institution_name') or 'bank'} connection"
               if revoked else "from connecting the same bank again")
        return {**base, "done": False, "action": "connections", "unposted": None,
                "last_sync_at": None, "linked_twice": twice,
                "detail": (f"{_cap_word(twice)} {_plural(twice, 'account is', 'accounts are')} in the books "
                           f"twice, {why}, so {_plural(twice, 'its', 'their')} rows count twice. Take the "
                           f"old {_plural(twice, 'copy', 'copies')} out in Settings → Connections.")}
    stuck = [i for i in revoked if not past_end(i)]
    if stuck:
        who = stuck[0].get("institution_name") or "bank"
        return {**base, "done": False, "action": "connections", "unposted": None,
                "last_sync_at": None,
                "detail": (f"An old {who} connection is still in the books, and it can’t sync "
                           f"anymore. Take its accounts out in Settings → Connections.")}
    live = [i for i in live if i not in revoked] or live
    stamps = [_ts(i.get("last_sync_at")) for i in live]
    broken = [i for i in live if i.get("last_error") and i not in revoked]
    oldest = min(stamps) if all(stamps) else None
    synced = bool(oldest and oldest.date() > m_end)
    unposted = None
    if ledger_active and posted_ids is not None:
        unposted = sum(1 for t in month_rows if t.get("transaction_id") not in posted_ids)
    ledger_ok = not ledger_active or unposted == 0
    out = {**base, "done": synced and not broken and ledger_ok,
           "last_sync_at": oldest.isoformat() if oldest else None,
           "unposted": unposted, "action": None}
    if broken:
        who = broken[0].get("institution_name") or "A bank"
        out.update(detail=f"{who} needs to be reconnected before it can sync again.",
                   action="connections")
    elif not synced:
        when = f"last synced {_day(oldest.date())}" if oldest else "hasn’t synced yet"
        out.update(detail=f"The bank {when}, before {name} ended. A sync brings in its last days.",
                   action="sync")
    elif ledger_active and unposted is None:
        out.update(detail="The ledger’s status didn’t load, so this can’t be checked yet.")
    elif unposted:
        out.update(detail=(f"{unposted} {name} {_plural(unposted, 'row isn’t', 'rows aren’t')} in "
                           f"the ledger yet. Rows usually post within a minute. If they don’t, "
                           f"re-sync the ledger in Settings."), action="ledger")
    else:
        n = len(included)
        covered = ("The account is covered." if n == 1 else
                   "Both accounts are covered." if n == 2 else "Every account is covered.")
        out["detail"] = f"Last pull {_day(oldest.date())}. {covered}"  # type: ignore[union-attr]
    return out


def money_in_step(m_start: date, month_rows: List[Dict[str, Any]],
                  window_rows: List[Dict[str, Any]], acct_by_id: Dict[str, Dict[str, Any]],
                  has_stripe: bool) -> Dict[str, Any]:
    key, name = m_start.strftime("%Y-%m"), _name(m_start)
    pairs = [p for p in bo.find_transfer_pairs(window_rows, acct_by_id)
             if str(p["out"].get("date"))[:7] == key or str(p["in"].get("date"))[:7] == key]
    pair_ids = {p[s].get("transaction_id") for p in pairs for s in ("out", "in")}
    deposits = [t for t in month_rows if _amt(t) < 0]
    loose = [t for t in deposits if t.get("transaction_id") not in pair_ids and not _explained(t)]
    stripe = [t for t in loose if "stripe" in bo._norm(bo.tx_name(t))]
    other = [t for t in loose if t not in stripe]

    def row(t: Dict[str, Any]) -> Dict[str, Any]:
        return {"transaction_id": t.get("transaction_id"), "date": t.get("date"),
                "name": bo.tx_name(t), "amount": abs(_amt(t)),
                "account": bo.account_label(acct_by_id.get(t.get("account_id"))),
                "suggestion": bo._suggest(t, None, acct_by_id)}

    if not (pairs or stripe or other):
        n = len(deposits)
        detail = (f"No money came in during {name}." if n == 0 else
                  f"The {name} deposit is explained." if n == 1 else
                  f"Both {name} deposits are explained." if n == 2 else
                  f"All {bo.number_word(n)} {name} deposits are explained.")
    else:
        n = len(deposits)
        parts = [f"{_cap_word(n)} {_plural(n, 'deposit', 'deposits')} in {name}."]
        if pairs:
            k = len(pairs)
            parts.append(f"{_cap_word(k)} {_plural(k, 'is a move', 'are moves')} between your own "
                         f"accounts, so {_plural(k, 'it needs', 'they need')} no category.")
        if stripe:
            k = len(stripe)
            parts.append(f"{_cap_word(k)} {_plural(k, 'is a Stripe deposit', 'are Stripe deposits')} "
                         + ("with no payout to match." if has_stripe else
                            f"and no Stripe account is connected to match {_plural(k, 'it', 'them')}."))
        if other:
            k = len(other)
            parts.append(f"{_cap_word(k)} {_plural(k, 'needs', 'need')} an answer.")
        detail = " ".join(parts)
    return {
        "key": "money_in", "title": "Money in matches where it came from",
        "done": not (pairs or stripe or other), "detail": detail,
        "deposits": len(deposits),
        "transfers": [{"out_id": p["out"]["transaction_id"], "in_id": p["in"]["transaction_id"],
                       "amount": abs(_amt(p["out"])),
                       "out_date": p["out"].get("date"), "in_date": p["in"].get("date"),
                       "from": bo.account_label(acct_by_id.get(p["out"].get("account_id"))),
                       "to": bo.account_label(acct_by_id.get(p["in"].get("account_id")))}
                      for p in pairs],
        "stripe": [row(t) for t in stripe],
        "stripe_total": round(sum(abs(_amt(t)) for t in stripe), 2),
        "other": [row(t) for t in other],
        "_pair_ids": pair_ids,
    }


def categorize_step(m_start: date, month_rows: List[Dict[str, Any]], pair_ids: set,
                    acct_by_id: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    name = _name(m_start)
    # The same rule as the To review queue this step links to, less the
    # transfer legs: confirming a pair in step 2 answers both.
    rows = [t for t in month_rows if t.get("transaction_id") not in pair_ids
            and bank_money.needs_category(t)]
    drafts = sum(1 for t in rows if bo._suggest(t, None, acct_by_id))
    n = len(rows)
    if not n:
        detail = f"Every {name} row has a category."
    else:
        names = sorted({display_name(t) for t in rows}, key=lambda x: (x.startswith("a "), x.lower()))
        which = f": {names[0]} and {names[1]}" if n == 2 and len(names) == 2 else \
            f": {names[0]}" if n == 1 and names else ""
        if pair_ids:
            detail = (f"Once the transfers are confirmed, {bo.number_word(n)} "
                      f"{_plural(n, 'row remains', 'rows remain')}{which}.")
        else:
            detail = f"{_cap_word(n)} {_plural(n, 'row still needs', 'rows still need')} a category{which}."
        if drafts:
            detail += (" Kai has a draft for it." if n == 1 else
                       " Kai has drafts for both." if drafts == n == 2 else
                       f" Kai has drafts for all {n}." if drafts == n else
                       f" Kai has drafts for {drafts}.")
    return {"key": "categorize", "title": "Everything left has a category",
            "done": n == 0, "detail": detail, "count": n, "drafts": drafts}


def statement_step(m_start: date, m_end: date, accounts: List[Dict[str, Any]],
                   bank_rows: List[Dict[str, Any]], checklist: Dict[str, Any],
                   supported: bool) -> Dict[str, Any]:
    name, last = _name(m_start), m_end.isoformat()
    first = m_start.isoformat()
    entered_all = checklist.get("statements") if isinstance(checklist.get("statements"), dict) else {}
    out = []
    for a in accounts:
        aid = a.get("account_id")
        mine = [t for t in bank_rows if t.get("account_id") == aid]
        after = [t for t in mine if str(t.get("date") or "") > last]
        exp = expected_ending(a, after)
        # A pocket with no rows in the month and nothing in it has nothing
        # to check; asking for its statement would bury the ones that do.
        quiet = (not any(first <= str(t.get("date") or "")[:10] <= last for t in mine)
                 and (exp is None or abs(exp) < 0.005))
        st = entered_all.get(aid) if isinstance(entered_all.get(aid), dict) else {}
        entered = st.get("balance")
        entered = float(entered) if isinstance(entered, (int, float)) else None
        diff = round(entered - exp, 2) if entered is not None and exp is not None else None
        out.append({"account_id": aid, "label": bo.account_label(a), "type": a.get("type"),
                    "trust": bool(a.get("is_trust_account")), "quiet": quiet, "expected": exp,
                    "entered": entered, "entered_at": st.get("at"), "difference": diff,
                    # No balance from the bank means nothing to check against.
                    "agrees": None if diff is None else abs(diff) < 0.005})
    title = "Your bank statement agrees with the books"
    if not out:
        return {"key": "statement", "title": title, "done": True, "supported": supported,
                "accounts": [], "detail": "No bank accounts to check."}
    if not supported:
        return {"key": "statement", "title": title, "done": False, "supported": False,
                "accounts": out,
                "detail": "Checking statements isn’t switched on for your books yet."}
    # Quiet accounts are optional, but a balance typed for one still has to agree.
    missing = [x for x in out if x["entered"] is None and not x["quiet"]]
    off = [x for x in out if x["agrees"] is False]
    active = [x for x in out if not x["quiet"]]
    if off:
        x = off[0]
        detail = (f"{x['label']} is off by {_money(x['difference'])}. A difference means a row is "
                  f"missing or extra, in {name} or since.")
    elif missing:
        n = len(active)
        which = "the account" if n == 1 else "both accounts" if n == 2 else f"the {n} accounts"
        detail = (f"Type the ending balance from the {name} statement for {which} with activity "
                  f"or money in {_plural(n, 'it', 'them')}.")
    elif not active:
        detail = f"No account had activity or money in it during {name}."
    else:
        detail = "Every account agrees with its statement."
    return {"key": "statement", "title": title, "done": not (missing or off),
            "supported": True, "accounts": out, "detail": detail}


def look_step(m_start: date, prev_start: date, checklist: Dict[str, Any],
              supported: bool) -> Dict[str, Any]:
    rv = checklist.get("reviewed") if isinstance(checklist.get("reviewed"), dict) else None
    done = bool(supported and rv and rv.get("at"))
    detail = (f"Looked over {_day(_d(rv.get('at')))}." if done else
              f"Money in, money out and the biggest changes from {_name(prev_start)}.")
    return {"key": "look", "title": f"Look over {_name(m_start)}", "done": done,
            "supported": supported, "reviewed_at": rv.get("at") if done else None,
            "detail": detail}


def close_step(m_start: date, period: Optional[Dict[str, Any]], lock_mode: str,
               waiting_signature: bool) -> Dict[str, Any]:
    name = _name(m_start)
    status = (period or {}).get("status") or "open"
    later = ("Edits are blocked until it’s reopened." if lock_mode == "hard" else
             "A later edit needs a reason and lands in the audit trail.")
    if status == "closed":
        when = _day(_d((period or {}).get("closed_at")))
        detail = f"Closed{f' {when}' if when else ''}. {later}"
    elif waiting_signature:
        detail = "Waiting on the second signature."
    elif status == "reopened":
        why = ((period or {}).get("reopened_reason") or "").strip()
        detail = f"Reopened{f' because “{why}”' if why else ''}. Close it again when it’s right."
    else:
        detail = f"Locks the month. {later}"
    return {"key": "close", "title": f"Close {name}", "done": status == "closed",
            "status": status, "waiting_signature": waiting_signature, "detail": detail}


def with_states(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """done · now (the first open check) · next (the second) · later."""
    out, open_seen = [], 0
    for s in steps:
        s = {k: v for k, v in s.items() if not k.startswith("_")}
        if s["done"]:
            s["state"] = "done"
        else:
            s["state"] = ("now", "next")[open_seen] if open_seen < 2 else "later"
            open_seen += 1
        out.append(s)
    return out


# ─── Reading the books once ──────────────────────────────────────────

def _load(biz: str, load_from: date, supported: bool) -> Dict[str, Any]:
    """Every read the checklist needs. Raises SourceFailed on any of them:
    a checklist built from a partial read would mark work done that isn't."""
    with ThreadPoolExecutor(max_workers=6) as pool:
        f_items = pool.submit(_get, f"/plaid_items?business_id=eq.{biz}"
                              f"&select=item_id,institution_name,status,last_sync_at,last_error")
        f_accts = pool.submit(_get, f"/plaid_accounts?business_id=eq.{biz}&deleted_at=is.null"
                              f"&select=account_id,item_id,name,official_name,type,subtype,mask,"
                              f"included_in_bookkeeping,is_trust_account,last_balance,last_balance_at")
        f_periods = pool.submit(_get, f"/accounting_periods?business_id=eq.{biz}&period_type=eq.month"
                                f"&select={_period_cols(supported)}&limit=500")
        f_any_je = pool.submit(_get, f"/journal_entries?business_id=eq.{biz}&status=eq.active"
                               f"&select=id&limit=1")
        f_je = pool.submit(_get_all, f"/journal_entries?business_id=eq.{biz}&status=eq.active"
                           f"&entry_date=gte.{load_from.isoformat()}"
                           f"&select=entry_date,source_type,source_id&order=entry_date.asc,id.asc")
        items, accounts = f_items.result(), f_accts.result()
        periods, any_je, journal = f_periods.result(), f_any_je.result(), f_je.result()
    included = [a for a in accounts if a.get("included_in_bookkeeping")]
    rows: List[Dict[str, Any]] = []
    if included:
        ids = ",".join(a["account_id"] for a in included)
        rows = _get_all(
            f"/plaid_transactions?business_id=eq.{biz}&account_id=in.({ids})"
            f"&pending=eq.false&date=gte.{load_from.isoformat()}"
            f"&select=transaction_id,account_id,amount,date,name,merchant_name,"
            f"business_category,business_subcategory,plaid_category_primary,plaid_category_detail,"
            f"reconciliation_status,reconciled_to_payout_id,excluded_from_books{bank_money.cols()}"
            f"&order=date.desc,transaction_id.desc")
    trust = {a["account_id"] for a in included if a.get("is_trust_account")}
    books = [t for t in rows if not t.get("excluded_from_books") and _amt(t) != 0
             and t.get("account_id") not in trust]
    return {"items": items, "accounts": accounts, "included": included, "periods": periods,
            "ledger_active": bool(any_je), "journal": journal, "bank_rows": rows, "books": books}


def _month_rows(books: List[Dict[str, Any]], m_start: date) -> List[Dict[str, Any]]:
    key = m_start.strftime("%Y-%m")
    return [t for t in books if str(t.get("date") or "")[:7] == key]


def _window_rows(books: List[Dict[str, Any]], m_start: date, m_end: date) -> List[Dict[str, Any]]:
    """The month plus the transfer window on each side, so a move that
    left on the 31st and landed on the 2nd still pairs."""
    lo = (m_start - timedelta(days=bo.TRANSFER_WINDOW_DAYS)).isoformat()
    hi = (m_end + timedelta(days=bo.TRANSFER_WINDOW_DAYS)).isoformat()
    return [t for t in books if lo <= str(t.get("date") or "")[:10] <= hi]


def month_steps(m_start: date, today: date, data: Dict[str, Any], period: Optional[Dict[str, Any]],
                supported: bool, has_stripe: bool, lock_mode: str,
                waiting_signature: bool = False) -> List[Dict[str, Any]]:
    m_end = month_end(m_start)
    acct_by_id = {a["account_id"]: a for a in data["accounts"] if a.get("account_id")}
    month_rows = _month_rows(data["books"], m_start)
    posted_ids = {je.get("source_id") for je in data["journal"]
                  if je.get("source_type") == "plaid_transaction"}
    checklist = _checklist(period)
    money = money_in_step(m_start, month_rows, _window_rows(data["books"], m_start, m_end),
                          acct_by_id, has_stripe)
    # A bank linked twice lists each account twice; the copy from a revoked
    # connection isn't asked for its statement while the live copy is.
    candidates = [a for a in data["included"] if a.get("type") in _BALANCE_TYPES]
    revoked_items = {i.get("item_id") for i in data["items"] if i.get("status") == "revoked"}
    live_keys = {bo.real_account_key(a) for a in candidates if a.get("item_id") not in revoked_items}
    balance_accounts = [a for a in candidates
                        if not (a.get("item_id") in revoked_items and bo.real_account_key(a) in live_keys)]
    return with_states([
        sync_step(m_start, m_end, today, data["items"], data["included"], month_rows,
                  posted_ids, data["ledger_active"]),
        money,
        categorize_step(m_start, month_rows, money["_pair_ids"], acct_by_id),
        statement_step(m_start, m_end, balance_accounts, data["bank_rows"], checklist, supported),
        look_step(m_start, bo._add_months(m_start, -1), checklist, supported),
        close_step(m_start, period, lock_mode, waiting_signature),
    ])


# ─── Look over the month: the Reports tab's own P&L, twice ───────────

def month_summary(biz: str, biz_row: Dict[str, Any], m_start: date) -> Dict[str, Any]:
    import gl_reports
    import reports_engine
    import reports_router
    prev = bo._add_months(m_start, -1)
    m_end, p_end = month_end(m_start), month_end(prev)
    basis = reports_router._basis_for(biz_row, None)

    def gl() -> Dict[str, Any]:
        lines = gl_reports.effective_lines(biz)
        window = gl_reports._pl_window_accrual if basis == "accrual" else gl_reports._pl_window
        return {"cur": window(lines, m_start, m_end), "prev": window(lines, prev, p_end)}

    def source() -> Dict[str, Any]:
        return {"cur": reports_engine._pl_for_window(biz, m_start, m_end),
                "prev": reports_engine._pl_for_window(biz, prev, p_end)}

    out = reports_router._gl_or_fallback(biz, gl, source)

    def nums(pl: Dict[str, Any]) -> Dict[str, Any]:
        rev, exp = pl.get("revenue") or {}, pl.get("expenses") or {}
        return {"money_in": rev.get("gross_revenue", 0.0), "money_out": exp.get("total", 0.0),
                "net": pl.get("net_income", 0.0),
                "buckets": {b.get("label") or b.get("bucket"): float(b.get("total") or 0)
                            for b in (exp.get("by_bucket") or [])}}

    cur, before = nums(out["cur"]), nums(out["prev"])
    lines = [("Money in", cur["money_in"], before["money_in"])]
    for label in sorted(set(cur["buckets"]) | set(before["buckets"])):
        lines.append((label, cur["buckets"].get(label, 0.0), before["buckets"].get(label, 0.0)))
    changes = sorted(({"label": label, "now": round(now, 2), "before": round(was, 2),
                       "change": round(now - was, 2)} for label, now, was in lines
                      if abs(now - was) >= 0.005), key=lambda c: -abs(c["change"]))[:3]
    return {"source": out.get("source"), "basis": basis if out.get("source") == "gl" else "cash",
            "money_in": cur["money_in"], "money_out": cur["money_out"], "net": cur["net"],
            "before": {"month": prev.strftime("%Y-%m"), "name": _name(prev),
                       "money_in": before["money_in"], "money_out": before["money_out"],
                       "net": before["net"]},
            "changes": changes}


# ─── GET /bookkeeping/close ──────────────────────────────────────────

def _biz_row(biz: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,type,settings,stripe_account_id&limit=1")
    if not rows:
        raise HTTPException(503, "Couldn't read this business just now.")
    return rows[0]


def _fy_month(biz_row: Dict[str, Any]) -> int:
    fin = ((biz_row.get("settings") or {}).get("financial") or {})
    try:
        m = int(fin.get("fiscal_year_start_month") or 1)
    except (TypeError, ValueError):
        return 1
    return m if 1 <= m <= 12 else 1


def _waiting_signature(biz: str, period_id: Optional[str]) -> bool:
    if not period_id:
        return False
    try:
        import chief_bookkeeping
        return any(p.get("proposal_type") == "propose_period_close"
                   and (p.get("proposed") or {}).get("period_id") == period_id
                   for p in chief_bookkeeping.list_proposals(biz, "pending"))
    except Exception as e:  # the signature line is a nicety, never the page
        logger.warning(f"[bk-close] proposals read failed for {biz}: {e}")
        return False


def build_close(biz: str, biz_row: Dict[str, Any], month: Optional[str] = None,
                now: Optional[datetime] = None, with_summary: bool = True) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    today = now.date()
    settings = biz_row.get("settings") or {}
    lock_mode = "hard" if settings.get("period_lock_mode") == "hard" else "soft"
    two_sig = bool(settings.get("period_close_two_signature"))
    has_stripe = bool((biz_row.get("stripe_account_id") or "").strip())
    fy_start = bo.fiscal_year_start(today, _fy_month(biz_row))
    picked = parse_month(month) if month else None
    if picked and picked > today:
        raise HTTPException(400, "That month hasn't started yet.")
    load_from = min(fy_start, picked or fy_start) - timedelta(days=bo.TRANSFER_WINDOW_DAYS)
    supported = checklist_supported()
    data = _load(biz, load_from, supported)
    period_by_start = {str(p.get("period_start") or "")[:7]: p for p in data["periods"]}

    # The strip: every month of the fiscal year, the overview's status plus
    # how many of the six checks are done.
    posted_by_month: Dict[str, int] = {}
    unposted_by_month: Dict[str, int] = {}
    posted_ids = {je.get("source_id") for je in data["journal"] if je.get("source_type") == "plaid_transaction"}
    for je in data["journal"]:
        k = str(je.get("entry_date") or "")[:7]
        posted_by_month[k] = posted_by_month.get(k, 0) + 1
    if data["ledger_active"]:
        for t in data["books"]:
            if t.get("transaction_id") not in posted_ids:
                k = str(t.get("date") or "")[:7]
                unposted_by_month[k] = unposted_by_month.get(k, 0) + 1
    closed = {k for k, p in period_by_start.items() if p.get("status") == "closed"}
    fy_books = [t for t in data["books"] if str(t.get("date") or "") >= fy_start.isoformat()]
    strip = bo.month_rows(fy_start, today, fy_books, posted_by_month, unposted_by_month, closed)
    for m in strip:
        start = parse_month(m["month"])
        m["period_status"] = (period_by_start.get(m["month"]) or {}).get("status") or "open"
        m["done"] = (sum(1 for s in month_steps(start, today, data, period_by_start.get(m["month"]),
                                                supported, has_stripe, lock_mode) if s["done"])
                     if m["status"] in ("open", "behind", "closed") else None)
        m["total"] = len(STEP_KEYS)

    # The month on the page: the one asked for, else the oldest month that
    # still needs closing, else the last month that ended.
    if picked is None:
        todo = [m for m in strip if m["status"] in ("open", "behind")]
        ended = [m for m in strip if m["status"] not in ("future", "current")]
        pick = todo[0]["month"] if todo else ended[-1]["month"] if ended else strip[0]["month"]
        picked = parse_month(pick)
    key = picked.strftime("%Y-%m")
    period = period_by_start.get(key)
    waiting = two_sig and _waiting_signature(biz, (period or {}).get("id"))
    steps = month_steps(picked, today, data, period, supported, has_stripe, lock_mode, waiting)

    summary = None
    if with_summary:
        try:
            summary = month_summary(biz, biz_row, picked)
        except Exception as e:  # the numbers are a section, never the page
            logger.warning(f"[bk-close] month summary failed for {biz} {key}: {e}")
    for s in steps:
        if s["key"] == "look":
            s["summary"] = summary

    m_end = month_end(picked)
    bills_due = None
    try:
        bills = _get(f"/bills?business_id=eq.{biz}&status=in.({','.join(bo._OPEN_BILL)})"
                     f"&due_date=lte.{m_end.isoformat()}&select=id&limit=500")
        bills_due = len(bills)
    except SourceFailed:
        pass
    money = next(s for s in steps if s["key"] == "money_in")
    return {
        "ok": True, "business_id": biz, "as_of": now.isoformat(),
        "month": key, "name": _name(picked), "label": f"{_name(picked)} {picked.year}",
        "ended": m_end < today,
        "months": strip,
        "period": ({"id": period.get("id"), "status": period.get("status"),
                    "closed_at": period.get("closed_at"), "closed_via": period.get("closed_via"),
                    "reopened_at": period.get("reopened_at"),
                    "reopened_reason": period.get("reopened_reason")} if period else None),
        "steps": steps,
        "done": sum(1 for s in steps if s["done"]),
        "total": len(steps),
        "glance": {"bank_rows": len(_month_rows(data["books"], picked)),
                   "deposits": money["deposits"],
                   "transfers": len(money["transfers"]),
                   "stripe_unmatched": len(money["stripe"]),
                   "bills_due": bills_due},
        "policy": {"lock_mode": lock_mode, "two_signature": two_sig},
        "supported": {"checklist": supported, "money_kind": bank_money.supported()},
    }


@router.get("")
def close_view(biz: str, month: Optional[str] = None,
               user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    from plaid_router import _require_reader
    _require_reader(biz, user)
    try:
        return build_close(biz, _biz_row(biz), month)
    except SourceFailed as e:
        raise HTTPException(503, f"Couldn't read your books just now ({e}).")


# ─── Writes: the two answers and the lock ────────────────────────────

def _manager(biz: str, user: AuthedUser) -> Dict[str, Any]:
    import accounting_periods_router
    return accounting_periods_router._access(biz, user, "manager")


def _period_row(biz: str, m_start: date, supported: bool) -> Optional[Dict[str, Any]]:
    rows = _get(f"/accounting_periods?business_id=eq.{biz}&period_type=eq.month"
                f"&period_start=eq.{m_start.isoformat()}&select={_period_cols(supported)}&limit=1")
    return rows[0] if rows else None


def _ensure_period(biz: str, m_start: date, biz_row: Dict[str, Any], supported: bool) -> Dict[str, Any]:
    row = _period_row(biz, m_start, supported)
    if row:
        return row
    import gl_engine
    fy = _fy_month(biz_row)
    gl_engine.generate_periods(biz, m_start.year if m_start.month >= fy else m_start.year - 1, fy)
    row = _period_row(biz, m_start, supported)
    if not row:
        raise HTTPException(502, "Couldn't set up this month's record. Try again.")
    return row


def _ended_month(month: str) -> date:
    m_start = parse_month(month)
    if month_end(m_start) >= datetime.now(timezone.utc).date():
        raise HTTPException(400, f"{_name(m_start)} isn't over yet.")
    return m_start


def _open_period_for_answers(biz: str, month: str, biz_row: Dict[str, Any]) -> Dict[str, Any]:
    if not checklist_supported():
        raise HTTPException(409, "Saving close checks needs the 2026-10-02 close checklist migration.")
    import billing_limits
    billing_limits.require_feature(biz, "period_close")   # the same plan gate as the lock
    m_start = _ended_month(month)
    period = _ensure_period(biz, m_start, biz_row, True)
    if period.get("status") == "closed":
        raise HTTPException(409, f"{_name(m_start)} is closed. Reopen it to change its checks.")
    return period


_SAVE_TRIES = 3


def _update_checklist(biz: str, period_id: str,
                      change: Callable[[Dict[str, Any]], Dict[str, Any]],
                      allow_closed: bool = False) -> Dict[str, Any]:
    """Read, merge, write, without losing a save made at the same moment
    (two tabs, or an owner and a manager). The write only lands if the
    row's updated_at is still the one this merge started from; otherwise
    it reads again and merges again."""
    for _ in range(_SAVE_TRIES):
        rows = _get(f"/accounting_periods?id=eq.{period_id}&business_id=eq.{biz}"
                    f"&select=id,status,updated_at,close_checklist&limit=1")
        if not rows:
            raise HTTPException(404, "That month's record is gone.")
        row = rows[0]
        if row.get("status") == "closed" and not allow_closed:
            raise HTTPException(409, "That month is closed. Reopen it to change its checks.")
        merged = change(_checklist(row))
        was = row.get("updated_at")
        guard = f"&updated_at=eq.{quote(str(was), safe='')}" if was else "&updated_at=is.null"
        res = sb_clients.sb_patch_as_service(
            f"/accounting_periods?id=eq.{period_id}&business_id=eq.{biz}{guard}",
            {"close_checklist": merged, "updated_at": datetime.now(timezone.utc).isoformat()})
        if res is None:
            raise HTTPException(502, "That didn't save. Try again.")
        if res:            # the row matched: nobody saved in between
            return merged
    raise HTTPException(409, "Someone else saved this month at the same moment. Try again.")


class StatementLine(BaseModel):
    account_id: str
    balance: float


class StatementBody(BaseModel):
    business_id: str
    month: str
    balances: List[StatementLine]


@router.post("/statement")
def save_statement(body: StatementBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Each account's ending balance from the month's statement. The books'
    own figure is computed fresh on every read, so a row that arrives later
    re-opens a check that agreed."""
    biz = body.business_id
    biz_row = _manager(biz, user)
    if not body.balances or len(body.balances) > 40:
        raise HTTPException(400, "Send between 1 and 40 balances.")
    for line in body.balances:
        if not math.isfinite(line.balance) or abs(line.balance) >= 1e10:
            raise HTTPException(400, "That balance doesn't look like an amount.")
    try:
        period = _open_period_for_answers(biz, body.month, biz_row)
        accts = _get(f"/plaid_accounts?business_id=eq.{biz}&deleted_at=is.null"
                     f"&included_in_bookkeeping=eq.true&select=account_id,type")
    except SourceFailed as e:
        raise HTTPException(503, f"Couldn't read your books just now ({e}).")
    allowed = {a["account_id"] for a in accts if a.get("type") in _BALANCE_TYPES}
    if any(line.account_id not in allowed for line in body.balances):
        raise HTTPException(400, "One of those accounts isn't in these books.")
    stamp = datetime.now(timezone.utc).isoformat()

    def add(checklist: Dict[str, Any]) -> Dict[str, Any]:
        statements = dict(checklist.get("statements") or {})
        for line in body.balances:
            statements[line.account_id] = {"balance": round(line.balance, 2), "at": stamp, "by": str(user.id)}
        return {**checklist, "statements": statements}
    try:
        _update_checklist(biz, str(period["id"]), add)
    except SourceFailed as e:
        raise HTTPException(503, f"Couldn't read your books just now ({e}).")
    return {"ok": True, "saved": len(body.balances)}


class ReviewedBody(BaseModel):
    business_id: str
    month: str
    reviewed: bool = True


@router.post("/reviewed")
def save_reviewed(body: ReviewedBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = body.business_id
    biz_row = _manager(biz, user)
    stamp = datetime.now(timezone.utc).isoformat()

    def mark(checklist: Dict[str, Any]) -> Dict[str, Any]:
        if body.reviewed:
            return {**checklist, "reviewed": {"at": stamp, "by": str(user.id)}}
        return {k: v for k, v in checklist.items() if k != "reviewed"}
    try:
        period = _open_period_for_answers(biz, body.month, biz_row)
        _update_checklist(biz, str(period["id"]), mark)
    except SourceFailed as e:
        raise HTTPException(503, f"Couldn't read your books just now ({e}).")
    return {"ok": True, "reviewed": body.reviewed}


class LockBody(BaseModel):
    business_id: str
    month: str
    with_open: bool = False   # close even though some checks aren't done


@router.post("/lock")
def lock_month(body: LockBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Close the month through the same close as Admin → Periods (manager
    role, plan gate, two signatures). A month with checks still open closes
    only when asked to explicitly, and the open checks are kept on the
    period row so the audit trail can say what was skipped."""
    import accounting_periods_router
    biz = body.business_id
    biz_row = _manager(biz, user)
    m_start = _ended_month(body.month)
    supported = checklist_supported()
    try:
        view = build_close(biz, biz_row, body.month, with_summary=False)
    except SourceFailed as e:
        raise HTTPException(503, f"Couldn't read your books just now ({e}).")
    open_steps = [s["key"] for s in view["steps"] if s["key"] != "close" and not s["done"]]
    if open_steps and not body.with_open:
        raise HTTPException(409, detail={
            "error": "checks_open", "open": open_steps,
            "message": f"{len(open_steps)} {_plural(len(open_steps), 'check is', 'checks are')} still open."})
    try:   # only a close that's going ahead creates the month's record
        period = _ensure_period(biz, m_start, biz_row, supported)
    except SourceFailed as e:
        raise HTTPException(503, f"Couldn't read your books just now ({e}).")
    result = accounting_periods_router.close(str(period["id"]), user)
    # A two-signature close comes back pending, not closed: no note yet.
    if result.get("closed") and supported:
        stamp = datetime.now(timezone.utc).isoformat()
        try:
            _update_checklist(biz, str(period["id"]),
                              lambda c: {**c, "closed_with_open": open_steps, "closed_at": stamp},
                              allow_closed=True)
        except (HTTPException, SourceFailed):   # the close stands; only the note was lost
            logger.warning(f"[bk-close] closed {biz} {body.month} but the checklist note didn't save")
    return {**result, "open": open_steps}
