"""church_duties.py — what each office login DOES, one duty at a time.

Kevin, 2026-11-01 (Love City's office checkup): "we have to either give chief
the ability to make adjustment and help the churches make adjustments like
these or come up with a better way that allows for a general structure plan
and customize roles as well", then "yes the duties part would be great".
The plan is docs/CHURCH_DUTIES.md; this is its step 1.

    an AREA ........ what a login SEES (church_areas: the menu, the walls).
                     Unchanged by anything here
    a DUTY ......... one job a login DOES: the weekly text, the Monday
                     leaders note, the books. CATALOG: its label, its area,
                     whether it's money, its lanes, its day, its training
                     line and what it opens
    a LANE ......... a bundle of duties (STARTER, from the catalog): the
                     office's lanes (church_areas.LANES) and the Executive
                     Pastor, a login whose person holds that role
    a MOVE ......... the church names who does one duty
                     (church_duty_holders). Once any row names who does a
                     duty, the lanes' defaults no longer decide it: it has
                     moved. Every move is logged (church_duty_changes: from,
                     to, by, at) and can be put back

Who holds a duty (holds):
  * the owner and every Admin login hold every duty, money ones too
  * a Manager holds a duty its lane does by default, while nobody has moved
    that duty; once it has moved, only if a row names them
  * a Manager's lane is the one stored on its login (business_users.lane),
    else the lane its picked areas are exactly (church_areas.lane_of); a
    login whose person holds the Executive Pastor role (by its key or the
    catalog's; where the church's leaders map is open, a role the church
    named to oversee the office) is in the Executive Pastor's lane too
  * a money duty is never a Manager's, whatever a row says
  * a Member or a Viewer holds none, and nor does anyone outside a church
  * a read that fails is a 503, never a yes

  GET  /church/duties?business_id=         the catalog and who does each duty
                                           (a manager seat or above)
  PUT  /church/duties/{duty}               {business_id, user_ids} (the owner or
                                           an admin): who does it; [] or null
                                           puts it back to the lanes' defaults
  POST /church/duties/{duty}/undo          {business_id} (the owner or an
                                           admin): puts the last change back

Chief reads and moves duties through the same functions (chief_duties.py:
list_duties reads build(), move_duty and undo_duty call move() and undo()).

The switch, CHURCH_DUTIES (off | owner | on; owner until a Thursday), gates
these routes only, for the login or the church (office_open): with `owner`,
the platform owner's login and the platform owner's own church (Love City:
its admins move a duty, its Managers read the page). holds() answers
whatever it says: it only reads rows an owner or an admin wrote here, and
with none it is the lanes' defaults.

Server-only tables (RLS on, no policies): supabase/APPLY-2026-11-01-church-
duties.sql. Before it is applied, a Manager's holds() is a 503 and my-role
leaves `duties` out; the owner's and the admins' answer reads no table.
"""
from __future__ import annotations

import logging
import os
import re
import time
import uuid
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
from auth_supabase import AuthedUser, UserSession
from business_access import assert_access, business_access
from church_areas import AREAS, AREA_ORDER, KEEPS_ALL, LANES, lane_of

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church", tags=["church"])


# ─── The catalog ──────────────────────────────────────────────────────

# The Executive Pastor is a lane no login is given: it is the person who
# holds the role (Kevin, 2026-11-01: "Jessica will be over the admin team").
EXEC = "executive_pastor"
PSEUDO_LANES: Dict[str, Dict[str, Any]] = {
    EXEC: {"label": "Executive Pastor", "role": "manager",
           "does": "Over the office's lanes: covers any lane's work, gathers the monthly report and reads "
                   "the Monday roll-up. No money"},
}
LANE_KEYS: Tuple[str, ...] = tuple(LANES) + tuple(PSEUDO_LANES)


def _duty(label: str, area: str, lanes: List[str], day: str, does: str, opens: List[str],
          money: bool = False) -> Dict[str, Any]:
    return {"label": label, "area": area, "money": money, "lanes": list(lanes), "day": day, "does": does,
            "opens": list(opens)}


# Love City's office split into the real jobs each admin does (Kevin,
# 2026-11-02: "yes fold it in, and track supplies in tasks"; "churchsavvy is
# shapretta"; "yes churchsavvy for worship team, announcements to shapretta").
# Each lane's section is in the order its week runs. Two things are still
# shared: Sunday's schedule, split by team (serve_schedule is the volunteer
# teams', production_schedule worship and production's), and the week's news
# list, which is the weekly text's (Office & Leadership); the posts and the
# announcements draw from it.
CATALOG: Dict[str, Dict[str, Any]] = {
    # Office & Leadership
    "front_desk": _duty(
        "The front desk", "office", ["office_leadership"], "Mon",
        "Everything that came in over the weekend has an owner, and each new ask, card, email and text gets one "
        "within a day.",
        ["Approvals", "What came in: asks, cards, email and texts"]),
    "leaders_note": _duty(
        "The Monday leaders note", "office", ["office_leadership"], "Mon",
        "Read over the week Chief gathered for the leaders, add a word, and send it on Monday.",
        ["The Monday leaders note"]),
    "meetings": _duty(
        "Meetings and minutes", "office", ["office_leadership"], "Tue, monthly",
        "Set up the huddle, the all-leaders meeting and each board's meeting, and take the attendance and the "
        "minutes.",
        ["Boards and their seats", "Meetings, attendance and minutes"]),
    "decisions": _duty(
        "Decisions to done", "office", ["office_leadership"], "Tue",
        "Each decision from the huddle and the leaders meeting becomes a task with one owner; follow it until it's "
        "done.",
        ["Tasks from the decisions"]),
    "weekly_text": _duty(
        "The weekly text and email", "office", ["office_leadership"], "Wed",
        "Write the church's weekly text and email from the week's news, and send them or schedule them for a day "
        "or a group.",
        ["Announcements by text: send, schedule, to a group", "The church's email", "The week's news list"]),
    "calendar": _duty(
        "The church calendar", "office", ["office_leadership"], "Fri",
        "Next week's services, events and meetings are on the calendar, each with its room.",
        ["The church calendar"]),
    "rooms": _duty(
        "Rooms", "office", ["office_leadership"], "Fri",
        "Every room is booked from one place: leaders send a room request, and the booking goes on the calendar.",
        ["Booking and approving rooms", "The rentals list, without the amounts"]),
    "building": _duty(
        "The building and safety", "office", ["office_leadership"], "weekly",
        "With the facilities lead and the safety officers: what's broken or unsafe has an owner.",
        ["Tasks for the building"]),
    "records": _duty(
        "Records, files and policies", "office", ["office_leadership"], "monthly",
        "The register, the church's files, and its policies (child safety, building use, member privacy) kept "
        "current in Files & policies.",
        ["Files & policies", "Church records"]),
    "chat_rules": _duty(
        "Chat rules", "messages_safety", ["office_leadership"], "as needed",
        "Keep the member chat's rules current: who can message whom, and what gets held.",
        ["The member chat's rules"]),
    "leaders_list": _duty(
        "The leaders list and department sheet", "office", ["office_leadership"], "as needed",
        "Keep the leaders, their roles and the department sheet current, and ask a new leader to take a role.",
        ["Leaders & roles", "The department sheet"]),
    "new_leaders": _duty(
        "Welcoming new leaders", "office", ["office_leadership"], "as needed",
        "Each new leader's role, covenant and first meeting, and their background check asked of Sunday & "
        "Serving.",
        ["Leaders & roles"]),
    "supplies": _duty(
        "Supplies", "office", ["office_leadership"], "as needed",
        "What's low gets counted and ordered, tracked in Tasks.",
        ["Tasks for supplies"]),
    # Kevin, 2026-11-13: "have it where the admins can give them out whoever
    # the church consider there main admin … Naiya would the one who gives out
    # the emails to others". The owner and every Admin hold it too.
    "church_email": _duty(
        "Church email addresses", "office", ["office_leadership"], "as needed",
        "Give each new admin and leader their church email address through Chief, point role addresses like "
        "prayer@ at the right role, and take one back when someone leaves.",
        ["Church email addresses, through Chief", "Email Setup"]),
    # People & Care
    "first_guests": _duty(
        "First-time guests and welcome calls", "people_care", ["people_care"], "Mon",
        "Every first-time guest has a person and a call date on Monday, and the calls are made by Wednesday.",
        ["Follow-up"]),
    "care_visits": _duty(
        "Care and visits", "people_care", ["people_care"], "Tue",
        "The care board: visits, meals, the hospital and the grieving, with the deacons.",
        ["Prayer & care", "The shared care inbox"]),
    "prayer": _duty(
        "Prayer", "people_care", ["people_care"], "weekly",
        "Requests people shared with the prayer team reach the intercessor leader, and each is marked prayed.",
        ["Prayer & care"]),
    "help_requests": _duty(
        "Help requests", "people_care", ["people_care"], "as needed",
        "Each help request gets a call; over the help fund's limit, the treasurer and the pastor approve it.",
        ["Help requests"]),
    "shepherding": _duty(
        "Shepherding", "people_care", ["people_care"], "Thu",
        "Check on the families drifting and the groups who missed weeks, and log each touch.",
        ["Shepherding", "Groups who missed weeks"]),
    "groups": _duty(
        "Groups and classes", "groups_classes", ["people_care"], "Thu",
        "Who missed three weeks, and the Next Step, Leaderschool and Bible study rosters.",
        ["Groups", "Class rosters"]),
    "member_records": _duty(
        "Member records and the directory", "people_care", ["people_care"], "as needed",
        "New members, changes and the directory kept right.",
        ["Members", "The member directory"]),
    # The kids' workers are Sunday & Serving's (serve_schedule); the rooms,
    # check-in and the families' details are People & Care's.
    "kids": _duty(
        "Kids", "kids_youth", ["people_care"], "Sun",
        "Kids check-in, pickup and the rooms open on Sunday, with the families' details right.",
        ["Kids check-in", "Kids rooms", "Approved adults"]),
    "youth": _duty(
        "Youth and Teen Bible Study", "kids_youth", ["people_care"], "weekly",
        "Youth and Teen Bible Study has its leaders, its room and its people.",
        ["Groups"]),
    "devotionals": _duty(
        "Devotionals and the reading plan", "people_care", ["people_care"], "weekly",
        "This week's devotional and reading plan are set.",
        ["Devotionals", "The Bible reading plan"]),
    # Sunday & Serving: the volunteers
    "serve_schedule": _duty(
        "Who serves when", "worship_media", ["sunday_serving"], "Wed",
        "Every spot on the volunteer teams has a yes: greeters, ushers, kids workers, parking, hospitality, "
        "outreach. Worship and production are ChurchSavvy's.",
        ["Who serves when: the volunteer teams"]),
    "serve_teams": _duty(
        "Teams and team leaders", "worship_media", ["sunday_serving"], "monthly",
        "Each volunteer team has a leader and its places.",
        ["Teams"]),
    "new_volunteers": _duty(
        "New volunteers", "worship_media", ["sunday_serving"], "as needed",
        "Each new volunteer is placed on a team, welcomed, and trained.",
        ["Teams"]),
    # Recording a check is this duty's (church_serving); reading who's
    # cleared stays Kids & youth's and People & care's too.
    "background_checks": _duty(
        "Background checks", "kids_youth", ["sunday_serving"], "monthly",
        "Every kids worker and team member who needs one has a current background check.",
        ["Recording background checks", "Check reminders", "The check link and how long a check is good"]),
    "serving_thanks": _duty(
        "Serving hours and thank-yous", "worship_media", ["sunday_serving"], "monthly",
        "Serving hours kept, and each team thanked.",
        ["Serving hours"]),
    "events": _duty(
        "Events and sign-ups", "website_outreach", ["sunday_serving"], "Thu",
        "Each event, from plan to day-of: sign-ups, a room request, and volunteers.",
        ["Event sign-ups", "A room request for the event"]),
    "outreach_nights": _duty(
        "Outreach nights", "website_outreach", ["sunday_serving"], "Thu",
        "Love Works and City Serve nights have their volunteers and a room.",
        ["Who serves when", "A room request for the night"]),
    "attendance": _duty(
        "Sunday attendance", "worship_media", ["sunday_serving"], "Sun",
        "Record Sunday's count before the day is out.",
        ["Sunday attendance"]),
    # Media & Communications: ChurchSavvy and production
    "sunday_plan": _duty(
        "The order of service", "worship_media", ["media_comms"], "Tue",
        "Next Sunday's order is set with the worship pastor in ChurchSavvy.",
        ["ChurchSavvy planning: the order of service"]),
    "production_schedule": _duty(
        "Worship and production teams", "worship_media", ["media_comms"], "Wed",
        "The worship and production teams' Sunday spots have a yes, with the worship pastor.",
        ["Who serves when: the worship and production teams"]),
    "churchsavvy_team": _duty(
        "ChurchSavvy's team", "worship_media", ["media_comms"], "as needed",
        "Who's on ChurchSavvy's worship and production team, and their parts.",
        ["Who's on ChurchSavvy's team"]),
    "announcements": _duty(
        "Sunday announcements", "worship_media", ["media_comms"], "Fri",
        "Sunday's announcements are set for the screens and the bulletin.",
        ["Sunday's announcements"]),
    "stream": _duty(
        "The livestream", "worship_media", ["media_comms"], "Sat, Sun",
        "Test the stream on Saturday, run it from the booth on Sunday, and file the replay.",
        ["The livestream", "The booth", "The media library"]),
    "sermons": _duty(
        "Sermon up", "worship_media", ["media_comms"], "Mon",
        "Sunday's sermon is posted with its notes.",
        ["Sermons"]),
    "clips": _duty(
        "Clips and covers", "website_outreach", ["media_comms"], "Mon",
        "Cut Sunday's best clips, make their covers and post them.",
        ["Posting clips", "Making covers"]),
    "posts": _duty(
        "Posts", "website_outreach", ["media_comms"], "Thu",
        "Plan the week's posts on the marketing desk and send them out.",
        ["The marketing desk", "Posts", "Chief's post actions"]),
    "flyers": _duty(
        "Flyers and graphics", "website_outreach", ["media_comms"], "Thu",
        "The weekend's flyers and graphics are made in Create.",
        ["Create: flyers and graphics"]),
    "website": _duty(
        "The website", "website_outreach", ["media_comms"], "as needed",
        "Keep the website and its events page current.",
        ["The site builder", "The events page"]),
    # The Executive Pastor
    "monthly_report": _duty(
        "The monthly report", "office", [EXEC], "first Monday",
        "Gather the month from each lane, without the money, into one report for the pastor.",
        ["The monthly report from the lanes, without the money"]),
    "oversee_lanes": _duty(
        "Over the lanes", "office", [EXEC], "Mon",
        "Look over each lane's week and the Monday roll-up, and step in where one is behind.",
        ["See as each lane", "The Monday team roll-up"]),
    # The Treasurer: money, so only the owner and the admins ever hold these.
    "deposit": _duty(
        "The Sunday deposit", "giving_money", ["treasurer"], "Sun, Mon",
        "Close each service's count and match it to the deposit that carried it.",
        ["Service counts", "The Sunday deposit match"], money=True),
    "books": _duty(
        "The books", "giving_money", ["treasurer"], "Mon, monthly",
        "Match the bank, reconcile the month, and keep the categories and statements in order.",
        ["Bank matching", "Reconciling", "Categories", "Statements"], money=True),
    "pay": _duty(
        "Bills and pay-backs", "giving_money", ["treasurer"], "Wed",
        "Pay the bills that are due and say yes or no to each pay-back and check request.",
        ["Bills", "Pay-backs", "Check requests to approve"], money=True),
    "store": _duty(
        "Store orders", "giving_money", ["treasurer"], "as needed",
        "Fill the store's orders, and refund one when it's asked for.",
        ["Store orders"], money=True),
}

# Each lane's default duties: the general structure a church starts from.
STARTER: Dict[str, List[str]] = {ln: [k for k, d in CATALOG.items() if ln in d["lanes"]] for ln in LANE_KEYS}
# The Executive Pastor is over every lane, so she covers any lane's work by
# default (the leadership plan Kevin approved 2026-10-27: "Manager login with
# every area picked"), never money. A duty moved to named logins is theirs.
STARTER[EXEC] = [k for k, d in CATALOG.items() if not d["money"]]
# The Executive Pastor's own: overseeing the lanes and gathering their
# report. They open other logins' weeks, so a Manager never gets them from
# its areas (_area_duties), only from the role or a move.
OVERSIGHT: FrozenSet[str] = frozenset(k for k, d in CATALOG.items() if d["lanes"] == [EXEC])

ALL: FrozenSet[str] = frozenset(CATALOG)
MAX_HOLDERS = 12
NOT_CHURCH = "Duties are for a church's office"


def lane_label(key: str) -> str:
    spec = LANES.get(key) or PSEUDO_LANES.get(key) or {}
    return spec.get("label") or key


def catalog_view() -> List[Dict[str, Any]]:
    return [{"key": k, **d, "area_label": AREAS[d["area"]]["label"],
             "lane_labels": [lane_label(ln) for ln in d["lanes"]]} for k, d in CATALOG.items()]


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_DUTIES") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_to(user: AuthedUser) -> bool:
    """The duties, for this login: on, or (owner) the platform owner's own login."""
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        owner = (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()
        return (getattr(user, "email", None) or "").strip().lower() == owner
    return False


def church_open(biz: Any) -> bool:
    """The duties, for this church: on, or (owner) the platform owner's own church (member_asks.platform_church,
    as church_map.church_open). An id that isn't one is a no."""
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        import member_asks
        return member_asks.platform_church(biz.get("id") if isinstance(biz, dict) else biz)
    return False


def office_open(user: AuthedUser, biz: Any) -> bool:
    """What the duties routes, Chief's duty verbs and an ask's duty move follow: the login (open_to) or the
    church (church_open), as church_map.office_open opens the map. With `owner`, Love City's own admins move
    its duties too; the seats still decide who may (the owner or an admin moves one, money only to a money
    login), and every other church stays closed."""
    return open_to(user) or church_open(biz)


def _gate(user: AuthedUser, biz: Any) -> None:
    if not office_open(user, biz):
        raise HTTPException(404, "Not Found")


# ─── Reads ────────────────────────────────────────────────────────────

def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _need(path: str) -> List[Dict[str, Any]]:
    """A read that must answer. One that failed is a 503: an unread row
    would otherwise read as "nobody was given it", which is a yes for a lane."""
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, "Who does what couldn't be read just now. Try again.")
    return rows


def _escape_ilike(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _business(biz: str) -> Optional[Dict[str, Any]]:
    rows = _need(f"/businesses?id=eq.{_q(biz)}&select=id,name,type,owner_id,settings&limit=1")
    return rows[0] if rows else None


def _is_church(business: Optional[Dict[str, Any]]) -> bool:
    import church_follow_up as cfu
    return bool(business) and cfu.is_church(business)


_SEAT_FIELDS = "user_id,role,lane,areas,contact_id,invited_email,name"


def _seat(biz: str, uid: str) -> Optional[Dict[str, Any]]:
    rows = _need(f"/business_users?business_id=eq.{_q(biz)}&user_id=eq.{_q(uid)}&status=eq.active"
                 f"&select={_SEAT_FIELDS}&limit=1")
    return rows[0] if rows else None


def _seats(biz: str) -> List[Dict[str, Any]]:
    return [s for s in _need(f"/business_users?business_id=eq.{_q(biz)}&status=eq.active"
                             f"&select={_SEAT_FIELDS}&limit=200") if s.get("user_id")]


def _moved(biz: str) -> Dict[str, List[str]]:
    """duty → the logins it was moved to. A duty with no rows isn't here:
    its lanes' defaults decide it."""
    rows = _need(f"/church_duty_holders?business_id=eq.{_q(biz)}&select=duty,user_id&limit=2000")
    out: Dict[str, List[str]] = {}
    for r in rows:
        if r.get("duty") and r.get("user_id"):
            out.setdefault(str(r["duty"]), []).append(str(r["user_id"]))
    return {k: sorted(set(v)) for k, v in out.items()}


def _seat_lane(seat: Dict[str, Any]) -> Optional[str]:
    """The lane a login was given (stored), else the lane its picked areas
    are exactly. Chief's guess at a login's areas never makes a lane: a
    duty is something the church said, not something Chief guessed."""
    stored = seat.get("lane")
    if stored in LANES:
        return stored
    areas = seat.get("areas")
    return lane_of(seat.get("role"), areas if isinstance(areas, list) else None)


def overseer_keys(biz: str) -> List[str]:
    """The keys of the roles whose holders oversee the office: where the
    church's leaders map is open and names them (office_overseer_roles,
    docs/CHURCH_LEADERS_MAP.md §3, PR 7; none named is nobody), those; else
    the Executive Pastor role, by its key or the catalog's. A failed read,
    the map's too, is a 503."""
    import church_map
    m = church_map.opened(biz)
    if m is None:
        raise HTTPException(503, "Who does what couldn't be read just now. Try again.")
    named = church_map.picked(m, "office_overseer_roles") if m else None
    if named is not None:
        return named
    defs = _need(f"/church_role_defs?business_id=eq.{_q(biz)}&status=eq.active"
                 f"&or=(key.eq.{EXEC},catalog_key.eq.{EXEC})&select=key&limit=50")
    return sorted({str(d["key"]) for d in defs if d.get("key")})


def _exec_users(biz: str, seats: Iterable[Dict[str, Any]]) -> Set[str]:
    """Which of these logins are the Executive Pastor: their person holds
    a role that oversees the office (overseer_keys) and has said yes to it.
    A login tied to its person (business_users.contact_id) is only that
    person; one that isn't is found by its email, and only when the email
    names exactly one of the church's people (or the one whose first name
    the login gave)."""
    seats = list(seats)
    b = _q(biz)
    keys = overseer_keys(biz)
    if not keys or not seats:
        return set()
    holders = _need(f"/church_leader_roles?business_id=eq.{b}&status=eq.active"
                    f"&role=in.({','.join(_q(k) for k in keys)})&select=contact_id&limit=50")
    ids = {str(h["contact_id"]) for h in holders if h.get("contact_id")}
    out: Set[str] = set()
    if not ids:
        return out
    for s in seats:
        uid = str(s.get("user_id") or "")
        if s.get("contact_id"):
            if str(s["contact_id"]) in ids:
                out.add(uid)
            continue
        email = (s.get("invited_email") or "").strip().lower()
        if not email or "@" not in email:
            continue
        people = [c for c in _need(f"/contacts?business_id=eq.{b}&email=ilike.{_q(_escape_ilike(email))}"
                                   "&select=id,name,email&limit=10")
                  if (c.get("email") or "").strip().lower() == email]
        if len(people) > 1:
            first = _plain(s.get("name")).split(" ")[0].lower()
            people = [c for c in people if first and _plain(c.get("name")).split(" ")[0].lower() == first]
        if len(people) == 1 and str(people[0].get("id")) in ids:
            out.add(uid)
    return out


# ─── Who holds what ───────────────────────────────────────────────────

# holds() runs on every gated job and my-role on every app load: a login's
# duties are kept a minute per replica, and a change saved here clears the
# church's at once.
CACHE_SECONDS = 60
_CACHE: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}
# my-role's read that failed (the tables before their migration, a database
# hiccup) isn't tried again on every app load: it waits this long. holds()
# never uses it, so a job gate still asks, and still answers 503.
FAILED_SECONDS = 45
_FAILED: Dict[Tuple[str, str], float] = {}


def _forget(biz: str) -> None:
    for k in [k for k in _CACHE if k[0] == str(biz)]:
        _CACHE.pop(k, None)
    for k in [k for k in _FAILED if k[0] == str(biz)]:
        _FAILED.pop(k, None)
    import church_map_asks          # a duty that moved changes a login's work: its check is due again
    church_map_asks.forget(biz)


def _prune(now: float) -> None:
    """Drop what's past its minute, so a long-lived replica keeps only the
    logins it has seen lately."""
    for k in [k for k, (at, _) in _CACHE.items() if now - at >= CACHE_SECONDS]:
        _CACHE.pop(k, None)
    for k in [k for k, at in _FAILED.items() if now - at >= FAILED_SECONDS]:
        _FAILED.pop(k, None)


def _area_duties(biz: str, uid: str, role: Optional[str]) -> FrozenSet[str]:
    """A Manager no lane names: the non-money duties in the areas it works,
    as each job's area check decided before duties (church_leaders_note's
    _office, church_spaces'). Its view is the church's pick, else Chief's
    guess; the whole church, or Who sees what not on, is every duty. A view
    that can't be read is a 503, never a yes. Overseeing the lanes and
    gathering their report (OVERSIGHT) never come from areas: they open
    other logins' weeks, so only the Executive Pastor's role or a move
    names who does them."""
    import church_areas
    every = frozenset(k for k, d in CATALOG.items() if not d["money"] and k not in OVERSIGHT)
    if church_areas.mode() != "on":
        return every
    view = church_areas.my_areas(biz, uid, role)
    if view is None:
        raise HTTPException(503, "Your areas couldn't be read just now. Try again.")
    areas = view.get("areas")
    if areas is None:
        return every
    return frozenset(k for k in every if CATALOG[k]["area"] in areas)


def _manager_duties(lanes: Set[str], uid: str, moved: Dict[str, List[str]],
                    by_area: Optional[FrozenSet[str]] = None) -> FrozenSet[str]:
    out = set()
    for key, d in CATALOG.items():
        if d["money"]:
            continue
        if key in moved:
            if uid in moved[key]:
                out.add(key)
        elif any(key in STARTER.get(ln, ()) for ln in lanes) or (by_area is not None and key in by_area):
            out.add(key)
    return frozenset(out)


def standing(business_id: str, user_id: str) -> Dict[str, Any]:
    """One login's standing for duties: {church, role, lanes, duties}.
    Raises 503 when a read fails."""
    biz, uid = str(business_id), str(user_id)
    key = (biz, uid)
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    b = _business(biz)
    church = _is_church(b)
    role: Optional[str] = None
    seat: Optional[Dict[str, Any]] = None
    lanes: Set[str] = set()
    if b and str(b.get("owner_id")) == uid:
        role = "owner"
    else:
        seat = _seat(biz, uid) if b else None
        role = (seat or {}).get("role") or None
        if seat and church and role == "manager":
            ln = _seat_lane(seat)
            if ln:
                lanes.add(ln)
    if role in KEEPS_ALL:
        duties = ALL
    elif role == "manager" and church:
        moved = _moved(biz)
        if uid in _exec_users(biz, [seat]):
            lanes.add(EXEC)
        # No lane at all: the areas it works decide, as before duties.
        by_area = None if lanes else _area_duties(biz, uid, role)
        duties = _manager_duties(lanes, uid, moved, by_area)
    else:
        duties = frozenset()
    out = {"church": church, "role": role, "lanes": sorted(lanes), "duties": duties}
    now = time.monotonic()
    _prune(now)
    _CACHE[key] = (now, out)
    return out


def _known(duty: str) -> Dict[str, Any]:
    if duty not in CATALOG:
        raise ValueError(f"{duty!r} isn't one of church_duties.CATALOG")
    return CATALOG[duty]


def holds(business_id: str, user: AuthedUser, duty: str) -> bool:
    """Whether this login does this duty at this church. The owner and the
    admins always; a Manager by its lane (the Executive Pastor's covers every
    non-money duty), or with no lane by the areas it works, until the duty
    moves, then by a row naming it; never a money duty for a Manager. A
    failed read is a 503."""
    _known(duty)
    return duty in standing(str(business_id), str(user.id))["duties"]


def _join(names: List[str]) -> str:
    names = [n for n in names if n]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _first(name: str) -> str:
    name = _plain(name)
    return name if "@" in name else name.split(" ")[0]


def refusal(business_id: str, duty: str) -> str:
    """What a login that doesn't do this duty is told: whose job it is, and
    who can give it to them. A read that fails says it plainly, without names."""
    d = _known(duty)
    label = d["label"]
    if d["money"]:
        return f"“{label}” is a money job, so it stays with the owner and the admins."
    tail = " The owner or an admin can give it to you in Logins & areas."
    try:
        moved = _moved(str(business_id))
        if duty in moved:
            b = _business(str(business_id)) or {}
            names = _names(str(business_id), b, _seats(str(business_id)))
            owner = str(b.get("owner_id") or "")
            # A login by its first name; the owner by the name the church calls them.
            who = _join([names[u] if u == owner else _first(names[u]) for u in moved[duty] if names.get(u)])
            return f"“{label}” is {who}'s job here.{tail}" if who else f"“{label}” is someone else's job here.{tail}"
    except HTTPException:
        return f"“{label}” is someone else's job here.{tail}"
    if d["lanes"] == [EXEC]:
        return f"“{label}” is the Executive Pastor's job here.{tail}"
    lanes = [lane_label(ln) for ln in d["lanes"]]
    whose = f"the {_join(lanes)} lane's" if len(lanes) == 1 else f"the {_join(lanes)} lanes'"
    return f"“{label}” is {whose} job here.{tail}"


def require(business_id: str, user: AuthedUser, duty: str) -> None:
    """403 unless this login does this duty, naming whose job it is."""
    if not holds(business_id, user, duty):
        raise HTTPException(403, refusal(business_id, duty))


def does_job(business_id: str, user_id: Any, duty: str, business: Optional[Dict[str, Any]]) -> Optional[str]:
    """For a job gate that was the owner's alone (or the owner's and the
    admins'), step 2b: in a church, the login's role when it does this job:
    the owner, an Admin, or a Manager that holds the duty. A Manager that
    doesn't is refused (403) with whose job it is. None for anyone else there
    (no seat, a Member, a Viewer) and for any business that isn't a church,
    so the gate's own rule and its own refusal stand. `business` is the row
    the gate already read (type and owner_id). A failed read is a 503."""
    _known(duty)
    if not business or not _is_church(business):
        return None
    biz, uid = str(business_id), str(user_id or "")
    if not uid:
        return None
    if str(business.get("owner_id") or "") == uid:
        return "owner"
    s = standing(biz, uid)
    if duty in s["duties"]:
        return s["role"]
    if s["role"] == "manager":
        raise HTTPException(403, refusal(biz, duty))
    return None


def holders_of(business_id: str, duty: str) -> List[str]:
    """Every login that does this duty at this church today, the owner
    first: the owner, each Admin login, and each Manager holds() says yes
    for. [] for a business that isn't a church. A failed read is a 503."""
    _known(duty)
    biz = str(business_id)
    b = _business(biz)
    if not _is_church(b):
        return []
    owner = str(b.get("owner_id") or "")
    out = [owner] if owner else []
    import church_map
    with church_map.once():         # each Manager's standing reads the map: once for them all
        for s in _seats(biz):
            uid = str(s["user_id"])
            if uid in out or s.get("role") not in ("admin", "manager"):
                continue
            if s.get("role") == "admin" or duty in standing(biz, uid)["duties"]:
                out.append(uid)
    return out


def manager_holders(business_id: str, duty: str) -> List[str]:
    """The Manager logins that do this duty at this church today (holds()
    says yes), without the owner and the admins: who the Executive Pastor's
    Monday roll-up goes to (church_team_week). [] for a business that isn't a
    church. A failed read is a 503."""
    _known(duty)
    biz = str(business_id)
    if not _is_church(_business(biz)):
        return []
    import church_map
    with church_map.once():
        return [str(s["user_id"]) for s in _seats(biz)
                if s.get("role") == "manager" and duty in standing(biz, str(s["user_id"]))["duties"]]


def duties_of(business_id: str, user_id: str, role: Optional[str]) -> Optional[List[str]]:
    """This login's duty keys, in the catalog's order, for /team/my-role:
    every key for the owner and the admins. None when they don't apply (not
    a church, or no standing here) and when a read fails, which then isn't
    tried again for FAILED_SECONDS: my-role runs on every app load, and the
    app shows what it showed before."""
    if not role:
        return None
    key = (str(business_id), str(user_id))
    failed = _FAILED.get(key)
    if failed is not None and time.monotonic() - failed < FAILED_SECONDS:
        return None
    try:
        s = standing(*key)
    except HTTPException:
        _FAILED[key] = time.monotonic()
        print(f"[church_duties] my-role duties not read for {key[0]}; trying again in {FAILED_SECONDS}s")
        return None
    _FAILED.pop(key, None)
    if not s["church"] or not s["role"]:
        return None
    return [k for k in CATALOG if k in s["duties"]]


# ─── Names ────────────────────────────────────────────────────────────

def _names(biz: str, business: Dict[str, Any], seats: List[Dict[str, Any]]) -> Dict[str, str]:
    """user id → the name the church knows the login by: its person's, else
    the name it gave, else its email. The owner by the business's settings."""
    ids = sorted({str(s["contact_id"]) for s in seats if s.get("contact_id")})
    people: Dict[str, str] = {}
    if ids:
        rows = _need(f"/contacts?business_id=eq.{_q(biz)}&id=in.({','.join(_q(i) for i in ids)})"
                     "&select=id,name&limit=200")
        people = {str(r["id"]): _plain(r.get("name")) for r in rows}
    out = {str(s["user_id"]): (people.get(str(s.get("contact_id") or "")) or _plain(s.get("name"))
                               or (s.get("invited_email") or "").strip() or "An office login") for s in seats}
    settings = business.get("settings") if isinstance(business.get("settings"), dict) else {}
    if business.get("owner_id"):
        out[str(business["owner_id"])] = _plain(settings.get("practitioner_name")) or "The account owner"
    return out


# ─── The page ─────────────────────────────────────────────────────────

_CHANGE_FIELDS = "id,duty,from_holders,to_holders,changed_by,changed_at,undoes,undone_at"


def _changes(biz: str, duty: Optional[str] = None) -> List[Dict[str, Any]]:
    one = f"&duty=eq.{_q(duty)}" if duty else ""
    rows = _need(f"/church_duty_changes?business_id=eq.{_q(biz)}{one}&select={_CHANGE_FIELDS}"
                 "&order=changed_at.desc&limit=500")
    # Newest first, whatever order the read came back in.
    return sorted(rows, key=lambda r: str(r.get("changed_at") or ""), reverse=True)


def _undoable(changes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The change an undo puts back: the newest one that isn't itself an
    undo and hasn't been put back."""
    return next((c for c in changes if not c.get("undoes") and not c.get("undone_at")), None)


def build(business: Dict[str, Any]) -> Dict[str, Any]:
    """The catalog for one church, and who does each duty today, with the
    map read once for all its logins (church_map.once)."""
    import church_map
    with church_map.once():
        return _build(business)


def _build(business: Dict[str, Any]) -> Dict[str, Any]:
    biz = str(business["id"])
    seats = _seats(biz)
    moved = _moved(biz)
    changes = _changes(biz)
    names = _names(biz, business, seats)
    owner = str(business.get("owner_id") or "")
    lanes_of: Dict[str, Set[str]] = {}
    for s in seats:
        ln = _seat_lane(s) if s.get("role") in ("manager", "admin") else None
        lanes_of[str(s["user_id"])] = {ln} if ln else set()
    for uid in _exec_users(biz, [s for s in seats if s.get("role") == "manager"]):
        lanes_of[uid].add(EXEC)
    role_of = {str(s["user_id"]): s.get("role") for s in seats}
    # What each login does until a duty moves: its lanes' starter duties (the
    # Executive Pastor's are every non-money one), else, for a Manager no lane
    # names, the duties in the areas it works. The same defaults holds() uses.
    default_of: Dict[str, Set[str]] = {}
    for uid, ln in lanes_of.items():
        if ln:
            default_of[uid] = {k for one in ln for k in STARTER.get(one, ())}
        elif role_of.get(uid) == "manager":
            default_of[uid] = set(_area_duties(biz, uid, "manager"))
        else:
            default_of[uid] = set()

    def person(uid: str, money: bool) -> Dict[str, Any]:
        # `active`: whether holds() says yes for them. A login that left the
        # office, or a Manager named for a money job, is listed but doesn't.
        role = "owner" if uid == owner else role_of.get(uid)
        return {"user_id": uid, "name": names.get(uid) or "Someone who has left the office",
                "role": role, "active": role in KEEPS_ALL or (role == "manager" and not money)}

    duties = []
    for d in catalog_view():
        key = d["key"]
        if key in moved:
            holders = [person(u, d["money"]) for u in moved[key]]
        else:
            holders = [person(uid, d["money"]) for uid in lanes_of
                       if key in default_of.get(uid, ()) and (role_of.get(uid) == "admin" or not d["money"])]
        mine = [c for c in changes if c.get("duty") == key]
        last = mine[0] if mine else None
        # Moved to logins that have all left (or can't do it now): the lanes
        # don't take it back by themselves, so the page says it needs someone.
        duties.append({**d, "follows_lanes": key not in moved, "holders": holders,
                       "needs_someone": key in moved and not any(h["active"] for h in holders),
                       "last_change": ({"at": last.get("changed_at"), "by": names.get(str(last.get("changed_by") or ""), ""),
                                        "undo": bool(last.get("undoes"))} if last else None),
                       "can_undo": _undoable(mine) is not None})
    rank = {"owner": 0, "admin": 1, "manager": 2, "member": 3, "viewer": 4}
    logins = [{"user_id": owner, "name": names.get(owner, ""), "role": "owner", "lanes": [], "money": True}] if owner else []
    logins += sorted(({"user_id": str(s["user_id"]), "name": names.get(str(s["user_id"]), ""), "role": s.get("role"),
                       "lanes": sorted(lanes_of.get(str(s["user_id"])) or []), "money": s.get("role") == "admin"}
                      for s in seats if str(s["user_id"]) != owner),
                     key=lambda x: (rank.get(x["role"] or "", 9), x["name"].lower()))
    return {
        "duties": duties,
        "logins": logins,
        "lanes": [{"key": k, "label": lane_label(k), "duties": STARTER[k]} for k in LANE_KEYS],
        "always": "The owner and every Admin login do every duty, money ones too.",
        "needs_someone": [d["key"] for d in duties if d["needs_someone"]],
        "area_order": list(AREA_ORDER),
    }


# ─── Routes ───────────────────────────────────────────────────────────

@router.get("/duties")
def list_duties(business_id: str, session: UserSession = Depends(sb_clients.authed_request),
                biz: Dict[str, Any] = Depends(business_access("manager"))):
    _gate(session.user, biz)
    if not _is_church(biz):
        raise HTTPException(404, NOT_CHURCH)
    return build(biz)


def _uuid(v: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(v or "")))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} isn't valid")


def _church_for_change(body: Dict[str, Any], user: AuthedUser, duty: str) -> Tuple[str, Dict[str, Any]]:
    """The church a change is for, and the owner or an admin making it."""
    _gate(user, (body or {}).get("business_id"))
    biz = _uuid((body or {}).get("business_id"), "church")
    assert_access(biz, user, "admin")
    if duty not in CATALOG:
        raise HTTPException(404, "That isn't one of the duties")
    business = _business(biz)
    if not _is_church(business):
        raise HTTPException(404, NOT_CHURCH)
    return biz, business


def _why_not(business: Dict[str, Any], seats: Dict[str, Dict[str, Any]], uid: str, duty: str) -> Optional[str]:
    """Why this login can't be given this duty, or None when it can: the
    owner and the admins can hold any; a Manager any but money; anyone
    else, or a login that isn't on the church, none."""
    if uid == str(business.get("owner_id") or ""):
        return None
    seat = seats.get(uid)
    if not seat:
        return "That login isn't on this church's office."
    role = seat.get("role")
    if CATALOG[duty]["money"] and role != "admin":
        return f"“{CATALOG[duty]['label']}” is a money job: only the owner or an Admin login can do it."
    if role not in ("admin", "manager"):
        return "Give it to a Manager or an Admin login. A Member or Viewer login doesn't do office jobs."
    return None


def _check(biz: str, business: Dict[str, Any], user_ids: List[str], duty: str) -> Optional[str]:
    if not user_ids:
        return None
    rows = _need(f"/business_users?business_id=eq.{_q(biz)}&status=eq.active"
                 f"&user_id=in.({','.join(_q(u) for u in user_ids)})&select=user_id,role&limit=50")
    seats = {str(r["user_id"]): r for r in rows if r.get("user_id")}
    return next((why for why in (_why_not(business, seats, u, duty) for u in user_ids) if why), None)


def _write(biz: str, duty: str, user_ids: List[str], by: str, undoes: Optional[str] = None) -> Dict[str, Any]:
    """Who does one duty, and its log row, in one transaction
    (church_duty_set): the holders it no longer names go, the new ones come
    with who gave it and when, and the row says from, to, by and at."""
    saved = sb_clients.sb_post_as_service("/rpc/church_duty_set", {
        "p_business_id": biz, "p_duty": duty, "p_user_ids": user_ids, "p_by": by, "p_undoes": undoes})
    if isinstance(saved, list):
        saved = saved[0] if saved else None
    if not isinstance(saved, dict) or not saved.get("id"):
        raise HTTPException(503, "That didn't save. Try again.")
    _forget(biz)
    return saved


def _result(duty: str, holders: List[str], change: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {"ok": True, "duty": duty, "holders": holders, "follows_lanes": not holders,
            "changed": change is not None, "change": change}


# ─── Moving and putting back: the routes' and Chief's one code path ───

def move(business: Dict[str, Any], duty: str, user_ids: List[Any], by: str) -> Dict[str, Any]:
    """Name who does one duty at this church: the PUT and Chief's move_duty
    (chief_duties). `business` is the church's row and `by` the owner or an
    admin making the change; each caller checked both. [] puts the duty back
    to its lanes' defaults. Refused (400): more than MAX_HOLDERS, a login id
    that isn't valid, or a login that can't hold it (_why_not). The same
    names again change nothing and log nothing. A read or a save that fails
    is a 503."""
    _known(duty)
    if len(user_ids) > MAX_HOLDERS:
        raise HTTPException(400, f"Name up to {MAX_HOLDERS} logins, or none to follow the lanes")
    biz = str(business["id"])
    ids = sorted({_uuid(u, "login") for u in user_ids})
    why = _check(biz, business, ids, duty)
    if why:
        raise HTTPException(400, why)
    if _moved(biz).get(duty, []) == ids:
        return _result(duty, ids, None)
    return _result(duty, ids, _write(biz, duty, ids, str(by)))


def undo(business: Dict[str, Any], duty: str, by: str, change_id: Optional[str] = None) -> Dict[str, Any]:
    """Put the last change to one duty back (the undo route and Chief's
    undo_duty); again puts back the one before. With `change_id`, only while
    that change is still the one an undo puts back (409 once another came
    after it). Nothing to put back is a 404; a login it would hand the duty
    back to that can't hold it now is a 409."""
    _known(duty)
    biz = str(business["id"])
    last = _undoable(_changes(biz, duty))
    if not last:
        raise HTTPException(404, f"Nothing to put back for “{CATALOG[duty]['label']}”.")
    if change_id and str(last.get("id")) != str(change_id):
        raise HTTPException(409, f"“{CATALOG[duty]['label']}” has changed again since then, so that change "
                                 "isn't the one to put back now. Say who does it instead.")
    was = last.get("from_holders")
    restore = sorted({str(u) for u in was}) if isinstance(was, list) else []
    why = _check(biz, business, restore, duty)
    if why:
        raise HTTPException(409, f"That can't be put back: {why} Name who does it instead.")
    return _result(duty, restore, _write(biz, duty, restore, str(by), undoes=str(last["id"])))


@router.put("/duties/{duty}")
def give_duty(duty: str, body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """Name who does one duty. [] or null puts it back to the lanes'
    defaults. The owner or an admin; a money duty only to the owner or an
    Admin login; only logins on this church's office."""
    user = session.user
    body = body or {}
    _, business = _church_for_change(body, user, duty)
    raw = body.get("user_ids")
    if raw is None:
        raw = []
    if not isinstance(raw, list) or len(raw) > MAX_HOLDERS:
        raise HTTPException(400, f"Name up to {MAX_HOLDERS} logins, or none to follow the lanes")
    return move(business, duty, raw, str(user.id))


@router.post("/duties/{duty}/undo")
def undo_duty(duty: str, body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """Put the last change to one duty back. Again puts back the one before."""
    user = session.user
    _, business = _church_for_change(body or {}, user, duty)
    return undo(business, duty, str(user.id))
