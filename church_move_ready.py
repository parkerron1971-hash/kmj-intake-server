"""
church_move_ready.py — is this church ready for its first Sunday?

Kevin's preparation list, 2026-11-14, on the Move-in room: "There's no
'ready for Sunday' check." The Move-in room says what a church HANDED IN.
This says what is actually SET UP in the church's account, read fresh on
every look, so the Friday check and Saturday's rehearsal start from what
is true and not from what was promised: a spreadsheet handed in is not
people who can sign in, and service times typed in a form are not a
service on the calendar.

WHAT IT ANSWERS
  ready(biz) -> {"lines": [{key, title, state, words}], "ready", "watch",
                 "not_yet", "unknown", "total"}
  One line per thing Sunday leans on. A line's state is one of:
    ready     it is set up
    watch     it will work, and something about it will trip people up
              (adults with no email or mobile of their own; an office login
              invited and not joined)
    not_yet   Sunday can't lean on it as it stands
    unknown   it couldn't be read just now. Never a guess: a read that
              failed is not "nothing there".

WHAT IT DOESN'T
  It writes nothing. In particular it never starts this week's check-in
  (kids_checkin's this-week does, on purpose) and never switches anything
  on. It can't see the room: the Wi-Fi, the screen, the sound and the
  printed tag are Saturday's to find out.

WHO
  The platform owner, from Mission Control's Move-ins
  (church_move_in.platform_router, GET /platform/move-in/{church}/ready).
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

import sb_clients

logger = logging.getLogger(__name__)

READY, WATCH, NOT_YET, UNKNOWN = "ready", "watch", "not_yet", "unknown"
PAGE = 1000
PAGES_MAX = 30
UNREAD_WORDS = "This couldn't be read just now. Refresh to try again."
# What only the room can tell, said on the screen under the list.
ROOM_ONLY = ("The Wi-Fi reaches the seats.", "The film plays on the screen with sound.",
             "A child is checked in on the tablet, the tag prints, and the child is picked up.",
             "One real dollar is given and the receipt arrives.")


class Unread(Exception):
    """A read failed. The line says so; it never says 'none'."""


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _rows(path: str) -> List[Dict[str, Any]]:
    got = sb_clients.sb_get_as_service(path)
    if not isinstance(got, list):
        raise Unread(path.split("?")[0])
    return got


def _all(path: str, order: str = "id.asc") -> List[Dict[str, Any]]:
    """Every row, a page at a time (a church's people can pass 1,000)."""
    out: List[Dict[str, Any]] = []
    for n in range(PAGES_MAX):
        page = _rows(f"{path}&order={order}&limit={PAGE}&offset={n * PAGE}")
        out += page
        if len(page) < PAGE:
            break
    return out


def _count(path: str) -> int:
    n = sb_clients.sb_count_as_service(path)
    if not isinstance(n, int):
        raise Unread(path.split("?")[0])
    return n


def _n(n: int, one: str, many: Optional[str] = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


# ─── The lines ────────────────────────────────────────────────────────

def _people(biz: Dict[str, Any]) -> Tuple[str, str]:
    """Who can sign in to the members' app on Sunday. The rule is
    member_portal's: a person signs in with an email or mobile of their
    own. No email and no mobile gets no code; one on more than one record
    gets no code (MAX_HOUSEHOLD = 1); under 13 never signs in, so a child
    sharing a parent's email blocks nobody."""
    import member_portal as mp
    import member_spaces as ms
    rows = _all(f"/contacts?business_id=eq.{_q(biz['id'])}&select=id,email,phone,birthdate")
    if not rows:
        return NOT_YET, "Nobody is on file yet."
    seen: Counter = Counter()
    signers: List[Tuple[str, str]] = []
    children = neither = 0
    for r in rows:
        if ms.is_child(r):
            children += 1
            continue
        email = str(r.get("email") or "").strip().lower()
        email = email if mp._EMAIL_RE.match(email) else ""
        phone = mp._last10(r.get("phone"))
        phone = phone if len(phone) == 10 else ""
        if not email and not phone:
            neither += 1
            continue
        signers.append((email, phone))
        seen.update(k for k in (email and f"e:{email}", phone and f"p:{phone}") if k)
    shared = sum(1 for e, p in signers if not ((e and seen[f"e:{e}"] == 1) or (p and seen[f"p:{p}"] == 1)))
    can = len(signers) - shared
    words = [f"{_n(len(rows), 'person', 'people')} on file. {can:,} can sign in on Sunday."]
    if neither:
        words.append(f"{neither:,} {'has' if neither == 1 else 'have'} no email or mobile of their own, "
                     "so no code can reach them.")
    if shared:
        words.append(f"{shared:,} share an email or mobile with someone else. A shared one gets no code.")
    if children:
        words.append(f"{_n(children, 'child', 'children')} under 13 {'doesn' if children == 1 else 'don'}'t sign in.")
    if not can:
        return NOT_YET, " ".join(words)
    return (WATCH if neither or shared else READY), " ".join(words)


def _families(biz: Dict[str, Any]) -> Tuple[str, str]:
    b = _q(biz["id"])
    families = _count(f"/households?business_id=eq.{b}&select=id")
    children = _count(f"/children?business_id=eq.{b}&active=eq.true&select=id")
    if not families:
        return NOT_YET, "No families are formed yet. Children appear at kids check-in through their family."
    words = f"{_n(families, 'family', 'families')} and {_n(children, 'child', 'children')}."
    if not children:
        return WATCH, words + " With no children on file, kids check-in has nobody to find."
    return READY, words


def _giving(biz: Dict[str, Any]) -> Tuple[str, str]:
    import giving_router
    import payments_core
    if not biz.get("stripe_account_id"):
        return NOT_YET, "Giving setup with Stripe hasn't been started. Only the owner's login can start it."
    if not payments_core.can_charge(biz):
        return NOT_YET, "Stripe hasn't approved the church yet. Giving can't be switched on until it does."
    if not giving_router.giving_is_active(biz):
        return NOT_YET, "Stripe has approved the church. Giving isn't switched on yet."
    return READY, "Stripe has approved the church and giving is switched on. Give one real dollar to be sure."


def _app(biz: Dict[str, Any]) -> Tuple[str, str]:
    import member_portal as mp
    if not mp.portal_active(biz):
        return NOT_YET, "The members' app is switched off. The owner switches it on."
    if not mp.sign_in_open(biz):
        return NOT_YET, "The members' app is on, and sign-in is paused. Nobody new can sign in until it's opened."
    if not mp.codes_can_go_out():
        return NOT_YET, "The members' app is on, and sign-in codes can't be sent right now."
    return READY, "The members' app is switched on and sign-in is open."


def _calendar(biz: Dict[str, Any]) -> Tuple[str, str]:
    import live_router
    coming = live_router.occasions(str(biz["id"]))
    if coming is None:
        raise Unread("occasions")
    if not coming:
        return NOT_YET, "Nothing is on the calendar from today on, so members see nothing coming up."
    from events_rsvp_router import _parse_day
    first = coming[0]
    day = _parse_day(first.get("when"))
    when = f"{day.strftime('%A, %B')} {day.day}" if day else str(first.get("when") or "")
    return READY, (f"{_n(len(coming), 'service or event', 'services and events')} on the calendar from today on. "
                   f"Next: {first['title']}, {when}.")


def _checkin(biz: Dict[str, Any]) -> Tuple[str, str]:
    import church_checkin as cc
    st = cc.settings(biz)
    if st is None:
        raise Unread("church_checkin_settings")
    if not st.get("enabled"):
        return NOT_YET, "Sunday check-in is switched off."
    w = cc.window(st)
    found = cc.find_occasion(str(biz["id"]), w["day"])
    if found is None:
        raise Unread("occasion")
    words = f"Sunday check-in is on: {w['weekday']}s at {cc.clock(w['start'])}."
    if not found:
        return WATCH, words + f" This week's service ({w['day'].strftime('%B')} {w['day'].day}) isn't started yet."
    return READY, words + f" This week's is started: {found['title']}."


def _kids(biz: Dict[str, Any]) -> Tuple[str, str]:
    b = _q(biz["id"])
    children = _all(f"/children?business_id=eq.{b}&active=eq.true&select=id,room")
    tablets = _rows(f"/checkin_stations?business_id=eq.{b}&revoked_at=is.null&paired_at=not.is.null"
                    "&select=id&limit=100")
    paired = (f"{_n(len(tablets), 'tablet')} {'is' if len(tablets) == 1 else 'are'} paired."
              if tablets else "No tablet is paired yet.")
    if not children:
        return WATCH, f"No children are on file. {paired}"
    rooms = sorted({str(c.get("room") or "").strip() for c in children} - {""})
    roomless = sum(1 for c in children if not str(c.get("room") or "").strip())
    words = [f"{_n(len(children), 'child', 'children')} in {_n(len(rooms), 'room')}"
             + (f" ({', '.join(rooms[:6])})." if rooms else ".")]
    if roomless:
        words.append(f"{roomless:,} {'has' if roomless == 1 else 'have'} no room yet.")
    words.append(paired)
    if not tablets:
        return NOT_YET, " ".join(words)
    return (WATCH if roomless else READY), " ".join(words)


def _logins(biz: Dict[str, Any]) -> Tuple[str, str]:
    seats = _rows(f"/business_users?business_id=eq.{_q(biz['id'])}&status=in.(invited,active)"
                  "&select=invited_email,status&limit=200")
    joined = sum(1 for s in seats if s.get("status") == "active")
    waiting = [str(s.get("invited_email") or "").strip() for s in seats if s.get("status") == "invited"]
    if not seats:
        return NOT_YET, "No office logins are invited. Each welcome desk helper needs one to add a person on Sunday."
    words = f"{_n(joined, 'office login')} {'has' if joined == 1 else 'have'} joined."
    if waiting:
        named = ", ".join(w for w in waiting[:5] if w)
        return WATCH, (words + f" {len(waiting):,} invited and not joined yet" + (f": {named}" if named else "")
                       + ("." if len(waiting) <= 5 else ", and more."))
    return READY, words


def _safety(biz: Dict[str, Any]) -> Tuple[str, str]:
    import member_portal_messaging as mpm
    import messaging_router
    try:
        named = messaging_router.officer_count(str(biz["id"]))
    except Exception as e:  # noqa: BLE001  (its reads answer 503)
        raise Unread("officers") from e
    need = messaging_router.MIN_OFFICERS
    if named < need:
        return NOT_YET, f"{named} of {need} safety officers are named. Member messaging stays off until both are."
    on = mpm.turned_on(biz)
    return READY, (f"{_n(named, 'safety officer')} are named. Member messaging is "
                   + ("on." if on else "still off, and can be switched on."))


def _look(biz: Dict[str, Any]) -> Tuple[str, str]:
    import member_app_ui
    kit = (biz.get("settings") or {}).get("brand_kit")
    kit = kit if isinstance(kit, dict) else {}
    assets = kit.get("assets") if isinstance(kit.get("assets"), dict) else {}
    logo = bool(kit.get("logo_url") or kit.get("logo") or assets.get("primary"))
    colour = member_app_ui.brand_colour(biz, {})
    if logo and colour:
        return READY, "The logo and the church colour are in, so the app and the giving page look like the church."
    if logo or colour:
        return WATCH, ("The logo is in. The church colour isn't set yet." if logo
                       else "The church colour is set. The logo isn't in yet.")
    return NOT_YET, "No logo or church colour yet, so the app wears the standard look."


def _texting(biz: Dict[str, Any]) -> Tuple[str, str]:
    rows = _rows(f"/sms_numbers?business_id=eq.{_q(biz['id'])}&status=eq.active&select=phone_number&limit=1")
    if not rows:
        return WATCH, ("The church has no texting number of its own yet. Members say yes to texts by texting it, "
                       "so get one before it goes on the screen.")
    tail = re.sub(r"\D", "", str(rows[0].get("phone_number") or ""))[-4:]
    return READY, f"The church has its own texting number, ending {tail}."


def _groups(biz: Dict[str, Any]) -> Tuple[str, str]:
    import member_app_pictures
    groups = member_app_pictures.church_groups(str(biz["id"]))
    if groups is None:
        raise Unread("groups")
    if not groups:
        return WATCH, "No groups yet, so there is nothing to join in the app."
    led = {str(r.get("group_id")) for r in _all(
        f"/group_members?business_id=eq.{_q(biz['id'])}&role=eq.leader&select=group_id",
        order="group_id.asc,contact_id.asc")}
    without = sum(1 for g in groups if str(g.get("id")) not in led)
    words = f"{_n(len(groups), 'group')}."
    if without:
        return WATCH, words + f" {without:,} {'has' if without == 1 else 'have'} no leader yet."
    return READY, words + " Each one has a leader."


LINES: List[Tuple[str, str, Callable[[Dict[str, Any]], Tuple[str, str]]]] = [
    ("people", "People who can sign in", _people),
    ("families", "Families and children", _families),
    ("app", "The members' app", _app),
    ("giving", "Giving", _giving),
    ("calendar", "What's coming up", _calendar),
    ("checkin", "Sunday check-in", _checkin),
    ("kids", "Kids rooms and the tablet", _kids),
    ("logins", "Office logins", _logins),
    ("safety", "Safety officers", _safety),
    ("look", "The church's look", _look),
    ("texting", "Texting number", _texting),
    ("groups", "Groups", _groups),
]


def ready(biz: Dict[str, Any]) -> Dict[str, Any]:
    """Every line, each read on its own: one that fails says so and the
    rest still answer. Never raises."""
    lines: List[Dict[str, Any]] = []
    for key, title, read in LINES:
        try:
            state, words = read(biz)
        except Exception as e:  # noqa: BLE001
            if not isinstance(e, Unread):
                logger.warning("move-in ready: %s failed for %s", key, biz.get("id"), exc_info=True)
            state, words = UNKNOWN, UNREAD_WORDS
        lines.append({"key": key, "title": title, "state": state, "words": words})
    tally = Counter(line["state"] for line in lines)
    return {"lines": lines, "total": len(lines), "room_only": list(ROOM_ONLY),
            **{s: tally.get(s, 0) for s in (READY, WATCH, NOT_YET, UNKNOWN)}}
