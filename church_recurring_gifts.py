"""church_recurring_gifts.py — the office's list of every recurring gift.

Kevin, 2026-10-27, "lets start building this" (the gap check of a church's
staff menu, artifact 4oXF1Be46RddJxXnKAHodn, Giving card): members can
change, pause or stop their own recurring gift on /my/gifts
(member_portal_gifts, #1424), but the office had no list of them.

WHERE A RECURRING GIFT LIVES. Nowhere on our side. A recurring gift is a
Stripe subscription on the CHURCH'S OWN connected account
(giving_router: Checkout mode=subscription, metadata source_type=gift +
business_id + fund + frequency + giver name/email). Each paid cycle lands
as its own paid invoice (GIVE-<stripe invoice id>), but the schedule
itself, its next date and whether it's paused or ended, exist only in
Stripe. So this reads Stripe, server-side, on the church's account, keeps
only gifts to THIS church, and shapes each one into a row the office
can read. The client sends nothing but the business id.

What a row carries: the giver (name, email, and their contact id when one
matches, for "Open their record"), the amount, how often, the fund, the
next date and the state (active, paused or ended; late when Stripe's last
try failed). Never a card: no payment method, no customer object, no
last four. _row builds every field from scratch, so nothing Stripe adds
later can leak through.

Read-only. Changing a gift is the giver's, on /my/gifts.

Cached per business for CACHE_SECONDS in this process (several replicas
each keep their own copy; a read-only list can be two minutes old).
`fresh` skips it.
"""
from __future__ import annotations

import threading
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx

import sb_clients

CACHE_SECONDS = 120
PAGE = 100
MAX_PAGES = 20            # 2,000 subscriptions; a church past that is told the list is cut
CONTACT_CHUNK = 40

# How each Stripe repeat reads, and what one gift comes to in a month.
EVERY = {("week", 1): "weekly", ("week", 2): "biweekly", ("month", 1): "monthly"}
PER_MONTH = {"weekly": 52 / 12, "biweekly": 26 / 12, "monthly": 1.0}

_cache: Dict[str, Tuple[float, str, Dict[str, Any]]] = {}
_lock = threading.Lock()


def _iso(ts: Any) -> Optional[str]:
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).isoformat() if ts else None
    except (TypeError, ValueError, OverflowError):
        return None


# ─── Stripe, on the church's own account ─────────────────────────────

def _stripe_get(path: str, account: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One GET on the connected account, or None when it failed."""
    from stripe_checkout_helpers import HTTP_TIMEOUT, STRIPE_API_BASE, _secret_key
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            resp = client.get(f"{STRIPE_API_BASE}{path}", auth=(_secret_key(), ""),
                              headers={"Stripe-Account": account}, params=params)
    except httpx.HTTPError as e:
        print(f"[recurring-gifts] stripe GET {path} failed: {type(e).__name__}", flush=True)
        return None
    if resp.status_code >= 400:
        print(f"[recurring-gifts] stripe GET {path} -> {resp.status_code}", flush=True)
        return None
    try:
        body = resp.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def read_subscriptions(account: str) -> Tuple[Optional[List[Dict[str, Any]]], bool]:
    """Every subscription on the account, newest first, with its customer
    expanded (for the giver's name and email when the gift's own metadata
    lacks them). (None, False) when Stripe couldn't be read; the bool says
    the list was cut at MAX_PAGES."""
    out: List[Dict[str, Any]] = []
    after: Optional[str] = None
    for _ in range(MAX_PAGES):
        params: Dict[str, Any] = {"status": "all", "limit": PAGE, "expand[]": "data.customer"}
        if after:
            params["starting_after"] = after
        page = _stripe_get("/subscriptions", account, params)
        if page is None:
            return None, False
        data = [s for s in (page.get("data") or []) if isinstance(s, dict)]
        out.extend(data)
        if not page.get("has_more") or not data:
            return out, False
        after = str(data[-1].get("id") or "")
        if not after:
            return None, False
    return out, True


# ─── One row ──────────────────────────────────────────────────────────

def _period_end(sub: Dict[str, Any]) -> Any:
    # Newer Stripe API versions keep the period on the item.
    items = (sub.get("items") or {}).get("data") or []
    return sub.get("current_period_end") or (items[0].get("current_period_end") if items else None)


def _giver(sub: Dict[str, Any]) -> Tuple[str, str]:
    md = sub.get("metadata") or {}
    cust = sub.get("customer") if isinstance(sub.get("customer"), dict) else {}
    email = str(md.get("giver_email") or cust.get("email") or "").strip().lower()
    name = str(md.get("giver_name") or cust.get("name") or "").strip()
    return name[:120], email[:200]


def is_gift_to(sub: Dict[str, Any], business_id: str) -> bool:
    md = sub.get("metadata") or {}
    return md.get("source_type") == "gift" and str(md.get("business_id")) == str(business_id)


def row(sub: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The office's row for one gift subscription, or None for one that
    never started (its first payment never went through). Every field is
    built here, by name: nothing of Stripe's passes through whole."""
    status = str(sub.get("status") or "")
    if status == "incomplete":
        return None
    items = (sub.get("items") or {}).get("data") or []
    first = items[0] if items else {}
    price = first.get("price") or {}
    rec = price.get("recurring") or {}
    try:
        gift_cents = int(price.get("unit_amount") or 0) * int(first.get("quantity") or 1)
        fee_cents = int((((items[1] if len(items) > 1 else {}).get("price") or {}).get("unit_amount")) or 0)
        every = EVERY.get((rec.get("interval"), int(rec.get("interval_count") or 1)), "other")
    except (TypeError, ValueError):
        return None
    pause = sub.get("pause_collection") if isinstance(sub.get("pause_collection"), dict) else None
    if status in ("canceled", "incomplete_expired"):
        state = "ended"
    elif pause or status == "paused":
        state = "paused"
    else:
        state = "active"
    if state == "active":
        next_at = _iso(_period_end(sub))
    elif state == "paused":
        next_at = _iso((pause or {}).get("resumes_at"))
    else:
        next_at = None
    name, email = _giver(sub)
    md = sub.get("metadata") or {}
    return {
        "id": str(sub.get("id") or ""),
        "giver": name,
        "email": email,
        "contact_id": None,
        "amount_cents": gift_cents,
        "fee_cents": fee_cents,
        "every": every,
        "fund": str(md.get("fund") or "General")[:40],
        "state": state,
        "late": status in ("past_due", "unpaid"),
        "next_at": next_at,
        "started_at": _iso(sub.get("start_date") or sub.get("created")),
        "ended_at": _iso(sub.get("ended_at") or sub.get("canceled_at")) if state == "ended" else None,
    }


def monthly_cents(r: Dict[str, Any]) -> int:
    """What one gift comes to in a month (a weekly $25 is about $108)."""
    return int(round(r["amount_cents"] * PER_MONTH.get(r["every"], 0)))


def totals(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The figures at the top: what the active gifts come to a month, by
    fund, and how many are active, paused, late and ended."""
    live = [r for r in rows if r["state"] == "active"]
    by_fund: Dict[str, Dict[str, Any]] = {}
    for r in live:
        f = by_fund.setdefault(r["fund"], {"fund": r["fund"], "monthly_cents": 0, "count": 0})
        f["monthly_cents"] += monthly_cents(r)
        f["count"] += 1
    return {
        "monthly_cents": sum(monthly_cents(r) for r in live),
        "paused_monthly_cents": sum(monthly_cents(r) for r in rows if r["state"] == "paused"),
        "active": len(live),
        "paused": sum(1 for r in rows if r["state"] == "paused"),
        "ended": sum(1 for r in rows if r["state"] == "ended"),
        "late": sum(1 for r in live if r["late"]),
        "by_fund": sorted(by_fund.values(), key=lambda f: -f["monthly_cents"]),
    }


# ─── Givers on file ───────────────────────────────────────────────────

def _in_list(values: Iterable[str]) -> str:
    # PostgREST unquotes values inside in.(...); the quotes keep a comma
    # in an address from splitting it.
    clean = [v.replace('"', "").replace("\\", "") for v in values]
    return urllib.parse.quote("(" + ",".join(f'"{v}"' for v in clean) + ")", safe="")


def match_contacts(business_id: str, emails: List[str]) -> Dict[str, Dict[str, Any]]:
    """email → {id, name} for givers who have a record at this church. A
    failed read leaves them unmatched (the list still shows the gift)."""
    out: Dict[str, Dict[str, Any]] = {}
    wanted = sorted({e for e in emails if e and "@" in e})
    for i in range(0, len(wanted), CONTACT_CHUNK):
        chunk = wanted[i:i + CONTACT_CHUNK]
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{urllib.parse.quote(str(business_id), safe='')}"
            f"&email=in.{_in_list(chunk)}&select=id,name,email&limit={len(chunk) * 3}", redact=True)
        for c in rows if isinstance(rows, list) else []:
            e = str(c.get("email") or "").strip().lower()
            if e and e not in out:
                out[e] = {"id": c.get("id"), "name": c.get("name") or ""}
    return out


# ─── The list ─────────────────────────────────────────────────────────

_ORDER = {"active": 0, "paused": 1, "ended": 2}


def build(business_id: str, subs: List[Dict[str, Any]], truncated: bool) -> Dict[str, Any]:
    rows = [r for r in (row(s) for s in subs if is_gift_to(s, business_id)) if r]
    found = match_contacts(business_id, [r["email"] for r in rows])
    for r in rows:
        c = found.get(r["email"])
        if c:
            r["contact_id"] = c["id"]
            r["giver"] = r["giver"] or c["name"]
        r["giver"] = r["giver"] or r["email"] or "A giver"
        r["monthly_cents"] = monthly_cents(r)
    rows.sort(key=lambda r: (_ORDER[r["state"]], -(r["monthly_cents"]), r["giver"].lower()))
    return {"connected": True, "gifts": rows, "totals": totals(rows), "cut_short": truncated}


def recurring_for(biz: Dict[str, Any], *, fresh: bool = False) -> Optional[Dict[str, Any]]:
    """The church's recurring gifts, or None when Stripe couldn't be read.
    A church without online giving connected has none."""
    business_id = str(biz["id"])
    account = str(biz.get("stripe_account_id") or "")
    if not account:
        return {"connected": False, "gifts": [], "totals": totals([]), "cut_short": False,
                "as_of": datetime.now(timezone.utc).isoformat()}
    now = time.time()
    if not fresh:
        with _lock:
            hit = _cache.get(business_id)
        if hit and hit[1] == account and now - hit[0] < CACHE_SECONDS:
            return hit[2]
    subs, truncated = read_subscriptions(account)
    if subs is None:
        return None
    payload = {**build(business_id, subs, truncated), "as_of": datetime.now(timezone.utc).isoformat()}
    with _lock:
        _cache[business_id] = (now, account, payload)
    return payload
