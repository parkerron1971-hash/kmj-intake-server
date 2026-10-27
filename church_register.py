"""church_register.py — the church register: baptisms, dedications, weddings,
funerals and membership dates, kept for good, with certificates.

Kevin, 2026-10-27, on the Church Office Prototypes ("Church register" tab,
artifact 2vGqaUZUynRuiFVKuQEZWo): "lets go with your list", the register
fourth, after help requests, serving hours and check requests. Lane: Build,
under the Build item "Love City leaves Subsplash (M-1)".

    an ENTRY ...... one event in the church's life: a baptism, a baby
                    dedication, a wedding, a funeral, or a membership date
                    (joined, transferred in, transferred out, removed). Its
                    day, its people, who officiated, where, the other church
                    for a transfer, and notes. Done (it happened) or planned
                    (a date is set)
    its PEOPLE .... named the way the day recorded them ([{role, contact_id,
                    name}]): a later change on Members doesn't rewrite the
                    register. The church's own people carry their contact
                    id (contact_ids beside them, so a person's page finds
                    their milestones); someone who isn't one of them is a
                    name
    an ASK ........ a member's "Plan a life event" from the app
                    (member_asks.py) lands in Prayer & care
                    (ministry_care_requests, submission.kind "life_event",
                    the event's words in submission.life_event, a date in
                    submission.date if they gave one). It waits at the top of
                    the register until the office marks it planned (with a
                    date) or records it (it happened): then it is an entry,
                    once (care_request_id is unique), and its Prayer & care
                    row moves along: reviewed once planned, closed once it
                    happened. Reading writes nothing
    the IMPORT .... baptism dates that came over from Subsplash
                    (contacts.metadata.imported["Baptism date"],
                    subsplash_import.py). Nothing is written until the office
                    presses "Add them to the register" (one press for all, or
                    one person from their page): then each is a baptism
                    entry, once per person (import_key), and stays out of
                    the offer even if it is later removed
    a CERTIFICATE . a baptism, a dedication or a wedding that happened prints
                    one, in the church's name and colours. What it says comes
                    from the entry alone (its people as recorded, its day,
                    officiant and place), never from anyone's record

Who: the owner, admins, and office logins whose areas include People & care
or Office (church_areas, "Who sees what"; while that is off, every login sees
the whole church, as before). Funerals and membership removals are the
owner's, admins' and People & care's alone, and so are the asks (they come
from Prayer & care, which is confidential). A viewer login reads; a member-
level login and up adds and changes; only the owner and admins remove. A
removed entry is marked (removed_at, removed_by): it leaves the page and the
year's numbers but stays on file.

  GET    /church/register/status?business_id=                    {enabled, view, write, remove}
  GET    /church/register?business_id=&year=                      the year's numbers, its entries, what's planned,
                                                                   the asks waiting
  POST   /church/register/entries                                 {business_id, kind, membership?, status?, event_on,
                                                                   people, officiant?, place?, other_church?, notes?}
  PATCH  /church/register/entries/{id}                            {business_id, ...what changes}
  DELETE /church/register/entries/{id}?business_id=               remove (the owner and admins)
  GET    /church/register/entries/{id}/certificate?business_id=   what its certificate prints
  POST   /church/register/asks/{care_id}                          {business_id, status: planned | done, event_on?,
                                                                   kind?, people?, officiant?, place?, notes?}
  GET    /church/register/person/{contact_id}?business_id=        one person's milestones
  GET    /church/register/import?business_id=                     baptism dates from the import, not in yet
  POST   /church/register/import                                  {business_id, contact_id?}: add them

Switched by CHURCH_REGISTER: off | owner | on (owner until a Thursday). Until
supabase/APPLY-2026-10-27-church-register.sql is applied the status says
enabled false and every other route answers 503, never 500.
"""
from __future__ import annotations

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
router = APIRouter(prefix="/church/register", tags=["church"])

KINDS = ("baptism", "dedication", "wedding", "funeral", "membership")
MEMBERSHIP = ("joined", "transferred_in", "transferred_out", "removed")
TRANSFERS = ("transferred_in", "transferred_out")
STATUSES = ("planned", "done")
CERT_KINDS = ("baptism", "dedication", "wedding")
# Who each kind of entry names, its first role the one it can't be without.
ROLES: Dict[str, tuple] = {
    "baptism": ("person",), "dedication": ("child", "parent"), "wedding": ("spouse",),
    "funeral": ("person",), "membership": ("person",),
}
MAIN = {k: v[0] for k, v in ROLES.items()}
ROLE_MOST = {("wedding", "spouse"): 2, ("dedication", "parent"): 4}
MAIN_WORD = {"baptism": "who was baptized", "dedication": "the child", "wedding": "the couple",
             "funeral": "who died", "membership": "who it's for"}
KIND_WORD = {"baptism": "baptism", "dedication": "dedication", "wedding": "wedding", "funeral": "funeral",
             "membership": "membership"}
CERT_TITLE = {"baptism": "Certificate of Baptism", "dedication": "Certificate of Dedication",
              "wedding": "Certificate of Holy Matrimony"}

WRITERS = ("owner", "admin", "manager", "member")   # add and change
KEEPS_ALL = ("owner", "admin")                      # remove; youth asks
CARE_AREA = "people_care"
OFFICE_AREA = "office"

PEOPLE_MAX = 12
NAME_MAX, OFFICIANT_MAX, PLACE_MAX, NOTES_MAX = 120, 120, 160, 2000
FIRST_YEAR = 1850
PLAN_YEARS = 3

# member_asks.py's contract: submission.kind "life_event", the pick's words
# in submission.life_event ("A baptism"), a day in submission.date.
KIND_LIFE = "life_event"
YOUTH_SOURCE = "Member app, Youth"
LIFE_KIND = {"a wedding": "wedding", "wedding": "wedding", "a funeral": "funeral", "funeral": "funeral",
             "a baby dedication": "dedication", "a dedication": "dedication", "dedication": "dedication",
             "a baptism": "baptism", "baptism": "baptism"}

# subsplash_import.py keeps the person's baptism date here.
IMPORT_FROM = "Subsplash"
IMPORT_FIELD = "Baptism date"
IMPORT_KEY = "subsplash-baptism"

ENTRY_FIELDS = ("id,kind,membership,status,event_on,people,contact_ids,officiant,place,other_church,notes,source,"
                "care_request_id,created_at,updated_at")
CARE_FIELDS = "id,created_at,status,submission,contact_id"


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_REGISTER") or "owner").strip().lower()
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
    """A read that must answer: a failed one (or the table before its
    migration) is a 503, never an empty register."""
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, "The register couldn't be read just now. Try again.")
    return rows


PAGE = 1000          # the most rows one read returns (PostgREST's cap)
MAX_ROWS = 100_000   # past this a read is refused, never cut short


def _need_all(path: str, order: str) -> List[Dict[str, Any]]:
    """Every row, a page at a time in a stable order: a read the server
    caps is never taken for the whole (a count cut short, or a baptism
    offered twice)."""
    out: List[Dict[str, Any]] = []
    while True:
        rows = _need(f"{path}&order={order}&limit={PAGE}&offset={len(out)}")
        out += rows
        if len(rows) < PAGE:
            return out
        if len(out) >= MAX_ROWS:
            raise HTTPException(503, "The register has more rows than one page can read. Try again later.")


def _tz(biz_id: str) -> ZoneInfo:
    try:
        import outside_calendar
        return ZoneInfo(outside_calendar.business_timezone(biz_id) or "UTC")
    except (ZoneInfoNotFoundError, ValueError, Exception):
        return ZoneInfo("UTC")


def _today(me: Dict[str, Any]) -> date:
    """Today in the church's clock (read once per request, when needed)."""
    if "tz" not in me:
        me["tz"] = _tz(str(me["biz"]["id"]))
    return _now().astimezone(me["tz"]).date()


def _chunks(ids: Iterable[Any], n: int = 100) -> Iterable[List[str]]:
    ids = sorted({str(i) for i in ids if i})
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def _day_of(v: Any) -> Optional[date]:
    """A stored or typed day: '2026-10-18' (a timestamp's day too)."""
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def import_day(v: Any) -> Optional[date]:
    """A date as Subsplash's export writes it: '2019-04-21', '2019-04-21
    00:00:00', or '4/21/2019'. None for anything else, or a day that can't
    have been (before 1900, or after today)."""
    s = _plain(v)
    d = _day_of(s)
    if d is None:
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})(?:\s.*)?", s)
        if m:
            try:
                d = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            except ValueError:
                d = None
    if d is None or d < date(1900, 1, 1) or d > _now().date():
        return None
    return d


# ─── Who's asking ─────────────────────────────────────────────────────

def _business(biz_id: str) -> Dict[str, Any]:
    rows = _need(f"/businesses?id=eq.{_q(biz_id)}&select=id,name,type,owner_id,settings&limit=1")
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def view_of(biz_id: str, uid: str, role: str) -> Optional[str]:
    """'care' (everything, the asks too), 'office' (all but funerals and
    removals) or None, for one login. The owner and admins always care;
    while Who sees what is off every login sees the whole church, as
    before; else a login whose areas are the whole church or include People
    & care, and the office's view for one that works the Office. A view
    that couldn't be read is a 503, never a yes."""
    if role in KEEPS_ALL:
        return "care"
    import church_areas
    if church_areas.mode() != "on":
        return "care"
    view = church_areas.my_areas(biz_id, uid, role)
    if view is None:
        raise HTTPException(503, "Your areas couldn't be read just now. Try again.")
    areas = view.get("areas")
    if areas is None or CARE_AREA in areas:
        return "care"
    if OFFICE_AREA in areas:
        return "office"
    return None


def _access(business_id: Any, user: AuthedUser) -> Dict[str, Any]:
    """The church, and this login's standing in its register. 404 when the
    switch is closed to them, they have no login here, or it isn't a
    church; 403 for a login that works neither People & care nor the
    Office."""
    if not open_to(user):
        raise HTTPException(404, "Not Found")
    biz_id = _uuid(business_id, "church")
    role = business_access.assert_access(biz_id, user, "viewer")
    biz = _business(biz_id)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, "The register is for churches")
    view = view_of(biz_id, str(user.id), role)
    if view is None:
        raise HTTPException(403, "The register is kept by the pastors, the care team and the office. "
                                 "An admin can add People & care or Office to your areas.")
    return {"biz": biz, "role": role, "uid": str(user.id), "user": user, "view": view,
            "boss": role in KEEPS_ALL, "writer": role in WRITERS}


def _writer(me: Dict[str, Any]) -> None:
    if not me["writer"]:
        raise HTTPException(403, "Your login can read the register but not change it.")


def _care(me: Dict[str, Any]) -> None:
    if me["view"] != "care":
        raise HTTPException(403, "Asks from the member app stay with the pastors and the care team.")


def _ready(biz_id: str) -> bool:
    """The table answers (one migration makes it)."""
    return isinstance(sb_clients.sb_get_as_service(
        f"/church_register_entries?business_id=eq.{_q(biz_id)}&select=id&limit=1"), list)


def _can(me: Dict[str, Any]) -> Dict[str, Any]:
    return {"view": me["view"], "write": me["writer"], "remove": me["boss"], "asks": me["view"] == "care"}


def visible(me: Dict[str, Any], row: Dict[str, Any]) -> bool:
    """Funerals and membership removals are People & care's: the office's
    view never has them, not even as a number."""
    if me["view"] == "care":
        return True
    return row.get("kind") != "funeral" and not (row.get("kind") == "membership" and row.get("membership") == "removed")


# ─── Reading ──────────────────────────────────────────────────────────

def shown(row: Dict[str, Any]) -> Dict[str, Any]:
    people = row.get("people") if isinstance(row.get("people"), list) else []
    return {
        "id": str(row["id"]), "kind": row.get("kind"), "membership": row.get("membership"),
        "status": row.get("status"), "event_on": str(row.get("event_on") or "")[:10],
        "people": [{"role": p.get("role"), "name": p.get("name") or "", "contact_id": p.get("contact_id")}
                   for p in people if isinstance(p, dict)],
        "officiant": row.get("officiant"), "place": row.get("place"), "other_church": row.get("other_church"),
        "notes": row.get("notes") or "", "source": row.get("source") or "office",
        "from_ask": bool(row.get("care_request_id")),
        "certificate": row.get("kind") in CERT_KINDS and row.get("status") == "done",
        "created_at": row.get("created_at"), "updated_at": row.get("updated_at"),
    }


def counts(me: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """One year's numbers, from the entries that happened. The office's view
    has no funeral or removal count at all (None, not 0)."""
    n = {k: 0 for k in ("baptism", "dedication", "wedding", "funeral")}
    m = {k: 0 for k in MEMBERSHIP}
    for r in rows:
        if r.get("kind") == "membership":
            if r.get("membership") in m:
                m[r["membership"]] += 1
        elif r.get("kind") in n:
            n[r["kind"]] += 1
    care = me["view"] == "care"
    return {**n, "funeral": n["funeral"] if care else None, **m, "removed": m["removed"] if care else None,
            "new_members": m["joined"] + m["transferred_in"]}


def _from_ask(care: Dict[str, Any]) -> Dict[str, Any]:
    """A member's ask from the app, in the shape the page reads."""
    sub = care.get("submission") if isinstance(care.get("submission"), dict) else {}
    words = _plain(sub.get("life_event"))
    text = _text(sub.get("request"), NOTES_MAX)
    when = _day_of(sub.get("date"))
    return {
        "id": str(care["id"]), "kind": LIFE_KIND.get(words.lower()), "asked_for": words or "A life event",
        "who": _plain(sub.get("name"))[:NAME_MAX] or None, "contact_id": care.get("contact_id"),
        "text": "" if text == words else text, "date": when.isoformat() if when else None,
        "wants_call": str(sub.get("wants_call") or "").lower() in ("yes", "true", "1"),
        "youth": _youth(sub), "status": care.get("status"), "created_at": care.get("created_at"),
    }


def _youth(sub: Dict[str, Any]) -> bool:
    return str(sub.get("youth") or "").lower() in ("yes", "true", "1") or sub.get("source") == YOUTH_SOURCE


def _is_life(care: Dict[str, Any]) -> bool:
    sub = care.get("submission")
    return isinstance(sub, dict) and sub.get("kind") == KIND_LIFE


def asks(me: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Life-event asks still open in Prayer & care with no entry of their
    own yet (a removed entry still counts as theirs)."""
    biz = str(me["biz"]["id"])
    rows = _need(f"/ministry_care_requests?business_id=eq.{_q(biz)}&submission->>kind=eq.{KIND_LIFE}"
                 f"&status=in.(new,reviewed)&select={CARE_FIELDS}&order=created_at.desc&limit=200")
    rows = [r for r in rows if _is_life(r)]
    linked: Set[str] = set()
    for ids in _chunks(r["id"] for r in rows):
        linked |= {str(x.get("care_request_id")) for x in _need(
            f"/church_register_entries?business_id=eq.{_q(biz)}&care_request_id=in.({','.join(ids)})"
            "&select=care_request_id&limit=200")}
    out = [_from_ask(r) for r in rows if str(r["id"]) not in linked]
    return [a for a in out if me["boss"] or not a["youth"]]


def page(me: Dict[str, Any], year: Any = None) -> Dict[str, Any]:
    biz = str(me["biz"]["id"])
    today = _today(me)
    if year in (None, ""):
        y = today.year
    else:
        try:
            y = int(str(year))
        except ValueError:
            raise HTTPException(400, "Pick a year, like 2026.")
        if not FIRST_YEAR <= y <= today.year + PLAN_YEARS:
            raise HTTPException(400, "Pick a year, like 2026.")
    done = f"/church_register_entries?business_id=eq.{_q(biz)}&removed_at=is.null&status=eq.done"
    # The year: every entry that happened in it (its numbers come from these).
    entries = [r for r in _need_all(f"{done}&event_on=gte.{y}-01-01&event_on=lte.{y}-12-31&select={ENTRY_FIELDS}",
                                    "event_on.desc,created_at.desc,id.desc") if visible(me, r)]
    # The years the register holds: from its first entry to this year (or its last).
    ends = {}
    for way in ("asc", "desc"):
        rows = _need(f"{done}&select=event_on&order=event_on.{way}&limit=1")
        ends[way] = int(str(rows[0]["event_on"])[:4]) if rows and rows[0].get("event_on") else None
    first_year = ends["asc"]
    top = max(today.year, ends["desc"] or today.year)
    years = list(range(top, min(first_year or today.year, today.year) - 1, -1))
    planned = [r for r in _need(
        f"/church_register_entries?business_id=eq.{_q(biz)}&removed_at=is.null&status=eq.planned"
        f"&select={ENTRY_FIELDS}&order=event_on.asc&limit=500") if visible(me, r)]
    return {
        "year": y, "years": years, "first_year": first_year, "today": today.isoformat(),
        "counts": counts(me, entries), "entries": [shown(r) for r in entries], "planned": [shown(r) for r in planned],
        "asks": asks(me) if me["view"] == "care" else [], "me": _can(me),
    }


# ─── Writing ──────────────────────────────────────────────────────────

def _people(me: Dict[str, Any], kind: str, raw: Any, kept: Iterable[str] = ()) -> List[Dict[str, Any]]:
    """Who the entry names, checked: the roles its kind has, its first role
    at least once, the church's own people by id (named as they are today
    when no name is given), anyone else by name. A person the entry already
    named who has since left the church's list keeps their name and loses
    the link; a new one must be one of the church's people."""
    if not isinstance(raw, list) or not raw:
        raise HTTPException(400, f"Name {MAIN_WORD[kind]}.")
    if len(raw) > PEOPLE_MAX:
        raise HTTPException(400, f"An entry names {PEOPLE_MAX} people at most.")
    biz = str(me["biz"]["id"])
    wanted: List[str] = []
    for p in raw:
        if not isinstance(p, dict):
            raise HTTPException(400, f"Name {MAIN_WORD[kind]}.")
        if p.get("contact_id") not in (None, ""):
            wanted.append(_uuid(p["contact_id"], "person"))
    names: Dict[str, str] = {}
    for ids in _chunks(wanted):
        for c in _need(f"/contacts?business_id=eq.{_q(biz)}&id=in.({','.join(ids)})&select=id,name&limit=200"):
            names[str(c["id"])] = _plain(c.get("name"))
    kept = {str(k) for k in kept}
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for p in raw:
        role = p.get("role") or MAIN[kind]
        if role not in ROLES[kind]:
            raise HTTPException(400, f"A {KIND_WORD[kind]} names {' and '.join(r + 's' for r in ROLES[kind])}.")
        cid = _uuid(p["contact_id"], "person") if p.get("contact_id") not in (None, "") else None
        if cid and cid not in names:
            if cid not in kept:
                raise HTTPException(400, "That person isn't one of this church's people.")
            cid = None
        if cid and cid in seen:
            raise HTTPException(400, "That person is named twice.")
        name = _plain(p.get("name"))[:NAME_MAX] or (names.get(cid, "")[:NAME_MAX] if cid else "")
        if not name:
            raise HTTPException(400, "Each person needs a name.")
        if cid:
            seen.add(cid)
        out.append({"role": role, "contact_id": cid, "name": name})
    if not any(p["role"] == MAIN[kind] for p in out):
        raise HTTPException(400, f"Name {MAIN_WORD[kind]}.")
    for (k, role), most in ROLE_MOST.items():
        if k == kind and sum(1 for p in out if p["role"] == role) > most:
            raise HTTPException(400, f"A {KIND_WORD[kind]} names {most} {role}s at most.")
    return out


def entry_fields(me: Dict[str, Any], body: Dict[str, Any], kept: Iterable[str] = ()) -> Dict[str, Any]:
    """A whole entry, checked. Funerals and removals are People & care's."""
    kind = body.get("kind")
    if kind not in KINDS:
        raise HTTPException(400, "Pick what it is: a baptism, a dedication, a wedding, a funeral or membership.")
    if kind == "funeral" and me["view"] != "care":
        raise HTTPException(403, "Funerals are kept with the pastors and the care team.")
    membership = None
    if kind == "membership":
        membership = body.get("membership")
        if membership not in MEMBERSHIP:
            raise HTTPException(400, "Say how: joined, transferred in, transferred out or removed.")
        if membership == "removed" and me["view"] != "care":
            raise HTTPException(403, "Removals from membership are kept with the pastors and the care team.")
    status = body.get("status") or "done"
    if status not in STATUSES:
        raise HTTPException(400, "An entry happened, or it's planned.")
    day = _day_of(body.get("event_on"))
    if day is None:
        raise HTTPException(400, "Pick the day." if status == "done" else "Pick the day it's planned for.")
    today = _today(me)
    if day.year < FIRST_YEAR or day.year > today.year + PLAN_YEARS:
        raise HTTPException(400, "Pick a day the church can keep.")
    if status == "done" and day > today + timedelta(days=1):
        raise HTTPException(400, "That day hasn't come yet. Mark it planned, and record it once it happens.")
    people = _people(me, kind, body.get("people"), kept)
    return {
        "kind": kind, "membership": membership, "status": status, "event_on": day.isoformat(),
        "people": people, "contact_ids": sorted({p["contact_id"] for p in people if p["contact_id"]}),
        "officiant": _plain(body.get("officiant"))[:OFFICIANT_MAX] or None,
        "place": _plain(body.get("place"))[:PLACE_MAX] or None,
        "other_church": (_plain(body.get("other_church"))[:PLACE_MAX] or None) if membership in TRANSFERS else None,
        "notes": _text(body.get("notes"), NOTES_MAX),
    }


EDITABLE = ("kind", "membership", "status", "event_on", "people", "officiant", "place", "other_church", "notes")


def resolve(me: Dict[str, Any], entry_id: Any) -> Dict[str, Any]:
    """An entry of this church this login may see, not removed. Anything
    else reads as missing."""
    biz = str(me["biz"]["id"])
    rows = _need(f"/church_register_entries?id=eq.{_q(_uuid(entry_id, 'entry'))}&business_id=eq.{_q(biz)}"
                 f"&removed_at=is.null&select={ENTRY_FIELDS}&limit=1")
    if not rows or not visible(me, rows[0]):
        raise HTTPException(404, "That entry isn't here.")
    return rows[0]


def _move_care(biz: str, care_id: Any, status: str) -> None:
    """The ask's Prayer & care row follows: reviewed once planned, closed
    once it happened. Best effort: the register is the record."""
    if not care_id:
        return
    frm = "(new,reviewed)" if status == "closed" else "(new)"
    now = _iso(_now())
    try:
        got = sb_clients.sb_patch_as_service(
            f"/ministry_care_requests?id=eq.{_q(care_id)}&business_id=eq.{_q(biz)}&status=in.{frm}",
            {"status": status, "status_changed_at": now, "updated_at": now})
    except Exception:
        got = None
    if not isinstance(got, list):
        # Printed so it reaches the logs; the next press on the ask tries again.
        print(f"[church_register] the Prayer & care row {care_id} didn't move to {status}")
        logger.warning("church register: the Prayer & care row %s didn't move to %s", care_id, status)


def add(me: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    _writer(me)
    fields = entry_fields(me, body)
    now = _iso(_now())
    saved = sb_clients.sb_post_as_service("/church_register_entries", {
        **fields, "business_id": str(me["biz"]["id"]), "source": "office", "created_by": me["uid"],
        "updated_by": me["uid"], "created_at": now, "updated_at": now})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That entry didn't save. Try again.")
    return {"entry": shown(saved[0])}


def edit(me: Dict[str, Any], entry_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Change what an entry says. A planned one that happened closes its
    ask in Prayer & care."""
    _writer(me)
    row = resolve(me, entry_id)
    merged = {k: row.get(k) for k in EDITABLE}
    merged.update({k: body[k] for k in EDITABLE if k in body})
    kept = [p.get("contact_id") for p in (row.get("people") or []) if isinstance(p, dict) and p.get("contact_id")]
    fields = entry_fields(me, merged, kept)
    biz = str(me["biz"]["id"])
    fields.update(updated_by=me["uid"], updated_at=_iso(_now()))
    got = sb_clients.sb_patch_as_service(
        f"/church_register_entries?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz)}&removed_at=is.null", fields)
    if not isinstance(got, list):
        raise HTTPException(503, "That didn't save. Try again.")
    if not got:
        raise HTTPException(409, "Someone removed this entry just now.")
    if row.get("status") == "planned" and fields["status"] == "done":
        _move_care(biz, row.get("care_request_id"), "closed")
    return {"entry": shown(got[0])}


def remove(me: Dict[str, Any], entry_id: str) -> Dict[str, Any]:
    """Take an entry off the register: the owner and admins. It stays on
    file, marked, and leaves the page and the numbers."""
    if not me["boss"]:
        raise HTTPException(403, "Only the owner or an admin removes an entry from the register.")
    row = resolve(me, entry_id)
    biz = str(me["biz"]["id"])
    got = sb_clients.sb_patch_as_service(
        f"/church_register_entries?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz)}&removed_at=is.null",
        {"removed_at": _iso(_now()), "removed_by": me["uid"]})
    if not isinstance(got, list):
        raise HTTPException(503, "Nothing was removed. Try again.")
    if not got:
        raise HTTPException(404, "That entry isn't here.")
    return {"removed": str(row["id"])}


# ─── Asks from the member app ─────────────────────────────────────────

def from_ask(me: Dict[str, Any], care_id: Any, body: Dict[str, Any]) -> Dict[str, Any]:
    """A member's ask becomes an entry, once: planned (with a date) or done.
    Two presses make one entry; the second answers with the first. Its
    Prayer & care row moves along."""
    _writer(me)
    _care(me)
    biz = str(me["biz"]["id"])
    cid = _uuid(care_id, "ask")
    care = _need(f"/ministry_care_requests?id=eq.{_q(cid)}&business_id=eq.{_q(biz)}&select={CARE_FIELDS}&limit=1")
    if not care or not _is_life(care[0]):
        raise HTTPException(404, "That ask isn't here.")
    ask = _from_ask(care[0])
    # An ask this login can't see reads as missing, entry or not.
    if ask["youth"] and not me["boss"]:
        raise HTTPException(404, "That ask isn't here.")
    have = _need(f"/church_register_entries?business_id=eq.{_q(biz)}&care_request_id=eq.{_q(cid)}"
                 f"&select={ENTRY_FIELDS}&limit=1")
    if have:
        # Already an entry: its Prayer & care row catches up if it didn't move before.
        _move_care(biz, cid, "reviewed" if have[0].get("status") == "planned" else "closed")
        return {"entry": shown(have[0]), "already": True}
    # Nothing is written for an ask Prayer & care already closed.
    if care[0].get("status") == "closed":
        raise HTTPException(409, "This one was closed in Prayer & care.")
    status = body.get("status")
    if status not in STATUSES:
        raise HTTPException(400, "Say whether it happened, or when it's planned.")
    kind = body.get("kind") or ask["kind"]
    if kind not in KINDS:
        raise HTTPException(400, "Pick what it is: a baptism, a dedication, a wedding or a funeral.")
    merged = {
        "kind": kind, "membership": body.get("membership"), "status": status,
        "event_on": body.get("event_on") or ask["date"],
        "people": body.get("people") or [{"role": MAIN[kind], "contact_id": ask["contact_id"], "name": ask["who"]}],
        "officiant": body.get("officiant"), "place": body.get("place"), "other_church": body.get("other_church"),
        "notes": body.get("notes"),
    }
    fields = entry_fields(me, merged)
    now = _iso(_now())
    saved = sb_clients.sb_post_as_service("/church_register_entries?on_conflict=care_request_id", {
        **fields, "business_id": biz, "source": "app", "care_request_id": cid, "created_by": me["uid"],
        "updated_by": me["uid"], "created_at": now, "updated_at": now},
        prefer="resolution=ignore-duplicates,return=representation")
    if not isinstance(saved, list):
        raise HTTPException(503, "That didn't save. Try again.")
    have = _need(f"/church_register_entries?business_id=eq.{_q(biz)}&care_request_id=eq.{_q(cid)}"
                 f"&select={ENTRY_FIELDS}&limit=1")
    if not have:
        raise HTTPException(503, "That didn't save. Try again.")
    _move_care(biz, cid, "reviewed" if have[0].get("status") == "planned" else "closed")
    return {"entry": shown(have[0]), "already": not saved}


# ─── One person ───────────────────────────────────────────────────────

def person(me: Dict[str, Any], contact_id: Any) -> Dict[str, Any]:
    """One of the church's people: their milestones, oldest first, and a
    baptism date from the import that isn't in the register yet."""
    biz = str(me["biz"]["id"])
    cid = _uuid(contact_id, "person")
    if not _need(f"/contacts?id=eq.{_q(cid)}&business_id=eq.{_q(biz)}&select=id&limit=1"):
        raise HTTPException(404, "That person isn't here.")
    rows = [r for r in _need(f"/church_register_entries?business_id=eq.{_q(biz)}&removed_at=is.null"
                             f"&contact_ids=cs.{{{cid}}}&select={ENTRY_FIELDS}&order=event_on.asc&limit=200")
            if visible(me, r)]
    try:
        waiting = import_candidates(me, only=cid)
    except HTTPException:
        waiting = []
    return {"entries": [shown(r) for r in rows],
            "imported": {"baptized_on": waiting[0]["baptized_on"]} if waiting else None, "me": _can(me)}


# ─── Baptism dates from the Subsplash import ──────────────────────────

def import_candidates(me: Dict[str, Any], only: Optional[str] = None) -> List[Dict[str, Any]]:
    """The church's people with a baptism date from the import and no
    baptism in the register: not one recorded by hand, and not one this
    import brought in before (even if it was removed since)."""
    biz = str(me["biz"]["id"])
    path = (f"/contacts?business_id=eq.{_q(biz)}&metadata->>imported_from=eq.{IMPORT_FROM}"
            "&select=id,name,imported:metadata->imported")
    if only:
        path += f"&id=eq.{_q(only)}"
    people = _need_all(path, "id.asc")
    found = []
    for c in people:
        imp = c.get("imported")
        if not isinstance(imp, dict):
            md = c.get("metadata") if isinstance(c.get("metadata"), dict) else {}
            imp = md.get("imported") if isinstance(md.get("imported"), dict) else {}
        day = import_day(imp.get(IMPORT_FIELD))
        if day:
            found.append({"contact_id": str(c["id"]), "name": _plain(c.get("name"))[:NAME_MAX] or "Unknown",
                          "baptized_on": day.isoformat()})
    if not found:
        return []
    keys: Set[str] = set()
    covered: Set[str] = set()
    have = _need_all(f"/church_register_entries?business_id=eq.{_q(biz)}&kind=eq.baptism"
                     + (f"&contact_ids=cs.{{{_q(only)}}}" if only else "")
                     + "&select=id,contact_ids,import_key,removed_at", "id.asc")
    for r in have:
        if r.get("import_key"):
            keys.add(str(r["import_key"]))
        if not r.get("removed_at"):
            covered |= {str(x) for x in (r.get("contact_ids") or [])}
    if only:
        keys |= {str(r["import_key"]) for r in _need(
            f"/church_register_entries?business_id=eq.{_q(biz)}&import_key=eq.{_q(f'{IMPORT_KEY}:{only}')}"
            "&select=import_key&limit=1")}
    out = [f for f in found if f"{IMPORT_KEY}:{f['contact_id']}" not in keys and f["contact_id"] not in covered]
    out.sort(key=lambda f: (f["baptized_on"], f["name"]), reverse=True)
    return out


def import_offer(me: Dict[str, Any]) -> Dict[str, Any]:
    waiting = import_candidates(me)
    years = sorted({int(f["baptized_on"][:4]) for f in waiting})
    return {"count": len(waiting), "first_year": years[0] if years else None,
            "last_year": years[-1] if years else None, "people": waiting[:6]}


def import_now(me: Dict[str, Any], contact_id: Any = None) -> Dict[str, Any]:
    """Add the waiting baptism dates as entries, once per person: two
    presses at once add each one once."""
    _writer(me)
    biz = str(me["biz"]["id"])
    only = _uuid(contact_id, "person") if contact_id not in (None, "") else None
    waiting = import_candidates(me, only=only)
    if only and not waiting:
        raise HTTPException(409, "Their baptism date is in the register already.")
    now = _iso(_now())
    added = 0
    for i in range(0, len(waiting), 200):
        rows = [{
            "business_id": biz, "kind": "baptism", "membership": None, "status": "done", "event_on": f["baptized_on"],
            "people": [{"role": "person", "contact_id": f["contact_id"], "name": f["name"]}],
            "contact_ids": [f["contact_id"]], "officiant": None, "place": None, "other_church": None,
            "notes": "From the Subsplash import.", "source": "import", "import_key": f"{IMPORT_KEY}:{f['contact_id']}",
            "created_by": me["uid"], "updated_by": me["uid"], "created_at": now, "updated_at": now,
        } for f in waiting[i:i + 200]]
        saved = sb_clients.sb_post_as_service("/church_register_entries?on_conflict=business_id,import_key", rows,
                                              prefer="resolution=ignore-duplicates,return=representation")
        if not isinstance(saved, list):
            raise HTTPException(503, f"{added} were added before something failed. Press it again: "
                                     "nothing is added twice." if added else "Nothing was added. Try again.")
        added += len(saved)
    return {"added": added}


# ─── The certificate ──────────────────────────────────────────────────

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")


def _hex(v: Any) -> Optional[str]:
    s = str(v or "").strip()
    return s if _HEX.match(s) else None


def church_look(biz: Dict[str, Any]) -> Dict[str, Any]:
    """The church's name, colours and mark, from its brand kit."""
    s = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    kit = s.get("brand_kit") if isinstance(s.get("brand_kit"), dict) else {}
    nested = kit.get("colors") if isinstance(kit.get("colors"), dict) else {}
    colors = {k: _hex(nested.get(k) or kit.get(f"{k}_color")) for k in ("primary", "secondary", "accent")}
    lib = s.get("media_library") if isinstance(s.get("media_library"), dict) else {}
    prof = lib.get("profile") if isinstance(lib.get("profile"), dict) else {}
    mark = prof.get("logo_primary") if isinstance(prof.get("logo_primary"), dict) else {}
    logo = str(kit.get("logo_url") or mark.get("url") or "").strip()
    return {"name": _plain(biz.get("name")) or "Our church", "colors": colors,
            "logo": logo if logo.startswith("https://") else None}


def certificate(me: Dict[str, Any], entry_id: str) -> Dict[str, Any]:
    """What a certificate prints: the entry's own words (its people as
    recorded, its day, officiant and place) and the church's name and
    colours. Nothing from anyone's record; no notes."""
    row = resolve(me, entry_id)
    if row.get("kind") not in CERT_KINDS:
        raise HTTPException(400, "Baptisms, dedications and weddings have a certificate.")
    if row.get("status") != "done":
        raise HTTPException(409, "A certificate prints once it has happened.")
    people = [p for p in (row.get("people") or []) if isinstance(p, dict)]
    return {
        "id": str(row["id"]), "kind": row["kind"], "title": CERT_TITLE[row["kind"]],
        "people": [{"role": p.get("role"), "name": _plain(p.get("name"))} for p in people],
        "event_on": str(row.get("event_on") or "")[:10], "officiant": row.get("officiant"), "place": row.get("place"),
        "church": church_look(me["biz"]),
    }


# ─── Routes ───────────────────────────────────────────────────────────

@router.get("/status")
def register_status(business_id: str, user: AuthedUser = Depends(require_user)):
    """Whether this login's office shows the register: the app asks once, so
    its menu offers the page only where it opens. Quietly false for a closed
    switch, a business that isn't a church, a login outside People & care
    and the Office, or the table not made yet."""
    off = {"enabled": False, "view": None, "write": False, "remove": False, "asks": False}
    if not open_to(user):
        return off
    try:
        me = _access(business_id, user)
    except HTTPException as e:
        if e.status_code in (403, 503) or e.detail == "The register is for churches":
            return off
        raise
    if not _ready(str(me["biz"]["id"])):
        return off
    return {"enabled": True, **_can(me)}


@router.get("")
def register_page(business_id: str, year: Optional[str] = None, user: AuthedUser = Depends(require_user)):
    return page(_access(business_id, user), year)


@router.post("/entries")
def register_add(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    me = _access((body or {}).get("business_id"), user)
    return add(me, body or {})


@router.patch("/entries/{entry_id}")
def register_edit(entry_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    me = _access((body or {}).get("business_id"), user)
    return edit(me, entry_id, body or {})


@router.delete("/entries/{entry_id}")
def register_remove(entry_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    return remove(_access(business_id, user), entry_id)


@router.get("/entries/{entry_id}/certificate")
def register_certificate(entry_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    return certificate(_access(business_id, user), entry_id)


@router.post("/asks/{care_id}")
def register_from_ask(care_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    me = _access((body or {}).get("business_id"), user)
    return from_ask(me, care_id, body or {})


@router.get("/person/{contact_id}")
def register_person(contact_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    return person(_access(business_id, user), contact_id)


@router.get("/import")
def register_import_offer(business_id: str, user: AuthedUser = Depends(require_user)):
    return import_offer(_access(business_id, user))


@router.post("/import")
def register_import(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    me = _access(body.get("business_id"), user)
    return import_now(me, body.get("contact_id"))
