"""church_areas.py — the map: every part of a church's system belongs to one area.

Kevin, 2026-10-23: "divide up the system ... so each section of the system is
viewed by specific people ... if we create media team, they would be able to
get the part when it comes to media like churchsavvy ... already setup for
them ... seats are more aligned to areas of managing the entire system:
treasurer oversees a section, Pastor oversees a section, Admin oversees a
section." The proposal is the artifact "Church Areas and Keys"
(7YRKpKa9g2DdFU9mm3WD8L); this is its step 1, the map.

    an AREA ......... AREAS: what it holds, the team that works it, who
                      usually keeps it, and what in it will need a keeper's
                      yes (step 2 enforces that; this step only names it)
    a PLACE ......... the area a role or a Serve team belongs to: the
                      church's own pick (church_area_places), else a guess
                      from its words, else its job; unplaced says so
    WHO'S IN IT ..... read live from where each kind of person already
                      lives: ChurchSavvy's team (worship_team), the Lead tab
                      roles (church_leader_roles), kids workers
                      (space_leaders), group leaders (group_members), the
                      safety officers, and the office logins (seats)

This step grants nothing. It reads who can already reach each area and
says so plainly, including where a login reaches further than its job:
every office login reads member records, and every admin login sees who
gave what. A failed read is a 503, never an empty area.

  GET /church/areas?business_id=     the map and its people (a manager seat)
  PUT /church/areas/place            {business_id, kind, key, area} (an admin;
                                     area null puts it back to the guess)

Switched by CHURCH_AREAS: off | owner | on (owner until a Thursday).
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
from auth_supabase import AuthedUser, UserSession
from business_access import assert_access, business_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church", tags=["church"])


# ─── The areas ────────────────────────────────────────────────────────

AREA_ORDER = ("worship_media", "people_care", "giving_money", "kids_youth", "groups_classes",
              "messages_safety", "website_outreach", "office")

AREAS: Dict[str, Dict[str, Any]] = {
    "worship_media": {
        "label": "Worship & media",
        "holds": ["ChurchSavvy: songs, Sundays and the screens", "Sermons", "The livestream and replays",
                  "The media library"],
        "team": "Media team",
        "keeper": "Worship pastor or media director",
        "guarded": [],
    },
    "people_care": {
        "label": "People & care",
        "holds": ["Member records", "Cards and follow-up", "Care", "Prayer", "Shepherding"],
        "team": "Welcome, care and prayer teams",
        "keeper": "Pastor",
        "guarded": ["Pastors-only notes and prayer"],
    },
    "giving_money": {
        "label": "Giving & money",
        "holds": ["Gifts and funds", "Giving statements", "The books", "The bank and payouts"],
        "team": "Counting team",
        "keeper": "Treasurer, with a second keeper",
        "guarded": ["Who gave what", "The bank", "Payouts"],
    },
    "kids_youth": {
        "label": "Kids & youth",
        "holds": ["Kids check-in", "Rooms", "Approved adults"],
        "team": "Kids workers",
        "keeper": "Kids director",
        "guarded": ["Medical and custody notes"],
    },
    "groups_classes": {
        "label": "Groups & classes",
        "holds": ["Groups", "Classes", "Gatherings and study", "The leaders room"],
        "team": "Group leaders and teachers",
        "keeper": "Groups pastor",
        "guarded": ["A group's private chat"],
    },
    "messages_safety": {
        "label": "Messages & safety",
        "holds": ["Chat rules", "Held messages", "Reports"],
        "team": "Safety officers",
        "keeper": "The two safety officers",
        "guarded": ["Opening a whole chat"],
    },
    "website_outreach": {
        "label": "Website & outreach",
        "holds": ["The website", "Events", "Flyers", "The marketing desk"],
        "team": "Communications team",
        "keeper": "Admin",
        "guarded": [],
    },
    "office": {
        "label": "Office",
        "holds": ["Office logins", "Billing", "Connections", "Settings"],
        "team": "Office staff",
        "keeper": "Admin",
        "guarded": ["Changing who keeps what"],
    },
}


# ─── Places: which area a role or a team belongs to ──────────────────

# Words in a title or a team's name, in order: the first area that matches
# wins. Outreach comes before media so "Social media" and "Graphic and web
# design" are communications, and media before people so "Worship Pastor"
# and "Minister of Music" are media.
_AREA_WORDS: Tuple[Tuple[str, str], ...] = (
    ("website_outreach", r"\bweb|social|communicat|marketing|outreach|evangel|\bevents?\b|\bdesign|newsletter|announce"),
    ("worship_media", r"media|\btech|sound|audio|\ba/?v\b|video|camera|stream|broadcast|production|lighting|"
                      r"\blights?\b|projection|slides|photo|worship|music|choir|praise|\bband\b|psalm|creative|\barts?\b"),
    ("kids_youth", r"\bkids?\b|child|youth|\bteens?\b|nursery|student|\bywd\b|\bvbs\b"),
    ("giving_money", r"treasur|financ|\bcount|stewardship|budget|bookkeep|accountant|trustee"),
    ("groups_classes", r"\bgroups?\b|\bclass|teach|bible study|school|discipl|academy"),
    ("office", r"clerk|secretar|\badmin|\boffice|receptionist"),
    ("people_care", r"greet|usher|welcome|hospitality|guest|parking|connect|\bcare\b|prayer|interces|benevol|"
                    r"visit|mother|deacon|pastor|elder|minister|chaplain|shepherd|bishop"),
)
# A job whose work lives in one place stays there whatever its title says.
_JOB_FIXED = {"kids": "kids_youth", "teach": "groups_classes"}
# Otherwise the job is the fallback when the words say nothing.
_JOB_AREA = {"senior": "people_care", "pastoral": "people_care", "prayer": "people_care", "care": "people_care",
             "welcome": "people_care", "office": "office"}
KINDS = ("role", "team")


def guess_area(text: str) -> Optional[Tuple[str, str]]:
    """The area the words in a title or a team's name point to, and the word
    that decided it. None when they say nothing."""
    t = (text or "").casefold()
    for area, rx in _AREA_WORDS:
        m = re.search(rx, t)
        if m:
            return area, m.group(0).strip()
    return None


def place_role(d: Dict[str, Any], places: Dict[Tuple[str, str], str]) -> Dict[str, Any]:
    """Where a role belongs, and why: {area, why, by} with `by` one of
    church (its own pick), words, job; area None when nothing places it."""
    picked = places.get(("role", d.get("key") or ""))
    if picked in AREAS:
        return {"area": picked, "by": "church", "why": "Your church placed it here"}
    job = d.get("job") or ""
    if job in _JOB_FIXED:
        return {"area": _JOB_FIXED[job], "by": "job", "why": "Its job works here"}
    words = " ".join([d.get("title") or ""] + list(d.get("oversees_teams") or []))
    hit = guess_area(words)
    if hit:
        return {"area": hit[0], "by": "words", "why": f"Chief's guess, from “{hit[1]}”"}
    if job in _JOB_AREA:
        return {"area": _JOB_AREA[job], "by": "job", "why": "Its job works here"}
    return {"area": None, "by": "", "why": "Nothing says where it belongs yet"}


def place_team(name: str, places: Dict[Tuple[str, str], str]) -> Dict[str, Any]:
    picked = places.get(("team", team_key(name)))
    if picked in AREAS:
        return {"area": picked, "by": "church", "why": "Your church placed it here"}
    hit = guess_area(name)
    if hit:
        return {"area": hit[0], "by": "words", "why": f"Chief's guess, from “{hit[1]}”"}
    return {"area": None, "by": "", "why": "Nothing says where it belongs yet"}


def team_key(name: str) -> str:
    """A Serve team's key for a place: its name, lowercased and spaced once."""
    return re.sub(r"\s+", " ", (name or "").strip().casefold())[:80]


# Which ChurchSavvy parts a role in Worship & media would start with, from
# its title. The office still sends the invite; this only fills it in.
_PART_WORDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (r"director|pastor|\bminister|overseer|head\b|\bchair", ("admin",)),
    (r"worship|music|choir|praise|\bband\b|psalm|vocal|singer", ("worship",)),
    (r"sound|audio|\btech|\ba/?v\b|lighting|\blights?\b|projection|slides|booth|production", ("booth",)),
)


def suggested_parts(title: str) -> List[str]:
    t = (title or "").casefold()
    for rx, parts in _PART_WORDS:
        if re.search(rx, t):
            return list(parts)
    return ["planner"]


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_AREAS") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_to(user: AuthedUser) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        owner = (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()
        return (user.email or "").strip().lower() == owner
    return False


def _gate(user: AuthedUser) -> None:
    if not open_to(user):
        raise HTTPException(404, "Not Found")


# ─── Reads ────────────────────────────────────────────────────────────

def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _need(path: str) -> List[Dict[str, Any]]:
    """A read that must answer. A failed one is the whole map's 503: an area
    that couldn't be read would otherwise look like an area with nobody in it."""
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, "The areas couldn't be read just now. Try again.")
    return rows


def _places(biz: str) -> Dict[Tuple[str, str], str]:
    rows = _need(f"/church_area_places?business_id=eq.{_q(biz)}&select=kind,key,area&limit=500")
    return {(r.get("kind") or "", r.get("key") or ""): r.get("area") or "" for r in rows}


def _contacts(biz: str, ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    ids = sorted({str(i) for i in ids if i})
    if not ids:
        return {}
    rows = _need(f"/contacts?business_id=eq.{_q(biz)}&id=in.({','.join(_q(i) for i in ids)})&select=id,name,email")
    return {str(r["id"]): {"name": _plain(r.get("name")) or "Someone", "email": (r.get("email") or "").strip().lower()}
            for r in rows}


def _person(name: str, how: str, kind: str, **extra: Any) -> Dict[str, Any]:
    return {"name": _plain(name) or "Someone", "how": how, "kind": kind, **extra}


def _parts_words(parts: Iterable[str]) -> str:
    from worship_team import ROLE_LABEL, ROLES
    have = [ROLE_LABEL[p] for p in ROLES if p in set(parts or [])]
    return ", ".join(have)


def build(business: Dict[str, Any]) -> Dict[str, Any]:
    """The whole map for one church: each area with the people who work it,
    who reaches it through an office login, and what's missing."""
    import church_roles as cr
    biz = str(business["id"])
    settings = business.get("settings") if isinstance(business.get("settings"), dict) else {}
    owner_name = _plain(settings.get("practitioner_name")) or "The account owner"

    places = _places(biz)
    if cr.ensure_library(business) is None:
        raise HTTPException(503, "The areas couldn't be read just now. Try again.")
    defs = _need(f"/church_role_defs?business_id=eq.{_q(biz)}&status=eq.active"
                 "&select=id,key,title,job,oversees_teams&order=sort.asc,title.asc&limit=300")
    holders = _need(f"/church_leader_roles?business_id=eq.{_q(biz)}&status=in.(active,invited)"
                    "&select=contact_id,role,scope,status&limit=1000")
    team = _need(f"/worship_team?business_id=eq.{_q(biz)}&status=in.(invited,active)"
                 "&select=name,email,roles,status&order=invited_at.asc&limit=100")
    seats = _need(f"/business_users?business_id=eq.{_q(biz)}&status=eq.active&select=invited_email,role,user_id&limit=200")
    accountants = _need(f"/business_collaborators?business_id=eq.{_q(biz)}&status=eq.active&role=eq.accountant"
                        "&select=invited_email&limit=50")
    kids = _need(f"/space_leaders?business_id=eq.{_q(biz)}&select=contact_id,space,background_check_on&limit=500")
    groups = _need(f"/groups?business_id=eq.{_q(biz)}&active=is.true&select=id,name&order=name.asc&limit=200")
    leads = _need(f"/group_members?business_id=eq.{_q(biz)}&role=eq.leader&select=group_id,contact_id&limit=1000")
    officer_users = _need(f"/msg_safety_officers?business_id=eq.{_q(biz)}&select=user_id&limit=50")
    officer_members = _need(f"/msg_member_officers?business_id=eq.{_q(biz)}&select=contact_id&limit=50")

    import church_follow_up as cfu
    team_names = cfu.teams(biz)
    if team_names is None:
        raise HTTPException(503, "The areas couldn't be read just now. Try again.")

    people = _contacts(biz, [h.get("contact_id") for h in holders] + [k.get("contact_id") for k in kids]
                       + [x.get("contact_id") for x in leads] + [o.get("contact_id") for o in officer_members])
    by_key = {d["key"]: d for d in defs}
    role_place = {d["key"]: place_role(d, places) for d in defs}

    area_people: Dict[str, List[Dict[str, Any]]] = {a: [] for a in AREA_ORDER}
    reach: Dict[str, List[Dict[str, Any]]] = {a: [] for a in AREA_ORDER}
    gaps: Dict[str, List[str]] = {a: [] for a in AREA_ORDER}
    suggest: List[Dict[str, Any]] = []

    # Lead tab roles. A team leader's area is their team's (its scope); any
    # other role's is the role's own place.
    team_place = {team_key(n): place_team(n, places) for n in team_names}
    on_team = {(t.get("email") or "").strip().lower() for t in team if t.get("email")}
    for h in holders:
        d = by_key.get(h.get("role") or "")
        p = people.get(str(h.get("contact_id")))
        if not d or not p:
            continue
        scope = _plain(h.get("scope"))
        where = role_place[d["key"]]
        if scope and d.get("job") == "team":
            tp = team_place.get(team_key(scope)) or place_team(scope, places)
            where = tp if tp["area"] else where
        area = where["area"]
        if not area:
            continue
        how = d["title"] + (f" · {scope}" if scope else "") + (" (asked, not yet answered)" if h.get("status") == "invited" else "")
        area_people[area].append(_person(p["name"], how, "role"))
        if (area == "worship_media" and h.get("status") == "active" and p["email"] not in on_team
                and str(h["contact_id"]) not in {s["contact_id"] for s in suggest}):
            suggest.append({"contact_id": str(h["contact_id"]), "name": p["name"], "email": p["email"],
                            "role": d["title"], "parts": suggested_parts(d["title"] + " " + scope)})

    # Worship & media: ChurchSavvy's team, and the office logins that are its admins.
    for t in team:
        status = " (invited)" if t.get("status") == "invited" else ""
        area_people["worship_media"].append(_person(t.get("name"), f"ChurchSavvy: {_parts_words(t.get('roles'))}{status}", "team"))
    if not any(t.get("status") == "active" for t in team):
        gaps["worship_media"].append("No one has joined the ChurchSavvy team yet.")

    # Kids workers.
    unchecked = 0
    for k in kids:
        p = people.get(str(k.get("contact_id")))
        if not p:
            continue
        space = _plain(k.get("space")) or "kids"
        area_people["kids_youth"].append(_person(p["name"], f"Kids check-in · {space}", "kids"))
        if not k.get("background_check_on"):
            unchecked += 1
    if unchecked:
        gaps["kids_youth"].append(f"{unchecked} kids {'worker has' if unchecked == 1 else 'workers have'} no background check date.")

    # Group leaders.
    leaderless = 0
    for g in groups:
        names = [people.get(str(x.get("contact_id")), {}).get("name") for x in leads if str(x.get("group_id")) == str(g["id"])]
        names = [n for n in names if n]
        for n in names:
            area_people["groups_classes"].append(_person(n, f"Leads {_plain(g.get('name')) or 'a group'}", "group"))
        if not names:
            leaderless += 1
    if leaderless:
        gaps["groups_classes"].append(f"{leaderless} {'group has' if leaderless == 1 else 'groups have'} no leader.")

    # Safety officers: members named from the pastors, and office logins.
    seat_by_user = {str(s.get("user_id")): s for s in seats}
    for o in officer_members:
        p = people.get(str(o.get("contact_id")))
        if p:
            area_people["messages_safety"].append(_person(p["name"], "Safety officer", "officer"))
    for o in officer_users:
        uid = str(o.get("user_id"))
        if uid == str(business.get("owner_id")):
            area_people["messages_safety"].append(_person(owner_name, "Safety officer · account owner", "officer"))
        else:
            email = (seat_by_user.get(uid) or {}).get("invited_email") or "An office login"
            area_people["messages_safety"].append(_person(email, "Safety officer · office login", "officer"))
    officers = len(officer_members) + len(officer_users)
    if officers < 2:
        gaps["messages_safety"].append(f"Messaging needs two safety officers. It has {officers}.")

    # Who reaches each area through an office login, today.
    owner = _person(owner_name, "Account owner", "owner")
    def _seat(s: Dict[str, Any]) -> Dict[str, Any]:
        return _person(s.get("invited_email") or "An office login", f"Office login · {(s.get('role') or '').title()}", "seat")
    admins = [_seat(s) for s in seats if s.get("role") == "admin"]
    managers = [_seat(s) for s in seats if s.get("role") == "manager"]
    writers = [_seat(s) for s in seats if s.get("role") in ("member", "manager", "admin")]
    every_login = [_seat(s) for s in seats]
    reach["worship_media"] = [owner] + admins + managers
    reach["people_care"] = [owner] + every_login
    reach["giving_money"] = [owner] + admins + [_person(a.get("invited_email") or "An accountant", "Accountant", "accountant")
                                                 for a in accountants]
    reach["kids_youth"] = [owner] + admins + managers
    reach["groups_classes"] = [owner] + every_login
    reach["messages_safety"] = []
    reach["website_outreach"] = [owner] + writers
    reach["office"] = [owner] + admins

    # Giving: a named treasurer has no way in except an admin login.
    for h in holders:
        d = by_key.get(h.get("role") or "")
        p = people.get(str(h.get("contact_id")))
        if d and p and h.get("status") == "active" and role_place[d["key"]]["area"] == "giving_money":
            gaps["giving_money"].append(f"{p['name']} is the {d['title']}, but the only way into Giving today is an admin login.")
    n_money = len(reach["giving_money"])
    if n_money > 3:
        gaps["giving_money"].append(f"{n_money} people can see who gave what today.")
    if every_login:
        gaps["people_care"].append(f"Every office login ({len(every_login)}) can read member records today.")

    senior = [h for h in holders if (by_key.get(h.get("role") or "") or {}).get("job") == "senior" and h.get("status") == "active"]
    if not senior:
        gaps["people_care"].append("No one holds the senior pastor's role yet.")

    unplaced = ([{"kind": "role", "key": d["key"], "name": d["title"]} for d in defs if not role_place[d["key"]]["area"]]
                + [{"kind": "team", "key": team_key(n), "name": n} for n in team_names if not team_place[team_key(n)]["area"]])

    return {
        "areas": [{"key": a, **AREAS[a], "people": area_people[a], "reach": reach[a], "gaps": gaps[a],
                   **({"suggest": suggest} if a == "worship_media" else {})} for a in AREA_ORDER],
        "roles": [{"key": d["key"], "title": d["title"], "job": d["job"], **role_place[d["key"]]} for d in defs],
        "teams": [{"key": team_key(n), "name": n, **team_place[team_key(n)]} for n in team_names],
        "unplaced": unplaced,
        "area_order": list(AREA_ORDER),
    }


# ─── Routes ───────────────────────────────────────────────────────────

@router.get("/areas")
def areas(business_id: str, session: UserSession = Depends(sb_clients.authed_request),
          biz: Dict[str, Any] = Depends(business_access("manager"))):
    # business_access resolves the same authed_request, so the sign-in is
    # checked once and both see the same person.
    _gate(session.user)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        # The map fills a church's role library; a salon gets no church roles.
        raise HTTPException(404, "The areas are for churches")
    return build(biz)


def _place_key(kind: str, key: Any) -> str:
    if kind == "team":
        k = team_key(str(key or ""))
    else:
        k = str(key or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", k):
            k = ""
    if not k:
        raise HTTPException(400, "Name the role or team to place")
    return k


@router.put("/areas/place")
def place(body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """Put a role or a Serve team in an area, or back to Chief's guess."""
    user = session.user
    _gate(user)
    body = body or {}
    try:
        biz = str(uuid.UUID(str(body.get("business_id") or "")))
    except (ValueError, TypeError):
        raise HTTPException(400, "That business id isn't valid")
    assert_access(biz, user, "admin")
    kind = body.get("kind")
    if kind not in KINDS:
        raise HTTPException(400, "Place a role or a team")
    key = _place_key(kind, body.get("key"))
    area = body.get("area")
    if area is not None and area not in AREAS:
        raise HTTPException(400, "That isn't one of the areas")
    if area is None:
        ok = sb_clients.sb_delete_as_service(
            f"/church_area_places?business_id=eq.{_q(biz)}&kind=eq.{_q(kind)}&key=eq.{_q(key)}")
        if ok is False or ok is None:
            raise HTTPException(503, "That didn't save. Try again.")
        return {"ok": True, "kind": kind, "key": key, "area": None}
    saved = sb_clients.sb_post_as_service("/church_area_places?on_conflict=business_id,kind,key", {
        "business_id": biz, "kind": kind, "key": key, "area": area,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, prefer="resolution=merge-duplicates,return=representation")
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Try again.")
    return {"ok": True, "kind": kind, "key": key, "area": area}
