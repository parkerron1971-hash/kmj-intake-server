"""Who sees what on the phone (Kevin, 2026-10-26; canvas 99aFvCSRXU1x9pmqUcncoP).

A business push (the morning brief, a new booking, a new email) reads the
whole business: leads, invoices, the inbox. On a church with Church Areas
on, an office login that works only some areas sees only those in the app
(church_areas.my_areas), so its phone shouldn't hear the rest either:

  * `limited` names those logins, and push_notifications.send_to_business
    leaves their phones out of every business push. The owner, admins and
    a login that still sees the whole church hear them as before.
  * `notes` gives each of them a morning line of its own instead: the one
    thing handed to them this week (church_my_week), on their own phone,
    opening on My week. A morning with nothing for them stays quiet.

No model call: the line is My week's own first item. Everything rides
CHURCH_AREAS; until it's on, phones hear what they always did.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import quote

from fastapi import HTTPException

import church_areas
import sb_clients

TITLE = "Good morning ✦ Chief here"
NAV = "operate:my-week"


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _applies(biz: Dict[str, Any]) -> bool:
    if church_areas.mode() != "on":
        return False
    import church_follow_up as cfu
    return cfu.is_church(biz)


def limited(biz: Dict[str, Any], seats: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """user id → seat, for the logins among `seats` (user id → an active
    business_users row) whose app shows only some areas. Empty when it
    doesn't apply. A login whose view couldn't be read isn't named: it
    hears what it heard before, as its menu shows what it showed before."""
    if not _applies(biz):
        return {}
    owner = str(biz.get("owner_id") or "")
    out: Dict[str, Dict[str, Any]] = {}
    for uid, seat in seats.items():
        role = seat.get("role")
        if uid == owner or role in church_areas.KEEPS_ALL:
            continue
        view = church_areas.my_areas(str(biz["id"]), uid, role)
        if view and view.get("areas") is not None:
            out[uid] = seat
    return out


def line(week: Dict[str, Any]) -> Optional[str]:
    """The morning line from a login's week: its first item, and how many
    more. None when nothing needs them."""
    first = week.get("next")
    if not first or not first.get("title"):
        return None
    more = int((week.get("counts") or {}).get("needs") or 0) - 1
    said = str(first["title"]).strip()
    if first.get("kind") == "task":
        # A task's title is the church's own words, not a sentence.
        said = f"Your task: {said}"
    if not said.endswith((".", "?", "!")):
        said += "."
    if more > 0:
        said += f" {more} more {'needs' if more == 1 else 'need'} you this week."
    return said


def notes(biz: Dict[str, Any], *, today: str) -> int:
    """Each limited login's own morning line, to its phones on this church.
    Returns how many devices heard one."""
    if not _applies(biz):
        return 0
    import church_my_week
    import push_notifications
    bid = str(biz["id"])
    subs = sb_clients.sb_get_as_service(f"/push_subscriptions?business_id=eq.{_q(bid)}&select=user_id&limit=50")
    if not isinstance(subs, list):
        return 0
    seats = push_notifications.active_seats(bid, (str(s["user_id"]) for s in subs if s.get("user_id")))
    if not seats:
        return 0
    sent = 0
    for uid, seat in limited(biz, seats).items():
        try:
            week = church_my_week.build(biz, uid, seat.get("invited_email") or "", seat.get("role") or "viewer")
        except HTTPException:
            print(f"[church_morning] {bid}: a login's week couldn't be read; no note")
            continue
        said = line(week)
        if said:
            first = str((week.get("me") or {}).get("name") or "").split(" ")[0]
            title = f"Good morning, {first} ✦ Chief here" if first else TITLE
            sent += push_notifications.send_to_user(uid, business_id=bid, title=title, body=said, nav=NAV,
                                                    tag=f"morning-{today}")
    return sent
