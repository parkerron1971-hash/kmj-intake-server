"""
trial_expiry.py — trials given inside the app end on their own (2026-10-01).

THE GAP: a trial started by Stripe ends by itself. When it runs out
without a card, Stripe sets the subscription to `canceled` and the
webhook writes that onto the business. A trial given inside the app
(Platform Chief's extend-trial action, platform_chief_actions.py) has no
Stripe subscription behind it, so nothing ever ended it. SM&M Infinite
Affairs read `trialing` for a month after its trial ended on 2026-08-31.

Access was already right (feature_gates.access_state locks a trialing
business whose trial_ends_at has passed), but everything that reads the
STATUS was not: seat counts, Mission Control, the money auditor.

THE FIX: hourly, a business that is `trialing` with no Stripe
subscription, no comp override, and a trial end in the past is set to
`canceled` with tier `starter`, exactly what a lapsed Stripe trial looks
like. So access, the trial-ended email (lifecycle_emails handles
canceled + trial_ends_at), seats and reports all agree. Extending the
trial again (Platform Chief) sets it back to `trialing`.

Each expiry is noted in the operator log so Kevin sees it. Kill switch:
TRIAL_EXPIRY=off.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx

from lead_admin import _service_headers, SUPABASE_URL

logger = logging.getLogger("trial_expiry")

AGENT = "trial_expiry"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=15.0, pool=10.0)


def enabled() -> bool:
    return (os.environ.get("TRIAL_EXPIRY") or "on").strip().lower() not in (
        "0", "off", "false", "no")


async def expire_tick(now: datetime | None = None) -> Dict[str, Any]:
    """One pass. Never raises (scheduler-safe)."""
    if not enabled():
        return {"skipped": True}
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat()
    headers = _service_headers()
    expired: List[str] = []
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.get(f"{SUPABASE_URL}/rest/v1/businesses", headers=headers, params={
                "select": "id,name,trial_ends_at",
                "subscription_status": "eq.trialing",
                "stripe_subscription_id": "is.null",
                "comp_tier": "is.null",
                "trial_ends_at": f"lt.{stamp}",
                "limit": "200"})
            if r.status_code >= 400:
                logger.warning(f"read failed {r.status_code}: {r.text[:200]}")
                await _record(c, headers, now, False, [], f"could not read trials ({r.status_code})")
                return {"ok": False, "error": f"read {r.status_code}"}
            for b in r.json() or []:
                # Guarded by the same conditions, so a trial extended a
                # moment ago (new end in the future) is left alone.
                p = await c.patch(
                    f"{SUPABASE_URL}/rest/v1/businesses",
                    headers={**headers, "Prefer": "return=representation"},
                    params={"id": f"eq.{b['id']}", "subscription_status": "eq.trialing",
                            "stripe_subscription_id": "is.null",
                            "trial_ends_at": f"lt.{stamp}"},
                    json={"subscription_status": "canceled", "tier": "starter"})
                if p.status_code >= 400 or not p.json():
                    logger.warning(f"expire {b['id']} did not apply: {p.status_code} {p.text[:200]}")
                    continue
                expired.append(b.get("name") or b["id"])
                try:
                    await c.post(
                        f"{SUPABASE_URL}/rest/v1/platform_changelog",
                        headers={**headers, "Prefer": "return=minimal"},
                        json={"category": "note", "status": "done", "agent": AGENT,
                              "title": f"Trial ended: {b.get('name') or b['id']}"[:300],
                              "detail": (f"Its trial ended {str(b.get('trial_ends_at'))[:10]} "
                                         "with no Stripe subscription, so it is now canceled "
                                         "(tier starter), like a lapsed Stripe trial. Extend "
                                         "the trial to give it more time.")})
                except Exception as e:
                    logger.warning(f"changelog note failed: {e}")
            # Every pass leaves a run row, found or not, so Mission Control
            # -> Agents shows when it last checked, not "not run yet".
            await _record(c, headers, now, True, expired,
                          f"ended {len(expired)} trial(s): {', '.join(expired)}" if expired
                          else "no app trials past their end")
    except Exception as e:
        logger.error(f"tick failed: {e}")
        return {"ok": False, "error": str(e)[:300]}
    if expired:
        logger.info(f"expired {len(expired)} app trial(s): {', '.join(expired)}")
    return {"ok": True, "expired": expired}


async def _record(c: httpx.AsyncClient, headers: Dict[str, str], started: datetime,
                  ok: bool, expired: List[str], summary: str) -> None:
    try:
        await c.post(f"{SUPABASE_URL}/rest/v1/platform_agent_runs",
                     headers={**headers, "Prefer": "return=minimal"},
                     json={"agent": AGENT, "started_at": started.isoformat(),
                           "finished_at": datetime.now(timezone.utc).isoformat(),
                           "ok": ok, "findings": len(expired), "summary": summary[:500],
                           "details": {"expired": expired}})
    except Exception as e:
        logger.warning(f"run row failed: {e}")
