"""church_meetings.py — Meetings & minutes: a meeting for every leader or for
the office, kept in step with the leaders list, and "I'll be there" / "I
can't" (docs/CHURCH_SCHEDULE.md section 10, PR S3-2).

The pastor, 2026-11-20, approving the mock and its five calls: one home for
every meeting (Board & minutes becomes Meetings & minutes); a meeting for
every leader follows the leaders list, and so does one for the office; "I
can't" needs no yes, with a short note only whoever set the meeting, the
meetings' keepers and whoever oversees the office read; a reminder the day
before (S3-6); a private link for a phone's calendar (S3-6).

A group that meets is a church_boards row, as every board is
(supabase/APPLY-2026-11-21-church-meetings.sql):

    kind ........ board (it governs: its people give the board's yes on
                  money, and it is a board on the leaders map) or meeting
                  (it only meets: the huddle, the leaders meeting, check-ins)
    audience .... members (the group's own people, as a board has them),
                  leaders (everyone on the leaders list) or office (the
                  office on it). A group for the list is always a meeting

A group for the list has member rows like a board's, so attendance, the
agenda, decisions, minutes and the Board tab work for the huddle as they do
for the deacons. The server keeps them in step with the leaders list
(keep_in_step): one row a person (from_list), a person off the list is let
go (active false, as leaving a board is, so old minutes keep the name), and
only the keeping in step writes them (church_board.add_member and
edit_member refuse there).

    POST /church/meetings                    Set a meeting, one at a time:
                                             {business_id, name, who:
                                             'leaders' | 'office' | 'group:<id>',
                                             starts_at, length_minutes?, place?,
                                             video_url?}. For every leader or
                                             the office, the open group of
                                             that name is found, or made
    GET  /church/meetings/{id}/answers       who said "I'll be there", who said
                                             "I can't" (a note only for its
                                             readers), who hasn't answered
    PUT  /church/meetings/{id}/answers       {business_id, member_id?, answer:
                                             'yes' | 'cant' | null, note?}; no
                                             member_id is this login's own seat

The note, 200 letters at most and with "I can't" only, is read by the person
it is about and whoever wrote it, the meetings' keepers (the owner, an
Admin, the Manager holding the meetings duty), the login that set that
meeting and whoever oversees the office (church_schedule.office_overseers).
answers_view() and person_view() are the ONLY places it leaves the server:
never in a notice, a calendar, a log line or the minutes.

How it writes, the way PostgREST can: the two partial unique indexes
(church_boards_one_list_name, church_board_members_one_from_list) are never
named in on_conflict (Postgres refuses that, 42P10). One row a request, and
a 409 (23505) read as "made just now" or "already seated". An answer is
upserted on its primary key (meeting_id, member_id), which is plain.

Switched by CHURCH_MEETINGS: off | owner | on, owner when unset (the
platform owner's own church, and his own login), and only where
CHURCH_BOARD is open too. Until ready() says the tables are there, every
route here answers 404 and Meetings & minutes is Board & minutes exactly:
its name, its answers and its writes. Every reader that tells a board from
a meeting fails closed, whatever the switch says and whatever ready() says:
it names step 3's columns (kind=eq.board, from_list, audience) and reads
through read(), which uses the old read only when the database says for
certain the columns aren't there, and is a 503 on a timeout. A meeting's
people never give the board's yes.
"""
from __future__ import annotations

import logging
import os
import re
import time as clock
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church/meetings", tags=["church"])

SWITCH = "CHURCH_MEETINGS"
KINDS = ("board", "meeting")
AUDIENCES = ("members", "leaders", "office")
LISTS = ("leaders", "office")              # the groups that follow the leaders list
BOARD_TABLES = ("church_boards", "church_board_members", "church_board_meetings")
ANSWERS = ("yes", "cant")
NOTE_MAX = 200
LENGTH_MIN, LENGTH_MAX = 5, 720
NAME = "Meetings & minutes"
OLD_NAME = "Board & minutes"
READY_SECONDS = 600.0                      # the tables, once there, are asked about again in ten minutes
MISSING_SECONDS = 60.0                     # not there (or couldn't tell): asked again a minute later

# What a read names of step 3's columns. Every reader that tells a board
# from a meeting (who gives the board's yes, who writes a group, the Board
# tab, the map, the board's log and the housing vote) names them always and
# reads through read(): the old read, without them, only when the database
# says for certain they aren't there (before the file). A timeout or a 5xx
# is a 503, never the old read, which would count a meeting as a board. The
# lint (test_board_readers_name_kind) sees each read name them.
KIND_BOARD = "&kind=eq.board"
NOT_CALLED_OFF = "&cancelled_at=is.null"
GROUP_COLS = ",kind,audience"
MEETING_COLS = ",cancelled_at,series_id,series_day,length_minutes,created_by"
SEAT_COLS = ",from_list"
NEW_BITS = (KIND_BOARD, NOT_CALLED_OFF, MEETING_COLS, GROUP_COLS, SEAT_COLS)
# The database saying a column or a table isn't there: Postgres's undefined
# column and undefined table, PostgREST's column and table "not in the
# schema cache". Nothing else is "not there".
ABSENT_CODES = ("42703", "42P01", "PGRST204", "PGRST205")

UNREAD = "The meetings couldn't be read just now. Try again."
UNSAVED = "That didn't save. Try again."
FOLLOWS_LIST = "This meeting follows the leaders list. Add them to the list instead."
NO_LIST = "The leaders list isn't on here yet, so a meeting can be set for a board or a group."
NOT_KEEPER = "Only the owner, an admin, or whoever keeps the meetings sets a meeting for every leader or the office."
NOT_IN = "You aren't in this meeting."
THEY_NOT_IN = "That person isn't in this meeting."
LEFT = "They've left this meeting, so there's no answer to give."
CALLED_OFF = "This meeting was called off. Put it back on first."
STARTED = "This meeting has started, so answers are closed."
OVER = "This meeting is over, so answers are closed."
NOTE_CANT = "A note goes with \"I can't\" only."
NO_REPEAT = "A meeting that repeats can't be set here yet. Set this one, and the next ones one at a time."
NO_ROOM = "Booking a room with a meeting can't be done here yet. Book it in Rooms & spaces."

_FORCE: Optional[bool] = None
_STATE: Dict[str, Any] = {"yes": None, "at": 0.0}


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get(SWITCH) or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def _platform_login(user: Any) -> bool:
    owner = (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()
    return (getattr(user, "email", None) or "").strip().lower() == owner


def _board_open_to(user: Any) -> bool:
    import church_board as cb
    return cb.open_to(user)


def _board_church_open(biz: Any) -> bool:
    """Board & minutes' switch for a church (it has none of its own: on, or
    owner and the platform owner's own church)."""
    import church_board as cb
    m = cb.mode()
    if m == "on":
        return True
    if m == "owner":
        import member_asks
        return member_asks.platform_church(biz.get("id") if isinstance(biz, dict) else biz)
    return False


def open_to(user: Any) -> bool:
    """For this login: Board & minutes open to it, and ours on, or (owner)
    the platform owner's own login."""
    if not _board_open_to(user):
        return False
    m = mode()
    return m == "on" or (m == "owner" and _platform_login(user))


def church_open(biz: Any) -> bool:
    """For this church: Board & minutes open for it, and ours on, or (owner)
    the platform owner's own church (member_asks.platform_church: kept ten
    minutes a replica, and a read that fails is a no)."""
    m = mode()
    if m == "off" or not _board_church_open(biz):
        return False
    if m == "on":
        return True
    import member_asks
    return member_asks.platform_church(biz.get("id") if isinstance(biz, dict) else biz)


def office_open(user: Any, biz: Any) -> bool:
    """The office's routes: the login (open_to) or the church (church_open)."""
    if mode() == "off" or not _board_open_to(user):
        return False
    return open_to(user) or church_open(biz)


def _no_table(err: Dict[str, Any]) -> bool:
    code = str(err.get("code") or "")
    return code in ("42P01", "PGRST205") or "42P01" in str(err.get("message") or "") \
        or (err.get("status") == 404 and code.startswith("PGRST"))


def ready() -> bool:
    """True once church_meeting_answers answers (one transaction makes all
    four tables and the columns): whether step 3's routes and features run.
    church_schedule.ready's rule for "no such table", with one change: only
    a definite answer is kept (yes ten minutes, no a minute); a blip keeps
    the last answer for this call only and is asked again on the next, and
    with none yet reads as not there (the routes answer 404, never a 500).
    The readers that tell a board from a meeting never ask this: they read
    through read(). NEVER RAISES."""
    if _FORCE is not None:
        return _FORCE
    if not sb_clients.sb_url():
        return False    # no database to ask (a script)
    now = clock.monotonic()
    yes, at = _STATE["yes"], _STATE["at"]
    if yes is not None and now - at < (READY_SECONDS if yes else MISSING_SECONDS):
        return yes
    try:
        rows = sb_clients.sb_get_as_service("/church_meeting_answers?select=meeting_id&limit=1")
        err = sb_clients.last_error() if rows is None else None
    except Exception:  # noqa: BLE001 — a fake or a broken client is "couldn't tell"
        rows, err = None, None
    if isinstance(rows, list):
        _STATE["yes"], _STATE["at"] = True, now
        return True
    if err and _no_table(err):
        _STATE["yes"], _STATE["at"] = False, now
        return False
    return bool(yes)                # couldn't tell: not kept


def absent(err: Optional[Dict[str, Any]]) -> bool:
    """The database said for certain a column or a table isn't there."""
    if not err:
        return False
    code = str(err.get("code") or "")
    return code in ABSENT_CODES or (err.get("status") == 404 and code.startswith("PGRST"))


def without_new(path: str) -> str:
    """The same read without step 3's columns: the read as it was."""
    for bit in NEW_BITS:
        path = path.replace(bit, "")
    return path


def pinned_absent() -> bool:
    """The tables are pinned as not there (a test's conftest, never
    production): nothing of step 3 is named or read, as before the file."""
    return _FORCE is False


def read(path: str) -> Optional[List[Dict[str, Any]]]:
    """A read that may name step 3's columns (through the helpers below):
    as it is, and only when the database says for certain those columns
    aren't there (before the file), the same read without them. A read that
    fails any other way (a timeout, a 5xx) is None: the caller's 503, never
    the old read. A definite answer is kept for ready(). The helpers name
    nothing when the tables are pinned as not there (pinned_absent), so a
    read is then exactly the old one. NEVER RAISES."""
    try:
        rows = sb_clients.sb_get_as_service(path)
        names = path.lstrip("/").split("?")[0] in BOARD_TABLES and path != without_new(path)
        if isinstance(rows, list):
            if names:
                _definite(True)
            return rows
        if not names or _FORCE is not None or not absent(sb_clients.last_error()):
            return None
        _definite(False)
        rows = sb_clients.sb_get_as_service(without_new(path))
        return rows if isinstance(rows, list) else None
    except Exception:  # noqa: BLE001 — a broken client is "couldn't read"
        return None


def _definite(yes: bool) -> None:
    if _FORCE is None:
        _STATE["yes"], _STATE["at"] = yes, clock.monotonic()


def on(biz: Any) -> bool:
    """What a reader outside the routes asks: the tables are there, and open
    for this church. ready() first, so a closed database reads nothing."""
    return ready() and church_open(biz)


def name_for(*, user: Any = None, biz: Any = None) -> str:
    """The page's name: Meetings & minutes where step 3 is open (for this
    login or this church), Board & minutes everywhere else."""
    if not ready():
        return OLD_NAME
    if user is not None and biz is not None:
        return NAME if office_open(user, biz) else OLD_NAME
    if user is not None:
        return NAME if open_to(user) else OLD_NAME
    return NAME if biz is not None and church_open(biz) else OLD_NAME


# ─── What a read names, once the columns are there ───────────────────

def board_kind() -> str:
    """'&kind=eq.board' for every read that means a board (one whose people
    give the board's yes on money, a board on the leaders map, the Board
    tab, the board's own decisions), read through read(); nothing when the
    tables are pinned as not there."""
    return "" if pinned_absent() else KIND_BOARD


def group_cols() -> str:
    return "" if pinned_absent() else GROUP_COLS


def meeting_cols() -> str:
    return "" if pinned_absent() else MEETING_COLS


def seat_cols() -> str:
    return "" if pinned_absent() else SEAT_COLS


def not_called_off() -> str:
    return "" if pinned_absent() else NOT_CALLED_OFF


def is_list(group: Optional[Dict[str, Any]]) -> bool:
    return bool(group) and group.get("audience") in LISTS


def is_meeting(group: Optional[Dict[str, Any]]) -> bool:
    """A group that only meets: never a board."""
    return bool(group) and group.get("kind") == "meeting"


def called_off(m: Optional[Dict[str, Any]]) -> bool:
    return bool(m) and bool(m.get("cancelled_at"))


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
    from urllib.parse import quote
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _need(path: str) -> List[Dict[str, Any]]:
    rows = read(path)
    if not isinstance(rows, list):
        raise HTTPException(503, UNREAD)
    return rows


def _code() -> str:
    return str((sb_clients.last_error() or {}).get("code") or "")


def _chunks(ids: Iterable[Any], n: int = 100) -> Iterable[List[str]]:
    ids = sorted({str(i) for i in ids if i})
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def _same(a: Any, b: Any) -> bool:
    """The same instant, however each was written."""
    x, y = _at(a), _at(b)
    return x is not None and y is not None and x == y


def note_of(v: Any) -> Optional[str]:
    """The note someone typed: kept as written, trimmed, 200 at most."""
    s = str(v or "").replace("\r\n", "\n").strip()
    if len(s) > NOTE_MAX:
        raise HTTPException(400, f"Keep the note to {NOTE_MAX} letters.")
    return s or None


def length_of(v: Any) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise HTTPException(400, "Say how long it runs, in minutes.")
    if isinstance(v, bool) or not LENGTH_MIN <= n <= LENGTH_MAX:
        raise HTTPException(400, f"A meeting runs from {LENGTH_MIN} minutes to {LENGTH_MAX // 60} hours.")
    return n


# ─── Keeping the list's seats in step ────────────────────────────────

def wanted(ch: Any, roster: Any, audience: str) -> Set[str]:
    """Who a group for the list is for, by person: `leaders` is everyone on
    the leaders list (both its groups); `office` is its office group and
    everyone counted among its leaders who has an office login (decision
    2 counts them under leaders; a pastor on staff still comes to the
    huddle)."""
    if audience == "leaders":
        return set(roster.people())
    if audience == "office":
        return set(roster.office) | (set(roster.leaders) & set(ch.person_login))
    return set()


def keep_in_step(ch: Any, group: Dict[str, Any], roster: Any = None) -> Dict[str, int]:
    """One group for the list, in step with the leaders list: a person on it
    with no seat gets one (from_list, their login by Church.person_login, so
    an office person reads it in the office app too); a seat whose person is
    back is active again (and follows their login); an active seat whose
    person is off the list is let go (active false). A closed group, or one
    that isn't for the list, is left alone. One row a request; a 409 on a
    new seat is "already seated" (another replica, just now). A read that
    fails is a 503, with what was written so far kept (every write is the
    list's own, and the next keeping finishes it)."""
    done = {"added": 0, "back": 0, "left": 0}
    if not is_list(group) or group.get("archived"):
        return done
    import church_schedule as cs
    r = roster if roster is not None else cs.roster(ch)
    want = wanted(ch, r, str(group["audience"]))
    logins = ch.person_login
    b, gid = _q(ch.b), str(group["id"])
    seats = _need(f"/church_board_members?business_id=eq.{b}&board_id=eq.{_q(gid)}"
                  f"&select=id,contact_id,user_id,active{seat_cols()}&limit=1000")
    by_person = {str(s["contact_id"]): s for s in seats if s.get("contact_id")}
    names: Dict[str, str] = {}
    for chunk in _chunks(c for c in want if c not in by_person):
        for c in _need(f"/contacts?business_id=eq.{b}&id=in.({','.join(chunk)})&select=id,name&limit=200"):
            names[str(c["id"])] = _plain(c.get("name"))
    now = _iso(_now())
    for cid in sorted(want):
        s = by_person.get(cid)
        login = logins.get(cid)
        if s is None:
            if cid not in names:
                continue            # not one of the church's people any more
            got = sb_clients.sb_post_as_service("/church_board_members", {
                "business_id": ch.b, "board_id": gid, "contact_id": cid, "user_id": login,
                "name": (names[cid] or "A leader")[:120], "title": "", "active": True, "from_list": True,
                "created_at": now, "updated_at": now})
            if isinstance(got, list) and got:
                done["added"] += 1
            elif _code() != "23505":       # 23505: already seated, by another replica just now
                raise HTTPException(503, UNSAVED)
        elif s.get("active") is False or str(s.get("user_id") or "") != str(login or ""):
            if not isinstance(sb_clients.sb_patch_as_service(
                    f"/church_board_members?id=eq.{_q(s['id'])}&business_id=eq.{b}&from_list=eq.true",
                    {"active": True, "user_id": login, "updated_at": now}), list):
                raise HTTPException(503, UNSAVED)
            done["back"] += s.get("active") is False
    for s in seats:
        if s.get("active") is not False and str(s.get("contact_id") or "") not in want:
            if not isinstance(sb_clients.sb_patch_as_service(
                    f"/church_board_members?id=eq.{_q(s['id'])}&business_id=eq.{b}&from_list=eq.true",
                    {"active": False, "updated_at": now}), list):
                raise HTTPException(503, UNSAVED)
            done["left"] += 1
    return done


def before_page(me: Dict[str, Any], group: Dict[str, Any]) -> None:
    """The office opens a group for the list: its seats follow the list
    first, read fresh (the office always reads the roster fresh). Where the
    leaders schedule is closed for the church, the seats stand as they are."""
    if not (ready() and is_list(group) and not group.get("archived")):
        return
    import church_over as co
    import church_schedule as cs
    if not cs.on(me["biz"]):
        return
    keep_in_step(co.Church(me["biz"]), group)


def before_member_page(biz: Dict[str, Any], group: Dict[str, Any]) -> None:
    """The member side opens a group for the list: the same, with the roster
    kept a minute a replica (church_schedule.roster_kept, decision 17). A
    roster that can't be read leaves the seats as they stand."""
    if not (ready() and is_list(group) and not group.get("archived")):
        return
    import church_over as co
    import church_schedule as cs
    if not cs.on(biz):
        return
    r = cs.roster_kept(biz)
    if r is None:
        return
    keep_in_step(co.Church(biz), group, r)


# ─── A group for every leader, or the office: found or made ──────────

def _open_list_groups(biz: str, audience: str) -> List[Dict[str, Any]]:
    return _need(f"/church_boards?business_id=eq.{_q(biz)}&audience=eq.{_q(audience)}&archived=eq.false"
                 f"&select=id,name,quorum_kind,quorum_count,sort,archived{group_cols()}&limit=100")


def _named(rows: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    return next((g for g in rows if _plain(g.get("name")).lower() == name.lower()), None)


def list_group(me: Dict[str, Any], audience: str, name: str) -> Dict[str, Any]:
    """The open group of this name for every leader (or the office), found,
    or made: a meeting (never a board) for the list. Two presses at once
    make one: the second insert is refused by church_boards_one_list_name
    (23505) and the group is read again."""
    biz = str(me["biz"]["id"])
    found = _named(_open_list_groups(biz, audience), name)
    if found:
        return found
    have = _need(f"/church_boards?business_id=eq.{_q(biz)}&archived=eq.false&select=id,sort{group_cols()}&limit=100")
    now = _iso(_now())
    got = sb_clients.sb_post_as_service("/church_boards", {
        "business_id": biz, "name": name, "kind": "meeting", "audience": audience, "quorum_kind": "majority",
        "quorum_count": None, "sort": max([int(g.get("sort") or 0) for g in have] + [0]) + 1, "archived": False,
        "created_by": me["uid"], "created_at": now, "updated_at": now})
    if isinstance(got, list) and got:
        return got[0]
    if _code() == "23505":                  # made just now, by the other press
        found = _named(_open_list_groups(biz, audience), name)
        if found:
            return found
    raise HTTPException(503, "That meeting didn't save. Try again.")


# ─── Set a meeting (one at a time; a series is S3-3) ─────────────────

def _gate(business_id: Any, user: AuthedUser) -> Dict[str, Any]:
    """church_board's own session and gate, then ours: closed, or the tables
    not there, is a 404 with nothing of ours read."""
    if not ready() or mode() == "off" or not _board_open_to(user):
        raise HTTPException(404, "Not Found")
    import church_board as cb
    me = cb._access(business_id, user)
    if not office_open(user, me["biz"]):
        raise HTTPException(404, "Not Found")
    return me


def set_meeting(me: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    """Set a meeting: for every leader or the office (the keepers only; the
    group of that name is found or made and its seats follow the list
    before the meeting is made), or for a group that is there (a board, a
    check-in, or a group for the list, by church_board's own rules). Then
    church_board.add_meeting, so the agenda carries the group's open items
    as a board's meeting always has."""
    import church_board as cb
    if body.get("repeat"):
        raise HTTPException(400, NO_REPEAT)
    if body.get("space_id"):
        raise HTTPException(400, NO_ROOM)
    who = str(body.get("who") or "")
    name = _plain(body.get("name"))[:cb.NAME_MAX]
    title = ""
    fields = {k: body[k] for k in ("starts_at", "place", "video_url", "length_minutes") if k in body}
    if who in LISTS:
        cb._boss(me, NOT_KEEPER)
        import church_schedule as cs
        if not cs.on(me["biz"]):
            raise HTTPException(409, NO_LIST)
        if not name:
            raise HTTPException(400, "Name the meeting: Leaders meeting, Office huddle.")
        cb._meeting_fields(fields, partial=False)   # a bad day or length is a 400 before anything is made
        import church_over as co
        group = list_group(me, who, name)
        me.setdefault("audience", {})[str(group["id"])] = group.get("audience")
        keep_in_step(co.Church(me["biz"]), group)
    elif who.startswith("group:"):
        group = cb._board(me, who[len("group:"):])
        title = name[:cb.TITLE_MAX]
        # A group for the list named by its id: its seats follow the list
        # before the meeting is made, as for every leader or the office
        # (who may set it is asked first, so nobody else writes seats).
        cb._writes(me, group["id"])
        cb._meeting_fields(fields, partial=False)
        before_page(me, group)
    else:
        raise HTTPException(400, "Pick who comes: every leader, the office, or a group.")
    out = cb.add_meeting(me, {"board_id": str(group["id"]), "title": title, **fields})
    return {**out, "series": None, "room": None}


# ─── Answers ─────────────────────────────────────────────────────────

def answers_of(biz: str, meeting_ids: Iterable[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for chunk in _chunks(meeting_ids):
        out += _need(f"/church_meeting_answers?business_id=eq.{_q(biz)}&meeting_id=in.({','.join(chunk)})"
                     "&select=meeting_id,member_id,answer,note,for_starts_at,by_user_id,by_contact_id,answered_at"
                     "&limit=5000")
    return out


def current(a: Dict[str, Any], m: Dict[str, Any]) -> bool:
    """An answer counts for the meeting's time it was given for: once the
    meeting moves, it is no answer (listed with those who haven't)."""
    return _same(a.get("for_starts_at"), m.get("starts_at"))


def cant_now(biz: str, m: Dict[str, Any]) -> Set[str]:
    """The seats that said "I can't" for this meeting's time: "End the
    meeting" marks them excused, not absent. Nothing read before the
    tables (the meeting was read without step 3's columns); a failed read is
    a 503 (the meeting stays open)."""
    if "cancelled_at" not in m:
        return set()
    return {str(a["member_id"]) for a in answers_of(biz, [m["id"]]) if a.get("answer") == "cant" and current(a, m)}


def answerable(m: Dict[str, Any], now: Optional[datetime] = None) -> Optional[str]:
    """Why this meeting takes no answer now, or None: only a meeting still
    planned, not called off and not started."""
    if called_off(m):
        return CALLED_OFF
    if m.get("status") != "planned":
        return OVER if m.get("status") in ("drafted", "approved") else STARTED
    at = _at(m.get("starts_at"))
    if at is not None and at <= (now or _now()):
        return STARTED
    return None


def _meeting_row(biz: str, meeting_id: Any) -> Dict[str, Any]:
    import church_board as cb
    mid = cb._uuid(meeting_id, "meeting")
    rows = _need(f"/church_board_meetings?id=eq.{_q(mid)}&business_id=eq.{_q(biz)}"
                 f"&select={cb.meeting_fields()}&limit=1")
    if not rows:
        raise HTTPException(404, "That meeting isn't here.")
    return rows[0]


def _group_row(biz: str, group_id: Any) -> Dict[str, Any]:
    rows = _need(f"/church_boards?id=eq.{_q(group_id)}&business_id=eq.{_q(biz)}"
                 f"&select=id,name,quorum_kind,quorum_count,sort,archived{group_cols()}&limit=1")
    if not rows:
        raise HTTPException(404, "That meeting isn't here.")
    return rows[0]


def _own_seat(seats: List[Dict[str, Any]], uid: str, person: Optional[str]) -> Optional[Dict[str, Any]]:
    """A login's own seat: one with its login, or with the login's person;
    an active one first."""
    mine = [s for s in seats if (uid and str(s.get("user_id") or "") == uid)
            or (person and str(s.get("contact_id") or "") == person)]
    mine.sort(key=lambda s: s.get("active") is False)
    return mine[0] if mine else None


def _note_reader(me: Dict[str, Any], m: Dict[str, Any], ch: Any) -> bool:
    """The keepers, the login that set this meeting, and whoever oversees the
    office (an office login's standing, read for this request)."""
    if me.get("boss"):
        return True
    uid = str(me.get("uid") or "")
    if not uid:
        return False
    if uid == str(m.get("created_by") or ""):
        return True
    import church_schedule as cs
    return uid in cs.office_overseers(ch)


def _seat_view(s: Dict[str, Any]) -> Dict[str, Any]:
    return {"member_id": str(s["id"]), "name": s.get("name") or "A member", "title": s.get("title") or "",
            "contact_id": s.get("contact_id"), "login": bool(s.get("user_id"))}


def answers_view(me: Dict[str, Any], m: Dict[str, Any], group: Dict[str, Any]) -> Dict[str, Any]:
    """Who comes: the group's active seats, each "I'll be there", "I can't"
    or not answered (for the meeting's time; an answer for an old time is
    listed with those who haven't, "said … for the old time"). Names for
    whoever may open the meeting; a note only for its readers."""
    import church_board as cb
    import church_over as co
    biz = str(me["biz"]["id"])
    seats = [s for s in cb._members(biz, [str(group["id"])], everyone=True) if s.get("active") is not False]
    got = {str(a["member_id"]): a for a in answers_of(biz, [m["id"]])}
    uid = str(me.get("uid") or "")
    ch = co.Church(me["biz"])
    person = ch.login_person.get(uid) if uid else None
    own = _own_seat(seats, uid, person)
    reader: Optional[bool] = None
    coming: List[Dict[str, Any]] = []
    cant: List[Dict[str, Any]] = []
    waiting: List[Dict[str, Any]] = []
    moved = False
    for s in seats:
        a = got.get(str(s["id"]))
        v = _seat_view(s)
        if a and current(a, m):
            v["answered_at"] = a.get("answered_at")
            if a.get("answer") == "yes":
                coming.append(v)
                continue
            if a.get("note"):
                if (own and str(own["id"]) == str(s["id"])) or (uid and str(a.get("by_user_id") or "") == uid):
                    v["note"] = a["note"]
                else:
                    if reader is None:
                        reader = _note_reader(me, m, ch)
                    if reader:
                        v["note"] = a["note"]
            cant.append(v)
            continue
        if a:
            moved = True
            v["said_before"] = a.get("answer")
        waiting.append(v)
    mine = None
    if own and own.get("active") is not False:
        a = got.get(str(own["id"]))
        mine = {"member_id": str(own["id"]),
                "answer": a.get("answer") if a and current(a, m) else None,
                "note": a.get("note") if a and current(a, m) else None}
    why = answerable(m)
    return {"meeting_id": str(m["id"]), "coming": coming, "cant": cant, "waiting": waiting, "moved": moved,
            "mine": mine, "open": why is None, "why": why,
            "can": {"mark": cb.may_write(me, group["id"]) and why is None}}


def _write_answer(biz: str, m: Dict[str, Any], seat: Dict[str, Any], ans: Any, note: Any, *,
                  by_user: Optional[str] = None, by_contact: Optional[str] = None) -> None:
    """One person's answer for this meeting's time, or none (taken back).
    Upserted on its primary key (meeting_id, member_id). Everything is
    checked before the write; a write that fails is a 503."""
    why = answerable(m)
    if why:
        raise HTTPException(409, why)
    if seat.get("active") is False:
        raise HTTPException(409, LEFT)
    if ans not in (*ANSWERS, None):
        raise HTTPException(400, "Answer I'll be there, or I can't.")
    text = note_of(note)
    if text and ans != "cant":
        raise HTTPException(400, NOTE_CANT)
    if ans is None:
        if not sb_clients.sb_delete_as_service(
                f"/church_meeting_answers?business_id=eq.{_q(biz)}&meeting_id=eq.{_q(m['id'])}"
                f"&member_id=eq.{_q(seat['id'])}"):
            raise HTTPException(503, UNSAVED)
        return
    got = sb_clients.sb_post_as_service("/church_meeting_answers?on_conflict=meeting_id,member_id", {
        "business_id": biz, "meeting_id": str(m["id"]), "member_id": str(seat["id"]), "answer": ans,
        "note": text, "for_starts_at": m["starts_at"], "by_user_id": by_user, "by_contact_id": by_contact,
        "answered_at": _iso(_now())}, prefer="resolution=merge-duplicates,return=representation", redact=True)
    if not isinstance(got, list) or not got:
        raise HTTPException(503, UNSAVED)


def put_answer(me: Dict[str, Any], m: Dict[str, Any], group: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    """This login's own answer (no member_id: a seat with its login, or with
    its person), or someone else's for them ("she called to say she
    can't"), which whoever may write the meeting gives; by_user_id says who."""
    import church_board as cb
    import church_over as co
    biz = str(me["biz"]["id"])
    seats = cb._members(biz, [str(group["id"])], everyone=True)
    uid = str(me["uid"])
    if body.get("member_id") not in (None, ""):
        sid = cb._uuid(body["member_id"], "member")
        seat = next((s for s in seats if str(s["id"]) == sid), None)
        if seat is None:
            raise HTTPException(400, THEY_NOT_IN)
        own = str(seat.get("user_id") or "") == uid or (
            seat.get("contact_id") and str(seat["contact_id"]) == str(co.Church(me["biz"]).login_person.get(uid) or ""))
        if not own:
            cb._writes(me, group["id"])
    else:
        seat = _own_seat(seats, uid, co.Church(me["biz"]).login_person.get(uid))
        if seat is None:
            raise HTTPException(403, NOT_IN)
    _write_answer(biz, m, seat, body.get("answer"), body.get("note"), by_user=uid)
    return answers_view(me, m, group)


# ─── The member app's side (S3-5 draws it) ───────────────────────────

def _person_seat(biz: str, group: Dict[str, Any], person: str) -> Optional[Dict[str, Any]]:
    import church_board as cb
    seats = cb._members(biz, [str(group["id"])], everyone=True)
    mine = [s for s in seats if str(s.get("contact_id") or "") == str(person)]
    mine.sort(key=lambda s: s.get("active") is False)
    return mine[0] if mine else None


def person_view(biz: Dict[str, Any], person: str, meeting_id: Any) -> Dict[str, Any]:
    """What a person reads of a meeting they are in, in the member app: their
    own answer (and their own note), and how many said they'll be there.
    Never who can't, never anyone's note but theirs."""
    import church_board as cb
    if not on(biz):
        raise HTTPException(404, "Not Found")
    b = str(biz["id"])
    m = _meeting_row(b, meeting_id)
    group = _group_row(b, m["board_id"])
    before_member_page(biz, group)
    seat = _person_seat(b, group, person)
    if seat is None or seat.get("active") is False:
        raise HTTPException(404, "That meeting isn't here.")
    active = {str(s["id"]) for s in cb._members(b, [str(group["id"])])}
    got = [a for a in answers_of(b, [m["id"]]) if current(a, m)]
    mine = next((a for a in got if str(a["member_id"]) == str(seat["id"])), None)
    why = answerable(m)
    return {"meeting_id": str(m["id"]), "answer": (mine or {}).get("answer"), "note": (mine or {}).get("note"),
            "coming": sum(1 for a in got if a.get("answer") == "yes" and str(a["member_id"]) in active),
            "open": why is None, "why": why}


def person_answer(biz: Dict[str, Any], person: str, meeting_id: Any, ans: Any, note: Any = None) -> Dict[str, Any]:
    """A person's own answer, from the member app: their seat on the
    meeting's group (by their person), by_contact_id them."""
    if not on(biz):
        raise HTTPException(404, "Not Found")
    b = str(biz["id"])
    m = _meeting_row(b, meeting_id)
    group = _group_row(b, m["board_id"])
    before_member_page(biz, group)
    seat = _person_seat(b, group, person)
    if seat is None:
        raise HTTPException(404, "That meeting isn't here.")
    _write_answer(b, m, seat, ans, note, by_contact=str(person))
    return person_view(biz, person, meeting_id)


# ─── Routes ───────────────────────────────────────────────────────────

def _meeting_and_group(me: Dict[str, Any], meeting_id: str):
    import church_board as cb
    m = cb._meeting(me, meeting_id)
    group = cb._board(me, m["board_id"])
    return m, group


@router.post("")
def meetings_set(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    return set_meeting(_gate(body.get("business_id"), user), body)


@router.get("/{meeting_id}/answers")
def meetings_answers(meeting_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    me = _gate(business_id, user)
    m, group = _meeting_and_group(me, meeting_id)
    before_page(me, group)
    return answers_view(me, m, group)


@router.put("/{meeting_id}/answers")
def meetings_answer(meeting_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    me = _gate(body.get("business_id"), user)
    m, group = _meeting_and_group(me, meeting_id)
    before_page(me, group)
    return put_answer(me, m, group, body)
