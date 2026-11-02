"""chief_duties.py — Chief reads and moves a church's duties.

Kevin, 2026-11-01 (Love City's office checkup): "give chief the ability to
make adjustment and help the churches make adjustments like these … you would
make the changes for love city directly but chief would do other churches".
docs/CHURCH_DUTIES.md, step 3.

A church's owner tells Chief "Jessica does the monthly report now". Chief
moves the duty the way Logins & areas → Duties does, through the same
function, and answers with the record: what moved, from whom to whom, that
it's logged, and that undo_duty puts it back.

    list_duties ..... who does each duty, grouped by lane: follows the lanes
                      (and who that is today) or moved to whom, and which need
                      someone; then the office logins by name. Any login that
                      may read the duties page (a Manager seat or above).
                      There are no money amounts here
    move_duty ....... {duty, to: [names or login ids]}; [] puts it back to the
                      lanes. The owner or an Admin only. Names resolve to the
                      church's active logins exactly (a full name, or a first
                      name only one login has); an unknown or shared name
                      changes nothing. Then church_duties.move(), the PUT's own
                      code: a money duty only to the owner or an Admin login,
                      never a Member or Viewer, logged, the same names again
                      changing nothing
    undo_duty ....... {duty}: the last change back (church_duties.undo()); with
                      change_id (undo_last's inverse) only while that change
                      is still the last one
    jobs_line() ..... "Their jobs here: …" for a church login that isn't the
                      owner or an Admin, in the THIS LOGIN block
                      (chief_areas.turn_for, block)

Switched with the routes: CHURCH_DUTIES (off | owner | on). Owner is the
platform owner's own login, as church_duties.open_to says for the routes,
read by the signed-in person's id. Off: Chief says duties aren't on yet.
jobs_line() isn't switched: the job gates read duties whatever it says.

Action tags only, never native write tools: mcp_server.WRITE_TOOL_SCHEMAS is
also the outside agent's list and carries no signed-in person, and each of
these needs one (registry chief_only). list_duties is a mid-turn read.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

import church_duties as cd

NAV = {"tab": "operate", "sub": "areas"}
NOT_ON = "Duties aren't switched on here yet, so Chief can't read or move them."
NOT_YOURS = "Moving a duty is the owner's or an admin's."
_ROLE_WORDS = {"owner": "owner", "admin": "Admin", "manager": "Manager", "member": "Member", "viewer": "Viewer"}
_RANK = {"viewer": 1, "member": 2, "manager": 3, "admin": 4, "owner": 5}

TOOL = {
    "name": "list_duties",
    "description": (
        "A church's duties: who does each office job (the weekly text, the Monday leaders note, meetings, rooms, "
        "the care board, the Sunday plan, posts, the monthly report, the books and the rest), grouped by lane; "
        "whether each follows the lanes or was moved to named logins; which need someone; and the office logins "
        "by name. Use it before saying whose job something is, and before move_duty so the names are real."),
    "input_schema": {"type": "object", "properties": {}},
}


# ─── Small things ─────────────────────────────────────────────────────

def _fail(atype: str, msg: str) -> Dict[str, Any]:
    return {"type": atype, "result": f"Failed: {msg}", "label": msg[:80], "failed": True, "nav": NAV}


def _norm(v: Any) -> str:
    return " ".join(str(v or "").split()).casefold()


def _join(words: List[str]) -> str:
    words = [w for w in words if w]
    if len(words) < 2:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def _turn_user() -> str:
    from chief_of_staff import _TURN_USER_ID
    return str(_TURN_USER_ID.get() or "")


# The signed-in person's email, by id, for the switch's owner mode. Kept per
# process: an email rarely changes, and a failed read isn't kept.
_EMAILS: Dict[str, str] = {}


def _switched_on(uid: str) -> Optional[bool]:
    """Whether the duties are on for this person, as the routes decide it
    (church_duties.open_to). None when owner mode can't read who they are."""
    m = cd.mode()
    if m == "on":
        return True
    if m != "owner" or not uid:
        return False
    if uid not in _EMAILS:
        try:
            import platform_suite
            _EMAILS[uid] = platform_suite._owner_email(uid) or ""
        except Exception:  # noqa: BLE001 — unread is not a yes
            return None
    return cd.open_to(SimpleNamespace(email=_EMAILS[uid]))


def _role(business: Dict[str, Any], uid: str) -> Optional[str]:
    if str(business.get("owner_id") or "") == uid:
        return "owner"
    return (cd._seat(str(business["id"]), uid) or {}).get("role") or None


def _open(atype: str, business_id: str, least: str) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any], str]:
    """(a refusal or None, the church's row, the person's role). The person
    talking must be signed in, the switch on for them, the business a church
    and their role `least` or above. A read that fails raises 503."""
    uid = _turn_user()
    if not uid:
        return _fail(atype, "duties are read and moved only by someone signed in to the church's office."), {}, ""
    on = _switched_on(uid)
    if on is None:
        return _fail(atype, "whether duties are on couldn't be checked just now. Try again."), {}, ""
    if not on:
        return _fail(atype, NOT_ON), {}, ""
    business = cd._business(business_id)
    if not cd._is_church(business):
        return _fail(atype, cd.NOT_CHURCH + "."), {}, ""
    role = _role(business, uid) or ""
    if _RANK.get(role, 0) < _RANK[least]:
        if least == "admin":
            return _fail(atype, NOT_YOURS), business, role
        return _fail(atype, "the duties are for the church's owner, its admins and its Manager logins."), business, role
    return None, business, role


def find_duty(raw: Any) -> Optional[str]:
    """A duty's key from its key or its label ("the monthly report")."""
    w = _norm(raw)
    for k in (w, w.replace(" ", "_").replace("-", "_")):
        if k in cd.CATALOG:
            return k
    bare = re.sub(r"^the ", "", w)
    return next((k for k, d in cd.CATALOG.items() if re.sub(r"^the ", "", _norm(d["label"])) == bare), None)


def _no_such_duty(raw: Any) -> str:
    return (f"there's no duty called “{str(raw or '').strip()}”. The duties: "
            + "; ".join(f"{d['label']} ({k})" for k, d in cd.CATALOG.items()) + ".")


def resolve(logins: List[Dict[str, Any]], wanted: List[Any]) -> Tuple[List[str], List[str]]:
    """(login ids, problems) for the names or ids asked for. A name is a
    login's whole name, or its first name when only one login has it; an id
    is a login's own. Never a guess: none, or more than one, is a problem."""
    ids: List[str] = []
    problems: List[str] = []
    for raw in wanted:
        w = _norm(raw)
        if not w:
            continue
        try:
            as_id: Optional[str] = str(uuid.UUID(w))
        except ValueError:
            as_id = None
        if as_id:
            hit = [x for x in logins if x["user_id"] == as_id]
        else:
            hit = [x for x in logins if _norm(x["name"]) == w]
            if not hit and " " not in w:
                hit = [x for x in logins if _norm(x["name"]).split(" ")[0] == w]
        if len(hit) == 1:
            if hit[0]["user_id"] not in ids:
                ids.append(hit[0]["user_id"])
        elif not hit:
            problems.append(f"no login on this church's office is named “{str(raw).strip()}”")
        else:
            problems.append(f"“{str(raw).strip()}” could be {_join([x['name'] for x in hit])}")
    return ids, problems


def _entry(page: Dict[str, Any], duty: str) -> Dict[str, Any]:
    return next(d for d in page["duties"] if d["key"] == duty)


def _lanes_words(d: Dict[str, Any]) -> str:
    labels = d.get("lane_labels") or [cd.lane_label(ln) for ln in d["lanes"]]
    return f"the {_join(labels)} lane" + ("s" if len(labels) > 1 else "")


def _who(d: Dict[str, Any]) -> str:
    """Who does one duty now, in words: the lanes' defaults (and who that is
    today) or the logins it was moved to."""
    active = [h["name"] for h in d["holders"] if h["active"]]
    gone = [h["name"] for h in d["holders"] if not h["active"]]
    if d["follows_lanes"]:
        who = _join(active) if active else "no Manager has it, so the owner and the admins"
        return f"{_lanes_words(d)}, by default ({who})"
    text = _join(active) if active else "nobody who can do it now, so only the owner and the admins"
    if gone:
        text += f" (named but can't do it now: {_join(gone)})"
    return text


def _who_short(d: Dict[str, Any]) -> str:
    """The same, short, for one line of the list under its lane's heading."""
    active = [h["name"] for h in d["holders"] if h["active"]]
    gone = [h["name"] for h in d["holders"] if not h["active"]]
    if d["follows_lanes"]:
        return "lanes: " + (", ".join(active) if active else "no Manager has it, so the owner and the admins")
    text = "moved to " + (", ".join(active) if active else "nobody who can do it now")
    return text + (f" (named but can't do it now: {', '.join(gone)})" if gone else "")


def _logins_words(page: Dict[str, Any]) -> str:
    out = []
    for x in page["logins"]:
        if x.get("role") not in ("owner", "admin", "manager"):
            continue
        lanes = [cd.lane_label(ln) for ln in x.get("lanes") or []]
        out.append(f"{x['name']} ({', '.join([_ROLE_WORDS.get(x['role'], x['role'])] + lanes)})")
    return "; ".join(out)


def _first(name: str) -> str:
    return name if "@" in name else (name.split(" ")[0] if name else name)


# ─── list_duties ──────────────────────────────────────────────────────

def list_sync(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "list_duties"
    try:
        refused, business, _ = _open(atype, business_id, "manager")
        if refused:
            return refused
        page = cd.build(business)
    except HTTPException as e:
        return _fail(atype, str(e.detail))
    church = " ".join(str(business.get("name") or "").split()) or "this church"
    lines = [f"Who does what at {church}. The owner and every Admin login do every duty, money ones too. "
             "\"lanes:\" is who does a duty by default, from the lanes; \"moved to\" is who the church named."]
    by_lane: Dict[str, List[Dict[str, Any]]] = {}
    for d in page["duties"]:
        by_lane.setdefault(d["lanes"][0], []).append(d)
    for lane in cd.LANE_KEYS:
        if lane not in by_lane:
            continue
        lines.append(f"{cd.lane_label(lane)}:")
        for d in by_lane[lane]:
            also = [cd.lane_label(ln) for ln in d["lanes"][1:]]
            tags = [d["key"], d["day"]] + (["money"] if d["money"] else []) + ([f"also {_join(also)}"] if also else [])
            lines.append(f"- {d['label']} ({'; '.join(tags)}): {_who_short(d)}.")
    needs = [_entry(page, k)["label"] for k in page["needs_someone"]]
    if needs:
        lines.append("Needs someone (moved to logins that can't do it now; only the owner and the admins do it "
                     f"until someone is named or it goes back to the lanes): {_join(needs)}.")
    lines.append(f"Office logins: {_logins_words(page)}.")
    moved = [d["key"] for d in page["duties"] if not d["follows_lanes"]]
    label = "Who does what" + (f" · {len(needs)} need someone" if needs else f" · {len(moved)} moved" if moved else "")
    return {"type": atype, "result": "\n".join(lines), "label": label, "nav": NAV,
            "moved": moved, "needs_someone": list(page["needs_someone"]),
            "note_for_chief": (
                "Say whose job a duty is from this, by name. Only the owner or an admin moves one (move_duty, the "
                "whole list of who does it; [] puts it back to the lanes); a money duty only to the owner or an "
                "Admin login. If moving one is your idea, suggest it and ask first.")}


async def handle_list_duties(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(list_sync, str((biz or {}).get("id") or ""), action or {})


# ─── move_duty ────────────────────────────────────────────────────────

def _record(verb: str, label: str, before: Dict[str, Any], after: Optional[Dict[str, Any]],
            names: List[str]) -> str:
    now = _who(after) if after is not None else (_join(names) if names else "the lanes, by default")
    head = {"move": f"Moved “{label}”.", "back": f"Put “{label}” back to the lanes.",
            "undo": f"Put back the last change to “{label}”."}[verb]
    tail = ("It's in the duties' change log; undo_duty again puts back the change before it, if there is one."
            if verb == "undo" else "It's in the duties' change log, and undo_duty puts it back.")
    return f"{head} Before: {_who(before)}. Now: {now}. The owner and every Admin still do it too. {tail}"


def move_sync(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "move_duty"
    if action.get("_unattended"):
        return _fail(atype, "a duty moves only when the owner or an admin asks for it.")
    try:
        refused, business, _ = _open(atype, business_id, "admin")
        if refused:
            return refused
        duty = find_duty(action.get("duty"))
        if not duty:
            return _fail(atype, _no_such_duty(action.get("duty")))
        label = cd.CATALOG[duty]["label"]
        if "to" not in action or action.get("to") is None:
            return _fail(atype, f"say who does “{label}” now (their names), or [] to put it back to the lanes.")
        wanted = action["to"] if isinstance(action["to"], list) else [action["to"]]
        before_page = cd.build(business)
        ids, problems = resolve(before_page["logins"], wanted)
        if problems:
            return _fail(atype, "; ".join(problems) + f". Nothing changed. The office logins: "
                         f"{_logins_words(before_page)}.")
        if wanted and not ids:
            return _fail(atype, f"say who does “{label}” now (their names), or [] to put it back to the lanes.")
        before = _entry(before_page, duty)
        try:
            out = cd.move(business, duty, ids, _turn_user())
        except HTTPException as e:
            if e.status_code == 400:
                return _fail(atype, f"{e.detail} Nothing changed.")
            raise
    except HTTPException as e:
        return _fail(atype, str(e.detail))
    names = {x["user_id"]: x["name"] for x in before_page["logins"]}
    said = [names.get(u, "") for u in out["holders"]]
    if not out["changed"]:
        return {"type": atype, "result": f"Nothing changed: “{label}” already goes to {_who(before)}.",
                "label": f"No change: “{label}”", "duty": duty, "changed": False, "nav": NAV}
    try:
        after: Optional[Dict[str, Any]] = _entry(cd.build(business), duty)
    except HTTPException:
        after = None                                   # the move saved; the record names who it went to
    change = out["change"] or {}
    short = ", ".join(_first(n) for n in said) if said else "the lanes"
    return {"type": atype, "result": _record("move" if ids else "back", label, before, after, said),
            "label": f"“{label}” → {short}"[:80], "duty": duty, "changed": True,
            "change_id": str(change.get("id") or ""), "holders": out["holders"],
            "follows_lanes": out["follows_lanes"], "from": [h["name"] for h in before["holders"] if h["active"]],
            "to": said, "undo": {"type": "undo_duty", "duty": duty}, "nav": NAV}


async def handle_move_duty(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(move_sync, str((biz or {}).get("id") or ""), action or {})


# ─── undo_duty ────────────────────────────────────────────────────────

def undo_sync(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "undo_duty"
    if action.get("_unattended"):
        return _fail(atype, "a duty is put back only when the owner or an admin asks for it.")
    try:
        refused, business, _ = _open(atype, business_id, "admin")
        if refused:
            return refused
        duty = find_duty(action.get("duty"))
        if not duty:
            return _fail(atype, _no_such_duty(action.get("duty")))
        label = cd.CATALOG[duty]["label"]
        before_page = cd.build(business)
        change_id = str(action.get("change_id") or "").strip() or None
        try:
            out = cd.undo(business, duty, _turn_user(), change_id=change_id)
        except HTTPException as e:
            if e.status_code in (404, 409):
                return _fail(atype, str(e.detail))
            raise
    except HTTPException as e:
        return _fail(atype, str(e.detail))
    names = {x["user_id"]: x["name"] for x in before_page["logins"]}
    said = [names.get(u, "") for u in out["holders"]]
    try:
        after: Optional[Dict[str, Any]] = _entry(cd.build(business), duty)
    except HTTPException:
        after = None
    change = out["change"] or {}
    return {"type": atype, "result": _record("undo", label, _entry(before_page, duty), after, said),
            "label": f"Put back “{label}”"[:80], "duty": duty, "changed": True,
            "change_id": str(change.get("id") or ""), "holders": out["holders"],
            "follows_lanes": out["follows_lanes"], "nav": NAV}


async def handle_undo_duty(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(undo_sync, str((biz or {}).get("id") or ""), action or {})


# ─── The THIS LOGIN line ──────────────────────────────────────────────

UNREAD = ("Their jobs here couldn't be read just now: don't say whose job something is; the owner or an admin "
          "can say.")


def jobs_line(business_id: Any, user_id: Any) -> Optional[str]:
    """One line for the THIS LOGIN block: the duties this church login does,
    so Chief answers "is the weekly text my job?" from the church's own
    answer. None for the owner, an Admin, a login with no seat here and any
    business that isn't a church (or whose row can't be read, since then
    nobody knows it is one). A church whose duties can't be read says so."""
    biz, uid = str(business_id or ""), str(user_id or "")
    if not biz or not uid:
        return None
    try:
        s = cd.standing(biz, uid)                      # kept a minute; a move clears it
    except HTTPException:
        try:
            return UNREAD if cd._is_church(cd._business(biz)) else None
        except HTTPException:
            return None
    if not s["church"] or not s["role"] or s["role"] in ("owner", "admin"):
        return None
    labels = [d["label"] for k, d in cd.CATALOG.items() if k in s["duties"]]
    if labels:
        return ("Their jobs here: " + "; ".join(labels) + ". Any other duty is someone else's: say whose with "
                "list_duties, and that the owner or an admin can move it.")
    if s["role"] == "manager":
        return ("Their jobs here: none of the office's duties yet. The owner or an admin gives a login its duties "
                "(Logins & areas → Duties).")
    return "Their jobs here: none. A Member or Viewer login doesn't do the office's duties."
