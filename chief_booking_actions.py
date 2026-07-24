"""
chief_booking_actions.py — P0.1, the booking verbs.

THE GAP THIS CLOSES: Chief had seven availability-CONFIG verbs
(set_availability_day, set_lead_time, set_business_timezone, …) and no way
to put a single appointment on the calendar. It could describe the hours and
not use them. Every booking in the system came in through the customer-facing
widget; a practitioner who said "book Maria for Tuesday at 2" got a shrug.

Isolated from the 14k-line chief_of_staff.py to keep blast radius tiny —
same discipline as chief_bookkeeping.py. chief_of_staff imports the three
handlers and registers them in ACTION_HANDLERS; nothing else changes there.

ONE BOOKING PATH (the load-bearing decision): these verbs do NOT re-implement
booking. They call the same booking_widget_router helpers the public widget
uses — _bookings_module, _maybe_denormalize_offering, _check_slot_available,
_create_appointment. That means a Chief-made booking automatically gets:
  • P5 price/name/duration denormalization at book time,
  • the D.4 double-book guard,
  • the ONE CALENDAR session mirror (_mirror_booking_session),
  • the Arc 20B rules_engine `booking_created` event.
If the widget's booking semantics change, these verbs change with it. A second
implementation would have drifted within a month.

Service-role + explicit business_id filter on every query (Ruling 4 α), so
these are safe to call from Chief's server-side context. The sync helpers are
wrapped in asyncio.to_thread — chief_of_staff's handlers are async and must
not block the event loop.

Return shape: every handler returns {type, result, label, …, nav}. `result`
and `label` are NON-NEGOTIABLE — the frontend action card calls .toLowerCase()
on them and a missing key blanks the app.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import sb_clients

logger = logging.getLogger("chief_booking_actions")

# How many alternative slots to offer when the requested time is taken.
_SUGGEST_LIMIT = 3
# How far ahead to look when suggesting alternatives.
_SUGGEST_DAYS = 7


# ─── Shared shapes ────────────────────────────────────────────────────

def _fail(action_type: str, msg: str) -> Dict[str, Any]:
    """Local mirror of chief_of_staff._fail. Duplicated deliberately: importing
    it would make this module depend on the 14k-line file it is trying to stay
    out of. Messages here are written to be practitioner-presentable already."""
    logger.info(f"Action {action_type} failed: {msg}")
    return {"type": action_type, "result": msg, "label": action_type, "nav": None}


def _nav_calendar() -> Dict[str, Any]:
    return {"tab": "operate", "sub": "calendar"}


def _normalize_iso(raw: Optional[str]) -> Optional[str]:
    """Accept the shapes a practitioner actually says, via Chief:
      "2026-08-04"                 → 2026-08-04T09:00:00Z
      "2026-08-04T14:00"           → 2026-08-04T14:00:00Z
      "2026-08-04T14:00:00Z"       → unchanged
      "2026-08-04T14:00:00+00:00"  → unchanged
    Mirrors handle_create_session's parsing so the two verbs behave the same.
    Returns None when there's nothing usable."""
    s = (raw or "").strip()
    if not s:
        return None
    if len(s) == 10:                       # bare date
        return f"{s}T09:00:00Z"
    if "T" in s and not s.endswith("Z") and "+" not in s:
        return s + ":00Z" if len(s) == 16 else s + "Z"
    return s


def _parse_dt(iso: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _pretty(iso: str) -> str:
    dt = _parse_dt(iso)
    return dt.strftime("%b %d, %I:%M %p").replace(" 0", " ") if dt else iso


# ─── Resolvers ────────────────────────────────────────────────────────

def _resolve_offering(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """offering_id wins; otherwise fuzzy-match offering_name against the live
    catalog. Returns {"offering": row} or {"error": msg}. An ambiguous name
    returns the candidate list so Chief can ask rather than guess."""
    offering_id = (action.get("offering_id") or "").strip()
    if offering_id:
        rows = sb_clients.sb_get_as_service(
            f"/offerings?id=eq.{offering_id}&business_id=eq.{business_id}"
            f"&select=id,name,duration_min,is_active&limit=1") or []
        if not rows:
            return {"error": "I couldn't find that offering."}
        return {"offering": rows[0]}

    name = (action.get("offering_name") or action.get("offering")
            or action.get("service") or "").strip()
    if not name:
        # No offering named at all — fall back to the only active one, if
        # there IS only one. A solo practitioner with a single service should
        # not have to name it.
        rows = sb_clients.sb_get_as_service(
            f"/offerings?business_id=eq.{business_id}&is_active=eq.true"
            f"&select=id,name,duration_min,is_active&limit=3") or []
        if len(rows) == 1:
            return {"offering": rows[0]}
        if not rows:
            return {"error": "There are no active offerings to book yet — "
                             "add one in OPERATE → Catalog first."}
        return {"error": "Which offering should I book? "
                         + ", ".join(r.get("name") or "" for r in rows[:3])}

    safe = name.replace("*", "").replace(",", " ")
    rows = sb_clients.sb_get_as_service(
        f"/offerings?business_id=eq.{business_id}&is_active=eq.true"
        f"&name=ilike.*{safe}*&select=id,name,duration_min,is_active&limit=3") or []
    if not rows:
        return {"error": f"I couldn't find an offering matching '{name}'."}
    if len(rows) > 1:
        return {"error": f"Multiple offerings match '{name}': "
                         + ", ".join(r.get("name") or "" for r in rows)
                         + ". Which one?"}
    return {"offering": rows[0]}


def _resolve_contact(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """contact_id wins; else fuzzy name. Returns {"contact": row|None} or
    {"error": msg}. A booking without a contact is allowed (walk-in with just
    a name), so a miss on name alone is not fatal — the caller decides."""
    contact_id = (action.get("contact_id") or "").strip()
    if contact_id:
        rows = sb_clients.sb_get_as_service(
            f"/contacts?id=eq.{contact_id}&business_id=eq.{business_id}"
            f"&select=id,name,email,phone&limit=1") or []
        if not rows:
            return {"error": "I couldn't find that contact."}
        return {"contact": rows[0]}

    name = (action.get("contact_name") or action.get("customer_name")
            or action.get("name") or "").strip()
    if not name:
        return {"contact": None}

    safe = name.replace("*", "").replace(",", " ")
    rows = sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{business_id}&name=ilike.*{safe}*"
        f"&select=id,name,email,phone&limit=3") or []
    if len(rows) == 1:
        return {"contact": rows[0]}
    if len(rows) > 1:
        return {"error": f"Multiple contacts match '{name}': "
                         + ", ".join(r.get("name") or "" for r in rows)
                         + ". Which one?"}
    return {"contact": None}


def _find_booking(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """Locate an existing active booking by id, or by contact name + the next
    upcoming appointment for that person. Returns {"booking": row} or
    {"error": msg}."""
    booking_id = (action.get("booking_id") or action.get("appointment_id") or "").strip()
    if booking_id:
        rows = sb_clients.sb_get_as_service(
            f"/module_entries?id=eq.{booking_id}&business_id=eq.{business_id}"
            f"&select=id,data,status,appointment_at,module_id&limit=1") or []
        if not rows:
            return {"error": "I couldn't find that booking."}
        return {"booking": rows[0]}

    name = (action.get("contact_name") or action.get("customer_name")
            or action.get("name") or "").strip()
    if not name:
        return {"error": "Which booking? Give me the client's name or the booking id."}

    mod = _bookings_module_id(business_id)
    if not mod:
        return {"error": "This business has no booking calendar set up yet."}

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rows = sb_clients.sb_get_as_service(
        f"/module_entries?module_id=eq.{mod}&business_id=eq.{business_id}"
        f"&status=eq.active&appointment_at=gte.{now}"
        f"&select=id,data,status,appointment_at,module_id"
        f"&order=appointment_at.asc&limit=50") or []

    needle = name.lower()
    matches = [
        r for r in rows
        if needle in str(((r.get("data") or {}).get("customer_name") or "")).lower()
        or needle in str(((r.get("data") or {}).get("name") or "")).lower()
    ]
    if not matches:
        return {"error": f"I don't see an upcoming booking for {name}."}
    return {"booking": matches[0]}


def _bookings_module_id(business_id: str) -> Optional[str]:
    from booking_widget_router import _bookings_module
    mod = _bookings_module(business_id)
    return mod.get("id") if mod else None


def _suggest_slots(business_id: str, offering: Dict[str, Any],
                   around_iso: str) -> List[str]:
    """When the requested time is taken, offer the next few free ones so the
    practitioner can pick without a second round-trip. Best-effort — an empty
    list just means the failure message stays generic."""
    try:
        from availability_engine import BusinessAvailability, compute_slots
        from availability_router import _bookings_in_window, _practitioner_timezone

        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{business_id}&select=id,owner_id,settings&limit=1") or []
        if not rows:
            return []
        biz = rows[0]
        settings = biz.get("settings") or {}
        av = BusinessAvailability.from_settings_dict(settings.get("availability"))

        start = _parse_dt(around_iso)
        if not start:
            return []
        from_date = start.date()
        to_date = from_date + timedelta(days=_SUGGEST_DAYS)

        slots = compute_slots(
            availability=av,
            practitioner_tz=_practitioner_timezone(biz.get("owner_id")),
            existing_bookings=_bookings_in_window(business_id, from_date, to_date),
            offering_duration_min=int(offering.get("duration_min") or 60),
            from_date=from_date,
            to_date=to_date,
        ) or []
        return [_pretty(s.get("start_utc") or "") for s in slots[:_SUGGEST_LIMIT]]
    except Exception as e:
        logger.info(f"[booking] slot suggestion skipped: {e}")
        return []


# ─── create_booking ───────────────────────────────────────────────────

def _create_booking_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    from booking_widget_router import (
        _bookings_module, _check_slot_available, _create_appointment,
        _maybe_denormalize_offering,
    )

    business_id = biz["id"]

    module = _bookings_module(business_id)
    if not module:
        return _fail("create_booking",
                     "This business doesn't have a booking calendar yet — "
                     "add the Bookings module first and I can book into it.")

    when = _normalize_iso(action.get("appointment_at") or action.get("scheduled_for")
                          or action.get("when") or action.get("date"))
    if not when:
        return _fail("create_booking", "What date and time should I book?")
    if not _parse_dt(when):
        return _fail("create_booking", "I couldn't read that date and time.")

    off_res = _resolve_offering(business_id, action)
    if off_res.get("error"):
        return _fail("create_booking", off_res["error"])
    offering = off_res["offering"]
    if not offering.get("is_active"):
        return _fail("create_booking",
                     f"{offering.get('name')} isn't active right now.")

    con_res = _resolve_contact(business_id, action)
    if con_res.get("error"):
        return _fail("create_booking", con_res["error"])
    contact = con_res.get("contact")

    customer_name = (action.get("customer_name") or action.get("contact_name")
                     or (contact or {}).get("name") or "").strip()
    if not customer_name:
        return _fail("create_booking", "Who is this booking for?")
    customer_email = (action.get("customer_email") or action.get("email")
                      or (contact or {}).get("email") or "").strip().lower()

    # Build the entry payload in the same shape the widget writes, so the
    # generated appointment_at column and every downstream reader agree.
    pdf = (module.get("archetype_params") or {}).get("primary_date_field") or "appointment_at"
    entry_data: Dict[str, Any] = {
        pdf: when,
        "appointment_at": when,
        "customer_name": customer_name,
        "booked_by": "chief",
    }
    if customer_email:
        entry_data["customer_email"] = customer_email
    if contact:
        entry_data["contact_id"] = contact["id"]
    if action.get("notes"):
        entry_data["notes"] = str(action["notes"])[:2000]

    # P5 denormalization — price/name/duration captured at book time. No
    # quoted_price from Chief (the practitioner is booking at the live price),
    # so the P5a tolerance gate is a no-op here by construction.
    try:
        entry_data = _maybe_denormalize_offering(
            business_id, module, offering["id"], None, entry_data)
    except Exception as e:
        logger.warning(f"[booking] denormalize failed: {e}")
        return _fail("create_booking",
                     "I couldn't price that offering just now — try again in a moment.")

    duration = int(entry_data.get("duration_min_at_booking")
                   or offering.get("duration_min") or 60)

    # D.4 double-book guard — the same check the public widget runs.
    if not _check_slot_available(business_id, when, duration):
        alts = _suggest_slots(business_id, offering, when)
        if alts:
            return _fail("create_booking",
                         f"{_pretty(when)} is already booked. "
                         f"Free instead: {', '.join(alts)}.")
        return _fail("create_booking",
                     f"{_pretty(when)} is already booked — pick another time.")

    entry = _create_appointment(business_id, module["id"], entry_data,
                                created_by="chief_of_staff")
    if not entry:
        return _fail("create_booking",
                     "I couldn't save that booking just now — try again in a moment.")

    return {
        "type": "create_booking",
        "result": f"booked for {_pretty(when)}",
        "label": f"{offering.get('name')} — {customer_name}",
        "booking_id": entry.get("id"),
        "contact_id": (contact or {}).get("id"),
        "offering_id": offering["id"],
        "appointment_at": when,
        "nav": _nav_calendar(),
    }


async def handle_create_booking(client, biz, action) -> Dict[str, Any]:
    result = await asyncio.to_thread(_create_booking_sync, biz, action)

    # Confirmation email, best-effort and AFTER the booking is durable —
    # booking is the load-bearing entity, notification is not. Same posture
    # as the widget's book-anon path.
    if result.get("booking_id") and action.get("send_confirmation", True):
        try:
            from booking_confirmation_emails import send_confirmation_email
            rows = await asyncio.to_thread(
                sb_clients.sb_get_as_service,
                f"/module_entries?id=eq.{result['booking_id']}&select=*&limit=1")
            entry = (rows or [None])[0]
            email = (action.get("customer_email") or action.get("email") or "").strip().lower()
            if not email and entry:
                email = ((entry.get("data") or {}).get("customer_email") or "").lower()
            if entry and email:
                asyncio.create_task(send_confirmation_email(
                    booking=entry,
                    business=biz,
                    customer_email=email,
                    customer_name=(entry.get("data") or {}).get("customer_name") or "",
                    offering_id=result.get("offering_id"),
                ))
        except Exception as e:
            logger.warning(f"[booking] confirmation email skipped: {e}")
    return result


# ─── reschedule_booking ───────────────────────────────────────────────

def _reschedule_booking_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    from booking_widget_router import _check_slot_available, _mirror_booking_session

    business_id = biz["id"]

    new_when = _normalize_iso(action.get("new_appointment_at") or action.get("new_time")
                              or action.get("appointment_at") or action.get("to"))
    if not new_when or not _parse_dt(new_when):
        return _fail("reschedule_booking", "What's the new date and time?")

    found = _find_booking(business_id, action)
    if found.get("error"):
        return _fail("reschedule_booking", found["error"])
    booking = found["booking"]
    if booking.get("status") != "active":
        return _fail("reschedule_booking", "That booking isn't active anymore.")

    data = dict(booking.get("data") or {})
    old_when = data.get("appointment_at") or booking.get("appointment_at") or ""
    duration = int(data.get("duration_min_at_booking") or data.get("duration_min") or 60)

    if not _check_slot_available(business_id, new_when, duration):
        return _fail("reschedule_booking",
                     f"{_pretty(new_when)} is already booked — pick another time.")

    # appointment_at is DB-maintained from `data`, so the write goes to the
    # jsonb. Patch every date key the entry actually carries, or the module's
    # primary_date_field and the canonical key can drift apart.
    for key in ("appointment_at", "starts_at", "scheduled_for"):
        if key in data:
            data[key] = new_when
    data["appointment_at"] = new_when
    data["rescheduled_by"] = "chief"
    data["rescheduled_at"] = datetime.now(timezone.utc).isoformat()

    # Falsy, not `is None`: sb_patch_as_service returns None on a transport/HTTP
    # error AND [] when the filter matched no rows (a stale id, or a booking
    # belonging to another business). Both mean "nothing moved" — treating []
    # as success would report a reschedule that never happened.
    updated = sb_clients.sb_patch_as_service(
        f"/module_entries?id=eq.{booking['id']}&business_id=eq.{business_id}",
        {"data": data})
    if not updated:
        return _fail("reschedule_booking",
                     "I couldn't move that booking just now — try again in a moment.")

    # Move the mirrored session too. Cancel the stale one, then re-mirror:
    # _mirror_booking_session is idempotent on the [booking:{id}] marker, so
    # cancelling first is what lets it write the new time.
    try:
        marker = f"[booking:{booking['id']}]"
        sb_clients.sb_patch_as_service(
            f"/sessions?business_id=eq.{business_id}"
            f"&notes=like.*{marker}*&status=eq.scheduled",
            {"status": "cancelled"})
        fresh = sb_clients.sb_get_as_service(
            f"/module_entries?id=eq.{booking['id']}&select=*&limit=1") or []
        if fresh:
            _mirror_booking_session(business_id, fresh[0])
    except Exception as e:
        logger.warning(f"[booking] session re-mirror failed soft: {e}")

    who = data.get("customer_name") or data.get("name") or "Booking"
    return {
        "type": "reschedule_booking",
        "result": f"moved to {_pretty(new_when)}"
                  + (f" (was {_pretty(old_when)})" if old_when else ""),
        "label": str(who),
        "booking_id": booking["id"],
        "appointment_at": new_when,
        "nav": _nav_calendar(),
    }


async def handle_reschedule_booking(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_reschedule_booking_sync, biz, action)


# ─── cancel_booking ───────────────────────────────────────────────────

def _cancel_booking_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    business_id = biz["id"]

    found = _find_booking(business_id, action)
    if found.get("error"):
        return _fail("cancel_booking", found["error"])
    booking = found["booking"]
    if booking.get("status") != "active":
        return _fail("cancel_booking", "That booking is already cancelled.")

    data = dict(booking.get("data") or {})
    when = data.get("appointment_at") or booking.get("appointment_at") or ""
    data["cancelled_by"] = "chief"
    data["cancelled_at"] = datetime.now(timezone.utc).isoformat()
    if action.get("reason"):
        data["cancellation_reason"] = str(action["reason"])[:500]

    # Falsy, not `is None` — see the note in _reschedule_booking_sync. A
    # cancel that matched nothing must not report "cancelled".
    updated = sb_clients.sb_patch_as_service(
        f"/module_entries?id=eq.{booking['id']}&business_id=eq.{business_id}",
        {"status": "cancelled", "data": data})
    if not updated:
        return _fail("cancel_booking",
                     "I couldn't cancel that just now — try again in a moment.")

    # Free the calendar immediately. booking_session_sync_tick backstops this
    # every 10 minutes, but the practitioner is looking at the calendar NOW.
    try:
        marker = f"[booking:{booking['id']}]"
        sb_clients.sb_patch_as_service(
            f"/sessions?business_id=eq.{business_id}"
            f"&notes=like.*{marker}*&status=eq.scheduled",
            {"status": "cancelled"})
    except Exception as e:
        logger.warning(f"[booking] session cancel failed soft: {e}")

    who = data.get("customer_name") or data.get("name") or "Booking"
    return {
        "type": "cancel_booking",
        "result": f"cancelled{f' — {_pretty(when)}' if when else ''}. That slot is free again.",
        "label": str(who),
        "booking_id": booking["id"],
        "nav": _nav_calendar(),
    }


async def handle_cancel_booking(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_cancel_booking_sync, biz, action)
