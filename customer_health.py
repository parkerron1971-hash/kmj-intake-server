"""
customer_health.py — Customer health, every morning (agent operations
plan, Agent 9).

Built ahead of its ~50-customer milestone at Kevin's word. Its job is the
quiet failure no alarm catches: a person signs up, gets stuck, and simply
never comes back. first_week.py already measures what each new business
did; nothing read it every day and said "this one needs a person".

THE SIGNALS (from first_week.first_week_report, newest 25 businesses)
  not back   — signed up 3+ days ago and has not come back since day one.
  not set up — 7+ days in and fewer than the activation number of
               plug-ins set up; names the next step.
  gone quiet — came back before, has a live trial, subscription or comp,
               and has not been seen for 7+ days.

For each (at most MAX_PER_DAY a day, and not one already raised in the
last 30 days) it drafts a short personal check-in from Kevin, specific to
where that business stopped, and leaves it in the operator log for
Business Chief to bring up. IT NEVER SENDS. The note must pass
support_thread.practitioner_safe like every practitioner-facing word.

Skipped: the platform owner's own businesses, and businesses named as
tests. Daily 14:00 UTC (10 AM Eastern). Sonnet via llm_call, units=0,
skipped over the spend cap. Kill switch: CUSTOMER_HEALTH=off.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from lead_admin import _service_headers, SUPABASE_URL

logger = logging.getLogger("customer_health")

AGENT = "customer_health"
MAX_PER_DAY = 5
QUIET_DAYS = 7
NOT_BACK_DAYS = 3
NOT_SET_UP_DAYS = 7
# A business already raised is not raised again for a month: a check-in
# that went unanswered does not get a second nag a week later.
REPEAT_AFTER_DAYS = 30
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=15.0, pool=10.0)
_TEST_NAME = re.compile(r"\btest\b", re.I)

SYSTEM = """You write a short personal check-in from Kevin, the founder of The Solutionist
System (an all-in-one app that runs a small business, with Chief, its built-in
chief of staff), to one business owner who signed up. Kevin will read it, edit
it and decide whether to send it. You never send.

- Warm, plain, first person from Kevin, 60 to 110 words. No hype, no guilt.
- Specific to where they stopped (the facts below). Offer one concrete next
  step, and offer a short call or a reply if they'd like help.
- Never mention tracking, analytics, "we noticed you haven't logged in",
  AI, Claude, agents or how this note was written.
- Sign off: "— Kevin"
Reply with the note text only."""


def enabled() -> bool:
    return (os.environ.get("CUSTOMER_HEALTH") or "on").strip().lower() not in (
        "0", "off", "false", "no")


def _when(v: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def signal(row: Dict[str, Any], now: datetime) -> Optional[Dict[str, str]]:
    """Pure: which signal (if any) a first-week row raises, most urgent first."""
    day = int(row.get("day") or 0)
    name = row.get("name") or "A business"
    plugins = row.get("plugins") or {}
    if day >= NOT_BACK_DAYS and not row.get("returned"):
        return {"code": "not_back",
                "title": f"{name} signed up {day} days ago and hasn't come back",
                "facts": f"Signed up {day} days ago, used the app on the first day only. "
                         f"Furthest onboarding step: {(row.get('onboarding') or {}).get('furthest_step_name') or 'unknown'}."}
    if day >= NOT_SET_UP_DAYS and not row.get("activated"):
        nxt = plugins.get("next")
        return {"code": "not_set_up",
                "title": f"{name} is {day} days in with {plugins.get('done', 0)} of "
                         f"{plugins.get('total', '?')} set up",
                "facts": f"{day} days in; set up {plugins.get('done', 0)} of {plugins.get('total', '?')} "
                         f"things. Next step: {nxt or 'unknown'}."}
    live = row.get("subscription_status") in ("active", "trialing") or row.get("comp_tier")
    seen = _when(row.get("last_seen_at"))
    if live and row.get("returned") and seen and now - seen >= timedelta(days=QUIET_DAYS):
        quiet = (now - seen).days
        return {"code": "gone_quiet",
                "title": f"{name} hasn't been in for {quiet} days",
                "facts": f"Was using the app, last seen {quiet} days ago, "
                         f"{row.get('subscription_status') or 'comped'}."}
    return None


async def _draft_note(c: httpx.AsyncClient, row: Dict[str, Any],
                      sig: Dict[str, str]) -> Optional[str]:
    import chief_models
    import llm_call
    import support_thread as st
    payload = {"model": chief_models.model_for("draft"), "max_tokens": 400, "system": SYSTEM,
               "messages": [{"role": "user", "content":
                             f"Business: {row.get('name')} ({row.get('type') or 'business'}).\n"
                             f"Where they are: {sig['facts']}\nWrite Kevin's note."}]}
    try:
        resp = await llm_call.apost(c, payload, task="customer_health",
                                    business_id=row.get("business_id"), units=0)
        if resp.status_code >= 400:
            return None
        note = llm_call.text_of(resp.json()).strip()
    except Exception as e:
        logger.warning(f"draft failed: {e}")
        return None
    ok, _hits = st.practitioner_safe(note)
    return note if note and ok else None


async def _recently_raised(c: httpx.AsyncClient, headers: Dict[str, str],
                           now: datetime) -> List[str]:
    try:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/platform_changelog", headers=headers, params={
            "agent": f"eq.{AGENT}", "select": "title",
            "created_at": f"gte.{(now - timedelta(days=REPEAT_AFTER_DAYS)).isoformat()}",
            "limit": "500"})
        return [x.get("title") or "" for x in r.json()] if r.status_code < 400 else []
    except Exception:
        return []


async def _owner_business_ids(c: httpx.AsyncClient, headers: Dict[str, str]) -> set:
    try:
        import platform_watchdog
        owner = await platform_watchdog._owner_user_id(c, headers)
        if not owner:
            return set()
        r = await c.get(f"{SUPABASE_URL}/rest/v1/businesses", headers=headers,
                        params={"owner_id": f"eq.{owner}", "select": "id"})
        return {b["id"] for b in r.json()} if r.status_code < 400 else set()
    except Exception:
        return set()


async def health_tick(now: Optional[datetime] = None) -> Dict[str, Any]:
    """One morning pass. Never raises (scheduler-safe)."""
    if not enabled():
        return {"skipped": True}
    now = now or datetime.now(timezone.utc)
    headers = _service_headers()
    raised: List[str] = []
    try:
        import first_week
        report = await asyncio.to_thread(first_week.first_week_report, 60)
        rows = report.get("businesses") or []
        over_budget = False
        try:
            import spend_guard
            over_budget = spend_guard.over_budget()
        except Exception:
            pass
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            own = await _owner_business_ids(c, headers)
            recent = await _recently_raised(c, headers, now)
            for row in rows:
                if len(raised) >= MAX_PER_DAY:
                    break
                if row.get("business_id") in own or _TEST_NAME.search(row.get("name") or ""):
                    continue
                sig = signal(row, now)
                if not sig or any((row.get("name") or "\0") in t for t in recent):
                    continue
                note = None if over_budget else await _draft_note(c, row, sig)
                detail = sig["facts"] + (
                    f"\n\nSuggested note from you (not sent):\n{note}" if note else
                    "\n\nNo note drafted; write to them yourself if it's worth a word.")
                await c.post(f"{SUPABASE_URL}/rest/v1/platform_changelog",
                             headers={**headers, "Prefer": "return=minimal"},
                             json={"category": "pending", "status": "pending", "agent": AGENT,
                                   "title": f"Customer health: {sig['title']}"[:300],
                                   "detail": detail[:2000]})
                raised.append(row.get("name") or row.get("business_id") or "?")
            summary = (f"{len(raised)} business(es) need a word: {', '.join(raised)}"
                       if raised else f"{len(rows)} recent businesses checked; nobody stuck or quiet")
            await c.post(f"{SUPABASE_URL}/rest/v1/platform_agent_runs",
                         headers={**headers, "Prefer": "return=minimal"},
                         json={"agent": AGENT, "started_at": now.isoformat(),
                               "finished_at": datetime.now(timezone.utc).isoformat(),
                               "ok": True, "findings": len(raised), "summary": summary[:500],
                               "details": {"checked": len(rows), "raised": raised}})
        return {"ok": True, "raised": raised}
    except Exception as e:
        logger.error(f"health tick failed: {e}")
        return {"ok": False, "error": str(e)[:300]}
