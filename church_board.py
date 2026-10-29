"""church_board.py — Board & minutes: a church's boards, their meetings and the record.

Kevin, 2026-10-27, on the Church Office Prototypes ("Board & minutes" tab,
artifact 2vGqaUZUynRuiFVKuQEZWo): "lets go with your list", the board fifth.
Elders and deacons meet, decide and need a record; today the minutes live
in someone's Word file. Lane: Build, under the Build item "Love City leaves
Subsplash (M-1)".

    a BOARD ....... Elders, Deacons, Trustees, the Church council: a name,
                    its members (one of the church's people, a login, or
                    both, with a title like Chair or Secretary) and its
                    quorum: a majority of the members, or a count
    a MEETING ..... when, where (a place or a video link), and where it
                    stands: planned, in progress, minutes drafted, approved.
                    A new meeting starts its agenda with the board's open
                    items (tabled, or a follow-up) from earlier meetings,
                    each carried once
    an ITEM ....... a title, notes, files linked from Documents (the
                    church's own folder; never a new kind of file), the
                    minutes written for it, and open / done / tabled /
                    follow-up. A follow-up names who and by when, and
                    becomes a Task when the office says so
    ATTENDANCE .... present, absent or excused, one tap a person. The
                    quorum is worked out live; ending the meeting marks
                    whoever wasn't marked absent
    a DECISION .... a motion on an item: who moved and who seconded, the
                    vote (for, against, abstaining) and carried, failed or
                    tabled. Kept in a decisions log searched across years
                    ("when did we approve the roof?")
    APPROVAL ...... "Send minutes for approval" emails the draft to the
                    board's members; approving them (at the next meeting)
                    marks them approved, and approved minutes no longer
                    change

Who: the owner and admins see every board and set boards up. Anyone else
sees the boards they sit on (a member row with their login) and nothing
else; a member-level login or above writes there, a viewer reads. The menu
files it under Office (church_areas "office"), with this board-member
check on top: the office area alone opens nothing. In the member app only
the church's people on a board see it, and only their own boards: the
Board tab (member_portal_board.py, Kevin 2026-10-28) reads the agenda, and
the minutes once they're sent for approval, and writes nothing. Other
members never see a board or its minutes.

  GET    /church/board/status?business_id=            {enabled, manage, member, boards}
  GET    /church/board?business_id=                   boards, members, meetings
  GET    /church/board/people?business_id=&q=         who can join a board (owner, admins)
  POST   /church/board/boards                         {business_id, name, quorum_kind, quorum_count?}
  PATCH  /church/board/boards/{id}                    {business_id, name?, quorum_kind?, quorum_count?, archived?}
  POST   /church/board/boards/{id}/members            {business_id, contact_id? | user_id?, title?}
  PATCH  /church/board/members/{id}                   {business_id, title?, active?}
  POST   /church/board/meetings                       {business_id, board_id, starts_at, place?, video_url?, title?}
  GET    /church/board/meetings/{id}?business_id=     the meeting, its roster, quorum, agenda and decisions
  PATCH  /church/board/meetings/{id}                  {business_id, starts_at?, place?, video_url?, title?, status?}
  DELETE /church/board/meetings/{id}?business_id=     a meeting with no decisions yet
  POST   /church/board/meetings/{id}/carry            bring in the board's open items (again)
  PUT    /church/board/meetings/{id}/attendance       {business_id, member_id, status | null}
  POST   /church/board/meetings/{id}/items            {business_id, title, notes?, documents?}
  PATCH  /church/board/items/{id}                     {business_id, title?, notes?, minutes?, status?, position?,
                                                       documents?, follow_up_member?, follow_up_due?}
  DELETE /church/board/items/{id}?business_id=        an item with no decision
  POST   /church/board/items/{id}/decisions           {business_id, motion, moved_by?, seconded_by?, votes_for,
                                                       votes_against, votes_abstain, result}
  PATCH  /church/board/decisions/{id}                 the same fields
  DELETE /church/board/decisions/{id}?business_id=
  GET    /church/board/decisions?business_id=&q=&board_id=&year=   the decisions log
  POST   /church/board/meetings/{id}/send             email the draft minutes to the board's members
  POST   /church/board/meetings/{id}/approve          {business_id, in_meeting_id?}
  POST   /church/board/meetings/{id}/tasks            make Tasks from the follow-ups

Switched by CHURCH_BOARD: off | owner | on (owner until a Thursday). Until
supabase/APPLY-2026-10-27-church-board.sql is applied the status says
enabled false and every other route answers 503, never 500.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException

import business_access
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church/board", tags=["church"])

QUORUM_KINDS = ("majority", "count")
MEETING_STATUSES = ("planned", "in_progress", "drafted", "approved")
ITEM_STATUSES = ("open", "done", "tabled", "follow_up")
CARRIES = ("tabled", "follow_up")          # what an earlier meeting hands the next
ATTENDS = ("present", "absent", "excused")
RESULTS = ("carried", "failed", "tabled")
WRITERS = ("owner", "admin", "manager", "member")
BOSSES = ("owner", "admin")                # every board, and setting boards up

NAME_MAX, TITLE_MAX, MEMBER_TITLE_MAX, ITEM_MAX = 80, 120, 60, 200
NOTES_MAX, MINUTES_MAX, MOTION_MAX, PLACE_MAX, LINK_MAX = 4000, 20000, 1000, 160, 500
DOCS_MAX, VOTES_MAX, QUORUM_MAX = 20, 1000, 500
PAST_DAYS = 3 * 366                        # the board page lists three years of meetings
NOT_CHURCH = "Board & minutes are for churches"
NOT_YOURS = ("The board's pages are for the owner, admins and the board's own members. "
             "An admin can add you to a board.")

MEMBER_FIELDS = "id,board_id,contact_id,user_id,name,title,active,created_at"
MEETING_FIELDS = ("id,board_id,title,starts_at,place,video_url,status,sent_at,sent_count,approved_at,approved_by,"
                  "approved_in,created_at,updated_at")
ITEM_FIELDS = ("id,meeting_id,position,title,notes,minutes,status,documents,carried_from,follow_up_member,"
               "follow_up_due,task_id,created_at,updated_at")
DECISION_FIELDS = ("id,board_id,meeting_id,item_id,item_title,motion,moved_by,seconded_by,votes_for,votes_against,"
                   "votes_abstain,result,decided_on,created_at")

STATUS_WORDS = {"planned": "Planned", "in_progress": "In progress", "drafted": "Minutes drafted",
                "approved": "Approved"}
RESULT_WORDS = {"carried": "Carried", "failed": "Failed", "tabled": "Tabled"}


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_BOARD") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_to(user: AuthedUser) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        owner = (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()
        return (user.email or "").strip().lower() == owner
    return False


# ─── Small things ─────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _at(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _text(v: Any, most: int) -> str:
    """Words someone typed: kept as written (line breaks too), trimmed."""
    return str(v or "").replace("\r\n", "\n").strip()[:most]


def _uuid(v: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, f"That {what} isn't one we know.")


def _need(path: str) -> List[Dict[str, Any]]:
    """A read that must answer: a failed one (or the tables before their
    migration) is a 503, never an empty board."""
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, "The board's pages couldn't be read just now. Try again.")
    return rows


def _saved(got: Any, what: str = "That didn't save. Try again.") -> Dict[str, Any]:
    if not isinstance(got, list) or not got:
        raise HTTPException(503, what)
    return got[0]


def _chunks(ids: Iterable[Any], n: int = 100) -> Iterable[List[str]]:
    ids = sorted({str(i) for i in ids if i})
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def _tz(biz_id: str) -> ZoneInfo:
    try:
        import outside_calendar
        return ZoneInfo(outside_calendar.business_timezone(biz_id) or "UTC")
    except (ZoneInfoNotFoundError, ValueError, Exception):
        return ZoneInfo("UTC")


def _zone(me: Dict[str, Any]) -> ZoneInfo:
    if "tz" not in me:
        me["tz"] = _tz(str(me["biz"]["id"]))
    return me["tz"]


def _local_day(v: Any, zone: ZoneInfo) -> Optional[date]:
    d = _at(v)
    return d.astimezone(zone).date() if d else None


def when_words(v: Any, zone: ZoneInfo) -> str:
    """'Thursday, October 29, 2026 at 7:00 PM', in the church's clock."""
    d = _at(v)
    if not d:
        return ""
    d = d.astimezone(zone)
    hour = d.strftime("%I").lstrip("0") or "12"
    return f"{d:%A}, {d:%B} {d.day}, {d.year} at {hour}:{d:%M} {d:%p}"


def _int(v: Any, what: str, lo: int, hi: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise HTTPException(400, f"Enter {what} as a number.")
    if isinstance(v, bool) or not lo <= n <= hi:
        raise HTTPException(400, f"Enter {what} from {lo} to {hi}.")
    return n


# ─── Who's asking ─────────────────────────────────────────────────────

def _business(biz_id: str) -> Dict[str, Any]:
    rows = _need(f"/businesses?id=eq.{_q(biz_id)}&select=id,name,type,owner_id,settings&limit=1")
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def boards_of_login(biz_id: str, uid: str) -> Set[str]:
    """The boards this login sits on (an active member row with their
    login). A read that fails is a 503, never "none"."""
    rows = _need(f"/church_board_members?business_id=eq.{_q(biz_id)}&user_id=eq.{_q(uid)}&active=eq.true"
                 "&select=board_id&limit=200")
    return {str(r["board_id"]) for r in rows if r.get("board_id")}


def _access(business_id: Any, user: AuthedUser) -> Dict[str, Any]:
    """The church, and this login's standing on its boards. 404 when the
    switch is closed to them, they have no login here, or it isn't a
    church; 403 for a login that is neither the owner, an admin, nor on a
    board."""
    if not open_to(user):
        raise HTTPException(404, "Not Found")
    biz_id = _uuid(business_id, "church")
    role = business_access.assert_access(biz_id, user, "viewer")
    biz = _business(biz_id)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, NOT_CHURCH)
    mine = boards_of_login(biz_id, str(user.id))
    boss = role in BOSSES
    if not boss and not mine:
        raise HTTPException(403, NOT_YOURS)
    return {"biz": biz, "role": role, "uid": str(user.id), "user": user, "boss": boss, "mine": mine,
            "writer": role in WRITERS}


def _boss(me: Dict[str, Any], why: str = "Only the owner or an admin sets up the church's boards.") -> None:
    if not me["boss"]:
        raise HTTPException(403, why)


def may_see(me: Dict[str, Any], board_id: Any) -> bool:
    return me["boss"] or str(board_id) in me["mine"]


def may_write(me: Dict[str, Any], board_id: Any) -> bool:
    return me["boss"] or (str(board_id) in me["mine"] and me["writer"])


def _writes(me: Dict[str, Any], board_id: Any) -> None:
    if not may_write(me, board_id):
        raise HTTPException(403, "Your login can read this board's meetings but not change them.")


def _ready(biz_id: str) -> bool:
    """The six tables answer (one migration makes them)."""
    return isinstance(sb_clients.sb_get_as_service(
        f"/church_board_decisions?business_id=eq.{_q(biz_id)}&select=id&limit=1"), list)


# ─── Quorum ───────────────────────────────────────────────────────────

def quorum(kind: str, count: Optional[int], total: int, present: int) -> Dict[str, Any]:
    """How many make a quorum, and whether it's met. A majority is more than
    half the members (4 of 7, 4 of 6); a count is that number. A board with
    no members has no quorum to meet."""
    needed = int(count or 0) if kind == "count" else total // 2 + 1
    needed = max(1, needed)
    return {"kind": kind, "count": count if kind == "count" else None, "needed": needed, "present": present,
            "total": total, "met": total > 0 and present >= needed}


def quorum_words(kind: str, count: Optional[int]) -> str:
    return f"{count} present" if kind == "count" else "A majority of the members"


# ─── Boards and members: reading ──────────────────────────────────────

def _boards(me: Dict[str, Any], *, archived: bool = False) -> List[Dict[str, Any]]:
    biz = str(me["biz"]["id"])
    rows = _need(f"/church_boards?business_id=eq.{_q(biz)}"
                 f"{'' if archived else '&archived=eq.false'}"
                 "&select=id,name,quorum_kind,quorum_count,sort,archived,created_at&order=sort.asc,created_at.asc&limit=100")
    return [b for b in rows if may_see(me, b["id"])]


def _board(me: Dict[str, Any], board_id: Any) -> Dict[str, Any]:
    """One board of this church this login may see; any other reads as
    missing."""
    bid = _uuid(board_id, "board")
    rows = _need(f"/church_boards?id=eq.{_q(bid)}&business_id=eq.{_q(me['biz']['id'])}"
                 "&select=id,name,quorum_kind,quorum_count,sort,archived&limit=1")
    if not rows or not may_see(me, bid):
        raise HTTPException(404, "That board isn't here.")
    return rows[0]


def _members(biz_id: str, board_ids: Iterable[str], *, everyone: bool = False) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ids in _chunks(board_ids):
        out += _need(f"/church_board_members?business_id=eq.{_q(biz_id)}&board_id=in.({','.join(ids)})"
                     f"{'' if everyone else '&active=eq.true'}&select={MEMBER_FIELDS}&order=created_at.asc&limit=1000")
    names = _contact_names(biz_id, [m.get("contact_id") for m in out])
    for m in out:
        # A member who is one of the church's people goes by that name now.
        m["name"] = names.get(str(m.get("contact_id") or "")) or m.get("name") or "A member"
    return out


def _contact_names(biz_id: str, ids: Iterable[Any]) -> Dict[str, str]:
    got: Dict[str, str] = {}
    for chunk in _chunks(ids):
        for c in _need(f"/contacts?business_id=eq.{_q(biz_id)}&id=in.({','.join(chunk)})&select=id,name&limit=200"):
            if _plain(c.get("name")):
                got[str(c["id"])] = _plain(c.get("name"))
    return got


def member_view(m: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": str(m["id"]), "board_id": str(m["board_id"]), "name": m.get("name") or "A member",
            "title": m.get("title") or "", "contact_id": m.get("contact_id"), "login": bool(m.get("user_id")),
            "active": m.get("active") is not False}


def board_view(me: Dict[str, Any], b: Dict[str, Any], members: List[Dict[str, Any]]) -> Dict[str, Any]:
    mine = [member_view(m) for m in members if str(m["board_id"]) == str(b["id"]) and m.get("active") is not False]
    return {"id": str(b["id"]), "name": b.get("name") or "", "quorum_kind": b.get("quorum_kind") or "majority",
            "quorum_count": b.get("quorum_count"), "archived": bool(b.get("archived")),
            "quorum_words": quorum_words(b.get("quorum_kind") or "majority", b.get("quorum_count")),
            "quorum": quorum(b.get("quorum_kind") or "majority", b.get("quorum_count"), len(mine), 0)["needed"],
            "members": mine, "mine": str(b["id"]) in me["mine"], "write": may_write(me, b["id"])}


# ─── Meetings: reading ────────────────────────────────────────────────

def _meeting(me: Dict[str, Any], meeting_id: Any) -> Dict[str, Any]:
    mid = _uuid(meeting_id, "meeting")
    rows = _need(f"/church_board_meetings?id=eq.{_q(mid)}&business_id=eq.{_q(me['biz']['id'])}"
                 f"&select={MEETING_FIELDS}&limit=1")
    if not rows or not may_see(me, rows[0]["board_id"]):
        raise HTTPException(404, "That meeting isn't here.")
    return rows[0]


def _items(biz_id: str, meeting_ids: Iterable[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ids in _chunks(meeting_ids):
        out += _need(f"/church_board_items?business_id=eq.{_q(biz_id)}&meeting_id=in.({','.join(ids)})"
                     f"&select={ITEM_FIELDS}&order=position.asc,created_at.asc&limit=5000")
    return out


def _decisions_of(biz_id: str, meeting_ids: Iterable[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ids in _chunks(meeting_ids):
        out += _need(f"/church_board_decisions?business_id=eq.{_q(biz_id)}&meeting_id=in.({','.join(ids)})"
                     f"&select={DECISION_FIELDS}&order=created_at.asc&limit=5000")
    return out


def _attendance(biz_id: str, meeting_id: str) -> Dict[str, str]:
    rows = _need(f"/church_board_attendance?business_id=eq.{_q(biz_id)}&meeting_id=eq.{_q(meeting_id)}"
                 "&select=member_id,status&limit=1000")
    return {str(r["member_id"]): str(r.get("status")) for r in rows}


def roster(meeting: Dict[str, Any], members: List[Dict[str, Any]], marks: Dict[str, str]) -> List[Dict[str, Any]]:
    """Who the meeting counts: once the minutes are drafted, whoever was
    marked; before then, the board's members now and anyone marked who has
    since left."""
    settled = meeting.get("status") in ("drafted", "approved")
    out = []
    for m in members:
        mid = str(m["id"])
        if mid in marks or (not settled and m.get("active") is not False):
            out.append({**member_view(m), "status": marks.get(mid)})
    return out


def meeting_summary(m: Dict[str, Any], items: List[Dict[str, Any]], decisions: List[Dict[str, Any]]) -> Dict[str, Any]:
    mine = [i for i in items if str(i["meeting_id"]) == str(m["id"])]
    return {"id": str(m["id"]), "board_id": str(m["board_id"]), "title": m.get("title") or "",
            "starts_at": m.get("starts_at"), "place": m.get("place") or "", "video_url": m.get("video_url") or "",
            "status": m.get("status"), "sent_at": m.get("sent_at"), "sent_count": int(m.get("sent_count") or 0),
            "approved_at": m.get("approved_at"), "items": len(mine),
            "carried": sum(1 for i in mine if i.get("carried_from")),
            "follow_ups": sum(1 for i in mine if i.get("status") == "follow_up"),
            "decisions": sum(1 for d in decisions if str(d["meeting_id"]) == str(m["id"]))}


def page(me: Dict[str, Any]) -> Dict[str, Any]:
    biz = str(me["biz"]["id"])
    boards = _boards(me)
    ids = [str(b["id"]) for b in boards]
    members = _members(biz, ids) if ids else []
    meetings: List[Dict[str, Any]] = []
    for chunk in _chunks(ids):
        meetings += _need(f"/church_board_meetings?business_id=eq.{_q(biz)}&board_id=in.({','.join(chunk)})"
                          f"&select={MEETING_FIELDS}&order=starts_at.desc&limit=1000")
    # Three years of meetings, and any older one whose minutes aren't approved.
    since = _now() - timedelta(days=PAST_DAYS)
    meetings = [m for m in meetings if m.get("status") != "approved" or (_at(m.get("starts_at")) or since) >= since]
    mids = [str(m["id"]) for m in meetings]
    items = _items(biz, mids) if mids else []
    decisions = _decisions_of(biz, mids) if mids else []
    zone = _zone(me)
    return {
        "boards": [board_view(me, b, members) for b in boards],
        "meetings": [meeting_summary(m, items, decisions) for m in meetings],
        "me": {"manage": me["boss"], "write": any(may_write(me, i) for i in ids), "role": me["role"]},
        "tz": getattr(zone, "key", "UTC"),
    }


def _decision_view(d: Dict[str, Any], names: Dict[str, str]) -> Dict[str, Any]:
    return {"id": str(d["id"]), "item_id": str(d["item_id"]), "meeting_id": str(d["meeting_id"]),
            "board_id": str(d["board_id"]), "item_title": d.get("item_title") or "", "motion": d.get("motion") or "",
            "moved_by": d.get("moved_by"), "moved_by_name": names.get(str(d.get("moved_by") or "")),
            "seconded_by": d.get("seconded_by"), "seconded_by_name": names.get(str(d.get("seconded_by") or "")),
            "votes_for": int(d.get("votes_for") or 0), "votes_against": int(d.get("votes_against") or 0),
            "votes_abstain": int(d.get("votes_abstain") or 0), "result": d.get("result"),
            "decided_on": d.get("decided_on")}


def _item_view(i: Dict[str, Any], decisions: List[Dict[str, Any]], names: Dict[str, str],
               carried: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    docs = i.get("documents") if isinstance(i.get("documents"), list) else []
    src = carried.get(str(i.get("carried_from") or ""))
    return {"id": str(i["id"]), "position": int(i.get("position") or 0), "title": i.get("title") or "",
            "notes": i.get("notes") or "", "minutes": i.get("minutes") or "", "status": i.get("status") or "open",
            "documents": [{"path": d.get("path"), "name": d.get("name")} for d in docs if isinstance(d, dict)],
            "carried_from": src,
            "follow_up": ({"member_id": i.get("follow_up_member"), "name": names.get(str(i.get("follow_up_member") or "")),
                           "due": i.get("follow_up_due")} if i.get("follow_up_member") or i.get("follow_up_due") else None),
            "task_id": i.get("task_id"),
            "decisions": [_decision_view(d, names) for d in decisions if str(d["item_id"]) == str(i["id"])]}


def meeting_page(me: Dict[str, Any], m: Dict[str, Any]) -> Dict[str, Any]:
    """One meeting: its board, who's counted and the quorum, the agenda in
    order with each item's minutes and decisions, the earlier minutes that
    wait to be approved here, and the ones approved in it."""
    biz = str(me["biz"]["id"])
    board = _board(me, m["board_id"])
    members = _members(biz, [str(board["id"])], everyone=True)
    names = {str(x["id"]): x["name"] for x in members}
    marks = _attendance(biz, str(m["id"]))
    people = roster(m, members, marks)
    present = sum(1 for p in people if p["status"] == "present")
    items = _items(biz, [str(m["id"])])
    decisions = _decisions_of(biz, [str(m["id"])])
    # Where a carried item came from: its meeting's day.
    carried: Dict[str, Dict[str, Any]] = {}
    src_ids = [i.get("carried_from") for i in items if i.get("carried_from")]
    if src_ids:
        src_items: List[Dict[str, Any]] = []
        for chunk in _chunks(src_ids):
            src_items += _need(f"/church_board_items?business_id=eq.{_q(biz)}&id=in.({','.join(chunk)})"
                               "&select=id,meeting_id,status&limit=500")
        src_meetings: Dict[str, Dict[str, Any]] = {}
        for chunk in _chunks(s["meeting_id"] for s in src_items):
            for x in _need(f"/church_board_meetings?business_id=eq.{_q(biz)}&id=in.({','.join(chunk)})"
                           "&select=id,starts_at&limit=500"):
                src_meetings[str(x["id"])] = x
        for s in src_items:
            sm = src_meetings.get(str(s["meeting_id"])) or {}
            carried[str(s["id"])] = {"meeting_id": str(s["meeting_id"]), "starts_at": sm.get("starts_at"),
                                     "status": s.get("status")}
    # Earlier minutes of this board that wait to be approved, and the ones
    # approved in this meeting.
    waiting = _need(f"/church_board_meetings?business_id=eq.{_q(biz)}&board_id=eq.{_q(board['id'])}&status=eq.drafted"
                    f"&starts_at=lt.{_q(m['starts_at'])}&select=id,starts_at,title,sent_at&order=starts_at.desc&limit=12")
    approves = _need(f"/church_board_meetings?business_id=eq.{_q(biz)}&approved_in=eq.{_q(m['id'])}"
                     "&select=id,starts_at,title&order=starts_at.asc&limit=12")
    approved_in = None
    if m.get("approved_in"):
        got = _need(f"/church_board_meetings?business_id=eq.{_q(biz)}&id=eq.{_q(m['approved_in'])}"
                    "&select=id,starts_at,title&limit=1")
        approved_in = got[0] if got else None
    write = may_write(me, board["id"])
    return {
        "meeting": {**meeting_summary(m, items, decisions), "approved_in": approved_in},
        "board": board_view(me, board, members),
        "roster": people,
        "quorum": quorum(board.get("quorum_kind") or "majority", board.get("quorum_count"), len(people), present),
        "items": [_item_view(i, decisions, names, carried) for i in items],
        "waiting": waiting, "approves": approves,
        "can": {"write": write and m.get("status") != "approved", "manage": me["boss"],
                "notice": write and m.get("status") in ("planned", "in_progress")},
        "tz": getattr(_zone(me), "key", "UTC"),
    }


# ─── Boards and members: writing ──────────────────────────────────────

def _quorum_fields(body: Dict[str, Any], have: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    kind = body.get("quorum_kind", (have or {}).get("quorum_kind") or "majority")
    if kind not in QUORUM_KINDS:
        raise HTTPException(400, "A quorum is a majority of the members, or a count.")
    out["quorum_kind"] = kind
    if kind == "count":
        raw = body.get("quorum_count", (have or {}).get("quorum_count"))
        out["quorum_count"] = _int(raw, "the quorum", 1, QUORUM_MAX)
    else:
        out["quorum_count"] = None
    return out


def add_board(me: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    _boss(me)
    biz = str(me["biz"]["id"])
    name = _plain(body.get("name"))[:NAME_MAX]
    if not name:
        raise HTTPException(400, "Name the board: Elders, Deacons, Trustees.")
    have = _need(f"/church_boards?business_id=eq.{_q(biz)}&archived=eq.false&select=id,name,sort&limit=100")
    if any(_plain(b.get("name")).lower() == name.lower() for b in have):
        raise HTTPException(409, f"Your church already has a board called {name}.")
    now = _iso(_now())
    row = _saved(sb_clients.sb_post_as_service("/church_boards", {
        "business_id": biz, "name": name, **_quorum_fields(body),
        "sort": max([int(b.get("sort") or 0) for b in have] + [0]) + 1,
        "created_by": me["uid"], "created_at": now, "updated_at": now}), "That board didn't save. Try again.")
    return {"board": board_view(me, row, [])}


def edit_board(me: Dict[str, Any], board_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    _boss(me)
    b = _board(me, board_id)
    fields: Dict[str, Any] = {}
    if "name" in body:
        name = _plain(body.get("name"))[:NAME_MAX]
        if not name:
            raise HTTPException(400, "Name the board: Elders, Deacons, Trustees.")
        fields["name"] = name
    if "quorum_kind" in body or "quorum_count" in body:
        fields.update(_quorum_fields(body, b))
    if "archived" in body:
        fields["archived"] = body.get("archived") is True
    if fields:
        fields["updated_at"] = _iso(_now())
        b = _saved(sb_clients.sb_patch_as_service(
            f"/church_boards?id=eq.{_q(b['id'])}&business_id=eq.{_q(me['biz']['id'])}", fields))
    members = _members(str(me["biz"]["id"]), [str(b["id"])])
    return {"board": board_view(me, b, members)}


def _seat_emails(biz: Dict[str, Any]) -> Dict[str, str]:
    """Each login's sign-in email (the owner's too): uid → email."""
    seats = _need(f"/business_users?business_id=eq.{_q(biz['id'])}&status=eq.active"
                  "&select=user_id,invited_email&limit=500")
    out = {str(s["user_id"]): str(s.get("invited_email") or "").strip().lower() for s in seats if s.get("user_id")}
    owner = str(biz.get("owner_id") or "")
    if owner:
        out[owner] = owner_email(owner)
    return out


def owner_email(uid: str) -> str:
    """The owner's sign-in email ("" when it can't be read)."""
    try:
        import messaging_router
        return str(messaging_router._owner_email(uid) or "").strip().lower()
    except Exception:
        return ""


def _logins(biz: Dict[str, Any], uid: str) -> List[Dict[str, Any]]:
    import church_my_week
    return church_my_week.people(biz, uid)


def people(me: Dict[str, Any], q: str) -> Dict[str, Any]:
    """Who can join a board: the church's logins, and its people by name."""
    _boss(me)
    biz = str(me["biz"]["id"])
    logins = [{"user_id": p["user_id"], "name": p["name"], "role": p.get("role")} for p in _logins(me["biz"], me["uid"])]
    words = _plain(q)[:60]
    found: List[Dict[str, Any]] = []
    if len(words) >= 2:
        pat = re.sub(r"[^\w\s'.-]", "", words).replace(" ", "*")
        if pat:
            found = _need(f"/contacts?business_id=eq.{_q(biz)}&name=ilike.*{_q(pat)}*&select=id,name,email"
                          "&order=name.asc&limit=12")
    return {"logins": logins, "contacts": [{"id": str(c["id"]), "name": _plain(c.get("name")),
                                            "email": bool(c.get("email"))} for c in found if _plain(c.get("name"))]}


def add_member(me: Dict[str, Any], board_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """One of the church's people or one of its logins joins a board. A
    person whose email is a login's is linked to that login, so a deacon
    who signs in sees their board."""
    _boss(me)
    biz = me["biz"]
    biz_id = str(biz["id"])
    b = _board(me, board_id)
    title = _plain(body.get("title"))[:MEMBER_TITLE_MAX]
    emails = _seat_emails(biz)
    cid = uid = None
    name = ""
    if body.get("contact_id"):
        cid = _uuid(body["contact_id"], "person")
        rows = _need(f"/contacts?id=eq.{_q(cid)}&business_id=eq.{_q(biz_id)}&select=id,name,email&limit=1")
        if not rows:
            raise HTTPException(400, "That person isn't one of this church's people.")
        name = _plain(rows[0].get("name"))
        email = str(rows[0].get("email") or "").strip().lower()
        if email:
            uid = next((u for u, e in emails.items() if e and e == email), None)
    elif body.get("user_id"):
        uid = _uuid(body["user_id"], "login")
        if uid not in emails:
            raise HTTPException(400, "That login isn't one of this church's.")
        name = next((p["name"] for p in _logins(biz, me["uid"]) if str(p["user_id"]) == uid), "")
        email = emails.get(uid) or ""
        if email:
            exact = email.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            rows = _need(f"/contacts?business_id=eq.{_q(biz_id)}&email=ilike.{_q(exact)}&select=id,name&limit=1")
            if rows:
                cid, name = str(rows[0]["id"]), _plain(rows[0].get("name")) or name
    else:
        raise HTTPException(400, "Pick someone from your people, or one of your logins.")
    have = _need(f"/church_board_members?business_id=eq.{_q(biz_id)}&board_id=eq.{_q(b['id'])}"
                 f"&select={MEMBER_FIELDS}&limit=1000")
    same = [m for m in have if (cid and str(m.get("contact_id") or "") == cid) or (uid and str(m.get("user_id") or "") == uid)]
    now = _iso(_now())
    if any(m.get("active") is not False for m in same):
        raise HTTPException(409, f"{name or 'They'} already sit{'s' if name else ''} on the {b['name']}.")
    if same:
        # They sat on it before: back, with their old minutes still theirs.
        row = _saved(sb_clients.sb_patch_as_service(
            f"/church_board_members?id=eq.{_q(same[0]['id'])}&business_id=eq.{_q(biz_id)}",
            {"active": True, "title": title, "contact_id": cid or same[0].get("contact_id"),
             "user_id": uid or same[0].get("user_id"), "name": name or same[0].get("name"), "updated_at": now}))
    else:
        row = _saved(sb_clients.sb_post_as_service("/church_board_members", {
            "business_id": biz_id, "board_id": str(b["id"]), "contact_id": cid, "user_id": uid,
            "name": (name or "A member")[:120], "title": title, "active": True, "created_at": now, "updated_at": now}))
    return {"member": member_view(row)}


def edit_member(me: Dict[str, Any], member_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """A title, or leaving the board (active false). Leaving keeps the row,
    so past minutes keep the name."""
    _boss(me)
    biz = str(me["biz"]["id"])
    mid = _uuid(member_id, "member")
    rows = _need(f"/church_board_members?id=eq.{_q(mid)}&business_id=eq.{_q(biz)}&select={MEMBER_FIELDS}&limit=1")
    if not rows:
        raise HTTPException(404, "That member isn't here.")
    fields: Dict[str, Any] = {}
    if "title" in body:
        fields["title"] = _plain(body.get("title"))[:MEMBER_TITLE_MAX]
    if "active" in body:
        fields["active"] = body.get("active") is True
    if not fields:
        return {"member": member_view(rows[0])}
    fields["updated_at"] = _iso(_now())
    row = _saved(sb_clients.sb_patch_as_service(f"/church_board_members?id=eq.{_q(mid)}&business_id=eq.{_q(biz)}", fields))
    return {"member": member_view(row)}


# ─── Meetings: writing ────────────────────────────────────────────────

def _when(v: Any) -> str:
    d = _at(v)
    if not d or d.year < 2000 or d.year > 2100:
        raise HTTPException(400, "Pick the day and time of the meeting.")
    return _iso(d)


def _link(v: Any) -> str:
    s = _plain(v)[:LINK_MAX]
    if s and not re.match(r"^https://\S+$", s):
        raise HTTPException(400, "A video link starts with https://.")
    return s


def _meeting_fields(body: Dict[str, Any], *, partial: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not partial or "starts_at" in body:
        out["starts_at"] = _when(body.get("starts_at"))
    if "place" in body:
        out["place"] = _plain(body.get("place"))[:PLACE_MAX]
    if "video_url" in body:
        out["video_url"] = _link(body.get("video_url"))
    if "title" in body:
        out["title"] = _plain(body.get("title"))[:TITLE_MAX]
    return out


def _settled(m: Dict[str, Any]) -> None:
    if m.get("status") == "approved":
        raise HTTPException(409, "These minutes were approved, so they no longer change.")


def add_meeting(me: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    b = _board(me, body.get("board_id"))
    _writes(me, b["id"])
    if b.get("archived"):
        raise HTTPException(409, "That board was closed. Open it again first.")
    biz = str(me["biz"]["id"])
    now = _iso(_now())
    m = _saved(sb_clients.sb_post_as_service("/church_board_meetings", {
        "business_id": biz, "board_id": str(b["id"]), "title": "", "place": "", "video_url": "",
        **_meeting_fields(body, partial=False), "status": "planned", "created_by": me["uid"],
        "created_at": now, "updated_at": now}), "That meeting didn't save. Try again.")
    carried = carry_forward(me, m)
    return {**meeting_page(me, m), "carried": carried}


def carry_forward(me: Dict[str, Any], m: Dict[str, Any]) -> int:
    """Bring the board's open items (tabled, or a follow-up) from its earlier
    meetings onto this one's agenda. Each item is carried once, ever
    (carried_from is unique): pressing twice, or a later meeting, finds it
    already carried. Returns how many came in."""
    _settled(m)
    biz = str(me["biz"]["id"])
    earlier = _need(f"/church_board_meetings?business_id=eq.{_q(biz)}&board_id=eq.{_q(m['board_id'])}"
                    f"&starts_at=lt.{_q(m['starts_at'])}&id=neq.{_q(m['id'])}&select=id,starts_at"
                    "&order=starts_at.desc&limit=60")
    if not earlier:
        return 0
    open_items: List[Dict[str, Any]] = []
    for chunk in _chunks(e["id"] for e in earlier):
        open_items += _need(f"/church_board_items?business_id=eq.{_q(biz)}&meeting_id=in.({','.join(chunk)})"
                            f"&status=in.({','.join(CARRIES)})&select={ITEM_FIELDS}&order=position.asc&limit=2000")
    if not open_items:
        return 0
    done: Set[str] = set()
    for chunk in _chunks(i["id"] for i in open_items):
        done |= {str(x.get("carried_from")) for x in _need(
            f"/church_board_items?business_id=eq.{_q(biz)}&carried_from=in.({','.join(chunk)})&select=carried_from&limit=2000")}
    # Oldest meeting first, then their own order.
    order = {str(e["id"]): str(e.get("starts_at") or "") for e in earlier}
    todo = sorted((i for i in open_items if str(i["id"]) not in done),
                  key=lambda i: (order.get(str(i["meeting_id"]), ""), int(i.get("position") or 0)))
    if not todo:
        return 0
    here = _items(biz, [str(m["id"])])
    pos = max([int(i.get("position") or 0) for i in here] + [0])
    now = _iso(_now())
    rows = []
    for n, i in enumerate(todo, start=1):
        rows.append({"business_id": biz, "meeting_id": str(m["id"]), "position": min(10000, pos + n),
                     "title": i.get("title") or "An open item", "notes": i.get("notes") or "", "minutes": "",
                     "status": "open", "documents": i.get("documents") or [], "carried_from": str(i["id"]),
                     "follow_up_member": i.get("follow_up_member"), "follow_up_due": i.get("follow_up_due"),
                     # A follow-up that already became a task keeps it: "Make
                     # tasks" at the next meeting doesn't make it twice.
                     "task_id": i.get("task_id"), "created_at": now, "updated_at": now})
    got = sb_clients.sb_post_as_service("/church_board_items?on_conflict=carried_from", rows,
                                        prefer="resolution=ignore-duplicates,return=representation")
    if not isinstance(got, list):
        raise HTTPException(503, "The open items didn't come across. Try again.")
    return len(got)


def edit_meeting(me: Dict[str, Any], meeting_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """The day, the place, the link, the title; and the meeting's own steps:
    start it (planned → in progress), end it (in progress → minutes drafted,
    with whoever wasn't marked marked absent), or open a draft again.
    Approved minutes are approved through /approve and change no more."""
    m = _meeting(me, meeting_id)
    _writes(me, m["board_id"])
    _settled(m)
    biz = str(me["biz"]["id"])
    fields = _meeting_fields(body, partial=True)
    status = body.get("status")
    if status is not None and status != m["status"]:
        steps = {("planned", "in_progress"), ("in_progress", "planned"), ("in_progress", "drafted"),
                 ("drafted", "in_progress")}
        if (m["status"], status) not in steps:
            raise HTTPException(400, "A meeting goes planned, in progress, minutes drafted; approving is its own step.")
        if status == "drafted":
            _mark_rest_absent(me, m)
        fields["status"] = status
    if not fields:
        return meeting_page(me, m)
    fields["updated_at"] = _iso(_now())
    got = sb_clients.sb_patch_as_service(
        f"/church_board_meetings?id=eq.{_q(m['id'])}&business_id=eq.{_q(biz)}&status=eq.{_q(m['status'])}", fields)
    if not isinstance(got, list):
        raise HTTPException(503, "That didn't save. Try again.")
    if not got:
        raise HTTPException(409, "Someone changed this meeting just now. Open it again.")
    return meeting_page(me, got[0])


def _mark_rest_absent(me: Dict[str, Any], m: Dict[str, Any]) -> None:
    biz = str(me["biz"]["id"])
    members = _members(biz, [str(m["board_id"])])
    marks = _attendance(biz, str(m["id"]))
    now = _iso(_now())
    rows = [{"business_id": biz, "meeting_id": str(m["id"]), "member_id": str(x["id"]), "status": "absent",
             "marked_by": me["uid"], "marked_at": now} for x in members if str(x["id"]) not in marks]
    if rows and not isinstance(sb_clients.sb_post_as_service(
            "/church_board_attendance?on_conflict=meeting_id,member_id", rows,
            prefer="resolution=ignore-duplicates,return=representation"), list):
        raise HTTPException(503, "Attendance didn't save, so the meeting is still open. Try again.")


def delete_meeting(me: Dict[str, Any], meeting_id: str) -> Dict[str, Any]:
    m = _meeting(me, meeting_id)
    _writes(me, m["board_id"])
    if m.get("status") not in ("planned", "in_progress"):
        raise HTTPException(409, "A meeting with drafted minutes stays in the record.")
    biz = str(me["biz"]["id"])
    if _need(f"/church_board_decisions?business_id=eq.{_q(biz)}&meeting_id=eq.{_q(m['id'])}&select=id&limit=1"):
        raise HTTPException(409, "This meeting has decisions recorded. Take them out first.")
    if not sb_clients.sb_delete_as_service(f"/church_board_meetings?id=eq.{_q(m['id'])}&business_id=eq.{_q(biz)}"):
        raise HTTPException(503, "Nothing was removed. Try again.")
    return {"ok": True}


def mark(me: Dict[str, Any], meeting_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """One tap: present, absent or excused for one member (null clears it).
    Answers the quorum as it now stands."""
    m = _meeting(me, meeting_id)
    _writes(me, m["board_id"])
    _settled(m)
    biz = str(me["biz"]["id"])
    mid = _uuid(body.get("member_id"), "member")
    members = _members(biz, [str(m["board_id"])], everyone=True)
    if not any(str(x["id"]) == mid for x in members):
        raise HTTPException(400, "That person isn't on this board.")
    status = body.get("status")
    path = f"/church_board_attendance?business_id=eq.{_q(biz)}&meeting_id=eq.{_q(m['id'])}&member_id=eq.{_q(mid)}"
    if status is None:
        if not sb_clients.sb_delete_as_service(path):
            raise HTTPException(503, "That didn't save. Try again.")
    else:
        if status not in ATTENDS:
            raise HTTPException(400, "Mark them present, absent or excused.")
        _saved(sb_clients.sb_post_as_service("/church_board_attendance?on_conflict=meeting_id,member_id", {
            "business_id": biz, "meeting_id": str(m["id"]), "member_id": mid, "status": status,
            "marked_by": me["uid"], "marked_at": _iso(_now())}, prefer="resolution=merge-duplicates,return=representation"))
    board = _board(me, m["board_id"])
    people = roster(m, members, _attendance(biz, str(m["id"])))
    present = sum(1 for p in people if p["status"] == "present")
    return {"member_id": mid, "status": status,
            "quorum": quorum(board.get("quorum_kind") or "majority", board.get("quorum_count"), len(people), present)}


# ─── Agenda items ─────────────────────────────────────────────────────

def _documents(biz_id: str, v: Any) -> List[Dict[str, str]]:
    """Files linked from Documents: paths in this church's own folder of the
    business-documents bucket, as the Documents page stores them."""
    if not isinstance(v, list) or len(v) > DOCS_MAX:
        raise HTTPException(400, f"Link up to {DOCS_MAX} files from Documents.")
    out: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for d in v:
        path = str((d or {}).get("path") if isinstance(d, dict) else d or "").strip()
        if (not path.startswith(f"{biz_id}/") or ".." in path or "\\" in path or len(path) > 500
                or path.endswith("/")):
            raise HTTPException(400, "That file isn't one of this church's documents.")
        if path in seen:
            continue
        seen.add(path)
        name = _plain(d.get("name") if isinstance(d, dict) else "")[:160]
        if not name:
            name = re.sub(r"^\d{10,}-", "", path.rsplit("/", 1)[-1])
        out.append({"path": path, "name": name})
    return out


def _item(me: Dict[str, Any], item_id: Any) -> Dict[str, Any]:
    """An item, with its meeting, in this church and on a board this login
    sees."""
    iid = _uuid(item_id, "item")
    rows = _need(f"/church_board_items?id=eq.{_q(iid)}&business_id=eq.{_q(me['biz']['id'])}&select={ITEM_FIELDS}&limit=1")
    if not rows:
        raise HTTPException(404, "That item isn't here.")
    m = _meeting(me, rows[0]["meeting_id"])
    return {**rows[0], "_meeting": m}


def add_item(me: Dict[str, Any], meeting_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    m = _meeting(me, meeting_id)
    _writes(me, m["board_id"])
    _settled(m)
    biz = str(me["biz"]["id"])
    title = _plain(body.get("title"))[:ITEM_MAX]
    if not title:
        raise HTTPException(400, "Give the item a title, like Roof bids.")
    here = _items(biz, [str(m["id"])])
    now = _iso(_now())
    row = _saved(sb_clients.sb_post_as_service("/church_board_items", {
        "business_id": biz, "meeting_id": str(m["id"]),
        "position": min(10000, max([int(i.get("position") or 0) for i in here] + [0]) + 1),
        "title": title, "notes": _text(body.get("notes"), NOTES_MAX), "minutes": "", "status": "open",
        "documents": _documents(biz, body.get("documents") or []), "created_at": now, "updated_at": now}),
        "That item didn't save. Try again.")
    return {"item": row["id"], **meeting_page(me, m)}


def _follow_member(me: Dict[str, Any], m: Dict[str, Any], v: Any) -> Optional[str]:
    if v in (None, ""):
        return None
    mid = _uuid(v, "member")
    members = _members(str(me["biz"]["id"]), [str(m["board_id"])], everyone=True)
    if not any(str(x["id"]) == mid for x in members):
        raise HTTPException(400, "Pick someone on this board for the follow-up.")
    return mid


def _day(v: Any) -> Optional[str]:
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        raise HTTPException(400, "Pick the day it's due.")


def edit_item(me: Dict[str, Any], item_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    i = _item(me, item_id)
    m = i["_meeting"]
    _writes(me, m["board_id"])
    _settled(m)
    biz = str(me["biz"]["id"])
    fields: Dict[str, Any] = {}
    if "title" in body:
        title = _plain(body.get("title"))[:ITEM_MAX]
        if not title:
            raise HTTPException(400, "Give the item a title, like Roof bids.")
        fields["title"] = title
    if "notes" in body:
        fields["notes"] = _text(body.get("notes"), NOTES_MAX)
    if "minutes" in body:
        fields["minutes"] = _text(body.get("minutes"), MINUTES_MAX)
    if "status" in body:
        if body.get("status") not in ITEM_STATUSES:
            raise HTTPException(400, "An item is open, done, tabled or a follow-up.")
        fields["status"] = body["status"]
    if "position" in body:
        fields["position"] = _int(body.get("position"), "the item's place", 0, 10000)
    if "documents" in body:
        fields["documents"] = _documents(biz, body.get("documents") or [])
    if "follow_up_member" in body:
        fields["follow_up_member"] = _follow_member(me, m, body.get("follow_up_member"))
    if "follow_up_due" in body:
        fields["follow_up_due"] = _day(body.get("follow_up_due"))
    if fields:
        fields["updated_at"] = _iso(_now())
        _saved(sb_clients.sb_patch_as_service(f"/church_board_items?id=eq.{_q(i['id'])}&business_id=eq.{_q(biz)}", fields))
        if "title" in fields:
            # The log keeps the item's title for its search: the new one.
            sb_clients.sb_patch_as_service(f"/church_board_decisions?item_id=eq.{_q(i['id'])}&business_id=eq.{_q(biz)}",
                                           {"item_title": fields["title"], "updated_at": fields["updated_at"]})
    return meeting_page(me, m)


def delete_item(me: Dict[str, Any], item_id: str) -> Dict[str, Any]:
    i = _item(me, item_id)
    m = i["_meeting"]
    _writes(me, m["board_id"])
    _settled(m)
    biz = str(me["biz"]["id"])
    if _need(f"/church_board_decisions?business_id=eq.{_q(biz)}&item_id=eq.{_q(i['id'])}&select=id&limit=1"):
        raise HTTPException(409, "This item has a decision recorded. Take the decision out first.")
    if not sb_clients.sb_delete_as_service(f"/church_board_items?id=eq.{_q(i['id'])}&business_id=eq.{_q(biz)}"):
        raise HTTPException(503, "Nothing was removed. Try again.")
    return meeting_page(me, m)


# ─── Decisions ────────────────────────────────────────────────────────

def _decision_fields(me: Dict[str, Any], m: Dict[str, Any], body: Dict[str, Any], *, partial: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not partial or "motion" in body:
        motion = _text(body.get("motion"), MOTION_MAX)
        if not motion:
            raise HTTPException(400, "Say the motion, like: Accept Northside Roofing's bid of $18,400.")
        out["motion"] = motion
    members = None
    for k in ("moved_by", "seconded_by"):
        if k in body:
            if body.get(k) in (None, ""):
                out[k] = None
                continue
            mid = _uuid(body[k], "member")
            if members is None:
                members = _members(str(me["biz"]["id"]), [str(m["board_id"])], everyone=True)
            if not any(str(x["id"]) == mid for x in members):
                raise HTTPException(400, "Who moved and who seconded are members of this board.")
            out[k] = mid
    if out.get("moved_by") and out.get("moved_by") == out.get("seconded_by"):
        raise HTTPException(400, "Someone else seconds the motion.")
    for k, what in (("votes_for", "the votes for"), ("votes_against", "the votes against"),
                    ("votes_abstain", "those abstaining")):
        if not partial or k in body:
            out[k] = _int(body.get(k) or 0, what, 0, VOTES_MAX)
    if not partial or "result" in body:
        if body.get("result") not in RESULTS:
            raise HTTPException(400, "The motion carried, failed or was tabled.")
        out["result"] = body["result"]
    return out


def add_decision(me: Dict[str, Any], item_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """A motion on an item, with its vote and result. A tabled motion tables
    the item (so it carries to the next meeting); one that carried or failed
    settles an open item."""
    i = _item(me, item_id)
    m = i["_meeting"]
    _writes(me, m["board_id"])
    _settled(m)
    biz = str(me["biz"]["id"])
    fields = _decision_fields(me, m, body, partial=False)
    now = _iso(_now())
    day = _local_day(m.get("starts_at"), _zone(me)) or _now().date()
    _saved(sb_clients.sb_post_as_service("/church_board_decisions", {
        "business_id": biz, "board_id": str(m["board_id"]), "meeting_id": str(m["id"]), "item_id": str(i["id"]),
        "item_title": (i.get("title") or "")[:ITEM_MAX], "moved_by": None, "seconded_by": None, **fields,
        "decided_on": day.isoformat(), "created_by": me["uid"], "created_at": now, "updated_at": now}),
        "That decision didn't save. Try again.")
    resettle(biz, str(i["id"]))
    return meeting_page(me, m)


def resettle(biz: str, item_id: str) -> None:
    """An item follows its latest decision: tabled carries it to the next
    meeting, carried or failed settles it, and with no decision left it's
    open again. A follow-up stays a follow-up whatever was decided. A move
    that doesn't save says so: the item would otherwise drop off (or stay
    on) the next agenda without anyone knowing."""
    rows = _need(f"/church_board_items?id=eq.{_q(item_id)}&business_id=eq.{_q(biz)}&select=id,status&limit=1")
    if not rows or rows[0].get("status") == "follow_up":
        return
    decided = _need(f"/church_board_decisions?business_id=eq.{_q(biz)}&item_id=eq.{_q(item_id)}"
                    "&select=result,created_at&order=created_at.asc&limit=200")
    decided.sort(key=lambda d: str(d.get("created_at") or ""))
    want = ("tabled" if decided[-1].get("result") == "tabled" else "done") if decided else "open"
    have = rows[0].get("status")
    if want == have or (not decided and have == "open"):
        return
    got = sb_clients.sb_patch_as_service(f"/church_board_items?id=eq.{_q(item_id)}&business_id=eq.{_q(biz)}",
                                         {"status": want, "updated_at": _iso(_now())})
    if not isinstance(got, list):
        raise HTTPException(503, f"The decision is saved, but the item is still marked {have.replace('_', '-')}. "
                                 f"Mark it {want} on the item.")


def _decision(me: Dict[str, Any], decision_id: Any) -> Dict[str, Any]:
    did = _uuid(decision_id, "decision")
    rows = _need(f"/church_board_decisions?id=eq.{_q(did)}&business_id=eq.{_q(me['biz']['id'])}"
                 f"&select={DECISION_FIELDS}&limit=1")
    if not rows:
        raise HTTPException(404, "That decision isn't here.")
    return {**rows[0], "_meeting": _meeting(me, rows[0]["meeting_id"])}


def edit_decision(me: Dict[str, Any], decision_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    d = _decision(me, decision_id)
    m = d["_meeting"]
    _writes(me, m["board_id"])
    _settled(m)
    biz = str(me["biz"]["id"])
    fields = _decision_fields(me, m, body, partial=True)
    moved = fields.get("moved_by", d.get("moved_by"))
    if moved and moved == fields.get("seconded_by", d.get("seconded_by")):
        raise HTTPException(400, "Someone else seconds the motion.")
    if fields:
        fields["updated_at"] = _iso(_now())
        _saved(sb_clients.sb_patch_as_service(f"/church_board_decisions?id=eq.{_q(d['id'])}&business_id=eq.{_q(biz)}",
                                              fields))
        if "result" in fields:
            resettle(biz, str(d["item_id"]))
    return meeting_page(me, m)


def delete_decision(me: Dict[str, Any], decision_id: str) -> Dict[str, Any]:
    d = _decision(me, decision_id)
    m = d["_meeting"]
    _writes(me, m["board_id"])
    _settled(m)
    biz = str(me["biz"]["id"])
    if not sb_clients.sb_delete_as_service(f"/church_board_decisions?id=eq.{_q(d['id'])}&business_id=eq.{_q(biz)}"):
        raise HTTPException(503, "Nothing was removed. Try again.")
    resettle(biz, str(d["item_id"]))
    return meeting_page(me, m)


def decisions_log(me: Dict[str, Any], q: str = "", board_id: str = "", year: str = "") -> Dict[str, Any]:
    """Every decision on the boards this login sees, newest first, searched
    by the motion and the item's title across years: "roof" finds the roof.
    Every word must appear."""
    biz = str(me["biz"]["id"])
    boards = _boards(me, archived=True)
    if board_id:
        boards = [b for b in boards if str(b["id"]) == _uuid(board_id, "board")]
    names = {str(b["id"]): b.get("name") or "" for b in boards}
    if not boards:
        return {"decisions": [], "years": [], "q": q}
    words = [w.lower() for w in re.findall(r"[\w$']+", _plain(q))][:6]
    path = (f"/church_board_decisions?business_id=eq.{_q(biz)}&board_id=in.({','.join(sorted(names))})"
            f"&select={DECISION_FIELDS}&order=decided_on.desc,created_at.desc&limit=1000")
    if words:
        w = max(words, key=len)
        path += f"&or=(motion.ilike.*{_q(w)}*,item_title.ilike.*{_q(w)}*)"
    rows = _need(path)
    rows.sort(key=lambda r: (str(r.get("decided_on") or ""), str(r.get("created_at") or "")), reverse=True)
    years = sorted({str(r.get("decided_on") or "")[:4] for r in rows if r.get("decided_on")}, reverse=True)
    if year:
        if not re.fullmatch(r"\d{4}", str(year)):
            raise HTTPException(400, "Pick a year.")
        rows = [r for r in rows if str(r.get("decided_on") or "").startswith(str(year))]
    if words:
        rows = [r for r in rows if all(w in f"{r.get('motion') or ''} {r.get('item_title') or ''}".lower() for w in words)]
    rows = rows[:300]
    members = _members(biz, list(names), everyone=True)
    people = {str(x["id"]): x["name"] for x in members}
    meetings: Dict[str, Dict[str, Any]] = {}
    for chunk in _chunks(r["meeting_id"] for r in rows):
        for x in _need(f"/church_board_meetings?business_id=eq.{_q(biz)}&id=in.({','.join(chunk)})"
                       "&select=id,starts_at,title,status&limit=500"):
            meetings[str(x["id"])] = x
    out = []
    for r in rows:
        mt = meetings.get(str(r["meeting_id"])) or {}
        out.append({**_decision_view(r, people), "board": names.get(str(r["board_id"]), ""),
                    "meeting_starts_at": mt.get("starts_at"), "meeting_title": mt.get("title") or "",
                    "approved": mt.get("status") == "approved"})
    return {"decisions": out, "years": years, "q": q}


# ─── The minutes, as words ────────────────────────────────────────────

def vote_words(d: Dict[str, Any]) -> str:
    return (f"For {int(d.get('votes_for') or 0)}, against {int(d.get('votes_against') or 0)}, "
            f"abstaining {int(d.get('votes_abstain') or 0)}.")


def minutes_text(church: str, mp: Dict[str, Any], zone: ZoneInfo) -> str:
    """The minutes as plain words: the masthead, who was there and the
    quorum, then each item in order with its minutes and decisions."""
    m, board, q = mp["meeting"], mp["board"], mp["quorum"]
    lines = [f"{church}", f"{board['name']}: minutes of the meeting of {when_words(m['starts_at'], zone)}"]
    if m.get("title"):
        lines.append(m["title"])
    if m.get("place"):
        lines.append(m["place"])
    lines.append("Approved" if m.get("status") == "approved" else "Draft, for the board's approval")
    lines.append("")
    by = {s: [p["name"] + (f" ({p['title']})" if p.get("title") else "") for p in mp["roster"] if p["status"] == s]
          for s in ATTENDS}
    for s, word in (("present", "Present"), ("absent", "Absent"), ("excused", "Excused")):
        if by[s]:
            lines.append(f"{word}: {', '.join(by[s])}.")
    lines.append(f"Quorum: {q['present']} of {q['total']} present, {q['needed']} needed. "
                 f"{'The quorum was met.' if q['met'] else 'The quorum was not met.'}")
    for a in mp.get("approves") or []:
        lines.append(f"The minutes of {when_words(a['starts_at'], zone).split(' at ')[0]} were approved.")
    for n, i in enumerate(mp["items"], start=1):
        lines += ["", f"{n}. {i['title']}"]
        if i.get("minutes"):
            lines.append(i["minutes"])
        for d in i["decisions"]:
            who = []
            if d.get("moved_by_name"):
                who.append(f"Moved by {d['moved_by_name']}")
            if d.get("seconded_by_name"):
                who.append(f"seconded by {d['seconded_by_name']}")
            lines.append(f"Motion: {d['motion']}")
            lines.append(" ".join(filter(None, [", ".join(who) + "." if who else "", vote_words(d),
                                                RESULT_WORDS.get(d.get("result") or "", "") + "."])))
        if i["status"] == "tabled" and not any(d.get("result") == "tabled" for d in i["decisions"]):
            lines.append("Tabled to the next meeting.")
        f = i.get("follow_up")
        if i["status"] == "follow_up" or f:
            who = (f or {}).get("name") or "the board"
            due = (f or {}).get("due")
            lines.append(f"Follow-up: {who}" + (f", by {date.fromisoformat(due):%B} {date.fromisoformat(due).day}" if due else "") + ".")
    return "\n".join(lines).strip() + "\n"


# ─── Send, approve, tasks ─────────────────────────────────────────────

def deliver(biz: Dict[str, Any], to_email: str, to_name: str, subject: str, text: str, key: str) -> None:
    """One email through the app's own path (Resend, the church's identity
    where it has one). Raises when it doesn't go."""
    import email_layout
    import email_sender
    settings = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    church = _plain(biz.get("name")) or "Your church"
    html = email_layout.render_html(
        text, business_name=church, brand=email_layout.brand_of(settings), sig=None, preheader=subject[:90],
        disclaimer=f"You sit on a board at {church}. These minutes are a draft until the board approves them.",
        footer_note="Sent by your church office")
    asyncio.run(email_sender.send_via_resend(
        to_email=to_email, to_name=to_name or None,
        from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
        from_name=church, subject=subject[:150], body=html, reply_to=None,
        business_id=str(biz["id"]), idempotency_key=key))


def send_minutes(me: Dict[str, Any], meeting_id: str) -> Dict[str, Any]:
    """Email the draft to the board's members, and only them: each active
    member's own email (theirs as one of the church's people, else their
    login's). Ending the meeting first if it's still in progress."""
    m = _meeting(me, meeting_id)
    _writes(me, m["board_id"])
    if m.get("status") == "approved":
        raise HTTPException(409, "These minutes are approved already.")
    if m.get("status") == "planned":
        raise HTTPException(409, "The meeting hasn't started. Minutes go out once there are minutes.")
    import rate_limit
    if not rate_limit.allow("church_board_send", str(m["id"])):
        raise HTTPException(429, "These minutes went out several times this hour. Try again later.")
    biz = me["biz"]
    biz_id = str(biz["id"])
    if m.get("status") == "in_progress":
        m = edit_meeting(me, str(m["id"]), {"status": "drafted"})["meeting"]
        m = _meeting(me, m["id"])
    mp = meeting_page(me, m)
    members = _members(biz_id, [str(m["board_id"])])
    emails: Dict[str, str] = {}
    for chunk in _chunks(x.get("contact_id") for x in members):
        for c in _need(f"/contacts?business_id=eq.{_q(biz_id)}&id=in.({','.join(chunk)})&select=id,email&limit=200"):
            if "@" in str(c.get("email") or ""):
                emails[str(c["id"])] = str(c["email"]).strip()
    logins = _seat_emails(biz) if any(x.get("user_id") for x in members) else {}
    zone = _zone(me)
    church = _plain(biz.get("name")) or "Your church"
    text = minutes_text(church, mp, zone)
    subject = f"Draft minutes: {mp['board']['name']}, {when_words(m['starts_at'], zone).split(' at ')[0]}"
    n = int(m.get("sent_count") or 0) + 1
    # One key per send, for each member: a retry of this send never goes
    # twice, and the next send is its own whatever the count says.
    token = uuid.uuid4().hex[:12]
    sent, missing, failed = [], [], []
    for x in members:
        email = emails.get(str(x.get("contact_id") or "")) or logins.get(str(x.get("user_id") or "")) or ""
        if "@" not in email:
            missing.append(x["name"])
            continue
        try:
            deliver(biz, email, x["name"], subject, text, f"board-minutes-{m['id']}-{x['id']}-{token}")
            sent.append(x["name"])
        except Exception:
            logger.warning("church board: a minutes email failed", exc_info=True)
            failed.append(x["name"])
    recorded = True
    if sent:
        got = sb_clients.sb_patch_as_service(
            f"/church_board_meetings?id=eq.{_q(m['id'])}&business_id=eq.{_q(biz_id)}",
            {"sent_at": _iso(_now()), "sent_by": me["uid"], "sent_count": min(1000, n), "updated_at": _iso(_now())})
        recorded = isinstance(got, list) and bool(got)
    return {"sent": len(sent), "to": sent, "no_email": missing, "failed": failed, "recorded": recorded,
            **meeting_page(me, _meeting(me, m["id"]))}


def approve(me: Dict[str, Any], meeting_id: str, in_meeting_id: Any = None) -> Dict[str, Any]:
    """The board approves the draft minutes, usually at its next meeting
    (in_meeting_id): they're marked approved, and no longer change."""
    m = _meeting(me, meeting_id)
    _writes(me, m["board_id"])
    if m.get("status") == "approved":
        raise HTTPException(409, "These minutes are approved already.")
    if m.get("status") != "drafted":
        raise HTTPException(409, "End the meeting first: minutes are approved once they're drafted.")
    biz = str(me["biz"]["id"])
    fields: Dict[str, Any] = {"status": "approved", "approved_at": _iso(_now()), "approved_by": me["uid"],
                              "updated_at": _iso(_now())}
    if in_meeting_id not in (None, ""):
        at = _meeting(me, in_meeting_id)
        if str(at["board_id"]) != str(m["board_id"]) or str(at["id"]) == str(m["id"]):
            raise HTTPException(400, "Minutes are approved at a meeting of the same board.")
        if (_at(at.get("starts_at")) or _now()) <= (_at(m.get("starts_at")) or _now()):
            raise HTTPException(400, "Minutes are approved at a later meeting.")
        if at.get("status") == "approved":
            raise HTTPException(409, "That meeting's own minutes are approved already.")
        fields["approved_in"] = str(at["id"])
    got = sb_clients.sb_patch_as_service(
        f"/church_board_meetings?id=eq.{_q(m['id'])}&business_id=eq.{_q(biz)}&status=eq.drafted", fields)
    if not isinstance(got, list):
        raise HTTPException(503, "That didn't save. Try again.")
    if not got:
        raise HTTPException(409, "Someone changed this meeting just now. Open it again.")
    return meeting_page(me, got[0])


def make_tasks(me: Dict[str, Any], meeting_id: str) -> Dict[str, Any]:
    """Each follow-up without a task becomes one, through the app's own tasks
    (Office › Tasks): handed to the member's login where they have one, due
    when the follow-up is. A member with no login who is one of the church's
    people is handed it as a leader (My tasks for leaders, church_leader_tasks:
    while its switch is open to this login and its migration is in), so it
    reaches their Lead tab. Twice makes each once."""
    m = _meeting(me, meeting_id)
    _writes(me, m["board_id"])
    biz = str(me["biz"]["id"])
    items = [i for i in _items(biz, [str(m["id"])]) if i.get("status") == "follow_up" and not i.get("task_id")]
    if not items:
        return {"made": 0, **meeting_page(me, m)}
    board = _board(me, m["board_id"])
    members = {str(x["id"]): x for x in _members(biz, [str(board["id"])], everyone=True)}
    zone = _zone(me)
    day = when_words(m["starts_at"], zone).split(" at ")[0]
    import church_leader_tasks
    by_contact = (any(x.get("contact_id") and not x.get("user_id") for x in members.values())
                  and church_leader_tasks.open_to(me["user"]) and church_leader_tasks.ready(biz))
    made = 0
    for i in items:
        who = members.get(str(i.get("follow_up_member") or "")) or {}
        title = i.get("title") or "A follow-up"
        leader = str(who.get("contact_id") or "") if by_contact and who and not who.get("user_id") else ""
        if who and not who.get("user_id") and not leader:
            title = f"{title} ({who.get('name')})"
        desc = f"A follow-up from the {board['name']} meeting of {day}."
        if i.get("minutes"):
            desc += f"\n\n{i['minutes'][:1500]}"
        row = {"business_id": biz, "title": title[:200], "description": desc, "status": "todo", "priority": "medium",
               "due_date": i.get("follow_up_due"), "assigned_to": who.get("user_id") or None}
        if leader:
            # Who handed it (the database keeps a server write's own value):
            # late, with no one above the leader, it comes back to them.
            row.update(assigned_contact_id=leader, handed_by=str(me["user"].id))
        task = sb_clients.sb_post_as_service("/tasks", row)
        if not isinstance(task, list) or not task or not task[0].get("id"):
            raise HTTPException(503, f"{made} task{'s' if made != 1 else ''} made; the rest didn't save. Try again.")
        tid = str(task[0]["id"])
        got = sb_clients.sb_patch_as_service(
            f"/church_board_items?id=eq.{_q(i['id'])}&business_id=eq.{_q(biz)}&task_id=is.null",
            {"task_id": tid, "updated_at": _iso(_now())})
        if isinstance(got, list) and not got:
            # Someone made it at the same moment: theirs stands.
            sb_clients.sb_delete_as_service(f"/tasks?id=eq.{_q(tid)}&business_id=eq.{_q(biz)}")
            continue
        made += 1
    return {"made": made, **meeting_page(me, m)}


# ─── Routes ───────────────────────────────────────────────────────────

@router.get("/status")
def board_status(business_id: str, user: AuthedUser = Depends(require_user)):
    """Whether this login's office shows Board & minutes: the app asks once,
    so its menu offers the page only where it opens. Quietly false for a
    closed switch, a business that isn't a church, a login that is neither
    the owner, an admin nor on a board, or tables not made yet."""
    off = {"enabled": False, "manage": False, "member": False, "boards": 0}
    if not open_to(user):
        return off
    try:
        me = _access(business_id, user)
    except HTTPException as e:
        if e.status_code in (403, 503) or e.detail == NOT_CHURCH:
            return off
        raise
    if not _ready(str(me["biz"]["id"])):
        return off
    return {"enabled": True, "manage": me["boss"], "member": bool(me["mine"]), "boards": len(me["mine"])}


@router.get("")
def board_page(business_id: str, user: AuthedUser = Depends(require_user)):
    return page(_access(business_id, user))


@router.get("/people")
def board_people(business_id: str, q: str = "", user: AuthedUser = Depends(require_user)):
    return people(_access(business_id, user), q)


@router.post("/boards")
def board_add(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    return add_board(_access((body or {}).get("business_id"), user), body or {})


@router.patch("/boards/{board_id}")
def board_edit(board_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    return edit_board(_access((body or {}).get("business_id"), user), board_id, body or {})


@router.post("/boards/{board_id}/members")
def board_member_add(board_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    return add_member(_access((body or {}).get("business_id"), user), board_id, body or {})


@router.patch("/members/{member_id}")
def board_member_edit(member_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    return edit_member(_access((body or {}).get("business_id"), user), member_id, body or {})


@router.post("/meetings")
def board_meeting_add(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    return add_meeting(_access((body or {}).get("business_id"), user), body or {})


@router.get("/meetings/{meeting_id}")
def board_meeting(meeting_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    me = _access(business_id, user)
    return meeting_page(me, _meeting(me, meeting_id))


@router.patch("/meetings/{meeting_id}")
def board_meeting_edit(meeting_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    return edit_meeting(_access((body or {}).get("business_id"), user), meeting_id, body or {})


@router.delete("/meetings/{meeting_id}")
def board_meeting_delete(meeting_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    return delete_meeting(_access(business_id, user), meeting_id)


@router.post("/meetings/{meeting_id}/carry")
def board_meeting_carry(meeting_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    me = _access((body or {}).get("business_id"), user)
    m = _meeting(me, meeting_id)
    _writes(me, m["board_id"])
    n = carry_forward(me, m)
    return {"carried": n, **meeting_page(me, m)}


@router.put("/meetings/{meeting_id}/attendance")
def board_meeting_mark(meeting_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    return mark(_access((body or {}).get("business_id"), user), meeting_id, body or {})


@router.post("/meetings/{meeting_id}/items")
def board_item_add(meeting_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    return add_item(_access((body or {}).get("business_id"), user), meeting_id, body or {})


@router.patch("/items/{item_id}")
def board_item_edit(item_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    return edit_item(_access((body or {}).get("business_id"), user), item_id, body or {})


@router.delete("/items/{item_id}")
def board_item_delete(item_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    return delete_item(_access(business_id, user), item_id)


@router.post("/items/{item_id}/decisions")
def board_decision_add(item_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    return add_decision(_access((body or {}).get("business_id"), user), item_id, body or {})


@router.patch("/decisions/{decision_id}")
def board_decision_edit(decision_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    return edit_decision(_access((body or {}).get("business_id"), user), decision_id, body or {})


@router.delete("/decisions/{decision_id}")
def board_decision_delete(decision_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    return delete_decision(_access(business_id, user), decision_id)


@router.get("/decisions")
def board_decisions(business_id: str, q: str = "", board_id: str = "", year: str = "",
                    user: AuthedUser = Depends(require_user)):
    return decisions_log(_access(business_id, user), q, board_id, year)


@router.post("/meetings/{meeting_id}/send")
def board_send(meeting_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    return send_minutes(_access((body or {}).get("business_id"), user), meeting_id)


@router.post("/meetings/{meeting_id}/approve")
def board_approve(meeting_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    return approve(_access(body.get("business_id"), user), meeting_id, body.get("in_meeting_id"))


@router.post("/meetings/{meeting_id}/tasks")
def board_tasks(meeting_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    return make_tasks(_access((body or {}).get("business_id"), user), meeting_id)
