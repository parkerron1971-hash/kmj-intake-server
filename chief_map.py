"""chief_map.py — Chief changes a church's leaders map in plain words, with Undo
(docs/CHURCH_LEADERS_STEP2.md §4, PR B5).

Kevin, 2026-11-03 (decision 1): when the owner or an admin asks Chief in plain
words, the change happens at once, with Undo, as duties do; a change that is
Chief's own idea waits on the sheet for a yes.

    list_map ............ the map in words: each department (leader, overseer,
                          office help and who does it, what hangs from it, what
                          it needs), the drafts apart, every role with who holds
                          it and what it can do, who answers to whom, the
                          settings and Shepherding's, what waits for a yes, and
                          the last ten changes with their ids
    change_map .......... {changes: [parts], said, stage?}: one change through
                          church_map_batch.apply (origin 'chief'), made at once;
                          stage (Chief's own idea) leaves it waiting for a yes
    draft_map ........... the same with `phase`, always waiting: the setup
                          coach's (B9), registered now (origin 'session')
    undo_map_change ..... {change_id}: church_map_batch.undo; a change that saying
                          yes to someone's suggestion made with a duty move goes
                          back with it (church_map_asks.ask_of_change: both or
                          neither, as Recent changes' Undo on screen)
    apply_map_change .... {change_id}: a waiting change made, a failed one finished
    discard_map_change .. {change_id}: a waiting change let go
    search_templates .... {q, kind?}: the ready-made list's search (church_templates)
    adopt_template ...... {kind, key, tradition?, name?}: church_templates.adopt

A part names things in words, and they resolve here before the batch sees ids:
a department by its name, a role by its title or key, a person by a whole name,
a first name only one person has, or a role's title and a last name ("Deacon
Moore"), the role holders first, then the church's people. None, or more than
one, changes nothing and says who it could be (risk 5). What a department holds
is named too, by its kind in Chief's words (a Serve team, a group, a role, a
board, a worship ministry, the youth or kids space, a budget line) or by its
name alone: a Serve team is the Serve card's team the editor offers under
Teams, else a Sunday team (a group). list_map says each held thing's kind, and
what hangs from no department yet.

Reads are a Manager seat's and up; every write the owner's or an admin's, a
money part (a level, the board's yes) the owner's alone (the batch's own seats).
Every verb needs someone signed in, refuses an unattended run, follows
CHURCH_MAP for that person or their church, as the routes do
(church_map.office_open), and needs step 2's file. Action tags, never native
write tools; list_map and search_templates are mid-turn reads.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import HTTPException

import church_areas as ca
import church_map as cm
import church_map_batch as batch
import church_roles as cr
import church_shepherding as shep
import church_templates as ct
from chief_duties import _EMAILS, _join, _norm, _turn_user, find_duty

NAV = {"tab": "operate", "sub": "leaders"}
NOT_ON = "The leaders map isn't on here yet, so Chief can't read or change it."
NOT_READY = "The leaders map isn't ready here yet, so Chief can't read or change it."
NOT_YOURS = "Changing the leaders map is the owner's or an admin's."
UNDO = "Undo puts it back."
WRITES = ("change_map", "draft_map", "undo_map_change", "apply_map_change", "discard_map_change", "adopt_template")
_RANK = {"viewer": 1, "member": 2, "manager": 3, "admin": 4, "owner": 5}
_KINDS = {"shape": "shape", "church": "shape", "whole church": "shape", "department": "department",
          "ministry": "department", "role": "role"}
# What a department holds, in the words Chief may use for each kind (folded: case, punctuation and a plural s
# aside). A name with no kind must fit exactly one.
_UNIT_KINDS = {_w: k for k, ws in (
    ("serve_option", ("serve option", "serve team", "team", "serve", "sunday team", "serving team", "volunteer team",
                      "ministry team")),
    ("group", ("group", "small group")), ("role", ("role",)), ("board", ("board",)),
    ("worship_ministry", ("worship ministry", "worship")), ("space", ("space",)),
    ("check_line", ("check line", "budget line", "line"))) for _w in ws}
HOLDS = ("a Serve team, a group, a role, a board, a worship ministry, the youth or kids space, or a budget line")
_ORIGIN = {"office": "made on screen", "chief": "by Chief", "session": "in a setup session",
           "template": "from a ready-made", "launch": "at launch"}
_STATUS = {"applied": "made", "undone": "put back", "discarded": "let go", "failed": "part went in"}

# draft_map's words, for the church setup coach's prompt (B9's build_church_coach_prompt carries them, as a
# value: single braces). The coach only ever stages; the main prompt teaches change_map's stage instead.
COACH_WORDS = (
    '[ACTION:{"type":"draft_map","phase":"ministries","said":"Youth and Children, each with its leader",'
    '"changes":[{"kind":"department","name":"Youth","status":"draft","area":"kids_youth"}]}]  — save what this '
    "session decided as one change that waits for the owner's yes: the parts are change_map's. Nothing is made "
    "until they launch.")

LIST_TOOL = {
    "name": "list_map",
    "description": (
        "A church's leaders map: each department with its leader, overseer, office help and what hangs from it, "
        "what each needs, the drafts, every role with who holds it and what it can do, who answers to whom, the "
        "settings, what waits for a yes and the last ten changes with their ids. Read it before change_map so the "
        "names are real."),
    "input_schema": {"type": "object", "properties": {}},
}
SEARCH_TOOL = {
    "name": "search_templates",
    "description": "The ready-made list: whole-church shapes, ministries and roles a church can add as drafts.",
    "input_schema": {"type": "object", "properties": {
        "q": {"type": "string"}, "kind": {"type": "string", "enum": ["shape", "department", "role"]}}},
}


def _fail(atype: str, msg: str, **more: Any) -> Dict[str, Any]:
    return {"type": atype, "result": f"Failed: {msg}", "label": msg[:80], "failed": True, "nav": NAV, **more}


def _plain(v: Any) -> str:
    return " ".join(str(v or "").split())


def _fold(v: Any) -> str:
    return " ".join(ct.words(v))


def _uuid(v: Any) -> Optional[str]:
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, TypeError):
        return None


def _bad(msg: str) -> None:
    raise HTTPException(400, msg)


# ─── Who is asking ────────────────────────────────────────────────────

def _switched_on(uid: str) -> Optional[bool]:
    """Whether CHURCH_MAP is open to this person, as the routes decide it.
    None when owner mode can't read who they are (chief_duties' cache)."""
    m = cm.mode()
    if m != "owner":
        return m == "on"
    if uid not in _EMAILS:
        try:
            import platform_suite
            _EMAILS[uid] = platform_suite._owner_email(uid) or ""
        except Exception:  # noqa: BLE001 — unread is not a yes
            return None
    return cm.open_to(SimpleNamespace(email=_EMAILS[uid]))


def _map_open(uid: str, business_id: str) -> Optional[bool]:
    """church_map.office_open for a Chief turn: the church (church_open: with `owner`, the platform owner's
    church, so its admins' Chief agrees with their screen), else the person (_switched_on)."""
    return True if cm.church_open(business_id) else _switched_on(uid)


def _open(atype: str, business_id: str, least: str) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any], str]:
    """(a refusal or None, the church's row, the person's seat). A read that fails raises 503."""
    uid = _turn_user()
    if not uid:
        return _fail(atype, "the leaders map is read and changed only by someone signed in to the church's "
                     "office."), {}, ""
    on = _map_open(uid, business_id)
    if on is None:
        return _fail(atype, "whether the leaders map is on couldn't be checked just now. Try again."), {}, ""
    if not on:
        return _fail(atype, NOT_ON), {}, ""
    import church_follow_up as cfu
    q = cm._q(business_id)
    rows = cm._need(f"/businesses?id=eq.{q}&select=id,name,type,owner_id,settings&limit=1")
    if not rows or not cfu.is_church(rows[0]):
        return _fail(atype, "the leaders map is for churches."), {}, ""
    seat = "owner" if str(rows[0].get("owner_id") or "") == uid else next(iter(cm._need(
        f"/business_users?business_id=eq.{q}&user_id=eq.{cm._q(uid)}&status=eq.active&select=role&limit=1")),
        {}).get("role") or ""
    if _RANK.get(seat, 0) < _RANK[least]:
        return _fail(atype, NOT_YOURS if least == "admin" else
                     "the leaders map is for the church's owner, its admins and its Manager logins."), rows[0], seat
    s = cm.step2_state()
    if s is not True:
        return _fail(atype, cm.UNREAD if s is None else NOT_READY), rows[0], seat
    return None, rows[0], seat


def _run(atype: str, biz: Any, action: Any, body: Callable[..., Dict[str, Any]]) -> Dict[str, Any]:
    action = action if isinstance(action, dict) else {}
    if action.get("_unattended"):
        return _fail(atype, "the leaders map is read and changed only when someone in the church's office asks.")
    try:
        refused, business, seat = _open(atype, str((biz or {}).get("id") or ""), "admin" if atype in WRITES else
                                        "manager")
        return refused or {"type": atype, "nav": NAV, **body(business, seat, action)}
    except HTTPException as e:
        said, more = str(e.detail), {}
        if getattr(e, "change_id", None):       # a part went in: the change this call acted on, kept failed
            more["change_id"] = e.change_id
        if getattr(e, "ask_id", None):          # an office login's suggestion: answered as theirs (B11)
            more["note_for_chief"] = (f"It's someone's suggestion: answer it with answer_ask (ask {e.ask_id}) "
                                      "once the owner or an admin says so, naming whose it is.")
        if "doesn’t hold a role that" in said:
            more["note_for_chief"] = ("Ask the owner whether that person's role may do it. If yes, send the same "
                                      "change again with a role part turning it on, placed before this part.")
        return _fail(atype, said, **more)


# ─── Names, in words ──────────────────────────────────────────────────

class _Names:
    """The church's roles and the people who hold them, read once a change."""

    def __init__(self, bid: str):
        self.bid = bid
        self.defs = cr.defs(bid, with_drafts=True)
        if self.defs is None:
            raise HTTPException(503, cm.UNREAD)
        self.holders = cm._holders(bid, asked=True)
        self.held = cm._people(bid, {h["contact_id"] for h in self.holders}) if self.holders else {}
        self._m: Optional[cm.Map] = None

    @staticmethod
    def _find(rows: List[Dict[str, Any]], raw: Any, *cols: str) -> Optional[str]:
        """One row's id: its id, its exact name (case aside), else the same words (a plural s aside); None
        when none is; two is a 400 saying which they could be."""
        if _uuid(raw):
            return _uuid(raw)
        for same in (lambda v: _norm(v) == _norm(raw), lambda v: _fold(raw) and _fold(v) == _fold(raw)):
            hit = {str(r["id"]): r for r in rows if any(same(r.get(c)) for c in cols)}
            if len(hit) > 1:
                _bad(f"“{_plain(raw)}” could be {_join(sorted({_plain(r[cols[0]]) for r in hit.values()}))}")
            if hit:
                return next(iter(hit))
        return None

    def pick(self, rows: List[Dict[str, Any]], raw: Any, what: str, *cols: str) -> str:
        got = self._find(rows, raw, *cols)
        if got is None:
            _bad(f"There’s no {what} called “{_plain(raw)}” here")
        return got

    def role(self, raw: Any) -> str:
        return self.pick(self.defs, raw, "role", "title", "key")

    def department(self, raw: Any) -> str:
        self._m = self._m or cm._map(self.bid)
        return self.pick(self._m.departments, raw, "department", "name")

    @staticmethod
    def _named(names: Dict[str, str], w: str) -> List[Tuple[str, str]]:
        whole = [(c, n) for c, n in names.items() if _norm(n) == w]
        return whole if whole or " " in w else [(c, n) for c, n in names.items() if _norm(n).split(" ")[0] == w]

    def _titled(self, w: str) -> List[Tuple[str, str]]:
        """"Deacon Moore": the holders of a role whose title (or key) is, or starts with, those words, and whose
        last name it is (Grace's Deacon Board)."""
        words, out = w.split(" "), {}
        for i in range(1, len(words)):
            title = _fold(" ".join(words[:i]))
            keys = {d["key"] for d in self.defs if title and any(
                f == title or f.startswith(title + " ") for f in (_fold(d["title"]), _fold(d["key"])))}
            for h in self.holders:
                n = self.held.get(str(h["contact_id"]), "")
                if h.get("role") in keys and _norm(n).endswith(" " + " ".join(words[i:])):
                    out[str(h["contact_id"])] = n
        return list(out.items())

    def person(self, raw: Any) -> str:
        """A contact id: holders first (a whole name, a unique first name, a title and last name), then everyone."""
        w = _norm(raw)
        if _uuid(w):
            return _uuid(w)
        hit = self._named(self.held, w) or self._titled(w)
        if not hit:     # the server finds who it could be: a church's people run past one read's 1,000 rows
            pat = "*".join(re.sub(r"[*%\\]", "", x).replace("_", "\\_") for x in w.split(" ")) + "*"
            rows = cm._need(f"/contacts?business_id=eq.{cm._q(self.bid)}&name=ilike.{cm._q(pat)}"
                            "&select=id,name&order=id.asc&limit=1000")
            if len(rows) >= 1000:
                _bad(f"Too many people here are called “{_plain(raw)}” to tell apart: say their whole name")
            hit = self._named({str(r["id"]): _plain(r.get("name")) for r in rows}, w)
        if len(hit) > 1:
            _bad(f"“{_plain(raw)}” could be {_join(sorted({n for _c, n in hit}))}")
        if not hit:
            _bad(f"Nobody at this church is called “{_plain(raw)}”")
        return hit[0][0]

    @staticmethod
    def _kind(raw: Any) -> Optional[str]:
        """A unit's kind as Chief said it ("serve team", "Teams", "group") -> the map's; None when none was said;
        a word that is none of them is a 400 saying what a department holds."""
        if not raw:
            return None
        if raw in cm.KINDS:
            return raw
        kind = _UNIT_KINDS.get(_fold(raw))
        if not kind:
            _bad(f"A department holds {HOLDS}: “{_plain(raw)}” isn’t one of those")
        return kind

    def _label(self, kind: str, raw: Any) -> Optional[str]:
        """A label kind's own spelling (the Serve card's team, a budget line, youth or kids): the same, case
        aside, else the same words; "the kids space" is kids. None when it isn't one."""
        labels, want = cm._labels(self.bid, kind), _fold(raw)
        if kind == "space" and want.endswith(" space"):
            want = want[:-len(" space")]
        hit = labels.get(_plain(raw).casefold()) or next(iter(sorted({v for v in labels.values() if want and
                                                                      _fold(v) == want})), None)
        return hit

    def _thing(self, kind: str, raw: Any) -> Optional[Dict[str, Any]]:
        """One kind's unit by name, or None when this church has none called that."""
        if kind in ("serve_option", "space", "check_line"):
            label = self._label(kind, raw)
            return {"kind": kind, "label": label} if label else None
        if kind == "role":
            rid = self._find(self.defs, raw, "title", "key")
        else:
            table, col, live = cm._THINGS[kind]
            rid = self._find(cm._need(f"/{table}?business_id=eq.{cm._q(self.bid)}{live}&select=id,{col}&limit=500"),
                             raw, col)
        return {"kind": kind, "ref": rid} if rid else None

    def unit(self, u: Any) -> Any:
        """A unit by name, as the department editor picks one: a Serve team (the Serve card's, the editor's
        Teams; else a Sunday team, which is a group), a group, role, board or worship ministry by its name, a
        space or budget line by its label; a name with no kind, the one kind that has it. By id (`ref`), as
        given: the batch checks it."""
        u = {"name": u} if isinstance(u, str) else u
        if not isinstance(u, dict):
            return u
        kind, name = self._kind(u.get("kind")), _plain(u.get("name") or ("" if u.get("ref") else u.get("label")))
        if u.get("ref") or not name:
            return {**u, "kind": kind or u.get("kind")}
        if kind == "serve_option":
            got = self._thing("serve_option", name) or self._thing("group", name)
            if not got:
                _bad(f"“{name}” isn’t a team on your Serve card or one of your groups")
            return got
        if kind:
            got = self._thing(kind, name)
            if not got:
                if kind in ("space", "check_line"):        # the batch's own words for these
                    return {"kind": kind, "label": name}
                _bad(f"There’s no {cm._WORD[kind]} called “{name}” here")
            return got
        hits = [x for x in (self._thing(k, name) for k in cm.KINDS) if x]
        if len(hits) > 1:
            _bad(f"“{name}” could be " + " or ".join(f"the {cm._WORD[k]}" for k in sorted({h["kind"] for h in hits}))
                 + ": say which")
        if not hits:
            _bad(f"Nothing called “{name}” here is something a department holds ({HOLDS})")
        return hits[0]

    def part(self, raw: Any) -> Dict[str, Any]:
        """One part as Chief said it -> as church_map_batch takes it (ids)."""
        if not isinstance(raw, dict):
            _bad("Each part is a department, a role, who someone answers to, the settings or Shepherding’s")
        p, kind = dict(raw), raw.get("kind")
        for k in ("leader", "overseer", "person", "to"):
            if p.get(k):
                p[k] = self.person(p[k])
        if kind == "department":
            if p.get("department"):
                p["id"] = self.department(p.pop("department"))
            if p.get("support_duty"):
                p["support_duty"] = find_duty(p["support_duty"]) or p["support_duty"]
            if p.get("area") and p["area"] not in ca.AREAS:
                p["area"] = next((k for k, a in ca.AREAS.items() if _fold(a["label"]) == _fold(p["area"])), p["area"])
            if isinstance(p.get("units"), list):
                p["units"] = [self.unit(u) for u in p["units"]]
        elif kind == "role":
            if p.get("role"):
                p["id"] = self.role(p.pop("role"))
            if p.get("reports_to"):
                p["reports_to"] = self.role(p["reports_to"])
        elif kind == "answers_to" and p.get("role"):
            p["role"] = self.role(p["role"])
        elif kind == "settings":
            p.update({k: [self.role(x) for x in p[k]] for k in cm.PICKS if isinstance(p.get(k), list)})
        return p


# ─── The record, in before → now words ────────────────────────────────

def _lines(business: Dict[str, Any], change_id: Any) -> Optional[List[str]]:
    """A change's lines, read by its id once it's written. None when that read fails: the change stands, and
    its receipt says so in plain words (as chief_duties' read after a move)."""
    try:
        return batch.lines_of(business, change_id)
    except HTTPException:
        return None


def _said(lines: Optional[List[str]]) -> str:
    if lines is None:
        return "Its details couldn’t be read back just now; the map’s list of changes shows them."
    return ". ".join(lines) + "." if lines else ""


UNLOGGED = "Its record didn’t save, so Undo can’t put it back from the map’s list: to reverse it, ask for it the other way."
UNMARKED = ("It still reads as waiting on the map’s list, because marking it made didn’t save, so Undo can’t put it "
            "back yet: apply it again to finish marking it.")


def _change(business: Dict[str, Any], seat: str, action: Dict[str, Any], *, stage: bool, origin: str,
            phase: Optional[str] = None) -> Dict[str, Any]:
    raw = action.get("changes")
    raw = [raw] if isinstance(raw, dict) else raw
    if not isinstance(raw, list) or not raw:
        _bad("Say what changes: a department, a role, who someone answers to, the settings or Shepherding’s")
    n = _Names(str(business["id"]))
    out = batch.apply(business, [n.part(p) for p in raw], _turn_user(), origin, stage=stage, phase=phase,
                      role=seat, said=_plain(action.get("said"))[:400])
    ch = out["change"]
    if ch is None and out.get("made"):          # made, but its row didn't save: no change to undo
        return {"result": f"Changed the leaders map as asked. {UNLOGGED}", "label": "Changed the map (not logged)",
                "changed": True}
    if ch is None:
        return {"result": "Nothing changed: the leaders map already reads that way.", "label": "No change to the map",
                "changed": False}
    lines = _lines(business, ch["id"])
    label = (lines[0] if lines and len(lines) == 1 else
             f"{len(lines)} changes to the map" if lines else "A change to the map")[:80]
    if ch["status"] == "pending":
        who = "the owner says yes" if ch["money"] else "the owner or an admin says yes"
        return {"result": f"Saved for a yes; nothing changed yet. {_said(lines)} It waits under “Waiting for your yes” "
                          f"in Leaders & roles until {who}.", "label": f"Waiting: {label}"[:80], "changed": False,
                "waiting": True, "change_id": ch["id"], "money": ch["money"]}
    return {"result": f"Changed the leaders map. {_said(lines)} It’s one change in the map’s list. {UNDO}",
            "label": label, "changed": True, "change_id": ch["id"], "money": ch["money"]}


def _change_id(action: Dict[str, Any]) -> str:
    cid = _uuid(action.get("change_id"))
    if not cid:
        _bad("Say which change: its id is in the leaders map’s list of changes")
    return cid


def _undo(business: Dict[str, Any], seat: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """undo_map_change. A change that saying yes to someone's suggestion made together with a duty move goes
    back with that move, both or neither (church_map_asks.ask_of_change, undo_ask's way), as on screen."""
    import church_map_asks as asks
    cid = _change_id(action)
    found = asks.ask_of_change(business, cid)
    if found:
        return asks.chief_undo_with_ask(business, _turn_user(), seat, found)
    return _undo_alone(business, seat, {"change_id": cid})


def _undo_alone(business: Dict[str, Any], seat: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """The map change's own undo (church_map_batch.undo), whatever else came with it."""
    out = batch.undo(business, _change_id(action), _turn_user(), role=seat, origin="chief")
    ch = out["change"]
    said = _said(_lines(business, ch["id"])) if ch else "Its record didn’t save, so the map’s list won’t show it."
    gone = " The change that waited for a yes on what it took out was let go too." if out.get("let_go") else ""
    return {"result": f"Put that change back. {said}{gone} Putting it back is a change too; to change it again, "
                      "ask for the change.", "label": "Put back a change to the map", "changed": True,
            "undone": out["undone"], "let_go": out.get("let_go") or []}


def _apply(business: Dict[str, Any], seat: str, action: Dict[str, Any]) -> Dict[str, Any]:
    cid = _change_id(action)
    undoes = batch._row(business, cid).get("undoes")       # finishing an undo: nothing to undo again
    out = batch.apply_pending(business, cid, _turn_user(), role=seat)
    if undoes:
        gone = " The change that waited for a yes on what it took out was let go too." if out.get("let_go") else ""
        return {"result": f"Finished putting a change back. {_said(_lines(business, cid))}{gone} Putting it back is "
                          "a change too; to change it again, ask for the change.",
                "label": "Finished putting a change back", "changed": True, "undoes": str(undoes),
                "let_go": out.get("let_go") or []}
    if (out.get("change") or {}).get("status") != "applied":       # made, but its mark didn't save
        return {"result": f"Made the change that was waiting. {_said(_lines(business, cid))} {UNMARKED}",
                "label": "Made a waiting change (not marked)", "changed": True}
    return {"result": f"Made the change that was waiting. {_said(_lines(business, cid))} {UNDO}",
            "label": "Made a waiting change", "changed": True, "change_id": cid}


def _discard(business: Dict[str, Any], seat: str, action: Dict[str, Any]) -> Dict[str, Any]:
    cid = _change_id(action)
    batch.discard(business, cid, _turn_user(), role=seat)
    return {"result": f"Let the waiting change go; nothing on the map changed. It was: {_said(_lines(business, cid))}",
            "label": "Let a waiting change go", "changed": False, "change_id": cid}


# ─── The ready-mades ──────────────────────────────────────────────────

def _home(business: Dict[str, Any]) -> str:
    st = cr.settings(str(business["id"]))
    if st is None:
        raise HTTPException(503, cm.UNREAD)
    return ct.tradition_of(business, st)


def _card(c: Dict[str, Any]) -> str:
    if c["kind"] == "role":
        also = f"; also {', '.join(c['also'])}" if c.get("also") else ""
        return (f"{c['title']} (role {c['key']}; {c['tradition']['label']}{also}): {c['does']} Answers to "
                f"{c['answers_to'] or 'nobody: it is the top'}. Sees: {c['sees']} Can: {c['can'] or 'its job only'}.")
    if c["kind"] == "department":
        return (f"{c['name']} (ministry {c['key']}): {c['about']} Office help: {c['office_help']['label']}. Leader: "
                f"{c['leader']['title']}; overseer: {c['overseer']['title']}. {c['rhythm']}")
    return (f"{c['label']} (whole church {c['key']}{'; fits yours' if c['fits_you'] else ''}): {c['about']} "
            f"Ministries: {', '.join(d['name'] for d in c['departments'])}. Shepherds: "
            f"{', '.join(c['shepherds']) or 'the Ministers setting decides'}.")


def _search(business: Dict[str, Any], seat: str, action: Dict[str, Any]) -> Dict[str, Any]:
    q, kind = _plain(action.get("q") or action.get("query"))[:80], _norm(action.get("kind"))
    if kind and kind not in _KINDS:
        _bad("Look through whole churches, ministries or roles")
    home = _home(business)
    hits = ct.search(q, _KINDS.get(kind, ""), home, _plain(business.get("name")))
    lines = [f"Ready-mades{f' for “{q}”' if q else ''}: {len(hits)} found, the {cr.TYPES[home]['label']} ones first. "
             "Each comes in as a draft."] + [f"- {_card(c)}" for c in hits[:8]]
    if len(hits) > 8:
        lines.append(f"And {len(hits) - 8} more: ask with narrower words.")
    return {"result": "\n".join(lines), "label": f"Ready-mades: {len(hits)} found", "found": len(hits)}


def _adopt(business: Dict[str, Any], seat: str, action: Dict[str, Any]) -> Dict[str, Any]:
    kind, key = _KINDS.get(_norm(action.get("kind")), ""), str(action.get("key") or "").strip()
    if kind and key and ct.get(kind, key) is None:          # a name, said in words: the church's own row first
        home = _home(business) if kind == "role" else ""
        hit = [t["key"] for t in ct.BY_KIND[kind].values() if _fold(t.get("title") or t.get("name") or t["label"])
               == _fold(key) and (kind != "role" or t["tradition"] in (home, ct.ANY))]
        key = hit[0] if len(hit) == 1 else key
    out = ct.adopt(business, kind, key, _turn_user(), role=seat, tradition=str(action.get("tradition") or ""),
                   name=str(action.get("name") or ""))
    ch = (out["change"] or {}).get("id")
    tail = " They come in as drafts: nothing goes to them until they’re live." if out["made"] else ""
    if out["made"] and not ch:
        tail += " Their record didn’t save, so Undo can’t take them out: remove the drafts in Leaders & roles."
    return {"result": out["said"] + tail + (f" {UNDO}" if ch else ""), "label": out["said"][:80],
            "changed": bool(out["made"]), "change_id": ch, "waiting_id": (out["waiting"] or {}).get("id"),
            "made": [m["name"] for m in out["made"]]}


# ─── list_map ─────────────────────────────────────────────────────────

def _dept_line(d: Dict[str, Any], needs: List[str]) -> str:
    duty = d["support_duty"]
    who = ", ".join(h["name"] for h in (duty or {}).get("holders") or [] if h["name"]) or "the owner and the admins"
    helps = f"{duty['label']} ({who})" if duty else "none"
    area = (ca.AREAS.get(d["area"] or "") or {}).get("label", "no area")
    units = ", ".join(f"{u['name']} ({cm._WORD.get(u['kind'], u['kind'])})" for u in d["units"]) or "nothing yet"
    return (f"- {d['name']} ({area}): leader {(d['leader'] or {}).get('name') or 'none'}; overseer "
            f"{(d['overseer'] or {}).get('name') or 'none'}; office help: {helps}; holds: {units}."
            + (f" Needs: {' '.join(needs)}" if needs else ""))


def _change_line(c: Dict[str, Any]) -> str:
    import church_map_asks as asks
    at = batch._parse(c.get("made_at"))
    ask = c.get("suggested_by")          # an office login's, never Chief's own idea (#1731 review)
    how = [f"suggested by {asks.fence(ask['name'])}, ask {ask['ask_id']}: answer it with answer_ask" if ask else
           _ORIGIN.get(c.get("origin"), ""), f"{at:%b} {at.day}" if at else ""]
    if c["status"] != "pending":
        how.insert(0, "an undo" if c.get("undoes") else _STATUS.get(c["status"], c["status"]))
    if c.get("money"):
        how.append("money: the owner’s")
    if (c.get("ask") or {}).get("duty"):        # saying yes moved a duty with it: one Undo puts back both
        how.append(f"saying yes also moved “{c['ask']['duty']}”: undo_map_change puts both back")
    if c.get("can_undo"):
        how.append("Undo can put it back")
    lines = [asks.fence(x) for x in c["lines"]] if ask else c["lines"]       # their words, as data
    return f"- change {c['id']} ({', '.join(w for w in how if w)}): {'; '.join(lines)}"


_FREE = (("serve_option", "Serve teams"), ("group", "groups"), ("board", "boards"),
         ("worship_ministry", "worship ministries"), ("space", "spaces"), ("check_line", "budget lines"))


def _free(v: Dict[str, Any]) -> str:
    """What hangs from no department yet, by kind, from the editor's own pickers (church_map._choices); the
    roles are in their own list."""
    said = [f"{word}: " + ", ".join(c["label"] for c in got[:30]) + (f" and {len(got) - 30} more" if len(got) > 30
                                                                    else "")
            for k, word in _FREE for got in [[c for c in v["choices"].get(k) or [] if not c["department"]]] if got]
    return "On no department yet: " + ("; ".join(said) or "nothing") + "."


def _list(business: Dict[str, Any], seat: str, action: Dict[str, Any]) -> Dict[str, Any]:
    import church_map_asks as asks
    bid = str(business["id"])
    v, m = cm.view(business, choices=True), cm._map(bid)
    rec = batch.recent(business, seat, asks._gates(_turn_user(), bid))
    holders = cm._holders(bid, asked=True)
    people = cm._people(bid, {h["contact_id"] for h in holders}) if holders else {}
    sh = shep.settings(bid)
    if sh is None:
        raise HTTPException(503, cm.UNREAD)
    needs: Dict[str, List[str]] = {}
    for g in v["gaps"]:
        needs.setdefault(g["department_id"], []).append(g["text"])
    out = [f"The leaders map at {_plain(business.get('name')) or 'this church'}. A draft routes nothing until it goes "
           "live. People are named as in the church's records."]
    for status, head in (("active", "Departments"), ("draft", "Drafts")):
        ds = [d for d in v["departments"] if d["status"] == status]
        out += [f"{head}:"] + [_dept_line(d, needs.get(d["id"], [])) for d in ds] if ds else []
    if not v["departments"]:
        out.append("Departments: none yet.")
    out.append(_free(v))
    out.append("Roles (who holds each; what it can do):")
    for r in v["roles"]:
        mine = [h for h in holders if h.get("role") == r["key"]]
        said = [people.get(str(h["contact_id"]), "") + (" (asked)" if h.get("status") == "invited" else "")
                for h in mine[:15]] + ([f"and {len(mine) - 15} more"] if len(mine) > 15 else [])
        out.append(f"- {r['title']} ({r['key']}{'; draft' if r['status'] == 'draft' else ''}): "
                   f"{', '.join(said) or 'nobody holds it'}. Can: {cm.says(m, r).split(': ', 1)[1]}.")
    for x in v["answers_to"]:
        title = next((r["title"] for r in v["roles"] if r["key"] == x["role"]), x["role"])
        out.append(f"{x['name']} ({title}) answers to {x['answers_to']['name']}.")
    st, titles = v["settings"], {r["id"]: r["title"] for r in v["roles"]}
    words = [f"{batch.WORD[k]} " + (batch._say(k, st.get(k), titles) if st.get(k) is not None else
                                    f"the usual ({batch._say(k, st['platform'][k], {})})") for k in cm.LEVELS]
    words += [f"{batch.WORD[k]}: " + batch._say(k, st.get(k), titles) for k in cm.PICKS]
    out.append("Settings: " + "; ".join(words) + ".")
    out.append(f"Shepherding: Ministers shepherd {'on' if sh['ministers'] else 'off'}; families per shepherd "
               f"{sh['cap']}; families for the lead pastor {sh['lead_cap']}.")
    out += ["Waiting for a yes:"] + [_change_line(c) for c in rec["pending"]] if rec["pending"] else \
        ["Waiting for a yes: nothing."]
    out += ["Recent changes, newest first:"] + [_change_line(c) for c in rec["recent"][:10]] if rec["recent"] else \
        ["Recent changes: none yet."]
    return {"result": "\n".join(out), "label": f"Leaders map · {len(v['gaps'])} need something" if v["gaps"] else
            "Leaders map", "gaps": len(v["gaps"]), "pending": [c["id"] for c in rec["pending"]],
            "note_for_chief": (
                "Name people and roles from this. Only the owner or an admin changes the map (change_map), at once "
                "when they ask; your own idea goes in with stage:true and waits for their yes. A department's units "
                "are its whole list: send what it holds now, by name and kind, with what's added. A money level or "
                "the board's yes is the owner's alone. Say draft, ready-made, change and Undo; never template or "
                "switch.")}


# ─── The handlers ─────────────────────────────────────────────────────

def _handler(atype: str, body: Callable[..., Dict[str, Any]]):
    async def handle(client, biz, action) -> Dict[str, Any]:
        return await asyncio.to_thread(_run, atype, biz, action, body)
    handle.__name__ = f"handle_{atype}"
    handle.__qualname__ = handle.__name__
    return handle


handle_list_map = _handler("list_map", _list)
handle_change_map = _handler("change_map", lambda b, s, a: _change(b, s, a, stage=bool(a.get("stage")),
                                                                    origin="chief"))
handle_draft_map = _handler("draft_map", lambda b, s, a: _change(b, s, a, stage=True, origin="session",
                                                                  phase=a.get("phase") or None))
handle_undo_map_change = _handler("undo_map_change", _undo)
handle_apply_map_change = _handler("apply_map_change", _apply)
handle_discard_map_change = _handler("discard_map_change", _discard)
handle_search_templates = _handler("search_templates", _search)
handle_adopt_template = _handler("adopt_template", _adopt)
