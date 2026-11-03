"""church_map_batch.py — one change, one row: the leaders map's change log, with
Undo (docs/CHURCH_LEADERS_STEP2.md §4.1-§4.3, PR B3a).

    apply(biz, changes, by, origin, stage=False, phase=None, *, role, said="")
        One change of up to 80 parts, each a department, a role, who a holder
        answers to, the church's settings or Shepherding's. A part names its
        thing by id or exact name (Chief's fuller resolver is B5's). Every
        part is checked first, by its own write run dry against what the
        parts before it would leave; then they are written in order. Each is
        kept as {kind, id, label, before, after}, with only the fields it
        changes: before None, this change made it; after None, it archived
        it (`deleted`, when an undo took out a draft). One church_map_changes
        row: applied; pending when staged (Chief's own idea, waiting on the
        sheet); failed when a write failed after another got in, with what
        got in (`done: false` on the rest). A part that changes nothing is
        left out, and a change of nothing logs nothing.
    apply_pending(...) . a pending change, or a failed one again: a part
                         already as its after is passed over, one whose
                         fields read as before (or already as after) is
                         written, any other is a 409. Safe to run again.
    discard(...) ....... a pending change, never made
    undo(...) .......... for UNDO_DAYS, only while every field it touched
                         reads as it left it, else a 409 naming what changed
                         since (never a half undo). Parts go back in reverse:
                         a draft it made is deleted, an active department it
                         made archived, every other field back to before. The
                         undo is a change too (`undoes`); the original gets
                         undone_at.
    recent(biz, role) .. the sheet's list: what waits for a yes, and the
                         recent changes, in plain words

The owner or an admin makes every change. One touching money (a money level,
or a role's board yes: decision 3) is the owner's alone to make, apply, undo
or discard (`money`). Every call needs church_map.step2_state(): a 503 until
step 2's file is applied, and when the probe itself fails.
"""
from __future__ import annotations

import copy
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

import church_map as cm
import church_roles as cr
import church_shepherding as shep
import sb_clients

UNDO_DAYS = 30                    # as expense_categories.UNDO_DAYS
PARTS_MAX = 80                    # the table's check
RECENT = 30
ORIGINS = ("office", "chief", "session", "template", "launch")
PHASES = ("church", "ministries", "leaders", "shepherding", "office_help", "rhythm_launch")
FIELDS: Dict[str, Tuple[str, ...]] = {
    "department": ("name", "leader_contact_id", "overseer_contact_id", "support_duty", "area", "status", "source",
                   "sort", "units"),
    "role": ("title", "definition", "reports_to", "status", *cr.SWITCHES, "made_for"),
    "answers_to": ("answers_to_contact_id",),
    "settings": (*cm.LEVELS, *cm.PICKS),
    "shepherding": ("ministers", "cap", "lead_cap")}
MAKES = {"role": ("job",)}        # said only by a part that makes one
SOURCE = {"office": ("office", "custom"), "template": ("template", "template")}    # (a department's, a role's)
PEOPLE = ("leader_contact_id", "overseer_contact_id", "answers_to_contact_id")
COLS = "id,status,origin,phase,said,parts,money,made_by,made_at,applied_by,applied_at,undoes,undone_at,error"
WORD = {"name": "name", "leader_contact_id": "leader", "overseer_contact_id": "overseer",
        "support_duty": "office helper", "area": "area", "status": "", "source": "comes from",
        "sort": "place in the list", "units": "teams, groups and spaces", "title": "title",
        "definition": "what it does", "reports_to": "who it answers to", "can_shepherd": "shepherds families",
        "can_oversee": "can oversee a department", "can_lead": "leads", "can_board_yes": "gives the board’s yes on money",
        "can_see_all": "sees everything", "made_for": "first in line for", "job": "job",
        "answers_to_contact_id": "who they answer to", "pastor_from_cents": "the pastor’s yes from",
        "board_over_cents": "the board’s yes over", "pastor_yes_roles": "who gives the pastor’s yes",
        "office_overseer_roles": "who oversees the office", "ministers": "Ministers shepherd",
        "cap": "families per shepherd", "lead_cap": "families for the lead pastor"}
NOT_READY = "The leaders map’s changes aren’t set up yet. Try again later."
WENT_IN = " Part of this change went in: apply it again to finish it."


def _open() -> None:
    s = cm.step2_state()
    if s is not True:
        raise HTTPException(503, cm.UNREAD if s is None else NOT_READY)


def _may(role: str, money: bool = False) -> None:
    if role not in ("owner", "admin"):
        raise HTTPException(403, "Only the owner or an admin changes the leaders map.")
    if money and role != "owner":
        raise HTTPException(403, "Only the owner changes the church’s money levels, or who gives the board’s yes.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(v: Any) -> Optional[datetime]:
    try:
        at = datetime.fromisoformat(str(v or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


# ─── What a part names ────────────────────────────────────────────────

def _uuid(v: Any) -> Optional[str]:
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, TypeError):
        return None


def _one(rows: List[Dict[str, Any]], v: Any, what: str, *cols: str) -> str:
    """An id as given (its write checks it is the church's), or the one row
    whose exact name, case aside, is `v`."""
    if _uuid(v):
        return _uuid(v)
    want = cm._plain(v).casefold()
    hit = {str(r["id"]) for r in rows if want and any(cm._plain(r.get(c)).casefold() == want for c in cols)}
    if len(hit) != 1:
        cm._bad(f"More than one {what} here is called {cm._plain(v)}" if hit else
                f"There’s no {what} called {cm._plain(v)} here")
    return hit.pop()


def _person(bid: str, v: Any) -> Optional[str]:
    if not v or _uuid(v):
        return _uuid(v) if v else None
    return _one(cm._need(f"/contacts?business_id=eq.{cm._q(bid)}&name=eq.{cm._q(cm._plain(v))}"
                         "&select=id,name&limit=5"), v, "person", "name")


class _Now:
    """The map as it reads now, read once: a change's befores, and what Undo
    and a waiting change are checked against."""

    def __init__(self, biz: Dict[str, Any]):
        self.biz, self.bid = biz, cm._bid(biz)
        self.m = cm._map(self.bid)
        self._defs: Optional[List[Dict[str, Any]]] = None
        self._shep: Optional[Dict[str, Any]] = None
        self.holders: Dict[str, Dict[str, Any]] = {}

    @property
    def defs(self) -> List[Dict[str, Any]]:
        if self._defs is None:
            self._defs = cr.defs(self.bid, with_drafts=True)
            if self._defs is None:
                raise HTTPException(503, cm.UNREAD)
        return self._defs

    def get(self, kind: str, rid: Optional[str]) -> Optional[Dict[str, Any]]:
        """One thing's fields as they read now (_vals); None when it isn't here."""
        q = f"business_id=eq.{cm._q(self.bid)}"
        if kind == "department":
            d = next((x for x in self.m.departments if x["id"] == rid), None)
            if d is None and rid:           # archived ones aren't on the map
                got = cm._need(f"/church_departments?id=eq.{cm._q(rid)}&{q}&select={cm.DEPT_COLS}&limit=1")
                d = cm._dept(got[0], []) if got else None
            return _vals(kind, d) if d else None
        if kind == "role":
            d = next((x for x in self.defs if x["id"] == rid), None)
            return _vals(kind, {**d, **self.m.roles.get(rid, {})}) if d else None
        if kind == "answers_to":
            got = cm._need(f"/church_leader_roles?id=eq.{cm._q(rid)}&{q}&status=eq.active&select={cm.LINK_COLS}&limit=1")
            self.holders[rid] = got[0] if got else {}
            return _vals(kind, got[0]) if got else None
        if kind == "settings":
            return _vals(kind, self.m.settings)
        if self._shep is None:
            self._shep = shep.settings(self.bid)
            if self._shep is None:
                raise HTTPException(503, cm.UNREAD)
        return _vals(kind, self._shep)


def _vals(kind: str, row: Dict[str, Any]) -> Dict[str, Any]:
    """A thing's fields as a change keeps them, and `at`: when it last changed."""
    out = {f: row.get(f) for f in FIELDS[kind] + MAKES.get(kind, ())}
    if kind == "department":
        out["units"] = sorted(({"kind": u["kind"], "ref": u.get("ref") or "",
                                "label": "" if u.get("ref") else u.get("label") or ""} for u in row.get("units") or []),
                              key=lambda u: (u["kind"], u["ref"], u["label"].casefold()))
    return {**out, "at": row.get("updated_at") or row.get("map_at")}


def _same(f: str, a: Any, b: Any) -> bool:
    def key(v: Any) -> Any:
        if f == "units":
            return sorted((u["kind"], u["ref"] or u["label"].casefold()) for u in v or [])
        return sorted(map(str, v)) if isinstance(v, list) else v
    return key(a) == key(b)


def _holder(now: _Now, raw: Dict[str, Any]) -> str:
    """The one active holder row of `person` (in `role`, when it's named)."""
    who, key = _person(now.bid, raw.get("person")), None
    if raw.get("role"):
        rid = _one(now.defs, raw["role"], "role", "key", "title")
        key = next((d["key"] for d in now.defs if d["id"] == rid), "")
    rows = [h for h in cm._holders(now.bid) if who and str(h["contact_id"]) == who and key in (None, h["role"])]
    if len(rows) != 1:
        cm._bad("They hold more than one role here: say which" if rows else "They don’t hold that role here")
    return str(rows[0]["id"])


def _op(now: _Now, raw: Any) -> Dict[str, Any]:
    """One part as asked -> {kind, id (None: it makes one), set}: its thing,
    by id or exact name, and the fields its write takes."""
    kind = raw.get("kind") if isinstance(raw, dict) else None
    if kind not in FIELDS:
        cm._bad("A change is made of departments, roles, who people answer to, the settings and Shepherding’s")
    set_ = {k: raw[k] for k in FIELDS[kind] if k in raw}
    for k, col in (("leader", PEOPLE[0]), ("overseer", PEOPLE[1]), ("to", PEOPLE[2])):
        if k in raw and col in FIELDS[kind]:
            set_[col] = _person(now.bid, raw[k])
    rid: Optional[str] = now.bid
    if kind == "department":
        rid = cm._id(raw["id"], "department") if raw.get("id") else (
            _one(now.m.departments, raw["department"], "department", "name") if raw.get("department") else None)
    elif kind == "role":
        rid = cm._id(raw["id"], "role") if raw.get("id") else (
            _one(now.defs, raw["role"], "role", "key", "title") if raw.get("role") else None)
        if rid and any(k in raw for k in MAKES["role"]):
            cm._bad("A role’s job changes on Leaders & roles, while no one holds it")
        set_.update({k: raw[k] for k in MAKES["role"] if k in raw and not rid})
    elif kind == "answers_to":
        if PEOPLE[2] not in set_:
            cm._bad("Say who they answer to, or nobody")
        rid = cm._id(raw["holder_id"], "role holder") if "holder_id" in raw else _holder(now, raw)
    return {"kind": kind, "id": rid, "set": set_}


# ─── Checked first, then written ──────────────────────────────────────

def _call(now: _Now, op: Dict[str, Any], by: Any, role: str, origin: str, pm: Optional[cm.Map] = None) -> Any:
    """One part through its own write. Given `pm` (the map as the parts
    before it would leave it), dry: every check, nothing written, and `pm`
    moved on."""
    biz, bid, kind, rid, body = now.biz, now.bid, op["kind"], op["id"], op["set"]
    dry, (dept_from, role_from) = pm is not None, SOURCE.get(origin, ("chief", "chief"))
    if op.get("delete"):            # Undo takes out a draft the change made
        if dry:
            return None
        if kind == "role":
            cr.archive_role(bid, rid)            # a draft goes outright
            return None
        q = f"business_id=eq.{cm._q(bid)}"
        if not (sb_clients.sb_delete_as_service(f"/church_department_units?{q}&department_id=eq.{cm._q(rid)}")
                and sb_clients.sb_delete_as_service(f"/church_departments?{q}&id=eq.{cm._q(rid)}")):
            raise HTTPException(503, cm.UNSAVED)
        return None
    if kind == "department":
        got = cm.save_department(biz, {**body, "id": rid} if rid else {"source": dept_from, **body}, by, m=pm, dry=dry)
        if dry:
            pm.departments = [d for d in pm.departments if d["id"] != rid] + (
                [] if got["status"] == "archived" else [{**got, "id": rid or f"new:{len(pm.departments)}"}])
        return got
    if kind == "role":
        got = (cr.update_role(bid, rid, body, dry=dry) if rid else
               cr.create_role(biz, {**body, "status": "draft"}, by_user=str(by or ""), source=role_from, dry=dry))
        if dry and rid:
            pm.roles[rid] = {**pm.roles.get(rid, {}),
                             **{k: got[k] for k in (*cr.SWITCHES, "made_for", "status") if k in got}}
        return got
    if kind == "answers_to":
        return cm.set_answers_to(biz, rid, body[PEOPLE[2]], dry=dry)
    if kind == "settings":
        got = cm.save_settings(biz, body, by, role, m=pm, dry=dry)
        if dry:
            pm.settings = {**pm.settings, **got["settings"]}
        return got
    return shep.save_settings(bid, body, str(by) if by else None, dry=dry)


def _after(kind: str, got: Dict[str, Any]) -> Dict[str, Any]:
    return _vals(kind, got["settings"] if kind == "settings" else got)


def _label(now: _Now, kind: str, rid: Optional[str], vals: Dict[str, Any]) -> str:
    if kind in ("department", "role"):
        return vals.get("name" if kind == "department" else "title") or f"A {kind}"
    if kind != "answers_to":
        return "Your church" if kind == "settings" else "Shepherding"
    h = now.holders.get(rid or "") or {}
    who = cm._people(now.bid, [h["contact_id"]]).get(str(h["contact_id"]), "") if h.get("contact_id") else ""
    title = next((d["title"] for d in now.defs if d["key"] == h.get("role")), "")
    return f"{who or 'Someone'} ({title})" if title else who or "Someone"


def _part(now: _Now, op: Dict[str, Any], was: Optional[Dict[str, Any]], got: Any) -> Optional[Dict[str, Any]]:
    """One part's record, with only the fields it changes; None when it changes nothing."""
    kind, rid = op["kind"], op["id"]
    if op.get("delete") or kind == "department" and got["status"] == "archived":
        if was is None or was["status"] == "archived":
            return None
        keep = FIELDS[kind] if op.get("delete") else ("status", "units")
        return {"kind": kind, "id": rid, "label": _label(now, kind, rid, was), "before": {f: was[f] for f in keep},
                "after": None, **({"deleted": True} if op.get("delete") else {})}
    after = _after(kind, got)
    if was is None:
        return {"kind": kind, "id": rid, "label": _label(now, kind, rid, after), "before": None,
                "after": {f: after[f] for f in FIELDS[kind] + MAKES.get(kind, ())}}
    moved = [f for f in FIELDS[kind] if f in op["set"] and not _same(f, was[f], after[f])]
    return {"kind": kind, "id": rid, "label": _label(now, kind, rid, was), "before": {f: was[f] for f in moved},
            "after": {f: after[f] for f in moved}} if moved else None


Plan = List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]


def _plan(now: _Now, ops: List[Dict[str, Any]], by: Any, role: str, origin: str) -> Plan:
    """Every part checked first, each against the map the parts before it
    would leave: (the write, its record or None)."""
    pm = copy.deepcopy(now.m)
    return [(op, _part(now, op, now.get(op["kind"], op["id"]) if op["id"] else None,
                       _call(now, op, by, role, origin, pm))) for op in ops]


def _write(now: _Now, plan: Plan, by: Any, role: str, origin: str) -> Tuple[List[Any], Optional[HTTPException]]:
    """Each part written in order. At the first that fails, it and the rest
    are marked not done: (the writes' answers, that failure)."""
    out: List[Any] = []
    for n, (op, p) in enumerate(plan):
        try:
            got = _call(now, op, by, role, origin)
        except HTTPException as e:
            for _o, rest in plan[n:]:
                if rest:
                    rest["done"] = False
            return out, e
        out.append(got)
        if p and p["after"] is not None and isinstance(got, dict):
            p["id"] = p["id"] or str(got["id"])
            a = _after(op["kind"], got)
            p["after"] = {f: a[f] for f in p["after"]}
    return out, None


def _money(parts: List[Optional[Dict[str, Any]]]) -> bool:
    """Whether a change touches money: a level, or a role's board yes."""
    for p in filter(None, parts):
        a = p["after"] or {}
        if p["kind"] == "settings" and any(k in a for k in cm.LEVELS) or \
                p["kind"] == "role" and "can_board_yes" in a and (p["before"] is not None or a["can_board_yes"]):
            return True
    return False


def _log(bid: str, status: str, parts: List[Dict[str, Any]], by: Any, origin: str, **more: Any) -> Optional[Dict[str, Any]]:
    at, by = _now(), str(by) if by else None
    row = {"business_id": bid, "status": status, "origin": origin, "phase": None, "said": "", "money": False,
           "parts": parts, "made_by": by, "made_at": at, "undoes": None, "error": "", **more}
    if status == "applied":
        row.update(applied_by=by, applied_at=at)
    got = sb_clients.sb_post_as_service("/church_map_changes", row)
    if isinstance(got, list) and got:
        return got[0]
    print(f"[church_map_batch] a {status} change at {bid} by {by} wasn’t logged ({len(parts)} parts)", flush=True)
    return None


def _brief(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return {"id": str(row["id"]), "status": row["status"], "money": bool(row.get("money"))} if row else None


def _failed(bid: str, parts: List[Dict[str, Any]], by: Any, origin: str, err: HTTPException, row: Any = None,
            **more: Any) -> HTTPException:
    """A write failed. When nothing got in, the write's own answer stands
    and nothing is logged (a waiting change still waits); else the change is
    kept failed, with what got in."""
    if all(p.get("done") is False for p in parts):
        return err
    said = {"status": "failed", "parts": parts, "error": str(err.detail)[:400]}
    if row is None:
        _log(bid, "failed", parts, by, origin, error=said["error"], **more)
    elif _set(bid, row["id"], said, ("pending", "failed")) is None:
        print(f"[church_map_batch] change {row['id']} at {bid} failed and couldn’t be marked so", flush=True)
    return HTTPException(err.status_code, f"{err.detail}{WENT_IN}")


def apply(biz: Dict[str, Any], changes: List[Dict[str, Any]], by: Any, origin: str, stage: bool = False,
          phase: Optional[str] = None, *, role: str, said: str = "") -> Dict[str, Any]:
    """Make one change (or, staged, keep it waiting for a yes). {change:
    {id, status, money} or None when it changed nothing, results: each
    part's write's own answer}."""
    _open()
    if origin not in ORIGINS or phase not in (None, *PHASES):
        cm._bad("That change says where it came from in a way this doesn’t know")
    if not isinstance(changes, list) or not 1 <= len(changes) <= PARTS_MAX:
        cm._bad(f"A change has 1 to {PARTS_MAX} parts")
    _may(role)
    now = _Now(biz)
    ops = [_op(now, c) for c in changes]
    named = [(o["kind"], o["id"]) for o in ops if o["id"]]
    if len(named) != len(set(named)):
        cm._bad("Name each department, role, person and setting once in a change")
    plan = _plan(now, ops, by, role, origin)
    parts = [p for _o, p in plan if p]
    more = {"phase": phase, "said": cm._plain(said)[:400], "money": _money(parts)}
    _may(role, more["money"])
    if stage:
        row = _log(now.bid, "pending", parts, by, origin, **more) if parts else None
        if parts and row is None:
            raise HTTPException(503, cm.UNSAVED)
        return {"change": _brief(row), "results": []}
    results, err = _write(now, plan, by, role, origin)
    if err is not None:
        raise _failed(now.bid, parts, by, origin, err, **more)
    return {"change": _brief(_log(now.bid, "applied", parts, by, origin, **more)) if parts else None,
            "results": results}


# ─── A change already logged ──────────────────────────────────────────

def _row(biz: Any, change_id: Any) -> Dict[str, Any]:
    got = cm._need(f"/church_map_changes?id=eq.{cm._q(cm._id(change_id, 'change'))}&business_id=eq."
                   f"{cm._q(cm._bid(biz))}&select={COLS}&limit=1")
    if not got:
        raise HTTPException(404, "That change isn’t here")
    return got[0]


def _set(bid: str, cid: Any, body: Dict[str, Any], was: Tuple[str, ...]) -> Optional[List[Dict[str, Any]]]:
    """Move one change on, only while it is still one of `was`. None when the write failed."""
    got = sb_clients.sb_patch_as_service(f"/church_map_changes?id=eq.{cm._q(cid)}&business_id=eq.{cm._q(bid)}"
                                         f"&status=in.({','.join(was)})", body)
    return got if isinstance(got, list) else None


def _moved(p: Dict[str, Any], cur: Optional[Dict[str, Any]]) -> str:
    """The first field that doesn't read as the part left it; "" when none."""
    if p["after"] is None:
        return "" if cur is None or cur["status"] == "archived" else "status"
    if cur is None:
        return "gone"
    return next((f for f, v in p["after"].items() if not _same(f, cur.get(f), v)), "")


def _neither(p: Dict[str, Any], cur: Optional[Dict[str, Any]]) -> str:
    """The first field reading neither as before nor as after; "" when none
    does, so writing the part is safe."""
    b, a = p["before"], p["after"] or {}
    if b is None or cur is None:
        return "" if cur is None and b is None else _moved(p, cur)
    if p["after"] is None and cur["status"] == "archived":
        return ""
    return next((f for f in {**b, **a} if not any(f in s and _same(f, cur.get(f), s[f]) for s in (b, a))), "")


def _since(p: Dict[str, Any], f: str, cur: Optional[Dict[str, Any]], how: str) -> str:
    label = p.get("label") or "That"
    if f == "gone":
        return f"{label} isn’t on the map any more"
    at = _parse((cur or {}).get("at"))
    on = f" on {at:%b} {at.day}" if at else ""
    what = f"{label}’s {WORD[f]} {'were' if f == 'units' else 'was'}" if WORD.get(f) else f"{label} was"
    return f"{what} {how}{on}"


def _redo(p: Dict[str, Any]) -> Dict[str, Any]:
    """The write that leaves a part's thing as its after."""
    if p.get("deleted"):
        return {"kind": p["kind"], "id": p["id"], "set": {}, "delete": True}
    return {"kind": p["kind"], "id": p.get("id"),
            "set": {"status": "archived"} if p["after"] is None else dict(p["after"])}


def _back(p: Dict[str, Any]) -> Dict[str, Any]:
    """The write that puts one part back: a draft it made is deleted, an
    active department it made archived, every other field as before."""
    if p["before"] is None:
        made_draft = p["kind"] == "role" or p["after"].get("status") == "draft"
        return {"kind": p["kind"], "id": p["id"], "set": {} if made_draft else {"status": "archived"},
                "delete": made_draft}
    return {"kind": p["kind"], "id": p["id"], "set": dict(p["before"])}


def _checked(now: _Now, ops: List[Dict[str, Any]], by: Any, role: str, origin: str, why: str) -> Plan:
    """_plan, where a write's own refusal (400, 404) is a 409: the change
    can't be made or put back as it stands."""
    try:
        return _plan(now, ops, by, role, origin)
    except HTTPException as e:
        if e.status_code in (400, 404):
            raise HTTPException(409, f"{why}: {e.detail}")
        raise


def _done_undo(bid: str, row: Dict[str, Any]) -> None:
    if row.get("undoes") and not _set(bid, row["undoes"], {"status": "undone", "undone_at": _now()}, ("applied",)):
        print(f"[church_map_batch] change {row['undoes']} at {bid} was put back but isn’t marked so", flush=True)


def apply_pending(biz: Dict[str, Any], change_id: Any, by: Any, *, role: str) -> Dict[str, Any]:
    """Make a change that waits for a yes, or finish one that failed."""
    _open()
    _may(role)
    row = _row(biz, change_id)
    if row["status"] not in ("pending", "failed"):
        raise HTTPException(409, "That change isn’t waiting to be made.")
    _may(role, bool(row.get("money")))
    now, parts, plan = _Now(biz), [dict(p) for p in row["parts"]], []
    for p in parts:
        cur = now.get(p["kind"], p["id"]) if p.get("id") else None
        p.pop("done", None)
        if p.get("id") and not _moved(p, cur):
            continue                        # already in
        f = _neither(p, cur)
        if f:
            raise HTTPException(409, _since(p, f, cur, "changed") + ", after this change was saved. Look at it again.")
        plan.append((_redo(p), p))
    _checked(now, [op for op, _p in plan], by, role, row["origin"], "That can’t be made now")
    results, err = _write(now, plan, by, role, row["origin"])
    if err is not None:
        raise _failed(now.bid, parts, by, row["origin"], err, row=row)
    saved = _set(now.bid, row["id"], {"status": "applied", "applied_by": str(by), "applied_at": _now(),
                                      "parts": parts, "error": ""}, ("pending", "failed"))
    if not saved:
        print(f"[church_map_batch] change {row['id']} at {now.bid} was made but isn’t marked so", flush=True)
    _done_undo(now.bid, row)
    return {"change": _brief((saved or [None])[0] or {**row, "status": "applied"}), "results": results}


def discard(biz: Dict[str, Any], change_id: Any, by: Any, *, role: str) -> Dict[str, Any]:
    """Let a change that waits for a yes go, unmade."""
    _open()
    _may(role)
    row = _row(biz, change_id)
    if row["status"] != "pending":
        raise HTTPException(409, "Only a change that waits for a yes can be discarded.")
    _may(role, bool(row.get("money")))
    saved = _set(cm._bid(biz), row["id"], {"status": "discarded"}, ("pending",))
    if saved is None:
        raise HTTPException(503, cm.UNSAVED)
    if not saved:
        raise HTTPException(409, "That change isn’t waiting any more.")
    return {"change": _brief(saved[0])}


def undo(biz: Dict[str, Any], change_id: Any, by: Any, *, role: str, origin: str = "office") -> Dict[str, Any]:
    """Put one change back, whole or not at all."""
    _open()
    _may(role)
    row = _row(biz, change_id)
    if row.get("undoes"):
        raise HTTPException(409, "That change put another one back. Change it directly instead.")
    if row["status"] != "applied":
        raise HTTPException(409, "That change was put back already." if row["status"] == "undone" else
                            "Only a change that was made can be put back.")
    at = _parse(row.get("applied_at"))
    if not at or datetime.now(timezone.utc) - at > timedelta(days=UNDO_DAYS):
        raise HTTPException(409, f"That change is more than {UNDO_DAYS} days old. Change it directly instead.")
    _may(role, bool(row.get("money")))
    now = _Now(biz)
    for p in row["parts"]:
        cur = now.get(p["kind"], p["id"]) if p.get("id") else None
        f = _moved(p, cur)
        if f:
            raise HTTPException(409, _since(p, f, cur, "changed again") + "; change it directly.")
    plan = _checked(now, [_back(p) for p in reversed(row["parts"])], by, role, origin, "That can’t be put back")
    parts = [p for _o, p in plan if p]
    more = {"money": bool(row.get("money")) or _money(parts), "undoes": str(row["id"])}
    results, err = _write(now, plan, by, role, origin)
    if err is not None:
        raise _failed(now.bid, parts, by, origin, err, **more)
    new = _log(now.bid, "applied", parts, by, origin, **more)
    _done_undo(now.bid, {"undoes": str(row["id"])})
    return {"change": _brief(new), "undone": str(row["id"]), "results": results}


# ─── A role's switches, saved on Leaders & roles (decision 3) ─────────

SWITCH_KEYS = (*cr.SWITCHES, "made_for")
SWITCH_SEAT = "Only the owner or an admin changes what a role can do."
BOARD_YES = "Only the owner changes who gives the board’s yes on money."


def switch_seat(bid: str, rid: Optional[str], changes: Dict[str, Any], role: str) -> None:
    """Decision 3: a role's switches (can_*, made_for) are the owner's or an
    admin's to change; its board yes, a yes on money, the owner's. Sending a
    board yes as it already reads is no change (as a money level the same
    again: CHURCH_LEADERS_MAP.md "As built in PR 5"). `rid` None: a new role."""
    if not any(k in changes for k in SWITCH_KEYS):
        return
    if role not in ("owner", "admin"):
        raise HTTPException(403, SWITCH_SEAT)
    if role == "owner" or "can_board_yes" not in changes:
        return
    now = False
    if rid:
        got = cm._rows(f"/church_role_defs?id=eq.{cm._q(rid)}&business_id=eq.{cm._q(bid)}&select=can_board_yes&limit=1")
        if got is None:
            raise HTTPException(503, "Couldn’t save that just now; try again.")
        now = bool(got and got[0].get("can_board_yes"))
    if bool(changes["can_board_yes"]) != now:
        raise HTTPException(403, BOARD_YES)


def save_role(biz: Dict[str, Any], role_id: Any, changes: Dict[str, Any], user: Any, *, role: str) -> Dict[str, Any]:
    """PATCH /church/roles/{id}: {role: the saved row, change}. A change of
    its switches needs the seat switch_seat says, everywhere; every other
    field keeps the route's. Where the map is open to this login
    (church_map.open_to) and step 2's file is there, a save that names a
    switch is one change (origin 'office', a role part, with the fields a
    part keeps), so the sheet's Undo puts it back; the role's other fields go
    in first, as today. Else it saves as it always has, logging nothing."""
    bid, by = cm._bid(biz), user.id
    rid = cr._uid(role_id, "role")
    switch_seat(bid, rid, changes, role)
    s = cm.step2_state() if any(k in changes for k in SWITCH_KEYS) and cm.open_to(user) else False
    if s is None:
        raise HTTPException(503, cm.UNREAD)
    if not s:
        return {"role": cr.update_role(bid, rid, changes), "change": None}
    rest = {k: v for k, v in changes.items() if k not in FIELDS["role"]}
    if rest:
        cr.update_role(bid, rid, rest)
    out = apply(biz, [{"kind": "role", "id": rid, **{k: v for k, v in changes.items() if k in FIELDS["role"]}}],
                by, "office", role=role)
    return {"role": out["results"][0], "change": out["change"]}


# ─── The sheet's list ─────────────────────────────────────────────────

def _say(f: str, v: Any, names: Dict[str, str]) -> str:
    import church_areas as ca
    import church_duties as cd
    if v is None and f in ("can_shepherd", *cm.LEVELS, *cm.PICKS, *PEOPLE):
        return {"can_shepherd": "when the Ministers setting is on"}.get(f, "nobody" if f in PEOPLE else "the usual")
    if v is None or v == []:
        return "none"
    if isinstance(v, bool):
        return "on" if v else "off"
    if f in cm.LEVELS:
        return f"${v / 100:,.0f}"
    if f == "units":
        return str(len(v))
    if f in ("support_duty", "area"):
        return ((cd.CATALOG if f == "support_duty" else ca.AREAS).get(v) or {}).get("label", str(v))
    if f == "made_for":
        return "; ".join(cr.STREAMS.get(s, s) for s in v)
    if isinstance(v, list) or f == "reports_to":
        return ", ".join(names.get(str(x), "a role") for x in (v if isinstance(v, list) else [v]))
    return names.get(str(v), "someone") if f in PEOPLE else str(v)


def _lines(p: Dict[str, Any], names: Dict[str, str]) -> List[str]:
    label, b, a = p.get("label") or "It", p.get("before"), p.get("after")
    left = " (this part didn’t go in)" if p.get("done") is False else ""
    if b is None:
        return [f"Made {label}{' as a draft' if (a or {}).get('status') == 'draft' else ''}{left}"]
    if a is None:
        return [f"{'Took out the draft' if p.get('deleted') else 'Archived'} {label}{left}"]
    return [f"{label}: {WORD[f] + ' ' if WORD.get(f) else ''}{_say(f, b.get(f), names)} → {_say(f, v, names)}{left}"
            for f, v in a.items()]


def recent(biz: Dict[str, Any], role: str) -> Dict[str, Any]:
    """GET /church/map/changes: what waits for a yes, and the last changes,
    newest first, each part a line in plain words."""
    _open()
    bid = cm._bid(biz)
    q = f"/church_map_changes?business_id=eq.{cm._q(bid)}&select={COLS}&order=made_at.desc"
    newest = lambda rows: sorted(rows, key=lambda r: str(r.get("made_at") or ""), reverse=True)  # noqa: E731
    waiting, rows = newest(cm._need(f"{q}&status=eq.pending&limit=50")), newest(cm._need(f"{q}&limit={RECENT}"))
    sides = [s for r in waiting + rows for p in r.get("parts") or [] for s in (p.get("before"), p.get("after")) if s]
    people = {str(s[f]) for s in sides for f in PEOPLE if s.get(f)}
    roles = {str(x) for s in sides for f in ("reports_to", *cm.PICKS) for x in
             (s.get(f) if isinstance(s.get(f), list) else [s.get(f)]) if x}
    names = cm._people(bid, people) if people else {}
    if roles:
        names.update({d["id"]: d["title"] for d in cr.defs(bid, with_drafts=True) or []})

    def show(r: Dict[str, Any]) -> Dict[str, Any]:
        at, may = _parse(r.get("applied_at")), role in ("owner", "admin") and (not r.get("money") or role == "owner")
        return {**{k: r.get(k) for k in COLS.split(",") if k != "parts"}, "id": str(r["id"]),
                "lines": [x for p in r.get("parts") or [] for x in _lines(p, names)],
                "can_undo": may and r["status"] == "applied" and not r.get("undoes") and bool(at)
                and datetime.now(timezone.utc) - at <= timedelta(days=UNDO_DAYS),
                "can_apply": may and r["status"] in ("pending", "failed"), "can_discard": may and r["status"] == "pending"}
    return {"pending": [show(r) for r in waiting], "recent": [show(r) for r in rows if r["status"] != "pending"]}
