"""guest_calls.py — who calls our guests (the Welcome Path, step 2).

Kevin, 2026-11-20, on the mock (canvas WmRiSK8seJky8pJUK5nztE, board "Who
calls our guests"): "by default the calls goes to people and care until we
get a welcome team. of course allow this to be selected by any church as to
how they want it done so there structure is unique to them", then "build".

Before this, church_follow_up.choose() handed a guest's welcome call to
whoever held a role that takes connect cards (the Welcome Team lead), else the
senior pastor, else the office. People & Care's duty (church_duties
first_guests: "Every first-time guest has a person and a call date on
Monday, and the calls are made by Wednesday") never got the calls, and a
follow-up couldn't go to an office login at all.

Everything here is behind guest_path.switched_on(biz) and only for a guest's
follow-up (guest_path.is_guest_follow_up). Off, every hand-off is as before.

THE SETTING  businesses.settings.guest_calls (a server key; written only by
             PUT /church/guest-calls/{biz}, with business_settings.merge):
               mode        auto | people_care | person | team
               person      {"contact_id"} for mode person
               team        a team's name for mode team
               rules       [{"when", "to": {"contact_id"}}], at most 10:
                           when = pastor_ask | baptism | door:<door>
               backup      {"contact_id"} or null
               due_days    1 | 2 | 3 (default 2): the call is due that many
                           days after the guest came, at 6 PM, church time
               welcome_ok  auto mode: the office said yes to the Welcome Team
               tell        {"app", "email"}: how a login caller is told
               welcome_asked  the server's own stamp: the office was asked,
                           once, whether to move calls to the Welcome Team
             Nothing saved is mode auto, due in 2 days.

WHO CAN CALL a guest: an office login (the owner, an Admin or a Manager
             seat), as its person (church_over.Church.login_person: the
             seat's tied record, else the one contact its sign-in email
             names; church_my_week reads My week the same way), or anyone
             who holds an active church role (they work it on the Lead tab).
             Anyone else couldn't reach the follow-up, so they are never
             offered and never handed one.

THE CALLER, in order (resolve()):
  1. a rule that matches: pastor_ask (church_follow_up.stream_for), baptism
     (the card says so), or door:<door> (contacts.metadata.new_here.door,
     else the card's own door)
  2. mode person: that person
  3. mode team: whoever on the team has the fewest open guest calls. A team
     is one of the church's teams or ministries (groups), its people who can
     call, and a role two or more people hold ("the deacons")
  4. mode people_care: whoever does First-time guests
  5. mode auto: the Welcome Team when the church has one (an active holder
     of a role whose job is "welcome") AND the office said yes (welcome_ok),
     through today's choose(); else whoever does First-time guests. A
     Welcome Team named without that yes keeps People & Care and asks the
     office once (sweep: welcome_question)
  Whoever does First-time guests: a Manager login that holds the duty (the
  fewest open guest calls first), else the owner. A login with no person
  record gets one, made once from its name and sign-in email (source
  "office_login"); one already carrying that email is used instead.
  Nobody valid at a step: the next step down, and the reason says so.

A guest handed here is marked: assigned_by "guest_calls:<route>", and
leader_role MARK ("guest_calls"; the board titles it "Guest calls") except
the Welcome Team route, which keeps the role today's choose() picked.
church_follow_up._sweep_handed leaves these to recheck(): a caller who can no
longer take the call (the login left, the duty moved, the person or their
role is gone) has the guest re-handed by the same rules, with a note.

TELLING (church_follow_up._sweep_church, through context()): a login caller
hears by a push and an email (care_handoff.tell's pattern) with a link to
the office app's Follow-up board; a member caller keeps today's email to
the Lead tab. The late ladder for a guest's call (late_step):
  the due day, 9 AM ..... the caller is reminded
  a day late ............ the backup takes the guest, and both hear; with no
                          backup, today's: the role above them hears
  three days late ....... with a backup, the senior pastor (else the owner)
                          hears; with none, today's: one more step up
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException

import guest_path
import sb_clients
from auth_supabase import UserSession
from business_access import business_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church", tags=["church"])

KEY = "guest_calls"
MARK = "guest_calls"
BY = "guest_calls"
MODES = ("auto", "people_care", "person", "team")
ASKS = {"pastor_ask": "Asked to talk with a pastor", "baptism": "Wants to get baptized"}
MAX_RULES = 10
DUE_DAYS = (1, 2, 3)
DUE_HOUR = 18
REMIND_BEFORE = timedelta(hours=9)          # 9 AM on the due day
NAV = "operate:follow-up"
OFFICE_ROLES = ("admin", "manager")
TEAM_KINDS = ("team", "ministry")
NOT_EDIT = "Who calls our guests is changed by the owner, the admins, or whoever does First-time guests."
UNREAD = "Who calls your guests couldn't be read just now. Try again."

DEFAULTS: Dict[str, Any] = {
    "mode": "auto", "person": None, "team": None, "rules": [], "backup": None,
    "due_days": 2, "welcome_ok": False, "tell": {"app": True, "email": True},
}

# Where a guest came in, from the card that made the follow-up, when the
# guest's record doesn't say (a first check-in may be the kids desk or the
# office's First time: only the record knows).
_CARD_DOOR = {"text:new_here": "text", "app:new_here": "app", "web:connect_card": "web"}
_BAPTISM = re.compile(r"\bbapti[sz](e|ed|m|ing)\b|\bbaptism\b", re.I)


# ─── Small helpers ────────────────────────────────────────────────────

def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return " ".join(str(v or "").split())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _cid(v: Any) -> Optional[str]:
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, TypeError):
        return None


def _first(name: str) -> str:
    return (_plain(name).split(" ") or [""])[0] or "Someone"


def _need(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, UNREAD)
    return rows


def _chunks(ids: Iterable[str], n: int = 100) -> Iterable[List[str]]:
    ids = list(ids)
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def routed(row: Optional[Dict[str, Any]]) -> bool:
    """A guest's follow-up this module handed (or re-handed)."""
    return (isinstance(row, dict) and str(row.get("assigned_by") or "").startswith(BY)
            and guest_path.is_guest_follow_up(row))


def route_of(row: Dict[str, Any]) -> str:
    by = str(row.get("assigned_by") or "")
    return by.split(":", 1)[1] if by.startswith(BY + ":") else ""


# ─── The setting ──────────────────────────────────────────────────────

def _who_ref(v: Any) -> Optional[Dict[str, str]]:
    cid = _cid((v or {}).get("contact_id")) if isinstance(v, dict) else None
    return {"contact_id": cid} if cid else None


def _when_ok(when: Any) -> bool:
    w = str(when or "")
    return w in ASKS or (w.startswith("door:") and w[5:] in guest_path.DOORS)


def settings_of(raw: Any) -> Dict[str, Any]:
    """The church's setting with the defaults filled in. A value that isn't
    one the setting takes reads as its default, never as a crash."""
    raw = raw if isinstance(raw, dict) else {}
    out = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
           for k, v in DEFAULTS.items()}
    if raw.get("mode") in MODES:
        out["mode"] = raw["mode"]
    out["person"] = _who_ref(raw.get("person"))
    team = _plain(raw.get("team"))[:80]
    out["team"] = team or None
    rules = []
    for r in raw.get("rules") or []:
        if isinstance(r, dict) and _when_ok(r.get("when")) and _who_ref(r.get("to")):
            rules.append({"when": str(r["when"]), "to": _who_ref(r.get("to"))})
    out["rules"] = rules[:MAX_RULES]
    out["backup"] = _who_ref(raw.get("backup"))
    try:
        days = int(raw.get("due_days"))
    except (TypeError, ValueError):
        days = 2
    out["due_days"] = days if days in DUE_DAYS else 2
    out["welcome_ok"] = raw.get("welcome_ok") is True
    tell = raw.get("tell") if isinstance(raw.get("tell"), dict) else {}
    out["tell"] = {"app": tell.get("app") is not False, "email": tell.get("email") is not False}
    if not (out["tell"]["app"] or out["tell"]["email"]):
        out["tell"] = {"app": True, "email": True}
    if isinstance(raw.get("welcome_asked"), str):
        out["welcome_asked"] = raw["welcome_asked"]
    return out


def conf_for(business: Dict[str, Any]) -> Dict[str, Any]:
    settings = business.get("settings") if isinstance(business.get("settings"), dict) else {}
    return settings_of(settings.get(KEY))


# ─── Who can call ─────────────────────────────────────────────────────

def _church(business: Dict[str, Any]):
    import church_over
    return church_over.Church(business)


def logins(ch: Any) -> Dict[str, str]:
    """contact id -> the office login (the owner, an Admin or a Manager seat)
    that person is. The owner first, so a shared record reads as the owner."""
    out: Dict[str, str] = {}
    lp = ch.login_person
    if ch.owner and lp.get(ch.owner):
        out[lp[ch.owner]] = ch.owner
    for uid, cid in lp.items():
        if uid != ch.owner and (ch.seats.get(uid) or {}).get("role") in OFFICE_ROLES:
            out.setdefault(cid, uid)
    return out


def _login_title(ch: Any, uid: str) -> str:
    import church_duties as cd
    lanes = [cd.lane_label(k) for k in ch.lanes(uid)]
    if lanes:
        return " · ".join(lanes)
    return ""


def _role_title(ch: Any, cid: str) -> str:
    import church_over
    what = church_over._what(ch, cid)
    return "" if what == "One of the church's people" else what


def people(ch: Any) -> Dict[str, Dict[str, Any]]:
    """Everyone who can take a guest's call, by contact id: {contact_id,
    name, email, title, login (bool), uid}. A read that fails is a 503."""
    who = logins(ch)
    held = {str(h["contact_id"]) for h in ch.holders if h.get("contact_id")}
    ids = sorted(set(who) | held)
    found: Dict[str, Dict[str, Any]] = {}
    for part in _chunks(ids):
        for r in _need(f"/contacts?business_id=eq.{_q(ch.b)}&id=in.({','.join(_q(i) for i in part)})"
                       "&select=id,name,email&limit=200"):
            found[str(r["id"])] = r
    out: Dict[str, Dict[str, Any]] = {}
    for cid in ids:
        r = found.get(cid)
        if not r:
            continue                       # the record is gone: nobody to hand to
        uid = who.get(cid)
        title = (_login_title(ch, uid) if uid else "") or _role_title(ch, cid)
        if not title and uid:
            title = "Owner" if uid == ch.owner else ("Admin" if ch.role(uid) == "admin" else "Office")
        out[cid] = {"contact_id": cid, "name": _plain(r.get("name")) or "Someone", "email": r.get("email") or "",
                    "title": title, "login": bool(uid), "uid": uid}
    return out


def teams(ch: Any, folks: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    """A team's name -> the people on it who can take a call: the church's
    teams and ministries (groups), and each role two or more people hold
    (the deacons, the elders). A team's leader role is named by its team, so
    it is never a team itself. Teams nobody on can call aren't offered."""
    out: Dict[str, Set[str]] = {}
    by_role: Dict[str, Set[str]] = {}
    for h in ch.holders:
        by_role.setdefault(str(h.get("role") or ""), set()).add(str(h["contact_id"]))
    for d in ch.defs:
        if d.get("covers") == "team":
            continue
        members = {c for c in by_role.get(str(d.get("key") or ""), set()) if c in folks}
        if len(members) >= 2 and _plain(d.get("title")):
            out.setdefault(_plain(d["title"]), set()).update(members)
    groups = _need(f"/groups?business_id=eq.{_q(ch.b)}&kind=in.({','.join(TEAM_KINDS)})&active=eq.true"
                   "&select=id,name&limit=500")
    names = {str(g["id"]): _plain(g.get("name")) for g in groups if _plain(g.get("name"))}
    for part in _chunks(sorted(names)):
        for m in _need(f"/group_members?business_id=eq.{_q(ch.b)}&group_id=in.({','.join(_q(i) for i in part)})"
                       "&select=group_id,contact_id&limit=5000"):
            c = str(m.get("contact_id") or "")
            if c in folks:
                out.setdefault(names[str(m["group_id"])], set()).add(c)
    return {k: sorted(v) for k, v in sorted(out.items(), key=lambda kv: kv[0].casefold()) if v}


def welcome_team(ch: Any, folks: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """{exists, lead, ids}: the church has a Welcome Team when someone holds
    an active role whose job is "welcome" (the first version's Welcome Team
    lead counts until the library is filled)."""
    import church_follow_up as cfu
    defs = cfu._effective_defs(ch.defs, ch.holders)
    keys = {d["key"] for d in defs if d.get("job") == "welcome" and d.get("status", "active") == "active"}
    ids = [str(h["contact_id"]) for h in ch.holders if h.get("role") in keys]
    lead = next((folks[c]["name"] for c in ids if c in folks), None)
    return {"exists": bool(ids), "lead": lead, "ids": ids}


def guest_load(biz: str) -> Dict[str, int]:
    """Open guest calls per caller (contact id). A read that fails is a 503."""
    out: Dict[str, int] = {}
    for r in _need(f"/church_follow_ups?business_id=eq.{_q(biz)}&status=eq.open&leader_contact_id=not.is.null"
                   "&select=leader_contact_id,card_key,path_kind&limit=2000"):
        if guest_path.is_guest_follow_up(r):
            k = str(r["leader_contact_id"])
            out[k] = out.get(k, 0) + 1
    return out


def _lightest(ids: Iterable[str], folks: Dict[str, Dict[str, Any]], load: Dict[str, int]) -> Optional[str]:
    ids = [c for c in ids if c in folks]
    if not ids:
        return None
    return min(ids, key=lambda c: (load.get(c, 0), folks[c]["name"].casefold(), c))


def first_guests_logins(ch: Any, load: Dict[str, int], skip: Iterable[str] = ()) -> List[str]:
    """Whoever does First-time guests, in the order to try them: each
    Manager login holding the duty (the fewest open guest calls first), then
    the owner. A login whose person is in `skip` is passed over."""
    skip = set(skip)
    lp = ch.login_person

    def rank(u: str) -> Tuple[int, str, str]:
        return (load.get(lp.get(u) or "", 0), ch.login_name(u).casefold(), u)
    out = sorted((u for u, s in ch.seats.items()
                  if s.get("role") == "manager" and u != ch.owner and guest_path.FIRST_GUESTS in ch.held(u)
                  and lp.get(u) not in skip), key=rank)
    if ch.owner and not (lp.get(ch.owner) and lp.get(ch.owner) in skip):
        out.append(ch.owner)
    return out


def first_guests_login(ch: Any, load: Dict[str, int], skip: Iterable[str] = ()) -> Optional[str]:
    got = first_guests_logins(ch, load, skip)
    return got[0] if got else None


def person_for_login(ch: Any, uid: str, *, create: bool) -> Optional[str]:
    """The login's person; with `create`, one is made when it has none: the
    one record already carrying its sign-in email when there is one (several
    the login's first name couldn't tell apart: the oldest), else a new
    record with its name and email, source "office_login". No email, no
    record: None (the next step decides)."""
    cid = ch.login_person.get(uid)
    if cid or not create:
        return cid
    import church_assignments as cas
    email = cas._login_email(ch, uid)
    if email is None:
        raise HTTPException(503, UNREAD)
    email = (email or "").strip().lower()
    if "@" not in email:
        return None
    import church_areas
    had = _need(f"/contacts?business_id=eq.{_q(ch.b)}&email=ilike.{_q(church_areas._escape_ilike(email))}"
                "&select=id&order=created_at.asc&limit=1")
    if had:
        return str(had[0]["id"])
    name = ch.login_name(uid)
    if name in ("The owner", "An office login"):
        name = email.split("@")[0]
    made = sb_clients.sb_post_as_service("/contacts", {
        "business_id": ch.b, "name": name[:120], "email": email, "status": "active", "source": "office_login"})
    if not isinstance(made, list) or not made or not made[0].get("id"):
        raise HTTPException(503, UNREAD)
    print(f"[guest_calls] made a person record for an office login (business {ch.b[:8]})", flush=True)
    return str(made[0]["id"])


# ─── The caller ───────────────────────────────────────────────────────

def asks(kind: str, answers: List[Dict[str, str]]) -> Set[str]:
    """What the card asks for that a rule can send elsewhere."""
    import church_follow_up as cfu
    out: Set[str] = set()
    stream, _ = cfu.stream_for(kind if kind in ("baptism", "visit", "serve") else "connect", answers or [])
    if stream == "pastor_ask":
        out.add("pastor_ask")
    if kind == "baptism" or any(_BAPTISM.search(str(a.get("a") or "")) for a in answers or []):
        out.add("baptism")
    return out


def door_for(card_key: str, contact: Optional[Dict[str, Any]]) -> str:
    """Where the guest came in: their record's door (the path's own), else
    the card's."""
    door = str(guest_path.guest_meta(contact).get("door") or "")
    if door in guest_path.DOORS:
        return door
    if card_key.startswith("form:"):
        return "form"
    return _CARD_DOOR.get(card_key, "")


def _to(p: Dict[str, Any], route: str, reason: str, role: str = MARK, uid: Optional[str] = None) -> Dict[str, Any]:
    return {"leader": {"contact_id": p["contact_id"], "name": p["name"]}, "role": role, "reason": reason,
            "route": route, "uid": uid if uid is not None else p.get("uid")}


_DOOR_RULE = {
    "text": "Guests who text NEW go to {name}.",
    "kids": "Guests met at the kids desk go to {name}.",
    "desk": "Guests met at the welcome desk go to {name}.",
    "web": "Guests who fill in the website card go to {name}.",
    "form": "Guests who fill in a card go to {name}.",
    "app": "Guests who say they’re new in the member app go to {name}.",
}


def resolve(ch: Any, conf: Dict[str, Any], *, kind: str, answers: List[Dict[str, str]], door: str,
            load: Dict[str, int], folks: Optional[Dict[str, Dict[str, Any]]] = None,
            today: Optional[Callable[[], Optional[Dict[str, Any]]]] = None,
            skip: Iterable[str] = (), create: bool = True) -> Dict[str, Any]:
    """Who gets this guest's call: {leader: {contact_id, name} | None, uid,
    role, reason, route, ask_welcome}. `today` gives today's choose() pick
    (the Welcome Team route). `skip`: contact ids passed over (a caller who
    can no longer take it). A read that fails is a 503."""
    folks = people(ch) if folks is None else folks
    skip = set(skip)

    def ok(cid: Optional[str]) -> bool:
        return bool(cid) and cid in folks and cid not in skip

    said = asks(kind, answers)
    for r in conf["rules"]:
        when, to = r["when"], r["to"]["contact_id"]
        if not ok(to):
            continue
        if when in said:
            first = folks[to]["name"]
            why = ("They asked to talk with a pastor" if when == "pastor_ask" else "They want to be baptized")
            return {**_to(folks[to], "rule", f"{why}, and the church sends those guests to {first}."), "ask_welcome": False}
        if door and when == f"door:{door}":
            return {**_to(folks[to], "rule", _DOOR_RULE.get(door, "Guests from that door go to {name}.").format(
                name=folks[to]["name"])), "ask_welcome": False}
    mode = conf["mode"]
    lead_in = ""
    if mode == "person":
        p = (conf.get("person") or {}).get("contact_id")
        if ok(p):
            return {**_to(folks[p], "person", f"The church has {_first(folks[p]['name'])} make every guest call."),
                    "ask_welcome": False}
        lead_in = "The person picked for guest calls can’t take this one, so "
    if mode == "team":
        team = conf.get("team") or ""
        on = [c for c in teams(ch, folks).get(team, []) if ok(c)]
        pick = _lightest(on, folks, load)
        if pick:
            return {**_to(folks[pick], "team", f"The church shares guest calls across {team}; "
                                               f"{_first(folks[pick]['name'])} had the fewest open."),
                    "ask_welcome": False}
        lead_in = f"Nobody on {team or 'the team picked'} can take a call right now, so "
    ask_welcome = False
    if mode == "auto":
        wt = welcome_team(ch, folks)
        if wt["exists"] and conf.get("welcome_ok") and today is not None:
            pick = today()
            leader = (pick or {}).get("leader")
            lid = str((leader or {}).get("contact_id") or "")
            if leader and lid not in skip:
                p = folks.get(lid) or {"contact_id": lid, "name": _plain(leader.get("name")) or "Someone", "uid": None}
                return {**_to(p, "welcome", pick.get("reason") or "", role=pick.get("role") or MARK),
                        "ask_welcome": False}
        ask_welcome = bool(wt["exists"] and not conf.get("welcome_ok"))
    for uid in first_guests_logins(ch, load, skip):
        cid = person_for_login(ch, uid, create=create)
        if create and not cid:
            continue                      # no record and no email to make one: the next who does it
        name = folks[cid]["name"] if cid in folks else ch.login_name(uid)
        if lead_in:
            reason = f"{lead_in}{name} has it: they do First-time guests."
        elif mode == "auto" and ask_welcome:
            reason = f"{name} does First-time guests, so the call is theirs until the office moves guest calls " \
                     "to the Welcome Team."
        elif mode == "auto":
            reason = f"{name} does First-time guests, so the call is theirs until there’s a Welcome Team."
        else:
            reason = f"{name} does First-time guests, and the church keeps guest calls with them."
        out = _to({"contact_id": cid, "name": name}, "people_care", reason, uid=uid)
        return {**out, "ask_welcome": ask_welcome}
    said_none = "nobody who does First-time guests has a record to hand it to"
    return {"leader": None, "role": "", "uid": None, "route": "office", "ask_welcome": ask_welcome,
            "reason": f"{lead_in}it’s with the office: {said_none}." if lead_in
            else f"It’s with the office: {said_none}."}


def backup_for(ch: Any, conf: Dict[str, Any], folks: Dict[str, Dict[str, Any]], caller: Optional[str],
               load: Dict[str, int], *, welcome_route: bool, create: bool = True) -> Optional[Dict[str, Any]]:
    """The backup for a caller: the church's pick (anyone who can call, not
    the caller); with none picked, once the Welcome Team makes the calls,
    whoever does First-time guests. None when there's no one else."""
    b = (conf.get("backup") or {}).get("contact_id")
    if b and b in folks and b != caller:
        return folks[b]
    if welcome_route:
        uid = first_guests_login(ch, load, {caller} if caller else ())
        cid = person_for_login(ch, uid, create=create) if uid else None
        if cid and cid != caller:
            return folks.get(cid) or {"contact_id": cid, "name": ch.login_name(uid), "email": "", "uid": uid,
                                      "login": True, "title": _login_title(ch, uid)}
    return None


def due_at(tz: Any, now: datetime, days: int) -> datetime:
    """`days` after today, at 6 PM in the church's clock: a Sunday guest
    with two days is due Tuesday at 6 PM."""
    local = now.astimezone(tz)
    d = local.date() + timedelta(days=days)
    return datetime(d.year, d.month, d.day, DUE_HOUR, tzinfo=tz).astimezone(timezone.utc)


def _zone(ch: Any):
    try:
        return ch.tz
    except Exception:  # noqa: BLE001 — a clock nobody could read: the plain day count
        return None


# ─── A card comes in (church_follow_up.start) ─────────────────────────

def route(business_id: str, contact_id: str, *, card_key: str, kind: str, answers: List[Dict[str, str]],
          today: Callable[[], Optional[Dict[str, Any]]], now: Optional[datetime] = None) -> Dict[str, Any]:
    """The hand-off for a guest's new follow-up: resolve()'s pick plus
    `assigned_by` and `due_at`. Raises on a failed read (start() then hands
    it as before rather than drop the card)."""
    biz = str(business_id)
    rows = _need(f"/businesses?id=eq.{_q(biz)}&select=id,name,type,owner_id,settings&limit=1")
    if not rows:
        raise HTTPException(404, "Not found")
    business = rows[0]
    ch = _church(business)
    conf = conf_for(business)
    contact = _need(f"/contacts?business_id=eq.{_q(biz)}&id=eq.{_q(contact_id)}&select=id,metadata&limit=1")
    door = door_for(card_key, contact[0] if contact else None)
    pick = resolve(ch, conf, kind=kind, answers=answers, door=door, load=guest_load(biz), today=today)
    now = now or _now()
    tz = _zone(ch)
    due = due_at(tz, now, conf["due_days"]) if tz is not None else now + timedelta(days=conf["due_days"])
    return {**pick, "assigned_by": f"{BY}:{pick['route']}", "due_at": due, "door": door}


def other_door_note(card_name: str, answers: List[Dict[str, str]]) -> str:
    said = "; ".join(f"{a['q']} {a['a']}" for a in answers if a.get("a"))[:1500]
    return f"Came through another door: {_plain(card_name) or 'a card'}." + (f" {said}" if said else "")


# ─── The sweep (church_follow_up._sweep_church) ───────────────────────

class Ctx:
    """One church's guest calls for one sweep: its logins, its people, its
    setting and its clock, each read once."""

    def __init__(self, business: Dict[str, Any]):
        self.business = business
        self.ch = _church(business)
        self.conf = conf_for(business)
        self.folks = people(self.ch)
        self.logins = logins(self.ch)
        self.load = guest_load(self.ch.b)
        self.tz = _zone(self.ch)

    def login_of(self, cid: str) -> Optional[str]:
        return self.logins.get(str(cid or "")) if cid else None

    def backup(self, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return backup_for(self.ch, self.conf, self.folks, str(row.get("leader_contact_id") or "") or None,
                          self.load, welcome_route=route_of(row) == "welcome")

    def seniors(self) -> List[Dict[str, Any]]:
        """The senior pastor (every holder of a senior-job role), else the
        owner's login: who hears when a guest waits three days."""
        import church_follow_up as cfu
        defs = cfu._effective_defs(self.ch.defs, self.ch.holders)
        keys = {d["key"] for d in defs if d.get("job") == "senior"}
        ids = [str(h["contact_id"]) for h in self.ch.holders if h.get("role") in keys]
        out = [self.folks[c] for c in dict.fromkeys(ids) if c in self.folks]
        if out:
            return out
        if self.ch.owner:
            cid = self.ch.login_person.get(self.ch.owner)
            return [self.folks.get(cid or "") or {"contact_id": cid, "name": self.ch.login_name(self.ch.owner),
                                                  "email": "", "uid": self.ch.owner, "login": True}]
        return []


def context(business: Dict[str, Any]) -> Optional[Ctx]:
    """None when the Welcome Path is off here; raises when a read fails."""
    if not guest_path.switched_on(business["id"]):
        return None
    return Ctx(business)


def late_step(row: Dict[str, Any], now: datetime, ctx: Ctx) -> Optional[Tuple[int, str]]:
    """A guest's call (the first step) climbs its own ladder: (level, kind),
    the highest rung due and not yet climbed. Kinds: "guest_nudged" (9 AM
    on the due day), "backup_took" (a day late, with a backup), else today's
    "overseer_told"; "pastor_told" (three days late, once a backup took it),
    else today's "next_up". Past the first step: today's ladder."""
    import church_follow_up as cfu
    if int(row.get("step") or 0) != 0:
        return cfu.late_step(row, now)
    if row.get("status") != "open":
        return None
    due = _parse(row.get("due_at"))
    if not due:
        return None
    level = int(row.get("late_level") or 0)
    best: Optional[Tuple[int, str]] = None
    for at, lvl in ((due - REMIND_BEFORE, 1), (due + timedelta(days=1), 2), (due + timedelta(days=3), 3)):
        if now >= at and lvl > level:
            best = (lvl, "")
    if not best:
        return None
    lvl = best[0]
    if lvl == 1:
        return (1, "guest_nudged")
    if lvl == 2:
        return (2, "backup_took" if ctx.backup(row) else "overseer_told")
    return (3, "pastor_told" if route_of(row) == "backup" else "next_up")


def _local(dt: datetime, tz: Any) -> datetime:
    return dt.astimezone(tz) if tz is not None else dt


def _clock(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")


def due_words(due: Any, tz: Any, now: datetime) -> str:
    """"Tuesday by 6 PM", "today by 6 PM", "tomorrow by 6 PM"."""
    dt = _parse(due)
    if not dt:
        return "soon"
    d, today = _local(dt, tz), _local(now, tz).date()
    day = ("today" if d.date() == today else "tomorrow" if d.date() == today + timedelta(days=1)
           else d.strftime("%A"))
    return f"{day} by {_clock(d)}"


def came_words(row: Dict[str, Any], door: str, tz: Any, now: datetime) -> str:
    """"came today through the kids desk", "texted NEW yesterday"."""
    import church_history
    made = _parse(row.get("created_at")) or now
    d, today = _local(made, tz).date(), _local(now, tz).date()
    when = ("today" if d == today else "yesterday" if d == today - timedelta(days=1)
            else f"on {_local(made, tz).strftime('%A')}")
    if door == "text":
        return f"texted NEW {when}"
    if door == "kids":
        return f"checked in at the kids desk {when}"
    if door == "desk":
        return f"came through the welcome desk {when}"
    if door == "web":
        return f"filled in the website card {when}"
    if door == "app":
        return f"said they’re new in the member app {when}"
    if str(row.get("card_key") or "") == "checkin:first":
        return f"checked in for the first time {when}"
    return f"filled in {church_history.card_words(row.get('card_name'))} {when}"


def new_guest_words(pname: str, came: str, due: str, reason: str, first: str) -> Dict[str, str]:
    return {
        "title": "Chief: a new guest for you",
        "body": f"{pname} {came}. Your call is due {due}.",
        "subject": f"A new guest for you: {pname}",
        "text": "\n\n".join([
            f"Hi {first}," if first else "Hello,",
            f"{pname} {came}, and Chief handed them to you for a welcome call. {reason}".strip(),
            f"Your call is due {due}. When you’ve talked, open them on the Follow-up board and press "
            "Mark “Reach out” done.",
        ]),
    }


def remind_words(pname: str, due: str, first: str) -> Dict[str, str]:
    return {
        "title": "Chief: a guest call is due",
        "body": f"Your welcome call with {pname} is due {due}.",
        "subject": f"Your call with {pname} is due {due}",
        "text": "\n\n".join([
            f"Hi {first}," if first else "Hello,",
            f"Your welcome call with {pname} is due {due}.",
            "When you’ve talked, open them on the Follow-up board and press Mark “Reach out” done. If a day "
            "goes by, the guest goes to the backup.",
        ]),
    }


def backup_words(pname: str, caller: str, first: str) -> Dict[str, str]:
    return {
        "title": "Chief: a guest for you to call",
        "body": f"{pname} is a day past due with {caller}. You’re the backup, so the call is yours now.",
        "subject": f"{pname} is yours to call",
        "text": "\n\n".join([
            f"Hi {first}," if first else "Hello,",
            f"{pname} hasn’t had a welcome call, a day past due with {caller}. You’re the church’s backup "
            "caller, so Chief handed them to you.",
            "When you’ve talked, open them on the Follow-up board and press Mark “Reach out” done.",
        ]),
    }


def handed_on_words(pname: str, backup: str, first: str) -> Dict[str, str]:
    return {
        "title": "Chief: your guest went to the backup",
        "body": f"{pname} was a day past due, so {backup} has the call now.",
        "subject": f"{pname} went to {backup}",
        "text": "\n\n".join([
            f"Hi {first}," if first else "Hello,",
            f"{pname} was a day past due for a welcome call, so Chief handed them to {backup}, the backup caller.",
            "Nothing else to do. If you already talked with them, tell the office so it’s on the Follow-up board.",
        ]),
    }


def pastor_words(pname: str, who: str) -> Dict[str, str]:
    return {
        "title": f"{pname} hasn’t had a welcome call",
        "body": f"Three days past due, with {who}. Hand them to someone else on the Follow-up board?",
        "subject": f"{pname} hasn’t had a welcome call",
        "text": "\n\n".join([
            "Hello,",
            f"{pname} is three days past due for a welcome call. {who} has them, after the first caller.",
            "Check in, or hand them to someone else on the Follow-up board.",
        ]),
    }


def _link() -> str:
    import app_base
    return f"{app_base.app_base_url()}/?nav={NAV}"


def tell_login(ctx: Ctx, uid: str, words: Dict[str, str], ref: str) -> bool:
    """One notice to one office login, as care_handoff.tell: a push to the
    office app and an email to its sign-in address, each as the church's
    setting says (both by default), with a link to the Follow-up board.
    True when either went. Never raises. Run it off the event loop (the
    email goes through asyncio.run)."""
    import church_assignments as cas
    import church_leader_tasks as clt
    import church_office_tasks as cot
    ch = ctx.ch
    want = ctx.conf.get("tell") or {}
    rang = 0
    if want.get("app", True):
        try:
            import push_notifications
            rang = push_notifications.send_to_user(uid, title=words["title"][:80], body=words["body"][:160], nav=NAV,
                                                   tag=ref[:60], business_id=ch.b)
        except Exception:  # noqa: BLE001
            logger.info("guest calls: a push didn't go (business %s)", ch.b[:8], exc_info=True)
    mailed = False
    if want.get("email", True):
        try:
            email = cas._login_email(ch, uid)
        except Exception:  # noqa: BLE001
            email = None
        if email:
            try:
                html = cot.render(ch.business, words["text"], words["title"], _link(), "Open the Follow-up board")
                clt.deliver(ch.business, email, "", words["subject"], html, ref, reply_to=clt._office_email(ch.business))
                mailed = True
            except Exception:  # noqa: BLE001
                logger.warning("guest calls: an email didn't go (business %s)", ch.b[:8], exc_info=True)
    return bool(rang) or mailed


async def office_alert(biz_id: str, title: str, body: str, key: str, person_id: Optional[str] = None,
                       action: str = "Open the Follow-up board") -> bool:
    try:
        import httpx
        import notification_engine
        async with httpx.AsyncClient(timeout=20) as client:
            await notification_engine.create_urgent_alert(
                client, biz_id, title, body, dedup_key=key, dedup_hours=24 * 30,
                suggested_action=action, related_contact_id=person_id)
        return True
    except Exception:  # noqa: BLE001
        logger.warning("guest calls: an office alert failed (business %s)", biz_id[:8], exc_info=True)
        return False


def welcome_question_due(ctx: Ctx) -> Optional[str]:
    """The Welcome Team's lead, when the office should be asked (once)
    whether guest calls move to the team: mode auto, no yes yet, never
    asked, and someone holds a welcome role. Else None."""
    conf = ctx.conf
    if conf["mode"] != "auto" or conf.get("welcome_ok") or conf.get("welcome_asked"):
        return None
    wt = welcome_team(ctx.ch, ctx.folks)
    return (wt["lead"] or "Someone") if wt["exists"] else None


async def welcome_question(ctx: Ctx, now: datetime) -> bool:
    import asyncio
    import business_settings
    lead = welcome_question_due(ctx)
    if not lead:
        return False
    ok = await office_alert(
        ctx.ch.b, "Move guest calls to the Welcome Team?",
        f"{lead} now leads your Welcome Team. People & Care keeps making the welcome calls until you say "
        "otherwise: open Who calls our guests (on the Follow-up board, or Text › New here) and choose "
        "the Welcome Team. Guests already handed out stay where they are.",
        f"guest-calls-welcome-{ctx.ch.b}", action="Open Who calls our guests")
    if ok:
        await asyncio.to_thread(business_settings.merge, ctx.ch.b, {"welcome_asked": _iso(now)}, (), [KEY])
        ctx.conf["welcome_asked"] = _iso(now)
    return ok


# ─── A caller who can no longer take it (church_follow_up._sweep_handed) ──

def gone_why(ctx: Ctx, row: Dict[str, Any], pairs: Set[Tuple[str, str]]) -> Optional[str]:
    """Why this guest's caller can no longer take the call, in the note's
    words; None while they still can."""
    lid = str(row.get("leader_contact_id") or "")
    if not lid:
        return None
    p = ctx.folks.get(lid)
    if not p:
        name = ctx.ch.names([lid]).get(lid, "Someone")
        if name == "Someone":
            return "Their caller is no longer one of the church’s people"
        return f"{name} no longer has an office login or a role here"
    r = route_of(row)
    if r == "people_care":
        uid = ctx.login_of(lid)
        if not uid or guest_path.FIRST_GUESTS not in ctx.ch.held(uid):
            return f"{p['name']} no longer does First-time guests"
    if r == "welcome":
        role = str(row.get("leader_role") or "")
        if role and role != MARK and (lid, role) not in pairs:
            return f"{p['name']} no longer holds the role guests came to them through"
    return None


def _today_for(biz: str, kind: str, answers: List[Dict[str, str]], what: str = "") -> Callable[[], Optional[Dict[str, Any]]]:
    def go() -> Optional[Dict[str, Any]]:
        import church_follow_up as cfu
        import church_map
        import church_roles as cr
        all_roles, load, all_defs, mp = cfu.roles(biz), cfu._load(biz), cr.defs(biz), church_map.opened(biz)
        if all_roles is None or load is None or all_defs is None or mp is None:
            raise HTTPException(503, UNREAD)
        return cfu.choose(kind, answers, all_roles, load, all_defs, what=what, m=mp)
    return go


def recheck(biz_id: str, ids: List[str], now: Optional[datetime] = None) -> int:
    """Every guest this module handed whose caller can no longer take the
    call is handed again by the same rules, with a note; with the Welcome
    Path off, back to the office as before. A church that can't be read is
    passed over: a failed read never moves anyone. Returns how many moved."""
    import church_follow_up as cfu
    now = now or _now()
    try:
        biz = _need(f"/businesses?id=eq.{_q(biz_id)}&select=id,name,type,owner_id,settings&limit=1")
        if not biz:
            return 0
        rows = _need(f"/church_follow_ups?business_id=eq.{_q(biz_id)}&id=in.({','.join(_q(i) for i in ids)})"
                     "&status=eq.open&select=*&limit=2000")
        ctx = Ctx(biz[0])
        pairs = {(str(h["contact_id"]), str(h.get("role") or "")) for h in ctx.ch.holders}
        on = guest_path.switched_on(biz_id)
    except Exception as e:  # noqa: BLE001
        print(f"[guest_calls] recheck skipped ({type(e).__name__}, business {biz_id[:8]})", flush=True)
        return 0
    moved = 0
    for r in rows:
        try:
            why = gone_why(ctx, r, pairs)
            if not why:
                continue
            lid = str(r["leader_contact_id"])
            if on:
                answers = [] if r.get("card_key") == "checkin:first" else list(r.get("answers") or [])
                contact = _need(f"/contacts?business_id=eq.{_q(biz_id)}&id=eq.{_q(r['contact_id'])}"
                                "&select=id,metadata&limit=1")
                pick = resolve(ctx.ch, ctx.conf, kind=str(r.get("path_kind") or "connect"), answers=answers,
                               door=door_for(str(r.get("card_key") or ""), contact[0] if contact else None),
                               load=ctx.load, folks=ctx.folks, skip={lid},
                               today=_today_for(biz_id, str(r.get("path_kind") or "connect"), answers))
            else:
                pick = {"leader": None, "role": "", "route": "office", "reason": ""}
            leader = pick.get("leader") if (pick.get("leader") or {}).get("contact_id") else None
            patch = {"leader_contact_id": leader["contact_id"] if leader else None,
                     "leader_role": pick["role"] if leader else "",
                     "assigned_by": f"{BY}:{pick['route']}" if leader else "chief",
                     "assigned_at": _iso(now), "leader_told_at": None, "status": "open",
                     "reason": (f"{why}. " + (pick.get("reason") or "") if leader
                                else f"{why}, so they’re with the office.")[:400],
                     "updated_at": _iso(now)}
            saved = sb_clients.sb_patch_as_service(
                f"/church_follow_ups?id=eq.{_q(r['id'])}&business_id=eq.{_q(biz_id)}"
                f"&leader_contact_id=eq.{_q(lid)}&status=eq.open", patch)
            if not (isinstance(saved, list) and saved):
                continue
            moved += 1
            if leader:
                ctx.load[leader["contact_id"]] = ctx.load.get(leader["contact_id"], 0) + 1
            cfu._note(biz_id, str(r["id"]), "chief", "reassigned",
                      f"{why}. Handed to {leader['name']}." if leader else f"{why}. Back with the office.")
        except Exception as e:  # noqa: BLE001 — one guest never stops the rest
            print(f"[guest_calls] a re-hand was skipped ({type(e).__name__}, business {biz_id[:8]})", flush=True)
    return moved


# ─── The sheet: GET and PUT /church/guest-calls/{business_id} ─────────

def may_edit(business: Dict[str, Any], user: Any) -> bool:
    """The owner, an admin, or whoever does First-time guests. A duty that
    can't be read is a 503 (never a yes)."""
    if business.get("_caller_role") in ("owner", "admin") or str(business.get("owner_id") or "") == str(user.id):
        return True
    import church_duties as cd
    return cd.holds(str(business["id"]), user, guest_path.FIRST_GUESTS)


def _brief(p: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not p:
        return None
    return {"contact_id": p.get("contact_id"), "name": p.get("name") or "Someone", "title": p.get("title") or ""}


def _ladder(caller: Optional[Dict[str, Any]], backup: Optional[Dict[str, Any]],
            seniors: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    who = _first(caller["name"]) if caller else "the office"
    top = seniors[0]["name"] if seniors else "The senior pastor"
    if backup:
        return [{"when": "On the due day", "what": f"Chief reminds {who}."},
                {"when": "A day late", "what": f"{backup['name']} takes the guest, and {who} is told."},
                {"when": "Three days late", "what": f"{top} is told."}]
    return [{"when": "On the due day", "what": f"Chief reminds {who}."},
            {"when": "A day late", "what": "The leader above the caller is told (the senior pastor when there’s "
                                           "no one between)."},
            {"when": "Three days late", "what": "One more step up is told, and the office is asked to hand the "
                                                "guest to someone else."}]


def _how(conf: Dict[str, Any], wt: Dict[str, Any], caller: Optional[Dict[str, Any]],
         backup: Optional[Dict[str, Any]]) -> str:
    mode = conf["mode"]
    if mode == "person":
        if caller and caller.get("contact_id") == (conf.get("person") or {}).get("contact_id"):
            return f"{caller['name']} makes every call."
        return "The person picked can’t take calls right now, so People & Care makes them."
    if mode == "team":
        return f"{conf.get('team') or 'The team'} shares the calls: each new guest goes to whoever on it has the fewest open."
    if mode == "people_care":
        return "People & Care makes every call, even with a Welcome Team."
    if wt["exists"] and conf.get("welcome_ok"):
        return (f"The Welcome Team makes the calls, and {backup['name']} is the backup." if backup
                else "The Welcome Team makes the calls.")
    if wt["exists"]:
        return "People & Care makes the calls until you move them to the Welcome Team."
    return "People & Care makes the calls until you have a Welcome Team."


def view(business: Dict[str, Any], user: Any) -> Dict[str, Any]:
    biz = str(business["id"])
    conf = conf_for(business)
    ch = _church(business)
    folks = people(ch)
    team_map = teams(ch, folks)
    wt = welcome_team(ch, folks)
    load = guest_load(biz)
    nxt = resolve(ch, conf, kind="connect", answers=[], door="", load=load, folks=folks, create=False,
                  today=_today_for(biz, "connect", [], "First check-ins"))
    caller = None
    if nxt.get("leader"):
        cid = nxt["leader"].get("contact_id")
        caller = (_brief(folks[cid]) if cid in folks else
                  {"contact_id": cid, "name": nxt["leader"]["name"],
                   "title": _login_title(ch, nxt["uid"]) if nxt.get("uid") else ""})
    backup = backup_for(ch, conf, folks, (caller or {}).get("contact_id"), load,
                        welcome_route=nxt.get("route") == "welcome", create=False)
    try:
        edit = may_edit(business, user)
    except HTTPException:
        edit = False
    import church_follow_up as cfu
    defs = cfu._effective_defs(ch.defs, ch.holders)
    senior_keys = {d["key"] for d in defs if d.get("job") == "senior"}
    seniors = [folks[str(h["contact_id"])] for h in ch.holders
               if h.get("role") in senior_keys and str(h["contact_id"]) in folks]
    if not seniors and ch.owner:
        seniors = [{"name": ch.login_name(ch.owner)}]
    settings = {k: v for k, v in conf.items() if k != "welcome_asked"}
    # Whoever does First-time guests today, whatever the mode: the sheet says
    # who "People & Care" is before a save, and who backs up the Welcome Team.
    pc_uid = first_guests_login(ch, load)
    pc_cid = person_for_login(ch, pc_uid, create=False) if pc_uid else None
    people_care = (_brief(folks[pc_cid]) if pc_cid in folks else
                   {"contact_id": pc_cid, "name": ch.login_name(pc_uid), "title": _login_title(ch, pc_uid)}
                   if pc_uid else None)
    return {
        "on": guest_path.switched_on(biz),
        "settings": settings,
        "caller": caller,
        "backup": _brief(backup),
        "how": _how(conf, wt, caller, backup),
        "welcome_team": {"exists": wt["exists"], "lead": wt["lead"]},
        "choices": {"people": sorted((_brief(p) | {"login": p["login"]} for p in folks.values()),
                                     key=lambda p: (p["name"].casefold(), p["contact_id"])),
                    "teams": list(team_map)},
        "doors": [{"key": k, "label": v} for k, v in guest_path.DOORS.items()],
        "ladder": _ladder(caller, _brief(backup), seniors),
        "people_care": people_care,
        "pastor": seniors[0]["name"] if seniors else None,
        "may_edit": bool(edit),
    }


def _church_business(business: Dict[str, Any]) -> None:
    import church_follow_up as cfu
    if not cfu.is_church(business):
        raise HTTPException(404, "Not Found")


@router.get("/guest-calls/{business_id}")
def get_guest_calls(business_id: str, business: Dict[str, Any] = Depends(business_access("manager")),
                    session: UserSession = Depends(sb_clients.authed_request)):
    """Who calls the church's guests: the setting, who gets the next guest,
    the backup, and the choices the sheet offers. Any office login that sees
    the Follow-up board (owner, Admin, Manager)."""
    _church_business(business)
    return view(business, session.user)


def _pick(v: Any, folks: Dict[str, Dict[str, Any]], what: str) -> Dict[str, str]:
    cid = _cid((v or {}).get("contact_id")) if isinstance(v, dict) else None
    if not cid:
        raise HTTPException(400, f"Pick {what}.")
    if cid not in folks:
        raise HTTPException(400, "That person can’t take guest calls. Pick an office login or someone who holds "
                                 "a role on Leaders & roles.")
    return {"contact_id": cid}


def clean(body: Dict[str, Any], folks: Dict[str, Dict[str, Any]], team_names: Iterable[str]) -> Dict[str, Any]:
    """What a save may write, checked: every person one who can take a call
    here, a team one of the church's, at most ten rules, the call due in 1–3
    days. Raises 400 with what to fix."""
    if not isinstance(body, dict):
        raise HTTPException(400, "Nothing to save.")
    mode = body.get("mode")
    if mode not in MODES:
        raise HTTPException(400, "Pick who makes the calls.")
    out: Dict[str, Any] = {"mode": mode, "person": None, "team": None}
    if mode == "person":
        out["person"] = _pick(body.get("person"), folks, "the person who makes the calls")
    if mode == "team":
        team = _plain(body.get("team"))
        if not team:
            raise HTTPException(400, "Pick the team that shares the calls.")
        if team not in set(team_names):
            raise HTTPException(400, "That team isn’t one of yours, or nobody on it can take a call yet.")
        out["team"] = team
    rules = body.get("rules") or []
    if not isinstance(rules, list):
        raise HTTPException(400, "Those rules don’t look right.")
    if len(rules) > MAX_RULES:
        raise HTTPException(400, f"Up to {MAX_RULES} rules.")
    seen: Set[str] = set()
    out["rules"] = []
    for r in rules:
        when = str((r or {}).get("when") or "") if isinstance(r, dict) else ""
        if not _when_ok(when):
            raise HTTPException(400, "A rule needs what the guest said or the door they came through.")
        if when in seen:
            raise HTTPException(400, "Two rules say the same thing. Keep one.")
        seen.add(when)
        out["rules"].append({"when": when, "to": _pick(r.get("to"), folks, "who that rule's guests go to")})
    out["backup"] = _pick(body["backup"], folks, "the backup") if body.get("backup") else None
    try:
        days = int(body.get("due_days", 2))
    except (TypeError, ValueError):
        days = 0
    if days not in DUE_DAYS or isinstance(body.get("due_days"), bool):
        raise HTTPException(400, "The call is due within 1, 2 or 3 days.")
    out["due_days"] = days
    out["welcome_ok"] = body.get("welcome_ok") is True
    tell = body.get("tell") if isinstance(body.get("tell"), dict) else {}
    out["tell"] = {"app": tell.get("app") is not False, "email": tell.get("email") is not False}
    if not (out["tell"]["app"] or out["tell"]["email"]):
        raise HTTPException(400, "Keep at least one way to tell the caller.")
    return out


@router.put("/guest-calls/{business_id}")
def put_guest_calls(business_id: str, body: Dict[str, Any] = Body(...),
                    business: Dict[str, Any] = Depends(business_access("manager")),
                    session: UserSession = Depends(sb_clients.authed_request)):
    """Save who calls the church's guests: the owner, an admin, or whoever
    does First-time guests (a duty that can't be read is a 503, never a
    yes). Only future guests follow a change: guests already handed out stay
    where they are."""
    import business_settings
    _church_business(business)
    if not guest_path.switched_on(business["id"]):
        raise HTTPException(404, "Not Found")
    if not may_edit(business, session.user):
        raise HTTPException(403, NOT_EDIT)
    ch = _church(business)
    folks = people(ch)
    put = clean(body, folks, teams(ch, folks))
    saved = business_settings.merge(str(business["id"]), put, (), [KEY])
    if saved is None:
        raise HTTPException(503, "That didn’t save. Nothing was changed. Try again.")
    print(f"[guest_calls] saved (business {str(business['id'])[:8]}, mode {put['mode']}, "
          f"{len(put['rules'])} rules, due {put['due_days']}d)", flush=True)
    fresh = dict(business, settings=saved if isinstance(saved, dict) else business.get("settings"))
    return view(fresh, session.user)
