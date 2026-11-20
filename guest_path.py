"""guest_path.py — the Welcome Path: one path for every first-time guest.

Kevin, 2026-11-20: "we need to upgrade the visitor flow experience ...
capture visitors, place them in a flow where they receive automated texts
from the church, chief should be sending a follow up call to the admin of
people and care or a church should be able to assign who should be over
this". On the mock (canvas WmRiSK8seJky8pJUK5nztE): "by default the calls
goes to people and care until we get a welcome team. of course allow this
to be selected by any church as to how they want it done so there structure
is unique to them", then "build".

This is the small shared core the path's pieces read, so they agree on
four things:

  THE SWITCH   GUEST_PATH = off | owner | on. Unset is "owner": only the
               platform's own church (member_asks.platform_church), the way
               NEW_HERE started. "off" is the rollback: every door, every
               hand-off and every text behaves exactly as it did before.
  THE DOORS    where a guest was first met (DOORS). New here kept only the
               guests who texted its word; the path keeps every door's.
  THE GUEST    contacts.metadata.new_here, New here's own key (no
               migration), now for every door. New here's keys stay as they
               were (code, visits, card_at, card, app); the path adds:
                 door        a DOORS key: where the path started
                 texted_at   when the path started (the welcome's time), for
                             every door, so New here's lists and counts read
                             every guest. For "text" it is still the moment
                             they texted the word.
                 texts_ok    they said yes to the church's texts (a text
                             door's word is that yes)
                 hold        a guest's reply waits on a person: no automatic
                             text goes until someone answers (hold_since)
  A GUEST'S FOLLOW-UP
               is_guest_follow_up(row): the follow-ups that are a first-time
               guest's welcome call, whichever door made them. "Who calls
               our guests" routes these, and only these.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

SWITCH = "GUEST_PATH"

# Where a guest was first met, in the words the office reads.
DOORS: Dict[str, str] = {
    "text": "Text NEW",
    "kids": "Kids desk",
    "desk": "Welcome desk",
    "web": "Website card",
    "form": "A card",          # Plan your visit, the bulletin's guest card, any guest form
    "app": "Member app",
}

# The church duty whose holder makes the calls until there's a Welcome Team
# (church_duties: People & Care's by default).
FIRST_GUESTS = "first_guests"

# Follow-ups that are a first-time guest's welcome, by the card that made
# them (church_follow_ups.card_key): New here's card, the member app's
# "I'm new here", a first check-in (the kids desk or the office's First
# time), and the website's connect card.
GUEST_CARD_KEYS = ("text:new_here", "app:new_here", "checkin:first", "web:connect_card")
# A church's own forms (card_key "form:<id>") are a guest's when the form is
# a connect card or a Plan your visit card (church_follow_up.kind_for_form).
GUEST_FORM_KINDS = ("connect", "visit")


def mode() -> str:
    m = (os.environ.get(SWITCH) or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def switched_on(business_id: Any) -> bool:
    """Whether the Welcome Path is on for this church. A read that fails is
    a no: the church keeps what it had."""
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        try:
            import member_asks
            return bool(member_asks.platform_church(business_id))
        except Exception:  # noqa: BLE001
            return False
    return False


def is_guest_follow_up(row: Optional[Dict[str, Any]]) -> bool:
    """A first-time guest's welcome follow-up, whichever door made it."""
    if not isinstance(row, dict):
        return False
    key = str(row.get("card_key") or "")
    if key in GUEST_CARD_KEYS:
        return True
    return key.startswith("form:") and str(row.get("path_kind") or "") in GUEST_FORM_KINDS


def guest_meta(contact: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """contacts.metadata.new_here as a dict ({} when there's none)."""
    meta = (contact or {}).get("metadata")
    mine = meta.get("new_here") if isinstance(meta, dict) else None
    return dict(mine) if isinstance(mine, dict) else {}


def door_words(door: Any) -> str:
    return DOORS.get(str(door or ""), "")
