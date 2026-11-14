"""
church_texts.py — a church plan's monthly texts: the count, the heads-up,
and the bill for the extra ones.

Kevin approved this on 2026-11-03 (artifact Pdg8hF4pB5n6efoFQmzd8d): every
church plan includes texts each month (Small 500, Growing 1,500, Established
3,000, Large 8,000, set by pricing_config.church_texts_monthly). Past that,
extra texts cost $20 per 1,000 (pricing_config.extra_texts_cents_per_thousand),
added to the next bill.

A TEXT IS NEVER STOPPED
-----------------------
Nothing here sends, holds or refuses a text. A kids pickup code, a sign-in
code or Sunday's announcement goes out whatever the count says. The church
gets a heads-up at 80% and again at 100%, and the extra texts show up on the
next bill.

WHAT IS COUNTED
---------------
Every text the church's line sent this calendar month (UTC), from the
api_usage rows twilio_sms.send_sms writes (sms_usage.py), EXCEPT sign-in
codes. A sign-in code is how a member gets into the app; a church shouldn't
pay because its people logged in.

A text is counted by 160-character part, the way Twilio bills it (Kevin,
2026-11-03: "count what Twilio bills"). A message up to 160 characters is
1 text; a longer one is split into parts of 153 characters, each 1 text (70
and 67 when it carries an emoji or another character outside the plain
texting alphabet). So a 300-character announcement is 2 texts toward the
count. Each row's input_tokens is the parts Twilio bills
(twilio_sms.segments); a row without a number counts as 1. Before this a
message was 1 text however long it was, and at 1.26 cents a part and 1.93
parts a message, every extra text cost more than the 2 cents it was billed.
The plan numbers and the $20 per 1,000 didn't change, only the unit.

Every row is read (paged by id, sb_get_all_as_service, strict), since
PostgREST hands back at most 1,000 rows a read and the parts are summed
here. A count that can't be read, in whole, is None, never 0: no heads-up
and no bill is ever based on a failed or partial read.

THE BILL
--------
bill_tick runs once a day on the scheduler's leader. For each church on a
church plan with an active (or past-due) subscription, it bills the month
that just ended:

  extra = texts (parts) sent - the plan's texts
  cents = extra x 2 cents  (the $20-per-1,000 dial, priced per text rather
          than per started thousand, so 40 texts over cost 80 cents, not $20)

Under the minimum (CHURCH_TEXT_BILL_MIN_CENTS, default $1) nothing is
charged. Otherwise one Stripe invoice item goes on the church's subscription
and lands on its next invoice, saying how many messages went out as how many
texts.

It's billed once per month. The record lives in
businesses.settings.church_texts_bill = {month, state, texts (parts),
messages, included, extra, cents, invoice_item}:
  * The month is claimed (state "billing") with a write filtered on the
    previous record, so two runs can't both claim it.
  * The Stripe call carries an idempotency key for the church and month.
    A run that finds its own "billing" claim (a crash between the claim
    and the charge) first looks for an item it already made (metadata
    kind=church_texts, month), and only creates one if there is none.
  * Then the record becomes "billed", or "none" when there was nothing to
    bill.

CHURCH_TEXT_BILLING=off stops the bill. The count and the heads-up keep
going.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger("church_texts")

KIND = "church_texts"
NOTICE_TYPE = "text_allowance"
SETTINGS_KEY = "church_texts_bill"
NOT_COUNTED_KINDS = ("sms_signin_code",)
BILLABLE_STATUSES = ("active", "past_due")
# The unit in plain words: the heads-up, the church plan cards' "Good to
# know" line (church_site) and the FAQ's church answer (marketing_pages).
UNIT_LINE = "A text is up to 160 characters; a longer one counts as 2 or more."


def _q(v: Any) -> str:
    return quote(str(v), safe="")


# ─── Months ──────────────────────────────────────────────────────────

def _utc(now: Optional[datetime]) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def month_start(now: Optional[datetime] = None) -> datetime:
    return _utc(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month_start(start: datetime) -> datetime:
    return start.replace(year=start.year + 1, month=1) if start.month == 12 \
        else start.replace(month=start.month + 1)


def previous_month_start(now: Optional[datetime] = None) -> datetime:
    start = month_start(now)
    return start.replace(year=start.year - 1, month=12) if start.month == 1 \
        else start.replace(month=start.month - 1)


def month_key(start: datetime) -> str:
    return start.strftime("%Y-%m")


def month_name(start: datetime) -> str:
    return start.strftime("%B")


def _z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── The plan's texts ────────────────────────────────────────────────

def church_plan_of(row: Optional[Dict[str, Any]]) -> Optional[str]:
    """Which church plan a business row is on, or None.

    businesses.subscription_plan holds the Stripe PRICE id, not the plan key
    (stripe_billing._apply_subscription_state writes the price), so it is
    mapped through feature_gates.price_to_plan. An owner-set comp_tier wins,
    as in feature_gates.plan_of. The subscription status isn't checked: a
    past-due church still sees its count."""
    import feature_gates
    if not row:
        return None
    comp = (row.get("comp_tier") or "").strip().lower()
    if comp in feature_gates.CHURCH_PLANS:
        return comp
    plan = feature_gates.price_to_plan().get((row.get("subscription_plan") or "").strip())
    return plan if plan in feature_gates.CHURCH_PLANS else None


def paid_church_plan_of(row: Optional[Dict[str, Any]]) -> Optional[str]:
    """The church plan a business PAYS for through Stripe, or None. A comped
    church (any comp_tier) is never billed for texts."""
    import feature_gates
    if not row or (row.get("comp_tier") or "").strip():
        return None
    plan = feature_gates.price_to_plan().get((row.get("subscription_plan") or "").strip())
    return plan if plan in feature_gates.CHURCH_PLANS else None


def church_price_ids() -> List[str]:
    """The Stripe price ids (monthly and annual) that are church plans."""
    import feature_gates
    return sorted(pid for pid, plan in feature_gates.price_to_plan().items()
                  if plan in feature_gates.CHURCH_PLANS)


def included_for(plan: Optional[str]) -> Optional[int]:
    """The plan's texts a month; None for anything that isn't a church plan.
    `plan` is a plan KEY (church_plan_of), never the stored price id."""
    import feature_gates
    if plan not in feature_gates.CHURCH_PLANS:
        return None
    try:
        n = feature_gates.plan_limits().get(plan, {}).get("texts_monthly")
        return int(n) if n is not None else None
    except Exception:  # noqa: BLE001
        return None


def price_per_thousand_cents() -> int:
    import pricing_config
    return int(pricing_config.extra_texts_cents_per_thousand())


def extra_cents(extra: int) -> int:
    """What `extra` texts past the plan cost, in whole cents, per text."""
    if extra <= 0:
        return 0
    return int(round(extra * price_per_thousand_cents() / 1000))


def bill_min_cents() -> int:
    try:
        return max(0, int(os.environ.get("CHURCH_TEXT_BILL_MIN_CENTS", "100")))
    except ValueError:
        return 100


def billing_on() -> bool:
    return (os.environ.get("CHURCH_TEXT_BILLING") or "on").strip().lower() not in ("off", "0", "false", "no")


# ─── Counting ────────────────────────────────────────────────────────

def _count_path(business_id: str, start: datetime, end: Optional[datetime]) -> str:
    import sms_usage
    path = (f"/api_usage?business_id=eq.{_q(business_id)}&endpoint=eq.{sms_usage.ENDPOINT}"
            f"&created_at=gte.{_z(start)}")
    if end is not None:
        path += f"&created_at=lt.{_z(end)}"
    for kind in NOT_COUNTED_KINDS:
        path += f"&task_type=neq.{kind}"
    return path + "&select=id,input_tokens"


def parts_of(row: Dict[str, Any]) -> int:
    """How many texts one message counts as: the parts Twilio billed for it
    (input_tokens, sms_usage.usage_row). A row without a number still went
    out, so it counts as 1."""
    try:
        n = int((row or {}).get("input_tokens") or 0)
    except (TypeError, ValueError):
        n = 0
    return n if n > 0 else 1


def counted(business_id: str, start: datetime,
            end: Optional[datetime] = None) -> Optional[Tuple[int, int]]:
    """(messages, texts) that count toward the plan, from `start` up to
    `end`: how many messages went out, and how many texts (160-character
    parts) they came to. Every row is read, page by page. None when any page
    can't be read: never a short count, never 0 for a failure. Blocking."""
    if not business_id:
        return None
    try:
        import sb_clients
        rows = sb_clients.sb_get_all_as_service(_count_path(business_id, start, end),
                                                key="id", strict=True)
    except Exception as e:  # noqa: BLE001  (PartialRead included)
        logger.warning(f"[church_texts] count failed: {type(e).__name__}")
        return None
    if not isinstance(rows, list):
        return None
    return len(rows), sum(parts_of(r) for r in rows)


def counted_texts(business_id: str, start: datetime, end: Optional[datetime] = None) -> Optional[int]:
    """Texts (160-character parts) that count toward the plan, from `start`
    up to `end`. None when the count can't be read. Blocking."""
    got = counted(business_id, start, end)
    return None if got is None else got[1]


def summary(business_id: str, plan: Optional[str], *, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """This month's texts for the Billing page and the announcement composer.
    None for a business that isn't on a church plan. `used` is texts, which
    are 160-character parts; `messages` is how many messages they came from.
    Both are None when the count can't be read, and then nothing derived
    from it is filled in."""
    included = included_for(plan)
    if included is None:
        return None
    start = month_start(now)
    got = counted(business_id, start)
    messages, used = got if got is not None else (None, None)
    out: Dict[str, Any] = {
        "included": included,
        "used": used,
        "messages": messages,
        "left": None,
        "extra": None,
        "extra_cents": None,
        "pct": None,
        "month": month_key(start),
        "resets_at": _z(next_month_start(start)),
        "per_thousand_cents": price_per_thousand_cents(),
        "never_blocked": True,
    }
    if used is not None:
        extra = max(0, used - included)
        out.update(left=max(0, included - used), extra=extra, extra_cents=extra_cents(extra),
                   pct=(round(100 * used / included) if included else None))
    return out


# ─── The heads-up ────────────────────────────────────────────────────

def level_for(used: Optional[int], included: Optional[int]) -> Optional[int]:
    if used is None or not included:
        return None
    if used >= included:
        return 100
    if used * 100 >= included * 80:
        return 80
    return None


def _messages(n: int) -> str:
    return f"{n:,} message" + ("" if n == 1 else "s")


def _per_k_words() -> str:
    """The price in words: '$20', or '$12.50' when the dial isn't whole."""
    per_k = price_per_thousand_cents() / 100
    return f"${per_k:,.0f}" if per_k == int(per_k) else f"${per_k:,.2f}"


def notice(level: int, used: int, included: int, start: datetime,
           messages: Optional[int] = None) -> Tuple[str, str]:
    """The heads-up's title and body. `used` is texts (parts); `messages`,
    when known, is how many messages they came from, so a church that sent
    600 long messages can see why it has used 1,200 texts."""
    per_k_s = _per_k_words()
    resets = month_name(next_month_start(start))
    if level >= 100:
        title = f"You've used this month's {included:,} texts"
        sent = f", from {_messages(messages)}" if messages else ""
        body = (f"{used:,} texts so far in {month_name(start)}{sent}. {UNIT_LINE} Every text "
                f"still goes out: pickup codes, sign-in codes, announcements. The ones past "
                f"{included:,} are {per_k_s} per 1,000, added to your next bill. The count starts "
                f"over on {resets} 1.")
    else:
        title = f"{used:,} of your {included:,} texts used this month"
        sent = f" ({_messages(messages)} so far)" if messages else ""
        body = (f"You're past 80% of this month's texts{sent}. {UNIT_LINE} Nothing stops when "
                f"you reach {included:,}: extra texts are {per_k_s} per 1,000 on your next bill. "
                f"The count starts over on {resets} 1.")
    return title, body


def check_allowance(business_id: str, plan: Optional[str] = None, *,
                    now: Optional[datetime] = None) -> Optional[int]:
    """Send the 80% or 100% heads-up if this month has just crossed one and
    it hasn't been sent yet. Returns the level sent, or None. Never raises,
    never blocks a text. `plan` is a plan key (church_plan_of); without one,
    the business row is read. Blocking (call it in a thread from async code)."""
    try:
        import sb_clients
        if plan is None:
            rows = sb_clients.sb_get_as_service(
                f"/businesses?id=eq.{_q(business_id)}&select=comp_tier,subscription_plan&limit=1") or []
            plan = church_plan_of(rows[0]) if rows else None
        included = included_for(plan)
        if included is None:
            return None
        start = month_start(now)
        got = counted(business_id, start)
        messages, used = got if got is not None else (None, None)
        level = level_for(used, included)
        if level is None:
            return None
        sent = sb_clients.sb_get_as_service(
            f"/chief_notifications?business_id=eq.{_q(business_id)}&type=eq.{NOTICE_TYPE}"
            f"&created_at=gte.{_z(start)}&select=id,data&limit=20")
        if not isinstance(sent, list):
            return None          # can't tell what was sent: send nothing rather than twice
        for r in sent:
            d = r.get("data") or {}
            try:
                if d.get("month") == month_key(start) and int(d.get("level") or 0) >= level:
                    return None
            except (TypeError, ValueError):
                continue
        title, body = notice(level, int(used), included, start, messages)
        sb_clients.sb_post_as_service("/chief_notifications", {
            "business_id": business_id,
            "type": NOTICE_TYPE,
            "title": title,
            "body": body,
            "priority": "high" if level >= 100 else "normal",
            "status": "unread",
            "created_at": _utc(now).isoformat(),
            "data": {"month": month_key(start), "level": level, "used": used, "messages": messages,
                     "included": included, "per_thousand_cents": price_per_thousand_cents()},
        }, prefer=None)
        return level
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[church_texts] heads-up failed: {type(e).__name__}: {e}")
        return None


# ─── The bill ────────────────────────────────────────────────────────

def _settings(row: Dict[str, Any]) -> Dict[str, Any]:
    s = row.get("settings")
    return dict(s) if isinstance(s, dict) else {}


def _record(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rec = _settings(row).get(SETTINGS_KEY)
    return rec if isinstance(rec, dict) else None


def _write_record(business_id: str, expect_month: Optional[str], expect_state: Optional[str],
                  rec: Dict[str, Any]) -> bool:
    """Put `rec` in settings only if the record there is still the one this
    run read (its month and state, or nothing). Settings are read fresh and
    merged, so no other key is touched. Blocking."""
    import sb_clients
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(business_id)}&select=id,settings&limit=1")
    if not isinstance(rows, list) or not rows:
        return False
    have = _record(rows[0])
    if (have or {}).get("month") != expect_month or (have or {}).get("state") != expect_state:
        return False
    settings = _settings(rows[0])
    settings[SETTINGS_KEY] = rec
    if expect_month is None:
        where = f"settings->{SETTINGS_KEY}=is.null"
    else:
        where = (f"settings->{SETTINGS_KEY}->>month=eq.{_q(expect_month)}"
                 f"&settings->{SETTINGS_KEY}->>state=eq.{_q(expect_state)}")
    got = sb_clients.sb_patch_as_service(f"/businesses?id=eq.{_q(business_id)}&{where}",
                                         {"settings": settings})
    return isinstance(got, list) and bool(got)


async def _stripe(method: str, path: str, form: Optional[Dict[str, Any]] = None,
                  idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    import httpx
    import stripe_billing as sb
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    flat: Dict[str, str] = {}
    for k, v in (form or {}).items():
        sb._flatten(flat, k, v)
    async with httpx.AsyncClient(timeout=sb.HTTP_TIMEOUT) as c:
        if method == "GET":
            r = await c.get(f"{sb.STRIPE_API_BASE}{path}", auth=(sb._stripe_key(), ""),
                            params=flat, headers=sb._stripe_headers())
        else:
            r = await c.post(f"{sb.STRIPE_API_BASE}{path}", auth=(sb._stripe_key(), ""),
                             data=flat, headers=sb._stripe_headers(headers))
    if r.status_code >= 400:
        raise RuntimeError(f"Stripe {path} {r.status_code}: {r.text[:200]}")
    return r.json()


async def _existing_item(customer: str, business_id: str, month: str, since: datetime) -> Optional[str]:
    """An invoice item this module already made for this church and month,
    whether or not an invoice has taken it yet (a pending-only look would
    miss one the renewal already swept up, and charge again). Items are
    only ever made after the month ends, so `since` (the 1st of the month
    after it) bounds the look. None when there isn't one."""
    page = await _stripe("GET", "/invoiceitems", {"customer": customer, "limit": 100,
                                                   "created": {"gte": int(since.timestamp())}})
    for it in page.get("data") or []:
        md = it.get("metadata") or {}
        if md.get("kind") == KIND and md.get("month") == month and md.get("business_id") == business_id:
            return it.get("id")
    return None


def item_description(start: datetime, rec: Dict[str, Any]) -> str:
    """The invoice line: what was over, the price, and the unit: how many
    messages went out as how many texts. A claim recorded before texts were
    counted by part has no `messages` and was counted by message, so its
    line doesn't claim a unit it wasn't counted in."""
    out = (f"Extra texts, {month_name(start)} {start.year}: {int(rec['extra']):,} past the "
           f"plan's {int(rec['included']):,} ({_per_k_words()} per 1,000).")
    messages = rec.get("messages")
    if messages:
        out += (f" Counted by 160-character part: {_messages(int(messages))} went out as "
                f"{int(rec['texts']):,} texts.")
    return out


async def bill_month(row: Dict[str, Any], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Bill one church for the month that just ended. The row needs id,
    name, settings, comp_tier, subscription_plan (the Stripe price id),
    subscription_status, stripe_customer_id and stripe_subscription_id.
    Returns what happened: {"state": "billed"|"none"|"skipped", ...}. Never
    charges twice for a month, never charges a comped church, and never
    charges from a count it couldn't read."""
    business_id = str(row.get("id") or "")
    if (row.get("comp_tier") or "").strip():
        return {"state": "skipped", "why": "comped"}
    plan = paid_church_plan_of(row)
    included = included_for(plan)
    if not business_id or included is None:
        return {"state": "skipped", "why": "not_church_plan"}
    if row.get("subscription_status") not in BILLABLE_STATUSES:
        return {"state": "skipped", "why": "not_active"}
    customer, sub = row.get("stripe_customer_id"), row.get("stripe_subscription_id")
    if not (customer and sub):
        return {"state": "skipped", "why": "no_subscription"}

    start = previous_month_start(now)
    month = month_key(start)
    have = _record(row)
    if have and have.get("month") == month and have.get("state") in ("billed", "none"):
        return {"state": "skipped", "why": "done", "month": month}
    resuming = bool(have and have.get("month") == month and have.get("state") == "billing")

    got = await asyncio.to_thread(counted, business_id, start, next_month_start(start))
    if got is None:
        return {"state": "skipped", "why": "count_unread", "month": month}
    messages, used = got
    extra = max(0, used - included)
    cents = extra_cents(extra)
    base = {"month": month, "texts": used, "messages": messages, "included": included,
            "extra": extra, "cents": cents, "at": _utc(now).isoformat()}

    if cents < max(1, bill_min_cents()) and not resuming:
        ok = await asyncio.to_thread(_write_record, business_id,
                                     (have or {}).get("month"), (have or {}).get("state"),
                                     {**base, "state": "none"})
        return {"state": "none" if ok else "skipped", "why": None if ok else "claimed", **base}

    if not resuming:
        claimed = await asyncio.to_thread(_write_record, business_id,
                                          (have or {}).get("month"), (have or {}).get("state"),
                                          {**base, "state": "billing"})
        if not claimed:
            return {"state": "skipped", "why": "claimed", "month": month}
    else:
        # The claim's numbers, so a resumed run charges what was claimed
        # (and a claim without messages was counted by message, not part).
        base.update({k: have.get(k) for k in ("texts", "included", "extra", "cents") if have.get(k) is not None})
        base["messages"] = have.get("messages")
        extra, cents = int(base["extra"]), int(base["cents"])

    item_id = (await _existing_item(customer, business_id, month, next_month_start(start))
               if resuming else None)
    if not item_id:
        item = await _stripe("POST", "/invoiceitems", {
            "customer": customer,
            "subscription": sub,
            "amount": cents,
            "currency": "usd",
            "description": item_description(start, base),
            "metadata": {"kind": KIND, "month": month, "business_id": business_id,
                         "texts": base["texts"], "messages": base.get("messages"),
                         "included": base["included"], "extra": extra,
                         "unit": "160-character part" if base.get("messages") is not None else None},
        }, idempotency_key=f"church-texts-{business_id}-{month}")
        item_id = item.get("id")

    await asyncio.to_thread(_write_record, business_id, month, "billing",
                            {**base, "state": "billed", "invoice_item": item_id})
    return {"state": "billed", "invoice_item": item_id, **base}


def _church_rows_path() -> str:
    """Every business on a church plan: paying through one of the church
    prices (subscription_plan holds the PRICE id), or comped to a church plan
    (heads-up only; bill_month never bills a comp)."""
    import feature_gates
    match = [f"comp_tier.in.({','.join(feature_gates.CHURCH_PLANS)})"]
    prices = church_price_ids()
    if prices:
        match.insert(0, f"subscription_plan.in.({','.join(_q(p) for p in prices)})")
    return (f"/businesses?or=({','.join(match)})"
            f"&select=id,name,settings,comp_tier,subscription_plan,subscription_status,"
            f"stripe_customer_id,stripe_subscription_id")


def _church_rows() -> Optional[List[Dict[str, Any]]]:
    import sb_clients
    return sb_clients.sb_get_all_as_service(_church_rows_path(), key="id", strict=True)


async def bill_tick(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Once a day: bill last month's extra texts for every church not billed
    yet, and send any heads-up this month has earned. A church that fails
    is tried again tomorrow; one church's failure never stops the rest."""
    out = {"billed": 0, "none": 0, "skipped": 0, "errors": 0, "notices": 0}
    try:
        rows = await asyncio.to_thread(_church_rows)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[church_texts] church read failed: {type(e).__name__}")
        rows = None
    if rows is None:
        out["errors"] += 1
        return out
    stripe_ready = billing_on() and bool((os.environ.get("STRIPE_SECRET_KEY") or "").strip())
    import sample_church
    rows = sample_church.drop_samples(rows, "id")   # never billed (BE-3)
    for row in rows:
        bid = str(row.get("id") or "")
        if stripe_ready:
            try:
                res = await bill_month(row, now=now)
                out[res["state"] if res["state"] in out else "skipped"] += 1
                if res["state"] == "billed":
                    print(f"[church_texts] billed {bid[:8]} {res.get('month')}: "
                          f"{res.get('extra')} extra texts, {res.get('cents')}c")
            except Exception as e:  # noqa: BLE001
                out["errors"] += 1
                logger.warning(f"[church_texts] bill failed {bid[:8]}: {type(e).__name__}: {e}")
        plan = church_plan_of(row)
        if not plan:
            continue
        level = await asyncio.to_thread(check_allowance, bid, plan, now=now)
        if level:
            out["notices"] += 1
    return out
