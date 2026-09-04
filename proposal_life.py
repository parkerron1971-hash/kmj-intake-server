"""
proposal_life.py — a proposal that expires, reminds, and reaches the phone.

THE GAP (the "Chief to Eight" plan, phase two, 2026-09-04)
  action_proposals puts a class-C verb in the Approval Queue and stops.
  The row never expired — a text Chief drafted for a lead on Monday was
  still "waiting" the next month, and approving it then would have
  sent a stale message. Nothing reminded anyone. And the queue was a
  screen the practitioner had to remember to open: the proposal never
  reached the phone, though the tap-to-execute door on notifications
  has existed since July.

WHAT THIS ADDS
  1. An EXPIRY on every filed proposal (agent_queue.expires_at,
     EXPIRE_HOURS from filing). The hourly tick flips overdue drafts to
     `expired` and says so where the practitioner looks — an activity
     row and a notification, never a push. An expired proposal can no
     longer be approved: the approvals door executes drafts only.
  2. A PUSH THE MOMENT IT IS FILED, with buttons: "Yes, do that" and
     "Not now". The tap carries the queue id into the app, which
     approves through the same audited /approvals door the queue's own
     button uses. Nothing runs from the notification itself.
  3. A REMINDER, once per proposal, after REMIND_AFTER_HOURS, in waking
     hours, at most one per business per REMIND_DEDUP_HOURS — "2 things
     need your hand" — as a notification and a push.

FAIL-SOFT WITHOUT THE MIGRATION
  agent_queue gains two columns and a wider status CHECK. The code
  probes for the columns once (cached), files without them when they
  are missing, and skips expiry and reminders; if the CHECK still
  refuses `expired`, an overdue draft is dismissed with the reason in
  ai_reasoning instead. Migration: APPLY-2026-09-04-proposals-with-life.sql.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import sb_clients

logger = logging.getLogger("proposal_life")

MIGRATION = "APPLY-2026-09-04-proposals-with-life.sql"

EXPIRE_HOURS = int(os.environ.get("PROPOSAL_EXPIRE_HOURS", "48") or 48)
REMIND_AFTER_HOURS = int(os.environ.get("PROPOSAL_REMIND_HOURS", "6") or 6)
REMIND_DEDUP_HOURS = 12
MAX_PER_SWEEP = 100
PROBE_TTL_S = 600

PUSH_TITLE = "Chief needs your OK"
ACTIONS = [{"action": "approve", "title": "Yes, do that"},
           {"action": "later", "title": "Not now"}]


def enabled() -> bool:
    return (os.environ.get("PROPOSAL_LIFE") or "on").strip().lower() != "off"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ─── The columns ──────────────────────────────────────────────────────

_probe: Dict[str, Any] = {"ok": None, "at": 0.0}


def columns_supported() -> bool:
    """Does agent_queue carry expires_at / reminded_at yet? Probed at
    most every PROBE_TTL_S; never probed at all without a Supabase URL
    (tests, scripts). A migration applied after boot is picked up
    within ten minutes."""
    if not os.environ.get("SUPABASE_URL"):
        return False
    if _probe["ok"] is not None and time.monotonic() - _probe["at"] < PROBE_TTL_S:
        return bool(_probe["ok"])
    try:
        rows = sb_clients.sb_get_as_service("/agent_queue?select=expires_at,reminded_at&limit=1")
        ok = isinstance(rows, list)
    except Exception:
        ok = False
    if not ok:
        logger.info(f"[proposal_life] agent_queue has no expires_at yet (apply {MIGRATION})")
    _probe.update(ok=ok, at=time.monotonic())
    return ok


def filing_extras(now: Optional[datetime] = None, hours: Optional[int] = None) -> Dict[str, Any]:
    """The columns a fresh proposal carries — when the table has them."""
    if not columns_supported():
        return {}
    now = now or _now()
    return {"expires_at": _z(now + timedelta(hours=hours or EXPIRE_HOURS))}


# ─── The push, the moment it is filed ─────────────────────────────────

def _owner_of(business_id: str) -> Optional[str]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=owner_id&limit=1") or []
    return str(rows[0].get("owner_id")) if rows and rows[0].get("owner_id") else None


def announce_filed(business_id: str, queue_id: str, sentence: str) -> int:
    """Push to the owner with the two buttons. Sync, best-effort, never
    raises; returns devices reached. Nothing executes from here — the
    tap opens the app, which approves through /approvals."""
    try:
        import push_notifications
        if not push_notifications.push_enabled():
            return 0
        owner = _owner_of(business_id)
        if not owner:
            return 0
        return push_notifications.send_to_user(
            owner, title=PUSH_TITLE, body=(sentence or "")[:160], nav="operate:queue",
            tag=f"proposal-{queue_id}", actions=ACTIONS,
            data={"approve_id": queue_id, "business_id": business_id})
    except Exception as e:
        logger.warning(f"[proposal_life] push for {queue_id} failed: {e}")
        return 0


# ─── The tick ─────────────────────────────────────────────────────────

async def proposals_tick(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Hourly, leader-gated. Expiry runs at any hour — a stale text
    should not survive the night; reminders only in waking hours."""
    if not enabled():
        return {"skipped": "off"}
    if not columns_supported():
        return {"skipped": "migration"}
    now = now or _now()
    expired = await asyncio.to_thread(expire_due, now)
    reminded: List[str] = []
    try:
        import notification_engine
        awake = notification_engine._within_waking_hours(now)
    except Exception:
        awake = True
    if awake:
        reminded = await asyncio.to_thread(remind_due, now)
    return {"expired": expired, "reminded": reminded}


def _businesses(ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not ids:
        return {}
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=in.({','.join(sorted(set(ids)))})&select=id,owner_id,name") or []
    return {str(r.get("id")): r for r in rows if isinstance(r, dict)}


def expire_due(now: Optional[datetime] = None) -> List[str]:
    """Flip overdue drafts to `expired`, and say so. Returns the ids."""
    now = now or _now()
    rows = sb_clients.sb_get_as_service(
        f"/agent_queue?channel=eq.action&status=eq.draft&expires_at=lte.{_z(now)}"
        f"&select=id,business_id,subject,contact_id,expires_at&order=expires_at.asc"
        f"&limit={MAX_PER_SWEEP}") or []
    if not isinstance(rows, list) or not rows:
        return []
    owners = _businesses([str(r.get("business_id")) for r in rows])
    done: List[str] = []
    for r in rows:
        qid = str(r.get("id") or "")
        bid = str(r.get("business_id") or "")
        if not qid or not bid:
            continue
        # Only a row still in draft is flipped — an approval that landed
        # between the read and this write keeps its `approved`.
        patched = sb_clients.sb_patch_as_service(
            f"/agent_queue?id=eq.{qid}&status=eq.draft",
            {"status": "expired", "reviewed_at": _z(now)})
        if patched is None:
            # The status CHECK has not been widened yet: dismissed, with
            # the reason on the row, is the honest fallback.
            patched = sb_clients.sb_patch_as_service(
                f"/agent_queue?id=eq.{qid}&status=eq.draft",
                {"status": "dismissed", "reviewed_at": _z(now),
                 "ai_reasoning": f"Expired unapproved after {EXPIRE_HOURS} hours (nothing was sent)."})
        if not patched:
            continue
        done.append(qid)
        subject = (r.get("subject") or "a proposal")[:120]
        body = (f"Nobody approved it within {EXPIRE_HOURS} hours, so nothing was sent. "
                f"Ask me again if you still want it.")
        owner = (owners.get(bid) or {}).get("owner_id")
        try:
            sb_clients.sb_post_as_service("/chief_activity", {
                "user_id": owner, "business_id": bid, "source": "system",
                "action_type": "proposal_expired", "label": f"Let go unapproved: {subject}"[:120],
                "summary": body[:240], "nav": None,
            }, prefer="return=minimal")
        except Exception as e:
            logger.warning(f"[proposal_life] activity row failed: {e}")
        try:
            sb_clients.sb_post_as_service("/chief_notifications", {
                "business_id": bid, "type": "reminder", "priority": "normal",
                "title": f"I let this go: {subject}"[:120], "body": body[:300],
                "related_contact_id": r.get("contact_id"),
                "action_payload": {"dedup_key": f"proposal_expired:{qid}"},
            }, prefer="return=minimal")
        except Exception as e:
            logger.warning(f"[proposal_life] notification failed: {e}")
    return done


def _recently_reminded(business_id: str, now: datetime) -> bool:
    cutoff = _z(now - timedelta(hours=REMIND_DEDUP_HOURS))
    rows = sb_clients.sb_get_as_service(
        f"/chief_notifications?business_id=eq.{business_id}"
        f"&action_payload->>dedup_key=eq.needs_hand:{business_id}"
        f"&created_at=gte.{cutoff}&select=id&limit=1")
    return bool(rows)


def remind_due(now: Optional[datetime] = None) -> List[str]:
    """One reminder per business for the drafts nobody has looked at
    in REMIND_AFTER_HOURS. Each draft is reminded about once. Returns
    the business ids reminded."""
    now = now or _now()
    since = _z(now - timedelta(hours=REMIND_AFTER_HOURS))
    rows = sb_clients.sb_get_as_service(
        f"/agent_queue?channel=eq.action&status=eq.draft&reminded_at=is.null"
        f"&created_at=lte.{since}&or=(expires_at.is.null,expires_at.gt.{_z(now)})"
        f"&select=id,business_id,subject&order=created_at.asc&limit={MAX_PER_SWEEP * 2}") or []
    if not isinstance(rows, list) or not rows:
        return []
    by_biz: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        bid = str(r.get("business_id") or "")
        if bid:
            by_biz.setdefault(bid, []).append(r)
    owners = _businesses(list(by_biz))
    reminded: List[str] = []
    for bid, items in by_biz.items():
        ids = [str(i.get("id")) for i in items if i.get("id")]
        # Covered by a reminder in the last twelve hours: mark these as
        # reminded too, so the next hour does not re-raise them.
        fresh = not _recently_reminded(bid, now)
        if fresh:
            n = len(items)
            first = (items[0].get("subject") or "a proposal")[:100]
            title = "One thing needs your hand" if n == 1 else f"{n} things need your hand"
            body = first if n == 1 else f"{first}, and {n - 1} more."
            try:
                sb_clients.sb_post_as_service("/chief_notifications", {
                    "business_id": bid, "type": "reminder", "priority": "normal",
                    "title": title[:120], "body": (body + " Each is one tap in your Approval Queue.")[:300],
                    "action_payload": {"type": "navigate", "tab": "operate", "sub": "queue",
                                       "dedup_key": f"needs_hand:{bid}"},
                    "suggested_action": "Open the queue",
                }, prefer="return=minimal")
            except Exception as e:
                logger.warning(f"[proposal_life] reminder row failed: {e}")
            owner = (owners.get(bid) or {}).get("owner_id")
            if owner:
                try:
                    import push_notifications
                    push_notifications.send_to_user(
                        str(owner), title=title, body=body[:160], nav="operate:queue",
                        tag="needs-hand",
                        actions=ACTIONS if n == 1 else None,
                        data={"approve_id": ids[0], "business_id": bid} if n == 1 else None)
                except Exception as e:
                    logger.warning(f"[proposal_life] reminder push failed: {e}")
            reminded.append(bid)
        try:
            sb_clients.sb_patch_as_service(
                f"/agent_queue?id=in.({','.join(ids)})&reminded_at=is.null",
                {"reminded_at": _z(now)})
        except Exception as e:
            logger.warning(f"[proposal_life] reminded_at failed: {e}")
    return reminded


# ─── For the notification engine ─────────────────────────────────────

def waiting_for_contact(business_id: str, contact_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """The draft proposal waiting for this contact, if any — so a lead
    alert can say "the reply is drafted, one tap" instead of "nobody
    has replied". Sync, never raises."""
    if not contact_id:
        return None
    try:
        rows = sb_clients.sb_get_as_service(
            f"/agent_queue?business_id=eq.{business_id}&contact_id=eq.{contact_id}"
            f"&channel=eq.action&status=eq.draft&select=id,subject&limit=1") or []
        return rows[0] if rows else None
    except Exception:
        return None
