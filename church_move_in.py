"""
church_move_in.py — the Move-in room.

Kevin, 2026-11-11, with the first founding church signing up: "create
upload areas of the information that they need to hand into the system
and I don't directly have to load it". Until now a church's move was a
handout and an inbox: the pastor emailed a spreadsheet, texted a logo,
and said the service times on a call. This is the same list (the eleven
things on "Your Church's Move to Solutionist"), inside the church's own
account, where each one is handed in and stays with the church.

WHAT AN ITEM IS
  One of ITEMS, in the handout's order. An item has any of:
    fields   a short form (text, long text, a number, or rows of a few
             columns). Saved as the item's `answers`.
    files    an upload slot: spreadsheets and PDFs, or pictures. Kept in
             the private business-documents bucket under
             "<church>/move-in/…", one row each in church_move_files.
    door     a place in the app where the real thing is done (Stripe for
             giving). Nothing is typed twice.
    live     what the system already knows (can the church take a gift;
             how many people are on file), read fresh on every look.

STATES
  todo -> handed_in -> checked, or -> needs (we asked for a change, with
  a note) -> handed_in again. A change to an item that was handed in
  takes it back to todo: what we checked is no longer what is there.
  Giving has no hand-in. Its state is Stripe's: todo, waiting, done.

WHO
  The church: the owner and admins, and any login that works the Office
  (as Rooms & spaces). A Viewer reads. Files are never read back to the
  church here: it sees the name, the size and the day.
  The platform owner: /platform/move-in reads every church's room with
  time-limited links to the files, and marks an item checked or asks for
  a change. Each hand-in emails the platform owner; the last one opens a
  ticket in Mission Control.

SWITCH
  CHURCH_MOVE_IN = off | owner | on. Unset is "owner": the platform's own
  church only. Tables: supabase/APPLY-2026-11-11-church-move-in.sql;
  until they are there the room says it is closed.
"""
from __future__ import annotations

import html
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

import business_access
import sb_clients
from auth_supabase import AuthedUser, require_user
from lead_admin import require_owner

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church/move-in", tags=["church"])
platform_router = APIRouter(prefix="/platform/move-in", tags=["platform"])

SWITCH = "CHURCH_MOVE_IN"
BUCKET = "business-documents"
FOLDER = "move-in"
MAX_FILE_BYTES = 15 * 1024 * 1024
TEXT_MAX, LONG_MAX, CELL_MAX, NOTE_MAX, NAME_MAX = 200, 2000, 160, 600, 120
ROWS_MAX = 40
LINK_TTL = 900

WRITERS = ("owner", "admin", "manager", "member")
KEEPS_ALL = ("owner", "admin")

_PATH_NAME = re.compile(r"[0-9a-f]{32}\.[a-z0-9]{2,7}")


# ─── The eleven ───────────────────────────────────────────────────────
# The handout's list, in its order and its words. `need` names what has
# to be there before the item can be handed in.

def _text(key: str, label: str, hint: str = "") -> Dict[str, Any]:
    return {"key": key, "label": label, "type": "text", "hint": hint}


def _long(key: str, label: str, hint: str = "") -> Dict[str, Any]:
    return {"key": key, "label": label, "type": "long", "hint": hint}


def _rows(key: str, label: str, columns: List[Tuple[str, str]], add: str, limit: int = ROWS_MAX) -> Dict[str, Any]:
    return {"key": key, "label": label, "type": "rows", "add": add, "max": limit,
            "columns": [{"key": k, "label": lbl} for k, lbl in columns]}


SHEETS = {"kind": "sheets", "words": "A spreadsheet (CSV or Excel) or a PDF, up to 15 MB each."}
PICTURES = {"kind": "pictures", "words": "JPG, PNG or WebP pictures, or a PDF of your logo, up to 15 MB each."}

ITEMS: List[Dict[str, Any]] = [
    {
        "key": "giving", "urgent": True, "live": "giving",
        "title": "Set up giving",
        "ask": "Have ready the church's legal name, its EIN, the bank account and one leader's photo ID.",
        "why": "Giving runs through Stripe, on an account that belongs to your church, so gifts go to your "
               "church's own bank account. Only the account owner can set it up. Stripe looks over every "
               "church before a gift can be given, and we don't control how long that takes. That's why "
               "this one comes first.",
        "door": {"label": "Open giving setup", "nav": {"tab": "operate", "sub": "payments"}},
    },
    {
        "key": "people", "urgent": True, "live": "people",
        "title": "Bring your people in",
        "ask": "One row per person: name, email, mobile, household, member or guest, birthday, adult or "
               "child. Save the spreadsheet as CSV, then bring it in here and check the families it makes.",
        "why": "This list becomes your members' app. The household column matters most: it's how "
               "families form and how children appear at kids check-in. A member signs in with the email "
               "or mobile you have for them, so anyone without one of their own can't sign in yet.",
        "door": {"label": "Bring in a spreadsheet", "import": "people"},
        "files": {**SHEETS, "max": 3, "label": "Stuck? Hand in the file as it is and we'll bring it in for you."},
        "need": "people",
    },
    {
        "key": "owner", "urgent": True,
        "title": "Name the person who owns the move",
        "ask": "One person at your church we work with every day this week. It doesn't have to be the pastor.",
        "why": "Questions come up during a move, like a family that looks wrong or a service time that's "
               "missing. This is the one person we ask. They tell us what's right, and we do the work.",
        "fields": [_text("name", "Their name"), _text("mobile", "Mobile number"), _text("email", "Email"),
                   _text("best_time", "Best time to reach them")],
        "need": ["name"],
    },
    {
        "key": "tools",
        "title": "What you use today, and when each one renews",
        "ask": "The name of each tool and its renewal date, so nothing renews by surprise.",
        "why": "It tells us what each part of the system is replacing for your church, and the renewal "
               "dates tell us what has to be working here first. Don't cancel anything yet. Keep each "
               "tool until the part that replaces it is working for your church.",
        "fields": [_text("giving", "Giving", "Name and renewal date"),
                   _text("checkin", "Kids check-in", "Name and renewal date"),
                   _text("app", "Your app", "Name and renewal date"),
                   _text("website", "Your website", "Name and renewal date"),
                   _text("texting", "Texting", "Name and renewal date"),
                   _long("other", "Anything else you pay for")],
        "need": "any",
    },
    {
        "key": "monthly_givers",
        "title": "How many people give monthly",
        "ask": "A close guess is fine.",
        "why": "Card details can't be moved from one company to another, so each person who gives monthly "
               "sets their gift up again here. The number tells us how many people we'll help you reach.",
        "fields": [{"key": "count", "label": "People who give monthly", "type": "number", "hint": ""},
                   _long("note", "Anything we should know")],
        "need": ["count"],
    },
    {
        "key": "giving_history",
        "title": "This year's giving",
        "ask": "Export it from the giving tool you use today: every gift this year with the giver, the "
               "date, the amount and the fund.",
        "why": "Each giver's year-end statement, in January, has to show the whole year, not only what they "
               "give after your move. This export is where the earlier months come from.",
        "files": {**SHEETS, "max": 6, "label": "Add the export"},
        "need": "files",
    },
    {
        "key": "logins",
        "title": "Choose your office logins",
        "ask": "Who gets one, and what each person looks after.",
        "why": "An office login is for someone who does the church's work in the system, like the person "
               "who records giving or the one who runs kids check-in. Each login is invited with the areas "
               "that person looks after, and nothing more. Members don't need one. They use the members' app.",
        "fields": [_rows("people", "Office logins",
                         [("name", "Name"), ("email", "Email"), ("looks_after", "Looks after")],
                         "Add a person", 35)],
        "need": ["people"],
    },
    {
        "key": "safety",
        "title": "Name two safety officers",
        "ask": "Two trusted adults, such as a pastor, an elder or someone with an office login, who will "
               "look at any member message the system holds back.",
        "why": "In the app, members can message each other and chat in their groups. Every message is "
               "checked before it's delivered, and one that looks harmful is held instead of sent. A safety "
               "officer looks at each held or reported message and decides whether it's delivered or "
               "removed. Staff don't read members' messages otherwise. Messaging stays off until two "
               "officers are named, so a held message always has someone to look at it.",
        "fields": [_rows("officers", "Safety officers", [("name", "Name"), ("contact", "Email or mobile")],
                         "Add an officer", 2)],
        "need": ["officers:2"],
    },
    {
        "key": "sunday",
        "title": "Your Sunday details",
        "ask": "Service times, kids rooms with ages, and your groups with each leader.",
        "why": "Your first Sunday is the day the whole move works toward. Your services are what members "
               "see coming up and what Sunday check-in is set up for. Kids rooms and their ages are how we "
               "put each child in the right room for kids check-in. Your groups and their leaders become "
               "the groups in the members' app.",
        # The first Sunday the church gathers with us. The welcome briefing asks it
        # ("When is your first Sunday with us?") and saves it here, as a draft like
        # any other line; the office can change it in the room.
        "fields": [_text("first_sunday", "Your first Sunday with us", "The date, like Sunday, November 22"),
                   _rows("services", "Services", [("day", "Day"), ("time", "Time"), ("name", "What it's called")],
                         "Add a service", 12),
                   _rows("kids_rooms", "Kids rooms", [("room", "Room"), ("ages", "Ages")], "Add a room", 20),
                   _rows("groups", "Groups and classes",
                         [("name", "Group"), ("leader", "Leader"), ("meets", "When it meets")], "Add a group")],
        "need": ["services"],
    },
    {
        "key": "look",
        "title": "Your look",
        "ask": "Your logo, your church colour, 10 to 15 photos and a link to your sermons.",
        "why": "Your logo and colour go on your members' app and your giving page, so they look like your "
               "church. Your photos are for your website, which follows after your first Sunday. The "
               "sermons link is how your recent messages get into the app.",
        "fields": [_text("colour", "Church colour", "A colour name or a code like #1D4ED8"),
                   _text("sermons", "Where your sermons are", "A YouTube, Vimeo or Facebook link")],
        "files": {**PICTURES, "max": 20, "label": "Add your logo and photos"},
        "need": "files",
    },
    {
        "key": "room",
        "title": "About the room",
        "ask": "What we'll find on Saturday when we rehearse.",
        "why": "On your first Sunday the church signs in on their phones from a code on the screen, so the "
               "Wi-Fi has to reach the seats and the screen has to be one everyone can see. Kids check-in "
               "needs a tablet and a label printer for name tags. Knowing this now leaves time to fix a gap "
               "before Saturday.",
        "fields": [_long("wifi", "Wi-Fi in the sanctuary", "Is there Wi-Fi, and does it reach the seats?"),
                   _text("screen", "The screen", "A projector, TVs, or none"),
                   _text("tablet", "A tablet for kids check-in", "What you have, or that you need one"),
                   _text("printer", "A label printer", "The model, or that you need one")],
        "need": ["wifi"],
    },
]
ITEM = {i["key"]: i for i in ITEMS}

STATE_WORDS = {"todo": "Not started", "started": "Started", "handed_in": "Handed in", "checked": "Checked",
               "needs": "Needs a change", "waiting": "Waiting on Stripe", "done": "Done"}
SETTLED = ("handed_in", "checked", "done")
# The move is FINISHED when we have checked every thing (giving: live with
# Stripe). Handed in is not finished: a thing can still come back needing a
# change, and the church has to be able to see that in its room.
FINISHED = ("checked", "done")
# One row that is not on the list: the day the church first saw its move
# finished (in `checked_at`). Home says "moved in" for a while from that
# day, then lets it go. Every read of the list keeps to ITEM, so this row
# is never taken for a thing to hand in.
MOVED_IN = "_moved_in"


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get(SWITCH) or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def switched_on(business_id: Any) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        import member_asks
        return member_asks.platform_church(business_id)
    return False


# ─── Small things ─────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v if v is not None else "")).strip()


def _lines(v: Any) -> str:
    s = str(v if v is not None else "").replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(re.sub(r"[ \t]+", " ", ln).rstrip() for ln in s.split("\n"))).strip()


def _uuid(v: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, f"That {what} isn't one we know.")


def _need(path: str) -> List[Dict[str, Any]]:
    """A read that must answer: a failed one (or the tables before their
    migration) is a 503, never an empty room."""
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, "The Move-in room couldn't be read just now. Try again.")
    return rows


def _item(key: Any) -> Dict[str, Any]:
    item = ITEM.get(str(key or ""))
    if not item:
        raise HTTPException(404, "That isn't on the move-in list.")
    return item


# ─── Who's asking ─────────────────────────────────────────────────────

def _business(biz_id: str) -> Dict[str, Any]:
    rows = _need(f"/businesses?id=eq.{_q(biz_id)}&select=id,name,type,owner_id,settings,stripe_account_id&limit=1")
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def _office(biz_id: str, uid: str, role: str) -> bool:
    """The owner and admins always; any login while Who sees what is off;
    else a login whose areas are the whole church or include the Office.
    A view that couldn't be read is a 503, never a yes."""
    if role in KEEPS_ALL:
        return True
    import church_areas
    if church_areas.mode() != "on":
        return True
    view = church_areas.my_areas(biz_id, uid, role)
    if view is None:
        raise HTTPException(503, "Your areas couldn't be read just now. Try again.")
    return view.get("areas") is None or "office" in (view.get("areas") or [])


def _access(business_id: Any, user: AuthedUser) -> Dict[str, Any]:
    """The church and this login's standing in its move. 404 when the
    switch is closed to the church, the login has no place here, or it
    isn't a church; 403 for a login that doesn't work the office."""
    biz_id = _uuid(business_id, "church")
    role = business_access.assert_access(biz_id, user, "viewer")
    if not switched_on(biz_id):
        raise HTTPException(404, "Not Found")
    biz = _business(biz_id)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, "The Move-in room is for churches")
    if not _office(biz_id, str(user.id), role):
        raise HTTPException(403, "The move belongs to the office. An admin can add the Office to your areas.")
    return {"biz": biz, "role": role, "uid": str(user.id), "email": (user.email or "").strip()}


def _writer(me: Dict[str, Any]) -> None:
    if me["role"] not in WRITERS:
        raise HTTPException(403, "This login reads the move. An admin can let it hand things in.")


def _ready(biz_id: str) -> bool:
    """Both tables answer (one migration makes both)."""
    return (isinstance(sb_clients.sb_get_as_service(
                f"/church_move_items?business_id=eq.{_q(biz_id)}&select=item&limit=1"), list)
            and isinstance(sb_clients.sb_get_as_service(
                f"/church_move_files?business_id=eq.{_q(biz_id)}&select=id&limit=1"), list))


# ─── What's on file ───────────────────────────────────────────────────

def _rows_of(biz_id: str) -> Dict[str, Dict[str, Any]]:
    rows = _need(f"/church_move_items?business_id=eq.{_q(biz_id)}"
                 "&select=item,state,answers,note,handed_in_at,handed_in_by,checked_at,updated_at&limit=50")
    return {r["item"]: r for r in rows if r.get("item") in ITEM}


def _files_of(biz_id: str) -> Dict[str, List[Dict[str, Any]]]:
    rows = _need(f"/church_move_files?business_id=eq.{_q(biz_id)}"
                 "&select=id,item,path,name,media_type,size_bytes,created_at&order=created_at.asc&limit=400")
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(str(r.get("item")), []).append(r)
    return out


def _live(biz: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """What the system already knows. A count that couldn't be read is
    None (not known), never 0."""
    import payments_core
    connected = bool(biz.get("stripe_account_id"))
    try:
        on_file = sb_clients.sb_count_as_service(f"/contacts?business_id=eq.{_q(biz['id'])}&select=id")
    except Exception:  # noqa: BLE001
        on_file = None
    return {"giving": {"connected": connected, "ready": connected and bool(payments_core.can_charge(biz))},
            "people": {"on_file": on_file if isinstance(on_file, int) else None}}


def _filled(item: Dict[str, Any], answers: Dict[str, Any], key: str) -> bool:
    name, _, at_least = key.partition(":")
    v = (answers or {}).get(name)
    if isinstance(v, list):
        return len(v) >= int(at_least or 1)
    return v not in (None, "", [])


def missing(item: Dict[str, Any], answers: Dict[str, Any], files: List[Dict[str, Any]],
            live: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """Why this item can't be handed in yet, in words; None when it can."""
    need = item.get("need")
    labels = {f["key"]: f["label"] for f in item.get("fields") or []}
    if need == "files":
        return None if files else "Add at least one file first."
    if need == "people":
        if files or (live.get("people") or {}).get("on_file"):
            return None
        return "Bring your people in first, or hand in the file."
    if need == "any":
        return None if any(_filled(item, answers, k) for k in labels) else "Fill in at least one line first."
    for key in need or []:
        if not _filled(item, answers, key):
            name, _, at_least = key.partition(":")
            if at_least:
                return f"{labels.get(name, name)}: add {at_least}."
            return f"{labels.get(name, name)} is still empty."
    return None


def _state(item: Dict[str, Any], row: Optional[Dict[str, Any]], files: List[Dict[str, Any]],
           live: Dict[str, Dict[str, Any]]) -> str:
    if item.get("live") == "giving":
        g = live["giving"]
        return "done" if g["ready"] else ("waiting" if g["connected"] else "todo")
    state = (row or {}).get("state") or "todo"
    if state not in ("handed_in", "checked", "needs"):
        return "started" if ((row or {}).get("answers") or files) else "todo"
    return state


def _finished(biz: Dict[str, Any]) -> bool:
    """Whether the whole move is done, for the menu: the room leaves the
    church's Home once it is (Kevin, 2026-11-12: "under the home section
    until everything for move in is complete and then it disappears"). The
    states only, so the menu's one question stays a small read."""
    rows, live = _rows_of(str(biz["id"])), None
    for it in ITEMS:
        if it.get("live") == "giving":
            import payments_core
            live = {"giving": {"connected": bool(biz.get("stripe_account_id")),
                               "ready": bool(biz.get("stripe_account_id")) and bool(payments_core.can_charge(biz))}}
        if _state(it, rows.get(it["key"]), [], live or {}) not in FINISHED:
            return False
    return True


def _moved_in_at(biz_id: str) -> Optional[str]:
    """When this church first saw its move finished, kept the first time
    the question is asked of a finished move. It starts on the church's
    first look, not on our last check, so a pastor who was away a week
    still gets the moment. None when it couldn't be read or kept; never
    raises (the menu's answer does not hang on it)."""
    where = f"/church_move_items?business_id=eq.{_q(biz_id)}&item=eq.{_q(MOVED_IN)}&select=checked_at&limit=1"
    try:
        rows = sb_clients.sb_get_as_service(where)
        if not isinstance(rows, list):
            return None
        if rows and rows[0].get("checked_at"):
            return rows[0]["checked_at"]
        when = _now()
        if rows:
            sb_clients.sb_patch_as_service(where.split("&select=")[0], {"checked_at": when, "updated_at": when})
            return when
        made = sb_clients.sb_post_as_service("/church_move_items", {
            "business_id": biz_id, "item": MOVED_IN, "state": "checked", "checked_at": when, "updated_at": when})
        if isinstance(made, list) and made:
            return when
        # Two logins asked at once and the other kept it: read theirs.
        rows = sb_clients.sb_get_as_service(where)
        return rows[0].get("checked_at") if isinstance(rows, list) and rows else None
    except Exception:  # noqa: BLE001
        logger.info("move-in: the moved-in day couldn't be kept for %s", biz_id, exc_info=True)
        return None


def _shown_file(f: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": f.get("id"), "name": f.get("name"), "size_bytes": f.get("size_bytes"),
            "picture": str(f.get("media_type") or "").startswith("image/"), "at": f.get("created_at")}


def _room(biz: Dict[str, Any], *, links: bool = False) -> Dict[str, Any]:
    biz_id = str(biz["id"])
    rows, files, live = _rows_of(biz_id), _files_of(biz_id), _live(biz)
    items, settled = [], 0
    for it in ITEMS:
        row, mine = rows.get(it["key"]), files.get(it["key"], [])
        state = _state(it, row, mine, live)
        settled += state in SETTLED
        shown = {"key": it["key"], "title": it["title"], "ask": it["ask"], "why": it.get("why"),
                 "urgent": bool(it.get("urgent")), "state": state, "state_words": STATE_WORDS[state],
                 "note": (row or {}).get("note") if state == "needs" else None,
                 "fields": it.get("fields") or [], "answers": (row or {}).get("answers") or {},
                 "door": it.get("door"), "live": live.get(it.get("live") or ""),
                 "handed_in_at": (row or {}).get("handed_in_at"), "checked_at": (row or {}).get("checked_at"),
                 "hand_in": None, "files": None}
        if it.get("live") != "giving":
            why_not = missing(it, shown["answers"], mine, live)
            shown["hand_in"] = {"ready": why_not is None and state not in ("handed_in", "checked"), "missing": why_not}
        if it.get("files"):
            shown["files"] = {"words": it["files"]["words"], "label": it["files"]["label"],
                              "kind": it["files"]["kind"], "max": it["files"]["max"],
                              "list": [_file_with_link(biz_id, f) if links else _shown_file(f) for f in mine]}
        items.append(shown)
    return {"church": {"id": biz_id, "name": biz.get("name") or "Your church"},
            "items": items, "progress": {"settled": settled, "total": len(ITEMS)}}


# ─── Answers ──────────────────────────────────────────────────────────

def clean_answers(item: Dict[str, Any], raw: Any) -> Dict[str, Any]:
    """The item's own fields, trimmed and typed; anything else is dropped.
    400 with the field's name for a number that isn't one or too many rows."""
    raw = raw if isinstance(raw, dict) else {}
    out: Dict[str, Any] = {}
    for f in item.get("fields") or []:
        v, kind = raw.get(f["key"]), f["type"]
        if kind == "text":
            s = _plain(v)[:TEXT_MAX]
            if s:
                out[f["key"]] = s
        elif kind == "long":
            s = _lines(v)[:LONG_MAX]
            if s:
                out[f["key"]] = s
        elif kind == "number":
            if v in (None, ""):
                continue
            try:
                n = int(str(v).strip().replace(",", ""))
            except ValueError:
                raise HTTPException(400, f"{f['label']}: type a number.")
            if not 0 <= n <= 1_000_000:
                raise HTTPException(400, f"{f['label']}: type a number.")
            out[f["key"]] = n
        elif kind == "rows":
            rows = []
            for r in (v if isinstance(v, list) else [])[:200]:
                if not isinstance(r, dict):
                    continue
                row = {c["key"]: _plain(r.get(c["key"]))[:CELL_MAX] for c in f["columns"]}
                row = {k: s for k, s in row.items() if s}
                if row:
                    rows.append(row)
            if len(rows) > f["max"]:
                raise HTTPException(400, f"{f['label']}: {f['max']} at most.")
            if rows:
                out[f["key"]] = rows
    return out


def _write(biz_id: str, key: str, had: Optional[Dict[str, Any]], patch: Dict[str, Any]) -> None:
    body = {**patch, "updated_at": _now()}
    where = f"/church_move_items?business_id=eq.{_q(biz_id)}&item=eq.{_q(key)}"
    if had is None:
        made = sb_clients.sb_post_as_service("/church_move_items", {"business_id": biz_id, "item": key, **body})
        if isinstance(made, list) and made:
            return
        # Two saves at once: the other one made the row. Fall through and patch it.
    saved = sb_clients.sb_patch_as_service(where, body)
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Try again.")


def _reopened(had: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A change to something handed in or checked takes it back: what we
    looked at is no longer what's there. A `needs` stays, with its note."""
    if (had or {}).get("state") in ("handed_in", "checked"):
        return {"state": "todo", "handed_in_at": None, "handed_in_by": None, "checked_at": None}
    return {}


# ─── Files ────────────────────────────────────────────────────────────

_SHEET_EXT = {"csv": "text/csv", "tsv": "text/tab-separated-values", "txt": "text/plain", "vcf": "text/vcard",
              "pdf": "application/pdf",
              "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
              "xls": "application/vnd.ms-excel", "ods": "application/vnd.oasis.opendocument.spreadsheet",
              "numbers": "application/zip"}
_ZIPPED, _TEXT = ("xlsx", "ods", "numbers"), ("csv", "tsv", "txt", "vcf")


def _looks_like_text(raw: bytes) -> bool:
    head = raw[:8192]
    if head[:2] in (b"\xff\xfe", b"\xfe\xff"):      # a UTF-16 export (Excel's "Unicode text")
        return True
    return b"\x00" not in head


def prepare_file(kind: str, name: str, raw: bytes) -> Tuple[bytes, str, str]:
    """(bytes, media type, extension) to keep, judged from the bytes and
    not from what the browser said. 400 in words for anything else."""
    if not raw:
        raise HTTPException(400, "That file is empty.")
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(413, "That file is too large. Choose one under 15 MB.")
    ext = (name.rsplit(".", 1)[-1] if "." in name else "").lower()
    if raw[:5] == b"%PDF-":
        return raw, "application/pdf", "pdf"
    if kind == "pictures":
        import upload_images
        got = upload_images.verified_image(raw, ("png", "jpeg", "webp"))
        if not got:
            raise HTTPException(400, "Choose a JPG, PNG or WebP picture, or a PDF of your logo.")
        return raw, got[0], got[1]
    if ext in _ZIPPED and raw[:4] == b"PK\x03\x04":
        return raw, _SHEET_EXT[ext], ext
    if ext == "xls" and raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return raw, _SHEET_EXT[ext], ext
    if ext in _TEXT and _looks_like_text(raw):
        return raw, _SHEET_EXT[ext], ext
    raise HTTPException(400, "Choose a spreadsheet (CSV or Excel) or a PDF.")


def _display_name(name: Any, ext: str) -> str:
    base = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", " ", str(name or "")).strip().rsplit("/", 1)[-1]
    base = _plain(base)[:NAME_MAX]
    return base or f"file.{ext}"


def file_key(biz_id: str, path: Any) -> bool:
    """True only for a path this module could have made for this church."""
    import storage_links
    biz = storage_links.canonical_business_id(biz_id)
    if not biz or not isinstance(path, str):
        return False
    head = f"{biz}/{FOLDER}/"
    return path.startswith(head) and bool(_PATH_NAME.fullmatch(path[len(head):]))


def _storage_url(path: str) -> str:
    return f"{(os.environ.get('SUPABASE_URL') or '').rstrip('/')}/storage/v1/object/{BUCKET}/{path}"


def _storage_put(path: str, data: bytes, media: str) -> Tuple[bool, int, str]:
    import httpx
    import storage_links
    try:
        r = httpx.post(_storage_url(path), headers={**storage_links.service_headers(), "Content-Type": media},
                       content=data, timeout=60)
        return r.is_success, r.status_code, r.text[:300]
    except Exception:  # noqa: BLE001
        logger.warning("move-in: upload failed", exc_info=True)
        return False, 0, ""


def _storage_drop(path: str) -> None:
    import httpx
    import storage_links
    try:
        httpx.request("DELETE", _storage_url(path), headers=storage_links.service_headers(), timeout=15)
    except Exception:  # noqa: BLE001
        logger.info("move-in: file delete skipped", exc_info=True)


def _signed(path: str, name: str) -> Optional[str]:
    import storage_links
    return storage_links.signed_url_sync(BUCKET, path, ttl=LINK_TTL, download_as=name)


def _file_with_link(biz_id: str, f: Dict[str, Any]) -> Dict[str, Any]:
    shown = _shown_file(f)
    path = f.get("path")
    shown["url"] = _signed(path, str(f.get("name") or "file")) if file_key(biz_id, path) else None
    return shown


# ─── Telling the platform owner ───────────────────────────────────────

def _answer_lines(item: Dict[str, Any], answers: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for f in item.get("fields") or []:
        v = (answers or {}).get(f["key"])
        if v in (None, "", []):
            continue
        if f["type"] == "rows":
            out.append(f"{f['label']}:")
            for r in v:
                out.append("  " + " · ".join(str(r[c["key"]]) for c in f["columns"] if r.get(c["key"])))
        else:
            out.append(f"{f['label']}: {v}")
    return out


async def _tell_owner(me: Dict[str, Any], item: Dict[str, Any], room: Dict[str, Any], when: str) -> bool:
    """One plain email the moment a church hands something in. Best
    effort: the room is the record, so a failed email never fails the
    hand-in."""
    to = (os.environ.get("PLATFORM_OWNER_EMAIL") or "").strip()
    if not to:
        return False
    try:
        from email_sender import send_via_resend
        name = str(me["biz"].get("name") or "A church")
        shown = next(i for i in room["items"] if i["key"] == item["key"])
        lines = [f"{name} handed in: {item['title']}."]
        lines += _answer_lines(item, shown["answers"])
        files = (shown.get("files") or {}).get("list") or []
        if files:
            lines.append(f"Files ({len(files)}): " + ", ".join(str(f["name"]) for f in files[:20]))
        on_file = (shown.get("live") or {}).get("on_file")
        if isinstance(on_file, int):
            lines.append(f"People on file: {on_file:,}.")
        if me.get("email"):
            lines.append(f"Handed in by {me['email']}.")
        p = room["progress"]
        lines.append(f"{p['settled']} of {p['total']} are in. Open it in Mission Control, under Customers, Move-ins.")
        await send_via_resend(
            to_email=to, to_name=None,
            from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
            from_name="Solutionist", subject=f"{name} handed in: {item['title']}"[:150],
            body="".join(f"<p>{html.escape(x)}</p>" for x in lines), reply_to=None,
            idempotency_key=f"move-in-{me['biz']['id']}-{item['key']}-{when}"[:200])
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("move-in: the owner's email didn't send for %s: %s", me["biz"].get("id"), e)
        return False


def _ticket_all_in(biz: Dict[str, Any]) -> None:
    """Everything is in: one line in Mission Control's Today. The church
    can read its own tickets, so nothing private goes in this one."""
    try:
        name = str(biz.get("name") or "A church")
        sb_clients.sb_post_as_service("/support_tickets", {
            "business_id": biz["id"], "category": "general",
            "subject": f"MOVE-IN: {name} has handed in everything"[:200],
            "message": "Every item in the Move-in room is handed in or checked. Look each one over and "
                       "mark it checked, or ask for a change.",
            "context": {"kind": "church_move_in"},
        })
    except Exception:  # noqa: BLE001
        logger.warning("move-in: the all-in ticket didn't save", exc_info=True)


# ─── The church's room ────────────────────────────────────────────────

@router.get("/status")
def move_in_status(business_id: str, user: AuthedUser = Depends(require_user)):
    """Whether this login's office shows the Move-in room, asked once so
    the menu offers it only where it opens. Quietly false for a closed
    switch, a business that isn't a church, a login that doesn't work the
    office, or tables not made yet. `finished` says the move is done, so
    the menu can let the room go; its address still opens it. A finished
    move also answers `finished_at`: the day this church first saw it
    finished, which is how long Home says "moved in" (None if unknown)."""
    off = {"enabled": False, "write": False}
    try:
        me = _access(business_id, user)
    except HTTPException as e:
        if e.status_code in (403, 404, 503):
            return off
        raise
    if not _ready(str(me["biz"]["id"])):
        return off
    try:
        finished = _finished(me["biz"])
    except Exception:  # noqa: BLE001  (not knowing is "not finished": the room stays on the menu)
        finished = False
    out: Dict[str, Any] = {"enabled": True, "write": me["role"] in WRITERS, "finished": finished}
    if finished:
        out["finished_at"] = _moved_in_at(str(me["biz"]["id"]))
    return out


@router.get("")
def move_in_room(business_id: str, user: AuthedUser = Depends(require_user)):
    me = _access(business_id, user)
    return {**_room(me["biz"]), "me": {"write": me["role"] in WRITERS}}


@router.put("/{key}")
def move_in_save(key: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Save an item's answers (not yet handed in)."""
    me = _access((body or {}).get("business_id"), user)
    _writer(me)
    item = _item(key)
    if not item.get("fields"):
        raise HTTPException(400, "There's nothing to type for this one.")
    biz_id = str(me["biz"]["id"])
    had = _rows_of(biz_id).get(key)
    _write(biz_id, key, had, {"answers": clean_answers(item, (body or {}).get("answers")),
                              "updated_by": me["uid"], **_reopened(had)})
    return {**_room(me["biz"]), "me": {"write": True}}


@router.post("/{key}/files")
def move_in_add_file(key: str, business_id: str = Form(...), file: UploadFile = File(...),
                     user: AuthedUser = Depends(require_user)):
    me = _access(business_id, user)
    _writer(me)
    item = _item(key)
    slot = item.get("files")
    if not slot:
        raise HTTPException(400, "This one doesn't take files.")
    biz_id = str(me["biz"]["id"])
    have = _need(f"/church_move_files?business_id=eq.{_q(biz_id)}&item=eq.{_q(key)}&select=id&limit=100")
    if len(have) >= slot["max"]:
        raise HTTPException(400, f"That's the most this one holds ({slot['max']}). Remove one to add another.")
    raw = file.file.read(MAX_FILE_BYTES + 1)
    data, media, ext = prepare_file(slot["kind"], file.filename or "", raw)
    import storage_links
    biz = storage_links.canonical_business_id(biz_id)
    if not biz or not storage_links.has_service_key():
        raise HTTPException(503, storage_links.UPLOAD_NOT_CONFIGURED)
    path = f"{biz}/{FOLDER}/{uuid.uuid4().hex}.{ext}"
    ok, status, text = _storage_put(path, data, media)
    if not ok:
        logger.warning("move-in: upload refused %s %s", status, text[:200])
        raise HTTPException(503, storage_links.upload_refusal(status, text) if status else storage_links.UPLOAD_UNREACHABLE)
    made = sb_clients.sb_post_as_service("/church_move_files", {
        "business_id": biz_id, "item": key, "path": path, "name": _display_name(file.filename, ext),
        "media_type": media, "size_bytes": len(data), "uploaded_by": me["uid"]})
    if not isinstance(made, list) or not made:
        _storage_drop(path)
        raise HTTPException(503, "That file didn't save. Try again.")
    had = _rows_of(biz_id).get(key)
    reopened = _reopened(had)
    if had is None or reopened:
        _write(biz_id, key, had, {"updated_by": me["uid"], **reopened})
    return {**_room(me["biz"]), "me": {"write": True}}


@router.delete("/files/{file_id}")
def move_in_remove_file(file_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    me = _access(business_id, user)
    _writer(me)
    biz_id, fid = str(me["biz"]["id"]), _uuid(file_id, "file")
    rows = _need(f"/church_move_files?business_id=eq.{_q(biz_id)}&id=eq.{_q(fid)}&select=id,item,path&limit=1")
    if not rows:
        raise HTTPException(404, "That file isn't here any more.")
    if not sb_clients.sb_delete_as_service(f"/church_move_files?business_id=eq.{_q(biz_id)}&id=eq.{_q(fid)}"):
        raise HTTPException(503, "That file couldn't be removed. Try again.")
    if file_key(biz_id, rows[0].get("path")):
        _storage_drop(rows[0]["path"])
    key = str(rows[0].get("item"))
    had = _rows_of(biz_id).get(key)
    reopened = _reopened(had)
    if had is not None and reopened:
        _write(biz_id, key, had, {"updated_by": me["uid"], **reopened})
    return {**_room(me["biz"]), "me": {"write": True}}


@router.post("/{key}/hand-in")
async def move_in_hand_in(key: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """The church says this one is ready. Emails the platform owner."""
    import asyncio
    me = await asyncio.to_thread(_access, (body or {}).get("business_id"), user)
    _writer(me)
    item = _item(key)
    if item.get("live") == "giving":
        raise HTTPException(400, "Giving is done when Stripe approves your church. There's nothing to hand in.")
    biz_id = str(me["biz"]["id"])

    def hand_in() -> Tuple[Dict[str, Any], str, bool]:
        before = _room(me["biz"])
        shown = next(i for i in before["items"] if i["key"] == key)
        if shown["state"] in ("handed_in", "checked"):
            return before, "", False
        if shown["hand_in"]["missing"]:
            raise HTTPException(400, shown["hand_in"]["missing"])
        when = _now()
        _write(biz_id, key, _rows_of(biz_id).get(key),
               {"state": "handed_in", "handed_in_at": when, "handed_in_by": me["uid"], "note": None,
                "checked_at": None, "updated_by": me["uid"]})
        after = _room(me["biz"])
        was_all = before["progress"]["settled"] == before["progress"]["total"]
        now_all = after["progress"]["settled"] == after["progress"]["total"]
        if now_all and not was_all:
            _ticket_all_in(me["biz"])
        return after, when, True

    room, when, changed = await asyncio.to_thread(hand_in)
    if changed:
        await _tell_owner(me, item, room, when)
    return {**room, "me": {"write": True}}


# ─── The platform owner's side ────────────────────────────────────────

@platform_router.get("")
def platform_move_ins(owner: AuthedUser = Depends(require_owner)):
    """Every church with something in its Move-in room, newest first."""
    rows = _need("/church_move_items?select=business_id,item,state,updated_at&order=updated_at.desc&limit=1000")
    by: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        if r.get("item") not in ITEM:
            continue
        b = by.setdefault(str(r["business_id"]), {"business_id": str(r["business_id"]), "handed_in": 0,
                                                  "checked": 0, "needs": 0, "last_at": r.get("updated_at")})
        if r.get("state") in ("handed_in", "checked", "needs"):
            b[r["state"]] += 1
    if by:
        ids = ",".join(_q(k) for k in by)
        for biz in _need(f"/businesses?id=in.({ids})&select=id,name&limit=1000"):
            by[str(biz["id"])]["name"] = biz.get("name")
    return {"churches": [{"name": "A church", **b, "total": len(ITEMS)} for b in by.values()]}


@platform_router.get("/{business_id}")
def platform_move_in_room(business_id: str, owner: AuthedUser = Depends(require_owner)):
    """One church's room, with a time-limited link to each file."""
    biz = _business(_uuid(business_id, "church"))
    return _room(biz, links=True)


@platform_router.post("/{business_id}/{key}")
def platform_move_in_mark(business_id: str, key: str, body: Dict[str, Any],
                          owner: AuthedUser = Depends(require_owner)):
    """Mark an item checked, or ask the church for a change (with a note
    the church reads in its room)."""
    biz = _business(_uuid(business_id, "church"))
    item = _item(key)
    if item.get("live") == "giving":
        raise HTTPException(400, "Giving follows Stripe. There's nothing to mark.")
    state = str((body or {}).get("state") or "")
    if state not in ("checked", "needs"):
        raise HTTPException(400, "Mark it checked, or ask for a change.")
    note = _lines((body or {}).get("note"))[:NOTE_MAX]
    if state == "needs" and not note:
        raise HTTPException(400, "Say what needs to change. The church reads this.")
    biz_id = str(biz["id"])
    had = _rows_of(biz_id).get(key)
    if had is None or had.get("state") not in ("handed_in", "checked", "needs"):
        raise HTTPException(409, "The church hasn't handed this one in yet.")
    _write(biz_id, key, had, {"state": state, "note": note if state == "needs" else None,
                              "checked_at": _now() if state == "checked" else None})
    return _room(biz, links=True)
