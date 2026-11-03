"""
chief_transactions.py — Chief reads the bank, row by row.

Kevin, 2026-10-30: "are you able to go through my transactions and get any
that was given to kmj paypal kmj ministries kevin and give a total amount
that was given so far for the year?" Chief had only counts in its prompt
(how many deposits were unreconciled, and their sum) and no way to read a
single row, so it said "let me search" and then told him to search the
Transactions screen himself, guessing along the way that "given to" meant
money coming in.

search_transactions is that search, run by Chief:

    words ........ any of them, matched against the bank's description and
                   the merchant name (the Transactions search box's match)
    direction .... in | out | both (both unless the ask is clear)
    dates ........ Jan 1 to today unless named
    status ....... unreconciled | reconciled | all

THE SERVER ADDS UP. Every match is read (paged; past the cap the search
fails rather than passing a part off as the whole) and summed here, in and
out kept apart, by status and by word. Chief quotes those numbers and the
answer check holds them as evidence. The rows it shows are a sample, and a
sample is never summed by the model (the 10-row-cap lesson, 2026-10-09).

Counted means in the books: not pending, not excluded. Matches that are
pending or excluded are reported on their own line, never silently dropped
or silently added.

WHO MAY: the Transactions screen's own reader gate (plaid_router.
_require_reader: owner, accountant, a team seat, a church's finance gate
and money wall), checked as the person talking. No person (a scheduled
run) means no rows. The verb is sensitive and Chief-only: bank rows never
go out on the agent surface.

ONE PAYLOAD, TWO USES. Mid-turn it is a read the model answers from. As an
[ACTION:] tag the same payload is a show_view card (type show_view, view
transactions), so the table lands under Chief's words.

Switched by CHIEF_BANK_SEARCH: off | owner | on, owner when unset (the
businesses the platform owner owns, until a Thursday flip).

FILED IS NOT MATCHED (2026-11-03). Kevin asked why the rows Chief filed were
"still under all transactions like we didn't do any transaction". Chief
answered from this card's "Reconciled: No" on every row, as if filing were
half the job. It isn't: All transactions lists every bank row for good;
filing (a category, or what the money is) takes a row out of To review.
"Reconciled" here was reconciliation_status, which only says whether a row
was tied to a payout, invoice, bill or a deposit of gifts; a bill paid
straight from the bank has nothing to tie to and stays unmatched, and that
is normal. So each row now says what it's filed under (or Waiting), the
totals count filed and waiting, the old column reads Matched, and status
can ask for waiting or filed rows.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import date
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import sb_clients

logger = logging.getLogger("chief_transactions")

ROWS_SHOWN = 25
MAX_WORDS = 6
_PAGE = 1000
_ROW_CAP = 5000

DIRECTIONS = ("both", "in", "out")
STATUSES = ("all", "unreconciled", "reconciled", "waiting", "filed")
FILED_STATUSES = ("waiting", "filed")      # read from the rows, not the query

_SELECT = ("select=transaction_id,date,name,merchant_name,amount,pending,"
           "excluded_from_books,reconciliation_status,business_category,business_subcategory")

COLUMNS = [
    {"key": "date", "label": "Date", "kind": "date"},
    {"key": "description", "label": "Description", "kind": "text"},
    {"key": "way", "label": "In / out", "kind": "text"},
    {"key": "amount", "label": "Amount", "kind": "money"},
    {"key": "filed", "label": "Filed under", "kind": "text"},
    {"key": "status", "label": "Matched", "kind": "text"},
]

# What the money IS, when the answer was a kind rather than a spending line.
_KIND_WORDS = {"income": "Income", "owner": "Owner's money", "transfer": "Move between accounts",
               "gifts": "Gifts arriving"}

TOOL = {
    "name": "search_transactions",
    "description": (
        "Search this business's bank transactions (the linked accounts in the books) and get "
        "exact totals, with what each row is filed under. Use it for any question about specific "
        "bank rows: 'what did we pay KMJ this year', 'deposits from PayPal', 'which of these are "
        "filed'. FILED means the row has an answer (a category, or what the money is): it has left "
        "To review, and it stays in All transactions for good (the full list, not a to-do list). "
        "MATCHED (status reconciled) only means tied to a payout, invoice, bill or a deposit of "
        "gifts; a bill paid from the bank has nothing to tie to and stays unmatched, which is "
        "normal, never unfinished. words: any of them matches the bank description or merchant "
        "name (leave empty for every transaction in the dates). direction: in, out or both; "
        "use both when 'given to'/'from' could mean either. Dates default to Jan 1 through "
        "today. The totals cover EVERY match, not just the rows shown: quote them, never "
        "add the rows yourself. To put the table on screen, emit the same call as an "
        "[ACTION:] tag."),
    "input_schema": {
        "type": "object",
        "properties": {
            "words": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_WORDS,
                      "description": "Names or words to match, any of them (e.g. [\"kmj\", \"paypal\"])."},
            "direction": {"type": "string", "enum": list(DIRECTIONS),
                          "description": "in = money into the account, out = money paid out. Default both."},
            "date_from": {"type": "string", "description": "YYYY-MM-DD. Default Jan 1 this year."},
            "date_to": {"type": "string", "description": "YYYY-MM-DD. Default today."},
            "status": {"type": "string", "enum": list(STATUSES),
                       "description": "waiting (no category yet), filed, unreconciled (not tied to a "
                                      "payout, bill or gifts), reconciled (tied to one), or all (default)."},
        },
    },
}


class _Unavailable(Exception):
    """A read came back as a failure, not as nothing."""


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHIEF_BANK_SEARCH") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def switched_on(business_id: Any) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        import member_asks
        return member_asks.platform_church(business_id)
    return False


# ─── Arguments ────────────────────────────────────────────────────────

def clean_words(raw: Any) -> List[str]:
    """Letters, digits, spaces, apostrophes and hyphens only: nothing that
    can reach the PostgREST or=() grammar or the query string. Lowercased,
    de-duplicated, at most MAX_WORDS."""
    if isinstance(raw, str):
        raw = [raw]
    out: List[str] = []
    for w in raw or []:
        w = re.sub(r"[^\w '\-]", "", str(w)).replace("_", " ")
        w = " ".join(w.split()).lower()
        if w and w not in out:
            out.append(w)
    return out[:MAX_WORDS]


def _day(raw: Any, default: date) -> Optional[date]:
    if raw in (None, ""):
        return default
    try:
        return date.fromisoformat(str(raw).strip()[:10])
    except ValueError:
        return None


def parse_args(action: Dict[str, Any], today: Optional[date] = None) -> Tuple[Optional[Dict[str, Any]], str]:
    """(args, "") or (None, why)."""
    today = today or date.today()
    direction = str(action.get("direction") or "both").strip().lower()
    if direction not in DIRECTIONS:
        return None, f"direction must be one of {', '.join(DIRECTIONS)}"
    status = str(action.get("status") or "all").strip().lower()
    if status not in STATUSES:
        return None, f"status must be one of {', '.join(STATUSES)}"
    d_from = _day(action.get("date_from"), date(today.year, 1, 1))
    d_to = _day(action.get("date_to"), today)
    if d_from is None or d_to is None:
        return None, "dates must be written YYYY-MM-DD"
    if d_from > d_to:
        return None, f"the start date {d_from} is after the end date {d_to}"
    return {"words": clean_words(action.get("words")), "direction": direction,
            "status": status, "date_from": d_from, "date_to": d_to}, ""


def query_path(business_id: str, account_ids: List[str], args: Dict[str, Any]) -> str:
    """The plaid_transactions read, without paging. Pending and excluded
    rows are fetched too: they are reported apart, not dropped."""
    parts = [f"business_id=eq.{business_id}",
             "account_id=in.(" + ",".join(account_ids) + ")",
             f"date=gte.{args['date_from'].isoformat()}",
             f"date=lte.{args['date_to'].isoformat()}"]
    # Plaid's sign: negative is money in, positive is money out.
    if args["direction"] == "in":
        parts.append("amount=lt.0")
    elif args["direction"] == "out":
        parts.append("amount=gt.0")
    if args["status"] == "unreconciled":
        parts.append("reconciliation_status=eq.unmatched")
    elif args["status"] == "reconciled":
        parts.append("reconciliation_status=neq.unmatched")
    if args["words"]:
        terms = []
        for w in args["words"]:
            q = quote(w, safe="'-")
            terms += [f"name.ilike.*{q}*", f"merchant_name.ilike.*{q}*"]
        parts.append("or=(" + ",".join(terms) + ")")
    import bank_money
    parts.append(_SELECT + bank_money.cols())
    parts.append("order=date.desc,transaction_id.asc")
    return "/plaid_transactions?" + "&".join(parts)


# ─── Adding up ────────────────────────────────────────────────────────

def _amount(t: Dict[str, Any]) -> float:
    try:
        return float(t.get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def _text(t: Dict[str, Any]) -> str:
    return f"{t.get('name') or ''} {t.get('merchant_name') or ''}".lower()


def _side() -> Dict[str, Any]:
    return {"count": 0, "money_in": 0.0, "money_out": 0.0}


def _add(side: Dict[str, Any], t: Dict[str, Any]) -> None:
    a = _amount(t)
    side["count"] += 1
    if a < 0:
        side["money_in"] += -a
    else:
        side["money_out"] += a


def _rounded(side: Dict[str, Any]) -> Dict[str, Any]:
    return {**side, "money_in": round(side["money_in"], 2), "money_out": round(side["money_out"], 2)}


def waiting(t: Dict[str, Any]) -> bool:
    """Still in To review: no answer yet (the screen's own rule)."""
    import bank_money
    return bank_money.needs_category(t)


def filed_as(t: Dict[str, Any], names: Optional[Dict[str, str]] = None) -> str:
    """What a row is filed under, in the business's words: its spending line
    (and label), what the money is, or Waiting."""
    import bank_money
    k = bank_money.kind(t)
    if k:
        return _KIND_WORDS.get(k, k)
    if waiting(t):
        return "Waiting"
    cat = str(t.get("business_category") or "")
    line = (names or {}).get(cat) or cat.replace("_", " ").capitalize()
    sub = str(t.get("business_subcategory") or "").strip()
    return f"{line} · {sub}" if sub else line


def tally(rows: List[Dict[str, Any]], words: List[str]) -> Dict[str, Any]:
    """Every total the answer may quote. `counted` is the books' view:
    posted and not excluded."""
    counted = [t for t in rows if not t.get("pending") and not t.get("excluded_from_books")]
    total, unrec, rec, filed, wait = _side(), _side(), _side(), _side(), _side()
    by_word = {w: _side() for w in words}
    for t in counted:
        _add(total, t)
        _add(unrec if t.get("reconciliation_status") == "unmatched" else rec, t)
        _add(wait if waiting(t) else filed, t)
        text = _text(t)
        for w in words:
            if w in text:
                _add(by_word[w], t)
    pending, excluded = _side(), _side()
    for t in rows:
        if t.get("pending"):
            _add(pending, t)
        elif t.get("excluded_from_books"):
            _add(excluded, t)
    return {
        "counted": counted,
        "total": _rounded(total),
        "unreconciled": _rounded(unrec),
        "reconciled": _rounded(rec),
        "filed": _rounded(filed),
        "waiting": _rounded(wait),
        "by_word": {w: _rounded(s) for w, s in by_word.items()},
        "pending": _rounded(pending),
        "excluded": _rounded(excluded),
    }


_MATCHED = {"auto_matched": "Yes", "manual_matched": "Yes", "ignored": "Set aside"}


def display_row(t: Dict[str, Any], names: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    a = _amount(t)
    name = (t.get("name") or "").strip()
    merchant = (t.get("merchant_name") or "").strip()
    desc = name or merchant or "(no description)"
    if merchant and name and merchant.lower() not in name.lower():
        desc = f"{merchant} · {name}"
    return {
        "id": t.get("transaction_id"),
        "date": str(t.get("date") or "")[:10],
        "description": desc[:80],
        "way": "In" if a < 0 else "Out",
        # The business's view: money in is positive, money out negative.
        "amount": round(-a, 2),
        "filed": filed_as(t, names),
        # Tied to a payout, bill or gifts. Nothing to tie to is normal: a dash, not "No".
        "status": _MATCHED.get(str(t.get("reconciliation_status") or ""), "—"),
    }


def _money(n: float) -> str:
    return f"${n:,.2f}"


def _sides_text(side: Dict[str, Any], direction: str) -> str:
    bits = []
    if direction in ("both", "in"):
        bits.append(f"{_money(side['money_in'])} in")
    if direction in ("both", "out"):
        bits.append(f"{_money(side['money_out'])} out")
    return " and ".join(bits)


def summarize(args: Dict[str, Any], t: Dict[str, Any],
              names: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """The payload: card fields, the totals, and the sentences."""
    words, direction = args["words"], args["direction"]
    span = f"{args['date_from'].isoformat()} to {args['date_to'].isoformat()}"
    what = ("matching " + " or ".join(f"'{w}'" for w in words)) if words else "of every kind"
    status_word = {"unreconciled": "unmatched ", "reconciled": "matched "}.get(args["status"], "")
    tail = {"waiting": " still waiting for a category", "filed": " already filed"}.get(args["status"], "")
    total = t["total"]
    counted = t["counted"]
    rows = [display_row(r, names) for r in counted[:ROWS_SHOWN]]

    if not counted:
        result = f"No {status_word}bank transactions{tail} {what} from {span} are in the books."
    else:
        result = (f"{total['count']} {status_word}bank transactions{tail} {what} from {span}: "
                  f"{_sides_text(total, direction)}.")
        if args["status"] not in FILED_STATUSES:
            f, w = t["filed"], t["waiting"]
            result += (f" Filed: {f['count']}. Still waiting for a category (in To review): {w['count']}" +
                       (f" ({_sides_text(w, direction)})" if w["count"] else "") + ".")
        if len(words) > 1:
            per = "; ".join(f"'{w}' {s['count']} ({_sides_text(s, direction)})"
                            for w, s in t["by_word"].items())
            result += f" By word, a row can match more than one: {per}."
        result += (f" Showing the {len(rows)} most recent." if total["count"] > len(rows)
                   else " All shown.")
    for key, why in (("pending", "still pending at the bank"), ("excluded", "excluded from the books")):
        s = t[key]
        if s["count"]:
            result += f" Not counted: {s['count']} {why} ({_sides_text(s, direction)})."

    title = "Bank transactions" + (f": {', '.join(words)}" if words else "") + f" · {span}"
    if counted:
        label = f"🏦 {total['count']} bank transactions · {_sides_text(total, direction)}"
    else:
        label = "🏦 No matching bank transactions"
    single = {"in": total["money_in"], "out": total["money_out"]}.get(direction)
    payload: Dict[str, Any] = {
        "type": "show_view",
        "view": "transactions",
        "filter": args["status"],
        "title": title,
        "form": "list",
        "date_key": "date",
        "columns": COLUMNS,
        "rows": rows,
        "summary": {"count": total["count"], **({"total": single} if single is not None else {})},
        "limit_reached": total["count"] > len(rows),
        "result": result,
        "label": label[:120],
        "totals": {k: t[k] for k in ("total", "unreconciled", "reconciled", "filed", "waiting",
                                     "by_word", "pending", "excluded")},
        "search": {"words": words, "direction": direction, "status": args["status"],
                   "date_from": args["date_from"].isoformat(), "date_to": args["date_to"].isoformat()},
        # The second pass reads this when the card was drawn by a tag.
        "speak": result,
        "nav": {"tab": "operate", "sub": "bookkeeping"},
    }
    if counted:
        payload["note_for_chief"] = (
            "These totals are the server's, over every match: quote them, do not re-add the rows. "
            "A word match can include refunds or moves between the business's own accounts; say "
            "so if it matters and offer to look at any row. " + FILED_NOTE)
    else:
        payload["note_for_chief"] = (
            "Genuinely nothing matched in these dates: say so plainly. Offer other words or dates "
            "(banks often shorten names, e.g. 'PAYPAL *KMJMIN'); never invent rows.")
    return payload


FILED_NOTE = (
    "'Filed under' is what each row was answered as; Waiting means it is still in To review. A filed "
    "row stays in All transactions for good: that tab is the whole bank list, not a to-do list. "
    "'Matched' only means tied to a payout, invoice, bill or a deposit of gifts; a bill paid from the "
    "bank has nothing to tie to, so a dash there is normal. Never call filed rows unreconciled or "
    "unfinished. For what still needs an answer, search with status waiting, or use bank_to_file.")


# ─── Reading ──────────────────────────────────────────────────────────

def _get(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if rows is None:
        raise _Unavailable(path.split("?")[0])
    return rows


def _read_all(path: str) -> Optional[List[Dict[str, Any]]]:
    """Every match, paged; the offset advances by what came back and an
    empty page proves the end. None when there are more than the cap."""
    rows: List[Dict[str, Any]] = []
    while True:
        page = _get(f"{path}&limit={_PAGE}&offset={len(rows)}")
        if not page:
            return rows
        rows.extend(page)
        if len(rows) > _ROW_CAP:
            return None


def _book_accounts(business_id: str) -> List[str]:
    rows = _get(f"/plaid_accounts?business_id=eq.{business_id}"
                f"&included_in_bookkeeping=eq.true&deleted_at=is.null&select=account_id")
    return [r["account_id"] for r in rows if r.get("account_id")]


def _authorize(business_id: str) -> Optional[str]:
    """None when the person talking may read bank rows; else why not."""
    from chief_of_staff import _TURN_USER_ID
    user_id = _TURN_USER_ID.get()
    if not user_id:
        return "Bank transactions are read only for a signed-in person who can see the books."
    from fastapi import HTTPException
    import plaid_router
    try:
        plaid_router._require_reader(business_id, SimpleNamespace(id=user_id))
    except HTTPException as e:
        detail = e.detail.get("message") if isinstance(e.detail, dict) else e.detail
        return str(detail or "This login can't see the bank transactions.")
    return None


def _fail(msg: str) -> Dict[str, Any]:
    logger.info(f"search_transactions failed: {msg}")
    return {"type": "search_transactions", "result": msg, "label": "Bank search", "failed": True}


def search(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    if not switched_on(business_id):
        return _fail("Searching bank transactions isn't switched on for this business yet. Say so "
                     "plainly and point them to Bookkeeping → Transactions, which has the same search.")
    args, why = parse_args(action)
    if args is None:
        return _fail(why)
    refused = _authorize(business_id)
    if refused:
        return _fail(refused)
    try:
        accounts = _book_accounts(business_id)
        if not accounts:
            return {"type": "search_transactions", "label": "Bank search",
                    "result": "No bank account is in the books yet, so there are no transactions to search.",
                    "note_for_chief": "Say no bank is linked (or none is included in the books); do not report $0."}
        rows = _read_all(query_path(business_id, accounts, args))
    except _Unavailable as e:
        logger.warning(f"[chief_tx] read failed: {e}")
        return _fail("The bank transactions couldn't be read just now. This is not a $0 result: "
                     "say the search didn't run and offer to try again.")
    if rows is None:
        return _fail(f"More than {_ROW_CAP:,} transactions match, too many to add up in one search. "
                     "Narrow the dates or add words.")
    if args["status"] in FILED_STATUSES:
        want = args["status"] == "waiting"
        rows = [r for r in rows if waiting(r) == want]
    try:
        import expense_lines
        names = expense_lines.names(business_id)   # a church reads Ministry & operations, not operating
    except Exception:
        names = {}
    return summarize(args, tally(rows, args["words"]), names)


async def handle_search_transactions(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(search, str(biz["id"]), action or {})
