"""
money_auditor.py — the Money auditor, the platform's daily look at money
(agent operations plan, Wave 2, 2026-10-01).

THE PATTERN (Kevin's ruling, 2026-07-04): one brain, many senses. Like
Hermes, this is a SENSE: a deterministic daily pass that reads the
billing rails and writes findings. It never converses, never spends AI
tokens, never touches money. Business Chief reads the findings from the
operator log and tells Kevin.

THE BEAT (each run):
  1. Webhook recording. Businesses hold Stripe subscriptions but no
     Stripe event has EVER been recorded: the webhook log is broken
     (the 2026-10-01 discovery, fixed by APPLY-2026-10-01-stripe-webhook-
     events-shape.sql; this check keeps it from going quiet again).
  2. Stuck webhooks: received 30+ minutes ago, neither processed nor
     failed.
  3. Failed webhooks in the last 24h (processed_error set), by type.
  4. Failed payments in the last 24h (live invoice.payment_failed).
  5. Businesses past due on their subscription.
  6. Trials that ended a day or more ago but still read 'trialing': the
     subscription update never arrived.
  7. Paying, but the plan is not one we recognise: an active/trialing
     subscription whose Stripe price maps to no tier and has no comp
     override, so the business silently gets no plan features.
  8. Negative prepaid credit balances.
  9. The database disagrees with Stripe about a subscription's status
     (read-only GET per subscription; Stripe is the record of truth).

NOT YET: gifts vs payouts (ministry giving reconciliation) needs a
decision on which side is the record of truth; it stays a named gap.

THE FLOW (Mission Control → Agents):
  run → platform_agent_runs (every run, findings or not)
      → platform_changelog[agent=money_auditor] (only what needs eyes)
      → Business Chief snapshot → Kevin.

Runs daily at 10:00 UTC (6 AM Eastern) via the shared scheduler, plus
POST /platform/agents/money-auditor/run. Kill switch: MONEY_AUDITOR=off.
It may read and report. Refunds, credits and plan changes stay with a
person.
"""

from __future__ import annotations

import logging
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from lead_admin import _service_headers, SUPABASE_URL

logger = logging.getLogger("money_auditor")

AGENT = "money_auditor"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)
STUCK_MINUTES = 30
TRIAL_GRACE_HOURS = 24


def enabled() -> bool:
    return (os.environ.get("MONEY_AUDITOR") or "on").strip().lower() not in (
        "0", "off", "false", "no")


async def _rows(c: httpx.AsyncClient, headers: Dict[str, str], table: str,
                params: Dict[str, str]) -> Optional[List[Dict[str, Any]]]:
    """Rows, or None when the read failed. None is never read as "none":
    a check that could not see says so instead of reporting all clear."""
    try:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=headers,
                        params=params)
        if r.status_code < 400:
            body = r.json()
            return body if isinstance(body, list) else None
        logger.warning(f"{table} read {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.warning(f"{table} read failed: {e}")
    return None


STRIPE_COMPARE_LIMIT = 200

# The webhook log could not record anything before this (the table had the
# wrong shape until APPLY-2026-10-01-stripe-webhook-events-shape.sql, applied
# 2026-10-01 ~10:45 UTC). Events Stripe sent earlier are lost for good, so
# only later ones count as "sent but not recorded".
WEBHOOK_LOG_SINCE = datetime(2026, 10, 1, 11, 0, tzinfo=timezone.utc)

# Stripe statuses that mean the same thing as a status we store.
_STRIPE_EQUIVALENT = {"incomplete_expired": "canceled"}


def _stripe_key() -> str:
    return (os.environ.get("STRIPE_SECRET_KEY") or "").strip()


async def _stripe_subscription(sub_id: str) -> Optional[Dict[str, Any]]:
    """A subscription as Stripe holds it now (read-only), or None."""
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as s:
            r = await s.get(f"https://api.stripe.com/v1/subscriptions/{sub_id}",
                            auth=(_stripe_key(), ""))
        if r.status_code < 400:
            return r.json()
        logger.warning(f"Stripe subscription {sub_id} read {r.status_code}")
    except Exception as e:
        logger.warning(f"Stripe subscription {sub_id} read failed: {e}")
    return None


async def _stripe_latest_event() -> Optional[Dict[str, Any]]:
    """Stripe's most recent event (read-only), or None."""
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as s:
            r = await s.get("https://api.stripe.com/v1/events", params={"limit": 1},
                            auth=(_stripe_key(), ""))
        if r.status_code < 400:
            data = (r.json() or {}).get("data") or []
            return data[0] if data else None
        logger.warning(f"Stripe events read {r.status_code}")
    except Exception as e:
        logger.warning(f"Stripe events read failed: {e}")
    return None


def _when(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _names(rows: List[Dict[str, Any]], limit: int = 5) -> str:
    names = [(r.get("name") or r.get("id") or "?") for r in rows[:limit]]
    more = f" and {len(rows) - limit} more" if len(rows) > limit else ""
    return ", ".join(names) + more


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


async def audit(c: httpx.AsyncClient, headers: Dict[str, str],
                now: Optional[datetime] = None) -> Dict[str, Any]:
    """The checks themselves. Returns findings and details; writes
    nothing. Each finding: {code, title, detail, pending}."""
    now = now or datetime.now(timezone.utc)
    findings: List[Dict[str, Any]] = []
    details: Dict[str, Any] = {}
    unseen: List[str] = []

    def find(code: str, title: str, detail: str, pending: bool = True) -> None:
        findings.append({"code": code, "title": title, "detail": detail,
                         "pending": pending})

    # Businesses with a Stripe subscription — the denominator for 1, 5–7.
    subs = await _rows(c, headers, "businesses", {
        "select": "id,name,subscription_status,subscription_plan,comp_tier,"
                  "trial_ends_at,stripe_subscription_id",
        "subscription_status": "not.is.null", "limit": "2000"})
    if subs is None:
        unseen.append("subscriptions")
        subs = []
    details["subscriptions"] = dict(Counter(
        (b.get("subscription_status") or "?") for b in subs))

    # 1. Is the webhook log recording what Stripe sends? Compared with
    #    Stripe's own latest event when the key is available: an empty log
    #    is fine on a quiet week, and only a sent-but-unrecorded event is
    #    a problem. Without the key, fall back to "live subscriptions but
    #    an empty log".
    latest_log = await _rows(c, headers, "stripe_webhook_events",
                             {"select": "id,received_at", "order": "received_at.desc",
                              "limit": "1"})
    if latest_log is None:
        unseen.append("webhook log")
    else:
        details["webhook_events_recorded"] = bool(latest_log)
        logged_at = _when(latest_log[0].get("received_at")) if latest_log else None
        latest = await _stripe_latest_event() if _stripe_key() else None
        if latest is not None:
            sent_at = datetime.fromtimestamp(int(latest.get("created") or 0), timezone.utc)
            details["stripe_latest_event"] = sent_at.isoformat()
            settled = (WEBHOOK_LOG_SINCE <= sent_at
                       < now - timedelta(minutes=STUCK_MINUTES))
            if settled and (logged_at is None or logged_at < sent_at - timedelta(minutes=5)):
                find("webhooks:not_recorded",
                     "Money: Stripe sent events that were never recorded",
                     f"Stripe's latest event ({latest.get('type')}, {sent_at:%Y-%m-%d %H:%M} UTC) "
                     f"is not in the webhook log (latest recorded: "
                     f"{logged_at.strftime('%Y-%m-%d %H:%M') + ' UTC' if logged_at else 'none, ever'}). "
                     "Without the log Stripe retries are not caught (a retried checkout "
                     "can be processed twice). Check the Stripe dashboard's webhook "
                     "deliveries for errors, and that "
                     "APPLY-2026-10-01-stripe-webhook-events-shape.sql is applied.")
        elif not latest_log and any(
                b.get("stripe_subscription_id")
                and b.get("subscription_status") in ("active", "trialing", "past_due")
                for b in subs):
            find("webhooks:never_recorded",
                 "Money: Stripe webhooks may not be recorded",
                 "Live Stripe subscriptions exist but the webhook log is empty, and "
                 "Stripe itself could not be checked. Check the Stripe dashboard's "
                 "webhook deliveries.")

    since_24h = (now - timedelta(hours=24)).isoformat()

    # 2. Stuck: received a while ago, never processed, never failed.
    stuck = await _rows(c, headers, "stripe_webhook_events", {
        "select": "id,type,received_at", "processed_at": "is.null",
        "processed_error": "is.null",
        "received_at": f"lt.{(now - timedelta(minutes=STUCK_MINUTES)).isoformat()}",
        "limit": "200"})
    if stuck is None:
        unseen.append("stuck webhooks")
    else:
        details["webhooks_stuck"] = len(stuck)
        if stuck:
            types = Counter(e.get("type") or "?" for e in stuck)
            find("webhooks:stuck",
                 f"Money: {_plural(len(stuck), 'Stripe event')} received but never processed",
                 f"Older than {STUCK_MINUTES} minutes with no result: "
                 + ", ".join(f"{t} ×{n}" for t, n in types.most_common(5))
                 + ". The handler may have crashed mid-event.")

    # 3. Failed in the last 24h.
    errored = await _rows(c, headers, "stripe_webhook_events", {
        "select": "id,type,processed_error", "processed_error": "not.is.null",
        "received_at": f"gte.{since_24h}", "limit": "200"})
    if errored is None:
        unseen.append("failed webhooks")
    else:
        details["webhooks_failed_24h"] = len(errored)
        if errored:
            types = Counter(e.get("type") or "?" for e in errored)
            sample = (errored[0].get("processed_error") or "")[:200]
            find("webhooks:failed",
                 f"Money: {_plural(len(errored), 'Stripe event')} failed to process (24h)",
                 "By type: " + ", ".join(f"{t} ×{n}" for t, n in types.most_common(5))
                 + (f". Latest error: {sample}" if sample else ""))

    # 4. Failed payments in the last 24h (live mode only).
    failed_pay = await _rows(c, headers, "stripe_webhook_events", {
        "select": "id,business_id", "type": "eq.invoice.payment_failed",
        "livemode": "eq.true", "received_at": f"gte.{since_24h}", "limit": "200"})
    if failed_pay is None:
        unseen.append("failed payments")
    else:
        details["payments_failed_24h"] = len(failed_pay)
        if failed_pay:
            biz = {e.get("business_id") for e in failed_pay if e.get("business_id")}
            find("payments:failed",
                 f"Money: {_plural(len(failed_pay), 'failed payment')} in the last 24 hours",
                 f"Across {_plural(len(biz), 'business')}. Stripe retries on its own "
                 "schedule; a person may want to reach out before the subscription "
                 "lapses.")

    # 5. Past due.
    past_due = [b for b in subs if b.get("subscription_status") == "past_due"]
    details["past_due"] = len(past_due)
    if past_due:
        find("subs:past_due",
             f"Money: {_plural(len(past_due), 'business')} past due",
             f"{_names(past_due)}. Past due keeps the seat for now; their card "
             "needs updating before Stripe gives up.")

    # 6. Trials that ended but never turned into anything.
    grace = now - timedelta(hours=TRIAL_GRACE_HOURS)
    overrun = []
    for b in subs:
        # Stripe trials only: a trial given in the app has no subscription
        # to update it and is ended by trial_expiry.py instead.
        if (b.get("subscription_status") != "trialing" or not b.get("trial_ends_at")
                or not b.get("stripe_subscription_id")):
            continue
        try:
            ends = datetime.fromisoformat(str(b["trial_ends_at"]).replace("Z", "+00:00"))
        except ValueError:
            continue
        if ends < grace:
            overrun.append(b)
    details["trials_overrun"] = len(overrun)
    if overrun:
        find("subs:trial_overrun",
             f"Money: {_plural(len(overrun), 'trial')} ended but still read as trialing",
             f"{_names(overrun)}. The trial end date passed over a day ago and no "
             "subscription update arrived, so these businesses keep trial access. "
             "Usually a missed webhook.")

    # 7. Paying, but on a price we do not recognise.
    try:
        from feature_gates import price_to_plan
        known = price_to_plan()
    except Exception:
        known = {}
    if not known:
        unseen.append("plan prices (no STRIPE_PRICE_ID_* configured)")
    else:
        unknown = [b for b in subs
                   if b.get("stripe_subscription_id")
                   and b.get("subscription_status") in ("active", "trialing")
                   and not (b.get("comp_tier") or "").strip()
                   and (b.get("subscription_plan") or "") not in known]
        details["plan_unrecognised"] = len(unknown)
        if unknown:
            find("subs:plan_unrecognised",
                 f"Money: {_plural(len(unknown), 'paying business')} on a plan we don't recognise",
                 f"{_names(unknown)}. Their Stripe price maps to no tier and there is "
                 "no comp override, so they get no plan features while paying. "
                 "Check the STRIPE_PRICE_ID_* settings against Stripe.")

    # 9. The database agrees with Stripe. Creative Genius (2026-10-01):
    #    cancelled in Stripe on Sep 17, still `past_due` here two weeks
    #    later, because two same-second webhooks applied in the wrong
    #    order. Stripe is the record of truth for a subscription.
    linked = await _rows(c, headers, "businesses", {
        "select": "id,name,subscription_status,stripe_subscription_id",
        "stripe_subscription_id": "not.is.null", "limit": "500"})
    if linked is None:
        unseen.append("Stripe comparison (businesses)")
    elif not linked:
        details["stripe_mismatch"] = 0
    elif not _stripe_key():
        unseen.append("Stripe comparison (no STRIPE_SECRET_KEY)")
    else:
        mismatched, unreadable = [], 0
        for b in linked[:STRIPE_COMPARE_LIMIT]:
            sub = await _stripe_subscription(b["stripe_subscription_id"])
            if sub is None:
                unreadable += 1
                continue
            theirs = _STRIPE_EQUIVALENT.get(sub.get("status"), sub.get("status"))
            ours = b.get("subscription_status")
            if theirs != ours:
                mismatched.append(f"{b.get('name') or b['id']} (here {ours or 'none'}, "
                                  f"Stripe {sub.get('status')})")
        details["stripe_mismatch"] = len(mismatched)
        if unreadable:
            unseen.append(f"Stripe comparison ({unreadable} unreadable)")
        if mismatched:
            find("subs:stripe_mismatch",
                 f"Money: {_plural(len(mismatched), 'business')} disagree with Stripe",
                 "; ".join(mismatched[:5])
                 + (f"; and {len(mismatched) - 5} more" if len(mismatched) > 5 else "")
                 + ". Stripe is the record of truth: access and seats here follow "
                 "the database, so these businesses get the wrong access until "
                 "corrected.")

    # 8. Negative prepaid credit balances.
    credits = await _rows(c, headers, "credit_ledger", {
        "select": "business_id,delta_units", "limit": "20000"})
    if credits is None:
        unseen.append("credits")
    else:
        balances: Dict[str, int] = defaultdict(int)
        for r in credits:
            if r.get("business_id"):
                balances[r["business_id"]] += int(r.get("delta_units") or 0)
        negative = {b: v for b, v in balances.items() if v < 0}
        details["credits_negative"] = len(negative)
        if negative:
            find("credits:negative",
                 f"Money: {_plural(len(negative), 'business')} with a negative credit balance",
                 "Burn rows exceed purchases and grants. The burn reconcile should "
                 "cap at what is available, so this points at a bug, not usage.",
                 pending=False)

    details["unseen"] = unseen
    return {"findings": findings, "details": details}


async def _record(c: httpx.AsyncClient, headers: Dict[str, str], started: datetime,
                  ok: bool, findings: List[Dict[str, Any]], summary: str,
                  details: Optional[Dict[str, Any]] = None) -> None:
    try:
        await c.post(f"{SUPABASE_URL}/rest/v1/platform_agent_runs",
                     headers={**headers, "Prefer": "return=minimal"},
                     json={"agent": AGENT, "started_at": started.isoformat(),
                           "finished_at": datetime.now(timezone.utc).isoformat(),
                           "ok": ok, "findings": len(findings),
                           "summary": summary[:500], "details": details or {}})
    except Exception as e:
        logger.warning(f"run row failed: {e}")


async def _log_finding(c: httpx.AsyncClient, headers: Dict[str, str],
                       f: Dict[str, Any]) -> None:
    try:
        await c.post(f"{SUPABASE_URL}/rest/v1/platform_changelog",
                     headers={**headers, "Prefer": "return=minimal"},
                     json={"category": "pending" if f["pending"] else "note",
                           "status": "pending" if f["pending"] else "done",
                           "title": f["title"][:300], "detail": f["detail"][:2000],
                           "agent": AGENT})
    except Exception as e:
        logger.warning(f"finding write failed: {e}")


async def audit_tick() -> Dict[str, Any]:
    """One full pass. Always records a run row; writes findings only when
    something needs eyes. Never raises (scheduler-safe)."""
    if not enabled():
        return {"skipped": True}
    headers = _service_headers()
    started = datetime.now(timezone.utc)
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            result = await audit(c, headers, now=started)
            findings, details = result["findings"], result["details"]
            for f in findings:
                await _log_finding(c, headers, f)
            parts = [f["title"].removeprefix("Money: ") for f in findings]
            if details.get("unseen"):
                parts.append("could not check: " + ", ".join(details["unseen"]))
            summary = "; ".join(parts) if parts else "money rails look right"
            await _record(c, headers, started, True, findings, summary, details)
        logger.info(f"audit complete — {len(findings)} finding(s): {summary[:200]}")
        return {"ok": True, "findings": len(findings), "summary": summary,
                "details": details}
    except Exception as e:
        logger.error(f"audit failed: {e}")
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
                await _record(c, headers, started, False, [], f"audit failed: {e}")
        except Exception:
            pass
        return {"ok": False, "error": str(e)[:300]}
