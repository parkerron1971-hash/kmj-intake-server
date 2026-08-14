"""
lead_response.py — how long a lead waited before anyone answered.

WHY THIS EXISTS
═══════════════════════════════════════════════════════════════════════
Nothing in either repo measured it. Not a field, not a metric, not a
query. The closest thing was growth_engine's stale-lead check, which
flags a lead at THIRTY DAYS OLD PLUS FOURTEEN DAYS SILENT — a monthly
retrospective, not a clock. A lead that arrived this morning and is
still untouched on Thursday triggered nothing, appeared nowhere, and
cost nothing to ignore.

First-response time is the number that decides whether an enquiry
becomes a customer. A system that promises to help a solo operator
capture leads, and never tells them one has been sitting for two days,
is not doing the job it says it does.

WHY IT IS DERIVED RATHER THAN STAMPED
═══════════════════════════════════════════════════════════════════════
The obvious implementation writes `first_response_at` at every outbound
send. There are at least six such paths — email_sender, sms_service,
approvals_router, two in chief_of_staff, and the FRONTEND, which
PATCHes agent_queue to 'sent' straight from ContactDetail.tsx. Six call
sites is six chances to miss one, and a missed one surfaces as a lead
that looks permanently unanswered: a false alarm, which is the fastest
way to teach somebody to ignore a real one.

Every one of those paths already leaves a durable record. This module
reads those records and materialises the answer. One place to be right,
it covers history as well as new activity, and a send path added next
month is picked up without anyone remembering to instrument it.

WHAT COUNTS AS A RESPONSE
═══════════════════════════════════════════════════════════════════════
The practitioner did something this person would notice:

  · an outbound SMS to them
  · an agent_queue row marked sent (email or in-app follow-up)
  · an `agent_message_sent` or `sms_sent` event on the spine
  · a session on the calendar with them
  · their status moving off 'lead' — somebody triaged them by hand

Deliberately NOT counted: reading the contact, scoring it, drafting a
reply that was never sent, or an inbound message FROM them. A draft
sitting in the approval queue is the opposite of a response.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("lead_response")

# PostgREST `in.(...)` goes in the URL, so the batch size is really a
# URL-length budget: 100 uuids is ~3.7kB of query string.
CHUNK = 100

# Per tick. Unanswered leads are re-scanned every pass by design (see
# "null means not yet" below), so this bounds the work rather than the
# backlog.
RECONCILE_LIMIT = int(os.environ.get("LEAD_RESPONSE_RECONCILE_LIMIT", "500"))

# How far back a tick looks. History older than this is left alone — a
# response time from last spring changes no decision anyone is making.
RECONCILE_WINDOW_DAYS = int(os.environ.get("LEAD_RESPONSE_WINDOW_DAYS", "90"))

RESPONSE_EVENT_TYPES = ("agent_message_sent", "sms_sent",
                        "contact_status_changed")


def _z(dt: datetime) -> str:
    """Z form. '+00:00' decodes to a space in a query string and turns a
    filter into one that silently matches nothing."""
    return dt.isoformat().replace("+00:00", "Z")


def _parse(ts: Any) -> Optional[datetime]:
    if not ts or not isinstance(ts, str):
        return None
    try:
        out = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def _chunks(items: List[str], size: int = CHUNK) -> Iterable[List[str]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _in(ids: List[str]) -> str:
    return "in.(" + ",".join(ids) + ")"


# ─── derivation ───────────────────────────────────────────────────────

def first_response_times(contacts: List[Dict[str, Any]]) -> Dict[str, datetime]:
    """{contact_id: first response} for whichever of these contacts have
    one. Contacts with no response are ABSENT from the result, not
    mapped to None — "not yet" is a different fact from "unknown", and
    the caller must not write either.

    A response only counts if it happened AFTER the contact arrived.
    Without that guard, a long-standing client who fills in the website
    form would inherit last year's outbound SMS as their response time
    and read as answered instantly.
    """
    import sb_clients

    created: Dict[str, datetime] = {}
    for c in contacts:
        at = _parse(c.get("created_at"))
        if at and c.get("id"):
            created[str(c["id"])] = at
    if not created:
        return {}

    best: Dict[str, datetime] = {}

    def consider(contact_id: Any, ts: Any) -> None:
        cid = str(contact_id or "")
        when = _parse(ts)
        born = created.get(cid)
        if not cid or not when or not born or when <= born:
            return
        if cid not in best or when < best[cid]:
            best[cid] = when

    ids = list(created.keys())
    for batch in _chunks(ids):
        sel = _in(batch)

        for row in (sb_clients.sb_get_as_service(
                f"/sms_messages?contact_id={sel}&direction=eq.outbound"
                f"&select=contact_id,created_at&limit=2000") or []):
            consider(row.get("contact_id"), row.get("created_at"))

        for row in (sb_clients.sb_get_as_service(
                f"/agent_queue?contact_id={sel}&status=eq.sent"
                f"&select=contact_id,sent_at,created_at&limit=2000") or []):
            # sent_at is the truth; created_at is when the DRAFT was
            # written, which is not a response to anybody.
            consider(row.get("contact_id"), row.get("sent_at"))

        for row in (sb_clients.sb_get_as_service(
                f"/events?contact_id={sel}"
                f"&event_type=in.({','.join(RESPONSE_EVENT_TYPES)})"
                f"&select=contact_id,event_type,created_at,data&limit=2000") or []):
            if row.get("event_type") == "contact_status_changed":
                # Only a move OFF 'lead' is a human deciding something.
                # lead -> lead, or anything -> lead, is not.
                data = row.get("data") or {}
                moved_to = str(data.get("to") or data.get("to_status") or "")
                moved_from = str(data.get("from") or data.get("from_status") or "")
                if moved_to == "lead" or moved_from != "lead":
                    continue
            consider(row.get("contact_id"), row.get("created_at"))

        for row in (sb_clients.sb_get_as_service(
                f"/sessions?contact_id={sel}"
                f"&select=contact_id,created_at&limit=2000") or []):
            consider(row.get("contact_id"), row.get("created_at"))

    return best


# ─── the tick ─────────────────────────────────────────────────────────

def awaiting_first_response(limit: int = RECONCILE_LIMIT) -> List[Dict[str, Any]]:
    """Contacts with no recorded first response, newest first.

    Not filtered to status='lead': somebody who was answered and
    converted still needs their response time recorded, or the median
    is computed only over the ones nobody got back to.
    """
    import sb_clients
    since = _z(datetime.now(timezone.utc) - timedelta(days=RECONCILE_WINDOW_DAYS))
    return sb_clients.sb_get_as_service(
        f"/contacts?first_response_at=is.null&created_at=gte.{since}"
        f"&order=created_at.desc&select=id,business_id,created_at"
        f"&limit={int(limit)}") or []


def reconcile_tick() -> Dict[str, Any]:
    """Materialise first_response_at for anything still missing it.

    NULL MEANS "NOT YET", NOT "UNKNOWN". A contact with no response
    found is left null and re-examined next tick, because a response
    can still arrive. Unanswered leads are therefore re-scanned every
    pass — which is the correct set to keep looking at, and if it is
    ever large enough for the cost to matter, the business has a much
    more expensive problem than this query.
    """
    import sb_clients
    try:
        pending = awaiting_first_response()
    except Exception as e:
        logger.warning("[lead_response] could not read pending contacts: %s", e)
        return {"scanned": 0, "stamped": 0, "error": str(e)}

    if not pending:
        return {"scanned": 0, "stamped": 0}

    try:
        found = first_response_times(pending)
    except Exception as e:
        logger.warning("[lead_response] derivation failed: %s", e)
        return {"scanned": len(pending), "stamped": 0, "error": str(e)}

    by_id = {str(c["id"]): c for c in pending if c.get("id")}
    stamped = 0
    for cid, when in found.items():
        row = by_id.get(cid)
        if not row:
            continue
        try:
            sb_clients.sb_patch_as_service(
                f"/contacts?id=eq.{cid}&business_id=eq.{row['business_id']}",
                {"first_response_at": _z(when)})
            stamped += 1
        except Exception as e:
            logger.warning("[lead_response] write failed for %s: %s", cid, e)

    logger.info("[lead_response] scanned %d, stamped %d, still waiting %d",
                len(pending), stamped, len(pending) - stamped)
    return {"scanned": len(pending), "stamped": stamped,
            "still_waiting": len(pending) - stamped}


# ─── reading it back ──────────────────────────────────────────────────

def response_stats(business_id: str, days: int = 30) -> Dict[str, Any]:
    """Median and worst first-response time for one business, plus what
    is still outstanding right now.

    MEDIAN, NOT MEAN. One lead answered three weeks late drags a mean
    into uselessness and hides the fact that the other forty were
    answered within the hour. The practitioner needs the typical
    experience, and then the outlier named separately.
    """
    import sb_clients
    now = datetime.now(timezone.utc)
    since = _z(now - timedelta(days=days))

    answered = sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{business_id}&created_at=gte.{since}"
        f"&first_response_at=not.is.null"
        f"&select=id,name,created_at,first_response_at&limit=1000") or []
    waiting = sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{business_id}&status=eq.lead"
        f"&first_response_at=is.null&created_at=gte.{since}"
        f"&order=created_at.asc&select=id,name,created_at,lead_score"
        f"&limit=200") or []

    minutes: List[float] = []
    for c in answered:
        born, replied = _parse(c.get("created_at")), _parse(c.get("first_response_at"))
        if born and replied and replied > born:
            minutes.append((replied - born).total_seconds() / 60.0)
    minutes.sort()

    median = None
    if minutes:
        mid = len(minutes) // 2
        median = (minutes[mid] if len(minutes) % 2
                  else (minutes[mid - 1] + minutes[mid]) / 2.0)

    oldest_wait_hours = None
    if waiting:
        born = _parse(waiting[0].get("created_at"))
        if born:
            oldest_wait_hours = (now - born).total_seconds() / 3600.0

    return {
        "answered": len(answered),
        "median_minutes": round(median, 1) if median is not None else None,
        "slowest_minutes": round(minutes[-1], 1) if minutes else None,
        "waiting": len(waiting),
        "oldest_wait_hours": round(oldest_wait_hours, 1)
        if oldest_wait_hours is not None else None,
        "waiting_contacts": waiting[:10],
        "window_days": days,
    }
