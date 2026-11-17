"""
church_threads.py — the member app's notes read like texts.

Kevin, 2026-11-17: "the goal is not be a text message itself but using the
app to push through as like a text", members "can respond and it not be an
issue", and "group notifications for groups people are in specifically".
"make this happen", on for his own churches first.

Each member gets an inbox in the member app that looks like a phone's
Messages (member_portal_threads.py draws it):

  * One conversation with their church. Every note the church already
    pushes (THREAD_KINDS) lands there as a bubble from the church, and the
    member can write back. What they write goes to the church office (the
    office's screen is the frontend's, on the API below).
  * One conversation per group they're in, holding that group's notes (a
    leader's Board post, a prayer-wall request). Only that group's members
    get them, and there's no reply box: the group's chat is its own place.

Group chat messages ("messages") and youth posts ("youth") are NOT recorded:
they have their own places.

RECORDING (member_push._send calls record()): after the church's per-kind
switch and the ref_id claim, before the device lookup. A url under
/my/groups/<uuid> is that group's thread ('group:<uuid>'); everything else
is the church's ('church'). A "groups" note with no group url is not
recorded. With contact_ids, one row per person (all of them, not only those
with a phone), in a bulk insert whose rows all carry the SAME keys (mixed
keys lose the whole chunk in PostgREST); without, one row for everyone at
the church (contact_id null). Never raises: a note that can't be recorded
still goes out, as it always did.

THE LOCK SCREEN (lock_screen(), same conditions, only once the row is
saved): a church note reads like a text from the church — its name on top,
then what the caller wrote — and opens /my/inbox/church; a group note keeps
the group's name and opens /my/inbox/group/<gid>. The words are the ones the
callers already compose for a lock screen, never a member's message.

THE SWITCH. CHURCH_THREADS = off | owner | on, owner when unset (the
member_asks pattern): owner is the platform owner's churches only. Off, or
closed for a church, records nothing, the member pages go back to /my, and
the office's status says open:false. A sample church records and sends
nothing. Everything goes quiet while the tables are missing
(supabase/APPLY-2026-11-17-church-threads.sql).

OFFICE API (a fixed contract: the frontend is built against it).
require_user, then business_access as text_room uses it: read at viewer,
write at member; another church is a 403.

  GET  /church-threads/{biz}/status            {"open": bool}
  GET  /church-threads/{biz}                   {"threads": [{contact_id, name, last: {direction, body,
                                               created_at}, unread}]}, newest first; only people who
                                               wrote at least once or were answered
  GET  /church-threads/{biz}/{contact_id}      {"contact": {id, name}, "notes": [note]}, that person's
                                               own rows, oldest first, the last 200; marks their
                                               messages read
  POST /church-threads/{biz}/{contact_id}/reply {"body"} -> {"ok": true, "note": note}; pushed to the
                                               member's phones like a text reply

  note = {id, direction, kind, title, body, url, author_name, created_at, held}

A held message (the screen said harm) is shown only to the people who may
review it: the church's safety officers (messaging_router's team logins),
or the owner while the church has named none. Nothing here ever writes an
SMS table: sms_messages inbound rows count as text consent.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("church_threads")
router = APIRouter(tags=["church-threads"])

NOTES = "church_thread_notes"
READS = "church_thread_reads"
THREAD_KINDS = ("announcements", "live", "sermons", "events", "classes", "prayer", "kids", "news", "serving",
                "groups")
CHURCH = "church"
BODY_MAX = 1000                   # a member's message, and the office's reply
DAY_MAX = 20                      # a member's messages a day
GAP_SECONDS = 5                   # never two from one member within this
CHURCH_WIDE_DAYS = 60             # how far back the church-wide notes reach
PERSON_NOTES = 200                # the office's view of one person
CHUNK = 500                       # rows per bulk insert
OFFICE_NAV = "operate:sms"   # the office phone alert opens Text, where the App messages button sits (FE #1611)
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
GROUP_URL_RE = re.compile(
    r"^/my/groups/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?:[/?#]|$)")
NOTE_FIELDS = "id,contact_id,thread,direction,kind,title,body,url,author_name,created_at,read_at,held"


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _plain(v: Any, top: int) -> str:
    return " ".join(str(v or "").split())[:top]


def words(v: Any) -> str:
    """A person's own words: line breaks kept (at most one blank line),
    spaces tidied. Not cut: the caller says when it's too long."""
    s = str(v or "").replace("\r\n", "\n").replace("\r", "\n")
    s = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in s.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", s).strip()


# ─── The switch ───────────────────────────────────────────────────────


def mode() -> str:
    m = (os.environ.get("CHURCH_THREADS") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def switch_open(business_id: Any) -> bool:
    """Whether threads are on for this church: on for every church, or with
    `owner` only a church whose owner is the platform owner (member_asks'
    rule, kept ten minutes per replica). A failed read is closed."""
    m = mode()
    if m == "off" or not business_id:
        return False
    try:
        import member_asks
        return member_asks._switch_open(m, business_id)
    except Exception:
        logger.warning("church threads: the switch couldn't be read", exc_info=True)
        return False


def open_for(biz: Optional[Dict[str, Any]]) -> bool:
    """Open for this church row: the switch, and never a sample church."""
    if not biz or not switch_open(biz.get("id")):
        return False
    try:
        import sample_church
        return not sample_church.skip(biz)
    except Exception:
        return False


_READY: Dict[str, Any] = {"at": 0.0, "ok": None}
READY_SECONDS, NOT_READY_SECONDS = 600, 60


def tables_ready(fresh: bool = False) -> bool:
    """Whether the tables answer (the migration is applied). Kept ten
    minutes once yes, a minute while no."""
    hit, at = _READY.get("ok"), float(_READY.get("at") or 0)
    if not fresh and hit is not None and time.monotonic() - at < (READY_SECONDS if hit else NOT_READY_SECONDS):
        return bool(hit)
    try:
        a = sb_clients.sb_get_as_service(f"/{NOTES}?select=id&limit=1")
        b = sb_clients.sb_get_as_service(f"/{READS}?select=thread&limit=1")
        ok = isinstance(a, list) and isinstance(b, list)
    except Exception:
        ok = False
    _READY.update(at=time.monotonic(), ok=ok)
    return ok


# ─── Threads and the lock screen ──────────────────────────────────────


def thread_for(url: Any) -> str:
    """'group:<uuid>' for a url under /my/groups/<uuid>, else 'church'."""
    m = GROUP_URL_RE.match(str(url or ""))
    return f"group:{m.group(1).lower()}" if m else CHURCH


def group_of(thread: str) -> str:
    return thread[len("group:"):] if str(thread or "").startswith("group:") else ""


def inbox_url(thread: str) -> str:
    gid = group_of(thread)
    return f"/my/inbox/group/{gid}" if gid else "/my/inbox/church"


def is_inbox_url(url: Any) -> bool:
    u = str(url or "")
    return u == "/my/inbox" or u.startswith("/my/inbox/") or u.startswith("/my/inbox?")


def church_name(business: Dict[str, Any]) -> str:
    name = _plain(business.get("name"), 120)
    if name:
        return name
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(business.get('id') or '')}&select=name&limit=1")
    if isinstance(rows, list) and rows and rows[0].get("name"):
        return _plain(rows[0]["name"], 120)
    return "Your church"


def lock_screen(business: Dict[str, Any], thread: str, title: str, body: str) -> Dict[str, str]:
    """The payload's title, body and url for a recorded note, so it reads
    like a text. A church note: the church's name on top, then the note's
    own title and line ("Tomorrow: Picnic — You said you're coming."), the
    title left out when it is the church's name already. A group note keeps
    its title (the group's name) and body, and opens straight into the
    group's chat where its notes sit (member_portal_threads), or its notes
    when the group has no chat. Never raises."""
    import member_push
    try:
        gid = group_of(thread)
        if gid:
            return {"url": group_url(business, gid)}
        name = church_name(business)
        title, body = _plain(title, 200), _plain(body, 400)
        said = body if (not title or title.casefold() == name.casefold()) else (
            f"{title} — {body}" if body else title)
        return {"title": name[:member_push.TITLE_MAX], "body": said[:member_push.BODY_MAX],
                "url": inbox_url(thread)}
    except Exception:
        logger.warning("church threads: the lock screen fell back", exc_info=True)
        return {}


def group_url(business: Dict[str, Any], group_id: str) -> str:
    """Where a group's note opens: its chat while the church's chats are on
    and the group's chat is (the note sits in it); else the group's notes
    (/my/inbox/group/<gid>, which also sends a member on to the chat)."""
    gid = str(group_id).lower()
    try:
        import member_portal_messaging as mpm
        if mpm.turned_on(business):
            rows = _rows(f"/groups?business_id=eq.{_q(business.get('id') or '')}&id=eq.{_q(gid)}&select=chat_on&limit=1")
            if rows and rows[0].get("chat_on") is not False:
                return f"/my/groups/{gid}/chat"
    except Exception:
        logger.warning("church threads: a group's chat couldn't be checked", exc_info=True)
    return inbox_url(f"group:{gid}")


# ─── Recording (member_push._send) ────────────────────────────────────


def record(business: Dict[str, Any], kind: str, *, title: str, body: str, url: str,
           contact_ids: Optional[List[str]], ref_id: Optional[str] = None) -> Optional[str]:
    """Record a church note in its thread. The thread's key when at least
    one row was saved, else None (closed, a kind that isn't kept, nobody to
    tell, the tables missing, a failed write). Never raises."""
    try:
        if kind not in THREAD_KINDS:
            return None
        biz_id = str(business.get("id") or "")
        if not UUID_RE.match(biz_id) or not switch_open(biz_id):
            return None
        thread = thread_for(url)
        if kind == "groups" and thread == CHURCH:
            return None
        if contact_ids is not None:
            people = sorted({str(c) for c in contact_ids if UUID_RE.match(str(c or ""))})
            if not people:
                return None
        else:
            people = [None]
        if not tables_ready():
            return None
        base = {"business_id": biz_id, "thread": thread, "direction": "church", "kind": kind,
                "title": _plain(title, 200) or None, "body": _plain(body, 400) or None,
                "url": str(url or "")[:500] or None, "ref_id": str(ref_id)[:200] if ref_id else None}
        # Every row carries the SAME keys: mixed keys lose the chunk.
        rows = [{**base, "contact_id": c} for c in people]
        saved = 0
        for i in range(0, len(rows), CHUNK):
            got = sb_clients.sb_post_as_service(f"/{NOTES}?select=id", rows[i:i + CHUNK],
                                                prefer="return=representation")
            if isinstance(got, list):
                saved += len(got)
        return thread if saved else None
    except Exception:
        logger.warning("church threads: a note wasn't recorded", exc_info=True)
        return None


# ─── Reading, for the member app ──────────────────────────────────────


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    got = sb_clients.sb_get_as_service(path)
    return got if isinstance(got, list) else None


def church_wide_since(now: Optional[datetime] = None) -> str:
    return ((now or _now()) - timedelta(days=CHURCH_WIDE_DAYS)).isoformat()


def church_notes(business_id: str, contact_id: str, limit: int = PERSON_NOTES) -> Optional[List[Dict[str, Any]]]:
    """The member's church conversation, oldest first: their own rows (the
    notes sent to them, their messages, the office's replies) and the
    church-wide notes from the last CHURCH_WIDE_DAYS. None when a read
    failed."""
    b, c = _q(business_id), _q(contact_id)
    own = _rows(f"/{NOTES}?business_id=eq.{b}&contact_id=eq.{c}&thread=eq.{CHURCH}"
                f"&select={NOTE_FIELDS}&order=created_at.desc&limit={limit}")
    wide = _rows(f"/{NOTES}?business_id=eq.{b}&contact_id=is.null&thread=eq.{CHURCH}"
                 f"&created_at=gte.{_q(church_wide_since())}&select={NOTE_FIELDS}&order=created_at.desc&limit={limit}")
    if own is None or wide is None:
        return None
    both = sorted(own + wide, key=lambda r: str(r.get("created_at") or ""))
    return both[-limit:]


def group_notes(business_id: str, contact_id: str, group_id: str,
                limit: int = PERSON_NOTES) -> Optional[List[Dict[str, Any]]]:
    rows = _rows(f"/{NOTES}?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}"
                 f"&thread=eq.{_q('group:' + str(group_id).lower())}"
                 f"&select={NOTE_FIELDS}&order=created_at.desc&limit={limit}")
    return None if rows is None else sorted(rows, key=lambda r: str(r.get("created_at") or ""))


def reads(business_id: str, contact_id: str) -> Optional[Dict[str, str]]:
    rows = _rows(f"/{READS}?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}&select=thread,read_at")
    return None if rows is None else {str(r["thread"]): str(r.get("read_at") or "") for r in rows}


def mark_read(business_id: str, contact_id: str, thread: str) -> None:
    """The member opened this conversation. Never raises."""
    try:
        sb_clients.sb_post_as_service(
            f"/{READS}?on_conflict=business_id,contact_id,thread",
            {"business_id": str(business_id), "contact_id": str(contact_id), "thread": thread,
             "read_at": _now().isoformat()},
            prefer="resolution=merge-duplicates,return=minimal")
    except Exception:
        logger.warning("church threads: read mark failed", exc_info=True)


def is_new(row: Dict[str, Any], read_at: str) -> bool:
    """Unread for the member: from the church (a note or a reply), after
    they last opened the conversation."""
    return row.get("direction") == "church" and str(row.get("created_at") or "") > (read_at or "")


def summary(business_id: str, contact_id: str, group_ids: Iterable[str]) -> Optional[Dict[str, Dict[str, Any]]]:
    """{thread: {"last": row, "unread": n}} for the church conversation and
    each of the member's groups that has notes. None when a read failed."""
    b, c = _q(business_id), _q(contact_id)
    own = _rows(f"/{NOTES}?business_id=eq.{b}&contact_id=eq.{c}&select={NOTE_FIELDS}"
                f"&order=created_at.desc&limit=500")
    wide = _rows(f"/{NOTES}?business_id=eq.{b}&contact_id=is.null&thread=eq.{CHURCH}"
                 f"&created_at=gte.{_q(church_wide_since())}&select={NOTE_FIELDS}&order=created_at.desc&limit=200")
    seen = reads(business_id, contact_id)
    if own is None or wide is None or seen is None:
        return None
    mine = {f"group:{str(g).lower()}" for g in group_ids}
    out: Dict[str, Dict[str, Any]] = {}
    for r in sorted(own + wide, key=lambda x: str(x.get("created_at") or "")):
        t = str(r.get("thread") or CHURCH)
        if t != CHURCH and t not in mine:
            continue
        hit = out.setdefault(t, {"last": None, "unread": 0})
        hit["last"] = r
        if is_new(r, seen.get(t, "")):
            hit["unread"] += 1
    return out


# ─── Who's told ───────────────────────────────────────────────────────


def _later(fn, *args) -> None:
    def run():
        try:
            fn(*args)
        except Exception:
            logger.warning("church threads: an alert failed", exc_info=True)
    threading.Thread(target=run, daemon=True).start()


def reviewers(business_id: str) -> Optional[Set[str]]:
    """The logins who may read a held message: the church's safety officers
    (team logins), or the owner while it has named none. None when it can't
    be read (nobody sees it then)."""
    try:
        import messaging_router
        officers = set(messaging_router.officers(str(business_id)))
    except Exception:
        return None
    if officers:
        return officers
    rows = _rows(f"/businesses?id=eq.{_q(business_id)}&select=owner_id&limit=1")
    if rows is None:
        return None
    return {str(rows[0]["owner_id"])} if rows and rows[0].get("owner_id") else set()


def _staff_push(business_id: str, users: Iterable[str], title: str, body: str, tag: str) -> int:
    """The staff path (push_notifications: the team's own devices, never
    the member table)."""
    import push_notifications
    n = 0
    for uid in sorted({str(u) for u in users if u}):
        try:
            n += push_notifications.send_to_user(uid, title=title, body=body, nav=OFFICE_NAV, tag=tag,
                                                 business_id=str(business_id))
        except Exception:
            logger.warning("church threads: a staff alert failed", exc_info=True)
    return n


def tell_office(business_id: str, contact_id: str, first: str) -> None:
    """A member wrote: the people who handle the office (member_asks'
    recipients for the office). Their first name, never their words."""
    def run():
        import member_asks
        who = member_asks.recipients(str(business_id), "office")
        _staff_push(business_id, who, "New message in the app", f"{first or 'Someone'} wrote to the church.",
                    f"church-thread-{contact_id}")
    _later(run)


def tell_reviewers(business_id: str, note_id: str) -> None:
    """A message was held: the people who may review it. No name, no words."""
    def run():
        who = reviewers(str(business_id)) or set()
        _staff_push(business_id, who, "A message is waiting for review",
                    "A message to the church was held by the check. Open it to review.",
                    f"church-thread-held-{note_id}")
    _later(run)


# ─── The office API ───────────────────────────────────────────────────


def _uuid(value: Any, what: str = "church") -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} isn't valid.")


def _access(business_id: Any, user: AuthedUser, min_role: str) -> str:
    """text_room's resolution (business_access): another church is a 403."""
    import business_access
    biz_id = _uuid(business_id)
    try:
        business_access.assert_access(biz_id, user, min_role)
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(403, "Not allowed.")
        raise
    return biz_id


def _business(biz_id: str) -> Dict[str, Any]:
    rows = _rows(f"/businesses?id=eq.{_q(biz_id)}&select=id,name,type,settings,owner_id,is_sample&limit=1")
    if rows is None:
        raise HTTPException(503, "That couldn't load just now. Please try again.")
    if not rows:
        raise HTTPException(403, "Not allowed.")
    return rows[0]


def _contact(biz_id: str, contact_id: str) -> Dict[str, Any]:
    rows = _rows(f"/contacts?business_id=eq.{_q(biz_id)}&id=eq.{_q(contact_id)}&select=id,name&limit=1")
    if rows is None:
        raise HTTPException(503, "That couldn't load just now. Please try again.")
    if not rows:
        raise HTTPException(404, "That person isn't in this church's records.")
    return rows[0]


def _may_review(biz_id: str, user: AuthedUser) -> bool:
    who = reviewers(biz_id)
    return bool(who) and str(user.id) in who


def note_out(r: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": r.get("id"), "direction": r.get("direction"), "kind": r.get("kind"), "title": r.get("title"),
            "body": r.get("body"), "url": r.get("url"), "author_name": r.get("author_name"),
            "created_at": r.get("created_at"), "held": bool(r.get("held"))}


def login_first_name(biz: Dict[str, Any], user: AuthedUser) -> str:
    """The office login's first name, for a reply's bubble."""
    uid = str(user.id)
    name = ""
    if uid == str(biz.get("owner_id") or ""):
        name = _plain(((biz.get("settings") or {}) if isinstance(biz.get("settings"), dict) else {})
                      .get("practitioner_name"), 120)
    if not name:
        seat = _rows(f"/business_users?business_id=eq.{_q(biz['id'])}&user_id=eq.{_q(uid)}&status=eq.active"
                     "&select=name,contact_id&limit=1") or []
        if seat:
            name = _plain(seat[0].get("name"), 120)
            if not name and seat[0].get("contact_id"):
                c = _rows(f"/contacts?business_id=eq.{_q(biz['id'])}&id=eq.{_q(seat[0]['contact_id'])}"
                          "&select=name&limit=1") or []
                name = _plain((c[0] if c else {}).get("name"), 120)
    first = name.split(" ")[0] if name else ""
    return first or "The office"


@router.get("/church-threads/{business_id}/status")
def office_status(business_id: str, user: AuthedUser = Depends(require_user)):
    biz_id = _access(business_id, user, "viewer")
    biz = _business(biz_id)
    return {"open": bool(open_for(biz) and tables_ready(fresh=True))}


@router.get("/church-threads/{business_id}")
def office_threads(business_id: str, user: AuthedUser = Depends(require_user)):
    biz_id = _access(business_id, user, "viewer")
    biz = _business(biz_id)
    if not open_for(biz) or not tables_ready():
        return {"open": False, "threads": []}
    rows = _rows(f"/{NOTES}?business_id=eq.{_q(biz_id)}&contact_id=not.is.null&thread=eq.{CHURCH}"
                 f"&or=(direction.eq.member,kind.eq.reply)&select={NOTE_FIELDS}&order=created_at.desc&limit=2000")
    if rows is None:
        raise HTTPException(503, "Messages couldn't load just now. Please try again.")
    review = any(r.get("held") for r in rows) and _may_review(biz_id, user)
    by: Dict[str, Dict[str, Any]] = {}
    for r in rows:                                   # newest first
        cid = str(r.get("contact_id") or "")
        if not cid or (r.get("held") and not review):
            continue
        hit = by.setdefault(cid, {"contact_id": cid, "last": None, "unread": 0})
        if hit["last"] is None:
            hit["last"] = {"direction": r.get("direction"), "body": r.get("body"), "created_at": r.get("created_at")}
        if r.get("direction") == "member" and not r.get("read_at") and not r.get("held"):
            hit["unread"] += 1
    names: Dict[str, str] = {}
    ids = sorted(by)
    for i in range(0, len(ids), 150):
        got = _rows(f"/contacts?business_id=eq.{_q(biz_id)}&id=in.({','.join(_q(x) for x in ids[i:i + 150])})"
                    "&select=id,name")
        if got is None:
            raise HTTPException(503, "Messages couldn't load just now. Please try again.")
        names.update({str(c["id"]): _plain(c.get("name"), 120) for c in got})
    out = [{"contact_id": t["contact_id"], "name": names.get(t["contact_id"]) or "Someone", "last": t["last"],
            "unread": t["unread"]} for t in by.values()]
    out.sort(key=lambda t: str(t["last"]["created_at"] or ""), reverse=True)
    return {"threads": out}


@router.get("/church-threads/{business_id}/{contact_id}")
def office_person(business_id: str, contact_id: str, user: AuthedUser = Depends(require_user)):
    biz_id = _access(business_id, user, "viewer")
    cid = _uuid(contact_id, "person")
    biz = _business(biz_id)
    if not open_for(biz) or not tables_ready():
        return {"open": False, "contact": {"id": cid, "name": ""}, "notes": []}
    person = _contact(biz_id, cid)
    # Their church conversation: what was sent to them, what they wrote,
    # the office's replies. Not the church-wide notes, not their groups'.
    rows = _rows(f"/{NOTES}?business_id=eq.{_q(biz_id)}&contact_id=eq.{_q(cid)}&thread=eq.{CHURCH}"
                 f"&select={NOTE_FIELDS}&order=created_at.desc&limit={PERSON_NOTES}")
    if rows is None:
        raise HTTPException(503, "Messages couldn't load just now. Please try again.")
    if any(r.get("held") for r in rows) and not _may_review(biz_id, user):
        rows = [r for r in rows if not r.get("held")]
    if any(r.get("direction") == "member" and not r.get("read_at") and not r.get("held") for r in rows):
        sb_clients.sb_patch_as_service(
            f"/{NOTES}?business_id=eq.{_q(biz_id)}&contact_id=eq.{_q(cid)}&thread=eq.{CHURCH}&direction=eq.member"
            f"&read_at=is.null&held=eq.false", {"read_at": _now().isoformat()})
    rows.sort(key=lambda r: str(r.get("created_at") or ""))
    return {"contact": {"id": str(person["id"]), "name": _plain(person.get("name"), 120) or "Someone"},
            "notes": [note_out(r) for r in rows]}


class ReplyIn(BaseModel):
    body: str = ""


def push_reply(biz: Dict[str, Any], contact_id: str, text: str) -> int:
    """The office's reply on the member's phones, like a text's: the
    church's name, the reply. Unless the member turned "New messages" off;
    the church's own per-kind switch isn't needed (it answers them). Never
    raises; phones reached."""
    import member_push
    import push_notifications as pn
    try:
        if not member_push.ready():
            return 0
        off = member_push.turned_off(str(biz["id"]), contact_id)
        if off is None or "messages" in off:
            return 0
        subs = _rows(f"/{member_push._TABLE}?business_id=eq.{_q(biz['id'])}&contact_id=eq.{_q(contact_id)}"
                     "&select=id,contact_id,endpoint,subscription&limit=20") or []
        payload = {"title": church_name(biz)[:member_push.TITLE_MAX], "body": _plain(text, member_push.BODY_MAX),
                   "url": inbox_url(CHURCH), "tag": "church-thread"}
        return sum(1 for s in subs if pn._send_one(s, payload, table=member_push._TABLE))
    except Exception:
        logger.warning("church threads: the reply's push failed", exc_info=True)
        return 0


@router.post("/church-threads/{business_id}/{contact_id}/reply")
def office_reply(business_id: str, contact_id: str, body: ReplyIn, user: AuthedUser = Depends(require_user)):
    biz_id = _access(business_id, user, "member")
    cid = _uuid(contact_id, "person")
    text = words(body.body)
    if not text:
        raise HTTPException(400, "Write a reply first.")
    if len(text) > BODY_MAX:
        raise HTTPException(400, f"Keep a reply under {BODY_MAX} characters.")
    biz = _business(biz_id)
    if not open_for(biz) or not tables_ready():
        raise HTTPException(409, "Messages in the app aren't on for this church.")
    _contact(biz_id, cid)
    row = sb_clients.sb_post_as_service(f"/{NOTES}", {
        "business_id": biz_id, "contact_id": cid, "thread": CHURCH, "direction": "church", "kind": "reply",
        "title": None, "body": text, "url": None, "ref_id": None, "author_user_id": str(user.id),
        "author_name": login_first_name(biz, user), "held": False}, redact=True)
    if not isinstance(row, list) or not row:
        raise HTTPException(503, "That reply didn't save. Please try again.")
    _later(push_reply, biz, cid, text)
    return {"ok": True, "note": note_out(row[0])}
