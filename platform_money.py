"""Mission Control → Money: what the platform costs Kevin, when each bill is
due, and how much of what's left he can pay himself.

Kevin, 2026-11-14: "build a system that literally can track all of this for
my business. when everything is due and cost and savings and a plan so i can
see how much money I should pay myself".

THE BILLS are rows in platform_money_bills (supabase/APPLY-2026-11-14-
platform-money.sql), seeded with his real numbers. A flat bill costs its
amount every month. A usage bill names a live reader that says what it has
cost so far this month; the room projects that to the end of the period
("on pace"). When a reader can't answer (no token set, the vendor timed
out, a page of the read failed) the bill shows its entered amount instead,
marked as such: a reader never fails the page.

  railway        Railway's GraphQL API (RAILWAY_API_TOKEN), its billing period
  digitalocean   DigitalOcean's balance (DIGITALOCEAN_TOKEN), month to date
  twilio         Twilio's own usage records (TWILIO_ACCOUNT_SID + auth), this
                 month and last
  api_usage:<p>  the api_usage ledger summed by provider, this calendar month
                 (UTC) and last; platform rows with no business count too,
                 since every row is Kevin's bill

THE INCOME is the paying subscriptions at their real price (a church on a
founding price id pays the founding price; an annual price counts a twelfth
of the year), grouped by plan. Comped businesses are counted, never priced,
and the platform owner's own businesses aren't income. Aggregates only: no
business name, id or email leaves this module.

THE SPLIT is the owner's: what's left after the month's costs goes to tax,
a reserve and his pay by the percentages in platform_money_config.

Owner-only (require_owner on the router). Live reads are cached ten minutes
in the process; the bills and the split are read on every request, so an
edit shows at once. Until the migration is applied the room reads the seed
below and saving answers 503.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import time
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

import sb_clients
from lead_admin import require_owner

logger = logging.getLogger("platform_money")
router = APIRouter(prefix="/platform/money", tags=["platform-money"],
                   dependencies=[Depends(require_owner)])

BILLS = "/platform_money_bills"
CONFIG = "/platform_money_config"
MIGRATION = "supabase/APPLY-2026-11-14-platform-money.sql"

CACHE_SECONDS = 600.0        # a live read is good for ten minutes
FAIL_CACHE_SECONDS = 60.0    # a failed one is tried again after a minute
HTTP_TIMEOUT = 10.0
SOURCE_TIMEOUT = 20.0        # one reader, all its requests
# The ledger pages through a month of rows (1,000 a page), so it gets longer.
SOURCE_TIMEOUTS = {"api_usage": 45.0}
DUE_WINDOW_DAYS = 35

API_USAGE_PROVIDERS = ("anthropic", "openai", "inworld", "elevenlabs")
LIVE_KEYS = ("railway", "digitalocean", "twilio") + tuple(f"api_usage:{p}" for p in API_USAGE_PROVIDERS)

RAILWAY_URL = "https://backboard.railway.com/graphql/v2"
RAILWAY_QUERY = "{ me { workspaces { customer { currentUsage billingPeriod { start end } } } } }"
DIGITALOCEAN_URL = "https://api.digitalocean.com/v2/customers/my/balance"
TWILIO_BASE = "https://api.twilio.com/2010-04-01/Accounts"

# Kevin's bills on 2026-11-14, the same rows the migration seeds. Read when
# the table isn't there yet, so the room works before the migration.
DEFAULT_BILLS: List[Dict[str, Any]] = [
    {"key": "claude", "vendor": "Claude plan", "what": "Your building tool", "kind": "flat",
     "amount_cents": 20000, "billing_day": 4, "live": None, "note": None, "watch": False, "sort": 10},
    {"key": "supabase", "vendor": "Supabase", "what": "The database", "kind": "flat",
     "amount_cents": 3500, "billing_day": 22, "live": None, "note": None, "watch": False, "sort": 20},
    {"key": "vercel", "vendor": "Vercel", "what": "Hosts the app", "kind": "flat",
     "amount_cents": 2000, "billing_day": 7, "live": None, "note": None, "watch": False, "sort": 30},
    {"key": "resend", "vendor": "Resend", "what": "Email", "kind": "flat",
     "amount_cents": 2000, "billing_day": 23, "live": None, "note": "May go up to $35", "watch": True, "sort": 40},
    {"key": "railway", "vendor": "Railway", "what": "The servers Chief runs on", "kind": "usage",
     "amount_cents": 1300, "billing_day": 27, "live": "railway", "note": None, "watch": False, "sort": 50},
    {"key": "digitalocean", "vendor": "DigitalOcean", "what": "The live-stream server", "kind": "usage",
     "amount_cents": 600, "billing_day": 1, "live": "digitalocean", "note": None, "watch": False, "sort": 60},
    {"key": "twilio", "vendor": "Twilio", "what": "Texts and phone numbers", "kind": "usage",
     "amount_cents": 4000, "billing_day": None, "live": "twilio", "note": "Paid from your Twilio balance",
     "watch": False, "sort": 70},
    {"key": "anthropic", "vendor": "Anthropic", "what": "Chief's AI, by the message", "kind": "usage",
     "amount_cents": 7000, "billing_day": None, "live": "api_usage:anthropic", "note": None, "watch": False, "sort": 80},
    {"key": "openai", "vendor": "OpenAI", "what": "Voice, transcription, backup AI", "kind": "usage",
     "amount_cents": 200, "billing_day": None, "live": "api_usage:openai", "note": None, "watch": False, "sort": 90},
    {"key": "inworld", "vendor": "Inworld", "what": "Spoken voice, pay as you go", "kind": "usage",
     "amount_cents": 0, "billing_day": None, "live": "api_usage:inworld", "note": None, "watch": False, "sort": 100},
    {"key": "elevenlabs", "vendor": "ElevenLabs", "what": "Old voice, being replaced by Inworld", "kind": "usage",
     "amount_cents": 0, "billing_day": None, "live": "api_usage:elevenlabs", "note": None, "watch": False, "sort": 110},
    {"key": "livekit", "vendor": "LiveKit", "what": "Live classes and group meetings", "kind": "usage",
     "amount_cents": 0, "billing_day": None, "live": None,
     "note": "Free plan stops at 5,000 participant-minutes a month; the $50 plan covers 150,000",
     "watch": True, "sort": 120},
    {"key": "r2", "vendor": "Cloudflare R2", "what": "Stored service recordings", "kind": "usage",
     "amount_cents": 0, "billing_day": None, "live": None, "note": None, "watch": False, "sort": 130},
]
DEFAULT_CONFIG: Dict[str, Any] = {"tax_pct": 30, "reserve_pct": 10, "pay_pct": 60, "reserve_goal_months": 3}

BILL_FIELDS = ("key", "vendor", "what", "kind", "amount_cents", "billing_day", "live",
               "note", "watch", "active", "sort")

# The plan model behind the screen's "what if" slider (Kevin's numbers).
PER_CHURCH_COST_CENTS = 1500       # about $10 of AI and $5 of texts a church
CARD_FEE_PCT = 2.9
CARD_FEE_FIXED_CENTS = 30
BASE_STEPS = ((25, 50000), (50, 80000), (100, 150000))


# ─── Time ───────────────────────────────────────────────────────────────

try:
    from zoneinfo import ZoneInfo
    _EASTERN = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001 — no tz database: standard time is close enough for a due date
    _EASTERN = timezone(timedelta(hours=-5))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today(now: datetime) -> date:
    """Kevin's calendar day: a bill due on the 22nd is due on his 22nd."""
    return now.astimezone(_EASTERN).date()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def month_bounds(now: datetime) -> Tuple[datetime, datetime]:
    """The UTC calendar month holding `now`: [start, next month's start)."""
    start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc) if now.month == 12 \
        else datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    return start, end


def last_month_bounds(now: datetime) -> Tuple[datetime, datetime]:
    start, _ = month_bounds(now)
    return month_bounds(start - timedelta(days=1))[0], start


def next_due(billing_day: Any, today: date) -> Optional[date]:
    """The next date on or after `today` that falls on `billing_day`, held
    to the month's last day (31 → Nov 30, Feb 28). None for no due day."""
    try:
        day = int(billing_day)
    except (TypeError, ValueError):
        return None
    if not 1 <= day <= 31:
        return None
    y, m = today.year, today.month
    candidate = date(y, m, min(day, monthrange(y, m)[1]))
    if candidate >= today:
        return candidate
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return date(y, m, min(day, monthrange(y, m)[1]))


def on_pace(so_far_cents: int, start: datetime, end: datetime, now: datetime) -> int:
    """so_far / days elapsed × days in the period. Never projects from less
    than a day (the first hour of a month isn't a month's pace) and never
    below what's already spent."""
    so_far = max(0, int(so_far_cents or 0))
    period = (end - start).total_seconds()
    if period <= 0:
        return so_far
    elapsed = max(86400.0, (now - start).total_seconds())
    if elapsed >= period:
        return so_far
    return max(so_far, int(round(so_far * period / elapsed)))


def _parse_ts(raw: Any) -> datetime:
    dt = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _cents(dollars: Any) -> int:
    """'12.3456' (dollars, as the vendors send it) → 1235."""
    return max(0, int(round(float(dollars) * 100)))


# ─── Live readers ───────────────────────────────────────────────────────
# Each reader returns {live_key: {so_far_cents, last_month_cents, start, end}},
# None when it isn't set up (no token: nothing to read), and raises when it
# is set up and couldn't be read. Nothing here logs a URL, a token or a body.

class ReadFailed(RuntimeError):
    """A vendor answered with an error status, or with a shape we don't know."""


def _http_json(method: str, url: str, *, headers: Optional[Dict[str, str]] = None,
               params: Optional[Dict[str, str]] = None, auth: Optional[Tuple[str, str]] = None,
               json_body: Any = None) -> Any:
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.request(method, url, headers=headers, params=params, auth=auth, json=json_body)
    if resp.status_code >= 400:
        raise ReadFailed(f"status {resp.status_code}")
    return resp.json()


def _why(e: BaseException) -> str:
    """A failure, said without anything it might carry (URLs hold the
    Twilio account id; bodies can echo a token)."""
    return str(e) if isinstance(e, ReadFailed) else type(e).__name__


def provider_of(model: Any, endpoint: Any = None) -> Optional[str]:
    """Who served an api_usage row: api_usage_logger's model map, then the
    endpoint for a row whose model says nothing."""
    import api_usage_logger
    p = api_usage_logger.provider_for(model)
    if p:
        return p
    ep = str(endpoint or "").lower()
    if "eleven" in ep or ep.endswith("tts-el"):
        return "elevenlabs"
    if "inworld" in ep:
        return "inworld"
    return None


def _api_usage_by_provider(start: datetime, end: datetime) -> Dict[str, float]:
    """cost_cents per provider for [start, end), every page (strict: a failed
    page is a failed read, never a smaller total). Texts are left out in the
    query (they are Twilio's bill, read from Twilio)."""
    import sms_usage
    path = (f"/api_usage?created_at=gte.{quote(_iso(start))}&created_at=lt.{quote(_iso(end))}"
            f"&or=(endpoint.is.null,endpoint.neq.{sms_usage.ENDPOINT})"
            f"&select=id,model,endpoint,cost_cents")
    rows = sb_clients.sb_get_all_as_service(path, key="id", strict=True, redact=True) or []
    totals: Dict[str, float] = {}
    for row in rows:
        if sms_usage.is_sms_row(row):
            continue
        provider = provider_of(row.get("model"), row.get("endpoint"))
        if provider not in API_USAGE_PROVIDERS:
            continue
        try:
            cost = float(row.get("cost_cents") or 0)
        except (TypeError, ValueError):
            continue
        totals[provider] = totals.get(provider, 0.0) + cost
    return totals


# A month that is over doesn't change: its totals are read once a process.
_closed_months: Dict[str, Dict[str, float]] = {}


def read_api_usage(now: datetime) -> Dict[str, Dict[str, Any]]:
    start, end = month_bounds(now)
    this = _api_usage_by_provider(start, end)
    last_start, last_end = last_month_bounds(now)
    last: Optional[Dict[str, float]] = _closed_months.get(last_start.strftime("%Y-%m"))
    if last is None:
        try:
            last = _api_usage_by_provider(last_start, last_end)
            _closed_months[last_start.strftime("%Y-%m")] = last
        except Exception as e:  # noqa: BLE001 — last month is context; this month still stands
            logger.warning("money: api_usage last month unread: %s", _why(e))
    return {f"api_usage:{p}": {"so_far_cents": int(round(this.get(p, 0.0))),
                               "last_month_cents": None if last is None else int(round(last.get(p, 0.0))),
                               "start": start, "end": end}
            for p in API_USAGE_PROVIDERS}


def _twilio_auth() -> Optional[Tuple[str, Tuple[str, str]]]:
    sid = (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
    token = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
    if sid and token:
        return sid, (sid, token)
    key_sid = (os.environ.get("TWILIO_API_KEY_SID") or "").strip()
    key_secret = (os.environ.get("TWILIO_API_KEY_SECRET") or "").strip()
    if sid and key_sid and key_secret:
        return sid, (key_sid, key_secret)
    return None


def _twilio_total(body: Any) -> int:
    records = (body or {}).get("usage_records") if isinstance(body, dict) else None
    if not isinstance(records, list):
        raise ReadFailed("twilio: no usage_records")
    if not records:
        return 0
    return _cents(records[0].get("price") or 0)


def read_twilio(now: datetime) -> Optional[Dict[str, Dict[str, Any]]]:
    creds = _twilio_auth()
    if creds is None:
        return None
    sid, auth = creds
    base = f"{TWILIO_BASE}/{quote(sid, safe='')}/Usage/Records"
    params = {"Category": "totalprice"}
    so_far = _twilio_total(_http_json("GET", f"{base}/ThisMonth.json", params=params, auth=auth))
    try:
        last: Optional[int] = _twilio_total(_http_json("GET", f"{base}/LastMonth.json", params=params, auth=auth))
    except Exception as e:  # noqa: BLE001
        logger.warning("money: twilio last month unread: %s", _why(e))
        last = None
    start, end = month_bounds(now)
    return {"twilio": {"so_far_cents": so_far, "last_month_cents": last, "start": start, "end": end}}


def read_railway(now: datetime) -> Optional[Dict[str, Dict[str, Any]]]:
    token = (os.environ.get("RAILWAY_API_TOKEN") or "").strip()
    if not token:
        return None
    body = _http_json("POST", RAILWAY_URL, json_body={"query": RAILWAY_QUERY},
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    if not isinstance(body, dict) or body.get("errors"):
        raise ReadFailed("railway: the query was refused")
    workspaces = (((body.get("data") or {}).get("me") or {}).get("workspaces")) or []
    total, period, seen = 0.0, None, False
    for ws in workspaces:
        customer = (ws or {}).get("customer") or {}
        if customer.get("currentUsage") is None:
            continue
        total += float(customer["currentUsage"])
        seen = True
        bp = customer.get("billingPeriod") or {}
        if period is None and bp.get("start") and bp.get("end"):
            period = (_parse_ts(bp["start"]), _parse_ts(bp["end"]))
    if not seen:
        raise ReadFailed("railway: no usage in the answer")
    start, end = period or month_bounds(now)
    return {"railway": {"so_far_cents": _cents(total), "last_month_cents": None, "start": start, "end": end}}


def read_digitalocean(now: datetime) -> Optional[Dict[str, Dict[str, Any]]]:
    token = (os.environ.get("DIGITALOCEAN_TOKEN") or "").strip()
    if not token:
        return None
    body = _http_json("GET", DIGITALOCEAN_URL, headers={"Authorization": f"Bearer {token}"})
    if not isinstance(body, dict) or body.get("month_to_date_usage") is None:
        raise ReadFailed("digitalocean: no month_to_date_usage")
    start, end = month_bounds(now)
    return {"digitalocean": {"so_far_cents": _cents(body["month_to_date_usage"]),
                             "last_month_cents": None, "start": start, "end": end}}


READERS: Dict[str, Callable[[datetime], Optional[Dict[str, Dict[str, Any]]]]] = {
    "api_usage": read_api_usage,
    "twilio": read_twilio,
    "railway": read_railway,
    "digitalocean": read_digitalocean,
}


def reader_for(live: Optional[str]) -> Optional[str]:
    if not live:
        return None
    if live.startswith("api_usage:"):
        return "api_usage"
    return live if live in READERS else None


# (name, month) → (monotonic at, state, values); state "ok" | "unset" | "failed"
_cache: Dict[Tuple[str, str], Tuple[float, str, Optional[Dict[str, Any]]]] = {}


def forget() -> None:
    _cache.clear()
    _closed_months.clear()
    _income_cache.update(at=None, value=None)


async def _run_reader(name: str, fn: Callable[[datetime], Any], now: datetime,
                      month: str, refresh: bool) -> Tuple[str, Optional[Dict[str, Any]]]:
    key = (name, month)
    hit = _cache.get(key)
    if hit and not refresh:
        at, state, values = hit
        ttl = FAIL_CACHE_SECONDS if state == "failed" else CACHE_SECONDS
        if time.monotonic() - at < ttl:
            return state, values
    try:
        values = await asyncio.wait_for(asyncio.to_thread(fn, now), SOURCE_TIMEOUTS.get(name, SOURCE_TIMEOUT))
        state = "unset" if values is None else "ok"
    except Exception as e:  # noqa: BLE001 — a reader never fails the page
        logger.warning("money: %s live read failed: %s", name, _why(e))
        state, values = "failed", None
    _cache[key] = (time.monotonic(), state, values)
    return state, values


async def live_values(names: List[str], now: datetime, refresh: bool = False) -> Dict[str, Tuple[str, Optional[Dict[str, Any]]]]:
    """reader name → (state, values) for the readers the active bills use."""
    month = f"{now.year:04d}-{now.month:02d}"
    names = sorted(set(n for n in names if n in READERS))
    results = await asyncio.gather(*(_run_reader(n, READERS[n], now, month, refresh) for n in names))
    return dict(zip(names, results))


# ─── Income ─────────────────────────────────────────────────────────────

def _price_ids(*, annual: bool = False, founder: bool = False) -> set:
    import feature_gates
    out = set()
    for env_key in feature_gates.PRICE_ENV_TO_PLAN:
        if annual and "_ANNUAL" not in env_key:
            continue
        if founder and not env_key.startswith("FOUNDER"):
            continue
        pid = (os.environ.get(f"STRIPE_PRICE_ID_{env_key}") or "").strip()
        if pid:
            out.add(pid)
    return out


def _annual_months() -> int:
    try:
        import marketing_pages
        return int(marketing_pages.ANNUAL_MONTHS)
    except Exception:  # noqa: BLE001 — annual is ten months' price everywhere it's sold
        return 10


def plan_name(plan: str) -> str:
    try:
        import billing_limits
        name = billing_limits.PLAN_DISPLAY.get(plan)
        if name:
            return name
    except Exception:  # noqa: BLE001
        pass
    try:
        import churchsavvy_billing
        name = churchsavvy_billing.NAMES.get(plan)
        if name:
            return name
    except Exception:  # noqa: BLE001
        pass
    return plan.replace("_", " ").title()


def monthly_price_cents(plan: str, price_id: str, *, founding_ids: set, founder_ids: set,
                        annual_ids: set) -> Tuple[int, bool]:
    """(what this subscription brings in a month, whether it's a founding
    church price). A church on a founding price id pays the founding price;
    the Founder seat pays its own; an annual price counts a twelfth of its
    year (ten months' price)."""
    import feature_gates
    import pricing_config
    founding = False
    if plan in feature_gates.CHURCH_PLANS:
        if price_id in founding_ids:
            base, founding = pricing_config.church_founding_price_cents().get(plan, 0), True
        else:
            base = pricing_config.church_price_cents().get(plan, 0)
    elif plan in pricing_config.audience_price_cents():
        base = pricing_config.audience_price_cents()[plan]
    elif plan in feature_gates.CHURCHSAVVY_PLANS:
        import churchsavvy_billing
        base = churchsavvy_billing.PRICES.get(plan, 0)
    else:
        tiers = pricing_config.tier_price_cents()
        base = tiers["founder"] if (plan == "professional" and price_id in founder_ids) else tiers.get(plan, 0)
    if price_id in annual_ids:
        return int(round(base * _annual_months() / 12)), founding
    return int(base), founding


def income_from_rows(rows: List[Dict[str, Any]],
                     owner_is_platform: Callable[[Any], Optional[bool]]) -> Dict[str, Any]:
    """Aggregate the paying businesses. `owner_is_platform(owner_id)` answers
    True for the platform owner's own (not income), None when it can't tell
    (left out, and counted as unchecked, so income is never overstated)."""
    import church_founding
    import feature_gates
    plans = feature_gates.price_to_plan()
    founding_ids = church_founding.founding_price_ids()
    founder_ids = _price_ids(founder=True)
    annual_ids = _price_ids(annual=True)
    by_plan: Dict[str, Dict[str, Any]] = {}
    owners: Dict[Any, Optional[bool]] = {}
    mrr = paying = founding = comped = unchecked = 0
    for row in rows or []:
        if str(row.get("comp_tier") or "").strip():
            comped += 1
            continue
        if row.get("subscription_status") not in ("active", "past_due"):
            continue
        price_id = str(row.get("subscription_plan") or "").strip()
        plan = plans.get(price_id)
        if not plan:
            continue
        owner_id = row.get("owner_id")
        if owner_id not in owners:
            owners[owner_id] = owner_is_platform(owner_id)
        mine = owners[owner_id]
        if mine is None:
            unchecked += 1
            continue
        if mine:
            continue
        cents, is_founding = monthly_price_cents(plan, price_id, founding_ids=founding_ids,
                                                 founder_ids=founder_ids, annual_ids=annual_ids)
        entry = by_plan.setdefault(plan, {"plan": plan, "name": plan_name(plan), "count": 0, "cents": 0})
        entry["count"] += 1
        entry["cents"] += cents
        mrr += cents
        paying += 1
        founding += 1 if is_founding else 0
    return {"mrr_cents": mrr, "paying": paying, "founding": founding, "comped": comped,
            "by_plan": sorted(by_plan.values(), key=lambda e: (-e["cents"], e["plan"])),
            "unchecked": unchecked}


def read_income() -> Dict[str, Any]:
    import church_founding
    rows = sb_clients.sb_get_all_as_service(
        "/businesses?or=(subscription_status.in.(active,past_due),comp_tier.not.is.null)"
        "&select=id,owner_id,subscription_status,subscription_plan,comp_tier",
        key="id", strict=True, redact=True) or []
    return income_from_rows(rows, church_founding._owner_is_platform)


_income_cache: Dict[str, Any] = {"at": None, "value": None}


async def income(refresh: bool = False) -> Optional[Dict[str, Any]]:
    """The income, cached like a live read; None when it can't be read."""
    at = _income_cache["at"]
    if not refresh and at is not None:
        ttl = CACHE_SECONDS if _income_cache["value"] is not None else FAIL_CACHE_SECONDS
        if time.monotonic() - at < ttl:
            return _income_cache["value"]
    try:
        value = await asyncio.wait_for(asyncio.to_thread(read_income), SOURCE_TIMEOUT)
    except Exception as e:  # noqa: BLE001 — unread income is said so, never a 500
        logger.warning("money: income unread: %s", _why(e))
        value = None
    _income_cache.update(at=time.monotonic(), value=value)
    return value


# ─── The bills and the split (the database) ─────────────────────────────

def _missing_table(err: Optional[Dict[str, Any]]) -> bool:
    if not err:
        return False
    return err.get("code") in ("42P01", "PGRST205") or err.get("status") == 404


def _not_set_up() -> HTTPException:
    return HTTPException(503, f"Money isn't set up yet: apply {MIGRATION}.")


def _bill_out(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {f: row.get(f) for f in BILL_FIELDS}
    out["active"] = row.get("active", True) is not False
    out["watch"] = bool(row.get("watch"))
    out["amount_cents"] = int(row.get("amount_cents") or 0)
    out["sort"] = int(row.get("sort") if row.get("sort") is not None else 100)
    return out


def load_bills() -> Tuple[List[Dict[str, Any]], bool]:
    """(every bill, active or not; whether they are the code's seed because
    the table isn't there yet). 503 when the table is there and unreadable."""
    rows = sb_clients.sb_get_as_service(f"{BILLS}?select=*&order=sort.asc,vendor.asc&limit=500")
    if isinstance(rows, list):
        return [_bill_out(r) for r in rows], False
    if _missing_table(sb_clients.last_error()):
        return [_bill_out({**b, "active": True}) for b in DEFAULT_BILLS], True
    raise HTTPException(503, "The bills couldn't be read just now. Try again in a minute.")


def _num(value: Any, default: float) -> float | int:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return int(f) if f.is_integer() else f


def _config_out(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"tax_pct": _num(row.get("tax_pct"), DEFAULT_CONFIG["tax_pct"]),
            "reserve_pct": _num(row.get("reserve_pct"), DEFAULT_CONFIG["reserve_pct"]),
            "pay_pct": _num(row.get("pay_pct"), DEFAULT_CONFIG["pay_pct"]),
            "reserve_goal_months": int(_num(row.get("reserve_goal_months"), DEFAULT_CONFIG["reserve_goal_months"]))}


def load_config() -> Tuple[Dict[str, Any], bool]:
    rows = sb_clients.sb_get_as_service(
        f"{CONFIG}?id=eq.1&select=tax_pct,reserve_pct,pay_pct,reserve_goal_months&limit=1")
    if isinstance(rows, list):
        return _config_out(rows[0] if rows else DEFAULT_CONFIG), False
    if _missing_table(sb_clients.last_error()):
        return dict(DEFAULT_CONFIG), True
    raise HTTPException(503, "The split couldn't be read just now. Try again in a minute.")


# ─── The summary (pure, given what was read) ───────────────────────────

def _money(cents: int) -> str:
    return f"${cents / 100:,.0f}" if cents % 100 == 0 or cents >= 10000 else f"${cents / 100:,.2f}"


def cost_row(bill: Dict[str, Any], live: Dict[str, Tuple[str, Optional[Dict[str, Any]]]],
             now: datetime, today: date) -> Dict[str, Any]:
    amount = int(bill.get("amount_cents") or 0)
    due = next_due(bill.get("billing_day"), today)
    row = {"key": bill["key"], "vendor": bill.get("vendor"), "what": bill.get("what"),
           "kind": bill.get("kind"), "source": "entered", "live_error": False,
           "so_far_cents": None, "on_pace_cents": amount, "last_month_cents": None,
           "billing_day": bill.get("billing_day"), "next_due": due.isoformat() if due else None,
           "note": bill.get("note"), "watch": bool(bill.get("watch"))}
    live_key = bill.get("live")
    if bill.get("kind") != "usage" or not live_key:
        return row
    reader = reader_for(live_key)
    state, values = live.get(reader, ("failed", None)) if reader else ("failed", None)
    value = (values or {}).get(live_key) if state == "ok" else None
    if value is None:
        # Not set up is no error: it's the entered amount, as asked. A reader
        # that is set up and didn't answer is.
        row["live_error"] = state != "unset"
        return row
    so_far = int(value["so_far_cents"])
    row.update(source="live", so_far_cents=so_far,
               on_pace_cents=on_pace(so_far, value["start"], value["end"], now),
               last_month_cents=value.get("last_month_cents"))
    return row


def alerts_for(costs: List[Dict[str, Any]], income_value: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One alert a bill at most (its key is the bill's): running high (a live
    bill on pace for over 1.5× last month and over $10), else the note on a
    bill Kevin is watching."""
    out: List[Dict[str, Any]] = []
    for c in costs:
        pace, last = c["on_pace_cents"], c.get("last_month_cents")
        high = (c["source"] == "live" and last is not None and pace > 1000 and pace > 1.5 * last)
        if high:
            body = f"On pace for {_money(pace)} this month, against {_money(int(last))} last month."
            if c.get("watch") and c.get("note"):
                body += f" {c['note']}"
            out.append({"key": c["key"], "title": f"{c['vendor']} is running high", "body": body, "level": "warn"})
        elif c.get("watch"):
            out.append({"key": c["key"], "title": f"Keep an eye on {c['vendor']}",
                        "body": c.get("note") or "You asked to watch this bill.", "level": "warn"})
    if income_value is None:
        out.append({"key": "income", "title": "Income couldn't be read",
                    "body": "Subscriptions didn't answer just now, so income shows as $0. Try again in a minute.",
                    "level": "warn"})
    elif income_value.get("unchecked"):
        n = int(income_value["unchecked"])
        out.append({"key": "income", "title": "Some income isn't counted",
                    "body": (f"{n} paying subscription{'s' if n != 1 else ''} couldn't be checked against your own "
                             "accounts, so they're left out until the next read."),
                    "level": "info"})
    return out


def split_for(left_over: int, config: Dict[str, Any], on_pace_total: int) -> Dict[str, Any]:
    tax_pct, reserve_pct, pay_pct = (float(config[k]) for k in ("tax_pct", "reserve_pct", "pay_pct"))
    months = int(config["reserve_goal_months"])
    tax = reserve = pay = 0
    if left_over > 0:
        tax = int(math.floor(left_over * tax_pct / 100))
        reserve = int(math.floor(left_over * reserve_pct / 100))
        if abs(tax_pct + reserve_pct + pay_pct - 100) < 1e-6:
            pay = left_over - tax - reserve     # the three add up to what's left, to the cent
        else:
            pay = int(math.floor(left_over * pay_pct / 100))
    return {"tax_pct": config["tax_pct"], "reserve_pct": config["reserve_pct"], "pay_pct": config["pay_pct"],
            "reserve_goal_months": months, "tax_cents": tax, "reserve_cents": reserve, "pay_cents": pay,
            "reserve_goal_cents": months * max(0, on_pace_total)}


def plan_model(on_pace_total: int) -> Dict[str, Any]:
    import church_founding
    import pricing_config
    steps: List[List[int]] = []
    floor = 0
    for i, (churches, cents) in enumerate(BASE_STEPS):
        if i == 0 and on_pace_total > cents:
            cents = int(math.ceil(on_pace_total / 5000) * 5000)   # up to the next $50
        cents = max(cents, floor)
        steps.append([churches, cents])
        floor = cents
    return {"founding_price_cents": pricing_config.church_founding_price_cents()["church_growing"],
            "regular_price_cents": pricing_config.church_price_cents()["church_growing"],
            "per_church_cost_cents": PER_CHURCH_COST_CENTS,
            "card_fee_pct": CARD_FEE_PCT, "card_fee_fixed_cents": CARD_FEE_FIXED_CENTS,
            "founding_spots": church_founding.spots(), "base_steps": steps}


def assemble(bills: List[Dict[str, Any]], config: Dict[str, Any],
             live: Dict[str, Tuple[str, Optional[Dict[str, Any]]]],
             income_value: Optional[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    today = _today(now)
    active = [b for b in bills if b.get("active", True) is not False]
    costs = [cost_row(b, live, now, today) for b in active]
    costs.sort(key=lambda c: (-c["on_pace_cents"], c["key"]))
    flat = sum(c["on_pace_cents"] for c in costs if c["kind"] == "flat")
    usage = sum(c["on_pace_cents"] for c in costs if c["kind"] != "flat")
    totals = {"on_pace_cents": flat + usage, "flat_cents": flat, "usage_cents": usage,
              "so_far_usage_cents": sum(c["so_far_cents"] for c in costs
                                        if c["kind"] != "flat" and c["so_far_cents"] is not None)}
    horizon = today + timedelta(days=DUE_WINDOW_DAYS)
    due_next = sorted(
        ({"key": c["key"], "vendor": c["vendor"], "date": c["next_due"],
          "amount_cents": c["on_pace_cents"], "source": c["source"]}
         for c in costs if c["next_due"] and date.fromisoformat(c["next_due"]) <= horizon),
        key=lambda d: (d["date"], d["key"]))
    inc = income_value or {"mrr_cents": 0, "paying": 0, "founding": 0, "comped": 0, "by_plan": []}
    income_out = {"mrr_cents": int(inc["mrr_cents"]), "paying": int(inc["paying"]),
                  "founding": int(inc["founding"]), "comped": int(inc["comped"]),
                  "by_plan": inc["by_plan"], "live_error": income_value is None}
    left_over = income_out["mrr_cents"] - totals["on_pace_cents"]
    return {"ok": True, "month": f"{now.year:04d}-{now.month:02d}",
            "as_of": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "income": income_out, "costs": costs, "totals": totals, "left_over_cents": left_over,
            "split": split_for(left_over, config, totals["on_pace_cents"]),
            "due_next": due_next, "alerts": alerts_for(costs, income_value),
            "plan_model": plan_model(totals["on_pace_cents"])}


# ─── Routes ─────────────────────────────────────────────────────────────

@router.get("/summary")
async def summary(refresh: bool = Query(False)):
    """Everything the Money room shows, in one read. `refresh` reads the
    vendors again instead of the ten-minute copy."""
    now = _now()
    (bills, seed), (config, config_seed) = await asyncio.gather(
        asyncio.to_thread(load_bills), asyncio.to_thread(load_config))
    readers = [reader_for(b.get("live")) for b in bills
               if b.get("active", True) is not False and b.get("kind") == "usage"]
    live, income_value = await asyncio.gather(
        live_values([r for r in readers if r], now, refresh), income(refresh))
    out = assemble(bills, config, live, income_value, now)
    out["setup_needed"] = bool(seed or config_seed)
    return out


_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40].strip("-")


def _clean(text: Optional[str]) -> Optional[str]:
    text = (text or "").strip()
    return text or None


class BillIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: Optional[str] = Field(None, max_length=40)
    vendor: str = Field(min_length=1, max_length=80)
    what: Optional[str] = Field(None, max_length=200)
    kind: Literal["flat", "usage"] = "flat"
    amount_cents: int = Field(0, ge=0, le=100_000_000)
    billing_day: Optional[int] = Field(None, ge=1, le=31)
    live: Optional[str] = None
    note: Optional[str] = Field(None, max_length=500)
    watch: bool = False
    sort: int = Field(100, ge=0, le=10_000)


class BillPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vendor: Optional[str] = Field(None, min_length=1, max_length=80)
    what: Optional[str] = Field(None, max_length=200)
    kind: Optional[Literal["flat", "usage"]] = None
    amount_cents: Optional[int] = Field(None, ge=0, le=100_000_000)
    billing_day: Optional[int] = Field(None, ge=1, le=31)
    note: Optional[str] = Field(None, max_length=500)
    watch: Optional[bool] = None
    active: Optional[bool] = None
    sort: Optional[int] = Field(None, ge=0, le=10_000)


_NULLABLE = {"what", "billing_day", "note"}


class ConfigIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tax_pct: float = Field(ge=0, le=100)
    reserve_pct: float = Field(ge=0, le=100)
    pay_pct: float = Field(ge=0, le=100)
    reserve_goal_months: int = Field(ge=0, le=24)


def _write(fn: Callable[[], Any]) -> Any:
    """Run one write; 503 when the table isn't there, 409 on a taken key."""
    result = fn()
    if result is None:
        err = sb_clients.last_error()
        if _missing_table(err):
            raise _not_set_up()
        if err and err.get("code") == "23505":
            raise HTTPException(409, "There's already a bill with that key.")
        raise HTTPException(503, "That didn't save just now. Try again in a minute.")
    return result


def _key_path(key: str) -> str:
    if not _KEY.match(key or ""):
        raise HTTPException(404, "No bill with that key.")
    return f"{BILLS}?key=eq.{quote(key, safe='')}"


@router.get("/bills")
async def list_bills():
    bills, seed = await asyncio.to_thread(load_bills)
    return {"ok": True, "bills": bills, "setup_needed": seed}


@router.post("/bills")
async def create_bill(req: BillIn):
    key = (req.key or "").strip().lower() or _slug(req.vendor)
    if not _KEY.match(key):
        raise HTTPException(422, "The key has to be lower-case letters, numbers, - or _.")
    if req.live is not None and req.live not in LIVE_KEYS:
        raise HTTPException(422, f"live has to be one of: {', '.join(LIVE_KEYS)}, or empty.")
    vendor = _clean(req.vendor)
    if not vendor:
        raise HTTPException(422, "A bill needs a vendor.")
    body = {"key": key, "vendor": vendor, "what": _clean(req.what), "kind": req.kind,
            "amount_cents": req.amount_cents, "billing_day": req.billing_day, "live": req.live,
            "note": _clean(req.note), "watch": req.watch, "sort": req.sort, "active": True}
    rows = await asyncio.to_thread(_write, lambda: sb_clients.sb_post_as_service(BILLS, body))
    row = rows[0] if isinstance(rows, list) and rows else body
    return {"ok": True, "bill": _bill_out(row)}


@router.patch("/bills/{key}")
async def update_bill(key: str, req: BillPatch):
    path = _key_path(key)
    said = req.model_dump(exclude_unset=True)
    for field, value in said.items():
        if value is None and field not in _NULLABLE:
            raise HTTPException(422, f"{field} can't be empty.")
    if "vendor" in said:
        said["vendor"] = _clean(said["vendor"])
        if not said["vendor"]:
            raise HTTPException(422, "A bill needs a vendor.")
    for field in ("what", "note"):
        if field in said:
            said[field] = _clean(said[field])
    if not said:
        raise HTTPException(422, "Nothing to change.")
    said["updated_at"] = _iso(_now())
    rows = await asyncio.to_thread(_write, lambda: sb_clients.sb_patch_as_service(path, said))
    if not rows:
        raise HTTPException(404, "No bill with that key.")
    return {"ok": True, "bill": _bill_out(rows[0])}


@router.delete("/bills/{key}")
async def delete_bill(key: str):
    """Soft: the bill stops counting (active=false) and can be brought back
    with PATCH active=true."""
    path = _key_path(key)
    rows = await asyncio.to_thread(
        _write, lambda: sb_clients.sb_patch_as_service(path, {"active": False, "updated_at": _iso(_now())}))
    if not rows:
        raise HTTPException(404, "No bill with that key.")
    return {"ok": True, "bill": _bill_out(rows[0])}


@router.get("/config")
async def get_config():
    config, seed = await asyncio.to_thread(load_config)
    return {"ok": True, "config": config, "setup_needed": seed}


@router.put("/config")
async def put_config(req: ConfigIn):
    if abs(req.tax_pct + req.reserve_pct + req.pay_pct - 100) > 1e-6:
        raise HTTPException(422, "Tax, reserve and pay have to add up to 100%.")
    body = {"id": 1, "tax_pct": req.tax_pct, "reserve_pct": req.reserve_pct, "pay_pct": req.pay_pct,
            "reserve_goal_months": req.reserve_goal_months, "updated_at": _iso(_now())}
    rows = await asyncio.to_thread(_write, lambda: sb_clients.sb_post_as_service(
        f"{CONFIG}?on_conflict=id", body, prefer="resolution=merge-duplicates,return=representation"))
    row = rows[0] if isinstance(rows, list) and rows else body
    return {"ok": True, "config": _config_out(row)}
