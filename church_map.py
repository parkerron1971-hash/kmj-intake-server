"""church_map.py — the church leaders map, read core (docs/CHURCH_LEADERS_MAP.md §3).

Kevin, 2026-11-03: show how elders, pastors and ministry leaders connect to
the admins, the lead pastor and the people, for every church that subscribes;
"what i don't want is what i build works for love city but is broken and
messed up for other churches." Every church runs on one engine, and each
church's structure is data (supabase/APPLY-2026-11-04-church-map.sql).

    the switch ...... CHURCH_MAP = off | owner | on (default owner):
                      open_to(user) opens the office's routes to a login,
                      church_open(biz) the engine (sweeps, the member side)
                      to a church
    ready() ......... the migration's columns answer
    load(biz) ....... a church's map: its roles' switches, who a holder
                      answers to, its settings, its departments and what
                      hangs from each. None on a failed read, never empty
    can(m, role) .... a role's seven switches
    propose(biz) .... a read-only draft of departments, step 2's hook

Every reader takes it in this order (§3): closed, or not ready, runs today's
code; open and ready, the map decides wherever it knows, then the role's
switches, then today's rule; open and ready but load() failed, the caller
does what it does today on a failed read. Nothing reads it to decide
anything yet (PR 4 on); church_roles writes the switches once ready().

Server-only tables, read through the service role, always by business_id.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import church_roles as cr
import sb_clients
from auth_supabase import AuthedUser

ROLE_COLS = "id,key,job,status,handles," + ",".join(cr.SWITCHES) + ",made_for"
LINK_COLS = "id,contact_id,role,status,answers_to_contact_id"
SETTINGS_COLS = "pastor_from_cents,board_over_cents,pastor_yes_roles,office_overseer_roles,map_by,map_at"
DEPT_COLS = ("id,name,leader_contact_id,overseer_contact_id,support_duty,area,status,source,sort,updated_by,"
             "updated_at")
UNIT_COLS = "id,department_id,kind,group_id,role_id,board_id,worship_ministry_id,label"
# A unit's thing, by kind; the other kinds (a serve option, a space, a check line) are its label.
UNIT_REF = {"group": "group_id", "role": "role_id", "board": "board_id", "worship_ministry": "worship_ministry_id"}


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_MAP") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_to(user: AuthedUser) -> bool:
    """The office's map routes (PR 5), for this login."""
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        owner = (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()
        return (user.email or "").strip().lower() == owner
    return False


def church_open(biz: Any) -> bool:
    """The engine and the member side, for this church: on, or (owner) the
    platform owner's own church. Nobody signs in there as a login."""
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        import member_asks
        return member_asks.platform_church(biz.get("id") if isinstance(biz, dict) else biz)
    return False


# ─── Ready ────────────────────────────────────────────────────────────

_READY: Dict[str, bool] = {}


def ready() -> bool:
    """Whether the migration's columns answer: one probe, remembered for the
    process once they do (the file is one transaction, so one table's columns
    say all of it). False on any error, and asked again next time."""
    if _READY.get("ok"):
        return True
    try:
        rows = sb_clients.sb_get_as_service(f"/church_role_defs?select={','.join(cr.SWITCHES)},made_for&limit=1")
    except Exception:
        return False
    if isinstance(rows, list):
        _READY["ok"] = True
        return True
    return False


# ─── The map ──────────────────────────────────────────────────────────

@dataclass
class Map:
    """One church's map. `roles`: role id -> its key, job, handles, switches
    and made_for. `links`: active holder rows that name who they answer to.
    `settings`: the church's levels and role picks (None = today's platform
    rule). `departments`: draft and active, each with its `units`."""
    business_id: str
    roles: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    links: List[Dict[str, Any]] = field(default_factory=list)
    settings: Dict[str, Any] = field(default_factory=dict)
    departments: List[Dict[str, Any]] = field(default_factory=list)

    def active(self) -> List[Dict[str, Any]]:
        return [d for d in self.departments if d["status"] == "active"]

    def answers_to(self, contact_id: str, role: str = "") -> Optional[str]:
        """The person this holder answers to, for `role` (or any role they hold)."""
        return next((x["answers_to_contact_id"] for x in self.links
                     if x["contact_id"] == str(contact_id) and (not role or x["role"] == role)), None)

    def led_by(self, contact_id: str) -> List[Dict[str, Any]]:
        return [d for d in self.active() if d["leader_contact_id"] == str(contact_id)]

    def overseen_by(self, contact_id: str) -> List[Dict[str, Any]]:
        return [d for d in self.active() if d["overseer_contact_id"] == str(contact_id)]

    def department_of(self, kind: str, ref: Any) -> Optional[Dict[str, Any]]:
        """The active department a group, role, board, worship ministry, serve
        option, space or check line hangs from (a thing hangs from one)."""
        want = str(ref or "") if kind in UNIT_REF else str(ref or "").strip().casefold()
        for d in self.active():
            for u in d["units"]:
                if u["kind"] == kind and (u["ref"] if kind in UNIT_REF else u["label"].strip().casefold()) == want:
                    return d
        return None


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def _bid(biz: Any) -> str:
    return str(biz.get("id") if isinstance(biz, dict) else biz)


def role_switches(biz: Any) -> Optional[Dict[str, Dict[str, Any]]]:
    """Each active or draft role's switches, by role id; None when the read
    failed. Its own read: church_roles.defs's select never names the new
    columns, so it can't fail before the migration."""
    rows = _rows(f"/church_role_defs?business_id=eq.{_q(_bid(biz))}&status=in.(active,draft)"
                 f"&select={ROLE_COLS}&limit=300")
    if rows is None:
        return None
    return {str(r["id"]): {"key": r.get("key"), "job": r.get("job"), "handles": list(r.get("handles") or []),
                           **{k: r.get(k) for k in cr.SWITCHES}, "made_for": list(r.get("made_for") or [])}
            for r in rows}


def load(biz: Any) -> Optional[Map]:
    """The church's map, from five reads of its own. None when any failed:
    a caller stops as it does today on a failed read, and never takes an
    empty map for one that says nothing. Call it once ready()."""
    bid = _bid(biz)
    q = _q(bid)
    roles = role_switches(bid)
    links = _rows(f"/church_leader_roles?business_id=eq.{q}&answers_to_contact_id=not.is.null"
                  f"&select={LINK_COLS}&limit=1000")
    st = _rows(f"/church_role_settings?business_id=eq.{q}&select={SETTINGS_COLS}&limit=1")
    depts = _rows(f"/church_departments?business_id=eq.{q}&status=neq.archived&select={DEPT_COLS}"
                  "&order=sort.asc,name.asc&limit=200")
    units = _rows(f"/church_department_units?business_id=eq.{q}&select={UNIT_COLS}&limit=1000")
    if roles is None or links is None or st is None or depts is None or units is None:
        return None
    under: Dict[str, List[Dict[str, Any]]] = {}
    for u in units:
        ref = u.get(UNIT_REF[u["kind"]]) if u.get("kind") in UNIT_REF else None
        under.setdefault(str(u.get("department_id")), []).append({
            "id": str(u["id"]), "kind": u.get("kind"), "ref": str(ref) if ref else "", "label": u.get("label") or ""})
    return Map(
        business_id=bid, roles=roles,
        links=[{"id": str(x["id"]), "contact_id": str(x["contact_id"]), "role": str(x.get("role") or ""),
                "answers_to_contact_id": str(x["answers_to_contact_id"])}
               for x in links if x.get("status") == "active" and x.get("answers_to_contact_id")],
        settings={k: (st[0] if st else {}).get(k) for k in SETTINGS_COLS.split(",")},
        departments=[{**{k: d.get(k) for k in DEPT_COLS.split(",")}, "id": str(d["id"]),
                      "leader_contact_id": str(d["leader_contact_id"]) if d.get("leader_contact_id") else None,
                      "overseer_contact_id": str(d["overseer_contact_id"]) if d.get("overseer_contact_id") else None,
                      "status": d.get("status") or "active", "units": under.get(str(d["id"]), [])}
                     for d in depts])


# ─── A role's switches ────────────────────────────────────────────────

def can(m: Optional[Map], d: Dict[str, Any], *, ministers: Optional[bool] = None) -> Dict[str, Any]:
    """A role's seven switches: shepherd (None = it follows the church's
    Ministers setting; given `ministers`, that setting), oversee, lead,
    board_yes, see_all, and prayer and care, which are its handles (it takes
    shared prayer requests, care needs), bounded by its job. From the map's
    row for the role; else a legacy role's catalog row (church_follow_up.
    _effective_defs), or a row that carries its own; else its job's."""
    rid = str(d.get("id") or "")
    row = m.roles.get(rid) if m else None
    if row is None and rid.startswith("legacy:"):
        row = cr.LEGACY.get(str(d.get("key") or ""))
    if row is None and "can_lead" in d:
        row = d
    if row is None:
        row = cr.JOBS.get(str(d.get("job") or ""), cr.JOBS["office"])["switches"]
    handles = d.get("handles") if d.get("handles") is not None else (row.get("handles") or [])
    shepherd = row.get("can_shepherd")
    if shepherd is None and ministers is not None:
        shepherd = bool(ministers)
    return {"shepherd": shepherd, "oversee": bool(row.get("can_oversee")), "lead": bool(row.get("can_lead")),
            "board_yes": bool(row.get("can_board_yes")), "see_all": bool(row.get("can_see_all")),
            "prayer": "prayer_shared" in handles, "care": "care_need" in handles}


_SAYS = (("oversee", "can oversee a department"), ("lead", "leads (the leaders room)"),
         ("board_yes", "gives the board’s yes on money"), ("see_all", "sees everything"))


def says(m: Optional[Map], d: Dict[str, Any]) -> str:
    """A role's switches as Chief reads them, in a sentence."""
    c = can(m, d)
    words = ({True: ["shepherds families"], None: ["shepherds families when the church’s Ministers setting is on"]}
             .get(c["shepherd"], []) + [w for k, w in _SAYS if c[k]])
    made = (m.roles.get(str(d.get("id") or "")) or {}).get("made_for") if m else []
    if made:
        words.append("first in line for: " + "; ".join(cr.STREAMS[s] for s in made if s in cr.STREAMS))
    return "Switches: " + (", ".join(words) if words else "none")


# ─── A draft ──────────────────────────────────────────────────────────

def propose(biz: Any) -> Dict[str, Any]:
    """A read-only draft of the church's departments, the hook for step 2.

    TODO (step 2): draft from groups of kind 'ministry' and from each role's
    oversees_teams, a leader only where one person holds the source, never an
    overseer (an overseer changes who hears about a late item, so a person
    names one: docs/CHURCH_LEADERS_MAP.md §2). Until then it drafts nothing,
    and it never writes."""
    return {}
