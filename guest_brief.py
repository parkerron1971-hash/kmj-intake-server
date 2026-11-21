"""guest_brief.py — Chief's call brief, and what Chief does after the call
(the Welcome Path, step 3).

Kevin, 2026-11-20, on the Welcome Path mock (canvas WmRiSK8seJky8pJUK5nztE,
boards "The caller's phone" and "The guest's phone"): "chief should be
sending a follow up call to the admin of people and care or a church should
be able to assign who should be over this ... top tier", then "build".

Chief never calls a guest. It hands the call to the person the church chose
(guest_calls.py), gets them ready, and keeps track until it's done.

THE BRIEF    brief(): for one guest's welcome follow-up, everything the caller
             needs on one phone screen, read from what the church already
             holds and nothing else (no AI call, nothing invented):
               who they are       name, first visit day, the door, who
                                  invited them (the card's "Who invited
                                  you?"), the kids (the card's names and
                                  ages, the member app's ages, or the kids
                                  desk's own children: first names and ages)
               what they asked    the card's "What would you like?" (group,
                                  serve, baptism, class, pastor: the member
                                  app's WANTS keys), the member app's, or a
                                  card's own answers that say so
               how to reach them  "Best way to reach you": a text instead
                                  makes Text the main button
               prayer             "They shared a prayer request; the pastors
                                  have it." Never its words: this module
                                  never reads a prayer request, only the
                                  card's yes/no
               the texts          New here's texts for this visit (sent,
                                  skipped, waiting) and what's next
               an opening line    in the church's and the caller's names
               worth mentioning   for each thing they asked for, the
                                  church's REAL matching thing: groups taking
                                  new people with their day and time (and
                                  who leads them), serving teams, classes
                                  open to join, who takes baptism and who
                                  talks with a guest who asks for a pastor.
                                  A line is left out when the church has
                                  nothing for it
             GET /church/guests/{business_id}/brief/{follow_up_id}: the
             follow-up's caller (an office login through its person record,
             guest_calls' way), anyone who sees the Guests room
             (church_guests' gate), the owner and the admins. A member
             caller reads the same brief on their Lead tab
             (member_portal_lead).

HOW DID IT GO  two taps (Talked, Left a message, No answer, Not right now)
             and an optional note, through the follow-up's existing note
             endpoints (the office's POST /church/follow-ups/{id}/note with
             `outcome`, the member page's POST /my/lead/note). The brief says
             beforehand what Chief will do for each (`outcomes`, `asks`);
             after_call() does it:
               Talked     each thing they asked for gets its person through
                          church_follow_up's own streams, each a normal
                          follow-up (card_key "call:<what>") with the note
                          "Asked for on their welcome call":
                            serve    the team they'd like (picked on the
                                     call) to its leader (choose())
                            baptism  the role that takes baptism (choose())
                            pastor   pastor_ask (choose())
                            group    the group picked on the call, to its
                                     leader when the leader holds a role
                                     (the Lead tab needs one); else a note
                                     to People & Care
                            class    a note to People & Care
                          Anything with no team or group picked is a note to
                          People & Care. "Leave it" skips one. Nothing is
                          handed twice: each ask is noted on the guest's
                          follow-up once, a hand-off's source_event is
                          unique, and one already open for them is left
                          where it is.
               Left a message, No answer, Not right now: nothing is handed on
             New here's Thursday invite is kept unless they've been back
             (New here skips it then, at send time, by its own rule).

Everything is behind guest_path.switched_on(biz); off, there is no brief and
a call's note is the note it always was.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

import church_follow_up as cfu
import guest_path
import sb_clients
from auth_supabase import UserSession
from business_access import business_access

router = APIRouter(prefix="/church", tags=["church"])

MIN_ROLE = "manager"                    # an office login: the owner, an Admin or a Manager seat
ASK_ORDER = ("group", "serve", "baptism", "class", "pastor")
LABELS = {"group": "Find a group", "serve": "Serve", "baptism": "Get baptized",
          "class": "Take a class", "pastor": "Talk with a pastor"}
WORDS = {"group": "find a group", "serve": "serve", "baptism": "get baptized",
         "class": "take a class", "pastor": "talk with a pastor"}
WANTS_CHIP = {"group": "Wants a group", "serve": "Wants to serve", "baptism": "Wants baptism",
              "class": "Wants a class", "pastor": "Wants a pastor"}
ASKED = "Asked for on their welcome call"
CALL_KEY = "call:"                      # church_follow_ups.card_key of a hand-off from a call
SKIP = "skip"
MAX_GROUPS = 3
MAX_TEAMS = 6
MAX_CLASSES = 2
OUTCOME_ORDER = ("talked", "message", "noanswer", "notnow")
TEXT_WORDS = {"welcome": "Welcome text", "thanks": "Thank-you text", "monday": "Monday note",
              "invite": "Invite back"}
SENT_WINDOW = timedelta(minutes=10)
OTHERS_DAYS = 7
UNREAD = "The brief couldn’t be read just now. Try again."
_WANT_Q = re.compile(r"interest|like to|would you like|next step|want|how can we|help you", re.I)
_WANT_A = (("baptism", re.compile(r"bapti", re.I)),
           ("serve", re.compile(r"\bserv|volunteer|\bteam\b", re.I)),
           ("group", re.compile(r"\bgroups?\b|small group|bible study", re.I)),
           ("class", re.compile(r"\bclass|course|membership|learn", re.I)),
           ("pastor", re.compile(r"pastor|pastoral", re.I)))
_INVITED_Q = re.compile(r"invit|brought you|who brought|came with", re.I)


class Unread(Exception):
    """A read the brief can't do without didn't answer."""


# ─── Small helpers ────────────────────────────────────────────────────

def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _plain(v: Any) -> str:
    return " ".join(str(v or "").split())


def _parse(v: Any) -> Optional[datetime]:
    return cfu._parse(v)


def _uuid(v: Any) -> str:
    try:
        return str(uuid.UUID(str(v)))
    except (TypeError, ValueError):
        raise HTTPException(404, "Not Found")


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def _need(path: str) -> List[Dict[str, Any]]:
    rows = _rows(path)
    if rows is None:
        raise Unread(path.split("?")[0])
    return rows


def _first(name: Any) -> str:
    return (_plain(name).split(" ") or [""])[0]


def _nameless(name: Any) -> bool:
    try:
        import text_room
        return text_room.nameless(name)
    except Exception:  # noqa: BLE001
        return not _plain(name)


def _and(items: List[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def short_church(name: Any) -> str:
    """"Grace Hill Church" -> "Grace Hill", the way a caller says it. A name
    that is only "Church", or that doesn't end with it, stays as it is."""
    n = _plain(name)
    m = re.match(r"^(.+?)\s+church$", n, re.I)
    return m.group(1) if m and m.group(1) else (n or "the church")


def _tz(business: Dict[str, Any]):
    import new_here
    return new_here.tz_of(business)


def _clock(local: datetime) -> str:
    hour = local.strftime("%I").lstrip("0") or "12"
    return f"{hour}:{local.minute:02d} {local.strftime('%p')}" if local.minute else f"{hour} {local.strftime('%p')}"


def day_word(t: datetime, tz: Any, now: datetime) -> str:
    """"today", "yesterday", "Sunday" (this past week), else "Nov 3"."""
    d, today = t.astimezone(tz).date(), now.astimezone(tz).date()
    if d == today:
        return "today"
    if d == today - timedelta(days=1):
        return "yesterday"
    if today - timedelta(days=6) <= d < today:
        return t.astimezone(tz).strftime("%A")
    if today < d <= today + timedelta(days=6):
        return t.astimezone(tz).strftime("%A")
    local = t.astimezone(tz)
    return f"{local.strftime('%b')} {local.day}"


def when_words(t: datetime, tz: Any, now: datetime) -> str:
    """"Sunday 11:05 AM", "today 2:05 PM", "Mon 10 AM"."""
    local = t.astimezone(tz)
    return f"{day_word(t, tz, now)} {_clock(local)}"


def _age(birthdate: Any, today) -> Optional[int]:
    try:
        from datetime import date
        b = date.fromisoformat(str(birthdate)[:10])
    except (TypeError, ValueError):
        return None
    years = today.year - b.year - ((today.month, today.day) < (b.month, b.day))
    return years if 0 <= years < 19 else None


# ─── What the guest told the church ───────────────────────────────────

def told(contact: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
    """{wants, reach, invited, kids_names, kids_count, ages, prayer,
    first_time} from the guest's own words: New here's card
    (metadata.new_here.card), the member app's "I'm new here"
    (metadata.new_here.app), and the follow-up's answers. Pure."""
    meta = guest_path.guest_meta(contact)
    card = meta.get("card") if isinstance(meta.get("card"), dict) else {}
    app = meta.get("app") if isinstance(meta.get("app"), dict) else {}
    answers = [a for a in (row.get("answers") or []) if isinstance(a, dict)]
    wants: List[str] = []
    for src in (card.get("wants"), app.get("wants")):
        for k in src or []:
            if k in LABELS and k not in wants:
                wants.append(str(k))
    for a in answers:
        q, said = str(a.get("q") or ""), str(a.get("a") or "")
        if q.startswith(ASKED):
            continue
        hits = [k for k, rx in _WANT_A if rx.search(said)] if _WANT_Q.search(q) else []
        if cfu._PASTOR_ASK.search(cfu._norm(said)):
            hits.append("pastor")
        for k in hits:
            if k not in wants:
                wants.append(k)
    reach = card.get("reach") if card.get("reach") in ("call", "text") else (
        app.get("reach") if app.get("reach") in ("call", "text") else None)
    invited = _plain(card.get("invited_by") or app.get("invited"))[:120]
    if not invited:
        invited = next((_plain(a.get("a"))[:120] for a in answers if _INVITED_Q.search(str(a.get("q") or ""))
                        and _plain(a.get("a")) and _plain(a.get("a")).lower() not in ("no", "none", "no one")), "")
    kids_names = _plain(card.get("kids_names"))[:200]
    kids_count = str(card.get("kids") or "")
    ages = _plain(app.get("ages"))[:60] if app.get("kids") == "yes" else ""
    has_kids_app = app.get("kids") == "yes"
    first_check = ""
    for a in answers:
        for part in str(a.get("a") or "").split(" · "):
            if "checked in" in part and re.search(r"\d", part):
                first_check = _plain(part)[:60]
    return {
        "wants": [k for k in ASK_ORDER if k in wants],
        "reach": reach, "invited": invited, "kids_names": kids_names,
        "kids_count": kids_count if kids_count in ("1", "2", "3 or more") else "",
        "ages": ages, "kids_app": has_kids_app, "kids_checked": first_check,
        "prayer": bool(card.get("prayer") or app.get("prayer")),
        "first_time": card.get("first_time") if "first_time" in card else app.get("first_time"),
    }


# ─── The church's real things ─────────────────────────────────────────

def _group_when(g: Dict[str, Any]) -> str:
    """"Wednesdays at 7 PM", "every other Thursday at 6:30 PM", the first
    Tuesday of the month, else the church's own words (groups.meets)."""
    try:
        import group_gatherings as gg
        t = gg._time(g)
        if gg.scheduled(g) and t is not None:
            day = gg.DAYS[int(g["meet_day"])]
            clock = _clock(datetime.combine(datetime(2026, 1, 1).date(), t))
            every = int(g.get("meet_every") or 1)
            if every == gg.MONTHLY:
                nth = gg.NTH[min(max(int(g.get("meet_nth") or 1), 1), 5) - 1].lower()
                return f"the {nth} {day} of the month at {clock}"
            if every == 2:
                return f"every other {day} at {clock}"
            return f"{day}s at {clock}"
    except Exception:  # noqa: BLE001 — the church's own words below
        pass
    return _plain(g.get("meets"))[:80]


class Church:
    """One church's real things for one brief, each read once, on demand."""

    def __init__(self, business: Dict[str, Any]):
        self.business = business
        self.b = str(business["id"])
        self._memo: Dict[str, Any] = {}

    def _got(self, name: str, fn):
        if name not in self._memo:
            try:
                self._memo[name] = fn()
            except Unread:
                self._memo[name] = None
        return self._memo[name]

    @property
    def routing(self) -> Optional[Tuple[list, dict, list, Any]]:
        """(roles, load, defs, map) for choose(); None when unread."""
        def load():
            import church_map
            import church_roles as cr
            got = (cfu.roles(self.b), cfu._load(self.b), cr.defs(self.b), church_map.opened(self.b))
            if any(x is None for x in got):
                raise Unread("roles")
            return got
        return self._got("routing", load)

    def pick(self, kind: str, answers: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        """choose()'s pick for a hand-off; None when the roles are unread."""
        r = self.routing
        if r is None:
            return None
        roles, load, defs, mp = r
        return cfu.choose(kind, answers, roles, load, defs, m=mp)

    def title_of(self, role: str) -> str:
        r = self.routing
        if r is None or not role:
            return ""
        import church_roles as cr
        return cr.title_of(role, cfu._effective_defs(r[2], r[0])) or ""

    @property
    def groups(self) -> Optional[List[Dict[str, Any]]]:
        """Groups taking new people (the group finder's rule: active, not by
        invitation, not a youth group, not a serving team), each with its
        leaders' names and whether one holds a role."""
        def load():
            import member_portal_church as mpc
            rows = _need(f"/groups?business_id=eq.{_q(self.b)}&active=eq.true"
                         "&select=id,name,kind,meets,meet_day,meet_time,meet_every,meet_nth,location,open_to_join,"
                         "join_mode,youth&order=name.asc&limit=200")
            rows = [g for g in rows if _plain(g.get("name")) and g.get("kind") != "team" and not g.get("youth")
                    and mpc.join_mode(g) != "invite"]
            if not rows:
                return []
            ids = [str(g["id"]) for g in rows]
            leads = _need(f"/group_members?business_id=eq.{_q(self.b)}&role=eq.leader"
                          f"&group_id=in.({','.join(_q(i) for i in ids)})&select=group_id,contact_id&limit=1000")
            people = sorted({str(m["contact_id"]) for m in leads if m.get("contact_id")})
            names = {}
            if people:
                names = {str(c["id"]): _plain(c.get("name")) for c in _need(
                    f"/contacts?business_id=eq.{_q(self.b)}&id=in.({','.join(_q(i) for i in people)})&select=id,name")}
            r = self.routing
            if r is None:
                raise Unread("roles")       # whether a leader holds a role decides the hand-off
            held = {str(h["contact_id"]): str(h.get("role") or "") for h in r[0] if h.get("status") == "active"}
            out = []
            for g in rows:
                mine = [str(m["contact_id"]) for m in leads if str(m.get("group_id")) == str(g["id"])]
                mine = [c for c in mine if names.get(c)]
                ok = next((c for c in mine if c in held), None)
                out.append({"id": str(g["id"]), "name": _plain(g["name"])[:80], "when": _group_when(g),
                            "leaders": [names[c] for c in mine],
                            "lead": ({"contact_id": ok, "name": names[ok], "role": held[ok]} if ok else None)})
            # Groups with a time first: a caller can say when.
            out.sort(key=lambda g: (not g["when"], g["name"].casefold()))
            return out
        return self._got("groups", load)

    @property
    def teams(self) -> Optional[List[str]]:
        """The teams a Serve card offers and the teams a team leader's role
        names: what choose() hands a serving step through."""
        def load():
            names = cfu.teams(self.b)
            if names is None:
                raise Unread("teams")
            out = list(names)
            r = self.routing
            for h in (r[0] if r else []):
                s = _plain(h.get("scope"))
                if h.get("status") == "active" and s and s not in out:
                    out.append(s)
            return out
        return self._got("teams", load)

    @property
    def classes(self) -> Optional[List[str]]:
        def load():
            import academy_join
            rows = _need(f"/academy_courses?business_id=eq.{_q(self.b)}&status=eq.published"
                         "&select=id,title,status,self_join,product_id,private&order=title.asc&limit=50")
            return [_plain(c.get("title"))[:80] for c in rows if academy_join.join_open(c) and _plain(c.get("title"))]
        return self._got("classes", load)

    @property
    def people_care(self) -> Optional[Dict[str, Any]]:
        """Whoever does First-time guests (guest_calls' way): {uid,
        contact_id, name}, or None when nobody does or it can't be read."""
        def load():
            import guest_calls
            ch = guest_calls._church(self.business)
            uid = guest_calls.first_guests_login(ch, guest_calls.guest_load(self.b))
            if not uid:
                return None
            cid = guest_calls.person_for_login(ch, uid, create=False)
            return {"uid": uid, "contact_id": cid, "name": ch.login_name(uid), "ch": ch}
        try:
            return self._got("people_care", load)
        except Exception:  # noqa: BLE001 — a 503 inside: nobody named, the note still goes
            self._memo["people_care"] = None
            return None


# ─── What Chief would do with each ask ────────────────────────────────

def _team_answers(team: str) -> List[Dict[str, str]]:
    return [{"q": "Team they'd like to serve on", "a": team}]


def _with(name: str, title: str) -> str:
    return f"{name} ({title})" if title else name


def _plan(ch: Church, key: str, pick: str, first: str, caller_cid: str) -> Dict[str, Any]:
    """What Talked does with one ask, given the caller's pick: {how:
    follow_up | note | skip | unread, line, kind, answers, card_name, pick
    (choose's pick or a decided leader), what}. Pure over the church's
    reads."""
    label = LABELS[key]
    if pick == SKIP:
        return {"how": "skip", "line": f"Leave “{label}” for now"}
    pc = ch.people_care

    def note(what: str) -> Dict[str, Any]:
        if pc and pc.get("contact_id") and pc["contact_id"] == caller_cid:
            line = f"Note on {first}’s follow-up that they’d like to {what}"
        elif pc:
            line = f"Tell People & Care ({pc['name']}) {first} would like to {what}"
        else:
            line = f"Note for People & Care that {first} would like to {what}"
        return {"how": "note", "what": what, "line": line}
    if key == "group":
        groups = ch.groups
        if pick and groups is None:
            return {"how": "unread", "line": f"Hand {first}’s group step to the group’s leader"}
        g = next((x for x in groups or [] if x["id"] == pick), None) if pick else None
        if not g:
            return note("find a group")
        if g["lead"]:
            return {"how": "follow_up", "kind": "general", "what": f"try {g['name']}",
                    "answers": [{"q": ASKED, "a": f"Find a group: {g['name']}"}],
                    "decided": {"leader": {"contact_id": g["lead"]["contact_id"], "name": g["lead"]["name"]},
                                "role": g["lead"]["role"],
                                "reason": f"{first} asked on their welcome call to try {g['name']}, and "
                                          f"{_first(g['lead']['name'])} leads it."},
                    "line": f"Hand {first}’s group step to {g['lead']['name']}, who leads {g['name']}"}
        return note(f"try {g['name']}")
    if key == "serve":
        if pick and ch.teams is None:
            return {"how": "unread", "line": f"Hand {first}’s step to serve on {pick} to its leader"}
        teams = ch.teams or []
        team = next((t for t in teams if t == pick), "") if pick else ""
        if not team:
            return note("serve")
        answers = [{"q": ASKED, "a": f"Serve: {team}"}] + _team_answers(team)
        p = ch.pick("serve", _team_answers(team))
        if p is None:
            return {"how": "unread", "line": f"Hand {first}’s step to serve on {team} to its leader"}
        lead = p.get("leader")
        line = (f"Hand {first}’s step to serve on {team} to {_with(lead.get('name') or 'its leader', ch.title_of(p.get('role') or ''))}"
                if lead else f"Hand {first}’s step to serve on {team} to the office: {team} has no leader yet")
        return {"how": "follow_up", "kind": "serve", "answers": answers, "line": line, "what": f"serve on {team}"}
    if key == "class":
        classes = ch.classes or []
        return note(f"take {classes[0]}" if len(classes) == 1 else "take a class")
    if key == "baptism":
        answers = [{"q": ASKED, "a": LABELS[key]}]
        p = ch.pick("baptism", answers)
        if p is None:
            return {"how": "unread", "line": f"Hand {first}’s baptism step to whoever takes baptism"}
        lead = p.get("leader")
        line = (f"Hand {first}’s baptism step to {_with(lead.get('name') or 'them', ch.title_of(p.get('role') or ''))}"
                if lead else f"Hand {first}’s baptism step to the office: no one takes baptism yet")
        return {"how": "follow_up", "kind": "baptism", "answers": answers, "line": line, "what": "get baptized"}
    # pastor: the pastor_ask stream (its own words say so).
    answers = [{"q": ASKED, "a": LABELS["pastor"]}]
    p = ch.pick("general", answers)
    if p is None:
        return {"how": "unread", "line": f"Hand {first}’s ask for a pastor to a pastor"}
    lead = p.get("leader")
    line = (f"Hand {first}’s ask to talk with a pastor to {_with(lead.get('name') or 'a pastor', ch.title_of(p.get('role') or ''))}"
            if lead else f"Hand {first}’s ask to talk with a pastor to the office: no pastor is named yet")
    return {"how": "follow_up", "kind": "general", "answers": answers, "line": line, "what": "talk with a pastor"}


def _done_before(key: str, notes: List[Dict[str, Any]], theirs: List[Dict[str, Any]],
                 names: Dict[str, str], fid: str) -> Optional[str]:
    """Why this ask is already taken care of, in the line's words, or None:
    asked on this call before (Chief's note), or a hand-off already open
    for them (a welcome call's, or their own Baptism or Serve card)."""
    label = LABELS[key]
    if any(str(n.get("body") or "").startswith(f"{ASKED}: {label}.") for n in notes):
        return f"“{label}” was already handed on from this call"
    for r in theirs:
        if str(r.get("id")) == fid or r.get("status") not in ("open", "handed_back"):
            continue
        ck, kind = str(r.get("card_key") or ""), str(r.get("path_kind") or "")
        if ck == f"{CALL_KEY}{key}" or (key in ("baptism", "serve") and kind == key and not ck.startswith(CALL_KEY)
                                        and not guest_path.is_guest_follow_up(r)):
            who = names.get(str(r.get("leader_contact_id") or ""), "")
            return f"Already with {who}: “{label}”" if who else f"Already with the office: “{label}”"
    return None


def asks_for(ch: Church, row: Dict[str, Any], wants: List[str], first: str, notes: List[Dict[str, Any]],
             theirs: List[Dict[str, Any]], names: Dict[str, str]) -> List[Dict[str, Any]]:
    """Each thing they asked for, what Talked will do with it, and the
    choices a caller can make on the call (the group, the team, or leave
    it)."""
    caller = str(row.get("leader_contact_id") or "")
    out = []
    for key in wants:
        done = _done_before(key, notes, theirs, names, str(row["id"]))
        item: Dict[str, Any] = {"key": key, "label": LABELS[key], "done": bool(done), "choices": [], "pick": ""}
        if done:
            item["line"] = done
            out.append(item)
            continue
        if key == "group":
            for g in (ch.groups or [])[:6]:
                item["choices"].append({"id": g["id"], "label": g["name"] + (f" · {g['when']}" if g["when"] else ""),
                                        "line": _plan(ch, key, g["id"], first, caller)["line"]})
        if key == "serve":
            for t in (ch.teams or [])[:MAX_TEAMS]:
                item["choices"].append({"id": t, "label": t, "line": _plan(ch, key, t, first, caller)["line"]})
        item["line"] = _plan(ch, key, "", first, caller)["line"]
        item["skip_line"] = f"Leave “{LABELS[key]}” for now"
        # The church has one group (or one team) for it: that one is the
        # caller's pick until they change it.
        if len(item["choices"]) == 1:
            item["pick"] = item["choices"][0]["id"]
        out.append(item)
    return out


def mentions_for(ch: Church, wants: List[str]) -> List[Dict[str, str]]:
    """Worth mentioning: the church's real thing for each ask, or no line."""
    out: List[Dict[str, str]] = []
    for key in wants:
        if key == "group":
            for g in (ch.groups or [])[:MAX_GROUPS]:
                said = f"{g['name']} meets {g['when']}." if g["when"] else f"{g['name']} takes new people."
                if g["leaders"]:
                    said += f" {_and(g['leaders'][:2])} {'leads' if len(g['leaders'][:2]) == 1 else 'lead'} it."
                out.append({"key": key, "line": said})
        elif key == "serve":
            teams = (ch.teams or [])[:4]
            if teams:
                out.append({"key": key, "line": f"Teams to serve on: {_and(teams)}."})
        elif key == "class":
            classes = (ch.classes or [])[:MAX_CLASSES]
            if classes:
                out.append({"key": key, "line": f"Open to join now: {_and(classes)}."})
        elif key in ("baptism", "pastor"):
            p = ch.pick("baptism" if key == "baptism" else "general", [{"q": ASKED, "a": LABELS[key]}])
            lead = (p or {}).get("leader")
            if lead and lead.get("name"):
                who = _with(lead["name"], ch.title_of(p.get("role") or ""))
                out.append({"key": key, "line": f"Baptism goes to {who}." if key == "baptism"
                            else f"A pastor to talk with: {who}."})
    return out


# ─── New here's texts for this visit ──────────────────────────────────

def texts_for(business: Dict[str, Any], contact: Dict[str, Any], start: Optional[datetime], tz: Any,
              now: datetime) -> Dict[str, Any]:
    """{ok, note, steps: [{step, label, state, at, when}], next}: what the
    church texted on this path and what's next. A read that fails is
    {unread: true}, never "nothing sent"."""
    import church_guests as cg
    meta = guest_path.guest_meta(contact)
    ok = cg.texts_ok(meta)
    biz, cid = str(business["id"]), str(contact["id"])
    out: Dict[str, Any] = {"ok": ok, "steps": [], "next": None, "note": "", "unread": False}
    if not ok:
        try:
            import new_here
            why = new_here.WHY_NOT.get(str(meta.get("texts") or ""), "")
        except Exception:  # noqa: BLE001
            why = ""
        out["note"] = (f"The church hasn’t texted them: {why[0].lower() + why[1:]}." if why
                       else "The church hasn’t texted them: they didn’t say yes to texts.")
        return out
    rows = _rows(f"/chief_scheduled_actions?business_id=eq.{_q(biz)}&action->>type=eq.new_here_text"
                 f"&action->>contact_id=eq.{_q(cid)}&select=id,action,run_at,status,last_run_at&limit=50")
    since = (start or now) - timedelta(days=1)
    msgs = _rows(f"/sms_messages?business_id=eq.{_q(biz)}&contact_id=eq.{_q(cid)}&direction=eq.outbound"
                 f"&created_at=gte.{_q(cg._iso(since))}&select=id,created_at&limit=200")
    if rows is None:
        out["unread"] = True
        return out
    outbound = None if msgs is None else [t for t in (_parse(m.get("created_at")) for m in msgs) if t]
    mine = [r for r in rows if (_parse(r.get("run_at")) or now) >= since]
    by_step: Dict[str, Dict[str, Any]] = {}
    for r in sorted(mine, key=lambda r: str(r.get("run_at") or "")):
        by_step[str((r.get("action") or {}).get("step") or "")] = r
    door = str(meta.get("door") or "text")
    steps = []
    if door == "text" and "welcome" not in by_step and meta.get("texted_at"):
        t = _parse(meta.get("texted_at"))
        if t:
            steps.append({"step": "welcome", "state": "done", "at": t})
    for step in ("welcome", "thanks", "monday", "invite"):
        r = by_step.get(step)
        if not r:
            continue
        state, at = cg._text_state(r, outbound)
        when = _parse(at) or _parse(r.get("run_at"))
        steps.append({"step": step, "state": state, "at": when})
    steps.sort(key=lambda s: s["at"] or now)
    for s in steps:
        s["label"] = TEXT_WORDS.get(s["step"], s["step"])
        s["when"] = when_words(s["at"], tz, now) if s["at"] else ""
        s["at"] = s["at"].astimezone(timezone.utc).isoformat() if s["at"] else None
    out["steps"] = steps
    nxt = next((s for s in steps if s["state"] == "waiting"), None)
    out["next"] = {"label": nxt["label"], "when": nxt["when"]} if nxt else None
    return out


# ─── The brief ────────────────────────────────────────────────────────

def _one(biz: str, fid: str) -> Dict[str, Any]:
    rows = _rows(f"/church_follow_ups?id=eq.{_q(fid)}&business_id=eq.{_q(biz)}&select=*&limit=1")
    if rows is None:
        raise HTTPException(503, UNREAD)
    if not rows:
        raise HTTPException(404, "Not Found")
    return rows[0]


def _kids(ch: Church, contact: Dict[str, Any], t: Dict[str, Any], start: Optional[datetime], tz: Any,
          now: datetime) -> Dict[str, Any]:
    """{line, chip, sentence, count}: the card's names, the member app's
    ages, or the kids desk's own children (first names and ages)."""
    b, cid = ch.b, str(contact["id"])
    homes = _need(f"/household_adults?business_id=eq.{_q(b)}&contact_id=eq.{_q(cid)}&select=household_id&limit=10")
    kids: List[Dict[str, Any]] = []
    came = False
    if homes:
        hids = ",".join(_q(h["household_id"]) for h in homes)
        kids = [k for k in _need(f"/children?business_id=eq.{_q(b)}&household_id=in.({hids})&active=eq.true"
                                 "&select=id,first_name,birthdate&order=birthdate.asc&limit=12")
                if _plain(k.get("first_name"))]
        if kids and start:
            since = cfu._iso(start - timedelta(hours=12))
            came = bool(_need(f"/child_checkins?business_id=eq.{_q(b)}&household_id=in.({hids})"
                              f"&checked_in_at=gte.{_q(since)}&select=id&limit=1"))
    today = now.astimezone(tz).date()
    if kids:
        named = []
        for k in kids:
            age = _age(k.get("birthdate"), today)
            named.append(f"{_plain(k['first_name']).split(' ')[0]}" + (f" ({age})" if age is not None else ""))
        line = _and(named)
        n = len(kids)
        return {"line": line, "count": n, "chip": f"{n} {'kid' if n == 1 else 'kids'}",
                "sentence": f"{line} {'was' if n == 1 else 'were'} in Kids." if came else f"Their kids: {line}."}
    if t["kids_names"]:
        n = {"1": 1, "2": 2}.get(t["kids_count"])
        return {"line": t["kids_names"], "count": n, "chip": f"{t['kids_count']} kids" if t["kids_count"] not in ("", "1")
                else ("1 kid" if t["kids_count"] == "1" else "Kids"), "sentence": f"Their kids: {t['kids_names']}."}
    if t["kids_app"]:
        return {"line": f"ages {t['ages']}" if t["ages"] else "", "count": None, "chip": "Kids",
                "sentence": f"They have kids, ages {t['ages']}." if t["ages"] else "They have kids."}
    if t["kids_count"]:
        n = t["kids_count"]
        return {"line": "", "count": {"1": 1, "2": 2}.get(n), "chip": "1 kid" if n == "1" else f"{n} kids",
                "sentence": f"{'1 kid' if n == '1' else n + ' kids'} with them."}
    if t["kids_checked"]:
        return {"line": "", "count": None, "chip": t["kids_checked"].replace(" checked in", ""),
                "sentence": f"{t['kids_checked'][0].upper()}{t['kids_checked'][1:]}."}
    return {}


def _opening(first: str, caller: str, church: str, kids: bool, start: Optional[datetime], tz: Any, now: datetime,
             *, planned: bool, app: bool) -> str:
    hi = f"Hi {first}," if first else "Hi,"
    who = f" this is {caller} from {church}." if caller else f" I’m calling from {church}."
    if planned:
        return f"{hi}{who} I saw you’re planning to visit, and I just wanted to say we can’t wait to meet you."
    if app:
        return f"{hi}{who} Thank you for telling us you’re new. I just wanted to say we’re so glad you’re here."
    day = day_word(start, tz, now) if start else ""
    when = "today" if day == "today" else ("yesterday" if day == "yesterday" else
                                           (day if day and day[0].isupper() and " " not in day else ""))
    loved = f" We loved having you{' and the kids' if kids else ''}{(' ' + when) if when else ''}."
    return f"{hi}{who}{loved} I just wanted to say thank you for coming."


def brief(business: Dict[str, Any], row: Dict[str, Any], *, viewer_cid: str = "",
          now: Optional[datetime] = None) -> Dict[str, Any]:
    """The call brief for one guest's welcome follow-up (see the top)."""
    now = now or _now()
    biz = str(business["id"])
    tz = _tz(business)
    ch = Church(business)
    cid = str(row["contact_id"])
    people = _rows(f"/contacts?business_id=eq.{_q(biz)}&id=eq.{_q(cid)}"
                   "&select=id,name,phone,email,metadata,created_at&limit=1")
    if people is None:
        raise HTTPException(503, UNREAD)
    if not people:
        raise HTTPException(404, "Not Found")
    contact = people[0]
    meta = guest_path.guest_meta(contact)
    name = "" if _nameless(contact.get("name")) else _plain(contact.get("name"))
    first = _first(name)
    t = told(contact, row)
    lid = str(row.get("leader_contact_id") or "")
    theirs = _rows(f"/church_follow_ups?business_id=eq.{_q(biz)}&contact_id=eq.{_q(cid)}"
                   "&select=id,card_key,path_kind,status,leader_contact_id,source_event&limit=50")
    notes = _rows(f"/church_follow_up_notes?business_id=eq.{_q(biz)}&follow_up_id=eq.{_q(row['id'])}"
                  "&author_kind=eq.chief&select=id,kind,body,created_at&limit=200")
    if theirs is None or notes is None:
        raise HTTPException(503, UNREAD)
    ids = {lid, viewer_cid} | {str(r.get("leader_contact_id") or "") for r in theirs}
    ids.discard("")
    names = {str(c["id"]): _plain(c.get("name")) for c in _need(
        f"/contacts?business_id=eq.{_q(biz)}&id=in.({','.join(_q(i) for i in sorted(ids))})&select=id,name")
    } if ids else {}
    caller_name = names.get(lid, "")
    start = _parse(meta.get("texted_at")) or _parse(row.get("created_at"))
    door = str(meta.get("door") or "")
    if door not in guest_path.DOORS:
        import guest_calls
        door = guest_calls.door_for(str(row.get("card_key") or ""), contact)
    door_words = guest_path.door_words(door)
    if door == "form":
        door_words = _plain(row.get("card_name"))[:40] or door_words
    planned = str(row.get("path_kind") or "") == "visit"
    app = door == "app"
    kids = _kids(ch, contact, t, start, tz, now)
    church = short_church(business.get("name"))
    call_as = _first(caller_name) or _first(names.get(viewer_cid, ""))
    who = first or "They"

    # Who they are.
    if planned:
        visit = f"Planning a visit · sent the card {day_word(start, tz, now)}" if start else "Planning a visit"
    elif app:
        visit = f"Told the church in the member app {day_word(start, tz, now)}" if start else "Told the church in the member app"
    else:
        visit = (f"First visit {day_word(start, tz, now)}, {_clock(start.astimezone(tz))}" if start else "First visit")
    if t["invited"]:
        visit += f" · invited by {_first(t['invited']) if len(t['invited'].split()) > 1 else t['invited']}"

    # Chief's brief, in sentences.
    said: List[str] = []
    if t["invited"]:
        said.append(f"{t['invited']} invited {first or 'them'}.")
    if kids.get("sentence"):
        said.append(kids["sentence"])
    if t["wants"]:
        said.append(f"On the card, {first or 'they'} asked to {_and([WORDS[k] for k in t['wants']])}.")
    if t["reach"] == "text":
        said.append(f"{who} would rather get a text than a call.")
    if t["prayer"]:
        said.append(f"{who} shared a prayer request, and the pastors have it.")
    if not said:
        if planned:
            said.append(f"{who} is planning a visit.")
        else:
            import guest_calls
            said.append(f"{who} {guest_calls.came_words(row, door, tz, now)}.")

    chips = [c for c in [door_words, kids.get("chip", ""),
                         (WANTS_CHIP[t["wants"][0]] if len(t["wants"]) == 1 else
                          (f"Asked for {len(t['wants'])} things" if t["wants"] else "")),
                         "Prefers a text" if t["reach"] == "text" else "",
                         "Prayer: with the pastors" if t["prayer"] else ""] if c]

    asks = asks_for(ch, row, t["wants"], first or "them", notes, theirs, names)
    texts = texts_for(business, contact, start, tz, now)
    steps = row.get("steps") or []
    step = int(row.get("step") or 0)
    status = str(row.get("status") or "")
    due = _parse(row.get("due_at"))
    invite = _invite_line(biz, cid, first or "they", meta, texts, tz, now)
    outcomes = _outcomes(asks, step, steps, status, due, tz, now, invite, first or "them")

    # The caller's other guests this week (the outcome sheet's foot).
    others: List[Dict[str, str]] = []
    others_read = True
    if lid:
        since = cfu._iso(now - timedelta(days=OTHERS_DAYS))
        rows = _rows(f"/church_follow_ups?business_id=eq.{_q(biz)}&leader_contact_id=eq.{_q(lid)}&status=eq.open"
                     f"&created_at=gte.{_q(since)}&select=id,contact_id,card_key,path_kind&limit=50")
        others_read = rows is not None
        rows = [r for r in rows or [] if guest_path.is_guest_follow_up(r) and str(r["id"]) != str(row["id"])]
        got_rows = (_rows(f"/contacts?business_id=eq.{_q(biz)}&id=in.({','.join(_q(r['contact_id']) for r in rows)})"
                          "&select=id,name") if rows else [])
        others_read = others_read and got_rows is not None
        if rows:
            got = {str(c["id"]): _plain(c.get("name")) for c in got_rows or []}
            others = [{"follow_up_id": str(r["id"]), "name": got.get(str(r["contact_id"]), "")}
                      for r in rows if got.get(str(r["contact_id"])) and not _nameless(got.get(str(r["contact_id"])))]

    return {
        "on": True,
        "follow_up": {
            "id": str(row["id"]), "status": status, "step": step,
            "step_title": str(steps[step].get("title") or "") if step < len(steps) else "",
            "due_at": row.get("due_at"), "due_words": when_words(due, tz, now) if due else "",
            "late": bool(status == "open" and due and due < now), "card_name": row.get("card_name") or "",
            "card_key": row.get("card_key") or "",
            "caller": {"contact_id": lid, "name": caller_name} if lid and caller_name else None,
        },
        "guest": {"contact_id": cid, "name": name, "first": first, "initials": cfu.initials(name) if name else "",
                  "phone": contact.get("phone") or "", "email": contact.get("email") or "",
                  "door": door, "door_words": door_words, "visit": visit, "first_visit_at": start.isoformat() if start else None,
                  "invited_by": t["invited"], "planned": planned},
        "kids": {"line": kids.get("line", ""), "count": kids.get("count")} if kids else None,
        "wants": [{"key": k, "label": LABELS[k]} for k in t["wants"]],
        "reach": t["reach"], "prefers_text": t["reach"] == "text",
        "prayer": t["prayer"], "prayer_line": "They shared a prayer request; the pastors have it." if t["prayer"] else None,
        "chips": chips,
        "summary": " ".join(said),
        "opening": _opening(first, call_as, church, bool(kids), start, tz, now, planned=planned, app=app),
        "mentions": mentions_for(ch, t["wants"]),
        "texts": texts,
        "asks": asks,
        "outcomes": outcomes,
        "others": others,
        "others_read": others_read,
    }


def _invite_line(biz: str, cid: str, first: str, meta: Dict[str, Any], texts: Dict[str, Any], tz: Any,
                 now: datetime) -> str:
    """New here's invite, as New here will decide it: kept while they
    haven't been back, skipped once they have (new_here._came_back, the rule
    run_scheduled reads at send time)."""
    step = next((s for s in texts.get("steps") or [] if s["step"] == "invite" and s["state"] == "waiting"), None)
    if not step:
        return ""
    at = _parse(step.get("at"))
    day = at.astimezone(tz).strftime("%A") if at else "the"
    try:
        import new_here
        back = new_here._came_back(biz, cid, _parse(meta.get("texted_at")))
    except Exception:  # noqa: BLE001
        return ""
    if back:
        return f"Skip {day}’s invite, since {first} has been back"
    return f"Keep {day}’s invite, since {first} hasn’t been back yet"


def _outcomes(asks: List[Dict[str, Any]], step: int, steps: List[Dict[str, Any]], status: str,
              due: Optional[datetime], tz: Any, now: datetime, invite: str, first: str) -> List[Dict[str, Any]]:
    """What Chief will do for each tap. Talked's hand-offs are the asks'
    lines (the client puts each one's pick in); these are the rest."""
    title = str(steps[step].get("title") or "") if step < len(steps) else ""
    reach_done = [f"Mark “{title}” done"] if status == "open" and step == 0 and title else []
    due_line = (f"Keep the call on your list, due {when_words(due, tz, now)}" if status == "open" and step == 0 and due
                else f"Keep {first} on your list")
    waiting = [a for a in asks if not a.get("done")]
    tail = [invite] if invite else []
    return [
        {"key": "talked", "label": cfu.OUTCOMES["talked"], "will": reach_done + tail},
        {"key": "message", "label": cfu.OUTCOMES["message"],
         "will": reach_done + (["Hand on what they asked for once you log “Talked”"] if waiting else []) + tail},
        {"key": "noanswer", "label": cfu.OUTCOMES["noanswer"], "will": [due_line] + tail},
        {"key": "notnow", "label": cfu.OUTCOMES["notnow"],
         "will": [f"Keep {first} on your list, and hand nothing on"] + tail},
    ]


def brief_for(business: Dict[str, Any], follow_up_id: str, *, viewer_cid: str = "",
              now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The brief for a follow-up by id, or None when there's none to give
    (the path is off, it isn't a guest's, a read failed). Never raises:
    the Lead tab draws without it."""
    try:
        biz = str(business["id"])
        if not cfu.is_church(business) or not guest_path.switched_on(biz):
            return None
        if "owner_id" not in business:
            # The member page's church row carries no owner: who does
            # First-time guests can fall back to the owner (guest_calls).
            got = _rows(f"/businesses?id=eq.{_q(biz)}&select=id,name,type,owner_id,settings&limit=1")
            if not got:
                return None
            business = got[0]
        row = _one(biz, _uuid(follow_up_id))
        if not guest_path.is_guest_follow_up(row):
            return None
        return brief(business, row, viewer_cid=viewer_cid, now=now)
    except Exception as e:  # noqa: BLE001
        print(f"[guest_brief] no brief ({type(e).__name__}, business {str(business.get('id'))[:8]})", flush=True)
        return None


# ─── After the call ───────────────────────────────────────────────────

def source_event(fid: str, key: str) -> str:
    """A hand-off's receipt: one per ask per welcome call (church_follow_ups'
    unique index on source_event)."""
    return f"call-ask:{fid}:{key}"[:80]


def _pc_words(pname: str, caller: str, what: str, first: str) -> Dict[str, str]:
    return {
        "title": "Chief: a guest’s next step",
        "body": f"{pname} talked with {caller} and would like to {what}. It’s noted on their follow-up.",
        "subject": f"{pname} would like to {what}",
        "text": "\n\n".join([f"Hi {first}," if first else "Hello,",
                             f"{pname} talked with {caller} on their welcome call and would like to {what}.",
                             "Chief noted it on their welcome call. Open Visitor flow to help them take the step."]),
    }


def after_call(business_id: str, follow_up_id: str, outcome: str, picks: Optional[Dict[str, Any]] = None, *,
               by_name: str = "", now: Optional[datetime] = None) -> List[str]:
    """What Chief does once a call is logged (see the top): for Talked on a
    guest's welcome follow-up with the path on, each thing they asked for
    goes to its person. The lines of what it did. Never raises: the note is
    already saved."""
    biz = str(business_id)
    try:
        if outcome != "talked" or not guest_path.switched_on(biz):
            return []
        bizs = _rows(f"/businesses?id=eq.{_q(biz)}&select=id,name,type,owner_id,settings&limit=1")
        if not bizs or not cfu.is_church(bizs[0]):
            return []
        business = bizs[0]
        row = _one(biz, _uuid(follow_up_id))
        if not guest_path.is_guest_follow_up(row) or row.get("status") not in ("open", "done"):
            return []
        cid = str(row["contact_id"])
        people = _rows(f"/contacts?business_id=eq.{_q(biz)}&id=eq.{_q(cid)}&select=id,name,metadata&limit=1")
        theirs = _rows(f"/church_follow_ups?business_id=eq.{_q(biz)}&contact_id=eq.{_q(cid)}"
                       "&select=id,card_key,path_kind,status,leader_contact_id,source_event&limit=50")
        notes = _rows(f"/church_follow_up_notes?business_id=eq.{_q(biz)}&follow_up_id=eq.{_q(row['id'])}"
                      "&author_kind=eq.chief&select=id,kind,body&limit=200")
        if not people or theirs is None or notes is None:
            print(f"[guest_brief] after the call: a read failed, nothing handed (business {biz[:8]})", flush=True)
            return ["Chief couldn’t check what they asked for just now, so nothing was handed on yet. "
                    "Log the call again later, or tell the office."]
        contact = people[0]
        name = "" if _nameless(contact.get("name")) else _plain(contact.get("name"))
        first = _first(name) or "them"
        t = told(contact, row)
        if not t["wants"]:
            return []
        ids = sorted({str(r.get("leader_contact_id") or "") for r in theirs} - {""})
        names = {str(c["id"]): _plain(c.get("name")) for c in (_rows(
            f"/contacts?business_id=eq.{_q(biz)}&id=in.({','.join(_q(i) for i in ids)})&select=id,name") or [])
        } if ids else {}
        ch = Church(business)
        caller_cid = str(row.get("leader_contact_id") or "")
        typed = _plain(by_name)
        caller = names.get(caller_cid, "") or ("" if "@" in typed else typed) or "their caller"
        picks = {str(k): str(v) for k, v in (picks or {}).items() if isinstance(v, (str, int))}
        did: List[str] = []
        told_pc: List[str] = []
        for key in t["wants"]:
            if _done_before(key, notes, theirs, names, str(row["id"])):
                continue
            plan = _plan(ch, key, picks.get(key, ""), first, caller_cid)
            label = LABELS[key]
            if plan["how"] == "skip":
                continue
            if plan["how"] == "unread":
                did.append(f"Chief couldn’t check who takes “{label}” just now, so it wasn’t handed on yet.")
                continue
            if plan["how"] == "note":
                body = f"{ASKED}: {label}. {name or 'They'} would like to {plan['what']}. Noted here for People & Care."
                if cfu._note(biz, str(row["id"]), "chief", "note", body[:1800]) is None:
                    did.append(f"“{label}” wasn’t noted just now. Try again.")
                    continue
                told_pc.append(plan["what"])
                did.append(f"Noted for People & Care: {first} would like to {plan['what']}.")
                continue
            receipt = source_event(str(row["id"]), key)
            made = cfu.start(biz, cid, card_key=f"{CALL_KEY}{key}", card_name=f"Welcome call: {label}",
                             kind=plan["kind"], answers=plan["answers"], source_event=receipt,
                             pick=plan.get("decided"))
            if not made:
                # None is also "already there" (the same tap on another server
                # copy a moment ago): the unique receipt says which.
                had = _rows(f"/church_follow_ups?business_id=eq.{_q(biz)}&source_event=eq.{_q(receipt)}"
                            "&select=id&limit=1")
                if not had:
                    did.append(f"Chief couldn’t hand on “{label}” just now. Log the call again later, or tell the office.")
                    continue
            who = ""
            if made:
                lid = str(made.get("leader_contact_id") or "")
                who = _plain(((cfu._contacts(biz, [lid]) or {}).get(lid) or {}).get("name")) if lid else ""
                cfu._note(biz, str(made["id"]), "chief", "note", f"{ASKED} with {caller}.")
            body = f"{ASKED}: {label}. " + (f"Handed to {who}." if who else "Handed to the office: no one takes it yet."
                                             if made else "Already handed on.")
            cfu._note(biz, str(row["id"]), "chief", "note", body[:1800])
            did.append(f"Handed {first}’s “{label}” to {who}." if who else
                       f"Handed {first}’s “{label}” to the office: no one takes it yet." if made else
                       f"“{label}” was already handed on.")
        if told_pc:
            _tell_people_care(ch, business, name or "A guest", caller, caller_cid, _and(told_pc), str(row["id"]))
        if did:
            import church_history
            church_history.note(biz, "church:card_handed", "Handed on what a guest asked for on their welcome call",
                                target_type="church_follow_up", target_id=row["id"])
        return did
    except HTTPException:
        return []
    except Exception as e:  # noqa: BLE001 — the note is saved; nothing here undoes it
        print(f"[guest_brief] after the call skipped ({type(e).__name__}, business {biz[:8]})", flush=True)
        return []


def _tell_people_care(ch: Church, business: Dict[str, Any], pname: str, caller: str, caller_cid: str,
                      what: str, fid: str) -> bool:
    """Whoever does First-time guests hears (guest_calls.tell_login: a push
    and an email), unless they made the call themselves: the note on their
    own follow-up says it then."""
    pc = ch.people_care
    if not pc or not pc.get("uid") or (pc.get("contact_id") and pc["contact_id"] == caller_cid):
        return False
    try:
        import guest_calls
        ctx = SimpleNamespace(ch=pc["ch"], conf=guest_calls.conf_for(business))
        return bool(guest_calls.tell_login(ctx, pc["uid"], _pc_words(pname, caller, what, _first(pc["name"])),
                                           f"gb-pc-{fid}"[:60]))
    except Exception as e:  # noqa: BLE001
        print(f"[guest_brief] People & Care wasn't told ({type(e).__name__})", flush=True)
        return False


# ─── Who may read it ──────────────────────────────────────────────────

def may_read(business: Dict[str, Any], user: Any, row: Dict[str, Any]) -> bool:
    """The follow-up's caller (an office login whose person it was handed
    to), anyone who sees the Guests room (church_guests' gate: the owner and
    admins always, People & care's areas), the owner, the admins. A view
    that can't be read is a 503, never a yes. People & care's areas and
    whoever does First-time guests open every guest's sheet in Visitor flow
    (church_guests.reads_every_guest); a login that is only some guests'
    caller opens theirs alone (the check above), though it sees the room."""
    role = str(business.get("_caller_role") or "")
    uid = str(getattr(user, "id", "") or "")
    if role in ("owner", "admin") or (uid and uid == str(business.get("owner_id") or "")):
        return True
    lid = str(row.get("leader_contact_id") or "")
    if lid:
        import guest_calls
        try:
            if guest_calls._church(business).login_person.get(uid) == lid:
                return True
        except HTTPException:
            raise HTTPException(503, UNREAD)
    import church_guests
    return church_guests.reads_every_guest(business, user)


def viewer_person(business: Dict[str, Any], user: Any) -> str:
    try:
        import guest_calls
        return str(guest_calls._church(business).login_person.get(str(getattr(user, "id", "") or "")) or "")
    except Exception:  # noqa: BLE001
        return ""


@router.get("/guests/{business_id}/brief/{follow_up_id}")
def get_brief(business_id: str, follow_up_id: str, business: Dict[str, Any] = Depends(business_access(MIN_ROLE)),
              session: UserSession = Depends(sb_clients.authed_request)):
    """Chief's call brief for one guest (see the top). The Welcome Path off,
    not a church, not a guest's follow-up: 404."""
    biz = _uuid(business_id)
    if not cfu.is_church(business) or not guest_path.switched_on(biz):
        raise HTTPException(404, "Not Found")
    row = _one(biz, _uuid(follow_up_id))
    if not guest_path.is_guest_follow_up(row):
        raise HTTPException(404, "Not Found")
    if not may_read(business, session.user, row):
        raise HTTPException(403, "The call brief is for the guest’s caller and People & care.")
    try:
        return brief(business, row, viewer_cid=viewer_person(business, session.user))
    except Unread:
        raise HTTPException(503, UNREAD)
