"""chief_roster.py — Chief writes an event's volunteers the way the events room reads them.

Kevin, 2026-11-17: "Laquesha couldn't make event volunteer list. can we make
sure that she has access and ability to make list and or make volunteers
list." She asked Chief, and Chief tried to build a new room, which is the
owner's and the admins' (chief_areas.OWNERS). But the church's events room
(an event_roster module, "Services & Events" at Love City) already holds each
event's volunteers: the roles it needs, how many each, and who is on them.
Any office login adds an event there (create_module_entry is everyone's).

The shape is the app's (event_roster/types.ts) and the public page's
(events_rsvp_router):

    entry.data["_roles"] ........ [{id, label, needed}]; a role without a
                                  string id is DROPPED by both readers
    entry.data[signups_field] ... one signup a person: {name, contact_id?,
                                  status: "yes", role: <the role's id>}

So the model never writes a role's id: create_module_entry and
update_module_entry pass what it said ("roles", "volunteers") through
shape(), which gives each new role its id by the app's own rule (newRoleId),
keeps the id of a role already there (nobody falls off a role whose number
changed), and puts each named person on their role.

A new occasion's roles are the ones asked for. On an occasion already there,
a role named again keeps its id and takes the new number, a new one is
added, and the others stay: removing a role is done in the room, where the
people on it can be seen.

A role's two ticks (docs/EVENT_VOLUNTEERS.md 3.3): `kids` (works with kids,
so it needs a current background check) and `open` (anyone can sign up on
the public events page). A role with no `open` key keeps today's public
behaviour, so where the church asks its serving teams (event_volunteers'
switch open and the migration in: the office shows both ticks there), a role
Chief MAKES writes both outright, false unless asked (`explicit`). A role it
names again takes a tick only when one was said; a role it doesn't touch
keeps its keys exactly. Where asking is closed nothing changes: no tick is
written, and none the model sends is taken (the office has no tick there to
undo one). With nobody signed in (`take` false) no tick is taken either. A
tick that lets more people in on a role already there (kids off, open on) is
shown first and saved only on the person's yes (chief_event_volunteers).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROLES_FIELD = "_roles"
MAX_ROLES = 30
MAX_NEEDED = 50
MAX_PEOPLE = 100
LABEL_MAX = 60
NAME_MAX = 80


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def role_id(label: str, taken: Iterable[str]) -> str:
    """A stable id for a new role, as the app's newRoleId makes one: the
    label in lower case, runs of anything but a-z and 0-9 made one dash, the
    ends trimmed, 24 characters, then -2, -3… while it's taken."""
    taken = set(taken)
    base = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", str(label).lower())).strip("-")[:24] or "role"
    rid, n = base, 2
    while rid in taken:
        rid, n = f"{base}-{n}", n + 1
    return rid


def _needed(v: Any) -> int:
    try:
        n = round(float(v))
    except (TypeError, ValueError):
        n = 1
    return min(MAX_NEEDED, max(1, n))


KEPT_FLAGS = ("kids", "open")     # a role's own ticks, kept through every edit


def clean_roles(raw: Any) -> List[Dict[str, Any]]:
    """Roles already saved (an occasion's own, or the room's default), kept
    as both readers keep them: a string id and a label; needed 1-50. A
    role's `kids` and `open` (docs/EVENT_VOLUNTEERS.md 3.3: works with kids;
    anyone can sign up) are kept when they are true or false, so an edit
    by Chief never strips them."""
    if not isinstance(raw, list):
        return []
    return [{"id": r["id"], "label": _plain(r["label"]), "needed": _needed(r.get("needed", 1)),
             **{k: r[k] for k in KEPT_FLAGS if isinstance(r.get(k), bool)}}
            for r in raw
            if isinstance(r, dict) and isinstance(r.get("id"), str) and r["id"]
            and isinstance(r.get("label"), str) and _plain(r["label"])]


def _split(raw: str) -> List[str]:
    return [s for s in (x.strip() for x in re.split(r"[,;\n]", raw)) if s]


def asked_roles(raw: Any) -> List[Dict[str, Any]]:
    """The roles the model named: labels ("Greeters"), {"label", "needed"}
    (or name/role, count/people), or a map of label to number. `needed` is
    None when no number was said."""
    if isinstance(raw, str):
        raw = _split(raw)
    elif isinstance(raw, dict):
        raw = [{"label": k, "needed": v} for k, v in raw.items()]
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for r in raw:
        flags: Dict[str, bool] = {}
        if isinstance(r, str):
            label, needed, rid = r, None, None
        elif isinstance(r, dict):
            label = r.get("label") or r.get("name") or r.get("role") or ""
            needed = next((r[k] for k in ("needed", "count", "people") if r.get(k) not in (None, "")), None)
            rid = r.get("id") if isinstance(r.get("id"), str) else None
            flags = {k: r[k] for k in KEPT_FLAGS if isinstance(r.get(k), bool)}   # only what was said
        else:
            continue
        label = _plain(label)[:LABEL_MAX]
        if label:
            out.append({"id": rid, "label": label, "needed": needed, **flags})
    return out


def _find(roles: List[Dict[str, Any]], said: Optional[str], rid: Optional[str] = None) -> Optional[Dict[str, Any]]:
    said = _plain(said).lower()
    return next((r for r in roles if (rid and r["id"] == rid) or (said and (r["label"].lower() == said
                                                                            or r["id"] == said))), None)


def made_flags(said: Optional[Dict[str, Any]] = None) -> Dict[str, bool]:
    """A role Chief makes where asking is open: both ticks outright, false
    unless that one was said (docs/EVENT_VOLUNTEERS.md 3.3)."""
    said = said or {}
    return {k: said.get(k) is True for k in KEPT_FLAGS}


def merge_roles(have: List[Dict[str, Any]], asked: List[Dict[str, Any]],
                explicit: bool = False) -> List[Dict[str, Any]]:
    """`have` with `asked` added. A role named again (by its id or its
    label, any case) keeps its id and takes the new number when one was
    said; a new one gets its own id. Never more than MAX_ROLES. With
    `explicit` (asking open here), a new role writes both ticks (made_flags)
    and a role named again takes a tick only when one was said; without it
    no tick is written or taken."""
    out = [dict(r) for r in have]
    for a in asked:
        hit = _find(out, a["label"], a.get("id"))
        if hit:
            if a.get("needed") is not None:
                hit["needed"] = _needed(a["needed"])
            if explicit:
                hit.update({k: a[k] for k in KEPT_FLAGS if isinstance(a.get(k), bool)})
            continue
        if len(out) >= MAX_ROLES:
            break
        out.append({"id": role_id(a["label"], (r["id"] for r in out)), "label": a["label"],
                    "needed": _needed(1 if a.get("needed") is None else a["needed"]),
                    **(made_flags(a) if explicit else {})})
    return out


def asked_people(raw: Any) -> List[Dict[str, Any]]:
    """The people the model named: names, or {"name", "role", "contact_id"}."""
    if isinstance(raw, str):
        raw = _split(raw)
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for p in raw[:MAX_PEOPLE]:
        if isinstance(p, str):
            p = {"name": p}
        if not isinstance(p, dict):
            continue
        name = _plain(p.get("name"))[:NAME_MAX]
        if not name:
            continue
        cid = p.get("contact_id")
        out.append({"name": name, "role": _plain(p.get("role"))[:LABEL_MAX] or None,
                    "contact_id": str(cid).strip() if isinstance(cid, str) and cid.strip() else None})
    return out


def place(roles: List[Dict[str, Any]], signups: List[Dict[str, Any]],
          people: List[Dict[str, Any]],
          explicit: bool = False) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Each person on their role: (roles, signups, the signups added). A
    role nobody listed is added for them, needing as many as were put on it
    (with `explicit`, both its ticks off: made_flags). Someone already on
    that role (by name or contact) isn't added twice."""
    roles = [dict(r) for r in roles]
    signups = list(signups)
    added: List[Dict[str, Any]] = []
    made: Dict[str, int] = {}
    for p in people:
        role = _find(roles, p["role"]) if p["role"] else None
        if p["role"] and not role and len(roles) < MAX_ROLES:
            role = {"id": role_id(p["role"], (r["id"] for r in roles)), "label": p["role"], "needed": 1,
                    **(made_flags() if explicit else {})}
            roles.append(role)
            made[role["id"]] = 0
        rid = role["id"] if role else None
        name = p["name"].lower()
        if any(isinstance(s, dict) and (s.get("status") or "yes") == "yes" and s.get("role") == rid
               and (_plain(s.get("name")).lower() == name or (p["contact_id"] and s.get("contact_id") == p["contact_id"]))
               for s in signups):
            continue
        row: Dict[str, Any] = {"name": p["name"], "status": "yes"}
        if p["contact_id"]:
            row["contact_id"] = p["contact_id"]
        if rid:
            row["role"] = rid
            if rid in made:
                made[rid] += 1
        signups.append(row)
        added.append(row)
    for r in roles:
        if made.get(r["id"]):
            r["needed"] = _needed(made[r["id"]])
    return roles, signups, added


def _fields(module: Dict[str, Any]) -> set:
    schema = module.get("schema") if isinstance(module.get("schema"), dict) else {}
    return {f.get("name") for f in schema.get("fields") or [] if isinstance(f, dict)}


def params(module: Dict[str, Any]) -> Dict[str, Any]:
    p = module.get("archetype_params") if isinstance(module.get("archetype_params"), dict) else {}
    return {"title_field": str(p.get("title_field") or "title"),
            "signups_field": str(p.get("signups_field") or "signups"),
            "roles": clean_roles(p.get("roles"))}


def asks_for_roster(action: Dict[str, Any]) -> bool:
    """Whether an entry write says anything about roles or volunteers."""
    data = action.get("data") if isinstance(action.get("data"), dict) else {}
    return any(action.get(k) not in (None, "", []) for k in ("roles", "volunteers")) or any(
        k in data for k in (ROLES_FIELD, "roles", "volunteers"))


def shape(module: Dict[str, Any], patch: Dict[str, Any], before: Optional[Dict[str, Any]] = None,
          roles: Any = None, volunteers: Any = None,
          explicit: bool = False, take: bool = True) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """The data to save for an occasion in an event_roster room, and what
    changed: {"roles": the occasion's roles now, "added": the signups added}.

    `patch` is what the model put in `data` (a new occasion's whole data,
    or an update's changes); `before` the occasion's data as it was (None
    for a new one). Roles and people may come beside `data` ("roles",
    "volunteers") or inside it ("_roles", or "roles"/"volunteers" when the
    room has no field of that name). `explicit`: asking is open at this
    church (chief_event_volunteers.roles_explicit), so a role made here
    writes its two ticks (see the module's note). `take`: someone signed in
    is asking; without them (an unattended run, an outside agent) no tick
    the model sent is taken, and every role keeps its own."""
    p = params(module)
    fields = _fields(module)
    patch = dict(patch or {})
    asked = asked_roles(patch.pop(ROLES_FIELD)) if ROLES_FIELD in patch else []
    people: List[Dict[str, Any]] = []
    if "roles" in patch and "roles" not in fields:
        asked += asked_roles(patch.pop("roles"))
    if "volunteers" in patch and "volunteers" not in fields:
        people += asked_people(patch.pop("volunteers"))
    asked += asked_roles(roles)
    people += asked_people(volunteers)
    out = {**(before or {}), **patch}
    own = (before or {}).get(ROLES_FIELD)
    if before is None:
        start = [] if asked else p["roles"]            # a new occasion: the roles asked for
    else:
        start = clean_roles(own) if isinstance(own, list) else p["roles"]
    if not asked and not people:
        return out, {"roles": start, "added": []}
    if not explicit or not take:
        # Asking closed here, or nobody signed in: a tick the model sent is
        # never taken (as today), and every role keeps its own.
        asked = [{k: v for k, v in a.items() if k not in KEPT_FLAGS} for a in asked]
    now = merge_roles(start, asked, explicit)
    raw = out.get(p["signups_field"])
    signups = [s for s in raw if isinstance(s, dict)] if isinstance(raw, list) else []
    now, signups, added = place(now, signups, people, explicit)
    if asked or now != start or isinstance(own, list):
        out[ROLES_FIELD] = now
    if people:
        out[p["signups_field"]] = signups
    return out, {"roles": now, "added": added}


def roles_words(roles: List[Dict[str, Any]]) -> str:
    """'3 volunteer roles: Greeters 4, Parking 2, Kids 3', for a label."""
    if not roles:
        return ""
    each = ", ".join(f"{r['label']} {r['needed']}" for r in roles[:8]) + (", …" if len(roles) > 8 else "")
    return f"{len(roles)} volunteer role{'' if len(roles) == 1 else 's'}: {each}"
