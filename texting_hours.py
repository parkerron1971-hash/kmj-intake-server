"""
texting_hours.py — a church's own texting hours, quiet hours and alert limit.

Kevin, 2026-11-14, on the Church Texting Playbook: "we need to make sure
that people know they can adjust the window when automatic texts can go
out. and any other rule we have as default that they can make the
changes", then "yes build the texting hours panel".

What a church can set (settings.texting_hours), each with the default
everyone had before:

  auto_from, auto_until   when automatic texts may go out, on the church's
                          clock: New here's thank-you, note and invite.
                          9 AM to 8 PM. Never earlier than 8 AM or later
                          than 9 PM: the federal calling hours.
  quiet_from, quiet_until when app alerts for groups, messages and news wait
                          (member_push.QUIET_KINDS), serving asks hold
                          (sunday_serving_alerts), and an Important post's
                          texts and emails to people without the app wait
                          (news_reach). All of them already asked
                          member_push.quiet_hour, which now reads this.
                          9 PM to 7 AM.
  alerts_per_day          app alerts the church sends everyone in a day
                          (announcements plus News posts that ring). 3; 1 to 5.
  note, invite            New here's weekday note and invite: {day, hour},
                          day 0 Monday .. 5 Saturday. Monday 10 AM and
                          Thursday 6 PM. The hour must sit inside the
                          automatic-text hours.

Not here: the DAILY devotional keeps its 7:30 PM text (one evening send for
every church), kids pickup and sign-in codes go when they're asked for, and
an announcement goes when someone presses Send or picked a time.

GET /texting-hours/{business_id} (any login), PUT (whoever sends the
church's announcements, as for New here).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("texting_hours")

router = APIRouter(tags=["texting-hours"])

DEFAULTS: Dict[str, Any] = {
    "auto_from": 9, "auto_until": 20,
    "quiet_from": 21, "quiet_until": 7,
    "alerts_per_day": 3,
    "note": {"day": 0, "hour": 10},
    "invite": {"day": 3, "hour": 18},
}
AUTO_FROM = range(8, 13)        # 8 AM .. noon
AUTO_UNTIL = range(17, 22)      # 5 PM .. 9 PM (exclusive end, so the last text goes before it)
QUIET_FROM = range(19, 24)      # 7 PM .. 11 PM
QUIET_UNTIL = range(5, 10)      # 5 AM .. 9 AM
ALERTS = range(1, 6)
DAYS = range(0, 6)              # Monday .. Saturday
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _int(v: Any, allowed: range, default: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return n if n in allowed else default


def of(business: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The church's hours, its saved choices over DEFAULTS: anything saved
    that isn't allowed reads as the default."""
    saved = ((business or {}).get("settings") or {}).get("texting_hours")
    saved = saved if isinstance(saved, dict) else {}
    out = {
        "auto_from": _int(saved.get("auto_from"), AUTO_FROM, DEFAULTS["auto_from"]),
        "auto_until": _int(saved.get("auto_until"), AUTO_UNTIL, DEFAULTS["auto_until"]),
        "quiet_from": _int(saved.get("quiet_from"), QUIET_FROM, DEFAULTS["quiet_from"]),
        "quiet_until": _int(saved.get("quiet_until"), QUIET_UNTIL, DEFAULTS["quiet_until"]),
        "alerts_per_day": _int(saved.get("alerts_per_day"), ALERTS, DEFAULTS["alerts_per_day"]),
    }
    for key in ("note", "invite"):
        mine = saved.get(key) if isinstance(saved.get(key), dict) else {}
        base = DEFAULTS[key]
        day = _int(mine.get("day"), DAYS, base["day"])
        hour = _int(mine.get("hour"), range(out["auto_from"], out["auto_until"]), -1)
        if hour < 0:   # outside the church's hours (they moved): the default, held inside them
            hour = min(max(base["hour"], out["auto_from"]), out["auto_until"] - 1)
        out[key] = {"day": day, "hour": hour}
    return out


def in_auto_window(business: Optional[Dict[str, Any]], local: datetime) -> bool:
    """May an automatic text go now? `local` is on the church's clock."""
    h = of(business)
    return h["auto_from"] <= local.hour < h["auto_until"]


def is_quiet(business: Optional[Dict[str, Any]], hour: int) -> bool:
    """Is this hour (the church's clock) inside its quiet hours?"""
    h = of(business)
    return hour >= h["quiet_from"] or hour < h["quiet_until"]


def alerts_per_day(business: Optional[Dict[str, Any]]) -> int:
    return of(business)["alerts_per_day"]


def hour_words(hour: int) -> str:
    """15 → '3 PM', 12 → 'noon', 0 → 'midnight'."""
    if hour == 0:
        return "midnight"
    if hour == 12:
        return "noon"
    return f"{hour % 12 or 12} {'AM' if hour < 12 else 'PM'}"


# ─── the panel ───────────────────────────────────────────────────────

def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _business(business_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{_q(business_id)}&select=id,name,type,settings,owner_id&limit=1")
    return rows[0] if isinstance(rows, list) and rows else None


def _uuid(v: Any) -> str:
    from uuid import UUID
    try:
        return str(UUID(str(v)))
    except (TypeError, ValueError):
        raise HTTPException(404, "Church not found")


def _may_edit(business_id: str, user: AuthedUser) -> bool:
    import sms_routing
    try:
        sms_routing._may_announce(business_id, user)
        return True
    except HTTPException:
        return False


def view(business: Dict[str, Any], *, can_edit: bool) -> Dict[str, Any]:
    return {"hours": of(business), "defaults": DEFAULTS, "can_edit": can_edit,
            "limits": {"auto_from": [AUTO_FROM.start, AUTO_FROM.stop - 1],
                       "auto_until": [AUTO_UNTIL.start, AUTO_UNTIL.stop - 1],
                       "quiet_from": [QUIET_FROM.start, QUIET_FROM.stop - 1],
                       "quiet_until": [QUIET_UNTIL.start, QUIET_UNTIL.stop - 1],
                       "alerts_per_day": [ALERTS.start, ALERTS.stop - 1]}}


@router.get("/texting-hours/{business_id}")
def get_hours(business_id: str, user: AuthedUser = Depends(require_user)):
    import business_access
    biz = _uuid(business_id)
    business_access.assert_access(biz, user, "viewer")
    business = _business(biz)
    if not business:
        raise HTTPException(503, "The church couldn't be read just now. Try again in a minute.")
    return view(business, can_edit=_may_edit(biz, user))


class Slot(BaseModel):
    day: int
    hour: int


class HoursIn(BaseModel):
    auto_from: int
    auto_until: int
    quiet_from: int
    quiet_until: int
    alerts_per_day: int
    note: Slot
    invite: Slot


def clean(body: HoursIn) -> Dict[str, Any]:
    """What gets saved, or a 400 that says what to change."""
    if body.auto_from not in AUTO_FROM:
        raise HTTPException(400, "Automatic texts can start between 8 AM and noon.")
    if body.auto_until not in AUTO_UNTIL:
        raise HTTPException(400, "Automatic texts stop between 5 PM and 9 PM. Texts after 9 PM aren't allowed.")
    if body.quiet_from not in QUIET_FROM:
        raise HTTPException(400, "Quiet hours start between 7 PM and 11 PM.")
    if body.quiet_until not in QUIET_UNTIL:
        raise HTTPException(400, "Quiet hours end between 5 AM and 9 AM.")
    if body.alerts_per_day not in ALERTS:
        raise HTTPException(400, "Pick 1 to 5 app alerts a day.")
    out: Dict[str, Any] = {k: int(getattr(body, k)) for k in
                           ("auto_from", "auto_until", "quiet_from", "quiet_until", "alerts_per_day")}
    for key, label in (("note", "New here's note"), ("invite", "New here's invite")):
        slot: Slot = getattr(body, key)
        if slot.day not in DAYS:
            raise HTTPException(400, f"{label} goes Monday to Saturday.")
        if not body.auto_from <= slot.hour < body.auto_until:
            raise HTTPException(400, f"{label} has to go inside your automatic-text hours "
                                     f"({hour_words(body.auto_from)} to {hour_words(body.auto_until)}).")
        out[key] = {"day": int(slot.day), "hour": int(slot.hour)}
    return out


@router.put("/texting-hours/{business_id}")
def put_hours(business_id: str, body: HoursIn, user: AuthedUser = Depends(require_user)):
    import business_access
    biz = _uuid(business_id)
    business_access.assert_access(biz, user, "viewer")
    if not _may_edit(biz, user):
        raise HTTPException(403, "Only someone who sends the church's announcements can change its texting hours.")
    business = _business(biz)
    if not business:
        raise HTTPException(503, "The church couldn't be read just now. Try again in a minute.")
    settings = dict(business.get("settings") or {})
    settings["texting_hours"] = clean(body)
    if sb_clients.sb_patch_as_service(f"/businesses?id=eq.{_q(biz)}", {"settings": settings}) is None:
        raise HTTPException(503, "That didn't save just now. Try again in a minute.")
    return view({**business, "settings": settings}, can_edit=True)
