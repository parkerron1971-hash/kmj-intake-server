"""chief_event_volunteers.py — Chief and an event's volunteers and flyer
(docs/EVENT_VOLUNTEERS.md, step S5).

Kevin, 2026-11-20: "when a event is made there should be questions asked normal
service volunteers or special volunteers ... and also a way to inser flyer for
like a thumbnail to this event", then "go" on the proposal. The office's New
event form asks the three questions (S4a); this is the same from a chat:
"Make the Youth Lock-in Saturday the 12th at 6, ask for 2 greeters and
parking, and put the flyer from the gallery on it."

    create_module_entry / update_module_entry, on an event (an entry of an
    event_roster room), take beside "data":
        teams ........ [{place, n?}]: the Volunteers' places, named the way a
                       person says them ("2 greeters, parking"); a place with
                       no n starts at its Sunday number (Kevin's call 2)
        teams_note ... a note with the ask (300 letters)
        flyer ........ a gallery picture's id, or "make"
        confirmed .... true once the person said yes to what the first send
                       showed
      and a role may say "kids" (works with kids) or "open" (anyone can sign
      up on the public page); a role Chief makes writes both (chief_roster).
    event_volunteers ... {entry_id? | event?}: how full one event is

NEVER A RULE OF ITS OWN. Every step is the office's own code, as the
signed-in login (never as the owner): the status reader
(event_volunteers.status: the gate, can_ask, who schedules the teams, the
Volunteers' places and their Sunday numbers), the ask's own checks before
anything is written (ask_blocks, clean_needs, the note), the gallery's rule
(gallery_reader, _artwork), then, in the office's order once the event is
saved (the app's afterCreate): the flyer (attach_flyer, the flyer route's own
body), the ask (event_volunteers.ask, the POST route itself: claim, then the
date when the asker schedules the teams) and the follow (changed, the route
the app calls after every save). The picture is the route's own reader
(picture), with its name rules.

SHOW BEFORE SAVING, BOUND TO WHAT WAS SHOWN. A save that asks the teams, puts
a gallery picture on, or loosens a role's tick (kids off, or open to the
public page) saves NOTHING the first time: the result says what saving will
do, Chief reads it to the person, and the look is claimed in the member notes'
ledger (member_push_sends, kind chief_event_look, ref_id the login and a
sha256 of the exact params and what was shown; server-only, every replica
reads it, no migration). Sent again with "confirmed" once they say yes, it
saves only when it consumes that claim (unused, this login, the same params,
under half an hour old; one save a look). A second send in the turn whose
first one showed it doesn't count: they haven't heard it yet. A token the
model carried could not do this: the history the app sends back is the
reply's cleaned prose, so a token in a result never reaches the next turn
unless it is put on the screen. Anything that would stop the ask (an unknown
place, no start time, a picture that isn't the church's) is said then too,
before anything is saved. An ask already there, or the event already on Who
serves when, never blocks the rest of a change: the teams are left out and
the words say where their numbers change.

ONCE A TURN. A save that went ahead is kept on the turn's context: the same
event sent again in the turn gets the first answer, and its tag after the
same native call is dropped (chief_tool_loop.remaining_tag_actions).

THE SWITCH. Only where asking is open for the church and this login
(event_volunteers.enabled: the migration in, the switch open, a church whose
teams have owners) and someone signed in is at the keyboard. Elsewhere the
event saves exactly as today, teams and flyer left out, and the result says
plainly why. With nobody signed in (an unattended run, an outside agent) no
tick the model sent is taken. How to use any of it rides the turn's tail only
where it is open (turn_line), never a cached segment: the switch's owner mode
opens it by login. Elsewhere event_volunteers answers from the event's own
roles and sign-ups, with no word of the serving teams.

A FAILURE AFTER THE SAVE never takes the event back: the result says the
event is saved and, in the server's own words, what didn't go.

Other people's words: the ask's note, the answer's note and the names on the
event's own roles (members and the public type them) are someone else's; a
read that brings one in raises the turn's taint on the turn's own context,
together with whatever untrusted_text.defuse found in the read's thread, and
a confirmed save on a tainted turn is held for the person to say it again.
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import re
import unicodedata
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

NOT_ON = "Asking the serving teams isn't on for this church yet"
# "make": the Studio's Light Table makes a flyer from an event (studio_light_table, the owner's, behind its
# own switch; paid, checked and drawn in the background), and the office starts it from the event's own page.
# Chief hands that way over; it never starts a paid design from a save.
MAKE_WORDS = ("A flyer is made in the Studio, from this event: open the event in {room}, then Volunteers and flyer, "
              "and Ask Chief to make one. It goes on the event when you press Use as the flyer.")
MAKE_OWNER = ("A flyer you make in the Studio goes on from the gallery: open the event in {room}, then Volunteers "
              "and flyer, and pick it there, or upload one.")
MAKE_NOT_OWNER = ("A flyer is made in the Studio by the church's owner. You can upload one, or pick one from the "
                  "gallery, on the event's Volunteers and flyer in {room}.")
AFTER_SETUP = ("The event is being set up in the background, so {what}. Once it's saved, ask again and I'll show "
               "what saving does first.")
AGAIN = 'Once they say yes, send the same again with "confirmed":true.'
MAX_TEAMS = 60
RESULT_MAX = 6000
DIGITS = re.compile(r"^\s*(\d{1,3})\s*$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
VERBS = ("create_module_entry", "update_module_entry")

# The look's claim, in the member notes' own ledger (event_volunteers.LEDGER).
LOOK_KIND = "chief_event_look"
LOOK_MINUTES = 30
SHOWN, USED = "shown", "used"

# What a first send showed THIS TURN (the event it would save): its second
# send doesn't count in the same turn, because the person hasn't heard it.
# Set on the turn's own context by the handler, never across turns.
_LOOKED: "contextvars.ContextVar[tuple]" = contextvars.ContextVar("chief_event_looked", default=())
# The saves that went ahead THIS TURN: ((target, the action's digest), result).
_DONE: "contextvars.ContextVar[tuple]" = contextvars.ContextVar("chief_event_done", default=())

TOOL = {
    "name": "event_volunteers",
    "description": "Only where the turn's EVENT VOLUNTEERS line shows: how full one event is.",
    "input_schema": {"type": "object", "properties": {
        "entry_id": {"type": "string"}, "event": {"type": "string"}}},
}


# ─── Small things ─────────────────────────────────────────────────────

def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _said(e: Exception) -> str:
    """A refusal in the server's own words, as a sentence."""
    if isinstance(e, HTTPException):
        words = _plain(e.detail)
        if e.status_code == 404 and words in ("Not Found", "business not found"):
            return NOT_ON + "."
        if e.status_code >= 500 or not words:
            return "That couldn't be done just now. Try again in a minute."
        return words if words[-1:] in ".?!" else words + "."
    return "That couldn't be done just now. Try again in a minute."


def _lower(words: str) -> str:
    return words[:1].lower() + words[1:] if words[:2] not in ("I ", "I'") else words


def _fence(v: Any) -> str:
    import church_map_asks as cma
    return cma.fence(v)


def _join(words: List[str]) -> str:
    from event_volunteers import _join as join
    return join(words)


def _key(v: Any) -> str:
    """A place's name the way two people say it alike: no accents, no case,
    letters and digits, one space."""
    s = unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _stem(k: str) -> str:
    """"greeters" and "greeter" alike; "kids rooms" and "kid room" alike;
    a trailing "team" said with the place is the team, not the place."""
    words = [w for w in k.split() if w not in ("the", "our")]
    if len(words) > 1 and words[-1] in ("team", "teams"):
        words = words[:-1]
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words)


def _ev():
    import event_volunteers
    return event_volunteers


def _sp():
    import sunday_planning
    return sunday_planning


def _sha(body: Any) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _taint_now() -> int:
    """The turn's taint as this context sees it (a thread's own copy too)."""
    try:
        from chief_of_staff import untrusted_taint
        return int(untrusted_taint())
    except Exception:  # noqa: BLE001
        return 0


def _bump(n: int) -> None:
    """Raise the turn's taint on the turn's own context (never a thread's)."""
    if n <= 0:
        return
    try:
        from chief_of_staff import _bump_taint
        _bump_taint(n)
    except Exception:  # noqa: BLE001 — a taint that can't be raised is said in the log
        print("[chief_event_volunteers] the turn's taint wasn't raised", flush=True)


# ─── Who is at the keyboard, and whether asking is open ───────────────

def turn_user(action: Optional[Dict[str, Any]] = None):
    """The signed-in login this turn (an AuthedUser), or None: an unattended
    run, an outside agent, or nobody signed in. Its email is read for the
    switch's owner mode (chief_church_schedule._email: a failed read isn't
    kept); unread, owner mode falls back to the church."""
    if (action or {}).get("_unattended"):
        return None
    from chief_duties import _turn_user
    uid = _turn_user()
    if not uid:
        return None
    from auth_supabase import AuthedUser
    import chief_church_schedule as ccs
    return AuthedUser(id=uid, email=ccs._email(uid) or "", role="authenticated")


def open_here(business_id: Any, user: Any = None) -> bool:
    """event_volunteers.enabled, and a read that fails is a no."""
    try:
        return _ev().enabled(str(business_id), user)
    except Exception:  # noqa: BLE001 — couldn't tell is closed, never a 500
        return False


def could_follow() -> bool:
    """Whether asking could be open anywhere: the switch not off, Who serves
    when not off, the migration in (kept answers, no read of a church)."""
    try:
        ev = _ev()
        return ev.mode() != "off" and _sp().mode() != "off" and ev.ready()
    except Exception:  # noqa: BLE001
        return False


def could_open(business: Dict[str, Any]) -> bool:
    """could_follow, and the business a church (from its own row, no read).
    Only then is a plain change to an events room's entry followed."""
    if not could_follow():
        return False
    if not (business or {}).get("type"):
        return True                     # a row read without its type: the follow's own gate decides
    import church_follow_up
    return church_follow_up.is_church(business)


def room_of(entry: Dict[str, Any]) -> str:
    """The archetype of an entry's room, read with the entry itself
    (custom_modules(archetype) embedded), '' when it wasn't."""
    m = (entry or {}).get("custom_modules")
    if isinstance(m, list):
        m = m[0] if m else None
    return str((m or {}).get("archetype") or "") if isinstance(m, dict) else ""


def roles_explicit(business_id: Any, user: Any = None) -> bool:
    """Whether a role Chief makes here writes its two ticks: asking open at
    this church (the office shows both ticks exactly there)."""
    return open_here(business_id, user)


def asks(action: Dict[str, Any]) -> bool:
    """Whether a save says anything about the serving teams or a flyer."""
    return any((action or {}).get(k) not in (None, "", [], {}) for k in ("teams", "flyer"))


def loosened(module: Dict[str, Any], before: Optional[Dict[str, Any]],
             roles_now: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """The tick changes on roles already there that let more people in: a
    role that worked with kids no longer does (no background check), or a
    role kept off the public page opened to it. Each is shown first, needs
    the person's yes and is held on a tainted turn."""
    if before is None:
        return []
    import chief_roster
    own = before.get(chief_roster.ROLES_FIELD)
    was = {r["id"]: r for r in (chief_roster.clean_roles(own) if isinstance(own, list)
                                 else chief_roster.params(module)["roles"])}
    out: List[Dict[str, str]] = []
    for r in roles_now:
        b = was.get(r["id"])
        if not b:
            continue
        if b.get("kids") is True and r.get("kids") is not True:
            out.append({"id": r["id"], "label": r["label"], "what": "kids"})
        if b.get("open") is False and r.get("open") is True:
            out.append({"id": r["id"], "label": r["label"], "what": "open"})
    return out


def _loose_words(loose: List[Dict[str, str]]) -> str:
    out = []
    for x in loose:
        if x["what"] == "kids":
            out.append(f"{x['label']} won't be marked as working with kids, so it won't need a background check.")
        else:
            out.append(f"{x['label']} opens to anyone on the public events page.")
    return " ".join(out)


# ─── The places, as a person says them ────────────────────────────────

def places_of(st: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The status reader's Volunteers' places, flat, in the teams' order:
    {id, name, needed, team}."""
    return [{"id": p["id"], "name": p["name"], "needed": p["needed"], "team": t["name"]}
            for t in st.get("teams") or [] for p in t.get("places") or []]


def _asked_teams(raw: Any) -> List[Tuple[str, Any]]:
    """(the place as said, its number or None), from [{place, n}], a map of
    place to number, or the words themselves ("2 greeters, parking")."""
    out: List[Tuple[str, Any]] = []
    if isinstance(raw, dict):
        raw = [{"place": k, "n": v} for k, v in raw.items()]
    if isinstance(raw, str):
        raw = [s for s in re.split(r",|;|\band\b|\n", raw) if s.strip()]
    if not isinstance(raw, list):
        return out
    for item in raw[:MAX_TEAMS + 1]:
        if isinstance(item, str):
            m = re.match(r"^\s*(\d{1,3})\s+(?:on\s+|in\s+)?(.+)$", item)
            out.append((m.group(2), int(m.group(1))) if m else (item, None))
        elif isinstance(item, dict):
            said = item.get("place") or item.get("name") or item.get("label") or item.get("id") or ""
            n = next((item[k] for k in ("n", "needed", "count", "people") if item.get(k) not in (None, "")), None)
            out.append((str(said), n))
    return [(_plain(s), n) for s, n in out if _plain(s)]


def _number(n: Any, place: Dict[str, Any]) -> Any:
    """No number: the place's Sunday number. A whole number said as digits
    reads as that number; anything else is left for clean_needs to refuse in
    its own words."""
    if n is None:
        return min(int(place["needed"]), _ev().MAX_EACH)
    if isinstance(n, float) and n.is_integer():
        return int(n)
    if isinstance(n, str) and DIGITS.match(n):
        return int(n)
    return n


def _list_places(places: List[Dict[str, Any]]) -> str:
    teams: Dict[str, List[str]] = {}
    for p in places:
        teams.setdefault(p["team"], []).append(p["name"])
    return _join([f"{', '.join(names)} ({team})" for team, names in teams.items()][:12])


def resolve(raw: Any, places: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[str]]:
    """({place_id: n}, the problems in plain words). A place is the church's
    own by its name (any case, singular or plural), "Team: Place" or "Place
    (Team)" when two teams have one of that name, or a team that has one
    place. An unknown place, one that could be two, a word that names both a
    place and a team, or one place given two numbers is named back, never
    guessed."""
    needs: Dict[str, Any] = {}
    problems: List[str] = []
    asked = _asked_teams(raw)
    if not asked:
        return {}, ["Name the serving teams' places to ask, and how many for each."]
    if len(asked) > MAX_TEAMS:
        return {}, [f"Ask for {MAX_TEAMS} places at most."]
    unknown: List[str] = []
    for said, n in asked:
        team_said, place_said = "", said
        m = re.match(r"^(.+?)\s*\((.+)\)\s*$", said)
        if m:
            place_said, team_said = m.group(1), m.group(2)
        elif ":" in said:
            team_said, _, place_said = said.partition(":")
        hit = next((p for p in places if p["id"] == place_said.strip().lower()), None) if _UUID.match(
            place_said.strip()) else None
        if hit is None:
            want = _stem(_key(place_said))
            by_place = [p for p in places if _stem(_key(p["name"])) == want]
            by_team: List[Dict[str, Any]] = []
            if team_said:
                by_place = [p for p in by_place if _stem(_key(p["team"])) == _stem(_key(team_said))]
            else:
                by_team = [p for p in places if _stem(_key(p["team"])) == want]
            if by_place and by_team and {p["id"] for p in by_team} != {p["id"] for p in by_place}:
                # One word, a place and a team: named back, never taken as either.
                where = by_place[0]
                problems.append(f"“{_fence(said)[:60]}” is a place on {_join(sorted({p['team'] for p in by_place}))} "
                                f"and a team of its own ({_join([p['name'] for p in by_team])}). Say which, as "
                                f"\"{where['team']}: {where['name']}\" or \"{by_team[0]['team']}: "
                                f"{by_team[0]['name']}\".")
                continue
            found = by_place or (by_team if len(by_team) == 1 else [])
            if not found and len(by_team) > 1:
                problems.append(f"{by_team[0]['team']} has {_join([p['name'] for p in by_team])}. Which of them, "
                                "and how many for each?")
                continue
            if len(found) > 1:
                problems.append(f"{found[0]['name']} is on {_join([p['team'] for p in found])}. Say which, as "
                                f"\"{found[0]['team']}: {found[0]['name']}\".")
                continue
            hit = found[0] if found else None
        if hit is None:
            unknown.append(_fence(said)[:60])
            continue
        n = _number(n, hit)
        if hit["id"] in needs and needs[hit["id"]] != n:
            problems.append(f"{hit['name']} is named twice, with {needs[hit['id']]} and {n}. How many for "
                            f"{hit['name']}?")
            continue
        needs[hit["id"]] = n
    if unknown:
        names = _join([f"“{u}”" for u in unknown])
        problems.append(f"{names} {'isn' if len(unknown) == 1 else 'aren'}'t one of the Volunteers' places. "
                        + (f"The places are {_list_places(places)}." if places else
                           "This church has no Volunteers' places yet: they're added on Who serves when."))
    return needs, problems


def make_words(biz: Dict[str, Any], user: Any, room: str) -> str:
    """Where a flyer for this event is made, for this login: the Light
    Table on the event's own page where the office shows it (the church's
    owner, with the Studio's Light Table open to them: studio_status's own
    rule, images.business then open_to); the gallery for an owner without
    it; upload or the gallery for anyone else."""
    owner = str(getattr(user, "id", "")) == str(biz.get("owner_id") or "")
    light = False
    if owner:
        try:
            import studio_light_table
            light = studio_light_table.open_to(user)
        except Exception:  # noqa: BLE001 — unread is the gallery's way, never a wrong door
            light = False
    return (MAKE_WORDS if light else MAKE_OWNER if owner else MAKE_NOT_OWNER).format(room=room)


def _flyer_said(raw: Any) -> Tuple[Optional[str], Optional[str]]:
    """("make" | an artwork id | None, a problem or None)."""
    if raw in (None, "", [], {}):
        return None, None
    s = _plain(raw)
    if s.lower() in ("make", "make one", "make it", "design", "new"):
        return "make", None
    if _UUID.match(s):
        return s.lower(), None
    return None, "Pick the flyer from the gallery, or say make, and I'll say where a flyer is made."


# ─── The look's claim (member_push_sends) ─────────────────────────────

def _ref(uid: str, digest: str) -> str:
    return f"look:{uid}:{digest[:56]}"


def _show(biz_id: str, uid: str, digest: str) -> None:
    """Claim what was shown: (re)written as shown, its time now. A write
    that fails is said in the log; the confirm then shows the look again."""
    import sb_clients
    ev = _ev()
    got = sb_clients.sb_post_as_service(ev.LEDGER, {
        "business_id": biz_id, "kind": LOOK_KIND, "ref_id": _ref(uid, digest), "title": SHOWN, "body": None,
        "url": None, "sent_by": uid, "recipients": 0, "created_at": ev._iso(ev._now())},
        prefer="resolution=merge-duplicates,return=representation")
    if not isinstance(got, list):
        print(f"[chief_event_volunteers] {biz_id[:8]}: a shown plan wasn't claimed", flush=True)


def _consume(biz_id: str, uid: str, digest: str) -> Optional[bool]:
    """Whether this login was shown exactly this plan in the last half hour
    and it hasn't been saved since: one write that marks it used, so two
    sends (or two replicas) can't both save it. None: couldn't be read."""
    import sb_clients
    ev = _ev()
    since = ev._iso(ev._now() - timedelta(minutes=LOOK_MINUTES))
    got = sb_clients.sb_patch_as_service(
        f"/member_push_sends?business_id=eq.{ev._q(biz_id)}&kind=eq.{LOOK_KIND}&ref_id=eq.{ev._q(_ref(uid, digest))}"
        f"&title=eq.{SHOWN}&created_at=gte.{ev._q(since)}&select=id", {"title": USED})
    if not isinstance(got, list):
        return None
    return bool(got)


# ─── Before the save: the gate, the look, and what stops it ───────────

def _stop(atype: str, said: str, told: str, nav: Optional[Dict[str, Any]] = None, **more: Any) -> Dict[str, Any]:
    """Nothing saved: what the person hears (the label, which the reply
    reads out on its own) and what Chief does next (told)."""
    return {"type": atype, "result": f"Failed: {told}", "label": said[:1200], "failed": True,
            "needs_confirmation": True, **({"nav": nav} if nav else {}), **more}


def _role_words(roles: List[Dict[str, Any]]) -> str:
    out = []
    for r in roles[:12]:
        ticks = [w for k, w in (("kids", "works with kids"), ("open", "anyone can sign up")) if r.get(k) is True]
        out.append(f"{r['label']} {r['needed']}" + (f" ({', '.join(ticks)})" if ticks else ""))
    return ", ".join(out)


def _who_gets_it(st: Dict[str, Any]) -> str:
    """The office's own sentence (eventVolunteersCore.whoGetsIt)."""
    if st.get("can_schedule"):
        return "You schedule the serving teams, so saving puts it straight on Who serves when."
    who = _join(st.get("holders") or [])
    if not who:
        return ("Whoever schedules the teams gets the request, and one tap from them puts it on Who serves when "
                "with just these places.")
    return (f"{who} {'gets' if len(st.get('holders') or []) == 1 else 'get'} the request, and one tap puts it on "
            "Who serves when with just these places.")


def _when(ent: Dict[str, Any]) -> str:
    ev = _ev()
    if ent.get("at") is not None:
        return ev.short_when(ent["at"])
    return ev.short_day(ent["day"]) if ent.get("day") else "no day yet"


def _target(module: Dict[str, Any], data: Dict[str, Any], entry_id: Optional[str]) -> str:
    """The event a send would save: its entry, or its room and name."""
    if entry_id:
        return f"entry:{entry_id}"
    import chief_roster
    title = chief_roster.params(module)["title_field"]
    return f"new:{module.get('id')}:{_key(data.get(title) or data.get('title'))}"


def _raw(action: Dict[str, Any]) -> str:
    """The action's own digest, as sent (its confirm, its type and the
    door's marks aside), so the same send as a tag after a native call is
    known."""
    return _sha({k: v for k, v in (action or {}).items() if k not in ("confirmed", "type") and not k.startswith("_")})


def _skip_words(biz_id: str, ent: Dict[str, Any], st: Dict[str, Any], room: str, e: HTTPException) -> str:
    """An ask already there, or the event already on Who serves when: the
    rest of the change still saves, and these words say where its numbers
    change (Chief has no way to change them)."""
    ev = _ev()
    title = ev.The(ent["title"])
    try:
        req = ev.live_request(biz_id, ent["entry_id"])
    except HTTPException:
        return f"{_said(e)} The serving teams weren't asked again."
    if req and req.get("status") == ev.WAITING:
        return (f"{title} already asked the serving teams, so they weren't asked again. Change the numbers on the "
                f"event's Volunteers and flyer page in {room}, or ask whoever schedules the teams.")
    if st.get("can_schedule"):
        how = "Change its numbers on Who serves when."
    else:
        how = f"Ask {_join(st.get('holders') or []) or 'whoever schedules the teams'} to change the numbers."
    return f"{title} is already on Who serves when, so the teams weren't asked again. {how}"


def _look(biz: Dict[str, Any], module: Dict[str, Any], action: Dict[str, Any], data: Dict[str, Any],
          entry: Optional[Dict[str, Any]], roles: List[Dict[str, Any]], loose: List[Dict[str, str]],
          other: bool, user: Any, tainted: bool, looked: tuple) -> Dict[str, Any]:
    """The plan for a save that names teams or a flyer, or loosens a tick. kind:
        none ... nothing of that: save as today
        off .... asking isn't open here, or isn't this login's: save as today,
                 and say why (`said`)
        stop ... nothing saved: the look, a hold, or what would stop it
                 (`result`, the handler's whole answer)
        go ..... save, then the flyer, the ask and the follow"""
    atype = "update_module_entry" if entry else "create_module_entry"
    ev, sp = _ev(), _sp()
    if not asks(action) and not loose:
        return {"kind": "none", "user": user, "follow": bool(user) and open_here(biz["id"], user)}
    flyer, flyer_problem = _flyer_said(action.get("flyer"))
    wants_teams = action.get("teams") not in (None, "", [], {})
    without = ("without asking them" + (" or a flyer" if action.get("flyer") else "") if wants_teams
               else "without a flyer")
    first = "Asking the serving teams" if wants_teams else "Putting a flyer on an event"

    def refused(why: str, closed: bool = False) -> Dict[str, Any]:
        if loose:
            return {"kind": "stop", "result": _stop(atype, f"Nothing saved yet. {why}", (
                f"NOT SAVED: {why} Say so plainly; nothing was saved."))}
        if closed:
            return {"kind": "off", "said": f"{first} {why}, so the event was saved {without}."}
        return {"kind": "off", "said": f"{why} The event was saved {without}."}
    if user is None:
        return refused("is done by someone signed in to the church's office, in the chat", closed=True)
    bid = str(biz["id"])
    if not open_here(bid, user):
        return refused("isn't on for this church yet", closed=True)
    try:
        st = ev.status(bid, user)
    except HTTPException as e:
        return refused(_said(e))
    if not st.get("enabled"):
        return refused("isn't on for this church yet", closed=True)
    if not st.get("can_ask"):
        from worship_team import REFUSED
        return refused(REFUSED["serve"])
    from system_destinations import module_destination
    nav = module_destination(module)
    room = module.get("name") or "Services & Events"
    places = places_of(st)
    problems: List[str] = []
    needs: Dict[str, Any] = {}
    skip = ""
    if wants_teams:
        needs, problems = resolve(action.get("teams"), places)
    note = ""
    try:
        note = ev._note(action.get("teams_note"))
    except HTTPException as e:
        problems.append(_said(e))
    zone = sp._zone(bid)
    now = sp._now().astimezone(zone)
    eid = (entry or {}).get("id") or ""
    ent = ev.entry_view({"id": eid, "status": (entry or {}).get("status") or "active", "data": data}, module, zone)
    title = ent["title"]
    if wants_teams and not problems:
        try:
            ev.clean_needs(bid, needs, places)          # the numbers, in the ask's own words
            ev.ask_blocks(bid, ent, now, zone)          # the time, a Sunday service, an ask already there
        except HTTPException as e:
            if e.status_code == 409 and eid:
                skip, needs = _skip_words(bid, ent, st, room, e), {}
            else:
                problems.append(_said(e))
    picture = None
    replacing = False
    if flyer_problem:
        problems.append(flyer_problem)
    elif flyer and flyer != "make":
        try:
            ev.gallery_reader(ev._business(bid), user)   # the gallery's own rule
            picture = ev._artwork(bid, flyer)
        except HTTPException as e:
            problems.append(_said(e))
        replacing = bool(eid) and ev.flyer_of((entry or {}).get("data"), bid, eid) is not None
    if problems:
        words = " ".join(problems)
        return {"kind": "stop", "result": _stop(atype, f"Nothing saved yet. {words}", (
            f"NOT SAVED: {words} Say this to them in these words and ask what to change; nothing was saved. "
            "When they answer, send it again with what they said."), nav)}
    make = make_words(biz, user, room) if flyer == "make" else ""
    if skip and not (other or picture is not None or loose):
        said = " ".join(w for w in (skip, make) if w)
        return {"kind": "stop", "result": _stop(atype, said, (
            f"NOTHING TO SAVE: {said} Say this to them in these words; nothing changed."), nav)}
    said_teams = ev.needs_words(needs, places) if needs else ""
    lines = [f"{ev.The(title)}, {_when(ent)}" + (f", {ent['place']}" if ent.get("place") else "")
             + f", in {room}."]
    if said_teams:
        lines.append(f"It asks the serving teams for {said_teams}. {_who_gets_it(st)}"
                     + (f" With the note: “{_fence(note)}”." if note else ""))
    if skip:
        lines.append(skip)
    if roles:
        lines.append(f"Special volunteers: {_role_words(roles)}.")
    if loose:
        lines.append(_loose_words(loose))
    if picture is not None:
        lines.append("The flyer: the gallery picture you picked" + (", in place of the event's current flyer."
                                                                   if replacing else "."))
    elif make:
        lines.append(make)
    target = _target(module, data, eid or None)
    go = {"kind": "go", "user": user, "needs": needs, "note": note, "flyer": flyer, "status": st,
          "said_teams": said_teams, "room": room, "make": make, "skip": skip, "follow": True,
          "target": target, "raw": _raw(action)}
    if not needs and picture is None and not loose:
        return go          # nothing reaches anyone, and nothing loosens: nothing to show first
    look = " ".join(lines)
    digest = _sha({"target": target, "look": look, "data": action.get("data") or {}, "roles": action.get("roles"),
                   "volunteers": action.get("volunteers"), "needs": needs, "note": note, "flyer": flyer,
                   "loose": [[x["id"], x["what"]] for x in loose], "who": [st.get("can_schedule"),
                                                                          st.get("holders")]})
    shown = {"kind": "stop", "target": target, "result": _stop(atype, f"Before I save: {look} Shall I?", (
        f"NOT SAVED YET, shown first: {look} Read this to them in these words and ask if it's right. {AGAIN} "
        "Not in this turn: they haven't heard it yet. Don't say it's saved or that anyone was asked."),
        nav, look=look)}
    if not action.get("confirmed") or target in looked:
        # A second send in the turn whose first one showed this doesn't
        # count: they haven't heard it yet.
        _show(bid, str(user.id), digest)
        return shown
    if tainted:
        return {"kind": "stop", "result": _stop(atype, (
            "Before I save this, say it once more: I read other people's words this turn, so I wait for you. "
            "Nothing has been saved yet."), (
            "HELD: something read this turn was someone else's words, so this waits for the person. Read back "
            "exactly what you were about to save and ask them to say it again; then it runs. Don't say it's "
            "saved."), nav)}
    took = _consume(bid, str(user.id), digest)
    if took is None:
        return {"kind": "stop", "result": _stop(atype, "Nothing saved yet. That couldn't be checked just now. "
                                                       "Try again in a minute.", (
            "NOT SAVED: whether this was shown to them couldn't be read just now. Say so plainly."), nav)}
    if not took:
        # Not what they were shown (another plan, another login, too long
        # ago, or already saved): shown now, and saved only on their yes.
        _show(bid, str(user.id), digest)
        return shown
    return go


async def before_save(biz: Dict[str, Any], module: Dict[str, Any], action: Dict[str, Any], data: Dict[str, Any],
                      *, entry: Optional[Dict[str, Any]] = None, roles: Optional[List[Dict[str, Any]]] = None,
                      loose: Optional[List[Dict[str, str]]] = None, other: bool = True,
                      user: Any = None) -> Dict[str, Any]:
    """The plan for this save (see _look), read off the turn's own context
    (the taint, what this turn already showed and saved) and run off the
    loop. A first send's look is remembered here, on the turn's context; the
    same event saved again this turn gets the first answer."""
    action = action or {}
    if user is None:
        user = turn_user(action)
    if asks(action) or loose:
        target, raw = _target(module, data, (entry or {}).get("id")), _raw(action)
        for (t, r), first in _DONE.get():
            if t == target or r == raw:
                return {"kind": "stop", "result": dict(first)}
    try:
        from chief_of_staff import untrusted_taint
        tainted = bool(untrusted_taint())
    except Exception:  # noqa: BLE001 — unread is not a yes
        tainted = True
    try:
        plan = await asyncio.to_thread(_look, biz, module, action, data, entry, roles or [], loose or [], other,
                                       user, tainted, _LOOKED.get())
    except HTTPException as e:
        # A read the look needed failed: nothing saved, and it says so.
        atype = "update_module_entry" if entry else "create_module_entry"
        return {"kind": "stop", "result": _stop(atype, f"Nothing saved yet. {_said(e)}", (
            f"NOT SAVED: {_said(e)} Say so plainly; nothing was saved."))}
    if plan.get("kind") == "stop" and plan.get("target"):
        _LOOKED.set(_LOOKED.get() + (plan["target"],))
    return plan


def ran_this_turn(action: Dict[str, Any]) -> bool:
    """Whether this exact send already went ahead this turn (a native call
    the reply's tag repeats): chief_tool_loop drops the tag."""
    if not isinstance(action, dict) or action.get("type") not in VERBS:
        return False
    raw = _raw(action)
    return any(r == raw for (_, r), _ in _DONE.get())


# ─── After the save: the flyer, the ask, the follow ───────────────────

def _follow(biz_id: str, entry_id: str, user: Any) -> None:
    """The route the app calls after every save of an event (changed): the
    event's date on Who serves when and its ask follow it now. Never able to
    fail the save: where it isn't open it's a 404, and the 15-minute sweep
    follows anything missed."""
    try:
        _ev().changed(entry_id, {"business_id": biz_id}, user)
    except HTTPException as e:
        if e.status_code not in (403, 404):
            print(f"[chief_event_volunteers] {biz_id[:8]}: the event's follow didn't run ({e.status_code})",
                  flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[chief_event_volunteers] {biz_id[:8]}: the event's follow didn't run ({type(e).__name__})",
              flush=True)


async def after_save(biz: Dict[str, Any], entry_id: Optional[str], plan: Dict[str, Any],
                     res: Dict[str, Any]) -> Dict[str, Any]:
    """The saved event's result, with what came of the flyer and the ask, in
    the server's own words. The event stays saved whatever happens here."""
    kind = plan.get("kind")
    bid = str(biz["id"])
    user = plan.get("user")
    if kind == "off":
        return _with(res, plan["said"], ask_state="not_asked")
    if not entry_id:
        return res
    if kind == "none":
        if plan.get("follow") and user is not None:
            await asyncio.to_thread(_follow, bid, entry_id, user)
        return res
    if kind != "go":
        return res
    ev = _ev()
    words: List[str] = []
    out: Dict[str, Any] = {}
    flyer = plan.get("flyer")
    if flyer and flyer != "make":
        try:
            got = await ev.attach_flyer(bid, entry_id, user, artwork_id=flyer)
            out["flyer"] = "on" if got.get("flyer") else "not_on"
            words.append("The flyer is on the event." if got.get("flyer") else
                         "The event is saved, but the flyer didn't go on. Try it again on the event's Volunteers "
                         "and flyer.")
        except Exception as e:  # noqa: BLE001 — the event is saved either way
            out["flyer"] = "not_on"
            words.append(f"The event is saved, but the flyer didn't go on: {_lower(_said(e))}")
    if plan.get("needs"):
        try:
            got = await asyncio.to_thread(ev.ask, entry_id, {"business_id": bid, "needs": plan["needs"],
                                                             "note": plan.get("note") or ""}, user)
            state = (got.get("request") or {}).get("status")
            out["ask"] = state
            if state == ev.ON:
                words.append(f"It's on Who serves when now, with {plan['said_teams']}. The teams' asks go out from "
                             "there.")
            else:
                who = _who_gets_it(plan.get("status") or {})
                words.append(f"Asked the serving teams for {plan['said_teams']}. {who}")
        except Exception as e:  # noqa: BLE001 — the event is saved either way
            out["ask"] = "not_asked"
            words.append(f"The event is saved, but the serving teams weren't asked: {_lower(_said(e))}")
    if plan.get("skip"):
        out["ask"] = "already"
        words.append(plan["skip"])
    if plan.get("make"):
        words.append(plan["make"])
    await asyncio.to_thread(_follow, bid, entry_id, user)
    final = _with(res, " ".join(words), ask_state=out.get("ask"), flyer_state=out.get("flyer"))
    # Kept for the rest of the turn: the same event sent again gets this answer.
    _DONE.set(_DONE.get() + (((plan.get("target"), plan.get("raw")), final),))
    return final


def _with(res: Dict[str, Any], said: str, *, ask_state: Optional[str] = None,
          flyer_state: Optional[str] = None) -> Dict[str, Any]:
    """The save's own result, with `said` after it: in the result and where
    to find it, and Chief told to say it in those words."""
    if not said:
        return res
    out = dict(res)
    out["result"] = f"{res.get('result') or 'saved'}. {said}"
    out["where"] = f"{res.get('where') or ''} {said}".strip()
    out["volunteers_said"] = said
    if ask_state:
        out["teams_ask"] = ask_state
    if flyer_state:
        out["flyer_state"] = flyer_state
    told = (f"Say this in these words: {said} The event itself is saved. Don't say the serving teams were asked "
            "or a flyer is on unless these words say so.")
    out["note_for_chief"] = f"{res.get('note_for_chief') or ''} {told}".strip()
    return out


def after_setup(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """chief_build_runtime folds an events room's create into one setup
    that runs in the background with nobody signed in, so it can't ask the
    teams or put a flyer on: a receipt that says so, in plain words."""
    what = [w for w, on in (("the serving teams weren't asked", entry.get("teams") not in (None, "", [], {})),
                            ("no flyer was put on", entry.get("flyer") not in (None, "", [], {}))) if on]
    if not what:
        return None
    return {"type": "event_volunteers", "_after_setup": " and ".join(what)}


# ─── The read: how full is my event ───────────────────────────────────

def _find(biz_id: str, action: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """(the event's entry id, or the words that say why there isn't one).
    By its id, or by its name among the events rooms' entries: one that's
    coming up before one that's past; two of the same name are named back
    with their days, never guessed between."""
    ev, sp = _ev(), _sp()
    raw = _plain(action.get("entry_id"))
    if raw:
        if not _UUID.match(raw):
            return None, "That isn't an event's id. Name the event instead."
        return raw.lower(), None
    said = _key(action.get("event") or action.get("title") or action.get("name"))
    if not said:
        return None, "Which event? Name it, as the Youth Lock-in."
    import events_rsvp_router as er
    mods = er.roster_modules_for(biz_id)
    if not mods:
        return None, "There's no events room here yet."
    room = mods[0].get("name") if len(mods) == 1 else None
    rows = ev._read(f"/module_entries?business_id=eq.{ev._q(biz_id)}&module_id=in.({ev._ids(m['id'] for m in mods)})"
                    "&status=eq.active&select=id,module_id,status,data&order=created_at.desc&limit=500")
    zone = sp._zone(biz_id)
    today = sp._now().astimezone(zone).date()
    by_mod = {str(m["id"]): {**m, "is_active": True} for m in mods}
    want = _stem(said)
    hits = []
    for r in rows:
        mod = by_mod.get(str(r.get("module_id")))
        if mod:
            ent = ev.entry_view(r, mod, zone)
            if want and want in _stem(_key(ent["title"])):
                hits.append(ent)
    # Its whole name before a part of one ("Lock-in" is the Youth Lock-in
    # only when no event is called just that).
    pool = [h for h in hits if _stem(_key(h["title"])) == want] or hits
    if not pool:
        return None, (f"There's no event called “{_fence(action.get('event') or said)[:60]}” in "
                      f"{room or 'the events rooms'}.")
    if len(pool) == 1:
        return pool[0]["entry_id"], None
    soon = sorted((h for h in pool if h["day"] is not None and h["day"] >= today),
                  key=lambda h: (h["day"], h["at"].timestamp() if h["at"] else 0))
    # One event that repeats (one name, several days): the next one. Two
    # different events, or none coming up: named back, never guessed between.
    if soon and len({_key(h["title"]) for h in soon}) == 1:
        return soon[0]["entry_id"], None
    named = _join([f"{h['title']} ({_when(h)})" for h in (soon or pool)[:5]])
    return None, f"Which one: {named}?"


def _slot_words(slots: List[Dict[str, Any]], pending: bool) -> str:
    """A team place's spots. The names are the church's contacts, which a
    stranger may have typed (the booking widget): fenced, and anything
    shaped like an instruction raises the turn's taint (defuse)."""
    yes = [s for s in slots if s["state"] == "yes"]
    asked = [s for s in slots if s["state"] == "asked"]
    open_ = [s for s in slots if s["state"] == "open"]
    if pending:
        return f"{len(slots)} asked for, nobody asked yet"
    bits = [f"{len(yes)} of {len(slots)}"]
    names = [_fence(s["name"]) for s in yes if s.get("name")]
    if names:
        bits[0] += f" ({', '.join(names)})"
    if asked:
        who = [_fence(s["name"]) for s in asked if s.get("name")]
        bits.append(f"{len(asked)} asked" + (f" ({', '.join(who)})" if who else ""))
    if open_:
        bits.append(f"{len(open_)} open")
    return ", ".join(bits)


def ask_words(req: Optional[Dict[str, Any]], date: Optional[Dict[str, Any]]) -> Tuple[str, bool]:
    """(where the ask to the serving teams stands, whether someone else's
    words came in: a note)."""
    if not req:
        if date:
            return "It's on Who serves when (added there, with no ask).", False
        return "The serving teams haven't been asked.", False
    s = req.get("status")
    who, by = req.get("asked_by_name") or "Someone", req.get("decided_by_name") or "whoever schedules the teams"
    note = req.get("note") or ""
    if s == "waiting":
        line = f"{who} asked the serving teams; it's waiting for whoever schedules the teams to say yes."
    elif s == "on":
        line = f"It's on Who serves when: {by} put it on."
    elif s == "declined":
        said = req.get("decided_note") or ""
        line = f"{by} couldn't staff it with the teams" + (f": “{_fence(said)}”." if said else ".")
        return line, bool(said or note)
    elif s == "withdrawn":
        line = "The ask to the serving teams was taken back."
    else:
        line = "The ask to the serving teams was closed when the event changed."
    if note and s in ("waiting", "on"):
        line += f" The note with it: “{_fence(note)}”."
    return line, bool(note and s in ("waiting", "on"))


def _role_parts(special: List[Dict[str, Any]]) -> Tuple[List[str], bool]:
    """Each of the event's own roles, filled against needed, with the people
    on it. Their names are typed by members and the public (the member app,
    the events page): someone else's words, fenced, and the turn's taint
    is raised when any is shown."""
    parts, foreign = [], False
    for r in special:
        yes = min(len(r.get("people") or []), r["needed"])
        ticks = [w for k, w in (("kids", "works with kids"), ("open", "anyone can sign up")) if r.get(k)]
        names = []
        for p in r.get("people") or []:
            n = _fence(p.get("name") or "Someone")
            foreign = True
            names.append(f"{n} ({p['check']})" if p.get("check") else n)
        part = f"{r['label']}" + (f" ({', '.join(ticks)})" if ticks else "") + f": {yes} of {r['needed']}"
        if names:
            part += f" ({', '.join(names)})"
        if r["needed"] > yes:
            part += f", {r['needed'] - yes} open"
        parts.append(part)
    return parts, foreign


def _cut(text: str) -> str:
    if len(text) <= RESULT_MAX:
        return text
    return text[:RESULT_MAX - 80].rsplit(";", 1)[0] + "; the rest is on the event's own page."


def fill_words(title: str, when: str, pic: Dict[str, Any]) -> Tuple[str, bool]:
    """The picture in church words: one count across both kinds, each place
    and role, what's open, and the ask. (words, someone else's words came in)."""
    ev = _ev()
    c = pic.get("counts") or {}
    lines = [f"{ev.The(title)}, {when}: {c.get('yes', 0)} of {c.get('all', 0)} volunteers so far"
             + (f" ({c.get('teams_yes', 0)} of {c.get('teams_needed', 0)} from the serving teams and "
                f"{c.get('special_yes', 0)} of {c.get('special_needed', 0)} by sign-up)."
                if c.get("teams_needed") and c.get("special_needed") else ".")]
    said, foreign = ask_words(pic.get("request"), pic.get("date"))
    lines.append(said)
    teams = pic.get("teams") or []
    if teams:
        lines.append("Serving teams: " + "; ".join(
            f"{t['name']} ({t['team']}): {_slot_words(t['slots'], bool(t.get('pending')))}" for t in teams) + ".")
    special = pic.get("special") or []
    if special:
        parts, named = _role_parts(special)
        foreign = foreign or named
        lines.append("Special volunteers: " + "; ".join(parts) + ".")
    if not teams and not special:
        lines.append("It has no volunteers asked for yet.")
    lines.append("It has a flyer." if pic.get("flyer") else "It has no flyer yet.")
    return _cut(" ".join(lines)), foreign


def roles_words(title: str, when: str, ent: Dict[str, Any], biz_id: str) -> Tuple[str, bool, int, int]:
    """Where asking the serving teams isn't open (or not a church): the
    event's own roles and sign-ups, as its room shows them, and nothing of
    the serving teams. (words, someone else's words came in, yes, needed)."""
    import events_rsvp_router as er
    signups = er.read_signups(ent["data"], ent["signups_field"])
    special = []
    for role in ent["roles"]:
        fill = er.role_fill(role, signups)
        special.append({"label": fill["label"], "needed": fill["needed"], "kids": role.get("kids") is True,
                        "open": role.get("open") is True,
                        "people": [{"name": _plain(s.get("name")) or "Someone"} for s in signups
                                   if s.get("role") == role.get("id") and (s.get("status") or "yes") == "yes"]})
    ev = _ev()
    if not special:
        return f"{ev.The(title)}, {when}, has no volunteer roles yet.", False, 0, 0
    parts, foreign = _role_parts(special)
    yes = sum(min(len(r["people"]), r["needed"]) for r in special)
    need = sum(r["needed"] for r in special)
    text = f"{ev.The(title)}, {when}: {yes} of {need} volunteers so far. " + "; ".join(parts) + "."
    if ev.flyer_of(ent["data"], biz_id, ent["entry_id"]):
        text += " It has a flyer."
    return _cut(text), foreign, yes, need


def _read_fill(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    """The read, in its thread. Its `_taint` is what defuse found here (this
    thread's own copy of the turn's count, which the turn never sees) and one
    for someone else's words shown, for the handler to raise on the turn."""
    before = _taint_now()
    out = _read(biz, action)
    out["_taint"] = max(0, _taint_now() - before) + (1 if out.pop("_foreign", False) else 0)
    return out


def _read(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "event_volunteers"
    if action.get("_unattended"):
        return _fail(atype, "an event's volunteers are read only when someone at the church asks.")
    if action.get("_after_setup"):
        said = AFTER_SETUP.format(what=_plain(action["_after_setup"])[:120])
        return {"result": said, "label": said}
    ev = _ev()
    user = turn_user(action)
    bid = str(biz["id"])
    asking = user is not None and open_here(bid, user)
    try:
        eid, why = _find(bid, action)
        if not eid:
            return _fail(atype, why or "Which event?")
        zone = _sp()._zone(bid)
        if asking:
            pic = ev.picture(eid, bid, user)
        ent = ev.event_entry(bid, eid, zone)
    except HTTPException as e:
        if not asking and e.status_code == 404:
            return _fail(atype, "that event isn't one of the events here.")
        return _fail(atype, _lower(_said(e)))
    from system_destinations import module_destination
    nav = module_destination({"id": ent["module_id"], "archetype": "event_roster"})
    if asking:
        text, foreign = fill_words(ent["title"], _when(ent), pic)
        c = pic.get("counts") or {}
        yes, all_ = c.get("yes", 0), c.get("all", 0)
    else:
        text, foreign, yes, all_ = roles_words(ent["title"], _when(ent), ent, bid)
    return {"result": text, "label": f"{ent['title']}: {yes} of {all_} volunteers"[:80], "nav": nav,
            "_foreign": foreign}


def _fail(atype: str, msg: str) -> Dict[str, Any]:
    said = msg[:1].upper() + msg[1:]
    return {"type": atype, "result": f"Failed: {said}", "label": said[:120], "failed": True}


async def handle_event_volunteers(client, biz, action) -> Dict[str, Any]:
    out = await asyncio.to_thread(_read_fill, biz, dict(action or {}))
    # Raised on the turn's own context: what the read's thread found (its
    # own copy of the count is lost with the thread) and someone else's
    # words it showed.
    _bump(int(out.pop("_taint", 0) or 0))
    return {"type": "event_volunteers", **out}


HANDLERS = {"event_volunteers": handle_event_volunteers}
PROGRESS = {"event_volunteers": "reading the event's volunteers"}


# ─── The turn's line ──────────────────────────────────────────────────

LINE = ("EVENT VOLUNTEERS (on here, in Services & Events). Making or changing an event, ask whether it needs our "
        "regular serving teams (which places, how many) or special volunteers (its own roles), and a flyer. Beside "
        '"data" on create_module_entry / update_module_entry: "teams":[{"place":"Greeters","n":2}] (no n: its '
        'Sunday number; a place the serving teams fill goes here, never in roles), "teams_note", "flyer": a gallery '
        'picture\'s id or "make", and a role may say "kids":true (works with kids) or "open":true (anyone can sign '
        "up on the public page). The first send saves nothing and shows what saving will do: say it to them in its "
        f"words. {AGAIN} event_volunteers reads how full an event is.\n")
READ_LINE = ("EVENT VOLUNTEERS: event_volunteers reads how full an event in Services & Events is; this login reads "
             "it and doesn't ask the serving teams.\n")


def turn_line(business: Dict[str, Any], user_id: Any) -> str:
    """The short block for this turn's tail, only where asking is open for
    the church and this login (event_volunteers.enabled) and the login works
    the office (its own gate, _login); the read-only line for a Viewer; ''
    otherwise and on any failure. In the tail, never a cached segment: the
    switch's owner mode opens it by login, and a Viewer's line differs."""
    try:
        ev = _ev()
        if not user_id or ev.mode() == "off" or not ev.ready():
            return ""
        from auth_supabase import AuthedUser
        import chief_church_schedule as ccs
        user = AuthedUser(id=str(user_id), email=ccs._email(str(user_id)) or "", role="authenticated")
        bid = str((business or {}).get("id") or "")
        if not bid or not open_here(bid, user):
            return ""
        me = ev._login(bid, user)
        return READ_LINE if me["role"] == "viewer" else LINE
    except Exception as e:  # noqa: BLE001 — a read that fails leaves it out, never the turn
        if not isinstance(e, HTTPException):
            print(f"[chief_event_volunteers] the turn's line wasn't read: {type(e).__name__}", flush=True)
        return ""
