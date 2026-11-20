"""payments_overview.py — the church's Payments page: the new Overview (piece 1).

Kevin, 2026-11-19: "also upgrade the payments section as well. this needs to
be top tier. make this experience awesome!" He saw the mock and on
2026-11-20 chose "Build it". This is the server half. It reads; it never
writes, sends or moves money.

  GET /payments/overview?biz=&period=week|month|year
  GET /payments/feed?biz=&period=&filter=all|gifts|store|events|refunded|disputed|on_the_way&q=&starting_after=
  GET /payments/feed.csv?biz=&period=&filter=&q=

THE SWITCH ...... PAYMENTS_OVERVIEW = off | owner (the default: the platform
                  owner's own church, member_asks.platform_church, as
                  church_money_ticks.open_for reads it) | on. Off for a
                  church, and every business that isn't a church: 404, and
                  the app shows today's Overview. The app has no flag of its
                  own: it asks here
WHO SEES WHAT ... only doors that already exist, asked the way they ask:
                    the page ...... the church wall at the books
                                    (church_money_gate "books" at "see": the
                                    owner, an Admin, the accountant; with the
                                    giving tick on, any tick), then the
                                    Giving keeper (church_keys.wall
                                    "giving_money"), as the Stripe proxy
                    the bank part . everything read from Stripe (what's on the
                                    way, in the bank, the next payout, the
                                    disputes, the fees, how people gave, the
                                    feed and its download, the payout bank's
                                    last four): the owner, or the "bank and
                                    payouts" tick, the Payouts tab's own door
                                    (stripe_data_proxy._require_owner_with_acct,
                                    door "payouts")
                    names ......... church_money_gate.sees_givers
                    refund ........ the refund route's own door
                                    (stripe_payments_router._require_owner)
                    disconnect .... the owner alone (part "setup")
                    going out ..... each page's own door: payroll_router
                                    ._access, contractors_router._access,
                                    bills_router._reader
WHERE THE NUMBERS COME FROM
  our records ... given and by fund, for any period: paid online gifts and
                  payments (invoices paid through Stripe, the store's orders,
                  paid event sign-ups), refunds taken off. A year never means
                  Stripe paging
  Stripe ........ (Connect: the platform key + Stripe-Account, as
                  stripe_data_proxy) the balance, the payouts, the next
                  payout's items, disputes waiting for an answer, the payout
                  schedule, and the period's charges for what only Stripe
                  knows: each charge's fee, how it was paid, whether the giver
                  covered the fee, and where the money is. At most
                  CHARGE_PAGES pages of charges a read; past that the fee and
                  method numbers say how many charges they counted
  the bank ...... plaid_reconciliation's matches: a payout is matched when a
                  bank row carries its id (reconciled_to_payout_id)
THE CACHE ....... each Stripe read is kept 60 seconds per church (and period,
                  where the read depends on it), in this replica's memory;
                  `checked_at` says when the oldest part used was read. A
                  read that failed is not kept
A PART THAT FAILS is null, with `partial: true`; never a 500. Stripe reads
are free and the existing Stripe proxies don't meter them, so neither does
this (api_usage_logger is for paid calls).
"""
from __future__ import annotations

import asyncio
import calendar as _cal
import csv
import io
import logging
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

import church_keys
import church_money_gate
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("payments_overview")

router = APIRouter(prefix="/payments", tags=["payments"])

STRIPE_API_BASE = "https://api.stripe.com/v1"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0)

PERIODS = ("week", "month", "year")
FILTERS = ("all", "gifts", "store", "events", "refunded", "disputed", "on_the_way")
CACHE_SECONDS = 60
CACHE_MAX = 200            # kept Stripe reads, all churches together ...
CACHE_MAX_ROWS = 10_000    # ... and the charges, payouts and payout gifts they hold
CHARGE_PAGES = 10          # 1,000 charges: a week or a month always; a big church's year is counted from records
PAYOUT_PAGES = 3           # a year of weekday payouts is about 260
ITEM_PAGES = 2             # the next payout's gifts
LIVE_PAGES = 2             # feed pages read past the cached charges, per request
CSV_PAGES = 20             # the download reads at most this many pages past the cached charges
FEED_PAGE = 25
NEXT_ITEMS = 4
ON_THE_WAY_DAYS = 16       # charges this recent are read whatever the period, to count what's on the way
PAYOUT_PAD_DAYS = 10
MATCH_AFTER_DAYS = 2       # a payout this old with no bank row is one to match (plaid_reconciliation's ±2 days)
UNMATCHED_MAX = 3
Q_MAX = 80

# Always fullmatch: "$" would let a trailing newline through.
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_STRIPE_ID = re.compile(r"[A-Za-z0-9_]{3,80}")

BANK_KEPT = "Bank and payouts are kept by the people the owner gave them to."
NOT_CONNECTED = "stripe account not connected"


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("PAYMENTS_OVERVIEW") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_for(business_id: Any) -> bool:
    """Whether the new Overview is switched on for this church. `owner`: the
    platform owner's own church only. A check that fails is a no."""
    m = mode()
    if m == "on":
        return bool(business_id)
    if m == "owner":
        try:
            import member_asks
            return bool(member_asks.platform_church(business_id))
        except Exception:  # noqa: BLE001 — couldn't tell: closed
            return False
    return False


# ─── Who sees what ────────────────────────────────────────────────────

class Access(NamedTuple):
    biz: Dict[str, Any]          # id, name, type, owner_id, settings, stripe_account_id
    owner: bool
    see_bank: bool
    see_names: bool
    refund: bool
    disconnect: bool


def _access(business_id: str, user: AuthedUser) -> Access:
    """The page's gate, then what this login may see on it. 404, for anyone,
    when the page is off for the church or the business isn't a church: the
    switch and the kind of business are asked BEFORE any door, so a refusal
    never tells a stranger that an id is a church. Then the door's own
    refusal (403)."""
    if not isinstance(business_id, str) or not _UUID.fullmatch(business_id):
        raise HTTPException(404, "Not Found")
    b = quote(business_id, safe="")
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{b}&select=id,name,type,owner_id,settings,stripe_account_id&limit=1")
    if rows is None:
        raise HTTPException(503, "Payments couldn't be read just now. Try again.")
    if not rows:
        raise HTTPException(404, "Not Found")
    biz = rows[0]
    import church_follow_up
    if not church_follow_up.is_church(biz) or not open_for(business_id):
        raise HTTPException(404, "Not Found")
    # The church wall at the books: the owner, an Admin, the accountant (and
    # with the giving tick on, any tick). Only a business that isn't a church
    # or nonprofit comes back NOT_ASKED, and none reaches here; kept as a no.
    passed = church_money_gate.require_money(business_id, user, "see", "books", business=biz)
    if passed.by == church_money_gate.NOT_ASKED:
        raise HTTPException(404, "Not Found")
    # Who gave what and the payouts: the church's Giving keeper holds the
    # owner to the key too, as the Stripe proxy does.
    church_keys.wall(business_id, user, "giving_money")
    owner = str(biz.get("owner_id")) == str(user.id)
    # The Payouts tab's own door (stripe_data_proxy._require_owner_with_acct,
    # door "payouts"): the owner, or the "bank and payouts" tick.
    see_bank = owner or church_money_gate.tick_admits(business_id, user, "see", "payouts")
    see_names = church_money_gate.sees_givers(business_id, user, biz)
    # The refund route's own door (stripe_payments_router._require_owner):
    # the owner, or "bank and payouts" at Work.
    refund = bool(see_bank and biz.get("stripe_account_id")
                  and (owner or church_money_gate.tick_admits(business_id, user, "work", "payouts")))
    disconnect = church_money_gate.may_money(business_id, user, "work", "setup", business=biz)
    return Access(biz, owner, bool(see_bank), bool(see_names), refund, bool(disconnect))


def _period_key(period: Optional[str]) -> str:
    p = (period or "month").strip().lower()
    if p not in PERIODS:
        raise HTTPException(400, "Choose this week, this month or this year.")
    return p


# ─── The period, on the church's clock ────────────────────────────────

class Period(NamedTuple):
    key: str
    label: str
    start: date                  # the first day, the church's date
    end: date                    # today, the church's date
    start_at: datetime           # UTC instants
    now: datetime
    prior_start_at: datetime     # the same stretch of the period before
    prior_end_at: datetime
    week_start: date             # this week, Monday..Sunday (the bills)
    week_end: date
    tz: Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clock(biz: Dict[str, Any]):
    import church_leaders_note
    return church_leaders_note._zone(biz)


def _midnight(d: date, tz) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=tz).astimezone(timezone.utc)


def period_of(key: str, tz, now: Optional[datetime] = None) -> Period:
    """This week (from Monday), this month or this year, up to now, and the
    same stretch of the one before ("12% ahead of October by this date"): a
    month's stretch never runs past the end of the shorter month."""
    now = (now or _now()).astimezone(timezone.utc)
    today = now.astimezone(tz).date()
    week_start = today - timedelta(days=today.weekday())
    if key == "week":
        start, label = week_start, "This week"
        prior_start = start - timedelta(days=7)
        prior_cap = start
    elif key == "month":
        start, label = date(today.year, today.month, 1), _cal.month_name[today.month]
        py, pm = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        prior_start = date(py, pm, 1)
        prior_cap = start
    else:
        start, label = date(today.year, 1, 1), str(today.year)
        prior_start = date(today.year - 1, 1, 1)
        prior_cap = start
    start_at = _midnight(start, tz)
    prior_start_at = _midnight(prior_start, tz)
    prior_end_at = min(prior_start_at + (now - start_at), _midnight(prior_cap, tz))
    return Period(key, label, start, today, start_at, now, prior_start_at, prior_end_at, week_start,
                  week_start + timedelta(days=6), tz)


def _z(at: datetime) -> str:
    return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(at: datetime) -> int:
    return int(at.timestamp())


def _from_ts(v: Any) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(int(v), timezone.utc) if v else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _day_of_ts(v: Any) -> Optional[str]:
    """A Stripe date (arrival_date: midnight UTC of the day) as YYYY-MM-DD."""
    at = _from_ts(v)
    return at.date().isoformat() if at else None


def _local_day(v: Any, tz) -> Optional[str]:
    at = _from_ts(v)
    return at.astimezone(tz).date().isoformat() if at else None


def _q(v: Any) -> str:
    return quote(str(v), safe="")


# ─── Our records: what was given online ───────────────────────────────

class Failed(Exception):
    """A read this page needs didn't answer: its part is null."""


def _all(path: str) -> List[Dict[str, Any]]:
    try:
        rows = sb_clients.sb_get_all_as_service(path, strict=True)
    except sb_clients.PartialRead as e:
        raise Failed(str(e))
    return rows or []


def _net(cents: Any, refunded: Any) -> int:
    try:
        return max(0, int(cents or 0) - int(refunded or 0))
    except (TypeError, ValueError):
        return 0


def _cents_of(dollars: Any) -> int:
    try:
        return int(round(float(dollars or 0) * 100))
    except (TypeError, ValueError):
        return 0


_EVERY = {"weekly": "every week", "every-two-weeks": "every two weeks", "monthly": "every month"}


def _every(notes: Any) -> Optional[str]:
    """How often a repeating gift repeats, from the words giving_router.record_gift
    writes on it ("Online gift · Building Fund · monthly · ...")."""
    for part in str(notes or "").split(" · ")[2:3]:
        return _EVERY.get(part.strip().lower())
    return None


def read_records(biz_id: str, start_at: datetime, end_at: datetime) -> List[Dict[str, Any]]:
    """Every online gift and payment paid start_at..end_at, refunds taken off:
    invoices paid through Stripe (gifts carry their fund), the store's paid
    orders and paid event sign-ups. Failed when any read doesn't answer."""
    b, s, e = _q(biz_id), _q(_z(start_at)), _q(_z(end_at))
    out: List[Dict[str, Any]] = []
    import giving_week
    for r in _all(f"/invoices?business_id=eq.{b}&status=eq.paid&payment_method=eq.stripe"
                  f"&paid_at=gte.{s}&paid_at=lte.{e}"
                  "&select=id,invoice_number,is_gift,gift_fund,total,refund_amount_cents,paid_at,contact_id,notes"):
        gift = r.get("is_gift") is True
        number = str(r.get("invoice_number") or "")
        every = _every(r.get("notes")) if gift and number.startswith("GIVE-in_") else None
        fund = giving_week.fund_of(r) if gift else "Other payments"
        out.append({"kind": "gift" if gift else "other", "id": r.get("id"), "number": number,
                    "cents": _net(_cents_of(r.get("total")), r.get("refund_amount_cents")),
                    "paid_at": r.get("paid_at"), "fund": fund, "for": (f"{fund}, {every}" if every else fund),
                    "contact_id": r.get("contact_id"), "name": None})
    for r in _all(f"/orders?business_id=eq.{b}&status=in.(paid,fulfilled,refunded)"
                  f"&stripe_payment_intent_id=not.is.null&paid_at=gte.{s}&paid_at=lte.{e}"
                  "&select=id,total_cents,refund_amount_cents,paid_at,contact_id,customer_name,"
                  "stripe_payment_intent_id"):
        out.append({"kind": "store", "id": r.get("id"), "pi": r.get("stripe_payment_intent_id"),
                    "cents": _net(r.get("total_cents"), r.get("refund_amount_cents")), "paid_at": r.get("paid_at"),
                    "fund": "Store", "for": "Store", "contact_id": r.get("contact_id"),
                    "name": r.get("customer_name")})
    for r in _all(f"/church_event_registrations?business_id=eq.{b}&status=in.(paid,confirmed,refunded)"
                  f"&stripe_session_id=not.is.null&amount_cents=gt.0&paid_at=gte.{s}&paid_at=lte.{e}"
                  "&select=id,amount_cents,refunded_cents,paid_at,contact_id,name,event_title,stripe_payment_intent"):
        title = " ".join(str(r.get("event_title") or "").split()) or "An event"
        out.append({"kind": "event", "id": r.get("id"), "pi": r.get("stripe_payment_intent"),
                    "cents": _net(r.get("amount_cents"), r.get("refunded_cents")), "paid_at": r.get("paid_at"),
                    "fund": "Events", "for": title, "contact_id": r.get("contact_id"), "name": r.get("name")})
    return out


def _at(v: Any) -> Optional[datetime]:
    try:
        at = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def _within(rows: List[Dict[str, Any]], start_at: datetime, end_at: datetime) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        at = _at(r.get("paid_at"))
        if at is not None and start_at <= at <= end_at and r["cents"] > 0:
            out.append(r)
    return out


def given_block(now_rows: List[Dict[str, Any]], prior_rows: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    cents = sum(r["cents"] for r in now_rows)
    pct = None
    if prior_rows is not None:
        before = sum(r["cents"] for r in prior_rows)
        if before > 0:
            pct = int(round((cents - before) * 100.0 / before))
    return {"cents": cents, "count": len(now_rows), "vs_prior_pct": pct}


def by_fund(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The period by fund, the largest first ("Building" and "building" are
    one fund); the store, events and other payments as their own lines."""
    funds: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        f = funds.setdefault(r["fund"].lower(), {"fund": r["fund"], "cents": 0, "count": 0})
        f["cents"] += r["cents"]
        f["count"] += 1
    return sorted(funds.values(), key=lambda f: (-f["cents"], f["fund"].lower()))


class Links:
    """Our records by the keys a Stripe charge carries, to name a charge's
    giver and what it was for."""

    def __init__(self, rows: List[Dict[str, Any]]):
        self.by_number = {r["number"]: r for r in rows if r.get("number")}
        self.by_id = {(r["kind"], str(r["id"])): r for r in rows if r.get("id")}
        self.by_pi = {str(r["pi"]): r for r in rows if r.get("pi")}

    def find(self, ch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        md = ch.get("metadata") or {}
        for ref in (ch.get("payment_intent"), ch.get("invoice")):
            if ref and f"GIVE-{ref}" in self.by_number:
                return self.by_number[f"GIVE-{ref}"]
        kind = {"order": "store", "invoice": "other"}.get(str(md.get("source_type") or ""))
        if kind and (kind, str(md.get("source_id") or "")) in self.by_id:
            return self.by_id[(kind, str(md["source_id"]))]
        if ch.get("payment_intent") and str(ch["payment_intent"]) in self.by_pi:
            return self.by_pi[str(ch["payment_intent"])]
        return None


# ─── Stripe ───────────────────────────────────────────────────────────

class StripeDown(Exception):
    pass


# key → (when read, the value, how many rows it holds). The rows carry
# givers' names and cards' last four, so nothing is kept past its minute:
# every read and every write drops what has run out, and the whole cache is
# held under CACHE_MAX entries and CACHE_MAX_ROWS rows, the oldest out first.
_CACHE: Dict[Tuple[str, str, str], Tuple[float, Any, int]] = {}


def _wall() -> float:
    return time.time()


def _size(value: Any) -> int:
    rows = value.get("rows") if isinstance(value, dict) else value
    return len(rows) if isinstance(rows, list) else 1


def _prune(now: float) -> None:
    for k in [k for k, v in _CACHE.items() if now - v[0] >= CACHE_SECONDS]:
        _CACHE.pop(k, None)
    held = sum(v[2] for v in _CACHE.values())
    if len(_CACHE) <= CACHE_MAX and held <= CACHE_MAX_ROWS:
        return
    for k, v in sorted(_CACHE.items(), key=lambda kv: kv[1][0]):
        if len(_CACHE) <= CACHE_MAX and held <= CACHE_MAX_ROWS:
            break
        _CACHE.pop(k, None)
        held -= v[2]


def _cached(key: Tuple[str, str, str]) -> Optional[Tuple[float, Any]]:
    _prune(_wall())
    hit = _CACHE.get(key)
    return (hit[0], hit[1]) if hit else None


def _keep(key: Tuple[str, str, str], value: Any) -> float:
    at = _wall()
    _CACHE[key] = (at, value, _size(value))
    _prune(at)
    return at


async def _get(client: httpx.AsyncClient, path: str, acct: str, params: List[Tuple[str, Any]]) -> Dict[str, Any]:
    """One GET as the connected account (platform key + Stripe-Account).
    Anything but a JSON answer under 400 is StripeDown."""
    key = os.environ.get("STRIPE_SECRET_KEY") or ""
    if not key:
        raise StripeDown("payments not configured")
    try:
        resp = await client.get(f"{STRIPE_API_BASE}{path}", auth=(key, ""), headers={"Stripe-Account": acct},
                                params=[(k, v) for k, v in params if v is not None and v != ""])
    except httpx.HTTPError as e:
        raise StripeDown(type(e).__name__)
    if resp.status_code >= 400:
        logger.warning("payments overview: stripe GET %s -> %s", path, resp.status_code)
        raise StripeDown(f"stripe {resp.status_code}")
    try:
        body = resp.json()
    except ValueError:
        raise StripeDown("not json")
    if not isinstance(body, dict):
        raise StripeDown("not an object")
    return body


async def _list(client: httpx.AsyncClient, path: str, acct: str, params: List[Tuple[str, Any]],
                pages: int, after: Optional[str] = None) -> Tuple[List[Dict[str, Any]], bool]:
    """Up to `pages` pages of a Stripe list, newest first: (rows, whether
    that was all of them)."""
    rows: List[Dict[str, Any]] = []
    for _ in range(max(1, pages)):
        got = await _get(client, path, acct, params + [("limit", 100), ("starting_after", after)])
        data = [d for d in (got.get("data") or []) if isinstance(d, dict)]
        rows.extend(data)
        if not got.get("has_more") or not data:
            return rows, True
        after = data[-1].get("id")
    return rows, False


def _usd(entries: Any) -> int:
    return sum(int(e.get("amount") or 0) for e in (entries or []) if isinstance(e, dict)
               and str(e.get("currency") or "usd").lower() == "usd")


def _last4(dest: Any) -> Optional[str]:
    if isinstance(dest, dict):
        l4 = str(dest.get("last4") or "")
        return l4 if re.fullmatch(r"[0-9]{4}", l4) else None
    return None


def _payout(p: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": p.get("id"), "cents": int(p.get("amount") or 0), "arrival": p.get("arrival_date"),
            "created": int(p.get("created") or 0), "status": p.get("status"), "automatic": p.get("automatic") is True,
            "last4": _last4(p.get("destination"))}


def _method(pmd: Any) -> Tuple[str, str]:
    """(the method's key, its words): ("card", "Card 4242"), ("apple_pay",
    "Apple Pay"), ("bank", "Bank account 6789") ..."""
    pmd = pmd if isinstance(pmd, dict) else {}
    kind = str(pmd.get("type") or "")
    if kind == "card":
        card = pmd.get("card") if isinstance(pmd.get("card"), dict) else {}
        wallet = str(((card.get("wallet") or {}) if isinstance(card.get("wallet"), dict) else {}).get("type") or "")
        if wallet in WALLETS:
            return wallet, WALLETS[wallet]
        l4 = str(card.get("last4") or "")
        return "card", f"Card {l4}" if re.fullmatch(r"[0-9]{4}", l4) else "Card"
    if kind == "us_bank_account":
        l4 = str(((pmd.get("us_bank_account") or {}) if isinstance(pmd.get("us_bank_account"), dict) else {})
                 .get("last4") or "")
        return "bank", f"Bank account {l4}" if re.fullmatch(r"[0-9]{4}", l4) else "Bank account"
    if kind in OTHER_METHODS:
        return kind, OTHER_METHODS[kind]
    return ("other", kind.replace("_", " ").capitalize()) if kind else ("other", "Online")


WALLETS = {"apple_pay": "Apple Pay", "google_pay": "Google Pay", "link": "Link", "samsung_pay": "Samsung Pay"}
OTHER_METHODS = {"link": "Link", "cashapp": "Cash App Pay", "paypal": "PayPal", "amazon_pay": "Amazon Pay"}
METHOD_WORDS = {"card": "Card", "bank": "Bank account", "other": "Other", **WALLETS, **OTHER_METHODS}


def _text(v: Any) -> str:
    """Text as it is shown: every run of whitespace one space, none at the
    ends, and no invisible characters in front."""
    return " ".join(str(v if v is not None else "").split()).lstrip(_INVISIBLE)


_INVISIBLE = "\u200b\u200c\u200d\u2060\ufeff"


def _int(v: Any) -> int:
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError):
        return 0


def _charge(c: Dict[str, Any]) -> Dict[str, Any]:
    """What this page keeps of a Stripe charge."""
    md = c.get("metadata") if isinstance(c.get("metadata"), dict) else {}
    bt = c.get("balance_transaction") if isinstance(c.get("balance_transaction"), dict) else None
    bill = c.get("billing_details") if isinstance(c.get("billing_details"), dict) else {}
    key, words = _method(c.get("payment_method_details"))
    inv = c.get("invoice")
    return {
        "id": c.get("id"), "created": int(c.get("created") or 0), "cents": _int(c.get("amount")),
        "refunded_cents": _int(c.get("amount_refunded")), "disputed": c.get("disputed") is True,
        "status": c.get("status"), "payment_intent": c.get("payment_intent") if isinstance(c.get("payment_intent"), str)
        else None, "invoice": inv if isinstance(inv, str) else (inv or {}).get("id") if isinstance(inv, dict) else None,
        "description": str(c.get("description") or "")[:120],
        "metadata": {k: md.get(k) for k in ("source_type", "source_id", "fund", "giver_name", "covered_fee_cents",
                                             "frequency") if md.get(k) not in (None, "")},
        "billing_name": _text(bill.get("name"))[:120] or None,
        "method": key, "how": words,
        "fee": _int(bt.get("fee")) if bt else None, "net": int(bt.get("net") or 0) if bt else None,
        "available_on": int(bt.get("available_on") or 0) if bt else None,
    }


def _dispute(d: Dict[str, Any]) -> Dict[str, Any]:
    ch = d.get("charge") if isinstance(d.get("charge"), dict) else {}
    ev = d.get("evidence_details") if isinstance(d.get("evidence_details"), dict) else {}
    return {"id": d.get("id"), "cents": _int(d.get("amount")), "status": d.get("status"),
            "charge_created": ch.get("created"), "due_by": ev.get("due_by"), "livemode": d.get("livemode") is True}


async def _part(client: httpx.AsyncClient, name: str, acct: str, p: "Period", arg: Any = None) -> Any:
    """One part of what Stripe knows, as this page keeps it."""
    if name == "balance":
        got = await _get(client, "/balance", acct, [])
        return {"pending": _usd(got.get("pending")), "available": _usd(got.get("available"))}
    if name == "account":
        got = await _get(client, "/account", acct, [])
        sched = (((got.get("settings") or {}).get("payouts") or {}).get("schedule") or {})
        ext = ((got.get("external_accounts") or {}).get("data") or []) if isinstance(got.get("external_accounts"),
                                                                                     dict) else []
        default = next((e for e in ext if isinstance(e, dict) and e.get("default_for_currency")), None)
        return {"schedule": sched if isinstance(sched, dict) else {}, "last4": _last4(default)}
    if name == "disputes":
        rows, _ = await _list(client, "/disputes", acct, [("expand[]", "data.charge")], 1)
        return [_dispute(d) for d in rows if d.get("status") in ("needs_response", "warning_needs_response")]
    if name == "payouts":
        since = _ts(p.start_at - timedelta(days=PAYOUT_PAD_DAYS))
        rows, complete = await _list(client, "/payouts", acct, [("created[gte]", since),
                                                                ("expand[]", "data.destination")], PAYOUT_PAGES)
        return {"rows": [_payout(r) for r in rows], "complete": complete}
    if name == "charges":
        rows, complete = await _list(client, "/charges", acct, [
            ("created[gte]", _ts(read_start(p))), ("created[lte]", _ts(p.now)),
            ("expand[]", "data.balance_transaction")], CHARGE_PAGES)
        return {"rows": [_charge(r) for r in rows], "complete": complete}
    if name == "items":
        rows, complete = await _list(client, "/balance_transactions", acct, [("payout", arg),
                                                                             ("expand[]", "data.source")], ITEM_PAGES)
        out = []
        for t in rows:
            if t.get("type") not in ("charge", "payment"):
                continue
            src = t.get("source") if isinstance(t.get("source"), dict) else {}
            out.append({"bt": t.get("id"), "created": int(t.get("created") or 0), "cents": int(t.get("amount") or 0),
                        "net": int(t.get("net") or 0), "charge": _charge(src) if src else None})
        return {"rows": out, "complete": complete}
    raise ValueError(name)


def read_start(p: "Period") -> datetime:
    """The charges read go back at least ON_THE_WAY_DAYS, so what is still on
    the way is counted whatever the period."""
    return min(p.start_at, p.now - timedelta(days=ON_THE_WAY_DAYS))


def period_complete(charges: Any, p: "Period") -> bool:
    """Whether the kept charges hold every charge of the period: the read
    reached its end, or it read past the period's first moment (Stripe lists
    the newest first)."""
    rows = (charges or {}).get("rows") or []
    return bool((charges or {}).get("complete")) or bool(rows and rows[-1]["created"] < _ts(p.start_at))


def _scope(name: str, p: "Period") -> str:
    """balance, account and disputes are the same for every period."""
    return "-" if name in ("balance", "account", "disputes") else f"{p.key}:{p.start.isoformat()}"


def _tenant(biz_id: str, acct: str) -> str:
    """Kept per church AND its connected account: a church that reconnects
    to another account never sees the old one's numbers."""
    return f"{biz_id}:{acct}"


def cold(biz_id: str, acct: str, p: "Period", names: Tuple[str, ...]) -> bool:
    """Whether answering would go to Stripe: a part asked for isn't kept.
    (The gifts inside a payout are read only with the payouts, so they ride
    on the payouts' answer.)"""
    return any(_cached((_tenant(biz_id, acct), _scope(n, p), n)) is None for n in names if n != "items")


FEED_429 = "That's a lot of looking at once. Try again in a minute."
DOWNLOADS_429 = "That's a lot of downloads at once. Try again in a few minutes."
STRIPE_429 = "Stripe has been asked a lot in the last few minutes. Try again in a few minutes."


def _slow_down(bucket: str, user: AuthedUser, words: str) -> None:
    """The per-login limiter in front of anything that can read Stripe or a
    whole period (rate_limit.allow: fail-open, as on every practitioner
    screen). A refusal is a 429 with a plain sentence and Retry-After."""
    import rate_limit
    if not rate_limit.allow(bucket, str(user.id)):
        raise HTTPException(429, words, headers={"Retry-After": str(rate_limit.retry_after(bucket))})


async def stripe_parts(biz_id: str, acct: str, p: "Period", names: Tuple[str, ...]
                       ) -> Tuple[Dict[str, Any], Optional[float], List[str]]:
    """The parts asked for: (part → value, the oldest read's time, the parts
    that failed). Kept parts come from the cache; the rest are read at once.
    "items" is the gifts inside the (at most two) payouts on their way, read
    once the payouts are known."""
    got: Dict[str, Any] = {}
    times: List[float] = []
    failed: List[str] = []
    tenant = _tenant(biz_id, acct)

    async def read(client: httpx.AsyncClient, key: Tuple[str, str, str], name: str, arg: Any = None) -> None:
        hit = _cached(key)
        if hit:
            times.append(hit[0])
            got[key[2]] = hit[1]
            return
        try:
            value = await _part(client, name, acct, p, arg)
        except Exception as e:  # noqa: BLE001 — that part is null, and isn't kept
            failed.append(name)
            if not isinstance(e, StripeDown):
                logger.warning("payments overview: %s read failed: %s", name, type(e).__name__)
            return
        got[key[2]] = value
        times.append(_keep(key, value))

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        await asyncio.gather(*(read(client, (tenant, _scope(n, p), n), n) for n in names if n != "items"))
        if "items" in names and got.get("payouts") is not None:
            jobs = []
            for po in pending_payouts(got["payouts"])[:2]:
                pid = str(po.get("id") or "")
                if not po.get("automatic") or not _STRIPE_ID.fullmatch(pid):
                    # Only an automatic payout can be asked for its gifts.
                    got[f"items:{pid}"] = {"rows": None, "complete": False}
                    continue
                jobs.append(read(client, (tenant, "-", f"items:{pid}"), "items", pid))
            await asyncio.gather(*jobs)
    return got, (min(times) if times else None), failed


def pending_payouts(payouts: Any) -> List[Dict[str, Any]]:
    """The payouts on their way to the bank, the first to land first."""
    rows = (payouts or {}).get("rows") or []
    return sorted([r for r in rows if r.get("status") in ("pending", "in_transit")],
                  key=lambda r: (int(r.get("arrival") or 0), r.get("created") or 0))


# ─── Where each gift is ───────────────────────────────────────────────

WHERE_WORDS = {"on_the_way": "On the way", "with_stripe": "With Stripe, on the way", "in_bank": "In the bank",
               "refunded": "Refunded", "part_refunded": "Part refunded", "disputed": "Questioned by the bank",
               "failed": "Didn't go through"}


class Placer:
    """Which payout carried a charge. Stripe's automatic payouts sweep every
    dollar available when the payout is made, so a charge rides the first
    payout made at or after the moment its money became available
    (balance_transaction.available_on). None: still with Stripe."""

    def __init__(self, payouts: Any):
        rows = (payouts or {}).get("rows") or []
        self.rows = sorted([r for r in rows if r.get("status") in ("paid", "pending", "in_transit")],
                           key=lambda r: r.get("created") or 0)
        self.complete = bool((payouts or {}).get("complete"))
        self.oldest = self.rows[0]["created"] if self.rows else None

    def place(self, available_on: Optional[int]) -> Optional[Dict[str, Any]]:
        if not available_on:
            return None
        for r in self.rows:
            if (r.get("created") or 0) >= available_on:
                return r
        return None


def where(ch: Dict[str, Any], placer: Placer) -> Tuple[str, str, Optional[str]]:
    """(where, its words, the payout's id)."""
    if ch.get("status") == "failed":
        return "failed", WHERE_WORDS["failed"], None
    if ch.get("disputed"):
        return "disputed", WHERE_WORDS["disputed"], None
    if ch.get("refunded_cents"):
        full = ch["refunded_cents"] >= ch.get("cents", 0)
        return "refunded", WHERE_WORDS["refunded" if full else "part_refunded"], None
    if ch.get("status") not in ("succeeded", None):
        return "on_the_way", WHERE_WORDS["with_stripe"], None
    po = placer.place(ch.get("available_on"))
    if po is None:
        return "on_the_way", WHERE_WORDS["with_stripe"], None
    # A charge older than the oldest payout read rode a payout this read
    # didn't reach: it is in the bank, and which payout isn't known here.
    unsure = not placer.complete and placer.oldest is not None and (ch.get("available_on") or 0) < placer.oldest
    pid = None if unsure else po.get("id")
    if po.get("status") == "paid":
        return "in_bank", WHERE_WORDS["in_bank"], pid
    return "on_the_way", WHERE_WORDS["on_the_way"], pid


def _kind(ch: Dict[str, Any], rec: Optional[Dict[str, Any]]) -> str:
    if rec:
        return rec["kind"]
    st = (ch.get("metadata") or {}).get("source_type")
    if st == "gift" or (ch.get("description") or "").startswith("Subscription"):
        return "gift"
    if st == "order":
        return "store"
    if st == "event_signup":
        return "event"
    return "other"


def _for(ch: Dict[str, Any], rec: Optional[Dict[str, Any]]) -> Optional[str]:
    if rec:
        return rec["for"]
    md = ch.get("metadata") or {}
    if md.get("source_type") == "gift":
        import giving_week
        return giving_week.fund_of({"gift_fund": md.get("fund")})
    if (ch.get("description") or "").startswith("Subscription"):
        return "A repeating gift"
    if md.get("source_type") == "order":
        return "Store"
    return None


# ─── The overview ─────────────────────────────────────────────────────

def _covered(ch: Dict[str, Any]) -> int:
    return _int((ch.get("metadata") or {}).get("covered_fee_cents"))


def charge_blocks(charges: List[Dict[str, Any]], complete: bool, p: Period, links: Links) -> Dict[str, Any]:
    """The fees, how people gave and who covered the fee, from the period's
    charges that went through."""
    lo, hi = _ts(p.start_at), _ts(p.now)
    went = [c for c in charges if lo <= c["created"] <= hi and c.get("status") == "succeeded"]
    fee = covered = 0
    for c in went:
        f = c.get("fee") or 0
        fee += f
        covered += min(_covered(c), f)
    counts: Dict[str, int] = {}
    for c in went:
        counts[c["method"]] = counts.get(c["method"], 0) + 1
    gifts = [c for c in went if _kind(c, links.find(c)) == "gift"]
    return {
        "fees": {"cents": fee, "covered_by_givers_cents": covered, "church_paid_cents": fee - covered},
        "methods": shares(counts),
        "covered_fee": {"givers": sum(1 for c in gifts if _covered(c) > 0), "of": len(gifts)},
        "counted": {"charges": len(went), "complete": bool(complete)},
    }


def shares(counts: Dict[str, int]) -> List[Dict[str, Any]]:
    """Each way of giving's share, whole percents that add up to 100 (the
    largest remainders get the leftover points)."""
    total = sum(counts.values())
    if not total:
        return []
    raw = {k: v * 100.0 / total for k, v in counts.items()}
    pct = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: (-(raw[k] - pct[k]), -counts[k], k))[: 100 - sum(pct.values())]:
        pct[k] += 1
    return [{"method": k, "words": METHOD_WORDS.get(k, k), "share_pct": pct[k], "count": counts[k]}
            for k in sorted(counts, key=lambda k: (-counts[k], k))]


def _names(biz_id: str, contact_ids: List[str]) -> Dict[str, str]:
    """Contact names for these ids, at this church only."""
    ids = sorted({c for c in contact_ids if c and _UUID.fullmatch(str(c))})
    out: Dict[str, str] = {}
    for i in range(0, len(ids), 100):
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{_q(biz_id)}&id=in.({','.join(ids[i:i + 100])})&select=id,name&limit=100")
        if not isinstance(rows, list):
            raise Failed("contacts")
        for r in rows:
            n = " ".join(str(r.get("name") or "").split())
            if n:
                out[str(r.get("id"))] = n
    return out


def _who(ch: Dict[str, Any], rec: Optional[Dict[str, Any]], names: Dict[str, str]) -> Optional[str]:
    if rec and rec.get("contact_id") and str(rec["contact_id"]) in names:
        return _text(names[str(rec["contact_id"])])[:120] or None
    if rec and rec.get("name"):
        return _text(rec["name"])[:120] or None
    md = ch.get("metadata") or {}
    return _text(md.get("giver_name"))[:120] or _text(ch.get("billing_name"))[:120] or None


def _needs_names(biz_id: str, rows: List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]], see: bool
                 ) -> Dict[str, str]:
    if not see:
        return {}
    return _names(biz_id, [str(r["contact_id"]) for _, r in rows if r and r.get("contact_id")])


def _has_bank_link(biz_id: str) -> Optional[bool]:
    rows = sb_clients.sb_get_as_service(
        f"/plaid_accounts?business_id=eq.{_q(biz_id)}&included_in_bookkeeping=eq.true&deleted_at=is.null"
        "&select=account_id&limit=1")
    if not isinstance(rows, list):
        raise Failed("plaid_accounts")
    return bool(rows)


def _matched(biz_id: str, payout_ids: List[str]) -> set:
    ids = [i for i in payout_ids if _STRIPE_ID.fullmatch(str(i or ""))]
    out: set = set()
    for i in range(0, len(ids), 50):
        rows = sb_clients.sb_get_as_service(
            f"/plaid_transactions?business_id=eq.{_q(biz_id)}&reconciled_to_payout_id=in.({','.join(ids[i:i + 50])})"
            "&select=reconciled_to_payout_id&limit=1000")
        if not isinstance(rows, list):
            raise Failed("plaid_transactions")
        out |= {str(r.get("reconciled_to_payout_id")) for r in rows}
    return out


def _seen_in_bank(biz_id: str, cents: int, day: str) -> bool:
    """An unmatched bank deposit of this payout's amount (±1 cent) within two
    days of its arrival: plaid_reconciliation's own test of a match."""
    try:
        d = date.fromisoformat(day)
    except (TypeError, ValueError):
        return False
    lo, hi = -(cents + 1) / 100.0, -(cents - 1) / 100.0
    rows = sb_clients.sb_get_as_service(
        f"/plaid_transactions?business_id=eq.{_q(biz_id)}&reconciliation_status=eq.unmatched&pending=eq.false"
        f"&amount=gte.{lo:.2f}&amount=lte.{hi:.2f}&date=gte.{(d - timedelta(days=2)).isoformat()}"
        f"&date=lte.{(d + timedelta(days=2)).isoformat()}&select=transaction_id&limit=1")
    return isinstance(rows, list) and bool(rows)


def bank_blocks(biz_id: str, parts: Dict[str, Any], p: Period, placer: Placer, links: Links, a: Access,
                failed: List[str]) -> Dict[str, Any]:
    """What's on the way, in the bank, the next payout and the payouts to
    match. Only ever built for a login with the bank part."""
    out: Dict[str, Any] = {"on_the_way": None, "in_bank": None, "next_payout": None, "unmatched": [],
                           "last4": None}
    payouts = parts.get("payouts")
    if payouts is None:
        return out
    pend = pending_payouts(payouts)
    rows = payouts.get("rows") or []
    out["last4"] = next((r["last4"] for r in sorted(rows, key=lambda r: -(r.get("created") or 0)) if r.get("last4")),
                        None)
    charges = (parts.get("charges") or {}).get("rows")
    bal = parts.get("balance")
    if bal is not None and charges is not None:
        count = 0
        for c in charges:
            if where(c, placer)[0] == "on_the_way" and c.get("status") == "succeeded":
                count += 1
        cents = max(0, sum(r["cents"] for r in pend) + bal["pending"] + bal["available"])
        out["on_the_way"] = {"cents": cents, "count": count, "lands_on": _day_of_ts(pend[0]["arrival"]) if pend else None}
    lo, hi = p.start.isoformat(), p.end.isoformat()
    paid = [r for r in rows if r.get("status") == "paid" and lo <= (_day_of_ts(r.get("arrival")) or "") <= hi]
    try:
        linked = _has_bank_link(biz_id)
        matched = _matched(biz_id, [r["id"] for r in paid]) if linked and paid else set()
    except Failed:
        failed.append("bank")
        linked, matched = None, set()
    all_matched = (all(r["id"] in matched for r in paid) if linked and paid else None)
    out["in_bank"] = {"cents": sum(r["cents"] for r in paid), "payouts": len(paid), "all_matched": all_matched}
    if linked:
        old = (p.end - timedelta(days=MATCH_AFTER_DAYS)).isoformat()
        waiting = [r for r in sorted(paid, key=lambda r: -(r.get("arrival") or 0))
                   if r["id"] not in matched and (_day_of_ts(r.get("arrival")) or "") <= old][:UNMATCHED_MAX]
        for r in waiting:
            day = _day_of_ts(r.get("arrival"))
            out["unmatched"].append({
                "kind": "unmatched_payout", "id": r["id"], "cents": r["cents"], "arrived_on": day,
                "seen_in_bank": _seen_in_bank(biz_id, r["cents"], day or ""),
                "action": {"label": "Match it", "nav": {"tab": "operate", "sub": "bookkeeping",
                                                         "bkTab": "reconciliation"}}})
    if pend:
        nxt = pend[0]
        items = parts.get(f"items:{nxt['id']}")
        block: Dict[str, Any] = {"id": nxt["id"], "cents": nxt["cents"], "lands_on": _day_of_ts(nxt["arrival"]),
                                 "bank_last4": nxt.get("last4") or out["last4"], "items": [], "more": None,
                                 "count": None}
        if items is not None and items.get("rows") is not None:
            its = sorted(items["rows"], key=lambda t: -(t.get("created") or 0))
            shown = its[:NEXT_ITEMS]
            pairs = [(t["charge"] or {}, links.find(t["charge"]) if t.get("charge") else None) for t in shown]
            try:
                names = _needs_names(biz_id, pairs, a.see_names)
            except Failed:
                names = {}
                failed.append("names")
            block["items"] = [{
                "when": _local_day(t.get("created"), p.tz), "who": _who(ch, rec, names) if a.see_names else None,
                "for": _for(ch, rec) if ch else None, "cents": t["cents"], "net_cents": t["net"]}
                for t, (ch, rec) in zip(shown, pairs)]
            block["count"] = len(its)
            block["more"] = max(0, len(its) - len(shown))
            block["count_complete"] = bool(items.get("complete"))
        out["next_payout"] = block
    return out


def dispute_items(parts: Dict[str, Any], tz) -> List[Dict[str, Any]]:
    out = []
    for d in sorted(parts.get("disputes") or [], key=lambda d: int(d.get("due_by") or 0)):
        if not _STRIPE_ID.fullmatch(str(d.get("id") or "")):
            continue
        due = _from_ts(d.get("due_by"))
        base = "https://dashboard.stripe.com/" + ("" if d.get("livemode") else "test/")
        out.append({"kind": "dispute", "id": d["id"], "cents": d["cents"],
                    "given_on": _local_day(d.get("charge_created"), tz), "due_by": _z(due) if due else None,
                    "action": {"label": "Answer the bank", "href": f"{base}disputes/{d['id']}"}})
    return out


def payout_words(schedule: Dict[str, Any]) -> Optional[str]:
    """Stripe's payout schedule in the church's words."""
    interval = str((schedule or {}).get("interval") or "")
    if interval == "daily":
        return "every weekday"
    if interval == "weekly":
        day = str(schedule.get("weekly_anchor") or "").capitalize()
        return f"every {day}" if day else "every week"
    if interval == "monthly":
        n = _int(schedule.get("monthly_anchor"))
        if not 1 <= n <= 31:
            return "once a month"
        suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"on the {n}{suffix} of each month"
    if interval == "manual":
        return "when someone sends them from Stripe"
    return None


# ─── Money going out ──────────────────────────────────────────────────

def _door(fn: Callable[[], Any]) -> Tuple[Optional[Any], bool]:
    """(the block, whether a read failed). A door that refuses is a block
    that isn't this login's: null, and nothing failed."""
    try:
        return fn(), False
    except HTTPException as e:
        return None, e.status_code >= 500
    except Failed:
        return None, True
    except Exception as e:  # noqa: BLE001 — one card never stops the page
        logger.warning("payments overview: going-out read failed: %s", type(e).__name__)
        return None, True


def pay_staff(biz_id: str, user: AuthedUser, p: Period) -> Optional[Dict[str, Any]]:
    """The next payday: the payroll calendar's own door and dates."""
    import payroll_calendar
    import payroll_router
    row = payroll_router._access(biz_id, user, "viewer")
    today = p.end
    horizon = today + timedelta(days=120)
    try:
        rows = payroll_calendar.load(biz_id, today - timedelta(days=45), horizon + timedelta(days=45))
    except payroll_calendar.Unreadable as e:
        raise Failed(str(e))
    events = payroll_calendar.build_events(
        runs=rows["runs"], settings=payroll_calendar.settings_of(row), marked=rows["marked"],
        frequencies=rows["frequencies"], latest=rows["latest"], start=today, end=horizon, today=today)
    nxt = next((e for e in events if e["kind"] == "payday" and e["date"] >= today), None)
    if nxt is None:
        return None
    run = next((r for r in rows["runs"] if nxt.get("run_id") and str(r.get("id")) == nxt["run_id"]), None)
    totals = (run or {}).get("totals") if isinstance((run or {}).get("totals"), dict) else {}
    people = int(totals.get("employees") or 0) if run else len([f for f in rows["frequencies"] if f])
    gross = _cents_of(totals.get("gross")) if run and totals.get("gross") is not None else None
    return {"next_payday": nxt["date"].isoformat(), "people": people, "gross_cents": gross,
            "approve_by": payroll_calendar.approve_by(nxt["date"]).isoformat(), "projected": run is None,
            "run_id": nxt.get("run_id")}


def contractors(biz_id: str, user: AuthedUser, p: Period) -> Optional[Dict[str, Any]]:
    """This year's 1099 payments (paid 1099-eligible bills, the 1099
    summary's own source) and the contractors on file."""
    import contractors_router
    contractors_router._access(biz_id, user, "viewer")
    b = _q(biz_id)
    cons = sb_clients.sb_get_as_service(
        f"/contractors?business_id=eq.{b}&select=id,w9_received_at,stripe_account_id&limit=500")
    if not isinstance(cons, list):
        raise Failed("contractors")
    y = p.end.year
    bills = _all(f"/bills?business_id=eq.{b}&status=eq.paid&is_1099_eligible=eq.true"
                 f"&paid_at=gte.{y}-01-01&paid_at=lte.{y}-12-31T23:59:59&select=id,paid_amount,amount")
    year_cents = sum(_cents_of(r.get("paid_amount") if r.get("paid_amount") is not None else r.get("amount"))
                     for r in bills)
    if not cons and not year_cents:
        return None
    return {"year_cents": year_cents, "people": len(cons),
            "w9_on_file": sum(1 for c in cons if c.get("w9_received_at") or c.get("stripe_account_id"))}


def bills_due(biz_id: str, user: AuthedUser, p: Period) -> Optional[Dict[str, Any]]:
    """The bills due this week (Monday to Sunday) and not yet paid."""
    import bills_router
    bills_router._reader(biz_id, user)
    rows = sb_clients.sb_get_as_service(
        f"/bills?business_id=eq.{_q(biz_id)}&status=not.in.(paid,cancelled)"
        f"&due_date=gte.{p.week_start.isoformat()}&due_date=lte.{p.week_end.isoformat()}"
        "&select=id,vendor_name,amount,paid_amount,due_date&order=due_date.asc&limit=200")
    if not isinstance(rows, list):
        raise Failed("bills")
    cents = sum(max(0, _cents_of(r.get("amount")) - _cents_of(r.get("paid_amount"))) for r in rows)
    names = []
    for r in rows:
        n = " ".join(str(r.get("vendor_name") or "").split())[:60]
        if n and n.lower() not in [x.lower() for x in names]:
            names.append(n)
    return {"due_this_week": len(rows), "cents": cents, "names": names[:3]}


def going_out(biz_id: str, user: AuthedUser, p: Period) -> Tuple[Dict[str, Any], bool]:
    out, bad = {}, False
    for key, fn in (("pay_staff", pay_staff), ("contractors", contractors), ("bills", bills_due)):
        out[key], failed = _door(lambda fn=fn: fn(biz_id, user, p))
        bad = bad or failed
    return out, bad


# ─── The routes ───────────────────────────────────────────────────────

def _period_json(p: Period) -> Dict[str, Any]:
    return {"key": p.key, "label": p.label, "start": p.start.isoformat(), "end": p.end.isoformat(),
            "week_starts": "monday"}


def _can(a: Access) -> Dict[str, Any]:
    return {"see_names": a.see_names, "see_bank": a.see_bank, "refund": a.refund, "download": a.see_bank}


def _records(biz_id: str, p: Period, prior: bool = True
             ) -> Tuple[Optional[List[Dict[str, Any]]], Optional[List[Dict[str, Any]]], bool]:
    """(the rows from read_start on, so a charge on the way can be linked to
    its record; the same stretch of the period before, given; whether a read
    failed)."""
    try:
        rows = read_records(biz_id, read_start(p), p.now)
    except Failed:
        return None, None, True
    if not prior:
        return rows, None, False
    try:
        before = _within(read_records(biz_id, p.prior_start_at, p.prior_end_at), p.prior_start_at, p.prior_end_at)
    except Failed:
        return rows, None, True
    return rows, before, False


@router.get("/overview")
async def payments_overview(biz: str, period: Optional[str] = None,
                            user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The Overview: where the period's money is, what needs someone, the
    funds, how people gave and the money going out. Read-only."""
    a = _access(biz, user)
    key = _period_key(period)
    bid = str(a.biz["id"])
    if not a.biz.get("stripe_account_id"):
        # Today's setup shows instead. Only the owner connects Stripe.
        return {"connected": False, "setup_href": None, "can_connect": a.disconnect}
    p = period_of(key, _clock(a.biz))
    rows, prior, partial = await asyncio.to_thread(_records, bid, p)
    links = Links(rows or [])
    now_rows = _within(rows, p.start_at, p.now) if rows is not None else None
    out: Dict[str, Any] = {
        "checked_at": None, "period": _period_json(p), "connected": True,
        "path": {"given": given_block(now_rows, prior) if now_rows is not None else None,
                 "fees": None, "on_the_way": None, "in_bank": None},
        "next_payout": None, "needs_you": [], "by_fund": by_fund(now_rows) if now_rows is not None else None,
        "methods": None, "covered_fee": None, "counted": None,
        "going_out": None,
        "stripe": {"payout_words": None, "bank_last4": None, "can_disconnect": a.disconnect},
        "can": _can(a),
    }
    if a.see_bank:
        wanted = ("balance", "account", "disputes", "payouts", "charges", "items")
        if cold(bid, str(a.biz["stripe_account_id"]), p, wanted):
            _slow_down("payments_stripe", user, STRIPE_429)
        parts, checked, failed = await stripe_parts(bid, str(a.biz["stripe_account_id"]), p, wanted)
        out["checked_at"] = _z(datetime.fromtimestamp(checked, timezone.utc)) if checked else None
        placer = Placer(parts.get("payouts"))
        charges = parts.get("charges")
        if charges is not None:
            cb = charge_blocks(charges["rows"], period_complete(charges, p), p, links)
            out["path"]["fees"] = cb["fees"]
            out["methods"], out["covered_fee"], out["counted"] = cb["methods"], cb["covered_fee"], cb["counted"]
        bank = await asyncio.to_thread(bank_blocks, bid, parts, p, placer, links, a, failed)
        out["path"]["on_the_way"], out["path"]["in_bank"] = bank["on_the_way"], bank["in_bank"]
        out["next_payout"] = bank["next_payout"]
        out["needs_you"] = (dispute_items(parts, p.tz) if "disputes" in parts else []) + bank["unmatched"]
        acct = parts.get("account")
        out["stripe"]["payout_words"] = payout_words(acct["schedule"]) if acct else None
        out["stripe"]["bank_last4"] = bank["last4"] or (acct or {}).get("last4")
        partial = partial or bool(failed)
    out["going_out"], bad = await asyncio.to_thread(going_out, bid, user, p)
    out["partial"] = bool(partial or bad)
    return out


# ─── The feed ─────────────────────────────────────────────────────────

def _filter_key(f: Optional[str]) -> str:
    k = (f or "all").strip().lower()
    if k not in FILTERS:
        raise HTTPException(400, "Choose All, Gifts, Store, Events, Refunded, Questioned or On the way.")
    return k


def _search(q: Optional[str]) -> Optional[Tuple[str, Optional[int]]]:
    s = " ".join(str(q or "").split())[:Q_MAX].casefold()
    if not s:
        return None
    num = s.replace("$", "").replace(",", "").strip()
    try:
        cents = int(round(float(num) * 100)) if re.fullmatch(r"[0-9]+(\.[0-9]{1,2})?", num) else None
    except ValueError:
        cents = None
    return s, cents


def _how(ch: Dict[str, Any], a: Access) -> str:
    """How it was paid. A card's or bank account's last four point at the
    person who gave, so they are shown only to a login that may see who gave."""
    return ch["how"] if a.see_names else METHOD_WORDS.get(ch["method"], "Online")


def _when(ch: Dict[str, Any], a: Access, tz) -> Optional[str]:
    """When it was given. To the second for a login that may see who gave;
    for one that may not, the church's day only ("2026-11-18"): a time, with
    the amount, the fund and the method, could point at one person in a
    small church."""
    at = _from_ts(ch["created"])
    if at is None:
        return None
    return _z(at) if a.see_names else at.astimezone(tz).date().isoformat()


def feed_row(ch: Dict[str, Any], rec: Optional[Dict[str, Any]], placer: Placer, names: Dict[str, str],
             a: Access, tz) -> Dict[str, Any]:
    w, words, pid = where(ch, placer)
    return {"id": ch["id"], "when": _when(ch, a, tz),
            "who": _who(ch, rec, names) if a.see_names else None, "for": _for(ch, rec), "kind": _kind(ch, rec),
            "how": _how(ch, a), "method": ch["method"], "cents": ch["cents"], "refunded_cents": ch["refunded_cents"],
            "fee_cents": ch.get("fee"), "fee_covered": _covered(ch) > 0, "where": w, "where_words": words,
            "payout_id": pid}



def _matches(ch: Dict[str, Any], rec: Optional[Dict[str, Any]], placer: Placer, f: str,
             search: Optional[Tuple[str, Optional[int]]], a: Access, names: Dict[str, str]) -> bool:
    """Whether a charge is one the filter and the search keep. The search
    reads only what this login is shown: a name only when it may see who gave."""
    if f == "gifts" and _kind(ch, rec) != "gift":
        return False
    if f == "store" and _kind(ch, rec) != "store":
        return False
    if f == "events" and _kind(ch, rec) != "event":
        return False
    if f in ("refunded", "disputed", "on_the_way") and where(ch, placer)[0] != f:
        return False
    if search is None:
        return True
    s, cents = search
    if cents is not None and cents in (ch["cents"], ch["refunded_cents"]):
        return True
    hay = [_how(ch, a), _for(ch, rec) or "", where(ch, placer)[1]]
    if a.see_names:
        hay.append(_who(ch, rec, names) or "")
    return any(s in h.casefold() for h in hay)


Pair = Tuple[Dict[str, Any], Optional[Dict[str, Any]]]


async def _feed_source(a: Access, p: Period, user: AuthedUser
                       ) -> Tuple[Dict[str, Any], Optional[float], Links, Placer, List[Pair], bool]:
    """What the feed and its download read: the period's charges (kept, or
    read now) with each one's record, and where the payouts put them. The
    rows are Stripe's charges, so they are the bank part's, the Payouts tab's
    own door."""
    if not a.see_bank:
        raise HTTPException(403, BANK_KEPT)
    if not a.biz.get("stripe_account_id"):
        raise HTTPException(409, NOT_CONNECTED)
    wanted = ("payouts", "charges")
    if cold(str(a.biz["id"]), str(a.biz["stripe_account_id"]), p, wanted):
        _slow_down("payments_stripe", user, STRIPE_429)
    parts, checked, failed = await stripe_parts(str(a.biz["id"]), str(a.biz["stripe_account_id"]), p, wanted)
    if failed:
        raise HTTPException(503, "Stripe couldn't be read just now. Try again in a minute.")
    rows, _before, _bad = await asyncio.to_thread(_records, str(a.biz["id"]), p, False)
    links = Links(rows or [])
    lo, hi = _ts(p.start_at), _ts(p.now)
    pairs = [(c, links.find(c)) for c in parts["charges"]["rows"] if lo <= c["created"] <= hi]
    return parts, checked, links, Placer(parts["payouts"]), pairs, period_complete(parts["charges"], p)


async def _more_charges(a: Access, p: Period, after: str, pages: int, links: Links) -> Tuple[List[Pair], bool]:
    """The period's charges past the kept ones, read now (the kept read
    stops at CHARGE_PAGES): (rows, whether that was all of them)."""
    if not _STRIPE_ID.fullmatch(after or ""):
        return [], True
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            rows, complete = await _list(client, "/charges", str(a.biz["stripe_account_id"]), [
                ("created[gte]", _ts(p.start_at)), ("created[lte]", _ts(p.now)),
                ("expand[]", "data.balance_transaction")], pages, after=after)
    except StripeDown:
        raise HTTPException(503, "Stripe couldn't be read just now. Try again in a minute.")
    return [(c, links.find(c)) for c in (_charge(r) for r in rows)], complete


@router.get("/feed")
async def payments_feed(biz: str, period: Optional[str] = None, filter: Optional[str] = None,
                        q: Optional[str] = None, starting_after: Optional[str] = None,
                        user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Every gift and payment in the period, newest first, FEED_PAGE at a
    time. `next` is the cursor for the next page (starting_after)."""
    a = _access(biz, user)
    key, f, search = _period_key(period), _filter_key(filter), _search(q)
    if starting_after is not None and not _STRIPE_ID.fullmatch(starting_after):
        raise HTTPException(400, "That page isn't valid. Start again.")
    _slow_down("payments_feed", user, FEED_429)
    p = period_of(key, _clock(a.biz))
    bid = str(a.biz["id"])
    _parts, checked, links, placer, pairs, complete = await _feed_source(a, p, user)
    # A search reads names only for a login that may see them, so the names
    # of every row are needed first; otherwise only the page's own.
    by_name = search is not None and a.see_names
    try:
        names = await asyncio.to_thread(_needs_names, bid, pairs, by_name)
    except Failed:
        names = {}
    ids = [c["id"] for c, _ in pairs]
    live_after: Optional[str] = None
    if not starting_after:
        pos = 0
    elif starting_after in ids:
        pos = ids.index(starting_after) + 1
    elif complete:
        raise HTTPException(400, "That page isn't there any more. Start again.")
    else:
        pos, live_after = len(pairs), starting_after      # past the kept charges: read on from Stripe
    picked: List[Pair] = []
    last = [starting_after]

    def take(seq: List[Pair]) -> bool:
        """Fill the page from seq; True when it is full and another row waits."""
        for c, rec in seq:
            if _matches(c, rec, placer, f, search, a, names):
                if len(picked) == FEED_PAGE:
                    return True
                picked.append((c, rec))
            last[0] = c["id"]
        return False

    has_more = take(pairs[pos:])
    if not has_more and not complete:
        after = live_after or (ids[-1] if ids else None)
        if after:
            more, done = await _more_charges(a, p, after, LIVE_PAGES, links)
            if by_name:
                try:
                    names.update(await asyncio.to_thread(_needs_names, bid, more, True))
                except Failed:
                    pass
            has_more = take(more) or not done
    if not by_name:
        try:
            names = await asyncio.to_thread(_needs_names, bid, picked, a.see_names)
        except Failed:
            names = {}
    total = sum(1 for c, rec in pairs if _matches(c, rec, placer, f, search, a, names)) if complete else None
    shown = None
    if live_after is None:
        shown = sum(1 for c, rec in pairs[:pos] if _matches(c, rec, placer, f, search, a, names)) + len(picked)
    return {"rows": [feed_row(c, rec, placer, names, a, p.tz) for c, rec in picked], "has_more": has_more,
            "next": last[0] if has_more else None, "shown": shown, "total": total,
            "checked_at": _z(datetime.fromtimestamp(checked, timezone.utc)) if checked else None,
            "period": _period_json(p), "filter": f, "can": _can(a)}


def _cell(v: Any) -> str:
    """Text a spreadsheet won't run (church_reports._cell): whitespace is
    collapsed and trimmed FIRST, so " =HYPERLINK(...)" is caught too, then a
    cell that starts like a formula is set as text."""
    s = _text(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


def _dollars(c: Optional[int]) -> str:
    return "" if c is None else f"{c / 100:.2f}"


@router.get("/feed.csv")
async def payments_feed_csv(biz: str, period: Optional[str] = None, filter: Optional[str] = None,
                            q: Optional[str] = None, user: AuthedUser = Depends(require_user)) -> Response:
    """Every row of the feed in the period, for the books (the filter and
    search as on the page). Names and times only for a login that may see who
    gave; without that, there is no From and no Time column at all."""
    a = _access(biz, user)
    key, f, search = _period_key(period), _filter_key(filter), _search(q)
    _slow_down("payments_feed_csv", user, DOWNLOADS_429)
    p = period_of(key, _clock(a.biz))
    bid = str(a.biz["id"])
    _parts, _checked, links, placer, pairs, complete = await _feed_source(a, p, user)
    if not complete and pairs:
        more, complete = await _more_charges(a, p, pairs[-1][0]["id"], CSV_PAGES, links)
        pairs = pairs + more
    try:
        names = await asyncio.to_thread(_needs_names, bid, pairs, a.see_names)
    except Failed:
        names = {}
    buf = io.StringIO()
    w = csv.writer(buf)
    head = ["Date", "Time", "From", "For", "How", "Amount", "Refunded", "Stripe fee", "Fee covered by the giver",
            "Where it is", "Payout"]
    if not a.see_names:
        head = [h for h in head if h not in ("Time", "From")]
    w.writerow(head)
    for c, rec in pairs:
        if not _matches(c, rec, placer, f, search, a, names):
            continue
        row = feed_row(c, rec, placer, names, a, p.tz)
        at = _from_ts(c["created"])
        local = at.astimezone(p.tz) if at else None
        cells = [local.date().isoformat() if local else "", local.strftime("%H:%M") if local else "",
                 row["who"] or "Someone", row["for"] or "", row["how"], _dollars(row["cents"]),
                 _dollars(row["refunded_cents"]) if row["refunded_cents"] else "", _dollars(row["fee_cents"]),
                 "yes" if row["fee_covered"] else "", row["where_words"], row["payout_id"] or ""]
        if not a.see_names:
            del cells[1:3]                      # no time of day and no name
        w.writerow([_cell(x) for x in cells])
    if not complete:
        w.writerow([_cell("More gifts and payments than one download holds. Choose a shorter period for the rest.")])
    name = f"payments-{p.key}-{p.end.isoformat()}.csv"
    return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
