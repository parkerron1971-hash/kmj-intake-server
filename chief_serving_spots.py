"""chief_serving_spots.py — Chief fills an open serving spot, through the serving page's own routes.

Kevin, 2026-11-26 (through KAI): "start the serving-spot skill as you proposed": Chief could see an open
spot on the volunteers' week ("the 9:00 sound spot is open") but couldn't ask anyone to take it. The
serving page (Who serves when, sunday_planning) already asks one person, offers a spot to the whole team,
takes an ask back and fills the coming weeks. These are those buttons, from a chat:

    serving_spot .......... {day?, time?, place?}: one service's spots for a place, who holds each, and
                            who on the team could take one, best first (the page's own order: free and not
                            away, trained before learning, fewest Sundays that month). No place: the open
                            spots that day on the teams this login schedules. Changes nothing.
    ask_to_serve .......... {day?, time?, place, person, slot?}: ask one person on the team.
    offer_serving_spot .... {day?, time?, place, slot?}: offer it to everyone on the team who's trained
                            and free; the first yes takes it.
    take_back_serving_ask . {day?, time?, place, person?} | {fill: true}: take an ask back (never a yes),
                            or a fill's asks that haven't gone out yet.
    fill_serving_spots .... {weeks?, team?}: ask people for every open spot in the coming weeks, fairly.

NEVER A RULE OF ITS OWN. Every write IS the page's route, called as the signed-in login
(sunday_planning.ask, offer, take_back, fill, unfill): its switch (_gate), who may schedule which team
(_scheduler, _place_gate: the owner and Admins every team, otherwise the duties that schedule a team's
door), and its checks before anything is written (on the team, not away that Sunday, not on another place
at that hour, the team's Sundays a month, a yes is never overwritten). The read is the page's own board
(_Board.candidates) behind the same gates as the ask, so Chief only suggests where it could ask. Chief adds
one rule that only narrows: it never takes back someone's yes (taking someone off a Sunday they agreed to
is a conversation first, then the page), as a team's own leader can't either (sunday_leading.take_back).

ASKED IS NOT FILLED. An ask goes out on the serving sweep (every 15 minutes, outside the church's quiet
hours), so until then it can be taken back unseen. Every receipt says the spot is asked and waiting for
an answer, never that it is filled.

THE SWITCH. CHIEF_SERVING_SPOTS = off | owner (the default: the platform owner's own church, Love City
first, as church_skills' owner mode) | on. Under it, the page's own SUNDAY_PLANNING. Someone signed in at
the keyboard, never an unattended run or an outside agent (registry chief_only; action tags, never native
write tools). A write on a tainted turn waits for the person to say it again. How to use them rides the
turn's tail only where it is open (turn_line), never a cached segment.

Names are the church's own records (its people and its teams). A spot's note is someone's own words and
is never read here.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

NAV = {"tab": "operate", "sub": "serve-schedule"}
NOT_ON = "Asking people to serve through Chief isn't switched on for this church yet."
PAGE_OFF = "Who serves when isn't switched on here yet."
SEND_WORDS = "It goes out on the next send, within about 15 minutes and outside the church's quiet hours"
WRITES = frozenset({"ask_to_serve", "offer_serving_spot", "take_back_serving_ask", "fill_serving_spots"})
READS = frozenset({"serving_spot"})
VERBS = tuple(sorted(READS | WRITES))
SHOW_FREE = 8               # people who could take a spot, at most, in a read
SHOW_NOT = 6                # people who can't, at most
FILL_IDS_MAX = 400          # the unfill route's own limit
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m?\.?\s*$", re.I)

TOOL = {
    "name": "serving_spot",
    "description": ("Only where the turn's SERVING SPOTS line shows: one service's serving spots for a place (who "
                    "holds each: open, asked, said yes) and who on the team could take an open one, best first, as "
                    "Who serves when shows them. With no place: the open spots that day. Changes nothing. For "
                    "\"who could do sound Sunday?\" or \"what's still open this Sunday?\"."),
    "input_schema": {"type": "object", "properties": {
        "day": {"type": "string", "description": "The service's day, YYYY-MM-DD; the coming Sunday unless said"},
        "time": {"type": "string", "description": "The service's time, as 9:00am, when that day has more than one"},
        "place": {"type": "string", "description": "The spot, as Sound or Greeters, or \"Team: Place\""}}},
}


# ─── Small things ─────────────────────────────────────────────────────

def _sp():
    import sunday_planning
    return sunday_planning


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _join(words: List[str]) -> str:
    words = [w for w in words if w]
    if len(words) <= 2:
        return " and ".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def _key(v: Any) -> str:
    from chief_event_volunteers import _key as key
    return key(v)


def _stem(k: str) -> str:
    from chief_event_volunteers import _stem as stem
    return stem(k)


def _first(name: Any) -> str:
    return _plain(name).split(" ")[0] or "them"


def _clock(hhmm: str) -> str:
    """'09:00' → '9:00am', '18:30' → '6:30pm'."""
    try:
        h, m = (int(x) for x in str(hhmm).split(":")[:2])
    except (TypeError, ValueError):
        return str(hhmm or "")
    return f"{(h % 12) or 12}:{m:02d}{'am' if h < 12 else 'pm'}"


def _when(svc: Dict[str, Any]) -> str:
    """'Sunday, Nov 29 at 9:00am (Sunday service)'."""
    try:
        d = date.fromisoformat(svc["day"])
        day = f"{d.strftime('%A')}, {d.strftime('%b')} {d.day}"
    except (KeyError, TypeError, ValueError):
        day = str(svc.get("day") or "that day")
    title = _plain(svc.get("title"))
    return f"{day} at {_clock(svc.get('time') or '')}" + (f" ({title})" if title else "")


def _short(svc: Dict[str, Any]) -> str:
    try:
        d = date.fromisoformat(svc["day"])
        return f"{d.strftime('%a')} {d.strftime('%b')} {d.day} {_clock(svc.get('time') or '')}"
    except (KeyError, TypeError, ValueError):
        return str(svc.get("day") or "")


def _fail(atype: str, msg: str) -> Dict[str, Any]:
    said = _plain(msg)
    said = (said[:1].upper() + said[1:]) if said else "That couldn't be done just now."
    return {"type": atype, "result": f"Failed: {said}", "label": said[:120], "failed": True, "nav": NAV}


def _said(e: HTTPException, atype: str) -> str:
    """A refusal in the page's own words; a write adds that nothing changed."""
    words = _plain(e.detail)
    if e.status_code == 404 and words in ("Not Found", "business not found"):
        return PAGE_OFF
    if e.status_code >= 500 or not words:
        return "That couldn't be done just now. Try again in a minute."
    words = words if words[-1:] in ".?!" else words + "."
    return f"{words} Nothing changed." if atype in WRITES else words


# ─── The switch, and who is at the keyboard ───────────────────────────

def mode() -> str:
    m = (os.environ.get("CHIEF_SERVING_SPOTS") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def church_open(business_id: Any) -> bool:
    """Off; the platform owner's own church (member_asks.platform_church, kept ten minutes); or every church.
    A read that fails is a no."""
    m = mode()
    if m == "off" or not business_id:
        return False
    if m == "on":
        return True
    try:
        import member_asks
        return bool(member_asks.platform_church(business_id))
    except Exception:  # noqa: BLE001 — can't tell: off
        return False


def _tainted() -> bool:
    try:
        from chief_of_staff import untrusted_taint
        return bool(untrusted_taint())
    except Exception:  # noqa: BLE001 — unread is not a yes
        return True


def _open(atype: str, biz: Any, action: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str, Any]:
    """(a refusal or None, the church's id, the signed-in login as an AuthedUser). Someone signed in, never
    unattended; the switch (off: nothing is read); a church; the switch open for it; the page's own switch
    for this login; and only then a write on a tainted turn held."""
    if action.get("_unattended"):
        return _fail(atype, "serving spots are asked for only when someone at the church asks."), "", None
    import chief_church_assignments as cca
    uid = cca._turn_user()
    if not uid:
        return _fail(atype, "serving spots are for someone signed in to the church's office."), "", None
    if mode() == "off":
        return _fail(atype, NOT_ON), "", None
    import sb_clients
    bid = str((biz or {}).get("id") or "")
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_sp()._q(bid)}&select=id,type,settings&limit=1")
    if not isinstance(rows, list):
        return _fail(atype, "the church couldn't be read just now. Try again in a minute."), "", None
    import church_follow_up as cfu
    if not rows or not cfu.is_church(rows[0]):
        return _fail(atype, "serving spots are for churches."), "", None
    if not church_open(bid):
        return _fail(atype, NOT_ON), "", None
    import chief_church_schedule as ccs
    email = ccs._email(uid) if _sp().mode() == "owner" else ""
    if email is None:
        return _fail(atype, "whether Who serves when is on couldn't be checked just now. Try again."), "", None
    from auth_supabase import AuthedUser
    user = AuthedUser(id=uid, email=email or "", role="authenticated")
    if not _sp().open_to(user):
        return _fail(atype, PAGE_OFF), "", None
    if atype in WRITES and _tainted():
        return ({"type": atype, "failed": True, "needs_confirmation": True, "nav": NAV,
                 "result": ("Failed: HELD — something read this turn was someone else's words, so this waits for "
                            "the person. Read back exactly who and which spot, and ask them to say it again; then "
                            "send the same tag. Don't say anyone was asked."),
                 "label": "Before I ask anyone to serve, say it once more. Nobody has been asked yet."}, "", None)
    return None, bid, user


# ─── Naming the service, the spot and the person ─────────────────────

def _coming_sunday(bid: str) -> str:
    sp = _sp()
    today = sp._now().astimezone(sp._zone(bid)).date()
    return sp._sunday_on_or_after(today).isoformat()


def _time_of(raw: Any) -> Optional[str]:
    """'9', '9am', '9:30 pm', '18:00' → 'HH:MM'; None when it isn't a time."""
    s = _plain(raw).lower()
    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    m = _TIME.match(s)
    if m:
        h, mins = int(m.group(1)), int(m.group(2) or 0)
        if 1 <= h <= 12 and mins < 60:
            h = (h % 12) + (12 if m.group(3).lower() == "p" else 0)
            return f"{h:02d}:{mins:02d}"
    m = re.match(r"^(\d{1,2})$", s)
    if m and int(m.group(1)) < 24:
        return f"{int(m.group(1)):02d}:00"
    return None


def _service(bid: str, action: Dict[str, Any]):
    """(the page's board for that week, the one service asked for). A day with no service, or more than one
    and no time or title that picks one, is a 400 that names what is there."""
    sp = _sp()
    day = _plain(action.get("day")) or _coming_sunday(bid)
    if not _DAY.match(day):
        raise HTTPException(400, "Say the day as a date, like 2026-11-29")
    try:
        date.fromisoformat(day)
    except ValueError:
        raise HTTPException(400, "Say the day as a date, like 2026-11-29")
    board = sp._Board(bid, day, 1)
    that_day = [s for s in board.services if s["day"] == day]
    if not that_day:
        later = [s for s in board.services if s["day"] > day][:3]
        tail = f" The next {'is' if len(later) == 1 else 'are'} {_join([_when(s) for s in later])}." if later else ""
        raise HTTPException(400, f"Nothing is on Who serves when on {day}.{tail}")
    if len(that_day) == 1:
        return board, that_day[0]
    said = _plain(action.get("time"))
    at = _time_of(said) if said else None
    # "9" or "9:30" may mean the afternoon too; "9am" and "18:00" mean only what they say (Codex review).
    either = bool(at) and not re.search(r"[ap]\.?\s*m?\.?\s*$", said.lower()) and int(at[:2]) < 12 and (
        ":" not in said or int(said.split(":")[0]) < 12)
    hits = [s for s in that_day if at and (s["time"] == at or (either and s["time"] ==
                                                                f"{int(at[:2]) + 12:02d}{at[2:]}"))]
    if not hits and said:
        k = _stem(_key(said))
        hits = [s for s in that_day if k and k in _stem(_key(s.get("title")))]
    if len(hits) == 1:
        return board, hits[0]
    raise HTTPException(400, f"That day has {_join([_when(s) for s in that_day])}: say which time")


def _place(board, svc: Dict[str, Any], raw: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(its team, the place) among the teams serving at this service, by name: any case, singular or plural,
    "Team: Place" or "Place (Team)" when two teams have one, or a team that has one place. Never guessed."""
    sp = _sp()
    said = _plain(raw)
    if not said:
        raise HTTPException(400, "Which spot? Say the place, as Sound or Greeters")
    teams = [t for t in board.teams if sp.serves(svc, t)]
    pairs = [(t, p) for t in teams for p in t["places"]]
    if not pairs:
        raise HTTPException(400, "No serving team has places for that service yet")
    team_said, place_said = "", said
    m = re.match(r"^(.+?)\s*\((.+)\)\s*$", said)
    if m:
        place_said, team_said = m.group(1), m.group(2)
    elif ":" in said:
        team_said, _, place_said = said.partition(":")
    want = _stem(_key(place_said))
    hits = [(t, p) for t, p in pairs if _stem(_key(p["name"])) == want]
    if team_said:
        hits = [(t, p) for t, p in hits if _stem(_key(t["name"])) == _stem(_key(team_said))]
    if not hits:
        whole = [(t, p) for t, p in pairs if _stem(_key(t["name"])) == want]
        if len(whole) == 1:
            hits = whole
    if len(hits) == 1:
        return hits[0]
    if hits:
        both = _join([t["name"] + ": " + p["name"] for t, p in hits])
        raise HTTPException(400, f"“{said[:60]}” could be {both}: say which, as "
                                 f"\"{hits[0][0]['name']}: {hits[0][1]['name']}\"")
    names = _join([f"{p['name']} ({t['name']})" for t, p in pairs][:15])
    raise HTTPException(400, f"“{said[:60]}” isn't a place on the teams serving then. They are: {names}")


def _spots(board, svc: Dict[str, Any], place: Dict[str, Any]) -> List[Tuple[int, Optional[Dict[str, Any]]]]:
    import serve_dates as sd
    return [(slot, board.holder(svc["id"], place["id"], slot)) for slot in range(1, sd.needed(svc, place) + 1)]


def _is_open(row: Optional[Dict[str, Any]]) -> bool:
    """A spot nobody holds: no row, or a no."""
    return row is None or row.get("status") == "no"


def _names(team: Dict[str, Any]) -> Dict[str, str]:
    return {str(p["contact_id"]): p["name"] for p in team.get("people") or []}


def _spot_words(row: Optional[Dict[str, Any]], names: Dict[str, str]) -> str:
    if row is None:
        return "open"
    status = row.get("status")
    who = names.get(str(row.get("contact_id") or ""), "someone")
    if status == "offered":
        return "offered to the team, nobody has taken it yet"
    if status == "asked":
        return f"{who}, asked, " + ("waiting for an answer" if row.get("notified_at") else "not sent yet")
    if status == "yes":
        return f"{who}, said yes"
    if status == "no":
        return f"open ({who} said no)"
    return f"{who}, {status or 'on it'}"


def _person(team: Dict[str, Any], raw: Any) -> Dict[str, Any]:
    """One person on the team, by what was said; anyone else is the page's to add first."""
    import chief_church_assignments as cca
    rows = [{"id": str(p["contact_id"]), "name": p["name"], "why": team["name"]} for p in team.get("people") or []]
    if not _plain(raw):
        raise HTTPException(400, "Who should be asked? Say their name")
    if not rows:
        raise HTTPException(400, f"Nobody is on {team['name']} yet. Add people to the team on Who serves when first")
    try:
        return cca.pick(rows, raw)
    except HTTPException as e:
        if "isn't anyone you can act for" in str(e.detail) or "nobody is under you" in str(e.detail):
            raise HTTPException(400, f"“{_plain(raw)[:60]}” isn't on {team['name']}. Add them to the team on Who "
                                     f"serves when first, or ask someone who is on it")
        raise


def _slot(action: Dict[str, Any], spots: List[Tuple[int, Optional[Dict[str, Any]]]], place: Dict[str, Any],
          names: Dict[str, str]) -> int:
    """The spot asked for, else the first open one. None open: a 400 that says who holds each."""
    raw = action.get("slot")
    if raw not in (None, ""):
        if isinstance(raw, bool) or not isinstance(raw, (int, str)) or not str(raw).strip().isdigit():
            raise HTTPException(400, "The spot is a number, as 1 or 2")
        return int(raw)
    free = [slot for slot, row in spots if _is_open(row)]
    if free:
        return free[0]
    held = "; ".join(f"spot {slot}: {_spot_words(row, names)}" for slot, row in spots)
    raise HTTPException(409, f"Every {place['name']} spot then is taken ({held}). To ask someone else, take an "
                             f"ask back first")


# ─── The read ─────────────────────────────────────────────────────────

def _read_spot(bid: str, user: Any, action: Dict[str, Any]) -> Dict[str, Any]:
    sp = _sp()
    sp._gate(user)
    board, svc = _service(bid, action)
    who = sp._scheduler(bid, user)
    when = _when(svc)
    if not _plain(action.get("place")):
        mine = [t for t in board.teams if sp.serves(svc, t) and (not who["office"] or t["owner"] in who["owners"])]
        lines, n_open = [], 0
        for t in mine:
            names = _names(t)
            for p in t["places"]:
                spots = _spots(board, svc, p)
                free = sum(1 for _, row in spots if _is_open(row))
                if free:
                    n_open += free
                    lines.append(f"- {p['name']} ({t['name']}): {free} of {len(spots)} open; "
                                 + "; ".join(f"spot {s}: {_spot_words(r, names)}" for s, r in spots))
        if not mine:
            raise HTTPException(403, sp._refusal(bid, sp.VOLUNTEERS))
        head = f"Open serving spots, {when}: {n_open}" + ("" if n_open else ", every spot is asked or taken")
        return {"result": "\n".join([head + "."] + lines), "label": f"{n_open} open, {_short(svc)}"[:80]}
    team, place = _place(board, svc, action.get("place"))
    sp._place_gate(bid, who, team["group_id"])
    names = _names(team)
    spots = _spots(board, svc, place)
    if not spots:
        raise HTTPException(409, f"{place['name']} isn't needed for {svc.get('title') or 'that service'}")
    holding = {str(r.get("contact_id")) for _, r in spots if r and r.get("status") in ("asked", "yes")}
    free, cant = [], []
    for c in board.candidates(svc["id"], place["id"]):
        if c["contact_id"] in holding:
            continue
        if c["ok"]:
            how = {"trained": "trained", "learning": "still learning it"}.get(c["trained"], "not trained for it yet")
            free.append(f"{c['name']} ({how}, {c['load']} Sunday{'' if c['load'] == 1 else 's'} this month)")
        else:
            why = ("away that day" if c["away"] else f"already on {c['clash']} then" if c["clash"]
                   else f"at {c['load']} of {c['at_most']} Sundays this month")
            cant.append(f"{c['name']} ({why})")
    lines = [f"{place['name']} ({team['name']}), {when}: "
             + "; ".join(f"spot {s}: {_spot_words(r, names)}" for s, r in spots) + "."]
    if free:
        lines.append("Could take it, best first: " + "; ".join(free[:SHOW_FREE])
                     + (f"; and {len(free) - SHOW_FREE} more" if len(free) > SHOW_FREE else "") + ".")
    else:
        lines.append(f"Nobody on {team['name']} is free for it.")
    if cant:
        lines.append("Can't: " + "; ".join(cant[:SHOW_NOT]) + (f"; and {len(cant) - SHOW_NOT} more"
                                                              if len(cant) > SHOW_NOT else "") + ".")
    return {"result": "\n".join(lines), "label": f"{place['name']}, {_short(svc)}"[:80]}


# ─── The writes: the page's own routes ────────────────────────────────

def _mine(bid: str, user: Any, action: Dict[str, Any]):
    """(board, service, team, place), once the page says this login may change that team: its own
    _scheduler and _place_gate, before anything about who holds the spot is said. The route checks again."""
    sp = _sp()
    sp._gate(user)
    board, svc = _service(bid, action)
    who = sp._scheduler(bid, user)
    team, place = _place(board, svc, action.get("place"))
    sp._place_gate(bid, who, team["group_id"])
    return board, svc, team, place


def _ask(bid: str, user: Any, action: Dict[str, Any]) -> Dict[str, Any]:
    sp = _sp()
    board, svc, team, place = _mine(bid, user, action)
    names = _names(team)
    person = _person(team, action.get("person"))
    spots = _spots(board, svc, place)
    already = next((s for s, r in spots if r and str(r.get("contact_id")) == person["id"]
                    and r.get("status") in ("asked", "yes")), None)
    if already:
        raise HTTPException(409, f"{person['name']} is already on {place['name']} then: "
                                 f"{_spot_words(dict(spots)[already], names)}")
    slot = _slot(action, spots, place, names)
    out = sp.ask({"business_id": bid, "service_id": svc["id"], "position_id": place["id"], "contact_id": person["id"],
                  "slot": slot}, user)
    warn = _plain((out or {}).get("assignment", {}).get("warning"))
    said = (f"Asked {person['name']} to serve {place['name']} ({team['name']}), {_when(svc)}. {SEND_WORDS}, and "
            f"until they answer it's asked, not filled: they haven't said yes yet.")
    if warn:
        said += f" Note: {warn}."
    return {"result": said, "label": f"Asked {_first(person['name'])}: {place['name']}, {_short(svc)}"[:80]}


def _offer(bid: str, user: Any, action: Dict[str, Any]) -> Dict[str, Any]:
    sp = _sp()
    board, svc, team, place = _mine(bid, user, action)
    names = _names(team)
    slot = _slot(action, _spots(board, svc, place), place, names)
    sp.offer({"business_id": bid, "service_id": svc["id"], "position_id": place["id"], "slot": slot}, user)
    return {"result": (f"Offered {place['name']} ({team['name']}), {_when(svc)}, to everyone on the team who's "
                       f"trained and free. The first yes takes it. {SEND_WORDS}; until someone says yes it's still "
                       f"open."),
            "label": f"Offered {place['name']}, {_short(svc)}"[:80]}


def _take_back_unless_yes(bid: str, user: Any, aid: str, name: str) -> None:
    """The page's take back (sunday_planning.take_back: its _gate, _scheduler and _asked_gate, then the delete),
    with the delete kept to an ask or an offer still unanswered, so a yes given after Chief looked is never
    removed (Codex review: the route's own delete doesn't look at the status, and a team's leader may never
    take back a yes either). A row still there after the delete said yes in between: a 409, nothing removed."""
    sp = _sp()
    import sb_clients
    sp._gate(user)
    who = sp._scheduler(bid, user)
    sp._asked_gate(bid, who, sp._assignment(bid, aid))
    where = f"/serve_assignments?id=eq.{sp._q(aid)}&business_id=eq.{sp._q(bid)}"
    if not sb_clients.sb_delete_as_service(where + "&status=in.(asked,offered)"):
        raise HTTPException(503, "That didn't save. Try again.")
    if sp._read(where + "&select=status&limit=1"):
        raise HTTPException(409, f"{name or 'They'} just said yes. Talk with them first; taking someone off a Sunday "
                                 f"they agreed to is done on Who serves when")


def _fill_asks(bid: str) -> List[str]:
    """The asks a fill made that haven't gone out yet and nobody answered (the unfill route keeps only those
    on the teams this login schedules)."""
    sp = _sp()
    rows = sp._read(f"/serve_assignments?business_id=eq.{sp._q(bid)}&asked_by=eq.{sp._q(sp.FILLED_BY)}"
                    f"&status=eq.asked&notified_at=is.null&select=id&limit={FILL_IDS_MAX}")
    return [str(r["id"]) for r in rows]


def _take_back(bid: str, user: Any, action: Dict[str, Any]) -> Dict[str, Any]:
    sp = _sp()
    sp._gate(user)
    if action.get("fill") is True:
        ids = _fill_asks(bid)
        if not ids:
            return {"result": ("No asks from a fill are waiting to go out. Any that went out already stay, and are "
                               "taken back one at a time."), "label": "Nothing to take back"}
        n = int((sp.unfill({"business_id": bid, "ids": ids}, user) or {}).get("taken_back") or 0)
        return {"result": (f"Took back {n} ask{'' if n == 1 else 's'} from the fill that hadn't gone out yet. "
                           + ("Asks that went out already stay." if n else "None of them were on teams you schedule.")),
                "label": f"Took back {n} fill ask{'' if n == 1 else 's'}"[:80]}
    board, svc, team, place = _mine(bid, user, action)
    names = _names(team)
    rows = [r for _, r in _spots(board, svc, place) if r and r.get("status") in ("asked", "offered", "yes")]
    if _plain(action.get("person")):
        pick = _person(team, action.get("person"))
        rows = [r for r in rows if str(r.get("contact_id") or "") == pick["id"]]
        if not rows:
            raise HTTPException(400, f"{pick['name']} isn't asked for {place['name']} then")
    if not rows:
        raise HTTPException(400, f"Nobody is asked for {place['name']} then")
    if len(rows) > 1:
        raise HTTPException(400, f"{place['name']} then has {_join([_spot_words(r, names) for r in rows])}: say whose "
                                 f"ask to take back")
    row = rows[0]
    who = names.get(str(row.get("contact_id") or ""), "")
    if row.get("status") == "yes":
        raise HTTPException(409, f"{who or 'They'} already said yes. Talk with them first; taking someone off a "
                                 f"Sunday they agreed to is done on Who serves when")
    _take_back_unless_yes(bid, user, str(row["id"]), who)
    what = f"the ask to {who}" if row.get("status") == "asked" else "the offer to the team"
    sent = " It had already gone out, so they may have seen it." if row.get("notified_at") else ""
    return {"result": f"Took back {what} for {place['name']} ({team['name']}), {_when(svc)}. The spot is open again.{sent}",
            "label": f"Took back {place['name']}, {_short(svc)}"[:80]}


def _fill(bid: str, user: Any, action: Dict[str, Any]) -> Dict[str, Any]:
    sp = _sp()
    sp._gate(user)
    sp._scheduler(bid, user)        # a login that schedules no team hears the page's refusal before any team's name
    raw = action.get("weeks", 4)
    weeks = int(raw) if isinstance(raw, int) and not isinstance(raw, bool) else (
        int(raw) if isinstance(raw, str) and raw.strip().isdigit() else raw)
    body: Dict[str, Any] = {"business_id": bid, "weeks": weeks}
    team_name = ""
    if _plain(action.get("team")):
        teams, _ = sp._teams(bid)
        want = _stem(_key(action["team"]))
        hits = [t for t in teams if _stem(_key(t["name"])) == want]
        if len(hits) != 1:
            raise HTTPException(400, f"“{_plain(action['team'])[:60]}” isn't one of the Sunday teams. They are: "
                                     f"{_join([t['name'] for t in teams][:15])}")
        body["group_id"], team_name = hits[0]["group_id"], hits[0]["name"]
    out = sp.fill(body, user) or {}
    n, left = int(out.get("asked") or 0), int(out.get("still_open") or 0)
    where = f" on {team_name}" if team_name else " on the teams you schedule"
    if not n:
        said = (f"Nobody was asked{where}: no open spot over the next {weeks} weeks has someone trained, free that "
                f"hour, not away and under their Sundays a month." + (f" {left} spot{'' if left == 1 else 's'} "
                                                                       f"still need someone asked by name." if left else ""))
    else:
        said = (f"Asked people for {n} open spot{'' if n == 1 else 's'}{where} over the next {weeks} weeks: only "
                f"people trained for the spot, free that hour and not away, the most rested first. "
                + (f"{left} spot{'' if left == 1 else 's'} still have nobody who fits; those need someone asked by "
                   f"name. " if left else "")
                + f"Nothing goes out until the next send, within about 15 minutes, so the whole fill can still be "
                  f"taken back. Each spot is asked, not filled, until they answer.")
    return {"result": said, "label": f"Asked for {n} spot{'' if n == 1 else 's'}"[:80]}


BODIES = {"serving_spot": _read_spot, "ask_to_serve": _ask, "offer_serving_spot": _offer,
          "take_back_serving_ask": _take_back, "fill_serving_spots": _fill}


def _run(atype: str, biz: Any, action: Any) -> Dict[str, Any]:
    action = action if isinstance(action, dict) else {}
    try:
        refused, bid, user = _open(atype, biz, action)
        if refused:
            return refused
        return {"type": atype, "nav": NAV, **BODIES[atype](bid, user, action)}
    except HTTPException as e:
        return _fail(atype, _said(e, atype))
    except Exception as e:  # noqa: BLE001 — a failure is said, never a blank screen
        print(f"[chief_serving_spots] {atype} failed: {type(e).__name__}", flush=True)
        return _fail(atype, "That couldn't be done just now. Try again in a minute."
                     + (" Nothing changed." if atype in WRITES else ""))


def _handler(atype: str):
    async def handle(client, biz, action) -> Dict[str, Any]:
        return await asyncio.to_thread(_run, atype, biz, action or {})
    handle.__name__ = f"handle_{atype}"
    handle.__qualname__ = handle.__name__
    return handle


HANDLERS = {verb: _handler(verb) for verb in VERBS}
PROGRESS = {
    "serving_spot": "reading the serving spots", "ask_to_serve": "asking them to serve",
    "offer_serving_spot": "offering the spot to the team", "take_back_serving_ask": "taking the ask back",
    "fill_serving_spots": "asking people for the open spots",
}


# ─── The turn's block ─────────────────────────────────────────────────

BLOCK = (
    "SERVING SPOTS (on here; page Who serves when). serving_spot (day, time, place) reads who holds each spot at "
    "one service and who on the team could take it, best first; with no place, the open spots that day. Tags, for "
    "the signed-in person, only once they have said yes to who and which spot:\n"
    '[ACTION:{"type":"ask_to_serve","day":"2026-11-29","time":"9:00am","place":"Sound","person":"Maria Diaz"}]\n'
    '[ACTION:{"type":"offer_serving_spot","day":"2026-11-29","place":"Greeters"}] — to everyone on the team who\'s '
    "trained and free; the first yes takes it.\n"
    '[ACTION:{"type":"take_back_serving_ask","day":"2026-11-29","place":"Sound","person":"Maria Diaz"}] — or '
    '{"type":"take_back_serving_ask","fill":true} for a fill\'s asks not yet sent. Never a yes.\n'
    '[ACTION:{"type":"fill_serving_spots","weeks":4,"team":"Greeters"}] — only when they ask to fill the coming '
    "weeks.\n"
    "An ask goes out on the next send (about 15 minutes). Say it is asked and waiting for their answer, never that "
    "the spot is filled.\n")


def turn_line(business: Dict[str, Any], user_id: Any) -> str:
    """The block for this turn's tail, only where Chief may ask people to serve for this church and the login
    has an office seat there (the page's own checks decide the rest); '' otherwise and on any failure."""
    try:
        if not user_id or mode() == "off" or _sp().mode() == "off":
            return ""
        import church_follow_up as cfu
        if not cfu.is_church(business or {}) or not church_open((business or {}).get("id")):
            return ""
        import chief_church_assignments as cca
        import church_over as co
        if co.Church(business).role(str(user_id)) not in cca.OFFICE_SEATS:
            return ""
        return BLOCK
    except Exception as e:  # noqa: BLE001 — a read that fails leaves it out, never the turn
        print(f"[chief_serving_spots] the turn's block wasn't read: {type(e).__name__}", flush=True)
        return ""


def turn_ready(business_id: Any) -> bool:
    """For church_skills' needs: whether serving spots are open for this church at all."""
    return mode() != "off" and _sp().mode() != "off" and church_open(business_id)
