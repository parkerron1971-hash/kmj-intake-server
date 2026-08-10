"""
spend_guard.py — daily AI-spend circuit breaker, per tenant and platform-wide.

Beta-readiness audit (AI-spend stream): nothing summed total dollars or
stopped a runaway. This is the overnight backstop: a daily-dollar
ceiling checked at the top of the paid AI entry points, which
soft-blocks new AI calls and pushes an alert to the owner when the day's
spend crosses the line.

It began as ONE shared ceiling for the whole platform, and that had a
failure mode worth naming: a single runaway tenant exhausts the shared
cap and Chief goes dark for every other paying practitioner. The people
who get cut off are precisely the ones who did nothing wrong. Fifty
dollars of someone else's loop is not a reason to stop serving them.

So there are now two ceilings:

  PER BUSINESS   the one that should fire in practice. Blocks only the
                 tenant that is running away. Everyone else keeps
                 working.
  PLATFORM       the backstop, unchanged in spirit. It catches what the
                 per-tenant ceiling structurally cannot: many tenants
                 drifting up at once, and spend that belongs to no
                 tenant at all.

The per-tenant sum is only honest because api_usage rows carry a
business_id. Until #470 that was NULL for 22 modules reaching the
llm_call seam — brand_engine, growth_engine, discovery and the rest —
so a per-business sum would have quietly omitted the most expensive
agentic paths while looking like a working control. Attribution shipped
first, deliberately. Spend that is STILL unattributed counts toward the
platform ceiling only; it cannot trip anyone's per-tenant one.

Fail-OPEN by doctrine: any error in the check ALLOWS the call. A
bookkeeping hiccup must never brick Chief. The ceiling is a backstop
against runaways, not a billing gate.

Env:
  DAILY_SPEND_CAP_USD               platform-wide ceiling (default 50).
  DAILY_SPEND_CAP_PER_BUSINESS_USD  per-tenant ceiling (default 25).
  SPEND_GUARD                       'off' disables the block (still logs).
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

import billing_context
import sb_clients

logger = logging.getLogger("spend_guard")

# In-process cache so we don't re-read api_usage on every AI call.
# 60s is fine — a runaway takes minutes to matter, and this bounds the
# extra query load to at most one per minute per instance.
#
# ONE query now serves both ceilings. It reads business_id alongside
# cost_cents and aggregates in memory, rather than issuing a fresh sum
# per tenant: a per-business query would have multiplied the load by the
# number of active tenants, on the hot path of every AI call.
_CACHE_TTL_S = 60
_cache_total_cents: float = 0.0
_cache_by_business: Dict[str, float] = {}
_cache_at: float = 0.0

# Alert dedup: one owner push per threshold per UTC day, per scope.
_alerted: dict = {}


def _cap_cents() -> float:
    try:
        return float(os.environ.get("DAILY_SPEND_CAP_USD", "50")) * 100.0
    except (TypeError, ValueError):
        return 5000.0


def _business_cap_cents() -> float:
    """The per-tenant ceiling.

    Default 25 dollars a day against a measured average near one — a
    build is about $1.50 and a Chief turn about 8 cents, so this is
    roughly ten heavy build days at once before anyone is stopped. Set
    deliberately BELOW the platform ceiling so one tenant cannot consume
    the whole platform's headroom on its own.
    """
    try:
        return float(os.environ.get(
            "DAILY_SPEND_CAP_PER_BUSINESS_USD", "25")) * 100.0
    except (TypeError, ValueError):
        return 2500.0


def _enabled() -> bool:
    return (os.environ.get("SPEND_GUARD") or "on").strip().lower() != "off"


def _utc_day_start_iso() -> str:
    n = datetime.now(timezone.utc)
    return n.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _refresh(force: bool = False) -> Tuple[float, Dict[str, float]]:
    """Read today's api_usage once and aggregate both views of it.

    Fails open to the last known numbers (zeros on a cold start), so a
    Supabase blip never blocks a call.
    """
    global _cache_total_cents, _cache_by_business, _cache_at
    now = time.time()
    if not force and (now - _cache_at) < _CACHE_TTL_S:
        return _cache_total_cents, _cache_by_business
    try:
        rows = sb_clients.sb_get_as_service(
            f"/api_usage?created_at=gte.{_utc_day_start_iso()}"
            f"&select=cost_cents,business_id&limit=100000") or []
        total = 0.0
        by_biz: Dict[str, float] = {}
        for r in rows:
            c = float(r.get("cost_cents") or 0)
            total += c
            biz = r.get("business_id")
            if biz:
                by_biz[str(biz)] = by_biz.get(str(biz), 0.0) + c
        _cache_total_cents, _cache_by_business, _cache_at = total, by_biz, now
        return total, by_biz
    except Exception as e:
        logger.warning(f"[spend_guard] read failed open: {e}")
        return _cache_total_cents, _cache_by_business


def today_spend_cents(force: bool = False,
                      business_id: Optional[str] = None) -> float:
    """Spend since UTC midnight, in cents. Cached 60s.

    With no business_id: the platform total, INCLUDING rows that belong
    to no tenant. With one: that tenant's share only.
    """
    total, by_biz = _refresh(force)
    if business_id:
        return by_biz.get(str(business_id), 0.0)
    return total


def over_budget(business_id: Optional[str] = None) -> bool:
    """True when this call should be soft-blocked. Never raises.

    business_id defaults to the ambient billing tenant, so the existing
    call sites did not have to change: whatever established attribution
    for the row also establishes which ceiling applies to the call.
    """
    try:
        if not _enabled():
            return False
        if business_id is None:
            business_id = billing_context.current()

        total, by_biz = _refresh()
        cap = _cap_cents()
        biz_cap = _business_cap_cents()
        spent = by_biz.get(str(business_id), 0.0) if business_id else 0.0

        # Alert on BOTH scopes before deciding anything, and in that
        # order deliberately. Returning as soon as the platform ceiling
        # trips would be correct for the block and wrong for the owner:
        # the alert would say "the platform is over budget" and never
        # say which tenant drove it there — which is the one fact worth
        # being woken up with.
        _maybe_alert(total, cap, scope="platform")
        if business_id:
            _maybe_alert(spent, biz_cap, scope=str(business_id))

        if total >= cap:
            logger.warning(
                "[spend_guard] PLATFORM over its daily ceiling "
                "(%.0fc of %.0fc) — every tenant is paused", total, cap)
            return True
        if business_id and spent >= biz_cap:
            logger.warning(
                "[spend_guard] business %s over its daily ceiling "
                "(%.0fc of %.0fc) — blocked; other tenants unaffected",
                business_id, spent, biz_cap)
            return True
        return False
    except Exception as e:
        logger.warning(f"[spend_guard] over_budget failed open: {e}")
        return False


def _maybe_alert(spent: float, cap: float, scope: str = "platform") -> None:
    """Push the owner one alert per threshold (50/80/100%) per UTC day.

    Keyed by SCOPE as well as threshold, so a busy tenant crossing its
    own ceiling does not consume the platform alert's dedup slot — the
    two mean very different things and the owner needs to see both.
    """
    if cap <= 0:
        return
    day = datetime.now(timezone.utc).date().isoformat()
    pct = spent / cap
    for mark in (1.0, 0.8, 0.5):
        if pct >= mark:
            key = f"{day}:{scope}:{mark}"
            if key in _alerted:
                return  # highest crossed threshold already alerted today
            _alerted[key] = True
            _push_owner(spent, cap, mark, scope)
            return


def _push_owner(spent: float, cap: float, mark: float,
                scope: str = "platform") -> None:
    try:
        import asyncio
        import httpx
        import platform_watchdog as wd
        import push_notifications
        from lead_admin import _service_headers

        platform = (scope == "platform")
        dollars = spent / 100.0
        cap_dollars = cap / 100.0
        pct_txt = f"{int(mark * 100)}%"
        # Which ceiling, and — the thing the owner actually needs to
        # know at 3am — how much of the platform it just took down.
        who = "Platform-wide AI spend" if platform else f"Business {scope[:8]}"
        blast = ("ALL tenants are paused" if platform
                 else "only this tenant is paused; everyone else is unaffected")
        env_var = ("DAILY_SPEND_CAP_USD" if platform
                   else "DAILY_SPEND_CAP_PER_BUSINESS_USD")
        crossed = ("reached its daily AI-spend ceiling" if mark >= 1.0
                   else f"passed {pct_txt} of its daily AI-spend ceiling")
        note = (f"{who} is ${dollars:.2f} of the ${cap_dollars:.0f} daily cap "
                f"({crossed}). "
                + (f"New AI calls are paused until UTC midnight or you raise "
                   f"{env_var} — {blast}." if mark >= 1.0
                   else "Heads up — still running normally."))

        async def _go():
            headers = _service_headers()
            async with httpx.AsyncClient(timeout=15) as c:
                await wd._log_finding(
                    c, headers,
                    f"{who} at {pct_txt} of daily cap",
                    note, pending=(mark >= 1.0))
                owner = await wd._owner_user_id(c, headers)
            if owner:
                push_notifications.send_to_user(
                    owner,
                    title=(("AI spend paused — daily cap hit" if platform
                            else "One tenant paused — hit its daily cap")
                           if mark >= 1.0 else f"AI spend at {pct_txt} of cap"),
                    body=note, nav="studio")

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_go())
        except RuntimeError:
            asyncio.run(_go())
    except Exception as e:
        logger.warning(f"[spend_guard] owner alert failed (non-fatal): {e}")


def block_message() -> str:
    """The friendly reason returned to a caller when blocked.

    Deliberately identical whichever ceiling tripped. The practitioner's
    experience is the same either way — AI is paused, it comes back —
    and telling a customer "the PLATFORM is over budget" invites the
    reasonable follow-up question of whose fault that is. The
    distinction is in the owner's alert and the logs, where it can be
    acted on.
    """
    return ("AI is paused for the rest of the day — the account hit its "
            "daily usage ceiling. It resets automatically, or the owner "
            "can raise the limit.")
