"""chief_church_roles.py — Chief puts people into a church's leader roles, and
takes them off, when someone at the church asks (docs/CHURCH_LEADERS_STEP2.md
§4, `ask_into_role`, B6).

Kevin, 2026-11-13: "allow for chief to be able to place people in leaders
position in the system so upon request, chief can do it."

    ask_into_role ... {who, role, team?}: asks one of the church's people into
                      one of its saved roles (a team leader's role names the
                      Serve card's team), as Leaders & roles' "Ask" does: the
                      row starts asked, they get an email with what the role is
                      and who they'd answer to, and they say yes on their member
                      page, where the Lead tab opens. Asked again, nothing new
                      is sent
    take_off_role ... {who, role?, team?} or {row_id}: takes them off it, as the
                      page's Remove does. An ask they haven't answered is taken
                      back; a role they said yes to goes with what it handed them
                      (church_follow_up.remove_role says what went back where)

Both call the Leaders & roles routes' own functions (church_router.leader_add
and leader_remove: church_follow_up.add_role, send_invite and remove_role), so
every rule is the page's: a draft role is saved first, an office role is an
office login (Settings → Team), a kids or youth leader is approved on Kids
check-in with their background check, a role that needs a class needs it
finished, and the person is one of the church's own people. The seat is the
page's too: the owner, an Admin or a Manager (church_router.CARE_MIN_ROLE,
through business_access's own role_of and rank). Roles and asks have no
feature switch on the page, and none here.

The church's people are its members, never its clients: every line here says
member or the person's name.

Someone signed in, never an unattended run, a church. A turn whose context held
instruction-shaped text from something Chief read (chief_of_staff.untrusted_taint)
is held by the class C gate (_gate_class_c), which reads back who and which role
(_confirmation_subject) and lets this exact action through on the person's "go
ahead"; the handlers don't hold it again, or that go-ahead could never run it
(#1831 review). Action tags, never native write tools (chief_only: they need the
signed-in person). An ask sends an email, so both are class C: Chief does them when it is
asked to, never on its own idea. "Undo that" after an ask puts nothing back:
no inverse may be class C (action_inverse.NOT_UNDOABLE_REASON
says why). Taking an ask back is take_off_role when they say so, with the
same who and role and only_if_asked (or the ask's row_id), which refuses once
they've said yes; the email itself can't be unsent, and the receipt says so.

Names resolve as change_map's do (chief_map._Names): a role by its title or
key (an id that is none of the church's roles is refused); a person by a whole
name, a first name only one person has, or a role's title and a last name. To
take someone off, the role holders come first, then the church's people. To
ask, everyone at the church counts at once: the person asked usually holds no
role yet, so a first name two people share asks which (#1831 review). None, or
more than one, changes nothing and says who it could be.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

import sb_clients

NAV = {"tab": "operate", "sub": "leaders"}
WRITES = frozenset({"ask_into_role", "take_off_role"})
MIN_ROLE = "manager"            # church_router.CARE_MIN_ROLE: the Leaders & roles routes' seat
NOT_YOURS = ("putting people into roles is for the church's owner, its admins and its Manager logins, as on "
             "Leaders & roles.")


# ─── Small things ─────────────────────────────────────────────────────

def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _fold(v: Any) -> str:
    return _plain(v).casefold().replace("’", "'")


def _first(name: str) -> str:
    return (_plain(name).split(" ") or [""])[0] or "They"


def _fail(atype: str, msg: str, **more: Any) -> Dict[str, Any]:
    return {"type": atype, "result": f"Failed: {msg}", "label": msg[:80], "failed": True, "nav": NAV, **more}


def _uuid(v: Any) -> Optional[str]:
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, TypeError, AttributeError):
        return None


def _q(v: Any) -> str:
    from urllib.parse import quote
    return quote(str(v), safe="")


def _turn_user() -> str:
    from chief_of_staff import _TURN_USER_ID
    return str(_TURN_USER_ID.get() or "")


def _open(atype: str, biz: Any, action: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any], str]:
    """(a refusal or None, the church's row, the person). Someone signed in,
    not an unattended run, a church, and the Leaders & roles routes' seat (a
    tainted turn is the class C gate's to hold). A read that fails raises
    503."""
    if action.get("_unattended"):
        return _fail(atype, "people are put into roles only when someone at the church asks."), {}, ""
    uid = _turn_user()
    if not uid:
        return _fail(atype, "putting people into roles is for someone signed in to the church's office."), {}, ""
    bid = _uuid((biz or {}).get("id"))
    if not bid:
        return _fail(atype, "no church on record."), {}, ""
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(bid)}&select=id,name,type,owner_id,settings&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "The church couldn't be read just now. Try again.")
    import church_follow_up as cfu
    if not rows or not cfu.is_church(rows[0]):
        return _fail(atype, "leader roles are for churches."), {}, ""
    import business_access as ba
    seat = ba._resolve_role(bid, uid)           # the routes' own: business_access(CARE_MIN_ROLE)
    if not seat or ba._rank(seat) < ba._rank(MIN_ROLE):
        return _fail(atype, NOT_YOURS), {}, ""
    return None, rows[0], uid


def _names(bid: str):
    from chief_map import _Names
    return _Names(bid)


def _def_of(names: Any, rid: str) -> Dict[str, Any]:
    return next((d for d in names.defs if str(d.get("id")) == rid), {})


def _role_def(names: Any, raw: Any) -> Dict[str, Any]:
    """The church's role a request names; a 400 when it is none of them (_Names takes any well-formed id as
    given, so an id that isn't one of this church's roles is refused here, #1831 review)."""
    d = _def_of(names, names.role(raw))
    if not d:
        raise HTTPException(400, f"There’s no role called “{_plain(raw)}” here")
    return d


def _ask_person(names: Any, bid: str, raw: Any) -> str:
    """The person to ask: a whole name, or a first name only one of the church's people has, among everyone at
    once (holders first would ask Ruth Okafor, who holds a role, when Ruth Jones, who holds none, was meant: an
    ask's person usually holds no role yet, and its email can't be unsent; #1831 review). None found this way:
    _Names' own (a role's title and a last name, "Deacon Moore")."""
    import church_map as cm
    from chief_map import _norm
    w = _norm(raw)
    if _uuid(w):
        return names.person(raw)
    pat = "*".join(re.sub(r"[*%\\]", "", x).replace("_", "\\_") for x in w.split(" ")) + "*"
    rows = cm._need(f"/contacts?business_id=eq.{cm._q(bid)}&name=ilike.{cm._q(pat)}"
                    "&select=id,name&order=id.asc&limit=1000")
    if len(rows) >= 1000:
        raise HTTPException(400, f"Too many people here are called “{_plain(raw)}” to tell apart: say their whole name")
    hit = names._named({str(r["id"]): _plain(r.get("name")) for r in rows}, w)
    if len(hit) > 1:
        said = sorted({n for _c, n in hit})
        raise HTTPException(400, f"“{_plain(raw)}” could be {', '.join(said[:-1])} or {said[-1]}" if len(said) > 1
                            else f"More than one person here is called “{_plain(raw)}”: say which")
    return hit[0][0] if hit else names.person(raw)


def _same_team(a: Any, b: Any) -> bool:
    """The same team, case and the word "team" aside ("hospitality" is the Hospitality Team)."""
    def bare(v: Any) -> str:
        return _fold(re.sub(r"(?i)\bteam\b", "", _plain(v))).strip()
    return bool(_plain(a)) and (_fold(a) == _fold(b) or bare(a) == bare(b))


def _team(bid: str, raw: Any, held: List[str]) -> str:
    """The Serve card's team a team leader's role names (the page's picker), in the card's own spelling, else
    one a holder row already names; a 400 listing them when it is none of those."""
    import church_follow_up as cfu
    got = cfu.teams(bid)
    if got is None:
        raise HTTPException(503, "The Serve card's teams couldn't be read just now. Try again.")
    want = _fold(raw)
    choices = list(dict.fromkeys([_plain(t) for t in got] + [_plain(t) for t in held if _plain(t)]))
    hit = next((t for t in choices if _fold(t) == want), None) or next(
        (t for t in choices if _same_team(raw, t)), None)
    if not hit:
        said = "; ".join(choices) if choices else "none yet (add them to the Serve card)"
        raise HTTPException(400, f"“{_plain(raw)}” isn’t one of the teams on your Serve card. The teams: {said}")
    return hit


def _what(d: Dict[str, Any], scope: str, church: str) -> str:
    """"Love City's Intercessor leader" / "the Hospitality Team's leader" """
    import church_follow_up as cfu
    name = cfu.role_name({"role": d.get("key"), "scope": scope, "def": d})
    return f"{name}'s leader" if d.get("covers") == "team" else f"{church}'s {name}"


# ─── ask_into_role ────────────────────────────────────────────────────

async def handle_ask_into_role(client, biz, action) -> Dict[str, Any]:
    atype = "ask_into_role"
    action = action if isinstance(action, dict) else {}
    try:
        refused, business, uid = await asyncio.to_thread(_open, atype, biz, action)
        if refused:
            return refused
        bid = str(business["id"])
        church = _plain(business.get("name")) or "the church"
        who, role = action.get("who") or action.get("person"), action.get("role")
        if not _plain(who):
            return _fail(atype, "say who to ask: their name.")
        if not _plain(role):
            return _fail(atype, "say which role: one of the church's roles on Leaders & roles.")
        names = await asyncio.to_thread(_names, bid)
        d = await asyncio.to_thread(_role_def, names, role)
        rid = str(d["id"])
        cid = await asyncio.to_thread(_ask_person, names, bid, who)
        scope = ""
        if d.get("covers") == "team":
            raw = action.get("team") or action.get("scope")
            if not _plain(raw):
                return _fail(atype, f"{d.get('title') or 'That role'} leads a team: say which team.")
            held = [str(h.get("scope") or "") for h in names.holders if h.get("role") == d.get("key")]
            scope = await asyncio.to_thread(_team, bid, raw, held)
        import church_follow_up as cfu
        row = await asyncio.to_thread(cfu.add_role, bid, cid, rid, scope, by_user=uid)
    except HTTPException as e:
        return _fail(atype, f"{_plain(e.detail).rstrip('.')}. Nothing changed.")
    person = row.get("person") or {}
    name = person.get("name") or _plain(who)
    first = _first(name)
    d = row.get("def") or d
    what = _what(d, scope, church)
    base = {"type": atype, "person": cid, "role": d.get("key") or "", "team": scope,
            "row_id": str(row.get("id") or ""), "status": row.get("status") or "", "nav": NAV}
    if row.get("already"):
        if row.get("status") == "active":
            said = f"{name} is already {what}: nothing new was sent."
        else:
            said = (f"{name} was already asked to be {what} and hasn't said yes yet: nothing new was sent. "
                    f"{first} says yes on their member page.")
        return {**base, "changed": False, "emailed": False, "result": said,
                "label": f"{first}: already {'holds' if row.get('status') == 'active' else 'asked into'} "
                         f"{d.get('title') or 'the role'}"[:80]}
    try:
        emailed = bool(await cfu.send_invite(business, row))
    except Exception:  # noqa: BLE001 — the ask saved; the email is said plainly either way
        emailed = False
    try:
        from chief_map import _map_open
        map_on = await asyncio.to_thread(_map_open, uid, bid) is True
    except Exception:  # noqa: BLE001 — a line of the receipt, never the ask
        map_on = False
    lines = [f"Asked {name} to be {what}. The role is asked, not held yet: {first} says yes on their member page, "
             "and their Lead tab opens then. Until they do, whatever comes through the role passes them by."]
    if emailed:
        lines.append(f"{first} was emailed what the role is and who they'd answer to.")
    elif person.get("email"):
        lines.append(f"The email to {first} didn't go out: tell them yourself that they were asked.")
    else:
        lines.append(f"There's no email on file for {first}, so nobody told them: tell them yourself, or add their "
                     "email to their record.")
    if map_on:          # the map is behind CHURCH_MAP: offer it only where change_map would run (#1831 review)
        lines.append("To make them a department's leader or overseer too, change the leaders map: it takes "
                     "someone asked who hasn't said yes yet.")
    lines.append("The ask can be taken back while it's unanswered; an email that went can't be unsent.")
    return {**base, "changed": True, "emailed": emailed, "result": " ".join(lines),
            "label": f"Asked {first} into {d.get('title') or 'the role'}"[:80],
            "note_for_chief": ("Say they were asked, never that they said yes or that they're the leader now. They "
                               "are one of the church's members, never a client. To take this ask back (\"undo "
                               "that\"), send take_off_role with the same who and role (and team) and "
                               "only_if_asked: true.")}


# ─── take_off_role ────────────────────────────────────────────────────

def _rows_for(bid: str, cid: str, key: Optional[str]) -> List[Dict[str, Any]]:
    path = (f"/church_leader_roles?business_id=eq.{_q(bid)}&contact_id=eq.{_q(cid)}&status=in.(invited,active)"
            + (f"&role=eq.{_q(key)}" if key else "") + "&select=id,contact_id,role,scope,status&limit=50")
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, "Their roles couldn't be read just now. Try again.")
    return rows


def _led(bid: str, cid: str) -> List[str]:
    """The departments this person leads or oversees on the leaders map, for the receipt; none when it can't be
    read (the map's own gaps say it then)."""
    try:
        import church_map as cm
        m = cm._map(bid)
        return [d["name"] for d in m.departments if cid in (d.get("leader_contact_id"), d.get("overseer_contact_id"))]
    except Exception:  # noqa: BLE001 — a line of the receipt, never the change
        return []


async def handle_take_off_role(client, biz, action) -> Dict[str, Any]:
    atype = "take_off_role"
    action = action if isinstance(action, dict) else {}
    try:
        refused, business, _uid = await asyncio.to_thread(_open, atype, biz, action)
        if refused:
            return refused
        bid = str(business["id"])
        church = _plain(business.get("name")) or "the church"
        names = await asyncio.to_thread(_names, bid)
        rid_in = _uuid(action.get("row_id"))
        if rid_in:
            got = await asyncio.to_thread(
                sb_clients.sb_get_as_service,
                f"/church_leader_roles?id=eq.{_q(rid_in)}&business_id=eq.{_q(bid)}"
                "&select=id,contact_id,role,scope,status&limit=1")
            if not isinstance(got, list):
                raise HTTPException(503, "That role couldn't be read just now. Try again.")
            if not got or got[0].get("status") not in ("invited", "active"):
                return _fail(atype, "that ask or role is already gone. Nothing changed.")
            row = got[0]
            cid = str(row["contact_id"])
        else:
            who = action.get("who") or action.get("person")
            if not _plain(who):
                return _fail(atype, "say whose role: their name.")
            cid = await asyncio.to_thread(names.person, who)
            key = None
            if _plain(action.get("role")):      # a role named that is none of the church's is refused, never "any"
                key = str((await asyncio.to_thread(_role_def, names, action.get("role"))).get("key") or "") or None
                if not key:
                    raise HTTPException(400, f"There’s no role called “{_plain(action.get('role'))}” here")
            rows = await asyncio.to_thread(_rows_for, bid, cid, key)
            team = action.get("team") or action.get("scope")
            if _plain(team):
                rows = [r for r in rows if _same_team(team, r.get("scope"))]
            if not rows:
                return _fail(atype, f"they don't hold {'that role' if key else 'a role'} here and weren't asked "
                                    "into one. Nothing changed.")
            if len(rows) > 1:
                import church_follow_up as cfu
                said = "; ".join(cfu.role_name({**r, "def": next((d for d in names.defs if d.get("key") ==
                                                                   r.get("role")), {})}) for r in rows)
                return _fail(atype, f"they hold more than one: {said}. Say which role (and team).")
            row = rows[0]
        if action.get("only_if_asked") and row.get("status") != "invited":
            return _fail(atype, "they already said yes, so undo would take the role away. Say \"take them off\" "
                                "the role if you mean that. Nothing changed.")
        d = next((x for x in names.defs if x.get("key") == row.get("role")), {})
        people = await asyncio.to_thread(names_of, bid, cid)
        import church_follow_up as cfu
        out = await asyncio.to_thread(cfu.remove_role, bid, str(row["id"]))
    except HTTPException as e:
        return _fail(atype, f"{_plain(e.detail).rstrip('.')}. Nothing changed.")
    name = people or "They"
    first = _first(name)
    what = _what(d or {"key": row.get("role")}, str(row.get("scope") or ""), church)
    base = {"type": atype, "person": cid, "role": row.get("role") or "", "row_id": str(row["id"]),
            "changed": True, "nav": NAV}
    went = []
    for k, said in (("returned", "follow-up{s} to the office"), ("prayer_returned", "prayer request{s} to Prayer "
                                                                                     "& care"),
                    ("tasks_returned", "open task{s} to whoever handed them out")):
        n = int(out.get(k) or 0)
        if n:
            went.append(f"{n} {said.format(s='' if n == 1 else 's')}")
    if row.get("status") == "invited":
        # An ask hands nothing (remove_role keeps their work when the row was only asked), so nothing should go
        # back; if anything did, the receipt says so rather than hide it (#1831 review).
        said = (f"Took back the ask: {name} won't be {what}. If the email reached {first}, it can't be unsent, so "
                "tell them it was taken back.")
        if went:
            said += " Also went back: " + ", ".join(went) + "."
        return {**base, "was": "asked", "returned": out, "result": said, "label": f"Took back {first}'s ask"[:80]}
    lines = [f"Took {name} off {what}."]
    lines.append(("What it handed them went back: " + ", ".join(went) + ".") if went else "Nothing went back.")
    if int(out.get("failed") or 0):
        lines.append("Some of it couldn't be moved just now; the next sweep moves it.")
    led = _led(bid, cid)
    if led:
        lines.append(f"{first} is still named on the leaders map for {', '.join(led)}: unless another role of theirs "
                     "covers it, that place now needs someone (change the leaders map).")
    lines.append(f"Putting {first} back means asking them again; they say yes again on their member page.")
    return {**base, "was": "held", "returned": out, "result": " ".join(lines),
            "label": f"Took {first} off {d.get('title') or 'the role'}"[:80]}


def names_of(bid: str, cid: str) -> str:
    import church_follow_up as cfu
    got = cfu._contacts(bid, [cid]) or {}
    return (got.get(cid) or {}).get("name") or ""


HANDLERS = {"ask_into_role": handle_ask_into_role, "take_off_role": handle_take_off_role}
PROGRESS = {"ask_into_role": "asking them into the role", "take_off_role": "taking them off the role"}
