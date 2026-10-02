"""
bookkeeping_overview.py — the Bookkeeping room's front page, in one read.

  GET /bookkeeping/overview?biz=<id>

The old room opened on a vault card that always said "on · tracking" — the
panel never passed it a number — and the facts a practitioner needed were
scattered across five tabs, or not computed at all. This endpoint answers
"where do my books stand?" in one payload:

  bank      — linked accounts, last sync, accounts that look linked twice
  ledger    — when the ledger last posted, bank rows it hasn't posted yet,
              a divergence alarm, the posting queue
  path      — the four steps to current: sync → categorize → match → close
  year      — the year so far, from the SAME P&L the Reports tab shows
              (GL when active, source tables otherwise)
  months    — each month of the fiscal year: quiet / open / behind /
              closed / current / future
  bills     — overdue and due in the next 30 days
  noticed   — what Kai noticed: own-account transfers booked as income or
              spending, rows that look doubled, a ledger that stopped
              posting, Stripe deposits with no payout, a stale bank sync
  recent    — the latest bank rows, in plain words
  headline  — the one-sentence status the page leads with

Read-only: it never generates periods, marks bills overdue, or runs a
sync — opening a page must not write. A source that fails costs its own
section, never the page; `sources_failed` names it (platform_today's rule).
Access is the financial-read tier (owner, active accountant, team seat),
the same ladder as /plaid/* reads.
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends

import sb_clients
from auth_supabase import AuthedUser, require_user
import plaid_categorization

logger = logging.getLogger("bookkeeping_overview")

router = APIRouter(prefix="/bookkeeping", tags=["bookkeeping"])

# A transfer between two of your own accounts usually clears within a day
# or two; three days catches weekends without pairing unrelated rows.
TRANSFER_WINDOW_DAYS = 3
SYNC_STALE_DAYS = 3
QUEUE_STALE_MINUTES = 30
_TX_LIMIT = 20000
_MATCHED = ("auto_matched", "manual_matched")
_OPEN_BILL = ("pending", "scheduled", "overdue")
_NUM_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven",
              "eight", "nine", "ten", "eleven", "twelve"]
_MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug",
               "Sep", "Oct", "Nov", "Dec"]
_MONTH_NAME = ["", "January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]


class SourceFailed(Exception):
    """A read came back as an error (sb_clients returns None on 4xx/5xx and
    transport errors; an empty table returns [])."""


def _get(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if rows is None:
        raise SourceFailed(path.split("?")[0])
    return rows


# ─── Small pure helpers ──────────────────────────────────────────────

def _d(value: Any) -> Optional[date]:
    s = str(value or "")[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _ts(value: Any) -> Optional[datetime]:
    s = str(value or "")
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _money(x: float) -> str:
    return f"${abs(x):,.2f}"


def _day(d: Optional[date]) -> str:
    return f"{_MONTH_ABBR[d.month]} {d.day}" if d else ""


def _amt(t: Dict[str, Any]) -> float:
    try:
        return float(t.get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def _cents(t: Dict[str, Any]) -> int:
    return int(round(abs(_amt(t)) * 100))


def tx_name(t: Dict[str, Any]) -> str:
    return (t.get("merchant_name") or t.get("name") or "").strip()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def account_short_name(a: Dict[str, Any]) -> str:
    """'KMJ Creative Solutions LLC - Primary' → 'Primary'. Bank account
    names lead with the legal entity, which is noise inside its own books."""
    name = (a.get("name") or a.get("official_name") or "Account").strip()
    if " - " in name:
        tail = name.rsplit(" - ", 1)[1].strip()
        if tail:
            return tail
    return name


def account_label(a: Optional[Dict[str, Any]]) -> str:
    if not a:
        return "an account"
    mask = (a.get("mask") or "").strip()
    short = account_short_name(a)
    return f"{short} ••{mask}" if mask else short


def real_account_key(a: Optional[Dict[str, Any]]) -> Optional[Tuple[str, str, str]]:
    """Identity of the real bank account behind a plaid_accounts row. Linking
    the same bank twice creates a second row with a new account_id but the
    same name, mask and type — that's how one deposit shows up twice."""
    if not a or not a.get("mask"):
        return None
    return (_norm(a.get("official_name") or a.get("name") or ""),
            str(a.get("mask")), str(a.get("type") or ""))


def needs_category(t: Dict[str, Any]) -> bool:
    # Same rule as chief_bookkeeping.bookkeeping_counts (the Home nudge):
    # no bucket, or the 'other' catch-all Plaid falls back to.
    return t.get("business_category") in (None, "", "other")


def counts_as_income(t: Dict[str, Any]) -> bool:
    """Would the books count this inflow as income? (gl_engine.desired_for_plaid:
    an inflow not reconciled to a payout, with an income-ish Plaid category.)"""
    return _amt(t) < 0 and not t.get("reconciled_to_payout_id") and \
        plaid_categorization.is_income_category(
            t.get("plaid_category_primary"), t.get("plaid_category_detail"))


def counts_as_spending(t: Dict[str, Any]) -> bool:
    return _amt(t) > 0 and not plaid_categorization.is_income_category(
        t.get("plaid_category_primary"), t.get("plaid_category_detail"))


def number_word(n: int) -> str:
    return _NUM_WORDS[n] if 0 <= n < len(_NUM_WORDS) else str(n)


# ─── Detectors ───────────────────────────────────────────────────────

def find_transfer_pairs(txs: List[Dict[str, Any]],
                        accounts: Dict[str, Dict[str, Any]],
                        window_days: int = TRANSFER_WINDOW_DAYS) -> List[Dict[str, Any]]:
    """Money that left one of your accounts and landed in another of yours:
    an outflow and an inflow of the same amount, in two different real
    accounts, within a few days. Greedy, closest date first, each row used
    once. Rows on the same real account (a bank linked twice) are duplicates,
    not transfers, and payout deposits are already explained by Stripe."""
    ins_by_cents: Dict[int, List[Dict[str, Any]]] = {}
    for t in txs:
        if _amt(t) < 0 and not t.get("reconciled_to_payout_id") and _d(t.get("date")):
            ins_by_cents.setdefault(_cents(t), []).append(t)
    outs = sorted((t for t in txs if _amt(t) > 0 and _d(t.get("date"))),
                  key=lambda t: (t.get("date") or "", t.get("transaction_id") or ""))
    used: set = set()
    pairs: List[Dict[str, Any]] = []
    for o in outs:
        o_date = _d(o.get("date"))
        o_key = real_account_key(accounts.get(o.get("account_id")))
        best, best_gap = None, None
        for i in ins_by_cents.get(_cents(o), []):
            tid = i.get("transaction_id")
            if tid in used or i.get("account_id") == o.get("account_id"):
                continue
            i_key = real_account_key(accounts.get(i.get("account_id")))
            if o_key is not None and o_key == i_key:
                continue
            gap = abs((_d(i.get("date")) - o_date).days)  # type: ignore[operator]
            if gap <= window_days and (best_gap is None or gap < best_gap):
                best, best_gap = i, gap
        if best is not None:
            used.add(best.get("transaction_id"))
            pairs.append({"out": o, "in": best})
    return pairs


def find_duplicates(txs: List[Dict[str, Any]],
                    accounts: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rows that look doubled: same real account, date, amount and name.
    `linked_twice` marks groups spread over different account_ids of one
    real account — near-certain duplicates from a bank linked twice. Same
    account_id groups may be genuine repeat charges, so they're 'look'."""
    groups: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for t in txs:
        acct = accounts.get(t.get("account_id"))
        key = (real_account_key(acct) or t.get("account_id"), t.get("date"),
               int(round(_amt(t) * 100)), _norm(tx_name(t)))
        groups.setdefault(key, []).append(t)
    out = []
    for rows in groups.values():
        if len(rows) < 2:
            continue
        first = rows[0]
        out.append({
            "date": first.get("date"), "name": tx_name(first), "amount": _amt(first),
            "count": len(rows),
            "linked_twice": len({r.get("account_id") for r in rows}) > 1,
            "transaction_ids": [r.get("transaction_id") for r in rows],
        })
    out.sort(key=lambda g: (g["date"] or ""), reverse=True)
    return out


def accounts_linked_twice(accounts: List[Dict[str, Any]]) -> int:
    """How many plaid_accounts rows are extra copies of an account already
    linked (same name, mask, type)."""
    seen: Dict[Tuple[str, str, str], int] = {}
    for a in accounts:
        k = real_account_key(a)
        if k is not None:
            seen[k] = seen.get(k, 0) + 1
    return sum(n - 1 for n in seen.values() if n > 1)


def fiscal_year_start(today: date, start_month: int) -> date:
    m = start_month if 1 <= start_month <= 12 else 1
    year = today.year if today.month >= m else today.year - 1
    return date(year, m, 1)


def _add_months(d: date, n: int) -> date:
    m0 = d.month - 1 + n
    return date(d.year + m0 // 12, m0 % 12 + 1, 1)


def month_rows(fy_start: date, today: date, txs: List[Dict[str, Any]],
               posted_by_month: Dict[str, int], unposted_by_month: Dict[str, int],
               closed_months: set) -> List[Dict[str, Any]]:
    """Twelve months of the fiscal year, each with one status:
    future · current · closed · quiet (no activity) · behind (bank rows the
    ledger hasn't posted) · open (posted, not closed yet)."""
    bank_by_month: Dict[str, int] = {}
    review_by_month: Dict[str, int] = {}
    for t in txs:
        k = str(t.get("date") or "")[:7]
        bank_by_month[k] = bank_by_month.get(k, 0) + 1
        if needs_category(t):
            review_by_month[k] = review_by_month.get(k, 0) + 1
    cur_key = today.strftime("%Y-%m")
    out = []
    for i in range(12):
        start = _add_months(fy_start, i)
        key = start.strftime("%Y-%m")
        bank, posted = bank_by_month.get(key, 0), posted_by_month.get(key, 0)
        unposted = unposted_by_month.get(key, 0)
        if start > today:
            status = "future"
        elif key == cur_key:
            status = "current"
        elif key in closed_months:
            status = "closed"
        elif bank == 0 and posted == 0:
            status = "quiet"
        elif unposted > 0:
            status = "behind"
        else:
            status = "open"
        out.append({"month": key, "label": _MONTH_ABBR[start.month],
                    "name": _MONTH_NAME[start.month], "status": status,
                    "bank_rows": bank, "unposted": unposted,
                    "to_review": review_by_month.get(key, 0)})
    return out


# ─── Notices ("Kai noticed") ─────────────────────────────────────────

def transfer_notice(pairs: List[Dict[str, Any]],
                    accounts: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    income = round(sum(-_amt(p["in"]) for p in pairs if counts_as_income(p["in"])), 2)
    spending = round(sum(_amt(p["out"]) for p in pairs if counts_as_spending(p["out"])), 2)
    if not pairs or (income == 0 and spending == 0):
        return None  # pairs the books already treat as neutral cost nothing
    as_what = ("income and spending" if income and spending
               else "income" if income else "spending")
    ex = max(pairs, key=lambda p: p["out"].get("date") or "")
    ex_from = account_label(accounts.get(ex["out"].get("account_id")))
    ex_to = account_label(accounts.get(ex["in"].get("account_id")))
    effects = []
    if income:
        effects.append(f"{_money(income)} to income")
    if spending:
        effects.append(f"{_money(spending)} to spending")
    n = len(pairs)
    lead = "It adds" if n == 1 else f"{n} pairs like it add"
    body = (f"On {_day(_d(ex['out'].get('date')))}, {_money(_amt(ex['out']))} left "
            f"{ex_from} and landed in {ex_to}. That's one transfer, booked twice. "
            f"{lead} {' and '.join(effects)}.")
    return {"kind": "transfer_pairs", "tone": "warn",
            "title": f"Moves between your own accounts are counted as {as_what}",
            "body": body, "count": n, "income": income, "spending": spending,
            "examples": [{"date": p["out"].get("date"), "amount": abs(_amt(p["out"])),
                          "from": account_label(accounts.get(p["out"].get("account_id"))),
                          "to": account_label(accounts.get(p["in"].get("account_id")))}
                         for p in sorted(pairs, key=lambda p: p["out"].get("date") or "",
                                         reverse=True)[:5]],
            "action": {"label": "Review transfer pairs", "target": "transactions:transfers"}}


def duplicate_notice(dups: List[Dict[str, Any]], linked_twice: int,
                     accounts_total: int) -> Optional[Dict[str, Any]]:
    if not dups:
        return None
    ex = dups[:3]
    parts = [f"{g['name'] or 'A transaction'} on {_day(_d(g['date']))}" for g in ex]
    listed = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    twice = "appears twice" if len(ex) == 1 else "each appear twice"
    if any(g["count"] > 2 for g in ex):
        twice = "appears more than once" if len(ex) == 1 else "each appear more than once"
    more = f", and {len(dups) - len(ex)} more like {'it' if len(ex) == 1 else 'them'}" \
        if len(dups) > len(ex) else ""
    body = f"{listed} {twice}{more}."
    if linked_twice:
        body += (f" {accounts_total} accounts are linked, and {linked_twice} "
                 f"{'looks' if linked_twice == 1 else 'look'} like the same bank "
                 f"account connected again.")
    return {"kind": "duplicates", "tone": "warn",
            "title": "Some bank rows look doubled",
            "body": body, "count": len(dups),
            "certain": sum(1 for g in dups if g["linked_twice"]),
            "accounts_linked_twice": linked_twice,
            "examples": [{"date": g["date"], "name": g["name"], "amount": abs(g["amount"]),
                          "count": g["count"]} for g in dups[:5]],
            "action": {"label": "Review duplicates", "target": "transactions:duplicates"}}


def ledger_notice(ledger: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not ledger.get("active"):
        return None
    unposted = int(ledger.get("unposted") or 0)
    if unposted:
        since = _d(ledger.get("oldest_unposted_date"))
        title = f"The ledger stopped posting in {_MONTH_NAME[since.month]}" if since \
            else "The ledger is behind the bank"
        body = (f"{unposted} bank {'transaction' if unposted == 1 else 'transactions'} "
                f"since {_day(since)} {'isn' if unposted == 1 else 'aren'}’t in the ledger, "
                f"so reports leave {'it' if unposted == 1 else 'them'} out. A re-sync rebuilds "
                f"the ledger from your bank, invoices and bills. Nothing is deleted.")
    elif ledger.get("divergence"):
        title = "The ledger doesn’t match your records"
        body = ("Something changed underneath the ledger. A re-sync rebuilds it from "
                "your bank, invoices and bills. Nothing is deleted.")
    else:
        return None
    return {"kind": "ledger", "tone": "bad", "title": title, "body": body,
            "count": unposted,
            "action": {"label": "Re-sync the ledger", "target": "settings:ledger"}}


def stripe_notice(txs: List[Dict[str, Any]], has_stripe_account: bool) -> Optional[Dict[str, Any]]:
    rows = [t for t in txs if _amt(t) < 0 and t.get("reconciliation_status") == "unmatched"
            and "stripe" in _norm(tx_name(t))]
    if not rows:
        return None
    total = round(sum(-_amt(t) for t in rows), 2)
    n = len(rows)
    noun = "deposit" if n == 1 else "deposits"
    if has_stripe_account:
        body = (f"{n} Stripe {noun} ({_money(total)}) haven’t matched a payout from your "
                f"connected Stripe account. If they come from a different Stripe account, "
                f"count them as income instead.")
        if n == 1:
            body = body.replace("haven’t", "hasn’t")
    else:
        body = (f"No Stripe account is connected here, so {n} Stripe {noun} "
                f"({_money(total)}) can’t be matched to payouts.")
    return {"kind": "stripe_deposits", "tone": "warn",
            "title": "Stripe deposits aren’t matching payouts",
            "body": body, "count": n, "amount": total,
            "action": {"label": "Open matching", "target": "close"}}


def sync_notice(last_sync: Optional[datetime], now: datetime) -> Optional[Dict[str, Any]]:
    if last_sync is None:
        return None
    days = (now - last_sync).days
    if days < SYNC_STALE_DAYS:
        return None
    return {"kind": "bank_sync", "tone": "warn",
            "title": f"The bank hasn’t synced in {days} days",
            "body": "New transactions won’t show up until it does. A sync takes a few seconds.",
            "count": days, "action": {"label": "Sync bank", "target": "sync"}}


def compose_headline(bank: Dict[str, Any], path: Dict[str, Any],
                     months: List[Dict[str, Any]], ledger: Dict[str, Any]) -> Dict[str, str]:
    if not bank.get("linked"):
        return {"lead": "Your books start", "emphasis": "when your bank is connected.",
                "detail": "Link the account your business runs through, and every "
                          "transaction lands here to sort."}
    behind = [m for m in months if m["status"] == "behind"]
    to_review = path["categorize"]["total"] - path["categorize"]["done"]
    unmatched = path["match"]["total"] - path["match"]["matched"]
    bits = []
    if ledger.get("active") and ledger.get("last_entry_date"):
        d = _d(ledger["last_entry_date"])
        if d and behind:
            bits.append(f"The ledger last posted on {_MONTH_NAME[d.month]} {d.day}.")
    if to_review:
        bits.append(f"{to_review} {'transaction still needs' if to_review == 1 else 'transactions still need'} a category")
    if unmatched:
        verb = "isn’t" if unmatched == 1 else "aren’t"
        bits.append(f"{unmatched} {'deposit' if unmatched == 1 else 'deposits'} {verb} matched "
                    f"to where {'it' if unmatched == 1 else 'they'} came from")
    detail = ""
    if bits:
        head = [b for b in bits if b.endswith(".")]
        tail = [b for b in bits if not b.endswith(".")]
        detail = " ".join(head)
        if tail:
            detail = (detail + " " if detail else "") + ", and ".join(tail) + "."
    if behind:
        n = len(behind)
        return {"lead": "Your books are",
                "emphasis": f"{number_word(n)} {'month' if n == 1 else 'months'} behind.",
                "detail": detail}
    if to_review or unmatched:
        n = to_review + unmatched
        return {"lead": "Your books are close.",
                "emphasis": f"{n} {'thing needs' if n == 1 else 'things need'} you.",
                "detail": detail}
    return {"lead": "Your books are", "emphasis": "current.",
            "detail": "Everything is categorized and matched. Close last month to lock it."}


# ─── Year so far: the Reports tab's own P&L ──────────────────────────

def year_so_far(biz: str, biz_row: Dict[str, Any]) -> Dict[str, Any]:
    import gl_reports
    import reports_engine
    import reports_router
    period, from_, to = reports_router._fiscal_period(biz_row, "this_year", None, None)
    basis = reports_router._basis_for(biz_row, None)
    out = reports_router._gl_or_fallback(
        biz,
        lambda: gl_reports.gl_profit_and_loss(biz, period, None, from_, to, basis=basis),
        lambda: reports_engine.profit_and_loss(biz, period, None, from_, to))
    cur = out.get("current") or {}
    rev, exp = cur.get("revenue") or {}, cur.get("expenses") or {}
    return {
        "range": out.get("range"), "source": out.get("source"),
        "basis": basis if out.get("source") == "gl" else "cash",
        "money_in": rev.get("gross_revenue", 0.0),
        "money_out": exp.get("total", 0.0),
        "net": cur.get("net_income", 0.0),
        "buckets": [{"bucket": b.get("bucket"), "label": b.get("label"),
                     "total": b.get("total"), "pct": b.get("pct")}
                    for b in (exp.get("by_bucket") or [])],
    }


# ─── The overview ────────────────────────────────────────────────────

def build_overview(biz: str, biz_row: Dict[str, Any],
                   now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    today = now.date()
    failed: List[str] = []
    fin = ((biz_row.get("settings") or {}).get("financial") or {})
    try:
        fy_month = int(fin.get("fiscal_year_start_month") or 1)
    except (TypeError, ValueError):
        fy_month = 1
    fy_start = fiscal_year_start(today, fy_month)

    def safe(name: str, fn: Callable[[], Any], default: Any) -> Any:
        try:
            return fn()
        except Exception as e:  # one source never costs the page
            logger.warning(f"[bk-overview] {name} failed for {biz}: {e}")
            failed.append(name)
            return default

    # Round 1 — reads that don't depend on each other.
    with ThreadPoolExecutor(max_workers=8) as pool:
        f_items = pool.submit(_get, f"/plaid_items?business_id=eq.{biz}"
                              f"&select=item_id,institution_name,status,last_sync_at,last_error")
        f_accts = pool.submit(_get, f"/plaid_accounts?business_id=eq.{biz}&deleted_at=is.null"
                              f"&select=account_id,item_id,name,official_name,type,subtype,mask,"
                              f"included_in_bookkeeping,is_trust_account")
        f_je = pool.submit(_get, f"/journal_entries?business_id=eq.{biz}&status=eq.active"
                           f"&select=entry_date,source_type,source_id,created_at"
                           f"&order=entry_date.desc&limit=50000")
        f_queue = pool.submit(_get, f"/gl_sync_queue?business_id=eq.{biz}&processed_at=is.null"
                              f"&select=enqueued_at&order=enqueued_at.asc&limit=5000")
        f_alarm = pool.submit(_get, f"/gl_divergence_alarms?business_id=eq.{biz}&status=eq.active"
                              f"&select=detected_at&order=detected_at.desc&limit=1")
        f_bills = pool.submit(_get, f"/bills?business_id=eq.{biz}"
                              f"&status=in.({','.join(_OPEN_BILL)})"
                              f"&select=id,vendor_name,amount,due_date,status,category,is_recurring"
                              f"&order=due_date.asc.nullslast&limit=500")
        f_periods = pool.submit(_get, f"/accounting_periods?business_id=eq.{biz}"
                                f"&period_type=eq.month&status=eq.closed"
                                f"&select=period_start&limit=500")
        f_year = pool.submit(year_so_far, biz, biz_row)

        items = safe("bank", f_items.result, [])
        accounts = safe("bank", f_accts.result, [])
        journal = safe("ledger", f_je.result, None)
        queue = safe("ledger", f_queue.result, [])
        # The alarms table may predate a deploy's migration — absent is "none".
        try:
            alarms = f_alarm.result()
        except Exception:
            alarms = []
        bills = safe("bills", f_bills.result, None)
        closed_rows = safe("months", f_periods.result, [])
        year = safe("year", f_year.result, None)

    acct_by_id = {a["account_id"]: a for a in accounts if a.get("account_id")}
    included = [a for a in accounts if a.get("included_in_bookkeeping")]
    trust_ids = {a["account_id"] for a in included if a.get("is_trust_account")}

    # Round 2 — every settled, in-books bank row on an included account.
    txs: List[Dict[str, Any]] = []
    if included:
        ids = ",".join(a["account_id"] for a in included)
        txs = safe("transactions", lambda: _get(
            f"/plaid_transactions?business_id=eq.{biz}&account_id=in.({ids})"
            f"&pending=eq.false&excluded_from_books=eq.false"
            f"&select=transaction_id,account_id,amount,date,name,merchant_name,"
            f"business_category,plaid_category_primary,plaid_category_detail,"
            f"reconciliation_status,reconciled_to_payout_id"
            f"&order=date.desc&limit={_TX_LIMIT}"), [])
    txs = [t for t in txs if _amt(t) != 0]
    books_txs = [t for t in txs if t.get("account_id") not in trust_ids]  # trust is client money

    # ── Bank ──
    stamps = [s for s in (_ts(i.get("last_sync_at")) for i in items) if s]
    last_sync = max(stamps) if stamps else None
    linked_twice = accounts_linked_twice(accounts)
    bank = {
        "linked": bool(items),
        "institutions": sorted({i.get("institution_name") for i in items if i.get("institution_name")}),
        "last_sync_at": last_sync.isoformat() if last_sync else None,
        "sync_stale": bool(last_sync and (now - last_sync).days >= SYNC_STALE_DAYS),
        "errors": [{"institution": i.get("institution_name"), "error": i.get("last_error")}
                   for i in items if i.get("last_error")],
        "accounts_linked": len(accounts),
        "accounts_linked_twice": linked_twice,
        "accounts_in_use": [{"account_id": a["account_id"], "label": account_label(a),
                             "type": a.get("type"), "trust": bool(a.get("is_trust_account"))}
                            for a in included],
    }

    # ── Ledger ──
    ledger: Dict[str, Any] = {"active": False, "state": "unknown"}  # journal read failed
    unposted_by_month: Dict[str, int] = {}
    posted_by_month: Dict[str, int] = {}
    if journal is not None:
        posted_ids = {je.get("source_id") for je in journal
                      if je.get("source_type") == "plaid_transaction"}
        for je in journal:
            k = str(je.get("entry_date") or "")[:7]
            posted_by_month[k] = posted_by_month.get(k, 0) + 1
        unposted = [t for t in txs if t.get("transaction_id") not in posted_ids] if journal else []
        for t in unposted:
            k = str(t.get("date") or "")[:7]
            unposted_by_month[k] = unposted_by_month.get(k, 0) + 1
        oldest_unposted = min((str(t.get("date")) for t in unposted if t.get("date")), default=None)
        created = [s for s in (_ts(je.get("created_at")) for je in journal) if s]
        oldest_q = _ts(queue[0].get("enqueued_at")) if queue else None
        last_entry = journal[0].get("entry_date") if journal else None
        posted_through = None
        if journal:
            if oldest_unposted:
                posted_through = (_d(oldest_unposted) - timedelta(days=1)).isoformat()  # type: ignore[operator]
            else:
                newest_tx = max((str(t.get("date")) for t in txs if t.get("date")), default=None)
                posted_through = max(filter(None, [newest_tx, str(last_entry or "")[:10]]), default=None)
        ledger = {
            "active": bool(journal),
            "last_entry_date": str(last_entry)[:10] if last_entry else None,
            "last_posted_at": max(created).isoformat() if created else None,
            "posted_through": posted_through,
            "unposted": len(unposted),
            "oldest_unposted_date": oldest_unposted,
            "queue_waiting": len(queue),
            "queue_stale": bool(oldest_q and (now - oldest_q) > timedelta(minutes=QUEUE_STALE_MINUTES)),
            "divergence": bool(alarms),
            "divergence_since": (alarms[0].get("detected_at") if alarms else None),
        }
        ledger["state"] = ("not_started" if not journal else
                           "behind" if (ledger["unposted"] or ledger["divergence"]) else "current")

    # ── Months ──
    closed = {str(r.get("period_start") or "")[:7] for r in closed_rows}
    months = month_rows(fy_start, today, books_txs, posted_by_month, unposted_by_month, closed)
    past_with_activity = [m for m in months if m["status"] in ("open", "behind", "closed")]

    # ── Path to current ──
    deposits = [t for t in books_txs if _amt(t) < 0]
    matched = sum(1 for t in deposits if t.get("reconciliation_status") in _MATCHED)
    unmatched = sum(1 for t in deposits if t.get("reconciliation_status") == "unmatched")
    path = {
        "sync": {"last_sync_at": bank["last_sync_at"], "stale": bank["sync_stale"]},
        "categorize": {"done": sum(1 for t in books_txs if not needs_category(t)),
                       "total": len(books_txs)},
        "match": {"matched": matched, "total": matched + unmatched,
                  "ignored": sum(1 for t in deposits if t.get("reconciliation_status") == "ignored")},
        "close": {"closed": sum(1 for m in past_with_activity if m["status"] == "closed"),
                  "total": len(past_with_activity),
                  "next": next((m["month"] for m in months if m["status"] in ("open", "behind")), None)},
    }

    # ── Bills ──
    bills_out = None
    if bills is not None:
        overdue, soon = [], []
        horizon = today + timedelta(days=30)
        for b in bills:
            due = _d(b.get("due_date"))
            row = {"id": b.get("id"), "vendor": b.get("vendor_name"),
                   "amount": float(b.get("amount") or 0), "due_date": b.get("due_date"),
                   "days_late": (today - due).days if due and due < today else 0}
            if due and due < today:
                overdue.append(row)
            elif due and due <= horizon:
                soon.append(row)
        bills_out = {"overdue": overdue[:5], "overdue_count": len(overdue),
                     "overdue_total": round(sum(b["amount"] for b in overdue), 2),
                     "due_soon": soon[:5], "due_soon_count": len(soon),
                     "due_soon_total": round(sum(b["amount"] for b in soon), 2),
                     "open_count": len(bills)}

    # ── What Kai noticed ──
    pairs = find_transfer_pairs(books_txs, acct_by_id)
    dups = find_duplicates(books_txs, acct_by_id)
    has_stripe = bool((biz_row.get("stripe_account_id") or "").strip())
    noticed = [n for n in (
        ledger_notice(ledger),
        transfer_notice(pairs, acct_by_id),
        duplicate_notice(dups, linked_twice, len(accounts)),
        stripe_notice(books_txs, has_stripe),
        sync_notice(last_sync, now),
    ) if n]
    noticed.sort(key=lambda n: 0 if n["tone"] == "bad" else 1)

    # ── Latest from the bank ──
    pair_ids = {p[s].get("transaction_id") for p in pairs for s in ("out", "in")}
    dup_ids = {tid for g in dups for tid in g["transaction_ids"][1:]}
    recent = [{
        "transaction_id": t.get("transaction_id"), "date": t.get("date"),
        "name": tx_name(t), "amount": _amt(t),
        "account": account_label(acct_by_id.get(t.get("account_id"))),
        "category": t.get("business_category"),
        "needs_category": needs_category(t),
        "transfer": t.get("transaction_id") in pair_ids,
        "duplicate": t.get("transaction_id") in dup_ids,
        "matched": t.get("reconciliation_status") in _MATCHED,
    } for t in books_txs[:8]]

    return {
        "ok": True,
        "business_id": biz,
        "as_of": now.isoformat(),
        "fiscal_year_start": fy_start.isoformat(),
        "headline": compose_headline(bank, path, months, ledger),
        "bank": bank,
        "ledger": ledger,
        "path": path,
        "year": year,
        "months": months,
        "bills": bills_out,
        "noticed": noticed,
        "recent": recent,
        "counts": {
            "to_review": path["categorize"]["total"] - path["categorize"]["done"],
            "deposits_unmatched": unmatched,
            "months_open": sum(1 for m in past_with_activity if m["status"] != "closed"),
            "bills_overdue": bills_out["overdue_count"] if bills_out else 0,
        },
        "sources_failed": sorted(set(failed)),
    }


@router.get("/overview")
def overview(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    from plaid_router import _require_reader
    _require_reader(biz, user)
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,type,settings,stripe_account_id&limit=1") or []
    return build_overview(biz, rows[0] if rows else {"id": biz})
