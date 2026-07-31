"""
balance_sweep.py — the nightly drawdown: completed sessions consume
prepaid balances without anyone typing anything.

THE GAP THIS CLOSES
  The ledger (BE#307) records grants and consumptions faithfully — when
  told. A coach who marks a session completed still had to separately
  tell Chief "Sarah used a session", and the step that has to be
  remembered manually is the step that silently stops happening. This
  sweep closes the loop: yesterday's completed sessions each draw one
  prepaid session, automatically, with the session id on the ledger row.

WHAT THIS JOB IS ALLOWED TO BE (vertical_autopilot's discipline)
  * It reads /sessions — a UNIVERSAL table every vertical writes (the
    booking→session sync mirrors bookings into it). This is not the
    removed no-show job's mistake of querying a table a vertical never
    touches: a business with no completed sessions costs one empty read.
  * Nothing leaves the system. It writes ledger rows and, when a balance
    runs dry or a grant nears expiry, a chief_notification the
    practitioner reads. No emails, no SMS, no Stripe.
  * Kill switch: BALANCE_SWEEP=off.

IDEMPOTENCY — THE LOAD-BEARING PROPERTY
  Every auto-consume carries session_id on its ledger row, and the sweep
  refuses any session that already has a ledger row referencing it. A
  re-run (restart mid-sweep, overlapping window, manual invocation)
  finds the row and skips. The window is also generous on purpose:
  scanning the last 2 days daily means a session missed by one downed
  run is caught by the next, and the session_id check makes the overlap
  free instead of double-billed.

NEVER BELOW ZERO
  The sweep only draws when the view shows a positive session balance,
  and customer_balances.consume() itself refuses insufficient draws and
  self-reverses lost races (see its docstring). A contact with no
  prepaid sessions is simply not the sweep's business — plenty of
  practitioners bill per session; silence is correct there.

EXPIRY WARNINGS
  Grants expiring within EXPIRY_WARN_DAYS produce one notification each
  (deduped by ledger row id in the notification's data), only while the
  contact still holds a positive balance of that kind — an expiring
  grant that is already spent is nothing to warn about.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import customer_balances as cb

logger = logging.getLogger("balance_sweep")

# How far back the daily pass looks for completed sessions. Two days, not
# one: a single missed run must not orphan a day of sessions, and the
# session_id dedupe makes overlap free.
LOOKBACK_DAYS = 2
EXPIRY_WARN_DAYS = 7


def _z(dt: datetime) -> str:
    """PostgREST timestamp class: the Z form, ALWAYS — the +00:00 offset
    form silently returns empty result sets in query strings (#196)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _contact_name(business_id: str, contact_id: str) -> str:
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/contacts?id=eq.{contact_id}&business_id=eq.{business_id}"
        f"&select=name&limit=1") or []
    return (rows[0].get("name") if rows else None) or "A contact"


def _notify(business_id: str, title: str, body: str,
            data: Optional[Dict[str, Any]] = None) -> None:
    """Best-effort in-app notification (notify_practitioner's row shape).
    A failed notification must never fail the sweep — the ledger row is
    the record; the notification is a courtesy."""
    import sb_clients
    try:
        row: Dict[str, Any] = {
            "business_id": business_id, "type": "reminder",
            "title": title[:120], "body": body[:300], "priority": "normal",
        }
        if data:
            row["data"] = data
        sb_clients.sb_post_as_service("/chief_notifications", row)
    except Exception as e:
        logger.warning(f"[balance_sweep] notification failed (non-fatal): {e}")


# ─── the session drawdown pass ───────────────────────────────────────

def _completed_sessions(since: datetime, until: datetime) -> List[Dict[str, Any]]:
    import sb_clients
    return sb_clients.sb_get_as_service(
        f"/sessions?status=eq.completed"
        f"&scheduled_for=gte.{_z(since)}&scheduled_for=lt.{_z(until)}"
        f"&select=id,business_id,contact_id,title,scheduled_for"
        f"&order=scheduled_for.asc&limit=1000") or []


def _already_consumed(session_id: str) -> bool:
    """THE idempotency check: one ledger row per session, ever."""
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/customer_ledger?session_id=eq.{session_id}&select=id&limit=1") or []
    return bool(rows)


def _session_balance_kind(business_id: str, contact_id: str) -> Optional[str]:
    """The kind holding a positive session-unit balance, or None. When a
    contact somehow holds several (package + gift_card of sessions),
    'package' wins — it is what every session-vertical grants by default."""
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/customer_balances?business_id=eq.{business_id}"
        f"&contact_id=eq.{contact_id}&unit=eq.session"
        f"&select=kind,balance") or []
    positive = [r for r in rows if _num(r.get("balance")) > 0]
    if not positive:
        return None
    positive.sort(key=lambda r: (r.get("kind") != "package", r.get("kind") or ""))
    return positive[0].get("kind")


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def consume_for_session(session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One session → at most one drawdown. Returns the consume result,
    or None when the session was skipped (already consumed / no balance
    / incomplete row)."""
    sid = session.get("id")
    biz = session.get("business_id")
    contact = session.get("contact_id")
    if not (sid and biz and contact):
        return None
    if _already_consumed(str(sid)):
        return None
    kind = _session_balance_kind(str(biz), str(contact))
    if not kind:
        return None  # no prepaid sessions — not the sweep's business

    day = str(session.get("scheduled_for") or "")[:10]
    title = (session.get("title") or "").strip()
    reason = f"Session completed {day}" + (f" — {title}" if title else "") + " (auto)"
    res = cb.consume(str(biz), str(contact), 1, kind, "session", reason,
                     session_id=str(sid))
    if not res.get("ok"):
        # consume() guards the floor (and self-reverses lost races); a
        # refusal here means the balance moved between our read and the
        # draw. Log and move on — never force below zero.
        logger.info(f"[balance_sweep] skipped session {sid}: "
                    f"{res.get('error')}")
        return None

    if _num(res.get("balance")) <= 0:
        name = _contact_name(str(biz), str(contact))
        _notify(str(biz),
                f"{name}: prepaid sessions used up",
                f"{name} used their last prepaid session"
                f"{f' on {day}' if day else ''}. Time to offer another "
                f"{kind.replace('_', ' ')}.",
                data={"contact_id": contact, "kind": kind,
                      "source": "balance_sweep"})
    elif res.get("low"):
        name = _contact_name(str(biz), str(contact))
        _notify(str(biz),
                f"{name}: 1 session left",
                f"{name} has one prepaid session remaining on their "
                f"{kind.replace('_', ' ')}.",
                data={"contact_id": contact, "kind": kind,
                      "source": "balance_sweep"})
    return res


# ─── the expiry-warning pass ─────────────────────────────────────────

def _expiry_already_warned(business_id: str, ledger_id: str) -> bool:
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/chief_notifications?business_id=eq.{business_id}"
        f"&data->>ledger_id=eq.{ledger_id}&select=id&limit=1") or []
    return bool(rows)


def warn_expiring() -> int:
    """One notification per expiring grant, while its balance is still
    positive. Deduped forever by ledger row id — a 7-day window swept
    daily must not nag seven times."""
    import sb_clients
    now = _now()
    grants = sb_clients.sb_get_as_service(
        f"/customer_ledger?expires_at=gte.{_z(now)}"
        f"&expires_at=lte.{_z(now + timedelta(days=EXPIRY_WARN_DAYS))}"
        f"&delta=gt.0&select=id,business_id,contact_id,kind,unit,delta,expires_at"
        f"&order=expires_at.asc&limit=200") or []
    warned = 0
    for g in grants:
        biz, contact = str(g.get("business_id")), str(g.get("contact_id"))
        gid = str(g.get("id"))
        try:
            if _expiry_already_warned(biz, gid):
                continue
            bal = cb.balance(biz, contact, str(g.get("kind")), str(g.get("unit")))
            if bal <= 0:
                continue  # already spent — nothing to lose
            name = _contact_name(biz, contact)
            expires = str(g.get("expires_at") or "")[:10]
            unit = str(g.get("unit"))
            left = (f"${bal:,.2f}" if unit == "money"
                    else f"{bal:g} {unit}{'' if bal == 1 else 's'}")
            _notify(biz,
                    f"{name}: {g.get('kind', '').replace('_', ' ')} expires {expires}",
                    f"{name} still has {left} that will lapse on {expires}. "
                    f"Worth a nudge to book before it's gone.",
                    data={"ledger_id": gid, "contact_id": contact,
                          "source": "balance_sweep"})
            warned += 1
        except Exception as e:
            logger.warning(f"[balance_sweep] expiry warn failed for {gid}: {e}")
    return warned


# ─── the tick ────────────────────────────────────────────────────────

def sweep_tick() -> Dict[str, Any]:
    """Daily. Sync on purpose — AsyncIOScheduler runs plain callables in
    its executor, same as gl_engine.drain_tick."""
    if (os.environ.get("BALANCE_SWEEP") or "on").lower() == "off":
        return {"ok": True, "skipped": "BALANCE_SWEEP=off"}
    now = _now()
    since = (now - timedelta(days=LOOKBACK_DAYS)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    until = now.replace(hour=0, minute=0, second=0, microsecond=0)

    consumed = 0
    checked = 0
    try:
        sessions = _completed_sessions(since, until)
    except Exception as e:
        logger.warning(f"[balance_sweep] session read failed: {e}")
        return {"ok": False, "error": str(e)[:200]}

    for s in sessions:
        checked += 1
        try:
            if consume_for_session(s) is not None:
                consumed += 1
        except Exception as e:
            logger.warning(f"[balance_sweep] session {s.get('id')} failed: {e}")

    try:
        warned = warn_expiring()
    except Exception as e:
        logger.warning(f"[balance_sweep] expiry pass failed: {e}")
        warned = 0

    if consumed or warned:
        logger.info(f"[balance_sweep] {checked} sessions checked, "
                    f"{consumed} consumed, {warned} expiry warnings")
    return {"ok": True, "sessions_checked": checked,
            "consumed": consumed, "expiry_warnings": warned}
