"""
bank_picks.py — reading the bank to pick transactions from: the housing
allowance's payments (housing_allowance.py) and the funds for the year
(funds.py) both start here.

    accounts ......... the accounts in the books: the Transactions screen's
                       own (included_in_bookkeeping, not removed)
    history_starts ... the first day the app has a row for; a payment before
                       it can't be picked here, and every screen says so
    year_rows ........ every cleared row of one year in those accounts,
                       money out, money in, or both: paged (an empty page
                       proves the end), and past the cap a failure, never a
                       part passed off as the whole
    words ............ a row's description as the bank and the merchant say it
    repeats .......... rows of the same amount and the same payee (the
                       description without its reference numbers): a regular
                       transfer, offered first
    read_all ......... any read that can pass 1,000 rows, paged: PostgREST
                       answers at most that many whatever the limit asks,
                       so one big limit quietly reads a part

Each caller passes its own `get`, which raises that module's Unavailable on
a failed read, so a failure there is never "no rows".
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

Get = Callable[[str], List[Dict[str, Any]]]

PAGE = 1000
CAP = 10_000
SELECT = "transaction_id,account_id,date,name,merchant_name,amount,pending,excluded_from_books"


class TooMany(Exception):
    """More rows than can be read at once."""


def q(v: Any) -> str:
    return quote(str(v), safe="")


def in_(ids: Any) -> str:
    return "in.(" + ",".join(q(i) for i in ids) + ")"


def num(v: Any) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def accounts(business_id: str, get: Get) -> List[str]:
    rows = get(f"/plaid_accounts?business_id=eq.{q(business_id)}&included_in_bookkeeping=eq.true"
               "&deleted_at=is.null&select=account_id")
    return [str(r["account_id"]) for r in rows if r.get("account_id")]


def history_starts(business_id: str, accts: List[str], get: Get) -> Optional[str]:
    if not accts:
        return None
    rows = get(f"/plaid_transactions?business_id=eq.{q(business_id)}&account_id={in_(accts)}"
               "&select=date&order=date.asc&limit=1")
    if not rows:
        return None
    return str(rows[0].get("date") or "")[:10] or None


def read_all(path: str, get: Get, cap: int = CAP) -> List[Dict[str, Any]]:
    """Every row of a read, a page at a time (an empty page proves the end);
    past the cap a failure. `path` names a stable order and no limit."""
    rows: List[Dict[str, Any]] = []
    while True:
        page = get(f"{path}&limit={PAGE}" + (f"&offset={len(rows)}" if rows else ""))
        if not page:
            return rows
        rows.extend(page)
        if len(rows) > cap:
            raise TooMany(f"more than {cap:,} rows")


def year_rows(business_id: str, accts: List[str], year: int, get: Get,
              direction: str = "out") -> List[Dict[str, Any]]:
    if not accts:
        return []
    sign = {"out": "&amount=gt.0", "in": "&amount=lt.0"}.get(direction, "")
    return read_all(f"/plaid_transactions?business_id=eq.{q(business_id)}&account_id={in_(accts)}"
                    f"&date=gte.{year}-01-01&date=lte.{year}-12-31{sign}&pending=eq.false"
                    f"&select={SELECT}&order=date.asc,transaction_id.asc", get)


def words(t: Dict[str, Any]) -> str:
    name = " ".join(str(t.get("name") or "").split())
    merchant = " ".join(str(t.get("merchant_name") or "").split())
    if merchant and name and merchant.lower() not in name.lower():
        return f"{merchant} · {name}"[:120]
    return (name or merchant or "(no description)")[:120]


def payee_key(desc: str) -> str:
    """A description without its reference numbers: two transfers to the
    same account read the same."""
    return " ".join([w for w in re.split(r"[^a-z]+", desc.lower()) if w][:5])


def repeats(rows: List[Dict[str, Any]], limit: int = 15) -> List[Dict[str, Any]]:
    """Rows of one amount (what's left of each) and one payee, two or more,
    the most first. Each row is {transaction_id, date, description, amount,
    left?}."""
    groups: Dict[Any, List[Dict[str, Any]]] = {}
    for r in sorted(rows, key=lambda r: (r["date"], r["transaction_id"])):
        groups.setdefault((r.get("left", r["amount"]), payee_key(r["description"])), []).append(r)
    found = sorted((g for g in groups.values() if len(g) >= 2),
                   key=lambda g: (-len(g), -g[0].get("left", g[0]["amount"])))
    return [{"amount": g[0].get("left", g[0]["amount"]), "count": len(g),
             "total": round(sum(r.get("left", r["amount"]) for r in g), 2),
             "description": g[-1]["description"], "dates": [r["date"] for r in g],
             "transaction_ids": [r["transaction_id"] for r in g]} for g in found[:limit]]
