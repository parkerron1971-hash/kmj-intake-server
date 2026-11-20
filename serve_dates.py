# serve_dates.py — Who serves when, past Sunday: a dated occasion that isn't
# a Sunday service (an outreach night, a Saturday event, a Wednesday Bible
# study), scheduled for the volunteer teams only. Kevin, 2026-11-17: "build
# that", about Laquesha (the Sunday & Serving lane) being unable to schedule
# greeters, ushers, parking, kids workers or hospitality for anything but a
# Sunday.
#
# An event date is a worship_services row of kind 'event'
# (supabase/APPLY-2026-11-17-event-volunteer-dates.sql), so every serving
# read already follows it: an ask, a sub, the reminders, the member app's
# My serving, the .ics, the phone alerts and the hours treat it as they
# treat a Sunday, in its own day's words. It carries no order of service.
#   * Who serves when (sunday_planning) adds one from an upcoming Services &
#     Events entry (event_entry_id, so the event and its volunteers are the
#     same thing) or typed (title, day, time, place), and schedules only the
#     Volunteers' teams for it: ChurchSavvy's worship and production teams
#     are never asked to an event date.
#   * ChurchSavvy never shows one: every read of the Sunday plans
#     (worship_show_router, sunday_order, the leaders note, the monthly
#     report, the work checks, the countdown's count) adds plans_only(). A
#     new reader of worship_services that is about the plan must add it too.
#
# Before the migration the columns aren't there: nothing selects them,
# nothing filters on them (no event date can exist yet), and the feature
# hides itself (ready() is False: Who serves when offers no event date and
# its routes answer 404). Nothing is a 500.
#
# CHURCH_EVENT_VOLUNTEERS = off | owner | on (default owner): who may add an
# event date. owner is the platform owner's own church (Love City), as
# new_here does it (member_asks.platform_church). Event dates already made
# stay on the schedule and in the member app whatever the switch says:
# people were asked, and they still need to know.
from __future__ import annotations

import os
import time as clock
from datetime import date, datetime
from typing import Any, Dict, Optional

import sb_clients

SWITCH = "CHURCH_EVENT_VOLUNTEERS"
SERVICE, EVENT = "service", "event"
# What a serving read adds to its select once the columns are there.
FIELDS = ",kind,place,event_entry_id"
READY_SECONDS = 600.0      # the columns, once there, are asked about again in ten minutes
MISSING_SECONDS = 60.0     # not there (or couldn't tell): asked again a minute later
_STATE: Dict[str, Any] = {"yes": None, "at": 0.0}
# Tests pin the answer (conftest: False, so every other suite reads as
# before the migration); production leaves it None and asks the database.
_FORCE: Optional[bool] = None


# ─── the switch ──────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get(SWITCH) or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def _platform_email() -> str:
    return (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()


def open_for(business_id: Any, user: Any = None) -> bool:
    """Whether this church may add event dates now: on for everyone, or
    owner mode and the platform owner's own church (the platform owner
    signed in is known at once; anyone else's church is looked up, kept ten
    minutes, and a read that fails is a no)."""
    m = mode()
    if m == "on":
        return True
    if m != "owner":
        return False
    if user is not None and (getattr(user, "email", None) or "").strip().lower() == _platform_email():
        return True
    try:
        import member_asks
        return member_asks.platform_church(business_id)
    except Exception:  # noqa: BLE001 — a lookup that fails is a no, never a 500
        return False


# ─── the columns ─────────────────────────────────────────────────────

def ready() -> bool:
    """True once worship_services has kind, place and event_entry_id. Only
    PostgREST's "no such column" (42703) says they aren't; a blip keeps the
    last answer, and with none yet reads as not there (nothing is filtered
    then, which is right: no event date can exist without the column)."""
    if _FORCE is not None:
        return _FORCE
    if not sb_clients.sb_url():
        return False    # no database to ask (a script), as schema_probe does
    now = clock.monotonic()
    yes, at = _STATE["yes"], _STATE["at"]
    if yes is not None and now - at < (READY_SECONDS if yes else MISSING_SECONDS):
        return yes
    try:
        rows = sb_clients.sb_get_as_service("/worship_services?select=kind,place,event_entry_id&limit=1")
        err = sb_clients.last_error() if rows is None else None
    except Exception:  # noqa: BLE001 — a fake or a broken client is "couldn't tell"
        rows, err = None, None
    if isinstance(rows, list):
        got = True
    elif err and (str(err.get("code")) == "42703" or "42703" in str(err.get("message") or "")):
        got = False
    else:
        got = bool(yes)
    _STATE["yes"], _STATE["at"] = got, now
    return got


def fields() -> str:
    """',kind,place,event_entry_id' for a serving read's select, once there,
    and ',needs' (an event date's own numbers: event_volunteers.py) once that
    migration is in too (event_volunteers.ready)."""
    if not ready():
        return ""
    import event_volunteers
    return FIELDS + (",needs" if event_volunteers.ready() else "")


def plans_only() -> str:
    """The filter a read of the Sunday plans adds: no event dates."""
    return f"&kind=neq.{EVENT}" if ready() else ""


def is_event(row: Optional[Dict[str, Any]]) -> bool:
    return (row or {}).get("kind") == EVENT


# ─── how many a place needs ──────────────────────────────────────────

def needed(service: Optional[Dict[str, Any]], place: Optional[Dict[str, Any]]) -> int:
    """How many people this place needs at this service: the one rule every
    slot loop reads (docs/EVENT_VOLUNTEERS.md 6.5). An event date with its
    own numbers (worship_services.needs, {"<place id>": n}) needs exactly
    those, and 0 for a place it doesn't name: that place doesn't show for the
    date, isn't counted open, and can't be asked, offered or filled. Every
    other service, and an event date without numbers (needs null, how every
    date made before them reads), needs the place's Sunday number."""
    needs = (service or {}).get("needs")
    if isinstance(needs, dict):
        try:
            n = needs.get(str((place or {}).get("id")), 0)
            return max(0, int(n)) if not isinstance(n, bool) else 0
        except (TypeError, ValueError):
            return 0
    n = (place or {}).get("needed")
    return n if isinstance(n, int) and not isinstance(n, bool) and n >= 1 else 1


# ─── saying the day ──────────────────────────────────────────────────

def weekday(at: Any) -> str:
    """"Sunday", "Thursday": the day a service or an event date is on."""
    return at.strftime("%A") if isinstance(at, (datetime, date)) else "Sunday"


def is_sunday(at: Any) -> bool:
    return isinstance(at, (datetime, date)) and at.weekday() == 6


def short_day(at: Any) -> str:
    """"Nov 19"."""
    return f"{at.strftime('%b')} {at.day}"


def day_label(at: Any) -> str:
    """"Thursday, Nov 19"."""
    return f"{weekday(at)}, {short_day(at)}"
