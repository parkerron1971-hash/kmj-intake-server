"""church_startup.py — a first assignment (docs/CHURCH_ASSIGNMENTS.md).

Kevin, 2026-11-11: "lets build what is missing". Every office login has its
duties and a week by day, but nobody handed anyone the work that comes
before the weekly job: what to gather so the job has something to run on.
This is that list, for any church.

    TEMPLATES ...... [{key, duty, title, done_when, week (1-4), check}]: the
                     office's items by church_duties.CATALOG duty (one to three
                     a duty, none for a duty with nothing to gather, never a
                     money duty), and the leaders' by the role switches they
                     hold (church_map.can): `lead` and `oversee`. General
                     words, never a church's names or a title word
    for_login() .... the items for the duties a login does of its own: its
                     lane's (stored, or its areas'), what was moved to it by
                     name, and for the Executive Pastor's lane only its own
                     two (OVERSIGHT), never the whole office it covers; the
                     owner and the Admins, their stored lane's and what was
                     moved to them. Never a money duty
    for_person() ... the items for the switches one of the church's people
                     holds: a role that leads (or a group they lead), a role
                     that oversees
    start() ........ makes the missing items as tasks handed to them
                     (handed_by the one starting it, startup_key, duty,
                     done_when, check_key, due the church's today + 7 x week);
                     once per person per key (tasks_startup_once), so a second
                     start makes only what's new and says how many it skipped

A church's own list is its rows (tasks): it changes, adds or takes back any
item like any other assignment. The checks are church_work_checks'.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import HTTPException

import church_over as co
import sb_clients

LEAD, OVERSEE = "lead", "oversee"
SWITCH_LABEL = {LEAD: "Leading", OVERSEE: "Overseeing"}
UNSAVED = "That didn't save. Try again."


def _t(key: str, duty: str, week: int, title: str, done_when: str, check: Optional[str] = None) -> Dict[str, Any]:
    return {"key": key, "duty": duty, "week": week, "title": title, "done_when": done_when, "check": check}


TEMPLATES: List[Dict[str, Any]] = [
    # Office & Leadership
    _t("rooms.listed", "rooms", 1, "Every room in the system",
       "Each room the church uses is listed with its size.", "rooms_listed"),
    _t("meetings.set_up", "meetings", 1, "The staff huddle and the leaders meeting set up",
       "Both are meetings in the system with their people, so their minutes and decisions have a home."),
    _t("calendar.eight_weeks", "calendar", 2, "The next 8 weeks on the calendar",
       "Every service, event and meeting for the next eight weeks is on the calendar.", "calendar_8_weeks"),
    _t("records.policies", "records", 3, "The church's policies in Files & policies",
       "Child safety, building use and member privacy are each in Files & policies."),
    _t("leaders_list.departments", "leaders_list", 3, "Every department has a leader",
       "The department sheet shows no department without a leader. Ask; the pastors decide who.",
       "departments_led"),
    _t("weekly_text.first", "weekly_text", 4, "The week's news list and the first weekly text",
       "The first weekly text goes out from the week's news.", "weekly_text"),
    # People & Care
    _t("first_guests.callers", "first_guests", 1, "Every first-time guest has a caller",
       "Nobody in follow-up is left without a person and a call date.", "follow_up_no_one"),
    _t("groups.leaders", "groups", 1, "Every group has a leader",
       "The Groups area shows no group without one.", "groups_led"),
    _t("member_records.reachable", "member_records", 2, "Member records can be reached",
       "No member is missing both a phone number and an email."),
    _t("shepherding.families", "shepherding", 3, "Every member family has a shepherd",
       "Shepherding shows no family without one."),
    _t("kids.release", "kids", 3, "The kids rooms and each child's approved adults",
       "Sunday check-in can release every child to an adult on their list."),
    _t("devotionals.next_month", "devotionals", 4, "Next month's devotional and reading plan set",
       "Next month has its devotional and its readings."),
    # Sunday & Serving
    _t("serve_teams.leaders", "serve_teams", 1, "Every volunteer team has a leader",
       "Each volunteer team is in the system with its leader and its places.", "serve_teams_led"),
    _t("background_checks.kids", "background_checks", 2, "Every kids worker has a background check date",
       "The Kids area shows no worker without one.", "kids_checked"),
    _t("serve_schedule.four_sundays", "serve_schedule", 3, "Spots filled for the next four Sundays",
       "Every place on the volunteer teams has a yes, four Sundays out."),
    _t("events.next_two", "events", 4, "The next two events have sign-ups and a room",
       "Each has its sign-up page and its room request."),
    _t("attendance.weekly", "attendance", 4, "Sunday's count recorded every week",
       "Each Sunday's attendance is in by Sunday night."),
    # Media & Communications
    _t("churchsavvy_team.joined", "churchsavvy_team", 1, "ChurchSavvy's team has joined",
       "Everyone invited to ChurchSavvy's worship and production team has joined.", "churchsavvy_joined"),
    _t("sermons.six_sundays", "sermons", 2, "The last six Sundays' sermons posted",
       "Each of the last six Sundays has its sermon posted.", "sermons_6"),
    _t("sunday_plan.next_two", "sunday_plan", 2, "The next two Sundays' order of service",
       "Both are set in ChurchSavvy with the worship leader."),
    _t("posts.two_weeks", "posts", 3, "Two weeks of posts planned",
       "The marketing desk holds the next two weeks."),
    _t("stream.test", "stream", 3, "A stream test before Sunday",
       "The stream is tested and the booth is ready the day before a Sunday."),
    _t("announcements.friday", "announcements", 4, "Sunday's announcements set by Friday",
       "The week's announcements are in by Friday."),
    # Over the lanes
    _t("oversee_lanes.start_each", "oversee_lanes", 1, "Start each office login's first assignment",
       "Every office login you're over has their first assignment, with its dates agreed with them."),
    _t("oversee_lanes.one_on_one", "oversee_lanes", 1, "A first one-on-one with each person you're over",
       "You've sat down with each of them: what's finished, what's stuck, what's next."),
    # A role that leads (or a group they lead). Each title reads alone, as
    # it does on the board and in a list of someone's things (the keys stay:
    # items already made keep working).
    _t("lead.people", LEAD, 1, "Who's on your team or group",
       "Everyone on your team or group is in the system."),
    _t("lead.meets", LEAD, 1, "When you meet: the day and time",
       "Your team or group's day and time are set, so everyone can see when you meet."),
    _t("lead.room", LEAD, 2, "The room you meet in",
       "Your team or group has its room, booked through a room request."),
    _t("lead.first_need", LEAD, 2, "What you need first",
       "You've said the one thing your team or group needs first, and who can help."),
    # A role that oversees
    _t("oversee.meet_each", OVERSEE, 1, "Meet each leader under you",
       "You've met each leader under you."),
    _t("oversee.each_started", OVERSEE, 2, "Each leader under you has started their first assignment",
       "Every leader under you has their first assignment."),
]

BY_KEY: Dict[str, Dict[str, Any]] = {t["key"]: t for t in TEMPLATES}


def duty_label(duty: Optional[str]) -> Optional[str]:
    import church_duties as cd
    if not duty:
        return None
    if duty in cd.CATALOG:
        return cd.CATALOG[duty]["label"]
    return SWITCH_LABEL.get(duty)


# ─── Whose items ──────────────────────────────────────────────────────

def own_duties(ch: co.Church, uid: str) -> List[str]:
    """The duties a login does of its own, in the catalog's order: its
    lanes' starter duties (the Executive Pastor's lane only its OVERSIGHT
    two: it covers the rest), what was moved to it by name, and, for a
    Manager no lane names, the duties its areas give it (church_duties'
    own answer). Never a money duty."""
    import church_duties as cd
    role = ch.role(uid)
    lanes = set(ch.lanes(uid))
    moved = ch.moved
    mine = {k for k, holders in moved.items() if uid in holders}
    if role in co.KEEPS_ALL:
        own = mine | {k for ln in lanes if ln != cd.EXEC for k in cd.STARTER.get(ln, ())}
    elif role == "manager":
        held = set(ch.held(uid))
        if cd.EXEC in lanes:
            own = {k for k in held if k in cd.OVERSIGHT or k in mine
                   or any(k in cd.STARTER.get(ln, ()) for ln in lanes if ln != cd.EXEC)}
        else:
            own = held
    else:
        own = set()
    return [k for k, d in cd.CATALOG.items() if k in own and not d["money"]]


def switches(ch: co.Church, cid: str) -> List[str]:
    """`lead` and `oversee` as this person holds them: an active role with
    the switch (church_map.can, on the open map or the role's own job), or a
    group they lead."""
    import church_map
    m = ch.map or None
    out: List[str] = []
    for h in ch.holders:
        if str(h.get("contact_id")) != cid:
            continue
        d = ch.def_of(key_=str(h.get("role") or ""))
        if not d:
            continue
        c = church_map.can(m, d)
        if c["lead"] and LEAD not in out:
            out.append(LEAD)
        if c["oversee"] and OVERSEE not in out:
            out.append(OVERSEE)
    if LEAD not in out and ch.leads_groups(cid):
        out.append(LEAD)
    return [s for s in (LEAD, OVERSEE) if s in out]


def for_login(ch: co.Church, uid: str) -> List[Dict[str, Any]]:
    duties = set(own_duties(ch, uid))
    return [t for t in TEMPLATES if t["duty"] in duties]


def for_person(ch: co.Church, cid: str) -> List[Dict[str, Any]]:
    held = set(switches(ch, cid))
    return [t for t in TEMPLATES if t["duty"] in held]


def for_who(ch: co.Church, target: Dict[str, Any]) -> List[Dict[str, Any]]:
    return for_login(ch, target["id"]) if target["kind"] == co.LOGIN else for_person(ch, target["id"])


# ─── Making them ──────────────────────────────────────────────────────

def _q(v: Any) -> str:
    return quote(str(v), safe="")


def column(target: Dict[str, Any]) -> str:
    return "assigned_to" if target["kind"] == co.LOGIN else "assigned_contact_id"


def made_keys(biz: str, target: Dict[str, Any]) -> Dict[str, str]:
    """startup_key -> task id of what's already been made for them."""
    rows = sb_clients.sb_get_as_service(
        f"/tasks?business_id=eq.{_q(biz)}&{column(target)}=eq.{_q(target['id'])}&startup_key=not.is.null"
        "&select=id,startup_key&limit=200")
    if not isinstance(rows, list):
        raise HTTPException(503, "Their first assignment couldn't be read just now. Try again.")
    return {str(r["startup_key"]): str(r["id"]) for r in rows if r.get("startup_key")}


def row_for(biz: str, target: Dict[str, Any], by: Dict[str, Any], t: Dict[str, Any], today: date) -> Dict[str, Any]:
    """One start-up item as a task. Every row carries the same keys (a bulk
    insert whose rows differ loses the chunk). `by` is who starts it: a
    login (handed_by) or one of the church's people, from the member app
    (handed_by_contact_id)."""
    return {"business_id": biz, "title": t["title"][:200], "description": None, "status": "todo",
            "priority": "medium", "due_date": (today + timedelta(days=7 * int(t["week"]))).isoformat(),
            "assigned_to": target["id"] if target["kind"] == co.LOGIN else None,
            "assigned_contact_id": target["id"] if target["kind"] == co.PERSON else None,
            "handed_by": str(by["id"]) if by["kind"] == co.LOGIN else None,
            "handed_by_contact_id": str(by["id"]) if by["kind"] == co.PERSON else None, "duty": t["duty"], "done_when": t["done_when"][:300], "check_key": t["check"],
            "startup_key": t["key"]}


def start(ch: co.Church, by: Dict[str, Any], target: Dict[str, Any], today: date) -> Dict[str, Any]:
    """Make the missing items of `target`'s first assignment, handed by
    `by`. {made: [task rows], skipped: n, of: m}. The caller checked that
    `by` is over them. A save that fails is a 503; one the unique index
    refused because someone else made it at the same moment is skipped."""
    items = for_who(ch, target)
    have = made_keys(ch.b, target)
    todo = [t for t in items if t["key"] not in have]
    out: Dict[str, Any] = {"made": [], "skipped": len(items) - len(todo), "of": len(items)}
    if not todo:
        return out
    rows = [row_for(ch.b, target, by, t, today) for t in todo]
    saved = sb_clients.sb_post_as_service("/tasks", rows)
    if isinstance(saved, list) and len(saved) == len(rows):
        out["made"] = saved
        return out
    # The bulk insert didn't land whole (another start at the same moment
    # took a key): one at a time, and what someone else made is skipped.
    have = made_keys(ch.b, target)
    for r in rows:
        if r["startup_key"] in have:
            out["skipped"] += 1
            continue
        one = sb_clients.sb_post_as_service("/tasks", r)
        if isinstance(one, list) and one:
            out["made"].append(one[0])
            continue
        if r["startup_key"] in made_keys(ch.b, target):
            out["skipped"] += 1
            continue
        raise HTTPException(503, f"{len(out['made'])} made; the rest didn't save. Try again.")
    return out
