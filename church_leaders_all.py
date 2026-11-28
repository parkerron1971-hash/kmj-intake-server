"""church_leaders_all.py — everyone who leads, in one place (mission M-8).

Kevin, 2026-11-28 (GO on kai/reviews/leaders-roles-group-leaders.md): one
place to see every leader and who they answer to. Leaders & roles reads it.

    GET /church/leaders/everyone?business_id=   a manager seat and up, as
        Leaders & roles itself (church_router.leaders)

One row a person a thing they lead, from the church's own records, never a
second copy of them:

    role     a role holder (church_leader_roles), active or asked; answers to
             the person on their holder row, else whoever holds the role the
             role answers to
    group    a group's lead or co-leader (group_members.role = 'leader'), by
             the group's kind: small group, team, class, ministry. Answers to
             the group's one person (groups.answers_to_contact_id), else its
             department's leader, else the leaders map
    worship  someone with the Worship part on the Sunday team (worship_team),
             as the Sunday hub counts them a team leader of the worship team
             (Kevin's answer 6); once, beside the team's own leader row. The
             worship team is the hub's own (WORSHIP_WORDS); a church with
             none lists nobody here (the hub makes them its Planner)
    teacher  a Course Studio class's teacher (academy_teachers, by email).
             A teacher who also leads the class group pointing at that class
             (groups.course_id) shows once, on the group's row, with both
             (Kevin's answer 7)
    kids     a Kids check-in leader (space_leaders), as before

Also `teams`: each serving team (groups of kind 'team') with its leaders,
whether it is on Sundays and its Serve card choice, for the Team leader
chips; and the gaps (groups and teams with no leader; leaders who answer
only to a role). A read that fails is a 503, never a short list. Columns
from APPLY-2026-11-28-group-leads.sql are read only once church_map says
they answer.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query

import sb_clients
from business_access import business_access

router = APIRouter(tags=["church"])

UNREAD = "Your leaders couldn't be loaded. Try again in a moment."
KIND_WORD = {"small_group": "Small group", "team": "Serve team", "class": "Class", "ministry": "Ministry"}
# The Sunday hub's own rule for the church's worship team (M-7, sunday_hub.
# WORSHIP_WORDS and _named), copied exactly so both say the same team (M-8
# review S2). Once M-7 is on main, call sunday_hub.worship_team(
# sunday_hub.sunday_teams(biz)) here instead.
WORSHIP_WORDS = ("worship", "praise", "band", "choir", "music", "singers", "vocal")


def _worship_team(groups: List[Dict[str, Any]], sunday: Set[str], owners: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The first ChurchSavvy-owned Sunday team, by name, whose name says one
    of WORSHIP_WORDS; None when the church has none."""
    for g in sorted((g for g in groups if str(g["id"]) in sunday), key=lambda g: str(g.get("name") or "")):
        low = str(g.get("name") or "").lower()
        if owners.get(str(g["id"])) == "churchsavvy" and any(w in low for w in WORSHIP_WORDS):
            return g
    return None
PAGE = 1000


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return " ".join(str(v or "").split())


def _need(path: str) -> List[Dict[str, Any]]:
    """Every row, a page at a time (PostgREST stops at 1,000)."""
    out: List[Dict[str, Any]] = []
    while True:
        sep = "&" if "?" in path else "?"
        more = f"&offset={len(out)}" if out else ""
        rows = sb_clients.sb_get_as_service(f"{path}{sep}limit={PAGE}{more}")
        if not isinstance(rows, list):
            raise HTTPException(503, UNREAD)
        out += rows
        if len(rows) < PAGE:
            return out


def _maybe(path: str, fallback: str) -> List[Dict[str, Any]]:
    """A read naming a column a church may not have yet: the fallback read
    when the first is refused (PostgREST's missing column), else a 503."""
    rows = sb_clients.sb_get_as_service(path)
    if isinstance(rows, list):
        return rows
    rows = sb_clients.sb_get_as_service(fallback)
    if isinstance(rows, list):
        return rows
    raise HTTPException(503, UNREAD)


def _contacts(biz: str, ids: Iterable[str]) -> Dict[str, Dict[str, str]]:
    ids = sorted({str(i) for i in ids if i})
    out: Dict[str, Dict[str, str]] = {}
    for i in range(0, len(ids), 50):
        for r in _need(f"/contacts?business_id=eq.{_q(biz)}&id=in.({','.join(_q(x) for x in ids[i:i + 50])})"
                       "&select=id,name,email&order=id.asc"):
            out[str(r["id"])] = {"name": _plain(r.get("name")) or "Someone", "email": str(r.get("email") or "").strip().lower()}
    return out


def _by_email(biz: str, emails: Iterable[str]) -> Dict[str, str]:
    """email (lower) -> the one person with it; an address two people share
    names nobody (never a guess)."""
    want = {e.strip().lower() for e in emails if e and "@" in e}
    if not want:
        return {}
    seen: Dict[str, List[str]] = {}
    # The church's addresses, a page at a time: a few hundred people, and an
    # address's case never matters.
    for r in _need(f"/contacts?business_id=eq.{_q(biz)}&email=not.is.null&select=id,email&order=id.asc"):
        e = str(r.get("email") or "").strip().lower()
        if e in want:
            seen.setdefault(e, []).append(str(r["id"]))
    return {e: ids[0] for e, ids in seen.items() if len(ids) == 1}


def _group_cols(biz: str) -> bool:
    """Whether APPLY-2026-11-28-group-leads.sql is in: its columns answer,
    asked of this church's own rows."""
    q = _q(biz)
    groups = sb_clients.sb_get_as_service(
        f"/groups?business_id=eq.{q}&select=answers_to_contact_id,course_id,serve_option&limit=1")
    members = sb_clients.sb_get_as_service(f"/group_members?business_id=eq.{q}&select=co_leader&limit=1")
    return isinstance(groups, list) and isinstance(members, list)


def everyone(business: Dict[str, Any]) -> Dict[str, Any]:
    import church_follow_up as cfu
    import church_map
    import church_roles as cr
    biz = str(business["id"])
    defs = cr.defs(biz)
    holders = cfu.roles(biz)
    if defs is None or holders is None:
        raise HTTPException(503, UNREAD)
    by_key = {d["key"]: d for d in defs}
    by_id = {str(d["id"]): d for d in defs}
    cols = _group_cols(biz)
    links: Dict[str, str] = {}
    if church_map.ready():
        links = {str(x["id"]): str(x["answers_to_contact_id"]) for x in _need(
            f"/church_leader_roles?business_id=eq.{_q(biz)}&answers_to_contact_id=not.is.null&select=id,answers_to_contact_id&order=id.asc")}
    m = church_map.opened(biz)
    m = m if m else None
    groups = _need(f"/groups?business_id=eq.{_q(biz)}&active=eq.true&select=id,name,kind"
                   f"{',answers_to_contact_id,course_id,serve_option' if cols else ''}&order=name.asc")
    leads = _need(f"/group_members?business_id=eq.{_q(biz)}&role=eq.leader&select=group_id,contact_id"
                  f"{',co_leader' if cols else ''}"
                  f"&order=group_id.asc,{'co_leader.asc,' if cols else ''}created_at.asc,contact_id.asc")
    sunday = {str(r["group_id"]) for r in _need(f"/serve_teams?business_id=eq.{_q(biz)}&select=group_id&order=group_id.asc")}
    owners = {str(r["group_id"]): r.get("owner") for r in _maybe(
        f"/serve_teams?business_id=eq.{_q(biz)}&select=group_id,owner&limit=200",
        f"/serve_teams?business_id=eq.{_q(biz)}&select=group_id&limit=200")}
    kids = _need(f"/space_leaders?business_id=eq.{_q(biz)}&select=contact_id,space&order=contact_id.asc")
    worship = [w for w in _need(f"/worship_team?business_id=eq.{_q(biz)}&status=eq.active&select=name,email,roles&order=name.asc")
               if "worship" in (w.get("roles") or [])]
    courses = {str(c["id"]): _plain(c.get("title")) or "Class" for c in _need(
        f"/academy_courses?business_id=eq.{_q(biz)}&status=neq.archived&select=id,title&order=title.asc")}
    teachers = _need(f"/academy_teachers?course_id=in.({','.join(_q(c) for c in courses)})&select=course_id,email,role"
                     "&order=course_id.asc") if courses else []
    teach_people = _by_email(biz, [t.get("email") or "" for t in teachers] + [w.get("email") or "" for w in worship])
    gname = {str(g["id"]): _plain(g.get("name")) or "A group" for g in groups}
    people = _contacts(biz, [h["contact_id"] for h in holders] + [r["contact_id"] for r in leads] + list(links.values())
                       + [g.get("answers_to_contact_id") for g in groups] + [k["contact_id"] for k in kids]
                       + list(teach_people.values()))

    def who(cid: Optional[str]) -> Optional[Dict[str, str]]:
        cid = str(cid or "")
        return {"contact_id": cid, "name": people.get(cid, {}).get("name") or "Someone"} if cid else None

    def role_fallback(d: Optional[Dict[str, Any]]) -> str:
        up = by_id.get(str((d or {}).get("reports_to") or ""))
        return f"{up['title']} (whoever holds it)" if up else "the top of the chain"

    rows: List[Dict[str, Any]] = []
    for h in holders:
        d = by_key.get(h["role"])
        if not d or d.get("job") in ("office",):
            continue
        to = links.get(h["id"])
        scope = _plain(h.get("scope"))
        rows.append({"kind": "role", "who": who(h["contact_id"]), "status": h.get("status") or "active",
                     "leads": f"{scope} · {d['title']}" if scope else d["title"], "thing": {"id": str(d["id"]), "name": d["title"]},
                     "holder_id": h["id"], "answers_to": who(to), "fallback": None if to else role_fallback(d)})

    # Groups: the lead first, then co-leaders, each a row; a class group with
    # its Course Studio class carries the class (and takes its teacher's row).
    by_group: Dict[str, List[Dict[str, Any]]] = {}
    for r in leads:
        if str(r["group_id"]) in gname:
            by_group.setdefault(str(r["group_id"]), []).append(r)
    taught: Set[tuple] = set()
    gaps: List[Dict[str, str]] = []
    for g in groups:
        gid = str(g["id"])
        mine = by_group.get(gid, [])
        lead = next((str(r["contact_id"]) for r in mine if not (cols and r.get("co_leader"))), None)
        to = (str(g.get("answers_to_contact_id") or "") or None) if cols else None
        dept = m.department_of("group", gid) if m else None
        fallback = None if to else (f"the {dept['name']} department’s leader" if dept else "the leaders map")
        course = courses.get(str(g.get("course_id") or "")) if cols and g.get("course_id") else None
        if not mine:
            gaps.append({"kind": "no_leader", "group_id": gid, "text": f"{gname[gid]} has no leader yet."})
        for r in mine:
            cid = str(r["contact_id"])
            co = bool(cols and r.get("co_leader")) or (lead is not None and cid != lead)
            if course:
                taught.add((str(g["course_id"]), cid))
            rows.append({"kind": "group", "group_kind": g.get("kind") or "small_group", "who": who(cid), "status": "active",
                         "co_leader": co, "leads": gname[gid], "thing": {"id": gid, "name": gname[gid], "kind": g.get("kind")},
                         "teaches": {"id": str(g["course_id"]), "title": course} if course else None,
                         "answers_to": who(to), "fallback": fallback})

    # The Worship part: a team leader of the church's worship team (the
    # Sunday hub's rule), once, unless they already lead that group. With no
    # worship team the hub makes them its Planner, not a team leader, so they
    # aren't listed here.
    wteam = _worship_team(groups, sunday, owners)
    for w in (worship if wteam else []):
        cid = teach_people.get(str(w.get("email") or "").strip().lower())
        if wteam and cid and any(str(r["contact_id"]) == cid for r in by_group.get(str(wteam["id"]), [])):
            continue
        rows.append({"kind": "worship", "who": who(cid) if cid else {"contact_id": "", "name": _plain(w.get("name")) or "Someone"},
                     "status": "active", "leads": gname[str(wteam["id"])],
                     "thing": {"id": str(wteam["id"]), "name": gname[str(wteam["id"])], "kind": "team"},
                     "part": "Worship", "answers_to": None, "fallback": "the planner and the pastor"})

    # Course Studio teachers, once each; one who leads the class group already has it.
    for t in teachers:
        cid = teach_people.get(str(t.get("email") or "").strip().lower())
        cour = str(t["course_id"])
        if cid and (cour, cid) in taught:
            continue
        taught.add((cour, cid or str(t.get("email"))))
        rows.append({"kind": "teacher", "who": who(cid) if cid else {"contact_id": "", "name": str(t.get("email") or "A teacher")},
                     "status": "active", "leads": courses.get(cour, "A class"), "teaches": {"id": cour, "title": courses.get(cour, "")},
                     "thing": {"id": cour, "name": courses.get(cour, "")}, "answers_to": None,
                     "fallback": role_fallback(by_key.get("class_teachers"))})

    for k in kids:
        rows.append({"kind": "kids", "who": who(k["contact_id"]), "status": "active",
                     "leads": "Kids check-in" if (k.get("space") or "kids") == "kids" else "Youth check-in",
                     "thing": {"id": "", "name": "Kids check-in"}, "answers_to": None, "fallback": "Children’s Director (whoever holds it)"})

    teams = []
    for g in groups:
        if g.get("kind") != "team":
            continue
        gid = str(g["id"])
        teams.append({"group_id": gid, "name": gname[gid], "sunday": gid in sunday,
                      "serve_option": g.get("serve_option") if cols else None,
                      "leaders": [{**who(str(r["contact_id"])), "co_leader": bool(cols and r.get("co_leader"))}
                                  for r in by_group.get(gid, [])]})
    role_only = sum(1 for r in rows if r["kind"] in ("role", "group") and r["status"] == "active" and not r["answers_to"])
    return {"rows": rows, "teams": teams, "gaps": gaps,
            "counts": {"leaders": len({(r["who"] or {}).get("contact_id") or r["who"]["name"] for r in rows if r["status"] == "active"}),
                       "groups": len(groups), "no_leader": len(gaps), "role_only": role_only},
            "group_leads_ready": bool(cols)}


@router.get("/leaders/everyone")
def everyone_read(business_id: str = Query(...), biz: Dict[str, Any] = Depends(business_access("manager"))):
    return everyone(biz)
