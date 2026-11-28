"""church_group_leads.py — every group has a leader (mission M-8).

Kevin, 2026-11-28 (GO on kai/reviews/leaders-roles-group-leaders.md):
whenever a group or team is made (small groups, classes, ministries, Serve
teams), it can be given a leader, and that leader shows up under Leaders &
roles, in the right place on the map, answering to a specific person.

One record of who leads a group: the group's own leader row
(group_members.role = 'leader'), the one the member app, the Lead tab and
the Sunday hub (M-7's team_leader) already read. This module adds who is the
lead and who is a co-leader (group_members.co_leader), the one person the
group answers to (groups.answers_to_contact_id), a class group's Course
Studio class (groups.course_id) and a team's Serve-card choice
(groups.serve_option): supabase/APPLY-2026-11-28-group-leads.sql.

    GET /church/groups/leads/choices?business_id=
        before a group exists (the New group form): who a group can answer
        to, the church's Course Studio classes, the Serve card's choices,
        and whether this login names leaders. Any seat that sees groups.
    GET /church/groups/{group_id}/leads?business_id=
        the group's lead, co-leaders, who it answers to, its class and
        Serve choice, the people it can answer to, and what this login may
        change (`can`). Any seat that sees groups.
    PUT /church/groups/{group_id}/leads   {business_id, leader_contact_id?,
        co_leader_contact_ids?, answers_to_contact_id?, course_id?,
        serve_option?}: only the fields sent change.

Who may (Kevin's answer 2): the pastor (the owner), the admins, and office
logins who look after groups (church_duties "groups") name a leader, the
co-leaders and who the group answers to. A group's lead, from their own
login or the Lead tab (member_portal_lead), changes only their co-leaders;
they never change who the group answers to. Naming someone puts them straight
in (answer 1) and sends them a note: "You now lead Parking Team." One person
a group (answer 3): co-leaders answer to whoever the group answers to.

Someone the group answers to must hold an active role here, as the map's
answers-to already asks (church_map.set_answers_to), and can't lead it.
A new lead takes the lead row; whoever led before stays on as a co-leader
unless the same save lists the co-leaders. Leaving the co-leaders makes
someone a member of the group again, never removes them from it.

Behind GROUP_LEADS = off | owner | on (default owner: the platform owner's
church). Closed, both routes are a 404. Before the file is applied (ready()),
reads say ready: false and writes are a 503.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["church-groups"])

CO_LEADERS_MAX = 4
SERVE_OPTION_MAX = 120
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_RANK = {"viewer": 1, "member": 2, "manager": 3, "admin": 4, "owner": 5}
KIND_WORD = {"small_group": "group", "team": "team", "class": "class", "ministry": "ministry"}
UNREAD = "Group leaders didn't load. Nothing was changed. Try again."
UNSAVED = "That didn't all save. Open the group again to see what did, then try again."
NOT_YET = "Group leaders are being switched on. Try again shortly."


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return " ".join(str(v or "").split())


def _id(v: Any, what: str) -> str:
    s = str(v or "").strip()
    if not _UUID.match(s):
        raise HTTPException(400, f"That {what} isn't valid")
    return s.lower()


# ─── The switch, and whether the file is in ──────────────────────────

def mode() -> str:
    m = (os.environ.get("GROUP_LEADS") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def church_open(biz: Any) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        import member_asks
        return member_asks.platform_church(biz.get("id") if isinstance(biz, dict) else biz)
    return False


_READY: Dict[str, Any] = {}
READY_SECONDS = 300


def ready(biz: str = "") -> bool:
    """The file's columns answer, asked of this church's own rows as every
    read here is. A yes is kept; a no is asked again after five minutes
    (Kevin may apply it any time)."""
    if _READY.get("yes"):
        return True
    at = _READY.get("no_at")
    if at and time.monotonic() - at < READY_SECONDS:
        return False
    scope = f"business_id=eq.{_q(biz)}&" if biz else ""
    ok = isinstance(sb_clients.sb_get_as_service(f"/group_members?{scope}select=co_leader&limit=1"), list) and \
        isinstance(sb_clients.sb_get_as_service(f"/groups?{scope}select=answers_to_contact_id,course_id,serve_option&limit=1"), list)
    if ok:
        _READY["yes"] = True
    else:
        _READY["no_at"] = time.monotonic()
    return ok


# ─── Reads ───────────────────────────────────────────────────────────

def _need(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, UNREAD)
    return rows


def group(biz: str, gid: str, *, cols: bool = True) -> Dict[str, Any]:
    more = ",answers_to_contact_id,course_id,serve_option" if cols else ""
    rows = _need(f"/groups?id=eq.{_q(gid)}&business_id=eq.{_q(biz)}&active=eq.true"
                 f"&select=id,name,kind,youth{more}&limit=1")
    if not rows:
        raise HTTPException(404, "That group isn't running any more.")
    return rows[0]


LEADER_ORDER = "co_leader.asc,created_at.asc,contact_id.asc"


def leader_rows(biz: str, gid: str, *, cols: bool = True) -> List[Dict[str, Any]]:
    """The group's leader rows in one fixed order (M-8 review M1): the lead
    first, then by when each started leading, then by id, so "the lead" of a
    group with several plain leader rows (led before co-leaders existed, or
    made leader on Groups) is the same row on every read."""
    more = ",co_leader" if cols else ""
    order = LEADER_ORDER if cols else "created_at.asc,contact_id.asc"
    return [{"contact_id": str(r["contact_id"]), "co_leader": bool(r.get("co_leader"))}
            for r in _need(f"/group_members?business_id=eq.{_q(biz)}&group_id=eq.{_q(gid)}&role=eq.leader"
                           f"&select=contact_id{more}&order={order}&limit=50")]


def lead_of(rows: List[Dict[str, Any]]) -> Optional[str]:
    """The group's lead: its leader row that isn't a co-leader. A group led
    before co-leaders existed has several plain leader rows; the first is
    its lead until someone names one."""
    return next((r["contact_id"] for r in rows if not r["co_leader"]), None)


def _people(biz: str, ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    ids = sorted({str(i) for i in ids if i})
    out: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(ids), 50):
        for r in _need(f"/contacts?business_id=eq.{_q(biz)}&id=in.({','.join(_q(x) for x in ids[i:i + 50])})"
                       "&select=id,name,email&limit=50"):
            out[str(r["id"])] = {"name": _plain(r.get("name")) or "Someone", "email": str(r.get("email") or "")}
    return out


def answer_choices(biz: str) -> List[Dict[str, Any]]:
    """Everyone the group can answer to: each person holding an active role,
    with their roles' titles, in the library's order."""
    import church_follow_up as cfu
    import church_roles as cr
    holders = cfu.roles(biz)
    defs = cr.defs(biz)
    if holders is None or defs is None:
        raise HTTPException(503, UNREAD)
    rank = {d["key"]: n for n, d in enumerate(defs)}
    out: Dict[str, Dict[str, Any]] = {}
    for h in sorted((h for h in holders if h.get("status") == "active"), key=lambda h: rank.get(h["role"], 999)):
        p = out.setdefault(h["contact_id"], {"contact_id": h["contact_id"], "name": h["name"], "roles": [], "_r": 999})
        t = cr.title_of(h["role"], defs)
        if t and t not in p["roles"]:
            p["roles"].append(t)
        p["_r"] = min(p["_r"], rank.get(h["role"], 999))
    return [{k: v for k, v in p.items() if k != "_r"} for p in sorted(out.values(), key=lambda p: (p["_r"], p["name"].lower()))]


def view(biz: str, gid: str) -> Dict[str, Any]:
    """What GET answers (and PUT answers with): the group's leaders and who
    it answers to, by name."""
    if not ready(biz):
        g = group(biz, gid, cols=False)
        rows = leader_rows(biz, gid, cols=False)
        names = _people(biz, [r["contact_id"] for r in rows])
        return {"ready": False, "group": {"id": str(g["id"]), "name": g.get("name") or "", "kind": g.get("kind")},
                "leader": None, "co_leaders": [], "leaders": [{"contact_id": r["contact_id"], **names.get(r["contact_id"], {})}
                                                              for r in rows],
                "answers_to": None, "course": None, "serve_option": None}
    g = group(biz, gid)
    rows = leader_rows(biz, gid)
    lead = lead_of(rows)
    ids = [r["contact_id"] for r in rows] + [g.get("answers_to_contact_id")]
    names = _people(biz, ids)

    def who(cid: Optional[str]) -> Optional[Dict[str, Any]]:
        return {"contact_id": cid, "name": names.get(cid, {}).get("name") or "Someone"} if cid else None

    course = None
    if g.get("course_id"):
        c = _need(f"/academy_courses?id=eq.{_q(g['course_id'])}&business_id=eq.{_q(biz)}&select=id,title&limit=1")
        course = {"id": str(g["course_id"]), "title": _plain(c[0].get("title")) if c else ""}
    return {"ready": True,
            "group": {"id": str(g["id"]), "name": g.get("name") or "", "kind": g.get("kind")},
            "leader": who(lead),
            "co_leaders": [who(r["contact_id"]) for r in rows if r["contact_id"] != lead],
            "answers_to": who(str(g["answers_to_contact_id"]) if g.get("answers_to_contact_id") else None),
            "course": course,
            "serve_option": g.get("serve_option")}


# ─── Who may ─────────────────────────────────────────────────────────

def _seat(biz: str, user: AuthedUser) -> Tuple[str, Optional[str]]:
    """(seat, the login's own person or None)."""
    import kids_router
    role = kids_router.role_for(biz, user) or ""
    person = None
    if role and role != "owner":
        rows = _need(f"/business_users?business_id=eq.{_q(biz)}&user_id=eq.{_q(user.id)}&status=eq.active"
                     "&select=contact_id&limit=1")
        person = str(rows[0]["contact_id"]) if rows and rows[0].get("contact_id") else None
    return role, person


def office_names(biz: str, user: AuthedUser, role: str) -> bool:
    """Whether this login names leaders: the owner, an admin, or an office
    login that looks after groups (church_duties 'groups')."""
    if role in ("owner", "admin"):
        return True
    if role in ("manager", "member"):
        import church_duties as cd
        return cd.holds(biz, user, "groups")
    return False


def level(biz: str, user: AuthedUser, rows: List[Dict[str, Any]]) -> Tuple[str, Optional[str]]:
    """('office' | 'lead' | '', the seat). 'lead': the login's own person is
    the group's lead (co-leaders only, never who it answers to)."""
    role, person = _seat(biz, user)
    if office_names(biz, user, role):
        return "office", role
    if person and person == lead_of(rows):
        return "lead", role
    return "", role


# ─── Writes ──────────────────────────────────────────────────────────

FIELDS = ("leader_contact_id", "co_leader_contact_ids", "answers_to_contact_id", "course_id", "serve_option")


def _ours(biz: str, ids: Iterable[str]) -> Set[str]:
    want = {i for i in ids if i}
    if not want:
        return set()
    got = set(_people(biz, want))
    if want - got:
        raise HTTPException(400, "Someone picked isn't one of this church's people.")
    return got


def save(biz: str, gid: str, body: Dict[str, Any], how: str) -> Dict[str, Any]:
    """Change a group's leaders. `how` is 'office' (everything) or 'lead'
    (co-leaders only). Returns {'view', 'new': [(contact_id, co)], 'group'}:
    who now leads it who didn't before, for the note."""
    if not ready(biz):
        raise HTTPException(503, NOT_YET)
    sent = {k for k in FIELDS if k in body}
    if not sent:
        raise HTTPException(400, "Nothing to change")
    if how == "lead" and sent - {"co_leader_contact_ids"}:
        raise HTTPException(403, "A group's leader adds their co-leaders. The office names the leader and who the group answers to.")
    g = group(biz, gid)
    kind = g.get("kind") or "small_group"
    rows = leader_rows(biz, gid)
    before = {r["contact_id"]: r["co_leader"] for r in rows}
    lead = lead_of(rows)

    if "leader_contact_id" in sent:
        new_lead = _id(body["leader_contact_id"], "person") if body["leader_contact_id"] else None
    else:
        new_lead = lead
    if "co_leader_contact_ids" in sent:
        raw = body["co_leader_contact_ids"]
        if raw is None:
            raw = []
        if not isinstance(raw, list):
            raise HTTPException(400, "Co-leaders are a list of people")
        co = []
        for x in raw:
            x = _id(x, "person")
            if x not in co and x != new_lead:
                co.append(x)
    else:
        # Whoever led before and isn't the new lead stays on, as a co-leader.
        co = [c for c in before if c != new_lead]
    if len(co) > CO_LEADERS_MAX:
        raise HTTPException(400, f"A group has at most {CO_LEADERS_MAX} co-leaders.")
    if co and not new_lead:
        raise HTTPException(400, "Name the group's leader first, then its co-leaders.")
    if how == "lead":
        # The lead picks co-leaders from the group's own people.
        members = {str(r["contact_id"]) for r in _need(
            f"/group_members?business_id=eq.{_q(biz)}&group_id=eq.{_q(gid)}&select=contact_id&limit=1000")}
        if set(co) - members:
            raise HTTPException(400, "A co-leader is someone already in the group.")

    patch: Dict[str, Any] = {}
    to = g.get("answers_to_contact_id")
    to = str(to) if to else None
    if "answers_to_contact_id" in sent:
        to = _id(body["answers_to_contact_id"], "person") if body["answers_to_contact_id"] else None
        patch["answers_to_contact_id"] = to
    if to and to in ({new_lead} | set(co)):
        raise HTTPException(400, "A group's leaders can't answer to one of themselves.")
    if to and "answers_to_contact_id" in sent and not any(p["contact_id"] == to for p in answer_choices(biz)):
        raise HTTPException(400, "They don’t hold a role here yet, so nobody can answer to them. Give them a role first.")
    if "course_id" in sent:
        cid = _id(body["course_id"], "class") if body["course_id"] else None
        if cid and kind != "class":
            raise HTTPException(400, "Only a class group points to a class.")
        if cid and not _need(f"/academy_courses?id=eq.{_q(cid)}&business_id=eq.{_q(biz)}&select=id&limit=1"):
            raise HTTPException(404, "That class isn't here.")
        patch["course_id"] = cid
    if "serve_option" in sent:
        opt = _plain(body["serve_option"])[:SERVE_OPTION_MAX] or None
        if opt and kind != "team":
            raise HTTPException(400, "Only a serving team answers for a Serve card choice.")
        patch["serve_option"] = opt

    _ours(biz, [new_lead, *co, to])
    leaders_sent = bool(sent & {"leader_contact_id", "co_leader_contact_ids"})
    # A save of only who it answers to, a class or a Serve choice leaves every
    # leader row as it is (M-8 review M1).
    want = (({new_lead: False} if new_lead else {}) | {c: True for c in co}) if leaders_sent else dict(before)
    up = [{"group_id": gid, "contact_id": c, "business_id": biz, "role": "leader", "co_leader": flag}
          for c, flag in want.items() if before.get(c) is not flag]
    if up:
        saved = sb_clients.sb_post_as_service("/group_members?on_conflict=group_id,contact_id", up,
                                              prefer="resolution=merge-duplicates,return=representation")
        if not isinstance(saved, list) or len(saved) != len(up):
            raise HTTPException(503, UNSAVED)
    gone = [c for c in before if c not in want]
    if gone:
        done = sb_clients.sb_patch_as_service(
            f"/group_members?business_id=eq.{_q(biz)}&group_id=eq.{_q(gid)}&contact_id=in.({','.join(_q(c) for c in gone)})",
            {"role": "member", "co_leader": False})
        if not isinstance(done, list):
            raise HTTPException(503, UNSAVED)
    if patch:
        done = sb_clients.sb_patch_as_service(f"/groups?id=eq.{_q(gid)}&business_id=eq.{_q(biz)}", patch)
        if not isinstance(done, list) or not done:
            raise HTTPException(503, UNSAVED)
    new = [(c, flag) for c, flag in want.items() if c not in before]
    return {"view": view(biz, gid), "new": new, "group": g}


# ─── The note ────────────────────────────────────────────────────────

def note_words(group_name: str, co: bool) -> str:
    name = _plain(group_name) or "your group"
    return f"You’re now a co-leader of {name}." if co else f"You now lead {name}."


async def tell(business: Dict[str, Any], g: Dict[str, Any], new: List[Tuple[str, bool]]) -> Dict[str, int]:
    """'You now lead Parking Team': a note to each phone that has the
    member app, and an email to each adult without one. Never raises."""
    if not new:
        return {"phones": 0, "emailed": 0}
    try:
        return await _tell(business, g, new)
    except Exception:
        logger.warning("group leads: the note didn't go", exc_info=True)
        return {"phones": 0, "emailed": 0}


async def _tell(business: Dict[str, Any], g: Dict[str, Any], new: List[Tuple[str, bool]]) -> Dict[str, int]:
    import academy_join
    import email_layout
    import email_sender
    import group_email
    import member_push
    biz = str(business["id"])
    gid = str(g["id"])
    phones = 0
    for co in (False, True):
        ids = [c for c, flag in new if flag is co]
        if ids:
            phones += await asyncio.to_thread(
                member_push.send, business, "groups", title=_plain(g.get("name")) or "Your group",
                body=note_words(g.get("name") or "", co) + " Open it on the Lead tab.",
                url=f"/my/lead/groups/{gid}", contact_ids=ids, ref_id=f"group-lead:{gid}:{'co' if co else 'lead'}:{','.join(sorted(ids))}",
                tag=f"group-{gid}")
    subs = sb_clients.sb_get_as_service(f"/member_push_subscriptions?business_id=eq.{_q(biz)}"
                                        f"&contact_id=in.({','.join(_q(c) for c, _ in new)})&select=contact_id&limit=500")
    have = {str(s["contact_id"]) for s in subs} if isinstance(subs, list) else set()
    people = await asyncio.to_thread(group_email._people, biz, [c for c, _ in new if c not in have]) or []
    co_of = dict(new)
    church = _plain(business.get("name")) or "Your church"
    settings = business.get("settings") if isinstance(business.get("settings"), dict) else {}
    app = await asyncio.to_thread(group_email.app_url, biz)
    emailed = 0
    for p in people:
        email = str(p.get("email") or "").strip()
        if not academy_join.valid_email(email) or not group_email._adult(p):
            continue
        words = note_words(g.get("name") or "", co_of.get(str(p["id"]), False))
        msg = f"{words}\n\nYou’ll find the group on the Lead tab of {church}’s app: its people, its gatherings and its Board."
        html = email_layout.render_html(
            msg, business_name=church, brand=email_layout.brand_of(settings), sig=None,
            unsubscribe_url=email_sender._unsubscribe_url(email), preheader=words,
            cta=(("Open the Lead tab", f"{app}/my/lead/groups/{gid}") if app else None),
            disclaimer=f"You’re getting this because {church} named you a leader of {_plain(g.get('name')) or 'a group'}.")
        try:
            await email_sender.send_via_resend(
                to_email=email, to_name=p.get("name") or None,
                from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
                from_name=church, subject=f"{church}: {words}"[:150], body=html, reply_to=None, business_id=biz,
                idempotency_key=f"group-lead-{gid}-{p['id']}")
            emailed += 1
        except Exception:
            logger.warning("group leads: an email didn't go", exc_info=True)
    return {"phones": phones, "emailed": emailed}


# ─── The office's routes ─────────────────────────────────────────────

def _church(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    biz = _id(business_id, "church")
    rows = _need(f"/businesses?id=eq.{_q(biz)}&select=id,name,settings,owner_id&limit=1")
    if not rows:
        raise HTTPException(404, "business not found")
    if not church_open(biz):
        raise HTTPException(404, "Not found")
    return rows[0]


@router.get("/church/groups/leads/choices")
def leads_choices(business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    """What a New group form offers before the group exists: who a group can
    answer to (people holding an active role), the church's Course Studio
    classes, the Serve card's choices, and whether this login names leaders."""
    import church_follow_up as cfu
    business = _church(business_id, user)
    biz = str(business["id"])
    role, _person = _seat(biz, user)
    if _RANK.get(role or "", 0) < _RANK["viewer"]:
        raise HTTPException(403, "This seat can't see groups.")
    if not ready(biz):
        return {"ready": False, "can_name": False, "answer_choices": [], "classes": [], "serve_options": []}
    can = office_names(biz, user, role)
    classes = _need(f"/academy_courses?business_id=eq.{_q(biz)}&status=neq.archived&select=id,title&order=title.asc&limit=200")
    teams = cfu.teams(biz)
    if teams is None:
        raise HTTPException(503, UNREAD)
    return {"ready": True, "can_name": can, "answer_choices": answer_choices(biz) if can else [],
            "classes": [{"id": str(c["id"]), "title": _plain(c.get("title")) or "Class"} for c in classes],
            "serve_options": teams}


@router.get("/church/groups/{group_id}/leads")
def leads_read(group_id: str, business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    business = _church(business_id, user)
    biz = str(business["id"])
    gid = _id(group_id, "group")
    v = view(biz, gid)
    rows = leader_rows(biz, gid, cols=v["ready"])
    how, role = level(biz, user, rows)
    if _RANK.get(role or "", 0) < _RANK["viewer"]:
        raise HTTPException(403, "This seat can't see groups.")
    v["can"] = {"name_leader": how == "office" and v["ready"], "co_leaders": how in ("office", "lead") and v["ready"],
                "answers_to": how == "office" and v["ready"]}
    if how == "office" and v["ready"]:
        v["answer_choices"] = answer_choices(biz)
    return v


class LeadsIn(BaseModel):
    business_id: str
    leader_contact_id: Optional[str] = None
    co_leader_contact_ids: Optional[List[str]] = None
    answers_to_contact_id: Optional[str] = None
    course_id: Optional[str] = None
    serve_option: Optional[str] = None


@router.put("/church/groups/{group_id}/leads")
async def leads_save(group_id: str, body: LeadsIn, user: AuthedUser = Depends(require_user)):
    business = await asyncio.to_thread(_church, body.business_id, user)
    biz = str(business["id"])
    gid = _id(group_id, "group")
    if not await asyncio.to_thread(ready, biz):
        raise HTTPException(503, NOT_YET)
    rows = await asyncio.to_thread(leader_rows, biz, gid)
    # A direct call, so the ownership sweep (ownership_sweep.py) sees the gate.
    how, role = level(biz, user, rows)
    if not how:
        raise HTTPException(403, "The pastor, an admin or whoever looks after groups names a group’s leader.")
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items() if k in FIELDS}
    out = await asyncio.to_thread(save, biz, gid, fields, how)
    told = await tell(business, out["group"], out["new"])
    return {"ok": True, **out["view"], "told": told}
