"""
church_shepherding.py — every member family has a shepherd.

Kevin, 2026-10-17: "yes you can start design and do as what we planned and
those that can shepherd are elders and pastors. visitors should go under
welcome for now." Then: Ministers off by default, 12 families per shepherd
and 10 for the Lead Pastor, a monthly rhythm (canvas 31su6kdYmYecH5b2NxjBJN,
boards 1-3, 6-8).

Who shepherds: a role on the senior job, and pastoral roles titled pastor,
elder, bishop, overseer or shepherd; roles titled minister only when the
church turns Ministers on. Only people who said yes (active holders).
Deacons and the Care team take care needs, not families. Visitors stay
with the Welcome role.

What a shepherd is given is a unit: a recorded family with a member in it
(`h:<household id>`), or a member in no family at all (`c:<contact id>`, a
family of one, made a household when the pastor approves). A member who is
a child is never a unit: children belong to their family.

Chief proposes; the pastor moves any family and approves; only then is
anything written or sent:
  1. someone who knows them: leads a group one of them is in, or took
     one of their cards on the Follow-up board;
  2. families stay whole (units);
  3. never their own: a shepherd's own family goes to someone else;
  4. even loads, never over the number set (the Lead Pastor's is lower);
  5. close by: the same ZIP code, when Chief has an address.

A shepherd sees their families on their Lead tab (member_portal_lead), logs
a call, a visit, a text or a talk at church, and can ask for a pastor. They
never see giving, prayer kept for the pastors, a child's care notes, or
other families. Drifting, birthdays, care needs and Chief's questions are
round two; this module says nothing about them yet.

  settings / save_settings      the switch, the caps, the rhythm
  overview(biz)                 Operate → Follow-up → Shepherding
  propose / proposal / move_in_draft / discard / approve
  move(biz, household, shepherd)  after approval
  office_family(biz, household)   a family's touches, for the office
  my_families / family_for / log_touch   the shepherd's Lead tab
  tell_shepherds / tell_new_shepherd / tell_pastor   the emails
"""
from __future__ import annotations

import html
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote

from fastapi import HTTPException

import church_families as cf
import sb_clients

logger = logging.getLogger("church_shepherding")

DEFAULTS: Dict[str, Any] = {"ministers": False, "cap": 12, "lead_cap": 10, "rhythm_days": 30}
SHEPHERD_TITLE = re.compile(r"pastor|elder|bishop|overseer|shepherd", re.I)
MINISTER_TITLE = re.compile(r"minister", re.I)
KINDS = {"call": "Called", "visit": "Visited", "text": "Texted", "church": "Talked at church"}
MAX_NOTE = 2000
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_UNIT = re.compile(r"^[hc]:[0-9a-fA-F-]{36}$")
NO_SHEPHERDS = "No pastor or elder has said yes to a role yet"


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


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def _uid(value: Any, what: str) -> str:
    s = str(value or "").strip()
    if not _UUID.match(s):
        raise HTTPException(400, f"That {what} isn't valid")
    return s.lower()


def initials(name: str) -> str:
    import church_follow_up as cfu
    return cfu.initials(name)


def family_initial(name: str) -> str:
    words = [w for w in _plain(name).split(" ") if w.casefold() not in ("the", "family", "and")]
    return (words[0][:1].upper() if words else "?") or "?"


def _unavailable(what: str = "Shepherding") -> HTTPException:
    return HTTPException(503, f"{what} couldn't be loaded. Try again in a moment.")


# ─── settings ─────────────────────────────────────────────────────────

def settings(biz_id: str) -> Optional[Dict[str, Any]]:
    rows = _rows(f"/church_shepherd_settings?business_id=eq.{_q(biz_id)}&select=*&limit=1")
    if rows is None:
        return None
    out = dict(DEFAULTS)
    if rows:
        out.update({k: rows[0][k] for k in DEFAULTS if rows[0].get(k) is not None})
    out["ministers"] = bool(out["ministers"])
    for k in ("cap", "lead_cap", "rhythm_days"):
        out[k] = int(out[k])
    return out


def save_settings(biz_id: str, body: Dict[str, Any], by_user: Optional[str]) -> Dict[str, Any]:
    cur = settings(biz_id)
    if cur is None:
        raise _unavailable()
    row = dict(cur)
    if body.get("ministers") is not None:
        row["ministers"] = bool(body["ministers"])
    for key, what in (("cap", "families per shepherd"), ("lead_cap", "families for the Lead Pastor")):
        if body.get(key) is not None:
            try:
                n = int(body[key])
            except (TypeError, ValueError):
                raise HTTPException(400, f"Give a number of {what}.")
            if not 1 <= n <= 40:
                raise HTTPException(400, f"{what[0].upper() + what[1:]} is between 1 and 40.")
            row[key] = n
    row.update({"business_id": str(biz_id), "updated_by": by_user, "updated_at": _iso(_now())})
    saved = sb_clients.sb_post_as_service("/church_shepherd_settings?on_conflict=business_id", row,
                                          prefer="return=representation,resolution=merge-duplicates")
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Nothing was changed. Try again.")
    return settings(biz_id) or {k: row[k] for k in DEFAULTS}


# ─── who shepherds ────────────────────────────────────────────────────

def role_rows(all_defs: List[Dict[str, Any]], st: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The senior and pastoral roles, each with whether it shepherds."""
    out = []
    for d in all_defs:
        if d.get("job") not in ("senior", "pastoral"):
            continue
        title = _plain(d.get("title"))
        switch = None
        if d["job"] == "senior" or SHEPHERD_TITLE.search(title):
            shep = True
        elif MINISTER_TITLE.search(title):
            shep, switch = bool(st.get("ministers")), "ministers"
        else:
            shep = False
        out.append({"def": d, "shepherds": shep, "switch": switch, "lead": d["job"] == "senior"})
    return out


def shepherds_from(roles: List[Dict[str, Any]], holders: Dict[str, List[Dict[str, Any]]],
                   st: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """contact id → the shepherd: name, email, their role's title, lead, cap.
    The Lead Pastor first, then in the library's order."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in roles:
        if not r["shepherds"]:
            continue
        d = r["def"]
        for h in holders.get(d["key"], []):
            cid = str(h["contact_id"])
            s = out.get(cid)
            if s is None:
                out[cid] = s = {"contact_id": cid, "name": _plain(h.get("name")) or "Someone",
                                "email": h.get("email") or "", "role": _plain(d.get("title")), "role_def": d,
                                "lead": False}
            if r["lead"] and not s["lead"]:
                s["lead"] = True
    for s in out.values():
        s["cap"] = int(st["lead_cap"] if s["lead"] else st["cap"])
        s["initials"] = initials(s["name"])
    return dict(sorted(out.items(), key=lambda kv: (not kv[1]["lead"], 0)))


# ─── everything the office page and the proposal read ─────────────────

def load(biz_id: str, *, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """One read of the church: roles, shepherds, members, families, who has
    whom. None when any read failed (never read a failure as "nobody")."""
    import church_follow_up as cfu
    import church_roles as cr
    b = str(biz_id)
    now = now or _now()
    all_defs = cr.defs(b)
    holder_rows = cfu.roles(b)
    st = settings(b)
    members = cf.members(b)
    homes = _rows(f"/households?business_id=eq.{_q(b)}&select=id,name,created_at&limit=10000")
    adults = _rows(f"/household_adults?business_id=eq.{_q(b)}&select=household_id,contact_id,relationship&limit=20000")
    kids = _rows(f"/children?business_id=eq.{_q(b)}&select=id,household_id,first_name,last_name,birthdate,contact_id,active"
                 "&limit=20000")
    assigned = _rows(f"/church_shepherds?business_id=eq.{_q(b)}&select=household_id,shepherd_contact_id,assigned_at,reason"
                     "&limit=10000")
    since = _iso(now - timedelta(days=400))
    touches = _rows(f"/church_shepherd_touches?business_id=eq.{_q(b)}&created_at=gte.{_q(since)}"
                    "&select=household_id,kind,created_at,shepherd_contact_id&order=created_at.desc&limit=20000")
    if any(x is None for x in (all_defs, holder_rows, st, members, homes, adults, kids, assigned, touches)):
        return None
    holders = cr.active_holders(holder_rows)
    roles = role_rows(all_defs, st)
    shepherds = shepherds_from(roles, holders, st)
    member_by = {str(m["id"]): m for m in members}
    home_by = {str(h["id"]): h for h in homes}
    adults_of: Dict[str, List[str]] = {}
    homes_of: Dict[str, Set[str]] = {}
    for a in adults:
        hid, cid = str(a["household_id"]), str(a["contact_id"])
        adults_of.setdefault(hid, []).append(cid)
        homes_of.setdefault(cid, set()).add(hid)
    kids_of: Dict[str, List[Dict[str, Any]]] = {}
    child_contacts: Set[str] = set()
    for k in kids:
        if k.get("active") is False:
            continue
        kids_of.setdefault(str(k["household_id"]), []).append(k)
        if k.get("contact_id"):
            child_contacts.add(str(k["contact_id"]))
            homes_of.setdefault(str(k["contact_id"]), set()).add(str(k["household_id"]))
    last_touch: Dict[str, Dict[str, Any]] = {}
    for t in touches:
        last_touch.setdefault(str(t["household_id"]), t)

    units: List[Dict[str, Any]] = []
    for hid, h in home_by.items():
        people = adults_of.get(hid, []) + [str(k["contact_id"]) for k in kids_of.get(hid, []) if k.get("contact_id")]
        if not any(p in member_by for p in people):
            continue
        zips = [cf.zip_of(cf._meta(member_by[p]).get("address")) for p in adults_of.get(hid, []) if p in member_by]
        units.append({"unit": f"h:{hid}", "household_id": hid, "contact_id": None,
                      "name": _plain(h.get("name")) or "A family",
                      "size": len(adults_of.get(hid, [])) + len(kids_of.get(hid, [])),
                      "people": people, "zip": next((z for z in zips if z), "")})
    for cid, m in member_by.items():
        if cid in homes_of or cid in child_contacts or cf.is_child(m, now.date()):
            continue
        units.append({"unit": f"c:{cid}", "household_id": None, "contact_id": cid,
                      "name": _plain(m.get("name")) or "Someone", "size": 1, "people": [cid],
                      "zip": cf.zip_of(cf._meta(m).get("address"))})
    units.sort(key=lambda u: u["name"].casefold())
    assigned_by = {str(a["household_id"]): a for a in assigned}
    return {"biz": b, "now": now, "settings": st, "defs": all_defs, "holders": holders, "roles": roles,
            "shepherds": shepherds, "members": member_by, "homes": home_by, "adults_of": adults_of,
            "kids_of": kids_of, "homes_of": homes_of, "units": units, "assigned": assigned_by,
            "last_touch": last_touch}


def _placed(ctx: Dict[str, Any], u: Dict[str, Any]) -> Optional[str]:
    """The current shepherd of a unit, if it has one who still shepherds."""
    if not u["household_id"]:
        return None
    a = ctx["assigned"].get(u["household_id"])
    if a and str(a["shepherd_contact_id"]) in ctx["shepherds"]:
        return str(a["shepherd_contact_id"])
    return None


def _reached(ctx: Dict[str, Any], hid: str) -> bool:
    t = ctx["last_touch"].get(hid)
    at = _parse((t or {}).get("created_at"))
    return bool(at and ctx["now"] - at <= timedelta(days=ctx["settings"]["rhythm_days"]))


def waiting_units(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [u for u in ctx["units"] if not _placed(ctx, u)]


def _held(ctx: Dict[str, Any]) -> Dict[str, int]:
    out = {cid: 0 for cid in ctx["shepherds"]}
    for u in ctx["units"]:
        s = _placed(ctx, u)
        if s:
            out[s] += 1
    return out


def overview(biz: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Operate → Follow-up → Shepherding."""
    b = str(biz["id"])
    ctx = load(b)
    visitors = _rows(f"/contacts?business_id=eq.{_q(b)}&status=eq.lead&select=id&limit=20000")
    draft = _rows(f"/church_shepherd_drafts?business_id=eq.{_q(b)}&select=rows,made_at&limit=1")
    if ctx is None or visitors is None or draft is None:
        return None
    st = ctx["settings"]
    holders = ctx["holders"]
    roles = [{"role_id": r["def"]["id"], "key": r["def"]["key"], "title": r["def"]["title"], "job": r["def"]["job"],
              "shepherds": r["shepherds"], "switch": r["switch"], "lead": r["lead"],
              "holders": [{"contact_id": str(h["contact_id"]), "name": _plain(h.get("name")) or "Someone"}
                          for h in holders.get(r["def"]["key"], [])]} for r in ctx["roles"]]
    care = [d["title"] for d in ctx["defs"] if d.get("job") == "care"]
    wd = next((d for d in ctx["defs"] if d.get("job") == "welcome"), None)
    welcome = ({"title": wd["title"], "names": [_plain(h.get("name")) for h in holders.get(wd["key"], [])]}
               if wd else None)
    cards: Dict[str, Dict[str, Any]] = {
        cid: {"contact_id": cid, "name": s["name"], "initials": s["initials"], "role": s["role"], "lead": s["lead"],
              "cap": s["cap"], "held": 0, "reached": 0, "families": []} for cid, s in ctx["shepherds"].items()}
    waiting, placed, reached = [], 0, 0
    households = sum(1 for u in ctx["units"] if u["household_id"])
    for u in ctx["units"]:
        s = _placed(ctx, u)
        if not s:
            waiting.append({"unit": u["unit"], "name": u["name"], "size": u["size"]})
            continue
        placed += 1
        hid = u["household_id"]
        t = ctx["last_touch"].get(hid) or {}
        hit = _reached(ctx, hid)
        reached += 1 if hit else 0
        c = cards[s]
        c["held"] += 1
        c["reached"] += 1 if hit else 0
        c["families"].append({"household_id": hid, "name": u["name"], "size": u["size"],
                              "since": ctx["assigned"][hid].get("assigned_at"),
                              "last_touch_at": t.get("created_at"), "last_touch_kind": t.get("kind")})
    d = draft[0] if draft else None
    return {
        "settings": st,
        "roles": roles,
        "care_titles": care,
        "welcome": welcome,
        "counts": {"members": len(ctx["members"]), "units": len(ctx["units"]), "households": households,
                   "singles": len(ctx["units"]) - households, "placed": placed, "waiting": len(waiting),
                   "visitors": len(visitors), "reached": reached},
        "families_empty": households == 0,
        "shepherds": list(cards.values()),
        "waiting": waiting,
        "draft": {"made_at": d.get("made_at"), "rows": len(d.get("rows") or [])} if d else None,
    }


# ─── the proposal ─────────────────────────────────────────────────────

def _own(ctx: Dict[str, Any], shepherd: str, u: Dict[str, Any]) -> bool:
    if u["contact_id"] == shepherd:
        return True
    return bool(u["household_id"] and u["household_id"] in ctx["homes_of"].get(shepherd, set()))


def _ties(biz: str, ctx: Dict[str, Any]) -> Optional[Dict[Tuple[str, str], str]]:
    """(unit, shepherd) → why the shepherd already knows them."""
    groups = _rows(f"/groups?business_id=eq.{_q(biz)}&select=id,name&limit=2000")
    gm = _rows(f"/group_members?business_id=eq.{_q(biz)}&select=group_id,contact_id,role&limit=20000")
    fus = _rows(f"/church_follow_ups?business_id=eq.{_q(biz)}&select=contact_id,leader_contact_id&limit=20000")
    if groups is None or gm is None or fus is None:
        return None
    gname = {str(g["id"]): _plain(g.get("name")) or "a group" for g in groups}
    leads: Dict[str, Set[str]] = {}
    inside: Dict[str, Set[str]] = {}
    for r in gm:
        g, c = str(r["group_id"]), str(r["contact_id"])
        inside.setdefault(c, set()).add(g)
        if r.get("role") == "leader":
            leads.setdefault(c, set()).add(g)
    took: Dict[str, Set[str]] = {}
    for f in fus:
        if f.get("leader_contact_id"):
            took.setdefault(str(f["leader_contact_id"]), set()).add(str(f["contact_id"]))
    out: Dict[Tuple[str, str], str] = {}
    for u in ctx["units"]:
        for s in ctx["shepherds"]:
            why = ""
            for p in u["people"]:
                if p == s:
                    continue
                m = ctx["members"].get(p)
                first = cf.first_name(m) if m else "one of them"
                shared = sorted(leads.get(s, set()) & inside.get(p, set()), key=lambda g: gname.get(g, ""))
                if shared:
                    why = f"Leads {gname.get(shared[0], 'a group')}, which {first} is in"
                    break
                if p in took.get(s, set()) and not why:
                    why = f"Took {first}’s card on the Follow-up board"
            if why:
                out[(u["unit"], s)] = why
    return out


def _shepherd_zips(biz: str, ctx: Dict[str, Any]) -> Dict[str, str]:
    ids = list(ctx["shepherds"])
    if not ids:
        return {}
    rows = _rows(f"/contacts?business_id=eq.{_q(biz)}&id=in.({','.join(_q(i) for i in ids)})&select=id,metadata") or []
    return {str(r["id"]): cf.zip_of(cf._meta(r).get("address")) for r in rows}


def _draft(biz: str) -> Optional[Dict[str, Any]]:
    rows = _rows(f"/church_shepherd_drafts?business_id=eq.{_q(biz)}&select=rows,made_at&limit=1")
    if rows is None:
        return None
    return rows[0] if rows else {}


def _save_draft(biz: str, rows: List[Dict[str, Any]], by_user: Optional[str], made_at: Optional[str] = None) -> str:
    stamp = made_at or _iso(_now())
    keep = [{k: r.get(k) for k in ("unit", "shepherd_contact_id", "reason", "why", "moved")} for r in rows]
    saved = sb_clients.sb_post_as_service("/church_shepherd_drafts?on_conflict=business_id",
                                          {"business_id": biz, "rows": keep, "made_at": stamp, "made_by": by_user},
                                          prefer="return=representation,resolution=merge-duplicates")
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "The proposal didn't save. Try again in a moment.")
    return stamp


def _wait_why(ctx: Dict[str, Any]) -> str:
    return "No shepherd has room" if ctx["shepherds"] else NO_SHEPHERDS


def _view(ctx: Dict[str, Any], rows: List[Dict[str, Any]], made_at: Optional[str]) -> Dict[str, Any]:
    by_unit = {u["unit"]: u for u in ctx["units"]}
    held = _held(ctx)
    count = dict(held)
    out_rows = []
    for r in rows:
        u = by_unit.get(r["unit"])
        if not u:
            continue
        s = r.get("shepherd_contact_id")
        if s and s in count:
            count[s] += 1
        out_rows.append({"unit": u["unit"], "name": u["name"], "size": u["size"],
                         "shepherd_contact_id": s if s in ctx["shepherds"] else None,
                         "reason": r.get("reason") if s in ctx["shepherds"] or not s else "wait",
                         "why": r.get("why") if s in ctx["shepherds"] or not s else _wait_why(ctx),
                         "moved": bool(r.get("moved"))})
    out_rows.sort(key=lambda r: r["name"].casefold())
    sheps = [{"contact_id": cid, "name": s["name"], "initials": s["initials"], "role": s["role"], "lead": s["lead"],
              "cap": s["cap"], "count": count.get(cid, 0)} for cid, s in ctx["shepherds"].items()]
    return {"proposal": {
        "made_at": made_at,
        "shepherds": sheps,
        "rows": out_rows,
        "waiting": sum(1 for r in out_rows if not r["shepherd_contact_id"]),
        "over": [{"contact_id": s["contact_id"], "name": s["name"], "count": s["count"], "cap": s["cap"]}
                 for s in sheps if s["count"] > s["cap"]],
    }}


def _current_rows(ctx: Dict[str, Any], stored: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The stored rows still waiting, then anyone who started waiting since."""
    waiting = {u["unit"] for u in waiting_units(ctx)}
    rows = [dict(r) for r in stored if r.get("unit") in waiting]
    have = {r["unit"] for r in rows}
    for u in waiting_units(ctx):
        if u["unit"] not in have:
            rows.append({"unit": u["unit"], "shepherd_contact_id": None, "reason": "wait",
                         "why": "Waiting since Chief proposed", "moved": False})
    return rows


def build(ctx: Dict[str, Any], ties: Dict[Tuple[str, str], str], zips: Dict[str, str],
          prior: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Chief's proposal for every waiting unit, keeping the pastor's moves."""
    sheps = ctx["shepherds"]
    load_ = _held(ctx)
    by_unit = {u["unit"]: u for u in ctx["units"]}
    rows: List[Dict[str, Any]] = []
    kept: Set[str] = set()
    for r in prior:
        u = by_unit.get(r.get("unit"))
        if not r.get("moved") or not u or _placed(ctx, u):
            continue
        s = r.get("shepherd_contact_id")
        if s and (s not in sheps or _own(ctx, s, u)):
            continue
        rows.append({"unit": u["unit"], "shepherd_contact_id": s, "reason": "moved", "why": "You chose", "moved": True})
        kept.add(u["unit"])
        if s:
            load_[s] += 1
    rest = [u for u in waiting_units(ctx) if u["unit"] not in kept]
    rest.sort(key=lambda u: (not any((u["unit"], s) in ties for s in sheps), not u["zip"], u["name"].casefold()))
    for u in rest:
        cands = [s for s in sheps if not _own(ctx, s, u) and load_[s] < sheps[s]["cap"]]
        fill = lambda s: (load_[s] / max(1, sheps[s]["cap"]), load_[s], sheps[s]["name"].casefold())  # noqa: E731
        pick, reason, why = None, "wait", _wait_why(ctx)
        tied = [s for s in cands if (u["unit"], s) in ties]
        near = [s for s in cands if u["zip"] and zips.get(s) == u["zip"]]
        if tied:
            pick = min(tied, key=fill)
            reason, why = "knows", ties[(u["unit"], pick)]
        elif near:
            pick = min(near, key=fill)
            reason, why = "close", f"Same part of town ({u['zip']})"
        elif cands:
            pick = min(cands, key=fill)
            reason, why = "even", "Room on their list"
        if pick:
            load_[pick] += 1
        rows.append({"unit": u["unit"], "shepherd_contact_id": pick, "reason": reason, "why": why, "moved": False})
    return rows


def propose(biz: Dict[str, Any], by_user: Optional[str]) -> Dict[str, Any]:
    b = str(biz["id"])
    ctx = load(b)
    if ctx is None:
        raise _unavailable()
    ties = _ties(b, ctx)
    prior = _draft(b)
    if ties is None or prior is None:
        raise _unavailable()
    rows = build(ctx, ties, _shepherd_zips(b, ctx), prior.get("rows") or [])
    stamp = _save_draft(b, rows, by_user)
    return _view(ctx, rows, stamp)


def proposal(biz: Dict[str, Any]) -> Dict[str, Any]:
    b = str(biz["id"])
    ctx = load(b)
    d = _draft(b)
    if ctx is None or d is None:
        raise _unavailable()
    if not d:
        return {"proposal": None}
    return _view(ctx, _current_rows(ctx, d.get("rows") or []), d.get("made_at"))


def _check_shepherd(ctx: Dict[str, Any], shepherd: str, u: Dict[str, Any]) -> None:
    if shepherd not in ctx["shepherds"]:
        raise HTTPException(400, "That person doesn't shepherd. Only your pastors and elders do.")
    if _own(ctx, shepherd, u):
        first = cf.first_name({"name": ctx["shepherds"][shepherd]["name"]})
        raise HTTPException(400, f"That's {first}'s own family. Give it to someone else.")


def move_in_draft(biz: Dict[str, Any], unit: str, shepherd: Optional[str], by_user: Optional[str]) -> Dict[str, Any]:
    b = str(biz["id"])
    unit = str(unit or "").strip().lower()
    if not _UNIT.match(unit):
        raise HTTPException(400, "That family isn't valid")
    ctx = load(b)
    d = _draft(b)
    if ctx is None or d is None:
        raise _unavailable()
    if not d:
        raise HTTPException(404, "There's no proposal right now. Ask Chief for one first.")
    rows = _current_rows(ctx, d.get("rows") or [])
    row = next((r for r in rows if r["unit"] == unit), None)
    if not row:
        raise HTTPException(404, "That family already has a shepherd, or isn't in this proposal.")
    u = next(x for x in ctx["units"] if x["unit"] == unit)
    s = _uid(shepherd, "shepherd") if shepherd else None
    if s:
        _check_shepherd(ctx, s, u)
    row.update({"shepherd_contact_id": s, "reason": "moved", "why": "You chose", "moved": True})
    _save_draft(b, rows, by_user, d.get("made_at"))
    return _view(ctx, rows, d.get("made_at"))


def discard(biz: Dict[str, Any]) -> None:
    if not sb_clients.sb_delete_as_service(f"/church_shepherd_drafts?business_id=eq.{_q(biz['id'])}"):
        raise HTTPException(503, "That didn't go through. Try again in a moment.")


def _make_home(b: str, ctx: Dict[str, Any], cid: str) -> Optional[str]:
    """A family of one, for a member in no family, when they are given a
    shepherd. None when they joined a family since (or a write failed)."""
    taken = cf.in_families(b)
    if taken is None or cid in taken or cid not in ctx["members"]:
        return None
    made = sb_clients.sb_post_as_service("/households", {"business_id": b,
                                                         "name": _plain(ctx["members"][cid].get("name"))[:120] or "A family"})
    if not isinstance(made, list) or not made:
        return None
    hid = str(made[0]["id"])
    linked = sb_clients.sb_post_as_service("/household_adults", {"household_id": hid, "contact_id": cid,
                                                                 "business_id": b, "relationship": "other"})
    if not isinstance(linked, list) or not linked:
        sb_clients.sb_delete_as_service(f"/households?id=eq.{_q(hid)}&business_id=eq.{_q(b)}")
        return None
    return hid


def _assign(b: str, hid: str, shepherd: str, by_user: Optional[str], reason: str) -> bool:
    saved = sb_clients.sb_post_as_service("/church_shepherds?on_conflict=household_id", {
        "household_id": hid, "business_id": b, "shepherd_contact_id": shepherd, "assigned_at": _iso(_now()),
        "assigned_by": by_user, "reason": _plain(reason)[:300]}, prefer="return=representation,resolution=merge-duplicates")
    return isinstance(saved, list) and bool(saved)


def approve(biz: Dict[str, Any], by_user: Optional[str]) -> Dict[str, Any]:
    """Write every family the proposal gives a shepherd. Returns placed,
    failed, and gained: shepherd → the family names they were given."""
    b = str(biz["id"])
    ctx = load(b)
    d = _draft(b)
    if ctx is None or d is None:
        raise _unavailable()
    if not d:
        raise HTTPException(400, "There's no proposal to approve. Ask Chief for one first.")
    by_unit = {u["unit"]: u for u in ctx["units"]}
    rows = _current_rows(ctx, d.get("rows") or [])
    gained: Dict[str, List[str]] = {}
    placed = failed = 0
    left: List[Dict[str, Any]] = []
    for r in rows:
        s = r.get("shepherd_contact_id")
        u = by_unit.get(r["unit"])
        if not s or not u or s not in ctx["shepherds"] or _own(ctx, s, u):
            continue
        hid = u["household_id"] or _make_home(b, ctx, u["contact_id"])
        if hid and _assign(b, hid, s, by_user, r.get("why") or ""):
            placed += 1
            gained.setdefault(s, []).append(u["name"])
        else:
            failed += 1
            left.append(r)
    if left:
        _save_draft(b, left, by_user, d.get("made_at"))
    else:
        sb_clients.sb_delete_as_service(f"/church_shepherd_drafts?business_id=eq.{_q(b)}")
    return {"placed": placed, "failed": failed, "gained": gained, "ctx": ctx}


def move(biz: Dict[str, Any], household_id: str, shepherd: Optional[str], by_user: Optional[str]) -> Dict[str, Any]:
    """After approval: one family to another shepherd, or back to waiting."""
    b = str(biz["id"])
    hid = _uid(household_id, "family")
    ctx = load(b)
    if ctx is None:
        raise _unavailable()
    u = next((x for x in ctx["units"] if x["household_id"] == hid), None)
    if not u:
        raise HTTPException(404, "That family isn't here.")
    before = (ctx["assigned"].get(hid) or {}).get("shepherd_contact_id")
    if not shepherd:
        if not sb_clients.sb_delete_as_service(f"/church_shepherds?household_id=eq.{_q(hid)}&business_id=eq.{_q(b)}"):
            raise HTTPException(503, "That didn't go through. Try again in a moment.")
        return {"changed": bool(before), "shepherd": None, "name": u["name"], "ctx": ctx}
    s = _uid(shepherd, "shepherd")
    _check_shepherd(ctx, s, u)
    if str(before or "") == s:
        return {"changed": False, "shepherd": ctx["shepherds"][s], "name": u["name"], "ctx": ctx}
    if not _assign(b, hid, s, by_user, "Moved by the office"):
        raise HTTPException(503, "That didn't save. Try again in a moment.")
    return {"changed": True, "shepherd": ctx["shepherds"][s], "name": u["name"], "ctx": ctx}


# ─── a family's record ────────────────────────────────────────────────

def _people(b: str, hid: str, ctx_members: Optional[Dict[str, Dict[str, Any]]] = None,
            today: Optional[date] = None) -> Optional[List[Dict[str, Any]]]:
    """The family, as a shepherd may see it: adults by name (and how to
    reach them), children by first name and age only."""
    adults = _rows(f"/household_adults?household_id=eq.{_q(hid)}&business_id=eq.{_q(b)}&select=contact_id&limit=40")
    kids = _rows(f"/children?household_id=eq.{_q(hid)}&business_id=eq.{_q(b)}"
                 "&select=first_name,birthdate,active&order=first_name.asc&limit=40")
    if adults is None or kids is None:
        return None
    ids = [str(a["contact_id"]) for a in adults]
    rows = (_rows(f"/contacts?business_id=eq.{_q(b)}&id=in.({','.join(_q(i) for i in ids)})"
                  "&select=id,name,status,phone,email") if ids else [])
    if rows is None:
        return None
    out = []
    for r in sorted(rows, key=lambda r: _plain(r.get("name")).casefold()):
        status = r.get("status")
        out.append({"contact_id": str(r["id"]), "name": _plain(r.get("name")) or "Someone", "kind": "adult",
                    "age": None, "tag": "Member" if status == "active" else "Visitor" if status == "lead" else "Guest",
                    "initials": initials(r.get("name") or ""), "phone": r.get("phone") or "", "email": r.get("email") or ""})
    for k in kids:
        if k.get("active") is False:
            continue
        a = cf.age(k.get("birthdate"), today)
        first = _plain(k.get("first_name")) or "Child"
        out.append({"contact_id": None, "name": first, "kind": "child", "age": a,
                    "tag": f"Child · {a}" if a is not None else "Child", "initials": first[:1].upper(),
                    "phone": "", "email": ""})
    return out


def _touches(b: str, hid: str) -> Optional[List[Dict[str, Any]]]:
    rows = _rows(f"/church_shepherd_touches?household_id=eq.{_q(hid)}&business_id=eq.{_q(b)}"
                 "&select=id,kind,note,needs_pastor,created_at,shepherd_contact_id&order=created_at.desc&limit=50")
    if rows is None:
        return None
    ids = sorted({str(r["shepherd_contact_id"]) for r in rows if r.get("shepherd_contact_id")})
    names: Dict[str, str] = {}
    if ids:
        ppl = _rows(f"/contacts?business_id=eq.{_q(b)}&id=in.({','.join(_q(i) for i in ids)})&select=id,name")
        if ppl is None:
            return None
        names = {str(p["id"]): _plain(p.get("name")) for p in ppl}
    return [{"at": r.get("created_at"), "kind": r.get("kind"), "note": r.get("note") or "",
             "needs_pastor": bool(r.get("needs_pastor")),
             "by_contact_id": str(r["shepherd_contact_id"]) if r.get("shepherd_contact_id") else None,
             "by": names.get(str(r.get("shepherd_contact_id") or ""), "") or "A former shepherd"} for r in rows]


def office_family(biz: Dict[str, Any], household_id: str) -> Dict[str, Any]:
    b = str(biz["id"])
    hid = _uid(household_id, "family")
    home = _rows(f"/households?id=eq.{_q(hid)}&business_id=eq.{_q(b)}&select=id,name&limit=1")
    who = _rows(f"/church_shepherds?household_id=eq.{_q(hid)}&business_id=eq.{_q(b)}&select=shepherd_contact_id&limit=1")
    if home is None or who is None:
        raise _unavailable("That family")
    if not home:
        raise HTTPException(404, "That family isn't here.")
    people = _people(b, hid)
    touches = _touches(b, hid)
    if people is None or touches is None:
        raise _unavailable("That family")
    shep = None
    if who:
        sid = str(who[0]["shepherd_contact_id"])
        row = _rows(f"/contacts?id=eq.{_q(sid)}&business_id=eq.{_q(b)}&select=id,name&limit=1") or []
        shep = {"contact_id": sid, "name": _plain(row[0].get("name")) if row else "Someone"}
    return {"household_id": hid, "name": _plain(home[0].get("name")) or "A family", "shepherd": shep,
            "people": [{"name": p["name"], "kind": p["kind"], "age": p["age"]} for p in people],
            "touches": [{k: t[k] for k in ("at", "kind", "note", "needs_pastor", "by")} for t in touches]}


# ─── the shepherd's side (member_portal_lead) ─────────────────────────

def _member_ctx(b: str) -> Optional[Dict[str, Any]]:
    import church_follow_up as cfu
    import church_roles as cr
    all_defs = cr.defs(b)
    holder_rows = cfu.roles(b)
    st = settings(b)
    if all_defs is None or holder_rows is None or st is None:
        return None
    holders = cr.active_holders(holder_rows)
    return {"defs": all_defs, "holders": holders, "settings": st,
            "shepherds": shepherds_from(role_rows(all_defs, st), holders, st)}


def _lead_names(mctx: Dict[str, Any], skip: str = "") -> List[Dict[str, Any]]:
    out = []
    for d in mctx["defs"]:
        if d.get("job") == "senior":
            out += [h for h in mctx["holders"].get(d["key"], []) if str(h["contact_id"]) != skip]
    return out


def _chain(mctx: Dict[str, Any], me_id: str) -> List[str]:
    import church_roles as cr
    s = mctx["shepherds"].get(me_id)
    if not s:
        return []
    names: List[str] = []
    for _role, people in cr.chain_above(s["role_def"], mctx["defs"], mctx["holders"], skip=[me_id]):
        for p in people:
            n = _plain(p.get("name"))
            if n and n not in names:
                names.append(n)
    return names


def my_families(biz_id: str, me_id: str, *, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The families this member shepherds, the ones who need them first
    first. {'shepherd': False} for a member who doesn't shepherd. None when
    a read failed."""
    b, me_id = str(biz_id), str(me_id)
    now = now or _now()
    mctx = _member_ctx(b)
    if mctx is None:
        return None
    if me_id not in mctx["shepherds"]:
        return {"shepherd": False, "families": []}
    rows = _rows(f"/church_shepherds?business_id=eq.{_q(b)}&shepherd_contact_id=eq.{_q(me_id)}"
                 "&select=household_id,assigned_at&limit=500")
    if rows is None:
        return None
    ids = [str(r["household_id"]) for r in rows]
    families: List[Dict[str, Any]] = []
    if ids:
        inn = ",".join(_q(i) for i in ids)
        homes = _rows(f"/households?business_id=eq.{_q(b)}&id=in.({inn})&select=id,name&limit=500")
        adults = _rows(f"/household_adults?business_id=eq.{_q(b)}&household_id=in.({inn})&select=household_id&limit=5000")
        kids = _rows(f"/children?business_id=eq.{_q(b)}&household_id=in.({inn})&select=household_id,active&limit=5000")
        touches = _rows(f"/church_shepherd_touches?business_id=eq.{_q(b)}&household_id=in.({inn})"
                        "&select=household_id,kind,created_at&order=created_at.desc&limit=5000")
        if any(x is None for x in (homes, adults, kids, touches)):
            return None
        size: Dict[str, int] = {}
        for a in adults:
            size[str(a["household_id"])] = size.get(str(a["household_id"]), 0) + 1
        for k in kids:
            if k.get("active") is not False:
                size[str(k["household_id"])] = size.get(str(k["household_id"]), 0) + 1
        last: Dict[str, Dict[str, Any]] = {}
        for t in touches:
            last.setdefault(str(t["household_id"]), t)
        since = {str(r["household_id"]): r.get("assigned_at") for r in rows}
        for h in homes:
            hid = str(h["id"])
            t = last.get(hid) or {}
            at = _parse(t.get("created_at"))
            families.append({"household_id": hid, "name": _plain(h.get("name")) or "A family", "size": size.get(hid, 0),
                             "since": since.get(hid), "last_touch_at": t.get("created_at"),
                             "last_touch_kind": t.get("kind"),
                             "days": (now - at).days if at else None,
                             "reached": bool(at and now - at <= timedelta(days=mctx["settings"]["rhythm_days"]))})
    # Never reached first, then the longest since; the reached after.
    families.sort(key=lambda f: (f["reached"], f["days"] is not None, -(f["days"] or 0), f["name"].casefold()))
    return {"shepherd": True, "families": families, "rhythm_days": mctx["settings"]["rhythm_days"],
            "chain": _chain(mctx, me_id),
            "lead": [_plain(h.get("name")) for h in _lead_names(mctx, me_id)]}


def family_for(biz_id: str, me_id: str, household_id: str, *, today: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """One family, for its current shepherd only. Raises 404 for anyone else."""
    b, me_id = str(biz_id), str(me_id)
    hid = _uid(household_id, "family")
    mctx = _member_ctx(b)
    who = _rows(f"/church_shepherds?household_id=eq.{_q(hid)}&business_id=eq.{_q(b)}"
                "&select=shepherd_contact_id,assigned_at&limit=1")
    if mctx is None or who is None:
        return None
    if not who or str(who[0]["shepherd_contact_id"]) != me_id or me_id not in mctx["shepherds"]:
        raise HTTPException(404, "That family isn't yours to shepherd.")
    home = _rows(f"/households?id=eq.{_q(hid)}&business_id=eq.{_q(b)}&select=id,name&limit=1")
    people = _people(b, hid, today=today)
    touches = _touches(b, hid)
    if home is None or people is None or touches is None:
        return None
    if not home:
        raise HTTPException(404, "That family isn't yours to shepherd.")
    return {"household_id": hid, "name": _plain(home[0].get("name")) or "A family", "since": who[0].get("assigned_at"),
            "people": people, "touches": touches, "chain": _chain(mctx, me_id),
            "lead": [_plain(h.get("name")) for h in _lead_names(mctx, me_id)],
            "lead_people": _lead_names(mctx, me_id)}


def log_touch(biz_id: str, me: Dict[str, Any], household_id: str, kind: str, note: str,
              needs_pastor: bool) -> Dict[str, Any]:
    """A call, a visit, a text or a talk at church, by the family's shepherd."""
    b = str(biz_id)
    fam = family_for(b, str(me["id"]), household_id)
    if fam is None:
        raise HTTPException(503, "That didn't save. Try again in a moment.")
    if kind not in KINDS:
        raise HTTPException(400, "Say how you reached them.")
    text = str(note or "").strip()[:MAX_NOTE]
    now = _iso(_now())
    saved = sb_clients.sb_post_as_service("/church_shepherd_touches", {
        "business_id": b, "household_id": fam["household_id"], "shepherd_contact_id": str(me["id"]), "kind": kind,
        "note": text, "needs_pastor": bool(needs_pastor), "created_at": now})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Try again in a moment.")
    adults = [p["contact_id"] for p in fam["people"] if p["kind"] == "adult" and p["contact_id"]]
    if adults:
        try:
            sb_clients.sb_patch_as_service(
                f"/contacts?business_id=eq.{_q(b)}&id=in.({','.join(_q(a) for a in adults)})", {"last_interaction": now})
        except Exception:
            logger.info("shepherding: last_interaction stamp skipped", exc_info=True)
    return {"family": fam, "kind": kind, "note": text, "needs_pastor": bool(needs_pastor)}


# ─── the emails ───────────────────────────────────────────────────────

def _asker(ctx: Dict[str, Any], biz: Dict[str, Any]) -> str:
    for d in ctx["defs"]:
        if d.get("job") == "senior":
            for h in ctx["holders"].get(d["key"], []):
                n = _plain(h.get("name"))
                if n:
                    return n
    return _plain(biz.get("name")) or "Your church"


def _the(name: str) -> str:
    return "the " + name[4:] if name.startswith("The ") else name


async def tell_shepherds(biz: Dict[str, Any], gained: Dict[str, List[str]], ctx: Dict[str, Any], stamp: str) -> int:
    """One email to each shepherd who was given families."""
    import church_follow_up as cfu
    asker = _asker(ctx, biz)
    church = _plain(biz.get("name")) or "your church"
    origin = cfu.site_origin(str(biz["id"]))
    told = 0
    for sid, names in gained.items():
        s = ctx["shepherds"].get(sid)
        if not s or not s.get("email") or not names:
            continue
        n = len(names)
        subject = (f"{asker} asked you to shepherd {_the(names[0])}" if n == 1
                   else f"{asker} asked you to shepherd {n} families")
        listed = "".join(f"<br>{html.escape(x)}" for x in names[:2])
        more = f"<br>and {n - 2} more" if n > 2 else ""
        lines = [f"{html.escape(cfu.first_name(s['name']))}, {html.escape(asker)} asked you to shepherd "
                 f"{'this family' if n == 1 else 'these families'} at {html.escape(church)}:{listed}{more}",
                 "Reach each one once a month: a call, a visit, a text or a real talk at church.",
                 "Their giving and their private prayer requests are never shown to you."]
        body = cfu._mail_html(lines, f"{origin}/my/lead/families" if origin else "", "Open your families")
        if await cfu._email(biz, s["email"], s["name"], subject, body, f"shep-{biz['id']}-{sid}-{stamp}"):
            told += 1
    return told


async def tell_new_shepherd(biz: Dict[str, Any], shepherd: Dict[str, Any], family: str, ctx: Dict[str, Any]) -> bool:
    import church_follow_up as cfu
    if not shepherd.get("email"):
        return False
    asker = _asker(ctx, biz)
    origin = cfu.site_origin(str(biz["id"]))
    lines = [f"{html.escape(cfu.first_name(shepherd['name']))}, {html.escape(asker)} asked you to shepherd "
             f"{html.escape(_the(family))} at {html.escape(_plain(biz.get('name')) or 'your church')}.",
             "Reach them once a month: a call, a visit, a text or a real talk at church.",
             "Their giving and their private prayer requests are never shown to you."]
    body = cfu._mail_html(lines, f"{origin}/my/lead/families" if origin else "", "Open your families")
    return await cfu._email(biz, shepherd["email"], shepherd["name"], f"{asker} asked you to shepherd {_the(family)}",
                            body, f"shep-move-{biz['id']}-{shepherd['contact_id']}-{family}-{_iso(_now())[:16]}")


async def tell_pastor(biz: Dict[str, Any], me: Dict[str, Any], logged: Dict[str, Any]) -> int:
    """'Needs a pastor': the Lead Pastor, at once. Never another member."""
    import church_follow_up as cfu
    fam = logged["family"]
    who = _plain(me.get("name")) or "A shepherd"
    told = 0
    for h in fam.get("lead_people") or []:
        if not h.get("email"):
            continue
        lines = [f"{html.escape(who)} asked for a pastor for {html.escape(_the(fam['name']))}."]
        if logged.get("note"):
            lines.append("Their note: " + html.escape(logged["note"]).replace("\n", "<br>"))
        lines.append("It went to the Lead Pastor only. No other member was told.")
        if await cfu._email(biz, h["email"], _plain(h.get("name")), f"{who} asked for a pastor for {_the(fam['name'])}",
                            cfu._mail_html(lines, "", ""),
                            f"shep-pastor-{biz['id']}-{fam['household_id']}-{_iso(_now())[:19]}"):
            told += 1
    return told
