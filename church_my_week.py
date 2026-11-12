"""church_my_week.py — My week: a church login's first page.

Kevin, 2026-10-26 ("Who sees what", canvas 99aFvCSRXU1x9pmqUcncoP, boards
"Built: My week"): pastors, admins and teams signing in would find the whole
system overwhelming. Each person's first page is what's theirs: what's been
handed to them, one line for each area they work in, and what crossed from
one area to another this week. The owner and admins see the whole church,
an area to a line; a login that works some areas sees only those.

    GET /church/my-week?business_id=          the page (any office login), with
                                              `rhythm`: How your week goes, from
                                              the duties the login holds (below),
                                              each on the day the login picked
                                              where church assignments are open
                                              (church_assignments), and what's
                                              stuck and was sent up to them
    GET /church/my-week/status?business_id=   whether this app shows it
    GET /church/my-week/people?business_id=   who a task can be handed to (and
                                              the church's leaders: church_leader_tasks)
    GET /church/my-week/team?business_id=     the office's Manager logins' weeks, in
                                              counts, for whoever is over the lanes
                                              (church_team_week)

Everything is read from where it already lives: the areas map
(church_areas.build: who works each area and what's missing), follow-ups
(church_follow_ups: handed to the person, matched by their sign-in email),
Prayer & care requests handed to their login (assigned_to, said as one
line with nothing of what was asked), and tasks handed to their login
(tasks.assigned_to, supabase/APPLY-2026-10-26-task-hand-off.sql). A read that fails is a 503, never an
empty week. Switched with the map: CHURCH_AREAS (off | owner | on).
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException

import church_areas
import sb_clients
from auth_supabase import UserSession
from business_access import business_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church", tags=["church"])

HANDED_DAYS = 7
SHOWN = 6
FINANCE_ROLES = ("owner", "admin")

# Where each kind of thing opens in the app (churchStructure's leaf ids).
DOOR = {
    "follow_up": {"area": "operate", "id": "follow-up", "label": "Open the Follow-up board"},
    "care": {"area": "operate", "id": "care", "label": "Open Prayer & care"},
    "areas": {"area": "operate", "id": "areas", "label": "Open Areas"},
    "kids_youth": {"area": "operate", "id": "kids", "label": "Open Kids check-in"},
    "groups_classes": {"area": "operate", "id": "groups", "label": "Open Groups"},
    "worship_media": {"area": "operate", "id": "sundays", "label": "Open Sundays"},
    "people_care": {"area": "operate", "id": "follow-up", "label": "Open the Follow-up board"},
    "messages_safety": {"area": "operate", "id": "messaging", "label": "Open Member messaging"},
    "website_outreach": {"area": "build", "id": "my-site", "label": "Open the website"},
    "office": {"area": "operate", "id": "tasks", "label": "Open Tasks"},
    "giving_money": {"area": "operate", "id": "bookkeeping", "label": "Open Giving"},
    "tasks": {"area": "operate", "id": "tasks", "label": "Open Tasks"},
    # Each duty's page (church_duties.CATALOG), for How your week goes. A
    # duty with no door here fails test_church_week_rhythm. Each id is a page
    # the app's church menu has (solutionist-studio churchStructure.tsx, its
    # table or the doors; checked 2026-11-02).
    # Office & Leadership. The front desk starts at Approvals, where what came
    # in waits for someone; decisions, the building and supplies are tracked
    # in Tasks (Kevin, 2026-11-02: "track supplies in tasks").
    "front_desk": {"area": "operate", "id": "queue", "label": "Open Approvals"},
    "leaders_note": {"area": "operate", "id": "leaders-note", "label": "Open the leaders note"},
    "meetings": {"area": "operate", "id": "board", "label": "Open Board & minutes"},
    "decisions": {"area": "operate", "id": "tasks", "label": "Open Tasks"},
    "weekly_text": {"area": "operate", "id": "sms", "label": "Open Texts"},
    "calendar": {"area": "operate", "id": "calendar", "label": "Open the calendar"},
    "rooms": {"area": "operate", "id": "spaces", "label": "Open Rooms & spaces"},
    "building": {"area": "operate", "id": "tasks", "label": "Open Tasks"},
    "records": {"area": "operate", "id": "documents", "label": "Open Files & policies"},
    "chat_rules": {"area": "operate", "id": "messaging", "label": "Open Member messaging"},
    "leaders_list": {"area": "operate", "id": "leaders", "label": "Open Leaders & roles"},
    "new_leaders": {"area": "operate", "id": "leaders", "label": "Open Leaders & roles"},
    "supplies": {"area": "operate", "id": "tasks", "label": "Open Tasks"},
    # People & Care. The member directory is one of the church's doors.
    "first_guests": {"area": "operate", "id": "follow-up", "label": "Open the Follow-up board"},
    "care_visits": {"area": "operate", "id": "care", "label": "Open Prayer & care"},
    "prayer": {"area": "operate", "id": "care", "label": "Open Prayer & care"},
    "help_requests": {"area": "operate", "id": "help", "label": "Open Help requests"},
    "shepherding": {"area": "operate", "id": "shepherding", "label": "Open Shepherding"},
    "groups": {"area": "operate", "id": "groups", "label": "Open Groups"},
    "member_records": {"area": "operate", "id": "directory", "label": "Open the member directory"},
    "kids": {"area": "operate", "id": "kids", "label": "Open Kids check-in"},
    "youth": {"area": "operate", "id": "groups", "label": "Open Groups"},
    "devotionals": {"area": "build", "id": "devotionals", "label": "Open Devotionals"},
    # Sunday & Serving: the volunteers.
    "serve_schedule": {"area": "operate", "id": "serve-schedule", "label": "Open Who serves when"},
    "serve_teams": {"area": "operate", "id": "serve-teams", "label": "Open Teams"},
    "new_volunteers": {"area": "operate", "id": "serve-teams", "label": "Open Teams"},
    "background_checks": {"area": "operate", "id": "serving", "label": "Open Serving"},
    "serving_thanks": {"area": "operate", "id": "serving", "label": "Open Serving"},
    # The sign-ups an event takes are set on the events page (the app's
    # search sends "sign up" there too).
    "events": {"area": "build", "id": "events-page", "label": "Open the events page"},
    "outreach_nights": {"area": "operate", "id": "serve-schedule", "label": "Open Who serves when"},
    "attendance": {"area": "operate", "id": "attendance", "label": "Open Attendance"},
    # Media & Communications: ChurchSavvy and production. The order is built
    # in ChurchSavvy's Sundays (Plan); Planning's Order of service only shows
    # it with each team's notes, and changes it in ChurchSavvy.
    "sunday_plan": {"area": "operate", "id": "sundays", "label": "Open Sundays"},
    "production_schedule": {"area": "operate", "id": "serve-schedule", "label": "Open Who serves when"},
    # Who's on ChurchSavvy's team is the Team part of Setup.
    "churchsavvy_team": {"area": "operate", "id": "worship-setup", "label": "Open ChurchSavvy setup"},
    "announcements": {"area": "operate", "id": "worship-announcements", "label": "Open Announcements"},
    "stream": {"area": "grow", "id": "live", "label": "Open Live"},
    "sermons": {"area": "grow", "id": "sermons", "label": "Open Sermons"},
    "clips": {"area": "grow", "id": "video-clips", "label": "Open Video clips"},
    # The marketing desk, or Posts where the desk is closed: the same page id.
    "posts": {"area": "grow", "id": "marketing", "label": "Open the marketing desk"},
    "flyers": {"area": "grow", "id": "create", "label": "Open Create"},
    "website": {"area": "build", "id": "my-site", "label": "Open the website"},
    "monthly_report": {"area": "operate", "id": "monthly-report", "label": "Open the monthly report"},
    "oversee_lanes": {"area": "operate", "id": "team", "label": "Open the office team"},
    # Money: the owner's and the admins'. The books are Giving's other tabs.
    "deposit": {"area": "operate", "id": "bookkeeping", "label": "Open Giving"},
    "books": {"area": "operate", "id": "bookkeeping", "label": "Open Giving"},
    "pay": {"area": "operate", "id": "checks", "label": "Open Check requests"},
    "store": {"area": "operate", "id": "offerings-manager", "label": "Open the store"},
}


def _q(v: Any) -> str:
    from urllib.parse import quote
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _need(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, "Your week couldn't be read just now. Try again.")
    return rows


def _first(name: str) -> str:
    return (name or "").strip().split(" ")[0] or "Someone"


def _when(ts: Any, now: datetime) -> str:
    """'Sunday', 'yesterday', 'Oct 12': how a person says when."""
    d = _parse(ts)
    if not d:
        return ""
    days = (now.date() - d.date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return d.strftime("%A")
    return f"{d.strftime('%b')} {d.day}"


def _area_line(area: Dict[str, Any]) -> Dict[str, Any]:
    gaps = list(area.get("gaps") or [])
    names = list(dict.fromkeys(p.get("name") for p in area.get("people") or [] if p.get("name")))
    return {
        "key": area["key"], "label": area["label"],
        "line": gaps[0] if gaps else ("Nothing missing." if names else f"No one works it yet. Usually: {area.get('team')}."),
        "more": max(0, len(gaps) - 1), "gaps": len(gaps),
        "state": "watch" if gaps or not names else "ok",
        "people": len(names), "names": names[:3],
        "door": DOOR.get(area["key"]),
    }


def build(business: Dict[str, Any], user_id: str, email: str, role: str, *, own: bool = True) -> Dict[str, Any]:
    """`own`: the login reading its own week. See as (another login's week)
    passes False: what the office sent a person is theirs alone, so it's
    never read or shown there (#1804 review)."""
    biz = str(business["id"])
    now = _now()
    view = church_areas.view_for(biz, user_id, role)
    if view is None:
        raise HTTPException(503, "Your week couldn't be read just now. Try again.")
    whole = view["areas"] is None
    finance = role in FINANCE_ROLES
    mine_areas = [a for a in church_areas.AREA_ORDER if (whole or a in view["areas"]) and (finance or a != "giving_money")]
    the_map = church_areas.build(business)
    by_key = {a["key"]: a for a in the_map["areas"]}
    areas = [_area_line(by_key[a]) for a in mine_areas if a in by_key]

    # The person behind this login, by their sign-in email.
    email = (email or "").strip().lower()
    me_ids: List[str] = []
    me_name: Optional[str] = None
    if email and "@" in email:
        me = _need(f"/contacts?business_id=eq.{_q(biz)}&email=ilike.{_q(church_areas._escape_ilike(email))}"
                   "&select=id,name&limit=10")
        me_ids = [str(c["id"]) for c in me]
        # Their own name for the greeting: the church's settings carry the
        # pastor's, and every login was greeted with it.
        me_name = next((str(c["name"]).strip() for c in me if str(c.get("name") or "").strip()), None)

    needs: List[Dict[str, Any]] = []
    # Follow-ups handed to them.
    if me_ids:
        rows = _need(f"/church_follow_ups?business_id=eq.{_q(biz)}&leader_contact_id=in.({','.join(_q(i) for i in me_ids)})"
                     "&status=eq.open&select=id,contact_id,card_name,due_at,created_at&order=due_at.asc&limit=50")
        names = _names(biz, [r["contact_id"] for r in rows])
        for r in rows:
            due = _parse(r.get("due_at"))
            late = bool(due and due < now)
            who = names.get(str(r["contact_id"])) or "Someone"
            needs.append({"kind": "follow_up", "late": late, "area": "people_care",
                          "title": f"{who} is waiting to hear from you." if late else f"{who} was handed to you.",
                          "detail": f"{r.get('card_name') or 'A card'} · " + (
                              f"due {_when(r.get('due_at'), now)}" if late else f"handed {_when(r.get('created_at'), now)}"),
                          "door": DOOR["follow_up"]})
    # Prayer & care handed to their login: one line, nothing of what was asked.
    care = _need(f"/ministry_care_requests?business_id=eq.{_q(biz)}&assigned_to=eq.{_q(user_id)}"
                 "&status=in.(new,reviewed)&select=id&limit=50")
    if care:
        n = len(care)
        needs.append({"kind": "care", "late": False, "area": "people_care",
                      "title": "A prayer or care request was handed to you." if n == 1
                      else f"{n} prayer or care requests were handed to you.",
                      "detail": "Private to you and the pastors.", "door": DOOR["care"]})
    # Tasks handed to their login, late first. A due date is the church's
    # own day: in a US evening, UTC is already tomorrow.
    today = _today(business, now)
    for t in _need(f"/tasks?business_id=eq.{_q(biz)}&assigned_to=eq.{_q(user_id)}&status=neq.done"
                   "&select=id,title,due_date&order=due_date.asc.nullslast&limit=20"):
        due = str(t.get("due_date") or "")[:10]
        late = bool(due and due < today.isoformat())
        needs.append({"kind": "task", "late": late, "area": "office",
                      "title": (t.get("title") or "A task").strip(),
                      "detail": "A task handed to you · " + (_due(due, today) if due else "no date"),
                      "door": DOOR["tasks"]})
    # What's stuck and was sent up to them (church_assignments), until it's
    # no longer stuck; once it's done, a line that says so for a week (it
    # never vanishes without a word). While its switch is open for the
    # church. A read that fails leaves these lines out; the week stands.
    import church_over
    if church_over.church_open(biz):
        week_ago = (now - timedelta(days=HANDED_DAYS + 1)).date().isoformat()
        up = sb_clients.sb_get_as_service(
            f"/tasks?business_id=eq.{_q(biz)}&raised_to=eq.{_q(user_id)}&raised_at=not.is.null"
            f"&or=(status.neq.done,completed_at.gte.{week_ago})"
            "&select=id,title,stuck_note,stuck_at,status,completed_at&order=raised_at.desc&limit=20")
        if isinstance(up, list):
            cut = (now - timedelta(days=HANDED_DAYS)).isoformat()
            for t in up:
                title = (t.get("title") or "An assignment").strip()
                note = " ".join(str(t.get("stuck_note") or "").split())
                if t.get("status") == "done":
                    if str(t.get("completed_at") or "") >= cut:
                        needs.append({"kind": "raised_done", "late": False, "area": "office",
                                      "title": f"“{title}” was sent up to you, and it's done now.",
                                      "detail": f"Done {_when(t.get('completed_at'), now)}", "door": DOOR["tasks"]})
                elif t.get("stuck_at"):
                    needs.append({"kind": "raised", "late": True, "area": "office",
                                  "title": f"“{title}” is stuck and was sent up to you.",
                                  "detail": note or "Sent up to you", "door": DOOR["tasks"]})
        else:
            print(f"[church_my_week] {biz[:8]}: what was sent up wasn't read", flush=True)
    # What the office sent this login's own person for their area
    # (church_handovers: never a task, so never one of the needs; the owner's
    # person included). A read that fails is None, said in the log; the week
    # stands.
    from_office: Optional[List[Dict[str, Any]]] = []
    if own and church_over.church_open(biz):
        import church_handovers
        try:
            from_office = church_handovers.for_login(business, user_id, now)
        except HTTPException:
            from_office = None
            print(f"[church_my_week] {biz[:8]}: what the office sent wasn't read", flush=True)
    # The whole church: follow-ups with no one, and late ones.
    if whole:
        open_rows = _need(f"/church_follow_ups?business_id=eq.{_q(biz)}&status=in.(open,handed_back)"
                          "&select=status,leader_contact_id,due_at&limit=500")
        no_one = sum(1 for r in open_rows if r.get("status") == "handed_back" or not r.get("leader_contact_id"))
        late = sum(1 for r in open_rows if r.get("status") == "open" and (_parse(r.get("due_at")) or now) < now)
        if no_one:
            needs.append({"kind": "no_one", "late": True, "area": "people_care",
                          "title": f"{no_one} {'person' if no_one == 1 else 'people'} in follow-up "
                                   f"{'has' if no_one == 1 else 'have'} no one.",
                          "detail": "Hand them to someone on the Follow-up board.", "door": DOOR["follow_up"]})
        if late:
            needs.append({"kind": "late", "late": False, "area": "people_care",
                          "title": f"{late} follow-up{'s are' if late != 1 else ' is'} late.",
                          "detail": "Each one has already been nudged; the board says who has it.", "door": DOOR["follow_up"]})
        unplaced = [x for x in the_map.get("logins") or [] if x.get("by") == "none"]
        if unplaced:
            n = len(unplaced)
            needs.append({"kind": "logins", "late": False, "area": "office",
                          "title": f"{n} office login{'s still see' if n != 1 else ' still sees'} everything.",
                          "detail": "Give them their areas, so each sees their part.", "door": DOOR["areas"]})
    else:
        # A login that works some areas: what's missing in them is theirs.
        for a in areas:
            for gap in (by_key[a["key"]].get("gaps") or [])[:2]:
                needs.append({"kind": "gap", "late": False, "area": a["key"], "title": gap, "detail": a["label"],
                              "door": a["door"]})
    # Last month's report, due on this month's first Monday, for the Manager
    # who does monthly_report (church_monthly_report), until it's sent. A read
    # that fails leaves this one line out; the week stands.
    import church_monthly_report
    report = church_monthly_report.week_item(business, user_id, role, today)
    if report:
        needs.append(report)

    handed = _handed(biz, now, whole, set(mine_areas))
    order = {"raised": 0, "follow_up": 0, "no_one": 1, "care": 2, "task": 3, "report": 3, "raised_done": 3,
             "gap": 4, "late": 5, "logins": 6}
    needs.sort(key=lambda n: (not n["late"], order.get(n["kind"], 9)))
    out = {
        "me": {"role": role, "areas": view["areas"], "by": view["by"], "why": view["why"], "name": me_name},
        "next": needs[0] if needs else None,
        "needs": needs[1:SHOWN + 1],
        "areas": areas,
        "handed": handed,
        "counts": {"needs": len(needs), "areas": len(areas), "handed": len(handed)},
    }
    if own:
        out["from_office"] = from_office
        out["counts"]["from_office"] = sum(1 for x in from_office or [] if not x["seen"])
    return out


def _clock(business: Dict[str, Any]) -> Tuple[Any, bool]:
    """(the clock, whether it's the church's own): the one clock every week
    page reads (church_work_checks.church_zone); one that can't be read is
    the platform's default for My week's own lines, said in the log, and
    never a 503 for the first page (the team page and the one-on-one 503)."""
    import church_work_checks as cw
    try:
        return cw.church_zone(business), True
    except HTTPException:
        print(f"[church_my_week] {str(business.get('id'))[:8]}: the church's clock wasn't read; "
              "My week uses the platform's for now and judges nothing", flush=True)
        return cw.platform_zone(), False


def _today(business: Dict[str, Any], now: datetime) -> date:
    """The church's own date (_clock)."""
    return now.astimezone(_clock(business)[0]).date()


def _due(day: str, today: date) -> str:
    """A task's due date, said: late by how much, today, tomorrow, or the day."""
    try:
        d = datetime.fromisoformat(day).date()
    except ValueError:
        return "no date"
    gap = (d - today).days
    if gap < 0:
        return f"{-gap} day{'s' if gap != -1 else ''} late"
    if gap == 0:
        return "due today"
    if gap == 1:
        return "due tomorrow"
    return f"due {d.strftime('%A')}" if gap < 7 else f"due {d.strftime('%b')} {d.day}"


def people(business: Dict[str, Any], me: str) -> List[Dict[str, Any]]:
    """Who a task can be handed to: the owner and every active office login,
    each by their own name (the church's list, by their sign-in email; else
    the part of the email before the @, never the whole address: the logins
    list is the admins'). The person asking is `you`."""
    biz = str(business["id"])
    seats = _need(f"/business_users?business_id=eq.{_q(biz)}&status=eq.active"
                  "&select=user_id,role,invited_email&limit=200")
    emails = sorted({(s.get("invited_email") or "").strip().lower() for s in seats if "@" in (s.get("invited_email") or "")})
    named: Dict[str, str] = {}
    if emails:
        rows = _need(f"/contacts?business_id=eq.{_q(biz)}&email=in.({','.join(_q(e) for e in emails)})"
                     "&select=name,email&limit=400")
        for r in rows:
            em, nm = (r.get("email") or "").strip().lower(), (r.get("name") or "").strip()
            if em and nm and em not in named:
                named[em] = nm
    owner = str(business.get("owner_id") or "")
    settings = business.get("settings") if isinstance(business.get("settings"), dict) else {}
    out = [{"user_id": owner, "name": (settings.get("practitioner_name") or "").strip() or "The owner",
            "role": "owner", "you": owner == me}] if owner else []
    for s in seats:
        uid = str(s.get("user_id") or "")
        if not uid or uid == owner:
            continue
        em = (s.get("invited_email") or "").strip().lower()
        out.append({"user_id": uid, "name": named.get(em) or em.split("@")[0] or "An office login", "role": s.get("role"),
                    "you": uid == me})
    return out


def _role(business: Dict[str, Any], user_id: str) -> str:
    """The caller's standing: the owner, or their seat's role. A read that
    fails is a 503, never "no seat" (business_access has already let them in)."""
    if str(business.get("owner_id")) == str(user_id):
        return "owner"
    rows = _need(f"/business_users?business_id=eq.{_q(business['id'])}&user_id=eq.{_q(user_id)}"
                 "&status=eq.active&select=role&limit=1")
    if not rows or not rows[0].get("role"):
        raise HTTPException(404, "Not Found")
    return str(rows[0]["role"])


def _names(biz: str, ids: List[Any]) -> Dict[str, str]:
    ids = sorted({str(i) for i in ids if i})
    if not ids:
        return {}
    rows = _need(f"/contacts?business_id=eq.{_q(biz)}&id=in.({','.join(_q(i) for i in ids)})&select=id,name&limit=200")
    return {str(r["id"]): (r.get("name") or "").strip() or "Someone" for r in rows}


def _handed(biz: str, now: datetime, whole: bool, mine: set) -> List[Dict[str, Any]]:
    """Follow-ups started this week, as hand-offs between areas: a first
    check-in goes from the kids desk to Welcome, a card from the card to its
    role. The whole church sees them all; a login that works People & care
    sees them too; Kids & youth sees the first check-ins."""
    if not (whole or mine & {"people_care", "kids_youth"}):
        return []
    since = (now - timedelta(days=HANDED_DAYS)).isoformat()
    rows = _need(f"/church_follow_ups?business_id=eq.{_q(biz)}&created_at=gte.{_q(since)}"
                 "&select=id,contact_id,card_key,card_name,leader_contact_id,leader_role,status,due_at,done_at,created_at"
                 "&order=created_at.desc&limit=40")
    if not (whole or "people_care" in mine):
        rows = [r for r in rows if r.get("card_key") == "checkin:first"]
    names = _names(biz, [r.get("contact_id") for r in rows] + [r.get("leader_contact_id") for r in rows])
    import church_roles as cr
    defs = cr.defs(biz)
    if defs is None:
        raise HTTPException(503, "Your week couldn't be read just now. Try again.")
    out = []
    for r in rows[:SHOWN]:
        who = names.get(str(r.get("contact_id"))) or "Someone"
        leader = names.get(str(r.get("leader_contact_id") or "")) if r.get("leader_contact_id") else None
        first = r.get("card_key") == "checkin:first"
        due = _parse(r.get("due_at"))
        status = r.get("status")
        if status == "done":
            state, said = "reached", f"{_first(leader) if leader else 'Someone'} reached them {_when(r.get('done_at'), now)}".strip()
        elif status == "handed_back" or not leader:
            state, said = "no_one", "With no one yet"
        elif due and due < now:
            state, said = "late", f"With {_first(leader)}, late"
        else:
            state, said = "with", f"With {_first(leader)}"
        out.append({
            "id": str(r.get("id")),
            "from": "Kids check-in" if first else (r.get("card_name") or "A card"),
            "to": cr.title_of(r.get("leader_role") or "", defs) if r.get("leader_role") else "The office",
            "title": f"{who}, first time" if first else who,
            "detail": f"{'Checked in' if first else 'Came in'} {_when(r.get('created_at'), now)} · {said}",
            "state": state,
        })
    return out


# ─── How your week goes (docs/CHURCH_DUTIES.md step 7) ────────────────
# Kevin, 2026-11-01: "a way for some sort of video or training or something
# that can be given so they know how there week will go so they can see what
# they suppose to do with no problem." Each duty a login holds, on its day,
# with its training line (`does`) and the page it opens; the app plays it as
# a walkthrough. The owner and every Admin hold every duty (`every_job`).

WEEKDAYS: Tuple[str, ...] = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DAY_NAMES = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday", "Fri": "Friday",
             "Sat": "Saturday", "Sun": "Sunday"}
WEEK, MONTH, ANY_DAY = "week", "month", "any"
GROUP_LABEL = {**DAY_NAMES, WEEK: "Each week", MONTH: "Once a month", ANY_DAY: "Any day"}
GROUP_ORDER: Tuple[str, ...] = WEEKDAYS + (WEEK, MONTH, ANY_DAY)


def _and(words: List[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def placed(day: Any) -> Tuple[str, List[str], str]:
    """Where a duty's catalog day puts it: (group, weekdays, said).
    "first Monday" and anything "monthly" are the Month's ("Tue, monthly" is
    a Tuesday once a month, never every Tuesday); days of the week are each
    of those days; "weekly" with no day is Each week (some day in the week,
    which one isn't said); "as needed", or a day this doesn't know, is Any
    day."""
    toks = [t.strip() for t in str(day or "").split(",") if t.strip()]
    low = {t.lower() for t in toks}
    days = list(dict.fromkeys(t for t in toks if t in WEEKDAYS))     # as the catalog says them: "Sun, Mon"
    if "first monday" in low:
        return MONTH, ["Mon"], "The first Monday of the month"
    if "monthly" in low:
        return MONTH, days, ("Once a month, on a " + " or a ".join(DAY_NAMES[d] for d in days)) if days else "Once a month"
    if days:
        return days[0], days, _and([DAY_NAMES[d] + "s" for d in days])
    if "weekly" in low:
        return WEEK, [], "Once a week, any day"
    return ANY_DAY, [], "Whenever it comes up"


def _held(biz: str, uid: str, role: str) -> FrozenSet[str]:
    """The duties this login holds (church_duties.standing). The owner and
    the admins hold every one, without a read."""
    import church_duties
    if role in church_duties.KEEPS_ALL:
        return church_duties.ALL
    return frozenset(church_duties.standing(biz, uid)["duties"])


def _done(business: Dict[str, Any], keys: FrozenSet[str], today: date, now: datetime, tz, *,
          picks: Optional[Dict[str, str]] = None, ctx: Any = None) -> Dict[str, bool]:
    """Whether this week's (or this month's) job is already done (_done_full,
    without its words)."""
    return {k: v["done"] for k, v in _done_full(business, keys, today, now, tz, picks=picks, ctx=ctx).items()}


# The weekly jobs church_work_checks judges (docs/CHURCH_ASSIGNMENTS.md, PR B),
# read only where church assignments are open for the church.
WEEK_JOBS: Tuple[str, ...] = ("first_guests", "serve_schedule", "calendar", "sermons", "attendance",
                              "shepherding")
STATE_TEXT = {"done": "Done", "not_yet": "Not yet", "late": "Late"}


def due_day(duty: str, monday: date, picked: Optional[str] = None, today: Optional[date] = None) -> Optional[date]:
    """The day this week (the one starting `monday`) a duty falls on: the day
    the login picked (church_assignments), else its catalog's last weekday
    ("Sat, Sun": Sunday); the first-Monday report, the first Monday of
    today's month (the report it judges is last month's). None for a duty
    that names no day."""
    import church_assignments as cas
    import church_duties
    d = church_duties.CATALOG.get(duty)
    if not d:
        return None
    day = cas.day_with(d["day"], picked) if picked and cas.movable(duty) else d["day"]
    toks = [t.strip() for t in str(day or "").split(",")]
    if "first monday" in {t.lower() for t in toks}:
        import church_monthly_report as cmr
        t = today or monday
        return cmr.first_monday(date(t.year, t.month, 1))
    days = [t for t in toks if t in WEEKDAYS]
    return monday + timedelta(days=WEEKDAYS.index(days[-1])) if days else None


def job_state(done: Optional[bool], due: Optional[date], today: date) -> Optional[str]:
    """done / not_yet / late for a job judged this week: late once its day
    is over and it isn't done. None when it wasn't judged (no check, nothing
    to count, or a read that failed): it claims nothing."""
    if done is None or due is None:
        return None
    if done:
        return "done"
    return "late" if today > due else "not_yet"


def _done_full(business: Dict[str, Any], keys: FrozenSet[str], today: date, now: datetime, tz, *,
               picks: Optional[Dict[str, str]] = None, ctx: Any = None) -> Dict[str, Dict[str, Any]]:
    """Whether this week's (or this month's) job is already done, with what
    says so: {duty: {done, text}}. Where a cheap read the job already keeps
    tells: the leaders note sent this week (its own last send, on its own
    clock), last month's report sent (or sending) this month, a text
    announcement that reached someone since Monday; and, where church
    assignments are open for the church, the six weekly jobs
    church_work_checks judges (WEEK_JOBS), each by the day the login picked
    (`picks`), else the catalog's. Any other duty isn't here. A read that
    fails leaves its duty out, never a guess: the week stands. `ctx` (a
    church_work_checks.Ctx) shares every read between logins: the team page
    reads each table once."""
    import church_work_checks as cw
    biz = str(business["id"])
    ctx = ctx or cw.Ctx(business, now, tz)
    out: Dict[str, Dict[str, Any]] = {}

    def fact(key: str, fn, yes: str, no: str, unread: str) -> None:
        def safe() -> bool:
            try:
                return fn()
            except cw.Unread:
                raise
            except Exception:           # any failure is a read that didn't answer: the week stands
                raise cw.Unread(key)
        try:
            got = ctx.once(("done", key), safe)
        except cw.Unread:
            print(f"[church_my_week] {biz[:8]}: {unread}")
            return
        out[key] = {"done": bool(got), "text": yes if got else no}

    if "leaders_note" in keys:
        def note() -> bool:
            import church_leaders_note as ln
            try:
                monday = ln.monday_of(now.astimezone(ln._zone(business)).date())
            except HTTPException:
                raise cw.Unread("leaders note clock")
            last = ln.last_of(business)
            return bool(last and last.get("week") == monday.isoformat())
        fact("leaders_note", note, "Sent this week", "Not sent yet this week",
             "the leaders note's last send wasn't read for the rhythm")
    if "monthly_report" in keys:
        def report() -> bool:
            import church_monthly_report as cmr
            first = cmr.prev_month(date(today.year, today.month, 1))
            try:
                row = cmr._row(biz, first.strftime("%Y-%m"))
            except Exception:
                raise cw.Unread("monthly report")
            return bool((row or {}).get("send_id"))
        fact("monthly_report", report, "Last month's report is sent", "Last month's report isn't sent yet",
             "the monthly report's row wasn't read for the rhythm")
    if "weekly_text" in keys:
        def texts() -> bool:
            # The texts reader (church_work_checks.texts: since last week's Monday, read once).
            lo = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time(), tzinfo=tz)
            return cw.texted(ctx, lo, now + timedelta(days=1))
        fact("weekly_text", texts, "This week's text went out", "This week's text hasn't gone out yet",
             "this week's announcements weren't read for the rhythm")
    jobs = [k for k in WEEK_JOBS if k in keys]
    if jobs:
        import church_over
        if church_over.church_open(business):
            monday = today - timedelta(days=today.weekday())
            for k in jobs:
                ans = cw.week_job(ctx, k, due_day(k, monday, (picks or {}).get(k), today) or monday)
                if ans and ans.get("done") is not None and not ans.get("unread"):
                    out[k] = {"done": bool(ans["done"]), "text": ans["text"]}
    return out


def last_week(business: Dict[str, Any], duties: FrozenSet[str], today: date, now: datetime, tz, *,
              picks: Optional[Dict[str, str]] = None, ctx: Any = None) -> Optional[Dict[str, Any]]:
    """Last week's result for one login's jobs (the Monday roll-up, the team
    page), where church assignments are open for the church: each job that
    fell last week and that a check judges, judged the same way as this
    week's, at the end of its own day (the day the login picks now, else the
    catalog's). {done, of, missed: [labels], unread: [labels], text}: "Last
    week: 6 of 7 done; missed: The church calendar". A read that failed, or
    a record a newer one replaced (the leaders note keeps only its last
    send), is said as couldn't be read, never as missed; a job with nothing
    to count isn't in it. None when no job of theirs was judged."""
    import church_duties
    import church_over
    import church_team_week as ctw
    import church_work_checks as cw
    if not church_over.church_open(business):
        return None
    ctx = ctx or cw.Ctx(business, now, tz)
    biz = str(business["id"])
    monday = today - timedelta(days=today.weekday()) - timedelta(days=7)
    done: List[str] = []
    missed: List[str] = []
    unread: List[str] = []

    def end_of(d: date) -> datetime:
        return datetime.combine(d + timedelta(days=1), datetime.min.time(), tzinfo=tz)

    for w in ctw.due_this_week(duties, monday, picks):
        k = w["duty"]
        due = due_day(k, monday, (picks or {}).get(k), monday)
        if due is None:
            continue
        label = church_duties.CATALOG[k]["label"]
        got: Optional[bool] = None
        try:
            if k in WEEK_JOBS:
                ans = cw.week_job(ctx, k, due, monday, end_of(due))
                if ans.get("unread"):
                    raise cw.Unread(k)
                got = ans.get("done")
            elif k == "weekly_text":
                got = cw.texted(ctx, datetime.combine(monday, datetime.min.time(), tzinfo=tz), end_of(due))
            elif k == "leaders_note":
                import church_leaders_note as ln
                week = str((ln.last_of(business) or {}).get("week") or "")
                if week > monday.isoformat():
                    raise cw.Unread("a newer note replaced the record")
                got = week == monday.isoformat()
            elif k == "monthly_report":
                import church_monthly_report as cmr
                month = cmr.prev_month(date(due.year, due.month, 1)).strftime("%Y-%m")
                row = ctx.once(("report", month), lambda: cmr._row(biz, month))
                at = cw._at((row or {}).get("sent_at"))
                got = bool(at and at < end_of(due))
        except Exception:
            unread.append(label)
            continue
        if got is None:
            continue
        (done if got else missed).append(label)
    of = len(done) + len(missed)
    if not of and not unread:
        return None
    text = f"Last week: {len(done)} of {of} done" if of else "Last week"
    if missed:
        text += "; missed: " + ", ".join(missed)
    if unread:
        text += ("; " if of else ": ") + "couldn't be read: " + ", ".join(unread)
    return {"done": len(done), "of": of, "missed": missed, "unread": unread, "text": text}


def rhythm(business: Dict[str, Any], user_id: str, role: str, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """How this login's week goes: the duties it holds, in the catalog's
    order, by day (Monday to Sunday, then Each week, then Once a month, then
    Any day; only the days with something on them), each with its training
    line, its door and whether it's today on the church's own day (an Each
    week job is never today: its day isn't said). `every_job`: the owner
    or an Admin, who holds every duty. None for a business that isn't a
    church, and when the duties can't be read (My week stands without it).
    A church clock that can't be read: the platform's for the days, and
    nothing judged (`judged` false, with `judged_text`)."""
    import church_duties
    import church_follow_up as cfu
    if not cfu.is_church(business):
        return None
    biz = str(business["id"])
    now = now or _now()
    try:
        held = _held(biz, str(user_id), role)
    except HTTPException:
        print(f"[church_my_week] {biz[:8]}: a login's duties weren't read; no rhythm")
        return None
    # The church's one clock; one that can't be read is the platform's for
    # the days, and nothing is judged on it (no done, not yet or late).
    tz, clock_ok = _clock(business)
    today = now.astimezone(tz).date()
    key_today = WEEKDAYS[today.weekday()]
    import church_monthly_report as cmr
    first_monday = cmr.first_monday(date(today.year, today.month, 1))
    # The days this login picked (church_assignments, where its switch is
    # open for the church): each stands in for the catalog's, and each
    # weekly job is judged by it.
    import church_assignments as cas
    import church_over
    assign = church_over.church_open(business)
    picks = cas.days_for(business, [user_id]).get(str(user_id), {}) if assign else {}
    judged = _done_full(business, held, today, now, tz, picks=picks) if clock_ok else {}
    done = {k: v["done"] for k, v in judged.items()}
    monday = today - timedelta(days=today.weekday())
    groups: Dict[str, List[Dict[str, Any]]] = {g: [] for g in GROUP_ORDER}
    for key, d in church_duties.CATALOG.items():
        if key not in held:
            continue
        pick = picks.get(key)
        group, days, said = placed(cas.day_with(d["day"], pick) if pick else d["day"])
        if group == MONTH:
            is_today = d["day"].strip().lower() == "first monday" and today == first_monday
        else:
            is_today = key_today in days
        item = {"key": key, "label": d["label"], "does": d["does"], "area": d["area"], "when": said, "days": days,
                "door": DOOR.get(key), "today": is_today}
        if assign:
            item["movable"] = cas.movable(key)
        if pick:
            item.update(picked=pick, usual=placed(d["day"])[2])
        if key in done:
            item["done"] = done[key]
            state = job_state(done[key], due_day(key, monday, pick, today), today) if assign else None
            if state:
                item.update(state=state, state_text=STATE_TEXT[state], detail=judged[key]["text"])
        for g in (days if group in WEEKDAYS else [group]):
            groups[g].append(item)
    out_days = [{"key": g, "label": GROUP_LABEL[g], "today": g == key_today or (g == MONTH and any(i["today"] for i in groups[g])),
                 "items": groups[g]} for g in GROUP_ORDER if groups[g]]
    out = {
        "every_job": role in church_duties.KEEPS_ALL,
        "today": {"key": key_today, "label": DAY_NAMES[key_today], "date": today.isoformat()},
        "days": out_days,
        "count": sum(1 for k in church_duties.CATALOG if k in held),
        "judged": clock_ok,
    }
    if not clock_ok:
        out["judged_text"] = "Done, not yet and late couldn't be checked just now."
    return out


def _with_rhythm(week: Dict[str, Any], business: Dict[str, Any], user_id: str, role: str) -> Dict[str, Any]:
    r = rhythm(business, user_id, role)
    if r is not None:
        week["rhythm"] = r
    return week


def rhythm_within(r: Dict[str, Any], areas: List[str]) -> Dict[str, Any]:
    """Another Manager's rhythm as whoever is over the lanes may read it
    (church_team_week.within's rule): only the jobs in her own areas."""
    mine = set(areas)
    days = [{**d, "items": [i for i in d["items"] if i.get("area") in mine]} for d in r.get("days") or []]
    days = [{**d, "today": any(i["today"] for i in d["items"])} if d["key"] == MONTH else d for d in days if d["items"]]
    return {**r, "days": days, "count": len({i["key"] for d in days for i in d["items"]})}


# ─── Routes ───────────────────────────────────────────────────────────

@router.get("/my-week/status")
def my_week_status(business_id: str, session: UserSession = Depends(sb_clients.authed_request),
                   biz: Dict[str, Any] = Depends(business_access("viewer"))):
    """Whether this person's app shows My week: a church, the switch on for
    them. Reads nothing but the business."""
    church_areas._gate(session.user)
    import church_follow_up as cfu
    return {"enabled": cfu.is_church(biz)}


@router.get("/my-week/people")
def my_week_people(business_id: str, session: UserSession = Depends(sb_clients.authed_request),
                   biz: Dict[str, Any] = Depends(business_access("member"))):
    """Who a task can be handed to (Tasks, "Hand to"), for anyone who can
    change tasks: the office logins, and (My tasks for leaders, while its
    switch is open to this login and its migration is in) `leaders`, the
    church's leaders by name and role title. No `leaders` key: no Leaders
    group in the picker."""
    church_areas._gate(session.user)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, "Handing tasks over is for churches")
    out: Dict[str, Any] = {"people": people(biz, str(session.user.id))}
    import church_leader_tasks
    leaders = church_leader_tasks.hand_list(biz, session.user)
    if leaders is not None:
        out["leaders"] = leaders
    return without_guarded(biz, str(session.user.id), out)


def without_guarded(biz: Dict[str, Any], uid: str, out: Dict[str, Any]) -> Dict[str, Any]:
    """Kevin, 2026-11-12: "admins can not give work to elders and pastors."
    For any seat but the owner, while church assignments are open for the
    church (church_over.church_open), the Hand to list offers no shepherd
    and no senior (church_over.Church.guarded: by each role's own switch),
    nor an office login whose person is one, nor the owner when the owner's
    own person is a pastor or an elder; the caller themselves stays (a task
    to yourself). Who is guarded that can't be read is a 503, never
    an unfiltered list. The database itself doesn't refuse such a task (the
    office writes tasks straight to it): that's the known limit, said in
    docs/CHURCH_ASSIGNMENTS.md."""
    import church_over
    if str(biz.get("owner_id") or "") == uid or not church_over.church_open(biz):
        return out
    ch = church_over.Church(biz)
    guard = ch.guarded
    if not guard:
        return out
    lp = ch.login_person
    out = dict(out)
    # The owner stays, but where the owner's own person is a pastor or an
    # elder (Love City's owner is its senior pastor): then not for this seat
    # either (#1804 review; hand-overs and Send up to the owner still go).
    keep_owner = not ch.owner_guarded
    out["people"] = [p for p in out.get("people") or []
                     if p.get("you") or (keep_owner if p.get("role") == "owner"
                                         else lp.get(str(p.get("user_id"))) not in guard)]
    if "leaders" in out:
        out["leaders"] = [x for x in out["leaders"] or [] if str(x.get("contact_id")) not in guard]
    return out


@router.get("/my-week")
def my_week(business_id: str, as_user: Optional[str] = None, session: UserSession = Depends(sb_clients.authed_request),
            biz: Dict[str, Any] = Depends(business_access("viewer"))):
    """The caller's week, or, seeing as another office login (See as), that
    login's week: what it's shown, what's handed to it, and `seeing_as`,
    whose week it is. The owner and an admin can see as any office login.
    Whoever is over the lanes (the oversee_lanes duty: the Executive Pastor
    by default; church_team_week, while CHURCH_TEAM_ROLLUP is open to the
    church) can see as another Manager login, never an Admin or the owner."""
    church_areas._gate(session.user)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, "My week is for churches")
    bid = str(biz["id"])
    role = _role(biz, str(session.user.id))
    if as_user and as_user != str(session.user.id):
        overseer = False
        if role not in FINANCE_ROLES:
            import church_team_week
            if not (church_team_week.overseer(bid, session.user, role) and church_team_week.church_open(bid)):
                raise HTTPException(403, "Only the owner, an admin or whoever is over the lanes can see as someone else")
            overseer = True
        try:
            uid = str(uuid.UUID(as_user))
        except (ValueError, TypeError):
            raise HTTPException(400, "That login isn't valid")
        if overseer and uid == str(biz.get("owner_id") or ""):
            raise HTTPException(403, OVERSEER_ONLY)
        seat = _need(f"/business_users?business_id=eq.{_q(bid)}&user_id=eq.{_q(uid)}&status=eq.active"
                     "&select=role,invited_email,contact_id,name,lane,areas&limit=1")
        if not seat:
            raise HTTPException(404, "That login isn't on this church")
        if overseer and seat[0].get("role") != "manager":
            raise HTTPException(403, OVERSEER_ONLY)
        out = build(biz, uid, seat[0].get("invited_email") or "", seat[0].get("role") or "viewer", own=False)
        view: Optional[List[str]] = None
        if overseer:
            # A duty never widens what a login sees: the overseer reads the
            # other Manager's week inside her own areas.
            import church_team_week
            view = church_team_week.view_of(bid, str(session.user.id), role)
            out = church_team_week.within(out, view)
        out["seeing_as"] = seeing_as(bid, uid, seat[0], out)
        # How their week goes: the seen login's duties (the overseer's, only
        # the jobs in her own areas).
        out = _with_rhythm(out, biz, uid, seat[0].get("role") or "viewer")
        if overseer and view is not None and out.get("rhythm"):
            out["rhythm"] = rhythm_within(out["rhythm"], view)
        return out
    return _with_rhythm(build(biz, str(session.user.id), session.user.email or "", role), biz, str(session.user.id), role)


OVERSEER_ONLY = "Over the lanes, you see the Manager logins' weeks. An Admin's week, and the owner's, stay theirs."


def seeing_as(biz: str, uid: str, seat: Dict[str, Any], week: Dict[str, Any]) -> Dict[str, Any]:
    """Whose week a See as page is: their name (their person's, else the
    name the login gave, else the part of the email before the @, never the
    whole address), their role and their lane's label."""
    import business_users_router
    import church_duties
    try:
        who = business_users_router.seat_person(biz, uid) or {}
    except Exception:
        who = {}   # the name is a label: the week itself already read
    email = (seat.get("invited_email") or "").strip()
    name = (str(who.get("name") or "").strip() or str((week.get("me") or {}).get("name") or "").strip()
            or email.split("@")[0] or "An office login")
    lane = church_duties._seat_lane(seat) if seat.get("role") == "manager" else None
    return {"user_id": uid, "name": name, "role": seat.get("role") or "viewer",
            "lane": church_duties.lane_label(lane) if lane else None}
