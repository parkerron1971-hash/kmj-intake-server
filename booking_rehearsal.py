"""CPU-only booking-plan rehearsal, exposed through Chief's existing read tools.

Uses the canonical availability engine. No model calls, writes, reservations,
or permission grants. A result describes a bounded read snapshot; execution
must still use the booking handlers and their current-state checks.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, time, timedelta, timezone
from urllib.parse import quote
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from availability_engine import compute_slots
from chief_host import _sb
from chief_availability import _busy_get, _pages, _settings, Unavailable

logger = logging.getLogger(__name__)
VERB = "rehearse_booking_plan"
VERSION = 1
MAX_BOOKINGS = 500
PAGE_SIZE = 100
CHECK_BUDGET_S = 6.0


class ProposedBooking(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offering_id: UUID
    start: AwareDatetime = Field(description="ISO timestamp with UTC offset; never a guessed timezone.")

    @field_validator("start", mode="before")
    @classmethod
    def timestamp_only(cls, value):
        if not isinstance(value, (str, datetime)):
            raise ValueError("start must be an ISO timestamp with timezone")
        if isinstance(value, str):
            # Pydantic also accepts numeric strings as Unix timestamps. Require
            # actual ISO input so an omitted timezone is never inferred as UTC.
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("start must include a timezone offset")
        return value


class BookingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    appointments: list[ProposedBooking] = Field(min_length=1, max_length=8)


READ_SCHEMA = (
    "Rehearse 1-8 NEW appointments together without creating or reserving anything. "
    "Uses current offering durations, business hours, lead time, shared capacity and outside-calendar blocks. "
    "Returns fit/conflict per appointment, same-day alternatives and dependency fingerprints "
    "in one CPU-only lookup. Order is priority order. Requires offering UUIDs and explicit "
    "timezone offsets. Does not check individual staff, rooms, customer eligibility, "
    "payments or rescheduling. Execution still needs the normal booking checks.",
    BookingPlan.model_json_schema(),
)


class RehearsalUnavailable(ValueError):
    """Missing or unsupported evidence; never interpreted as an empty calendar."""


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _duration(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1440:
        raise RehearsalUnavailable("A service or booking has no supported duration (1-1440 minutes).")
    return value


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise RehearsalUnavailable("A stored booking has an invalid appointment time.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Match the database's established convention for legacy bare UTC timestamps.
        return (parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed).astimezone(timezone.utc)
    except ValueError as exc:
        raise RehearsalUnavailable("A stored booking has an invalid appointment time.") from exc


def rehearse(plan: BookingPlan, *, business_id: str, availability: dict,
             practitioner_tz: str | None, offerings: list[dict], bookings: list[dict],
             now: datetime, busy: list[dict] | None = None) -> dict:
    """Pure computation over a complete, tenant-scoped snapshot supplied by the loader."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    try:
        av, tz = _settings(availability, practitioner_tz or os.environ.get("PLATFORM_DEFAULT_TZ", "").strip())
    except Unavailable as exc:
        raise RehearsalUnavailable(str(exc)) from exc
    tz_name = tz.key
    dates = [a.start.astimezone(tz).date() for a in plan.appointments]
    if (max(dates) - min(dates)).days > 31:
        raise RehearsalUnavailable("Rehearse a plan covering no more than 31 days at a time.")

    services = {}
    for row in offerings:
        if row.get("business_id") != business_id or row.get("is_active") is not True:
            raise RehearsalUnavailable("The service records could not be verified for this business.")
        key = str(row.get("id"))
        if key in services:
            raise RehearsalUnavailable("The service snapshot contains duplicate records.")
        services[key] = _duration(row.get("duration_min"))
    if any(str(a.offering_id) not in services for a in plan.appointments):
        raise RehearsalUnavailable("A requested service is unavailable in this business.")

    occupied = []
    for row in bookings:
        if row.get("business_id") != business_id or row.get("status") != "active":
            raise RehearsalUnavailable("The booking records could not be verified for this business.")
        occupied.append({
            "appointment_at": _timestamp(row.get("appointment_at")).isoformat(),
            "duration_min_at_booking": _duration(row.get("duration_min_at_booking")),
        })
    if len(occupied) > MAX_BOOKINGS:
        raise RehearsalUnavailable("The calendar exceeds this rehearsal's 500-booking inspection limit.")

    outside = []
    for row in busy or []:
        if row.get("business_id") != business_id:
            raise RehearsalUnavailable("Outside-calendar blocks could not be verified for this business.")
        start, end = _timestamp(row.get("starts_at")), _timestamp(row.get("ends_at"))
        if end <= start:
            raise RehearsalUnavailable("An outside-calendar block has an invalid interval.")
        outside.append({"starts_at": start.isoformat(), "ends_at": end.isoformat()})
    if len(outside) > MAX_BOOKINGS:
        raise RehearsalUnavailable("Too many outside-calendar blocks for this rehearsal.")
    dependencies = {
        "availability": _fingerprint({"business_id": business_id, "rules": av.model_dump(), "timezone": tz_name}),
        "offerings": _fingerprint({"business_id": business_id, "durations": services}),
        "bookings": _fingerprint({"business_id": business_id, "intervals": sorted(occupied, key=lambda b: (b["appointment_at"], b["duration_min_at_booking"]))}),
        "outside_calendar": _fingerprint({"business_id": business_id, "intervals": sorted(outside, key=lambda b: (b["starts_at"], b["ends_at"]))}),
    }
    results = []
    for index, appointment in enumerate(plan.appointments):
        duration = services[str(appointment.offering_id)]
        start = appointment.start.astimezone(timezone.utc)
        day = start.astimezone(tz).date()
        slots = compute_slots(availability=av, practitioner_tz=tz_name,
                              existing_bookings=occupied, offering_duration_min=duration,
                              from_date=day, to_date=day, now=now, busy_blocks=outside)
        # Do not report nonexistent local times or DST-spanning wall-time durations
        # as verified elapsed-time slots. The existing engine remains authoritative
        # for its scheduling rules; this narrower capability may conservatively defer.
        usable = []
        for slot in slots:
            instant = _timestamp(slot["start_utc"])
            local = instant.astimezone(tz)
            if local.replace(tzinfo=None).isoformat() != slot["start_local"]:
                continue
            local_end = local + timedelta(minutes=duration)
            utc_end = local_end.astimezone(timezone.utc)
            if utc_end.astimezone(tz).replace(tzinfo=None) != local_end.replace(tzinfo=None):
                continue
            if utc_end - instant != timedelta(minutes=duration):
                continue
            usable.append((instant, slot))
        fit = next((slot for instant, slot in usable if instant == start), None)
        item = {"index": index, "offering_id": str(appointment.offering_id),
                "start": start.isoformat(), "duration_min": duration,
                "status": "fits" if fit else "conflict"}
        if fit:
            if fit.get("arrival_window_min"):
                item["arrival_window_min"] = fit["arrival_window_min"]
            occupied.append({"appointment_at": start.isoformat(), "duration_min_at_booking": duration})
        else:
            item["reason"] = "Does not fit the current slot rules, capacity, or earlier fitting proposals."
            nearest = sorted(usable, key=lambda pair: (abs((pair[0] - start).total_seconds()), pair[0]))[:2]
            item["alternatives"] = [dict(slot, start_local=instant.astimezone(tz).isoformat()) for instant, slot in nearest]
        results.append(item)

    conflicts = sum(item["status"] == "conflict" for item in results)
    return {
        "type": VERB, "result": "ok", "label": f"Booking rehearsal: {len(results) - conflicts} fit, {conflicts} conflict.",
        "capability_version": VERSION, "status": "conflicts" if conflicts else "fits",
        "checked_at": now.astimezone(timezone.utc).isoformat(), "timezone": tz_name,
        "snapshot_fingerprint": _fingerprint({"version": VERSION, "dependencies": dependencies}),
        "dependencies": dependencies, "appointments": results,
        "scope": "New bookings; business hours, duration, lead time, slot grid, shared capacity and outside-calendar blocks.",
        "execution_required": "Nothing reserved or changed. Reads are not atomic. Recheck current state through normal booking handlers before acting.",
        "alternatives_scope": "Same-day suggestions are independent, not reserved; rehearse a revised plan before using them together.",
    }


async def _rows(client, path: str) -> list[dict]:
    rows = await _sb(client, "GET", path)
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise RehearsalUnavailable("Required business data could not be read; availability is unknown.")
    return rows


async def _handle_rehearse_booking_plan(client, biz, action) -> dict:
    """Tenant identity comes only from Chief/MCP's authenticated business context."""
    try:
        plan = BookingPlan.model_validate({k: v for k, v in action.items() if k != "type"})
        business_id = str(UUID(str(biz["id"])))
        owner_id = str(UUID(str(biz["owner_id"])))
        rows = await _rows(client, f"/businesses?id=eq.{business_id}&select=id,owner_id,settings&limit=1")
        if len(rows) != 1 or rows[0].get("id") != business_id or rows[0].get("owner_id") != owner_id:
            raise RehearsalUnavailable("The current business could not be verified.")
        business = rows[0]
        settings = business.get("settings")
        if not isinstance(settings, dict):
            raise RehearsalUnavailable("Business scheduling settings are unavailable.")
        availability = settings.get("availability")
        practitioner_tz = None
        if isinstance(availability, dict) and not availability.get("timezone") and business.get("owner_id"):
            owner = str(UUID(str(business["owner_id"])))
            profiles = await _rows(client, f"/practitioner_profiles?owner_id=eq.{owner}&select=timezone&limit=1")
            practitioner_tz = profiles[0].get("timezone") if profiles else None
        ids = ",".join(sorted({str(a.offering_id) for a in plan.appointments}))
        offerings = await _rows(client, f"/offerings?business_id=eq.{business_id}&id=in.({ids})&is_active=eq.true&select=id,business_id,is_active,duration_min&limit=8")
        # Read through an empty page, even if the server returns short pages. Do
        # not assume an HTTP 200 or a row limit proves a complete calendar.
        # Include older starts too: a long booking can overlap the requested day.
        bookings = []
        while True:
            page = await _rows(client, f"/module_entries?business_id=eq.{business_id}&status=eq.active&appointment_at=not.is.null&select=id,business_id,status,appointment_at,duration_min_at_booking&order=id.asc&limit={PAGE_SIZE}&offset={len(bookings)}")
            if not page:
                break
            bookings.extend(page)
            if len(bookings) > MAX_BOOKINGS:
                raise RehearsalUnavailable("The calendar exceeds this rehearsal's 500-booking inspection limit.")
        if any(not r.get("id") for r in bookings) or len({r.get("id") for r in bookings}) != len(bookings):
            raise RehearsalUnavailable("The calendar changed during inspection; retry the rehearsal.")
        # Reuse production's server-owned busy-block adapter only after the fresh
        # exact business/owner check. Other reads retain the caller's RLS context.
        _, tz = _settings(availability, practitioner_tz or os.environ.get("PLATFORM_DEFAULT_TZ", "").strip())
        days = [a.start.astimezone(tz).date() for a in plan.appointments]
        if (max(days) - min(days)).days > 31:
            raise RehearsalUnavailable("Rehearse a plan covering no more than 31 days at a time.")
        lo = datetime.combine(min(days), time.min, tzinfo=tz).astimezone(timezone.utc)
        hi = datetime.combine(max(days) + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc)
        busy = await _pages(client, f"/calendar_busy_blocks?business_id=eq.{business_id}&starts_at=lt.{quote(hi.isoformat(), safe='')}"
                            f"&ends_at=gt.{quote(lo.isoformat(), safe='')}&select=id,business_id,starts_at,ends_at", read=_busy_get)
        return rehearse(plan, business_id=business_id, availability=availability,
                        practitioner_tz=practitioner_tz, offerings=offerings,
                        bookings=bookings, busy=busy, now=datetime.now(timezone.utc))
    except (RehearsalUnavailable, Unavailable) as exc:
        message = str(exc)
    except (ValueError, TypeError, KeyError):
        message = "The plan or scheduling data is invalid. Use 1-8 new appointments with offering IDs and timestamps including timezone offsets; check the stored hours and durations."
    except Exception:
        logger.exception("Booking rehearsal failed")
        message = "The booking plan could not be checked. Availability is unknown; try again."
    return {"type": VERB, "result": message, "label": "Booking rehearsal needs review.",
            "failed": True, "status": "needs_review", "capability_version": VERSION}


async def handle_rehearse_booking_plan(client, biz, action) -> dict:
    """Bound the complete read and log execution without tenant/customer content."""
    try:
        async with asyncio.timeout(CHECK_BUDGET_S):
            result = await _handle_rehearse_booking_plan(client, biz, action)
    except TimeoutError:
        result = {"type": VERB, "result": "The calendar check timed out; availability is unknown. Try again.",
                  "label": "Booking rehearsal needs review.", "failed": True,
                  "status": "needs_review", "capability_version": VERSION}
    logger.info("capability=%s version=%s status=%s", VERB, VERSION, result["status"])
    return result
