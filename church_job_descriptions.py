"""church_job_descriptions.py — everyone's job at a church, in the church's own
words, and whose job new work is (docs/CHURCH_JOB_DESCRIPTIONS.md).

Kevin, 2026-11-12: "I need to make sure chief is able to learn job descriptions
for everyone. this important because when a job is created and the leader is
unaware, Chief should know Jobs of each person. can we make sure chief knows."

    job(...) ........... one person's whole job: their title (the written one,
                         else their role's, else their seat's), the written
                         description and who wrote it when, the duties they do
                         of their own (church_map_asks.work() for an office
                         login), the departments they lead, oversee or help,
                         their roles with each role's definition filled in, who
                         they answer to and who is over them (church_over.above)
    roster(...) ........ everyone: the owner, every active office login, every
                         person with an active or asked role or who leads or
                         oversees a department, and anyone with a written
                         description; ROSTER_MAX at most, one compact line each
                         (a written description as its title and about its first
                         paragraph, EXCERPT_MAX; only job() carries the whole)
    whose(...) ......... whose job some new work is: everyone ranked against
                         the work's words (lower case, stop words out, light
                         stemming) across written descriptions and titles, duty
                         labels, their training lines and areas, departments,
                         roles and their definitions. The top three with the
                         words that matched and who is over each. A department
                         whose name matches is in its leader's and overseer's
                         words, so they rank. Nobody: whoever oversees the
                         office; else the owner. The roster comes back too, so
                         Chief judges past the words
    draft(...) ......... a starting description from what the system holds only,
                         in plain sections: Summary (title, who they answer to,
                         whom they support as the office, departments, role
                         definitions), What they own (each duty and its training
                         line), Their week (duties by the day they fall on, as
                         church_my_week places them, picked days included), On
                         Sunday (their Sunday duties; the church fills in the
                         times). Never saved by itself
    set_description, undo
                         write or clear one, logged (church_job_description_
                         changes); undo puts the last change back, only the last
    the routes ......... GET  /church/jobs?business_id=                    roster
                         GET  /church/jobs/person?business_id=&contact_id=|user_id=
                         GET  /church/jobs/whose?business_id=&q=
                         GET  /church/jobs/draft?business_id=&contact_id=|user_id=
                         PUT  /church/jobs/person {business_id, contact_id|user_id,
                              title, description, source} ({..., clear: true} clears)
                         POST /church/jobs/person/undo {business_id, contact_id|user_id}

Who (every route and Chief verb: someone signed in with a seat at the church):
  write ........ set, clear, undo: the owner, or someone over that person
                 (church_over.is_over), the same people who may hand them work.
                 No office seat is over a pastor or an elder, so an Admin can't
                 write a pastor's; the owner or the map's ministry chain can
  read one ..... the person, anyone over them, and any office seat (Manager and
                 up), as the duties page shows every duty's holder to a Manager
  read all ..... the roster and whose: the office seats, Manager and up
  pay .......... a title or description with pay words (PAY_WORDS) isn't saved;
                 a budget is fine

A person is keyed by their contact; a login with no person behind it by its
user id. A login's person is church_over.Church.login_person (the seat's tied
record, else the one person its sign-in email names: business_users_router.
seat_person's rule, read once for the whole church; the owner's by their
sign-in email). A read looks for the person's row first, then the login's.

Server-only tables (supabase/APPLY-2026-11-12-church-job-descriptions.sql).
Before the file is applied (ready()) every route answers 503 with "isn't
ready", and Chief's verbs say so. Switched with assignments:
CHURCH_ASSIGNMENTS (church_over.office_open for the routes). A read that fails
is a 503, never a yes.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

import business_access
import church_over as co
import sb_clients
from auth_supabase import UserSession

router = APIRouter(prefix="/church", tags=["church"])

TABLE = "church_job_descriptions"
LOG = "church_job_description_changes"
COLS = "id,business_id,contact_id,user_id,title,description,source,written_by,written_at,updated_by,updated_at"
LOG_COLS = "id,business_id,contact_id,user_id,before,after,by,at,undone_at"
IMAGE = ("title", "description", "source", "written_by", "written_at", "updated_by", "updated_at")
TITLE_MAX, DESCRIPTION_MAX = 80, 8000
EXCERPT_MAX = 300          # a person's description in the roster and whose: about its first paragraph
MATCHED_LINES, LINE_MAX = 3, 240
SOURCES = ("said", "pasted", "document", "drafted")
ROSTER_MAX = 80
TOP = 3
SEATS = ("owner", "admin", "manager", "member")     # who may ask at all
READ_ALL = ("owner", "admin", "manager")            # every job: the office seats, Manager and up
OFFICE = ("admin", "manager")

NOT_CHURCH = "Job descriptions are for churches."
NOT_READY = "Job descriptions aren't ready at this church yet."
UNREAD = "The job descriptions couldn't be read just now. Try again."
UNSAVED = "That didn't save. Try again."
OFFICE_ONLY = "Job descriptions are for the church's office logins."
ALL_ONLY = "Everyone's jobs are for the church's office seats: a Manager and up."
NOT_YOURS = "Their job is read by the people over them and the church's office seats."
PAY = "Pay stays out of job descriptions; office seats can read them."

# Pay, never budgets: "manages the $5k youth budget" is fine.
PAY_WORDS = re.compile(r"\b(?:salar(?:y|ies|ied)|wages?|compensation|hourly|stipends?|pay\s*rates?|rates?\s+of\s+pay|"
                       r"per\s+hour|benefits)\b|/\s*(?:hr|hour)\b", re.I)


# ─── Small things ─────────────────────────────────────────────────────

def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


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


def _join(words: Iterable[str]) -> str:
    words = [w for w in dict.fromkeys(words) if w]
    if len(words) < 2:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def _day(v: Any) -> str:
    try:
        at = datetime.fromisoformat(str(v or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    return f"{at:%b} {at.day}, {at.year}"


# ─── Ready ────────────────────────────────────────────────────────────

_READY: Dict[str, bool] = {}


def ready() -> Optional[bool]:
    """Whether both tables answer: True (remembered for the process once they
    do), False (the file isn't applied: the church's own row still reads),
    None (the probe itself failed, and nothing can be said either way)."""
    if _READY.get("ok"):
        return True
    try:
        a = sb_clients.sb_get_as_service(f"/{TABLE}?select=id&limit=1")
        b = sb_clients.sb_get_as_service(f"/{LOG}?select=id&limit=1")
        if isinstance(a, list) and isinstance(b, list):
            _READY["ok"] = True
            return True
        base = sb_clients.sb_get_as_service("/businesses?select=id&limit=1")
    except Exception:  # noqa: BLE001 — unread is not a yes
        return None
    return False if isinstance(base, list) else None


# ─── Words ────────────────────────────────────────────────────────────

STOP = frozenset((
    "a an the and or but nor of to for in on at by with from into onto over under about as is are was were be been "
    "being it its it's this that these those there here who whom whose what which when where why how job jobs work "
    "works task tasks thing things someone somebody anyone anybody everyone everybody people person need needs "
    "needed should would could can will shall may might must do does did done doing get gets got make makes made "
    "have has had i me my mine we us our you your they them their he him his she her hers please also just than "
    "then so if not no yes up down out off before after during next each every all any some more most very much "
    "many one ones else whoever handle handles handling take takes look looks someone's").split())


def _stem(w: str) -> str:
    """A word without its common ending, so "inspecting" finds "inspect" and
    "policies" finds "policy". Light on purpose: the match below also takes
    one word starting the other."""
    w = w.replace("'", "")
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 4 and w.endswith("ed") and not w.endswith("eed"):
        return w[:-2]
    if len(w) > 4 and (w.endswith("ches") or w.endswith("shes") or w.endswith("xes") or w.endswith("sses")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def terms(text: Any) -> List[Tuple[str, str]]:
    """(the word as said, its stem) for each word that carries meaning, once
    each: lower case, stop words and bare numbers out."""
    out: Dict[str, str] = {}
    for w in re.findall(r"[a-z0-9][a-z0-9']*", _plain(text).casefold().replace("’", "'")):
        w = w.strip("'")
        if len(w) < 2 or w in STOP or w.isdigit():
            continue
        st = _stem(w)
        if st and st not in STOP and st not in out:
            out[st] = w
    return [(w, st) for st, w in out.items()]


def _hit(a: str, b: str) -> bool:
    return a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)))


# ─── Their duties ─────────────────────────────────────────────────────

def duties_of(ch: co.Church, uid: Optional[str]) -> Tuple[List[str], bool]:
    """(the duties a login does of its own, in the catalog's order; whether it
    covers the rest of the office's lanes). church_startup.own_duties' rule,
    with the money duties kept (an Admin's books are part of their job; no
    amount is ever here): the owner and an Admin, what was moved to them by
    name and their stored lane's starter duties nobody moved (church_map_asks.
    work's rule); a Manager, what it holds (church_duties' standing), and in
    the Executive Pastor's lane only its own two (OVERSIGHT) of the whole
    office it covers."""
    import church_duties as cd
    role = ch.role(uid) if uid else None
    if role not in READ_ALL:
        return [], False
    lanes = set(ch.lanes(uid))
    moved = ch.moved
    mine = {k for k, holders in moved.items() if uid in holders}
    covers = False
    if role in co.KEEPS_ALL:
        own = mine | {k for ln in lanes if ln != cd.EXEC for k in cd.STARTER.get(ln, ()) if k not in moved}
    else:
        held = set(ch.held(uid))
        if cd.EXEC in lanes:
            own = {k for k in held if k in cd.OVERSIGHT or k in mine
                   or any(k in cd.STARTER.get(ln, ()) for ln in lanes if ln != cd.EXEC)}
            covers = True
        else:
            own = held
    return [k for k in cd.CATALOG if k in own], covers


def definition(d: Dict[str, Any], title: str, church: str) -> str:
    """A role's definition with its words filled in (a ready-made's carries
    {title}); its job's when it has none of its own."""
    import church_roles as cr
    text = str(d.get("definition") or (cr.JOBS.get(str(d.get("job") or "")) or {}).get("definition") or "")
    return _plain(text.replace("{title}", _plain(title) or "This role").replace("{church}", church or "the church")
                  .replace("{lead}", "leader")).rstrip(".")


# ─── One church's jobs ────────────────────────────────────────────────

class Jobs:
    """One church's jobs: church_over.Church's reads (its logins, people, map
    and roles, each once), plus the written rows and the asked roles, each
    read once."""

    def __init__(self, ch: co.Church):
        self.ch = ch
        self._memo: Dict[str, Any] = {}

    def _got(self, name: str, fn):
        if name not in self._memo:
            self._memo[name] = fn()
        return self._memo[name]

    @property
    def church(self) -> str:
        return _plain(self.ch.business.get("name")) or "the church"

    @property
    def rows(self) -> List[Dict[str, Any]]:
        """Every written row at this church."""
        return self._got("rows", lambda: [
            r for r in _need(f"/{TABLE}?business_id=eq.{_q(self.ch.b)}&select={COLS}&limit=1000")
            if str(r.get("business_id")) == self.ch.b])

    @property
    def asked(self) -> List[Dict[str, Any]]:
        """Every role a person holds or was asked to hold (active, invited), in
        the library's order."""
        def load():
            rows = _need(f"/church_leader_roles?business_id=eq.{_q(self.ch.b)}&status=in.(active,invited)"
                         "&select=contact_id,role,status,scope&limit=2000")
            rank = {d["key"]: n for n, d in enumerate(self.ch.defs)}
            return sorted((r for r in rows if r.get("contact_id")),
                          key=lambda r: (r.get("status") != "active", rank.get(str(r.get("role") or ""), 999)))
        return self._got("asked", load)

    def row_for(self, cid: Optional[str], uid: Optional[str]) -> Optional[Dict[str, Any]]:
        """Their written row: the person's, else the login's (a login with no
        person when it was written)."""
        if cid:
            hit = next((r for r in self.rows if str(r.get("contact_id") or "") == cid), None)
            if hit:
                return hit
        if uid:
            return next((r for r in self.rows if not r.get("contact_id") and str(r.get("user_id") or "") == uid), None)
        return None

    def login_of(self, cid: Optional[str]) -> Optional[str]:
        """The login a person is: their office login, the owner's, else any
        seat whose person they are (a Member seat: still their person to
        church_over, but its row may be kept by the login)."""
        ch = self.ch
        if not cid:
            return None
        if cid in ch.person_login:
            return ch.person_login[cid]
        if ch.owner and cid == ch.owner_person:
            return ch.owner
        return next((u for u, c in sorted(ch.login_person.items()) if c == cid and u in ch.seats), None)

    def entry(self, cid: Optional[str], uid: Optional[str], *, full: bool = True) -> Dict[str, Any]:
        """One person, or one login with no person, as everything here takes
        them. `who` is church_over's: an office login (or the owner) is their
        login, anyone else their person."""
        ch = self.ch
        cid = cid or (ch.login_person.get(uid) if uid else None) or None
        uid = uid or self.login_of(cid)
        seat = ch.role(uid) if uid else None
        office = bool(uid) and (uid == ch.owner or uid in ch.office)
        who = co.who(co.LOGIN, uid) if office or not cid else co.who(co.PERSON, cid)
        roles = []
        for h in self.asked if cid else []:
            if str(h.get("contact_id")) != cid:
                continue
            import church_roles as cr
            key = str(h.get("role") or "")
            d = ch.def_of(key_=key) or {}
            title = d.get("title") or cr.title_of(key, ch.defs)
            roles.append({"key": key, "title": title, "scope": _plain(h.get("scope")),
                          "asked": h.get("status") == "invited", "team": d.get("covers") == "team",
                          "definition": definition(d, title, self.church) if d else ""})
        e: Dict[str, Any] = {
            "key": f"person:{cid}" if cid else f"login:{uid}", "contact_id": cid, "user_id": uid, "who": who,
            "seat": seat, "roles": roles, "row": self.row_for(cid, uid), "own": [], "covers": False,
            "leads": [], "oversees": [], "helps": [], "answers_to": None, "name": "", "answers_to_name": None}
        if not full:
            return e
        import church_duties as cd
        e["own"], e["covers"] = duties_of(ch, uid) if seat in READ_ALL else ([], False)
        e["lanes"] = ch.lanes(uid) if seat in OFFICE else []
        m = ch.map or None
        if m and cid:
            e["leads"] = [d["name"] for d in m.led_by(cid)]
            e["oversees"] = [d["name"] for d in m.overseen_by(cid)]
            e["answers_to"] = m.answers_to(cid)
        if m and e["own"]:
            e["helps"] = [{"name": d["name"], "duty": cd.CATALOG[d["support_duty"]]["label"]}
                          for d in m.active() if d.get("support_duty") in e["own"]]
        return e

    def name(self, entries: List[Dict[str, Any]]) -> None:
        """Each one's name and the name of whoever they answer to, in one read."""
        ch = self.ch
        names = ch.names([e["contact_id"] for e in entries if e["contact_id"]] +
                         [e["answers_to"] for e in entries if e.get("answers_to")])
        for e in entries:
            n = names.get(e["contact_id"]) if e["contact_id"] else None
            e["name"] = n if n and n != "Someone" else (ch.login_name(e["user_id"]) if e["user_id"] else "Someone")
            e["answers_to_name"] = names.get(e["answers_to"]) if e.get("answers_to") else None

    def everyone(self) -> List[Dict[str, Any]]:
        """The owner, the office logins (the Admins first), every person with an
        active or asked role (the library's order), each department's leader and
        overseer, and anyone with a written description; each once."""
        ch = self.ch
        seen: Dict[str, Dict[str, Any]] = {}

        def add(cid: Optional[str], uid: Optional[str]) -> None:
            e = self.entry(cid, uid)
            seen.setdefault(e["key"], e)

        if ch.owner:
            add(None, ch.owner)
        for u in sorted(ch.office, key=lambda u: (ch.role(u) != "admin", ch.login_name(u).casefold())):
            add(None, u)
        for h in self.asked:
            add(str(h["contact_id"]), None)
        m = ch.map
        if m:
            for d in m.active():
                for p in (d.get("leader_contact_id"), d.get("overseer_contact_id")):
                    if p:
                        add(str(p), None)
        for r in self.rows:
            cid, uid = str(r.get("contact_id") or "") or None, str(r.get("user_id") or "") or None
            if cid:
                add(cid, None)
            elif uid and (uid == ch.owner or uid in ch.seats):      # a login that left shows nowhere
                add(None, uid)
        out = list(seen.values())
        self.name(out)
        return out

    def writer(self, uid: Any) -> str:
        uid = str(uid or "")
        if uid and (uid == self.ch.owner or uid in self.ch.seats):
            return self.ch.login_name(uid)
        return "someone who has left the office"


# ─── Titles, who may, and the lines ───────────────────────────────────

def system_title(ch: co.Church, e: Dict[str, Any]) -> str:
    """Their title from what the system holds: their first role (a team's
    leader by their team), else their seat and lane, else what they lead."""
    for r in e["roles"]:
        return f"{r['scope']} leader" if r["team"] and r["scope"] else r["title"]
    if e["seat"] == "owner":
        return "The owner"
    if e["seat"] in OFFICE:
        import church_duties as cd
        lanes = " · ".join(cd.lane_label(k) for k in ch.lanes(e["user_id"]))
        return lanes or ("Admin" if e["seat"] == "admin" else "Office")
    if e["leads"]:
        return f"Leads {e['leads'][0]}"
    if e["oversees"]:
        return f"Oversees {e['oversees'][0]}"
    return "One of the church's people"


def title_of(ch: co.Church, e: Dict[str, Any]) -> Tuple[str, bool]:
    """(their title, whether it's a written one)."""
    row = e["row"]
    if row and _plain(row.get("title")):
        return _plain(row["title"]), True
    return system_title(ch, e), False


def under_keys(ch: co.Church, me: Dict[str, str]) -> Set[str]:
    """church_over's answer for everyone at once: whom `me` is over."""
    import church_map
    with church_map.once():
        return {f"{k}:{i}" for k, i, _w in co._under(ch, me)}


def is_self(ch: co.Church, uid: str, e: Dict[str, Any]) -> bool:
    return e["user_id"] == uid or (bool(e["contact_id"]) and e["contact_id"] == ch.login_person.get(uid))


def can_read(ch: co.Church, uid: str, e: Dict[str, Any], under: Set[str]) -> bool:
    return ch.role(uid) in READ_ALL or is_self(ch, uid, e) or co.key(e["who"]) in under


def can_write(ch: co.Church, uid: str, e: Dict[str, Any], under: Set[str]) -> bool:
    return ch.role(uid) == "owner" or co.key(e["who"]) in under


def mine(row: Optional[Dict[str, Any]], uid: str) -> bool:
    """Whether the words saved now are this login's own."""
    return bool(row) and str(row.get("updated_by") or "") == str(uid)


def line(J: Jobs, e: Dict[str, Any], *, words: bool, fence=None) -> str:
    """One compact line: who, title, what they do of their own, departments,
    other roles, who they answer to, and their written description (its first
    words, with `words`). `fence` makes a person's written words safe to read
    (Chief's), else they come as written (the screen's)."""
    import church_duties as cd
    say = fence or _plain
    title, written = title_of(J.ch, e)
    head = f"{e['name']} ({say(title) if written else title})"
    bits: List[str] = []
    labels = [cd.CATALOG[k]["label"] for k in e["own"]]
    if labels:
        bits.append("does " + "; ".join(labels[:6]) + (f" and {len(labels) - 6} more" if len(labels) > 6 else ""))
    if e["covers"]:
        bits.append("covers any lane's work")
    if e["leads"]:
        bits.append("leads " + _join(e["leads"]))
    if e["oversees"]:
        bits.append("oversees " + _join(e["oversees"]))
    if e["helps"]:
        bits.append("helps " + _join([h["name"] for h in e["helps"]]) + " as the office")
    shown = {_plain(title).casefold()}
    more = [r["title"] + (f" · {r['scope']}" if r["scope"] and not r["team"] else "") + (" (asked)" if r["asked"] else "")
            for r in e["roles"] if r["title"].casefold() not in shown and f"{r['scope']} leader".casefold() not in shown]
    if more:
        bits.append("roles: " + ", ".join(more))
    if e.get("answers_to_name"):
        bits.append(f"answers to {e['answers_to_name']}")
    row = e["row"]
    if row and words:
        bits.append(f"job description: “{say(excerpt(row.get('description')))}”")
    elif row:
        bits.append("job description written")
    else:
        bits.append("no written job description")
    return f"{head}: " + "; ".join(bits)


def _cut(text: str, most: int) -> str:
    return text if len(text) <= most else text[:most - 1].rsplit(" ", 1)[0] + "…"


def excerpt(text: Any) -> str:
    """About the first paragraph of a description, EXCERPT_MAX at most: a
    heading's paragraph runs on into the next, and its lines are joined with a
    slash. The roster and whose carry this, never the whole."""
    paras = [[_plain(ln) for ln in p.split("\n") if _plain(ln)]
             for p in re.split(r"\n\s*\n", str(text or "").replace("\r\n", "\n"))]
    paras = [p for p in paras if p]
    out = ""
    for p in paras:
        out = f"{out} / {' / '.join(p)}" if out else " / ".join(p)
        if len(out) >= 120:
            break
    return _cut(out, EXCERPT_MAX)


def matched_lines(text: Any, stems: List[str]) -> List[str]:
    """The lines of a description that carry the matched words (MATCHED_LINES
    at most, each LINE_MAX), so whose shows why without the whole."""
    found = []
    for n, ln in enumerate(str(text or "").split("\n")):
        ln = _plain(ln)
        count = len({st for st in stems for _w, s in terms(ln) if _hit(st, s)}) if ln else 0
        if count:
            found.append((count, n, ln))
    if not found:
        return []
    best = max(c for c, _n, _ln in found)
    keep = sorted(sorted((f for f in found if f[0] >= best - 1), key=lambda f: (-f[0], f[1]))[:MATCHED_LINES],
                  key=lambda f: f[1])               # the lines that carry most of the words, in their order
    return [_cut(ln, LINE_MAX) for _c, _n, ln in keep]


def foreign(e: Dict[str, Any], uid: str) -> bool:
    """Whether anything shown of theirs (the written title or description) is
    someone else's words."""
    return bool(e["row"]) and not mine(e["row"], uid)


def view(J: Jobs, e: Dict[str, Any], *, full: bool = False) -> Dict[str, Any]:
    """One person as the screen takes them: their description's excerpt, and
    the whole of it only with `full` (one person's job)."""
    title, written = title_of(J.ch, e)
    row = e["row"] or {}
    return {"for": e["key"], "contact_id": e["contact_id"], "user_id": e["user_id"], "name": e["name"],
            "title": title, "title_written": written, "seat": e["seat"], "line": line(J, e, words=False),
            "written": bool(e["row"]), "excerpt": excerpt(row.get("description")) if row else None,
            **({"description": row.get("description") if row else None} if full else {}),
            "source": row.get("source") if row else None,
            "written_by": J.writer(row.get("written_by")) if row else None, "written_at": row.get("written_at"),
            "updated_by": J.writer(row.get("updated_by")) if row else None, "updated_at": row.get("updated_at")}


# ─── job / roster / whose / draft ─────────────────────────────────────

def job(J: Jobs, uid: str, e: Dict[str, Any], under: Set[str]) -> Dict[str, Any]:
    """One person's whole job (an office login's duties and who they answer to
    from church_map_asks.work, the same reader my_work uses)."""
    import church_duties as cd
    ch = J.ch
    duties = [{"key": k, "label": cd.CATALOG[k]["label"], "when": "", "picked": None} for k in e["own"]]
    answers = e.get("answers_to_name")
    if e["seat"] in READ_ALL and e["user_id"]:
        import church_assignments as cas
        import church_map_asks as cma
        import church_my_week as week
        w = cma.work(ch.business, e["user_id"], e["seat"])
        when = {d["key"]: d["when"] for d in w["duties"]}
        picks = picks_of(ch, e["user_id"]) if duties else {}
        # Its day as My week places it: the day they picked, else work()'s catalog day.
        duties = [{**d, "picked": picks.get(d["key"]),
                   "when": week.placed(cas.day_with(cd.CATALOG[d["key"]]["day"], picks[d["key"]]))[2]
                   if d["key"] in picks else when.get(d["key"], "")} for d in duties]
        answers = w.get("answers_to") or answers
    over = [o["name"] for o in co.above(ch, e["who"])]
    return {**view(J, e, full=True), "duties": duties, "covers": e["covers"], "leads": e["leads"],
            "oversees": e["oversees"],
            "helps": e["helps"],
            "roles": [{k: r[k] for k in ("title", "scope", "asked", "definition")} for r in e["roles"]],
            "answers_to": answers, "over": over, "can_write": can_write(ch, uid, e, under)}


def roster(J: Jobs) -> Dict[str, Any]:
    people = J.everyone()
    return {"church": J.church, "people": [view(J, e) for e in people[:ROSTER_MAX]],
            "more": max(0, len(people) - ROSTER_MAX)}


def _bag(J: Jobs, e: Dict[str, Any]) -> List[Tuple[str, int, str]]:
    """(stem, weight, where) for everything their job says: their own words
    and their duties' labels weigh most, departments and roles next, training
    lines, areas and definitions least."""
    import church_duties as cd
    from church_areas import AREAS
    out: List[Tuple[str, int, str]] = []

    def put(text: Any, weight: int, where: str) -> None:
        out.extend((st, weight, where) for _w, st in terms(text))

    row = e["row"]
    if row:
        put(row.get("description"), 3, "their written job description")
        put(row.get("title"), 3, "their job title")
    for k in e["own"]:
        d = cd.CATALOG[k]
        put(d["label"], 3, f"the duty “{d['label']}”")
        put(d["does"], 1, f"what “{d['label']}” covers")
        put((AREAS.get(d["area"]) or {}).get("label"), 1, f"the {(AREAS.get(d['area']) or {}).get('label', '')} area")
    if e["covers"]:
        put(cd.PSEUDO_LANES[cd.EXEC]["does"], 1, "covering the office's lanes")
    for n in e["leads"]:
        put(n, 2, f"leading {n}")
    for n in e["oversees"]:
        put(n, 2, f"overseeing {n}")
    for h in e["helps"]:
        put(h["name"], 2, f"helping {h['name']} as the office")
    for r in e["roles"]:
        put(r["title"], 2, f"the role {r['title']}")
        if r["scope"]:
            put(r["scope"], 2, f"leading {r['scope']}")
        put(r["definition"], 1, f"what the {r['title']} role does")
    for ln in e.get("lanes") or []:
        put(cd.lane_label(ln), 1, f"the {cd.lane_label(ln)} lane")
    return out


def whose(J: Jobs, uid: str, text: Any) -> Dict[str, Any]:
    """Whose job `text` is: the top TOP of everyone ranked by their job's words,
    each with the words that matched and where, who is over them, and whether
    `uid` may hand them work; the fallback when nobody matches; everyone."""
    ch = J.ch
    want = terms(text)
    if not want:
        raise HTTPException(400, "Say what the work is, in a few words.")
    people = J.everyone()           # everyone ranked; the lines shown are capped by the caller
    scored = []
    for n, e in enumerate(people):
        bag = _bag(J, e)
        hits: Dict[str, Tuple[int, str]] = {}
        for said, st in want:
            best = max(((w, where) for s, w, where in bag if _hit(st, s)), default=None, key=lambda x: x[0])
            if best:
                hits[said] = best
        score = sum(w for w, _where in hits.values())
        if score:
            scored.append((score, len(hits), bool(e["row"]), -n, e, hits))
    scored.sort(key=lambda x: x[:4], reverse=True)
    me = co.who(co.LOGIN, uid)
    under = under_keys(ch, me)
    guarded = ch.guarded

    stem_of = dict(want)

    def about(e: Dict[str, Any], hits: Dict[str, Tuple[int, str]], why: str = "") -> Dict[str, Any]:
        where: Dict[str, List[str]] = {}
        for said, (_w, place) in hits.items():
            where.setdefault(place, []).append(said)
        mine_ = [stem_of[w] for w in where.get("their written job description", [])]
        return {"entry": e, "why": why, "matched": [{"words": ws, "where": place} for place, ws in where.items()],
                "lines": matched_lines((e["row"] or {}).get("description"), mine_) if mine_ else [],
                "over": [o["name"] for o in co.above(ch, e["who"])],
                "can_give": is_self(ch, uid, e) or co.key(e["who"]) in under,
                "pastor_or_elder": bool(e["contact_id"]) and e["contact_id"] in guarded}

    matches = [about(e, hits) for *_rank, e, hits in scored[:TOP]]
    fallback = None
    if not matches:
        fallback = _fallback(J, people, want)
        if fallback:
            fallback = about(fallback[0], {}, fallback[1])
    return {"work": _plain(text), "words": [w for w, _st in want], "matches": matches, "fallback": fallback,
            "people": people}


def _fallback(J: Jobs, people: List[Dict[str, Any]], want: List[Tuple[str, str]]
              ) -> Optional[Tuple[Dict[str, Any], str]]:
    """Nobody's job says it (not even a department's name: that is in its
    leader's and overseer's words, so they'd have ranked): whoever oversees the
    office's lanes; else the owner."""
    ch = J.ch
    over = [u for u in ch.office if ch.role(u) == "manager" and ch.over_lanes(u)]
    for u in over:
        e = next((x for x in people if x["user_id"] == u), None)
        if e:
            return e, "Nobody's job names it; they oversee the office's lanes, so it starts with them."
    e = next((x for x in people if x["user_id"] and x["user_id"] == ch.owner), None)
    return (e, "Nobody's job names it, and nobody oversees the office, so it's the owner's to place.") if e else None


SUNDAY_TIMES = ("The church fills in the times: when they arrive, what they do before, during and after each "
                "service, and when they leave.")


def picks_of(ch: co.Church, uid: Optional[str]) -> Dict[str, str]:
    """The days this login picked for its duties (church_duty_days), where the
    church's readers follow them (church_assignments.days_for's rule: the
    switch open for the church); a failed read is a 503."""
    if not uid or not co.church_open(ch.business):
        return {}
    import church_assignments as cas
    got = cas.picked_days(ch.b, [uid])
    if got is None:
        raise HTTPException(503, UNREAD)
    return got.get(uid, {})


def week_of(keys: List[str], picks: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """(their week as lines, by the day each duty falls on, as church_my_week
    places it with their picked day; their Sunday duties)."""
    import church_assignments as cas
    import church_duties as cd
    import church_my_week as week
    by: Dict[str, List[str]] = {}
    sunday: List[str] = []
    for k in keys:
        d = cd.CATALOG[k]
        picked = picks.get(k)
        group, days, said = week.placed(cas.day_with(d["day"], picked))
        label = d["label"] + (" (their pick)" if picked else "")
        if "Sun" in days and group != week.MONTH:
            sunday.append(d["label"])
        if group in week.WEEKDAYS:
            for dy in days:
                by.setdefault(dy, []).append(label)
        elif group == week.MONTH:
            when = said[len("Once a month, "):] if said.startswith("Once a month, ") else (
                "the first Monday" if "first Monday" in said else "")
            by.setdefault(week.MONTH, []).append(label + (f" ({when})" if when else ""))
        else:
            by.setdefault(group, []).append(label)
    names = {**week.DAY_NAMES, week.WEEK: "Each week, any day", week.MONTH: "Once a month",
             week.ANY_DAY: "Whenever it comes up"}
    order = [*week.WEEKDAYS, week.WEEK, week.MONTH, week.ANY_DAY]
    return [f"{names[g]}: {'; '.join(by[g])}" for g in order if by.get(g)], sunday


def draft(J: Jobs, e: Dict[str, Any]) -> Dict[str, Any]:
    """A starting description from what the system holds only, never their
    written words, in plain sections (headings on their own line, no marks the
    app would show raw): Summary, What they own, Their week, On Sunday. Nothing
    is saved."""
    import church_duties as cd
    ch = J.ch
    title = system_title(ch, e)
    up = e.get("answers_to_name") or _join(o["name"] for o in co.above(ch, e["who"]))
    summary = [f"{title}." + (f" Answers to {up}." if up else "")]
    if e["helps"]:
        summary.append("Supports, as the office: " + _join([f"{h['name']} ({h['duty']})" for h in e["helps"]]) + ".")
    if e["leads"]:
        summary.append(f"Leads {_join(e['leads'])}.")
    if e["oversees"]:
        summary.append(f"Oversees {_join(e['oversees'])}.")
    for r in e["roles"]:
        if r["definition"]:
            summary.append(f"{r['definition']}" + (f" ({r['scope']})" if r["scope"] else "") + ".")
    week_lines, sunday = week_of(e["own"], picks_of(ch, e["user_id"]) if e["own"] else {})

    def build(training: bool) -> str:
        own = [f"{cd.CATALOG[k]['label']}: {cd.CATALOG[k]['does']}" if training else cd.CATALOG[k]["label"]
               for k in e["own"]]
        if e["covers"]:
            own.append(f"Covers the office's lanes: {cd.PSEUDO_LANES[cd.EXEC]['does']}.")
        parts = [["Summary", *summary],
                 ["What they own", *(own or ["Nothing in the system names a duty for them yet."])],
                 ["Their week", *(week_lines or ["Nothing in the system puts them on a day yet."])],
                 ["On Sunday", ("; ".join(sunday) + ".") if sunday else "No Sunday duty in the system yet.",
                  SUNDAY_TIMES]]
        return "\n\n".join("\n".join(p) for p in parts)

    text = build(True)
    if len(text) > DESCRIPTION_MAX:                       # a long list: the duties without their training lines
        text = build(False)
    return {"for": e["key"], "name": e["name"], "title": title[:TITLE_MAX],
            "description": text[:DESCRIPTION_MAX].rstrip(), "source": "drafted", "written": bool(e["row"])}


# ─── The writes ───────────────────────────────────────────────────────

def _title(v: Any) -> Optional[str]:
    t = _plain(v)
    if len(t) > TITLE_MAX:
        raise HTTPException(400, f"A job title is {TITLE_MAX} characters at most; this one is {len(t)}.")
    return t or None


def _description(v: Any) -> str:
    d = str(v or "").replace("\r\n", "\n").replace("\r", "\n")
    d = "\n".join(ln.rstrip() for ln in d.split("\n")).strip()      # line breaks kept as written
    if not d:
        raise HTTPException(400, "Say what their job is: a job description can't be empty.")
    if len(d) > DESCRIPTION_MAX:
        raise HTTPException(400, f"A job description is {DESCRIPTION_MAX:,} characters at most; this one is "
                                 f"{len(d):,}.")
    return d


def has_pay(*texts: Any) -> bool:
    return any(PAY_WORDS.search(str(t or "")) for t in texts)


def _image(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return {k: row.get(k) for k in IMAGE} if row else None


def fresh(J: Jobs, e: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Their row as it is now (read again before any write): the person's,
    else the login's."""
    b = _q(J.ch.b)
    rows: List[Dict[str, Any]] = []
    if e["contact_id"]:
        rows = _need(f"/{TABLE}?business_id=eq.{b}&contact_id=eq.{_q(e['contact_id'])}&select={COLS}&limit=1")
    if not rows and e["user_id"]:
        rows = _need(f"/{TABLE}?business_id=eq.{b}&user_id=eq.{_q(e['user_id'])}&contact_id=is.null"
                     f"&select={COLS}&limit=1")
    return rows[0] if rows else None


def _log(J: Jobs, e: Dict[str, Any], before: Optional[Dict[str, Any]], after: Optional[Dict[str, Any]],
         by: str, at: str) -> Optional[str]:
    got = sb_clients.sb_post_as_service(f"/{LOG}", {
        "business_id": J.ch.b, "contact_id": e["contact_id"], "user_id": e["user_id"], "before": _image(before),
        "after": _image(after), "by": by, "at": at})
    if isinstance(got, list) and got and got[0].get("id"):
        return str(got[0]["id"])
    print(f"[church_job_descriptions] {J.ch.b[:8]}: a change saved but its log didn't; it can't be undone", flush=True)
    return None


def set_description(J: Jobs, uid: str, e: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    """Write (or, with clear: true, clear) one person's description, then log
    it. Whoever calls this checked can_write. A failed write is a 503 with
    nothing saved; a log that fails after a saved write leaves it without an
    undo (said: change_id None), never a 503 for a saved write."""
    b = J.ch.b
    old = fresh(J, e)
    at = _iso(_now())
    if body.get("clear") is True:
        if not old:
            raise HTTPException(400, f"{e['name']} has no written job description to clear.")
        if not sb_clients.sb_delete_as_service(f"/{TABLE}?id=eq.{_q(old['id'])}&business_id=eq.{_q(b)}"):
            raise HTTPException(503, UNSAVED)
        return {"saved": None, "before": old, "change_id": _log(J, e, old, None, uid, at), "cleared": True}
    title = _title(body["title"]) if "title" in body else (_plain((old or {}).get("title")) or None)
    text = _description(body.get("description"))
    source = str(body.get("source") or "said").strip().lower()
    if source not in SOURCES:
        raise HTTPException(400, "Where it came from is one of: said, pasted, document, drafted.")
    if has_pay(title, text):
        raise HTTPException(400, PAY)
    fields = {"title": title, "description": text, "source": source, "updated_by": uid, "updated_at": at}
    if old:
        if e["contact_id"] and not old.get("contact_id"):          # the login has a person now: it moves to them
            fields["contact_id"] = e["contact_id"]
        got = sb_clients.sb_patch_as_service(f"/{TABLE}?id=eq.{_q(old['id'])}&business_id=eq.{_q(b)}", fields)
    else:
        got = sb_clients.sb_post_as_service(f"/{TABLE}", {
            "business_id": b, "contact_id": e["contact_id"], "user_id": e["user_id"], "written_by": uid,
            "written_at": at, **fields})
    if not isinstance(got, list) or not got:
        raise HTTPException(503, UNSAVED)
    saved = got[0]
    return {"saved": saved, "before": old, "change_id": _log(J, e, old, saved, uid, at), "cleared": False}


def _same(row: Optional[Dict[str, Any]], image: Optional[Dict[str, Any]]) -> bool:
    if row is None or image is None:
        return row is None and image is None
    return (_plain(row.get("title")) == _plain(image.get("title"))
            and str(row.get("description") or "") == str(image.get("description") or ""))


def undo(J: Jobs, uid: str, e: Dict[str, Any], change_id: Any = None) -> Dict[str, Any]:
    """Put the last change to their description back, only the last: its
    `before` (with the earlier writer's name), or no description when there
    was none. Claimed first (undone_at), so two at once put it back once;
    let go if the put-back fails. Whoever calls this checked can_write."""
    b = _q(J.ch.b)
    seen: Dict[str, Dict[str, Any]] = {}
    if e["contact_id"]:
        for r in _need(f"/{LOG}?business_id=eq.{b}&contact_id=eq.{_q(e['contact_id'])}&select={LOG_COLS}"
                       "&order=at.desc&limit=1"):
            seen[str(r["id"])] = r
    if e["user_id"]:
        for r in _need(f"/{LOG}?business_id=eq.{b}&user_id=eq.{_q(e['user_id'])}&select={LOG_COLS}"
                       "&order=at.desc&limit=1"):
            seen[str(r["id"])] = r
    last = max(seen.values(), key=lambda r: str(r.get("at") or ""), default=None)
    if not last:
        raise HTTPException(400, f"There's no change to {e['name']}'s job description to put back.")
    if last.get("undone_at"):
        raise HTTPException(400, f"The last change to {e['name']}'s job description was already put back; only the "
                                 "last change can be.")
    if change_id and str(last["id"]) != str(change_id):
        raise HTTPException(409, f"{e['name']}'s job description changed again since, so that change can't be put "
                                 "back by itself; only the last change can be.")
    current = fresh(J, e)
    if not _same(current, last.get("after")):
        raise HTTPException(409, f"{e['name']}'s job description changed since, so nothing was put back.")
    at = _iso(_now())
    claimed = sb_clients.sb_patch_as_service(f"/{LOG}?id=eq.{_q(last['id'])}&business_id=eq.{b}&undone_at=is.null",
                                             {"undone_at": at})
    if not isinstance(claimed, list):
        raise HTTPException(503, UNSAVED)
    if not claimed:
        raise HTTPException(409, "That was just put back.")
    before = last.get("before")
    restored: Optional[Dict[str, Any]] = None
    if before is None:
        done = sb_clients.sb_delete_as_service(f"/{TABLE}?id=eq.{_q(current['id'])}&business_id=eq.{b}") \
            if current else True
    else:
        fields = {k: before.get(k) for k in IMAGE}
        got = sb_clients.sb_patch_as_service(f"/{TABLE}?id=eq.{_q(current['id'])}&business_id=eq.{b}", fields) \
            if current else sb_clients.sb_post_as_service(f"/{TABLE}", {
                "business_id": J.ch.b, "contact_id": e["contact_id"], "user_id": e["user_id"], **fields})
        done = isinstance(got, list) and bool(got)
        restored = got[0] if done else None
    if not done:
        sb_clients.sb_patch_as_service(f"/{LOG}?id=eq.{_q(last['id'])}&business_id=eq.{b}", {"undone_at": None})
        raise HTTPException(503, UNSAVED)
    return {"restored": restored, "before": before, "after": last.get("after"), "undone": str(last["id"])}


# ─── For people_under and one_on_one ──────────────────────────────────

def marks(ch: co.Church, targets: List[Dict[str, str]]) -> Optional[Dict[str, Dict[str, Any]]]:
    """{church_over key: {title, written}} for the people in an assignments
    read: their title from what the system holds (never someone's written
    words, so the read's taint stays as it was) and whether a description is
    written. None before the file is applied or on any failed read: the line
    is left out, never the read."""
    try:
        if ready() is not True:
            return None
        J = Jobs(ch)
        out: Dict[str, Dict[str, Any]] = {}
        for t in targets:
            e = J.entry(None, t["id"], full=False) if t["kind"] == co.LOGIN else J.entry(t["id"], None, full=False)
            out[co.key(t)] = {"title": system_title(ch, e), "written": bool(e["row"])}
        return out
    except HTTPException:
        return None
    except Exception as ex:  # noqa: BLE001 — the assignments read never fails on this
        print(f"[church_job_descriptions] marks unread: {type(ex).__name__}", flush=True)
        return None


# ─── The routes ───────────────────────────────────────────────────────

def _gate(session: UserSession, biz: Dict[str, Any]) -> Jobs:
    """A church (404), the switch (404), the file applied (503), a seat (403)."""
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, NOT_CHURCH)
    if not co.office_open(session.user, biz):
        raise HTTPException(404, "Not Found")
    s = ready()
    if s is not True:
        raise HTTPException(503, UNREAD if s is None else NOT_READY)
    ch = co.Church(biz)
    if ch.role(str(session.user.id)) not in SEATS:
        raise HTTPException(403, OFFICE_ONLY)
    return Jobs(ch)


def _gate_body(session: UserSession, body: Dict[str, Any]) -> Jobs:
    bid = _uuid((body or {}).get("business_id"), "church")
    business_access.assert_access(bid, session.user, "member")
    rows = _need(f"/businesses?id=eq.{_q(bid)}&select=id,name,type,owner_id,settings&limit=1")
    if not rows:
        raise HTTPException(404, "business not found")
    return _gate(session, rows[0])


def person(J: Jobs, contact_id: Any = None, user_id: Any = None) -> Dict[str, Any]:
    """The person a route names: one of the church's people, or one of its
    logins (the owner or an active seat); 404 for anyone else's."""
    if bool(contact_id) == bool(user_id):
        raise HTTPException(400, "Say who: a contact_id or a user_id.")
    ch = J.ch
    if contact_id:
        cid = _uuid(contact_id, "person")
        if not _need(f"/contacts?business_id=eq.{_q(ch.b)}&id=eq.{_q(cid)}&select=id&limit=1"):
            raise HTTPException(404, "That person isn't one of this church's people.")
        e = J.entry(cid, None)
    else:
        uid = _uuid(user_id, "login")
        if uid != ch.owner and uid not in ch.seats:
            raise HTTPException(404, "That login isn't one of this church's.")
        e = J.entry(None, uid)
    J.name([e])
    return e


def _readable(J: Jobs, uid: str, e: Dict[str, Any]) -> Set[str]:
    under = under_keys(J.ch, co.who(co.LOGIN, uid))
    if not can_read(J.ch, uid, e, under):
        raise HTTPException(403, NOT_YOURS)
    return under


def _writable(J: Jobs, uid: str, e: Dict[str, Any]) -> None:
    if not can_write(J.ch, uid, e, under_keys(J.ch, co.who(co.LOGIN, uid))):
        raise HTTPException(403, refusal(J, e))


def refusal(J: Jobs, e: Dict[str, Any]) -> str:
    """Why this login can't write their description, in the church's rule."""
    if e["contact_id"] and e["contact_id"] in J.ch.guarded:
        return (f"Only the owner, or whoever is over {e['name']} on the leaders map, writes their job description: "
                "no office seat is over a pastor or an elder.")
    return f"Only the owner, or someone over {e['name']}, writes their job description."


def _saved_view(J: Jobs, e: Dict[str, Any], got: Dict[str, Any]) -> Dict[str, Any]:
    e = {**e, "row": got.get("saved") or got.get("restored")}
    return view(J, e, full=True)          # one person's, as it was just saved: the whole of it


@router.get("/jobs")
def jobs_roster(business_id: str, session: UserSession = Depends(sb_clients.authed_request),
                biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """Everyone's job, one line each (the office seats, Manager and up)."""
    import church_map
    J = _gate(session, biz)
    if J.ch.role(str(session.user.id)) not in READ_ALL:
        raise HTTPException(403, ALL_ONLY)
    with church_map.once():
        return roster(J)


@router.get("/jobs/person")
def jobs_person(business_id: str, contact_id: Optional[str] = None, user_id: Optional[str] = None,
                session: UserSession = Depends(sb_clients.authed_request),
                biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """One person's whole job (the person, anyone over them, an office seat)."""
    import church_map
    J = _gate(session, biz)
    uid = str(session.user.id)
    with church_map.once():
        e = person(J, contact_id, user_id)
        under = _readable(J, uid, e)
        return job(J, uid, e, under)


@router.get("/jobs/whose")
def jobs_whose(business_id: str, q: str = "", session: UserSession = Depends(sb_clients.authed_request),
               biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """Whose job some work is (the office seats, Manager and up)."""
    import church_map
    J = _gate(session, biz)
    uid = str(session.user.id)
    if J.ch.role(uid) not in READ_ALL:
        raise HTTPException(403, ALL_ONLY)
    with church_map.once():
        got = whose(J, uid, q)
        pick = lambda m: {**{k: v for k, v in m.items() if k != "entry"}, "person": view(J, m["entry"])}  # noqa: E731
        return {"work": got["work"], "words": got["words"], "matches": [pick(m) for m in got["matches"]],
                "fallback": pick(got["fallback"]) if got["fallback"] else None,
                "people": [view(J, e) for e in got["people"][:ROSTER_MAX]],
                "more": max(0, len(got["people"]) - ROSTER_MAX)}


@router.get("/jobs/draft")
def jobs_draft(business_id: str, contact_id: Optional[str] = None, user_id: Optional[str] = None,
               session: UserSession = Depends(sb_clients.authed_request),
               biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """A starting description from what the system holds; nothing is saved."""
    import church_map
    J = _gate(session, biz)
    uid = str(session.user.id)
    with church_map.once():
        e = person(J, contact_id, user_id)
        _readable(J, uid, e)
        return draft(J, e)


@router.put("/jobs/person")
def jobs_set(body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """Write (or clear) one person's description: the owner, or someone over
    them. Answers with what it saved; a failed write is a 503."""
    import church_map
    J = _gate_body(session, body)
    uid = str(session.user.id)
    with church_map.once():
        e = person(J, body.get("contact_id"), body.get("user_id"))
        _writable(J, uid, e)
        got = set_description(J, uid, e, body)
        return {"saved": _saved_view(J, e, got), "cleared": got["cleared"], "change_id": got["change_id"],
                "can_undo": bool(got["change_id"])}


@router.post("/jobs/person/undo")
def jobs_undo(body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """Put the last change to one person's description back: the owner, or
    someone over them."""
    import church_map
    J = _gate_body(session, body)
    uid = str(session.user.id)
    with church_map.once():
        e = person(J, body.get("contact_id"), body.get("user_id"))
        _writable(J, uid, e)
        got = undo(J, uid, e, body.get("change_id"))
        return {"saved": _saved_view(J, e, got), "undone": got["undone"]}
