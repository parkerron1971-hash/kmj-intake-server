"""church_handovers.py — From the office: the office sends a leader something
for their area (docs/CHURCH_ASSIGNMENTS.md, PR C1).

Kevin, 2026-11-12: "admins can not give work to elders and pastors but they
can give them things that is related to their area that they need for them
to have." So no office standing is over a pastor or an elder (church_over:
the shepherds), and the office hands them this instead: something they need,
for their area. A hand-over is never a task: never late, never escalated,
never judged, never on anyone's list of work. It's read, and "Got it" says so.

    POST /church/handovers                     send one: {business_id,
                                               contact_id, title (140),
                                               note? (1000), link? (https),
                                               for_date?, department_id?}
    GET  /church/handovers?business_id=        what I sent, newest first, each
                                               Seen or Not yet seen
    GET  /church/handovers/leaders?business_id=
                                               the leaders I may send to, with
                                               why ("Leads Youth · you help it
                                               as Rooms")
    POST /church/handovers/{id}/seen           Got it, from My week: the login
                                               whose own person it's for

Who may send, and to whom (an office seat; a Member seat sends nothing):

  the owner, an Admin ... any leader: everyone who leads or holds a role
                          (church_over._everyone: holders of an active role,
                          the leaders of active groups, each active
                          department's leader and overseer), and the owner's
                          own person
  a Manager ............. the leader or the overseer of an active department
                          (the map's) whose support_duty it holds
                          (church_duties: its lanes, its moves, else its
                          areas), or whose area is one of its areas (Who sees
                          what; with that off, every area, as its duties
                          read). The map closed: no one
  never ................. yourself

Where it's read: the leader's Lead tab in the member app (From the office,
with Got it: member_portal_lead), and My week for a login whose own person
it's for, the owner's included (church_my_week: `from_office`). Seen marks
it read for whoever sent it ("Seen" / "Not yet seen"); nothing else changes.

Told: the hourly sweep (sweep_tick, on the worker) sends each person one
email for what arrived since the last sweep, from the church, naming who sent
each. Each row is claimed before the send (told_at), and let go when the send
fails, so two replicas never both send. No email on file: told anyway (it's
on their page). One older than a week and never told is left untold.

Server-only table (supabase/APPLY-2026-11-12-church-handovers.sql), read and
written through the service role, always by business_id. A failed read is a
503 (a list that couldn't be read is never empty); a failed write is a 503,
never a 200. Switched with the assignments: CHURCH_ASSIGNMENTS
(church_over.mode); closed, the routes answer 404 and the sweep does nothing.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, HTTPException

import business_access
import church_over as co
import sb_clients
from auth_supabase import UserSession

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church", tags=["church"])

FIELDS = "id,business_id,contact_id,sent_by,title,note,link,for_date,department_id,created_at,seen_at,told_at"
TITLE_MAX, NOTE_MAX, LINK_MAX = 140, 1000, 500
SENT_DAYS = 90             # what I sent: the last three months
SEEN_DAYS = 14             # a leader's list keeps what they've seen for two weeks
TELL_DAYS = 7              # one never told within a week is left untold
READ_MAX = 500
SENDERS = ("owner", "admin", "manager")
OFFICE = "The church office"
UNREAD = "What the office sent couldn't be read just now. Try again."
UNSAVED = "That didn't send. Try again."
NOT_SENDER = "Only the church office sends these."
NOT_LEADER = "They aren't a leader you can send to here."
NOT_YOURS = "That isn't one of the things sent to you."


# ─── Small things ─────────────────────────────────────────────────────

def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _need(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, UNREAD)
    return rows


def _uuid(v: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(v or "")))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} isn't valid")


def _day(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def day_words(d: Optional[date]) -> str:
    """'Friday, Nov 20'."""
    return f"{d:%A}, {d:%b} {d.day}" if d else ""


def _lower_the(label: str) -> str:
    return "the " + label[4:] if label.startswith("The ") else label


# ─── What a hand-over says ────────────────────────────────────────────

def _title(v: Any) -> str:
    s = _plain(v)
    if not s:
        raise HTTPException(400, "Say what it is")
    if len(s) > TITLE_MAX:
        raise HTTPException(400, f"Keep what it is to {TITLE_MAX} letters")
    return s


def _note(v: Any) -> Optional[str]:
    s = str(v or "").replace("\r\n", "\n").strip()
    if len(s) > NOTE_MAX:
        raise HTTPException(400, f"Keep the note to {NOTE_MAX} letters")
    return s or None


def _link(v: Any) -> Optional[str]:
    """An https link, or none. Never another scheme (a javascript: or data:
    link would run where it's shown), never a sign-in inside it."""
    s = str(v or "").strip()
    if not s:
        return None
    u = urlparse(s)
    if (len(s) > LINK_MAX or any(c.isspace() for c in s) or u.scheme != "https" or not u.hostname
            or u.username or u.password):
        raise HTTPException(400, "A link starts with https://")
    # urlparse reads the scheme in any case; the table holds it lower case
    # (its check is case-sensitive: HTTPS:// would fail the insert for good).
    return "https" + s[len(u.scheme):] if s[:len(u.scheme)] != "https" else s


def _for_date(v: Any) -> Optional[str]:
    if v in (None, ""):
        return None
    d = _day(v)
    if not d:
        raise HTTPException(400, "A day is like 2026-11-20")
    return d.isoformat()


# ─── Who may send to whom ─────────────────────────────────────────────

def _areas(ch: co.Church, uid: str) -> Optional[set]:
    """A Manager's areas (Who sees what): None for every area (the whole
    church, or Who sees what not on, as its duties read); a read that fails
    is a 503."""
    import church_areas
    if church_areas.mode() != "on":
        return None
    view = church_areas.my_areas(ch.b, uid, ch.role(uid))
    if view is None:
        raise HTTPException(503, UNREAD)
    areas = view.get("areas")
    return None if areas is None else set(areas)


def _manager_reach(ch: co.Church, uid: str) -> List[Tuple[Dict[str, Any], str]]:
    """The active departments a Manager may send for, each with why: one
    whose support_duty it holds, else one in its areas."""
    import church_areas
    import church_duties as cd
    m = ch.map
    if not m:
        return []
    held = ch.held(uid)
    read, areas = False, None
    out: List[Tuple[Dict[str, Any], str]] = []
    for d in m.active():
        duty, area = str(d.get("support_duty") or ""), str(d.get("area") or "")
        if duty in cd.CATALOG and duty in held:
            out.append((d, f"you help it as {_lower_the(cd.CATALOG[duty]['label'])}"))
            continue
        if not area:
            continue
        if not read:
            read, areas = True, _areas(ch, uid)          # read once, and only when a department asks
        if areas is None or area in areas:
            label = (church_areas.AREAS.get(area) or {}).get("label")
            out.append((d, f"it's in your {label} area" if label else "it's in your areas"))
    return out


def _sender(ch: co.Church, uid: str) -> str:
    role = ch.role(uid)
    if role not in SENDERS:
        raise HTTPException(403, NOT_SENDER)
    return role


def leaders(ch: co.Church, uid: str) -> List[Dict[str, Any]]:
    """The leaders this login may send to, by name, each with why and the
    departments it can be for: [{contact_id, name, why, departments: [{id,
    name}]}]. Nobody is an empty list; a read that fails is a 503."""
    import church_map
    role = _sender(ch, uid)
    with church_map.once():
        mine = ch.persons_of(co.who(co.LOGIN, uid))
        others_at_top = ch.top - ({ch.owner_person} if ch.owner_person else set())
        m = ch.map
        depts = m.active() if m else []
        found: Dict[str, Dict[str, Any]] = {}

        def add(cid: Any, why: str, dept: Optional[Dict[str, Any]]) -> None:
            cid = str(cid or "")
            if not cid or cid in mine or cid in others_at_top:
                return
            got = found.setdefault(cid, {"contact_id": cid, "whys": [], "departments": []})
            if why and why not in got["whys"]:
                got["whys"].append(why)
            if dept and all(x["id"] != dept["id"] for x in got["departments"]):
                got["departments"].append({"id": dept["id"], "name": _plain(dept.get("name")) or "A department"})

        if role in co.KEEPS_ALL:
            for d in depts:
                for cid, verb in ((d.get("leader_contact_id"), "Leads"), (d.get("overseer_contact_id"), "Oversees")):
                    add(cid, f"{verb} {_plain(d.get('name'))}", d)
            everyone = co._everyone(ch) + ([ch.owner_person] if ch.owner_person else [])
            for cid in everyone:
                if cid not in found:
                    add(cid, co._what(ch, cid), None)
        else:
            for d, via in _manager_reach(ch, uid):
                for cid, verb in ((d.get("leader_contact_id"), "Leads"), (d.get("overseer_contact_id"), "Oversees")):
                    add(cid, f"{verb} {_plain(d.get('name'))} · {via}", d)
        names = ch.names(list(found))
    out = [{"contact_id": c, "name": names.get(c, "Someone"), "why": " · ".join(v["whys"][:2]) if role in co.KEEPS_ALL
            else "; ".join(v["whys"][:2]), "departments": v["departments"]} for c, v in found.items()]
    return sorted(out, key=lambda r: (r["name"].casefold(), r["contact_id"]))


# ─── Sending ──────────────────────────────────────────────────────────

def send(ch: co.Church, uid: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Checks it all, then one insert; answers with what it saved."""
    cid = _uuid(body.get("contact_id"), "leader")
    row = {"business_id": ch.b, "contact_id": cid, "sent_by": str(uid), "title": _title(body.get("title")),
           "note": _note(body.get("note")), "link": _link(body.get("link")),
           "for_date": _for_date(body.get("for_date")), "department_id": None}
    may = {r["contact_id"]: r for r in leaders(ch, uid)}
    if cid not in may:
        raise HTTPException(403, NOT_LEADER)
    dept = None
    if body.get("department_id") not in (None, ""):
        did = _uuid(body.get("department_id"), "department")
        m = ch.map
        dept = next((d for d in (m.active() if m else []) if d["id"] == did), None)
        if not dept:
            raise HTTPException(400, "That department isn't one of this church's")
        if ch.role(uid) not in co.KEEPS_ALL and all(x["id"] != did for x in may[cid]["departments"]):
            raise HTTPException(403, "That department isn't one you can send for.")
        row["department_id"] = did
    # Everything the answer says is read before the write: nothing after it
    # can fail on a read and answer 503 for something that was sent.
    sender = ch.login_name(str(uid))
    name = may[cid]["name"]
    saved = sb_clients.sb_post_as_service("/church_handovers", row)
    if not isinstance(saved, list) or not saved or not saved[0].get("id"):
        raise HTTPException(503, UNSAVED)
    depts = {dept["id"]: _plain(dept.get("name")) or "A department"} if dept else {}
    return shape_sent(saved[0], {cid: name}, depts, sender)


def _dept_names(ch: co.Church) -> Dict[str, str]:
    m = ch.map
    return {d["id"]: _plain(d.get("name")) or "A department" for d in (m.departments if m else [])}


def _seen_text(r: Dict[str, Any]) -> str:
    return "Seen" if r.get("seen_at") else "Not yet seen"


def shape_sent(r: Dict[str, Any], people: Dict[str, str], depts: Dict[str, str], sender: str = "") -> Dict[str, Any]:
    d = _day(r.get("for_date"))
    return {"id": str(r["id"]), "to": {"contact_id": str(r.get("contact_id")),
                                       "name": people.get(str(r.get("contact_id")), "Someone")},
            "title": _plain(r.get("title")), "note": r.get("note") or "", "link": r.get("link") or "",
            "for_date": d.isoformat() if d else None, "for_date_text": day_words(d),
            "department": depts.get(str(r.get("department_id") or "")) if r.get("department_id") else None,
            "sent_at": r.get("created_at"), "from": sender or OFFICE,
            "seen": bool(r.get("seen_at")), "seen_at": r.get("seen_at"), "seen_text": _seen_text(r)}


def sent(ch: co.Church, uid: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """What this login sent in the last three months, newest first."""
    _sender(ch, uid)
    now = now or _now()
    since = _q(_iso(now - timedelta(days=SENT_DAYS)))
    rows = _need(f"/church_handovers?business_id=eq.{_q(ch.b)}&sent_by=eq.{_q(uid)}&created_at=gte.{since}"
                 f"&select={FIELDS}&order=created_at.desc&limit={READ_MAX}")
    people = ch.names([r.get("contact_id") for r in rows])
    depts = _dept_names(ch) if any(r.get("department_id") for r in rows) else {}
    sender = ch.login_name(str(uid))
    items = [shape_sent(r, people, depts, sender) for r in rows]
    return {"sent": items, "counts": {"sent": len(items), "seen": sum(1 for i in items if i["seen"]),
                                      "not_seen": sum(1 for i in items if not i["seen"])}}


# ─── The leader's side ────────────────────────────────────────────────

def for_people(biz: Dict[str, Any], contact_ids: Iterable[Any], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """What the office sent these people (one person, as the member app and
    My week ask it): every one not yet seen, then what they've seen in the
    last two weeks, newest first. Each says who sent it. A read that fails
    raises a 503; the caller decides whether its page stands without it."""
    ids = sorted({str(c) for c in contact_ids if c})
    if not ids:
        return []
    now = now or _now()
    b = str(biz["id"])
    cut = _iso(now - timedelta(days=SEEN_DAYS))
    rows = _need(f"/church_handovers?business_id=eq.{_q(b)}&contact_id=in.({','.join(_q(i) for i in ids)})"
                 f"&or=(seen_at.is.null,seen_at.gte.{_q(cut)})&select={FIELDS}&order=created_at.desc&limit=100")
    rows = [r for r in rows if str(r.get("business_id")) == b and str(r.get("contact_id")) in ids]
    if not rows:
        return []
    ch = co.Church(biz)
    senders = {}
    for u in {str(r.get("sent_by") or "") for r in rows if r.get("sent_by")}:
        try:
            senders[u] = ch.login_name(u) if (u == ch.owner or u in ch.seats) else ""
        except HTTPException:
            senders[u] = ""
    names = {u: (n if n not in ("The owner", "An office login") else "") for u, n in senders.items()}
    depts = {}
    if any(r.get("department_id") for r in rows):
        try:
            depts = _dept_names(ch)
        except HTTPException:
            depts = {}
    out = []
    for r in rows:
        d = _day(r.get("for_date"))
        out.append({"id": str(r["id"]), "title": _plain(r.get("title")) or "Something from the office",
                    "note": r.get("note") or "", "link": r.get("link") or "",
                    "for_date": d.isoformat() if d else None, "for_date_text": day_words(d),
                    "department": depts.get(str(r.get("department_id") or "")),
                    "from": names.get(str(r.get("sent_by") or "")) or OFFICE, "sent_at": r.get("created_at"),
                    "seen": bool(r.get("seen_at"))})
    out.sort(key=lambda x: (x["seen"], -_stamp(x["sent_at"])))
    return out


def persons_of_login(biz: Dict[str, Any], uid: Any) -> set:
    """A login's own person (church_over: its tied record, else the one its
    sign-in email names; the owner's by their Auth email)."""
    return co.Church(biz).persons_of(co.who(co.LOGIN, uid))


def for_login(biz: Dict[str, Any], uid: Any, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """What was sent to this login's own person, as for_people says (My week)."""
    return for_people(biz, persons_of_login(biz, uid), now)


def _stamp(v: Any) -> float:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def mark_seen(business_id: Any, contact_ids: Iterable[Any], handover_id: Any,
              now: Optional[datetime] = None) -> Dict[str, Any]:
    """Got it: marks one of these people's hand-overs seen (once; again
    answers with it as it is). Anyone else's, or another church's, is a 404;
    a failed write is a 503."""
    hid = _uuid(handover_id, "item")
    ids = sorted({str(c) for c in contact_ids if c})
    if not ids:
        raise HTTPException(404, NOT_YOURS)
    b = _q(business_id)
    who = f"contact_id=in.({','.join(_q(i) for i in ids)})"
    got = sb_clients.sb_patch_as_service(
        f"/church_handovers?id=eq.{_q(hid)}&business_id=eq.{b}&{who}&seen_at=is.null",
        {"seen_at": _iso(now or _now())})
    if not isinstance(got, list):
        raise HTTPException(503, "That didn't save. Try again.")
    if got:
        return {"id": hid, "seen": True, "seen_at": got[0].get("seen_at")}
    rows = _need(f"/church_handovers?id=eq.{_q(hid)}&business_id=eq.{b}&{who}&select=id,seen_at&limit=1")
    if not rows:
        raise HTTPException(404, NOT_YOURS)
    return {"id": hid, "seen": bool(rows[0].get("seen_at")), "seen_at": rows[0].get("seen_at")}


# ─── The routes ───────────────────────────────────────────────────────

def _gate(session: UserSession, biz: Dict[str, Any]) -> co.Church:
    import church_assignments as cas
    return cas._church(session, biz)


@router.get("/handovers/leaders")
def handovers_leaders(business_id: str, session: UserSession = Depends(sb_clients.authed_request),
                      biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """The leaders I may send to, each with why. Nobody is an empty list."""
    ch = _gate(session, biz)
    return {"leaders": leaders(ch, str(session.user.id))}


@router.get("/handovers")
def handovers_sent(business_id: str, session: UserSession = Depends(sb_clients.authed_request),
                   biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """What I sent, newest first, each Seen or Not yet seen."""
    ch = _gate(session, biz)
    return sent(ch, str(session.user.id))


@router.post("/handovers")
def handovers_send(body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """Send a leader something for their area. Answers with what it saved."""
    import church_assignments as cas
    ch = cas._church_from_body(session, body or {})
    return {"saved": send(ch, str(session.user.id), body or {})}


@router.post("/handovers/{handover_id}/seen")
def handovers_seen(handover_id: str, body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """Got it, from My week: one sent to this login's own person."""
    import church_assignments as cas
    ch = cas._church_from_body(session, body or {})
    return {"saved": mark_seen(ch.b, ch.persons_of(co.who(co.LOGIN, session.user.id)), handover_id)}


# ─── Told: the hourly sweep ───────────────────────────────────────────

TOLD_FIELDS = "id,business_id,contact_id,sent_by,title,note,link,for_date,department_id,created_at,told_at"


def _item_text(r: Dict[str, Any], senders: Dict[str, str], depts: Dict[str, str], many: bool) -> str:
    """One hand-over, in full: what it is, who sent it (when several did),
    its department and day, the note, the link."""
    bits = []
    if many:
        bits.append(f"from {senders.get(str(r.get('sent_by') or '')) or OFFICE}")
    dept = depts.get(str(r.get("department_id") or ""))
    if dept:
        bits.append(f"for {dept}")
    d = _day(r.get("for_date"))
    if d:
        bits.append(f"for {day_words(d)}")
    lines = [f"“{_plain(r.get('title'))}”" + (", " + ", ".join(bits) if bits else "")]
    note = str(r.get("note") or "").replace("\r\n", "\n").strip()
    if note:
        lines.append(note)
    if str(r.get("link") or "").startswith("https://"):
        lines.append(str(r["link"]))
    return "\n".join(lines)


def told_text(name: str, rows: List[Dict[str, Any]], senders: Dict[str, str], depts: Dict[str, str],
              where: str) -> Tuple[str, str]:
    """(subject end, the email's words) for what arrived for one person:
    every hand-over in full, one after another (#1804 review: a grouped
    email never drops a note or a link), then `where`."""
    import church_leader_tasks as clt
    by = [senders.get(str(r.get("sent_by") or "")) or OFFICE for r in rows]
    who = _join(by)
    many = len(set(by)) > 1
    n = len(rows)
    intro = f"{who} sent you something:" if n == 1 else f"{who} sent you {n} things:"
    parts = [f"Hi {clt.first_name(name) or 'there'},", intro]
    parts += [_item_text(r, senders, depts, many) for r in rows]
    if where:
        parts.append(where)
    return (f"{who} sent you something" if n == 1 else f"{who} sent you {n} things"), "\n\n".join(parts)


def _render(biz: Dict[str, Any], text: str, preheader: str, link: str = "", label: str = "") -> str:
    """The email, from the church, with only https:// addresses made into
    links (an http:// one stays plain text)."""
    import email_layout
    settings = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    church = _plain(biz.get("name")) or "Your church"
    return email_layout.render_html(
        text, business_name=church, brand=email_layout.brand_of(settings), sig=None, preheader=preheader[:90],
        cta=(label, link) if link and label else None, https_only=True,
        disclaimer=f"You’re getting this because you lead at {church}.", footer_note="Sent by your church office")


def _join(names: List[str]) -> str:
    names = [n for n in dict.fromkeys(names) if n]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _claim(b: str, cid: str, ids: List[str], stamp: str) -> Optional[List[Dict[str, Any]]]:
    got = sb_clients.sb_patch_as_service(
        f"/church_handovers?business_id=eq.{_q(b)}&contact_id=eq.{_q(cid)}&id=in.({','.join(_q(i) for i in ids)})"
        "&told_at=is.null", {"told_at": stamp})
    return got if isinstance(got, list) else None


def _release(b: str, ids: List[str], stamp: str) -> None:
    try:
        sb_clients.sb_patch_as_service(
            f"/church_handovers?business_id=eq.{_q(b)}&id=in.({','.join(_q(i) for i in ids)})&told_at=eq.{_q(stamp)}",
            {"told_at": None})
    except Exception:
        logger.warning("handovers: a claim wasn't let go (business %s)", b[:8], exc_info=True)


def tell(biz: Dict[str, Any], rows: List[Dict[str, Any]], now: datetime, stats: Dict[str, int]) -> None:
    """One church's untold hand-overs: one email a person. Everything the
    email says is read before the claim; what can't be read waits for the
    next sweep."""
    import church_assignments as cas
    import church_leader_tasks as clt
    import church_office_tasks as cot
    ch = co.Church(biz)
    b = ch.b
    church = _plain(biz.get("name")) or "Your church"
    by_person: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        if str(r.get("business_id")) == b and r.get("contact_id"):
            by_person.setdefault(str(r["contact_id"]), []).append(r)
    people = clt._contacts(b, list(by_person))
    if people is None:
        stats["unread"] += len(rows)
        print(f"[church_handovers] {b[:8]}: the people weren't read; next sweep", flush=True)
        return
    try:
        office_people = set(ch.person_login) | ({ch.owner_person} if ch.owner_person else set())
        senders = {}
        for u in {str(r.get("sent_by") or "") for r in rows if r.get("sent_by")}:
            n = ch.login_name(u) if (u == ch.owner or u in ch.seats) else ""
            senders[u] = n if n not in ("The owner", "An office login") else ""
        depts = _dept_names(ch) if any(r.get("department_id") for r in rows) else {}
    except HTTPException:
        stats["unread"] += len(rows)
        print(f"[church_handovers] {b[:8]}: who sent them wasn't read; next sweep", flush=True)
        return
    office_reply = clt._office_email(biz)
    sender_email: Dict[str, Optional[str]] = {}
    for u in senders:
        got = cas._login_email(ch, u)
        sender_email[u] = got or None          # '' (none) or None (unread): the church office answers instead
    for cid, mine in by_person.items():
        mine.sort(key=lambda r: str(r.get("created_at") or ""))
        p = people.get(cid) or {}
        email, name = p.get("email", ""), p.get("name", "")
        # A reply goes to whoever sent it, when one login sent everything
        # and their address is known; else to the church office.
        sent_by = {str(r.get("sent_by") or "") for r in mine}
        one = next(iter(sent_by)) if len(sent_by) == 1 else ""
        reply_to = (sender_email.get(one) if one else None) or office_reply
        answer = (f"Reply to this email to answer {senders[one].split(' ')[0]}." if one and sender_email.get(one)
                  and senders.get(one) else "Reply to this email to answer the church office.")
        if cid in office_people:
            where = f"It’s on your My week in the church’s app. {answer}"
            link, label = cot._link(b), "Open My week"
        else:
            # No Lead tab line until the member app's part ships (PR C2).
            where, link, label = answer, "", ""
        ids = [str(r["id"]) for r in mine]
        stamp = _iso(now)
        claimed = _claim(b, cid, ids, stamp)
        if not claimed:
            continue
        got = {str(r["id"]) for r in claimed}
        mine = [r for r in mine if str(r["id"]) in got]
        if not email:
            stats["no_email"] += len(mine)
            continue
        subject_end, text = told_text(name, mine, senders, depts, where)
        try:
            html = _render(biz, text, _plain(mine[0].get("title"))[:80], link, label)
            clt.deliver(biz, email, name, f"{church}: {subject_end}", html,
                        f"handover-{cas.digest(r['id'] for r in mine)}", reply_to=reply_to)
        except Exception:
            logger.warning("handovers: an email failed (business %s)", b[:8], exc_info=True)
            _release(b, [str(r["id"]) for r in mine], stamp)
            stats["unsent"] += len(mine)
            continue
        stats["told"] += len(mine)
        stats["emails"] += 1


def sweep_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Hourly, on the worker (kmj_intake_automation): what the office sent
    since the last sweep, one email a person. Only the churches the switch is
    open for, every untold row of theirs from the last week, page by page.
    A church that fails never stops the others. Quiet with the switch off,
    and before the migration (its read fails and nothing happens)."""
    import church_assignments as cas
    import church_follow_up as cfu
    import church_leader_tasks as clt
    stats = {"churches": 0, "told": 0, "emails": 0, "no_email": 0, "unsent": 0, "unread": 0}
    if co.mode() == "off":
        return stats
    now = now or _now()
    churches = cas._open_churches()
    if churches == []:
        return stats
    scope = "" if churches is None else f"&business_id=in.({','.join(_q(b['id']) for b in churches)})"
    since = _q(_iso(now - timedelta(days=TELL_DAYS)))
    rows = cas._all(f"/church_handovers?told_at=is.null&created_at=gte.{since}{scope}&select={TOLD_FIELDS}",
                    "what the office sent")
    if not rows:
        return stats            # nothing new, the migration isn't applied, or the read failed: next hour
    work: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        work.setdefault(str(r.get("business_id")), []).append(r)
    bizs: Dict[str, Dict[str, Any]] = {str(b["id"]): b for b in churches or []}
    for chunk in clt._chunks(b for b in work if b not in bizs):
        for x in sb_clients.sb_get_as_service(f"/businesses?id=in.({','.join(_q(i) for i in chunk)})"
                                              f"&select={cas.BIZ_FIELDS}&limit=100") or []:
            bizs[str(x["id"])] = x
    for b, todo in work.items():
        biz = bizs.get(b)
        if not biz or not cfu.is_church(biz) or not co.church_open(b):
            continue
        stats["churches"] += 1
        try:
            tell(biz, todo, now, stats)
        except Exception:
            logger.warning("handovers sweep failed for business %s", b[:8], exc_info=True)
    return stats
