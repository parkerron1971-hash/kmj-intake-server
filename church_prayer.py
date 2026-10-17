"""church_prayer.py — prayer shared with the prayer team reaches a member who leads.

Kevin, 2026-10-17: "In a church always have prayer connected to Pastoral
roles and for Pastor to be able to assign a direct leaders to oversee prayer
request … create and Intercessor leader now." Design canvas
BKNqVVNiyxfAGAa7UAVWUC, boards 2, 5, 7.

    the person chooses ........ "Our prayer team may pray over this with you"
                                or "Keep this with the pastors only"
                                (ministry_care_requests.prayer_team)
    words about danger ........ needs_pastor: someone hurting themselves or
                                someone else, abuse, or a death. Always the
                                pastor's, never a member's (a database trigger
                                refuses the hand-off too)
    a shared request .......... handed to a member holding a role that takes
                                prayer_shared (the Intercessor leader), the one
                                with the fewest waiting first; due in a day
    they pray, and say so ..... "I prayed", "Send a note" (an email from the
                                church), or pass it to an intercessor who
                                answers to them
    nobody waits .............. the sweep tells them once; on the day, a
                                reminder; a day late, the role they answer to
                                is told; three days late, one more step up

The office (Prayer & care, private_care.py) still sees every request; a
member who leads sees only the ones handed to them: the request, a first
name, and how to reach them only when the person asked for a call and the
role allows it. Emails never carry the request's words.
"""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

import sb_clients

logger = logging.getLogger(__name__)

DUE_DAYS = 1
LATE_LADDER = ((0, 1, "nudged"), (1, 2, "overseer_told"), (3, 3, "next_up"))

_DANGER = re.compile(
    r"\b(abus(e|ed|es|ing|ive)|molest\w*|rap(e|ed|ing)|sexual(ly)? assault\w*|assault(ed)?|"
    r"beat(s|ing)? (me|us|her|him)|hits? (me|us|her|him)|threaten\w* (me|us|to kill)|kill (him|her|them|me)|"
    r"overdos\w*|died|passed away|death|funeral|murder\w*|suicid\w*)\b", re.IGNORECASE)


def needs_pastor(text: Any) -> bool:
    """Words about someone in danger, abuse, or a death: the pastor's,
    always, whatever the person chose. The crisis floor is the one the
    member app's messages use (msg_screen.CRISIS_RE)."""
    s = str(text or "")
    try:
        from msg_screen import CRISIS_RE
        if CRISIS_RE.search(s):
            return True
    except Exception:
        pass
    return bool(_DANGER.search(s))


def _yes(v: Any) -> bool:
    if isinstance(v, list):
        return any(_yes(x) for x in v)
    return str(v or "").strip().lower() in ("yes", "true", "1", "on", "team", "share")


def consent_columns(submission: Dict[str, Any], *, share: Any = None, wants_call: Any = None) -> Dict[str, Any]:
    """The three columns every new care request carries. A request is shared
    with the prayer team only when the person said so; one that needs a
    pastor is never shared."""
    sub = submission or {}
    fields = sub.get("fields") if isinstance(sub.get("fields"), dict) else {}
    shared = _yes(share if share is not None else (sub.get("prayer_team") or fields.get("share") or fields.get("prayer_team")))
    call = _yes(wants_call if wants_call is not None else (sub.get("wants_call") or sub.get("follow_up") or fields.get("follow_up")))
    text = " ".join(str(sub.get(k) or "") for k in ("prayer_request", "message", "request"))
    danger = needs_pastor(text)
    return {"prayer_team": bool(shared and not danger), "wants_call": bool(call), "needs_pastor": danger}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _q(v: Any) -> str:
    from urllib.parse import quote
    return quote(str(v), safe="")


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def first_name(name: Any) -> str:
    s = " ".join(str(name or "").split())
    return (s.split(" ")[0] if s else "") or "Someone"


# ─── Handing a shared request to a member who leads ───────────────────

def _prayer_holders(biz: str, stream: str = "prayer_shared") -> Optional[List[Dict[str, Any]]]:
    """Active holders of roles that take this stream, with their role."""
    import church_follow_up as cfu
    import church_roles as cr
    defs = cr.defs(biz)
    holders = cfu.roles(biz)
    if defs is None or holders is None:
        return None
    keys = {d["key"] for d in defs if stream in (d.get("handles") or [])}
    return [h for h in holders if h["status"] == "active" and h["role"] in keys]


def _waiting(biz: str) -> Optional[Dict[str, int]]:
    rows = _rows(f"/ministry_care_requests?business_id=eq.{_q(biz)}&leader_contact_id=not.is.null"
                 "&leader_prayed_at=is.null&select=leader_contact_id&limit=2000")
    if rows is None:
        return None
    out: Dict[str, int] = {}
    for r in rows:
        k = str(r["leader_contact_id"])
        out[k] = out.get(k, 0) + 1
    return out


def on_new(business_id: str, row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """After a care request is saved: hand it to a prayer leader when the
    person shared it and nothing in it needs a pastor. Never raises; the
    request is already saved for the office either way."""
    try:
        if not row or not row.get("id") or not row.get("prayer_team") or row.get("needs_pastor") or row.get("leader_contact_id"):
            return None
        biz = str(business_id)
        import church_follow_up as cfu
        bizs = _rows(f"/businesses?id=eq.{_q(biz)}&select=id,name,type&limit=1")
        if not bizs or not cfu.is_church(bizs[0]):
            return None
        people, load = _prayer_holders(biz), _waiting(biz)
        if people is None or load is None:
            logger.warning("prayer hand-off skipped: roles could not be read (business %s)", biz[:8])
            return None
        if not people:
            return None  # no one leads prayer yet: it waits with the pastor
        pick = sorted(people, key=lambda h: (load.get(h["contact_id"], 0), h["name"].casefold()))[0]
        now = _now()
        out = sb_clients.sb_patch_as_service(
            f"/ministry_care_requests?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz)}&leader_contact_id=is.null",
            {"leader_contact_id": pick["contact_id"], "leader_role": pick["role"], "leader_assigned_at": _iso(now),
             "leader_due_at": _iso(now + timedelta(days=DUE_DAYS)), "leader_late_level": 0, "updated_at": _iso(now)})
        return out[0] if isinstance(out, list) and out else None
    except Exception:
        logger.warning("prayer hand-off failed for business %s", str(business_id)[:8], exc_info=True)
        return None


# ─── The leader's side ────────────────────────────────────────────────

_SEL = ("id,created_at,submission,contact_id,prayer_team,wants_call,needs_pastor,leader_contact_id,leader_role,"
        "leader_assigned_at,leader_due_at,leader_prayed_at,leader_noted_at,leader_late_level")


def _sees_reach(biz: str, role_key: str) -> bool:
    import church_roles as cr
    d = next((x for x in (cr.defs(biz) or []) if x["key"] == role_key), None)
    return bool(d and "reach" in (d.get("sees") or []))


def item(row: Dict[str, Any], *, reach: bool) -> Dict[str, Any]:
    """A request as a member who leads sees it: a first name, the words,
    where it came from, and how to reach them only when they asked for a
    call and the role may see that."""
    sub = row.get("submission") or {}
    can_reach = bool(row.get("wants_call") and reach)
    return {
        "id": str(row["id"]), "first": first_name(sub.get("name")),
        "text": " ".join(str(sub.get("prayer_request") or sub.get("message") or "").split())[:4000],
        "source": str(sub.get("source") or "Prayer request"), "created_at": row.get("created_at"),
        "due_at": row.get("leader_due_at"), "wants_call": bool(row.get("wants_call")),
        "phone": (sub.get("phone") or "") if can_reach else "", "email_ok": bool(sub.get("email")),
        "email": (sub.get("email") or "") if can_reach else "",
        "prayed_at": row.get("leader_prayed_at"), "noted_at": row.get("leader_noted_at"),
        "role": row.get("leader_role") or "",
    }


def leader_prayers(business_id: str, leader_contact_id: str) -> Optional[Dict[str, Any]]:
    """The Prayer list: requests handed to this member and not yet prayed,
    plus how many they prayed over in the last 30 days."""
    biz, lid = str(business_id), str(leader_contact_id)
    since = _iso(_now() - timedelta(days=30))
    rows = _rows(f"/ministry_care_requests?business_id=eq.{_q(biz)}&leader_contact_id=eq.{_q(lid)}"
                 f"&or=(leader_prayed_at.is.null,leader_prayed_at.gte.{_q(since)})&select={_SEL}"
                 "&order=leader_due_at.asc&limit=200")
    if rows is None:
        return None
    reach_by_role: Dict[str, bool] = {}
    out = []
    today = _now() - timedelta(hours=20)
    for r in rows:
        # Prayed over: it stays on the list that day, so a note can follow.
        done = cfu_parse(r.get("leader_prayed_at"))
        if done and done < today:
            continue
        k = r.get("leader_role") or ""
        if k not in reach_by_role:
            reach_by_role[k] = _sees_reach(biz, k)
        out.append(item(r, reach=reach_by_role[k]))
    prayed = sum(1 for r in rows if r.get("leader_prayed_at"))
    return {"requests": out, "prayed_30": prayed}


def _mine(biz: str, rid: str, lid: str) -> Dict[str, Any]:
    import church_follow_up as cfu
    rid = cfu._uid(rid, "request")
    rows = _rows(f"/ministry_care_requests?id=eq.{_q(rid)}&business_id=eq.{_q(biz)}&select={_SEL}&limit=1")
    if rows is None:
        raise HTTPException(503, "That couldn’t be loaded. Try again in a moment.")
    if not rows or str(rows[0].get("leader_contact_id") or "") != lid:
        raise HTTPException(404, "That request isn’t handed to you")
    return rows[0]


def prayed(business_id: str, leader: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    biz, lid = str(business_id), str(leader["id"])
    row = _mine(biz, request_id, lid)
    if row.get("leader_prayed_at"):
        return row
    now = _iso(_now())
    out = sb_clients.sb_patch_as_service(
        f"/ministry_care_requests?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz)}&leader_contact_id=eq.{_q(lid)}",
        {"leader_prayed_at": now, "updated_at": now})
    if not isinstance(out, list) or not out:
        raise HTTPException(503, "That didn’t save. Try again.")
    # The office's "marked prayed" too, when no one marked it yet.
    sb_clients.sb_patch_as_service(
        f"/ministry_care_requests?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz)}&prayed_at=is.null", {"prayed_at": now})
    return out[0]


NOTE_SUBJECT = "We prayed for you today"


async def send_note(business: Dict[str, Any], leader: Dict[str, Any], request_id: str) -> bool:
    """An email from the church to the person who asked: "We prayed for you
    today." Their own words are never repeated in it. Once per request."""
    import asyncio
    import church_follow_up as cfu
    biz, lid = str(business["id"]), str(leader["id"])
    row = await asyncio.to_thread(_mine, biz, request_id, lid)
    sub = row.get("submission") or {}
    if row.get("leader_noted_at"):
        return True
    if not sub.get("email"):
        raise HTTPException(400, "They left no email, so a note can’t be sent")
    church = " ".join(str(business.get("name") or "Your church").split())
    body = cfu._mail_html([f"Hi {html.escape(first_name(sub.get('name')))},",
                           f"We prayed for you today. {html.escape(church)} is with you.",
                           f"— {html.escape(first_name(leader.get('name')))}, for the prayer team"], "", "")
    ok = await cfu._email(business, str(sub["email"]), str(sub.get("name") or ""), NOTE_SUBJECT, body,
                          f"prayer-note-{row['id']}")
    if not ok:
        raise HTTPException(503, "That note didn’t send. Try again in a moment.")
    now = _iso(_now())
    await asyncio.to_thread(sb_clients.sb_patch_as_service,
                            f"/ministry_care_requests?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz)}",
                            {"leader_noted_at": now, "updated_at": now})
    return True


def pass_targets(business_id: str, leader: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """Who a prayer leader can pass a request to: members holding a role
    that takes passed-on prayer and answers to one of this leader's roles."""
    import church_follow_up as cfu
    import church_roles as cr
    biz, lid = str(business_id), str(leader["id"])
    defs, holders = cr.defs(biz), cfu.roles(biz)
    if defs is None or holders is None:
        return None
    mine = {d["id"] for d in defs if any(h["contact_id"] == lid and h["status"] == "active" and h["role"] == d["key"]
                                          for h in holders)}
    keys = {d["key"] for d in defs if d.get("reports_to") in mine and "prayer_passed" in (d.get("handles") or [])}
    return [{"contact_id": h["contact_id"], "name": h["name"], "role": h["role"]}
            for h in holders if h["status"] == "active" and h["role"] in keys and h["contact_id"] != lid]


def pass_on(business_id: str, leader: Dict[str, Any], request_id: str, to_contact_id: str) -> Dict[str, Any]:
    biz, lid = str(business_id), str(leader["id"])
    row = _mine(biz, request_id, lid)
    if row.get("leader_prayed_at"):
        raise HTTPException(400, "You’ve already prayed over this one")
    targets = pass_targets(biz, leader)
    if targets is None:
        raise HTTPException(503, "That couldn’t be checked. Try again in a moment.")
    to = next((t for t in targets if t["contact_id"] == str(to_contact_id)), None)
    if not to:
        raise HTTPException(400, "Pick someone who prays with you")
    now = _now()
    out = sb_clients.sb_patch_as_service(
        f"/ministry_care_requests?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz)}&leader_contact_id=eq.{_q(lid)}",
        {"leader_contact_id": to["contact_id"], "leader_role": to["role"], "leader_assigned_at": _iso(now),
         "leader_due_at": _iso(now + timedelta(days=DUE_DAYS)), "leader_told_at": None, "leader_late_level": 0,
         "updated_at": _iso(now)})
    if not isinstance(out, list) or not out:
        raise HTTPException(503, "That didn’t save. Try again.")
    return out[0]


# ─── The office's Prayer & care list ──────────────────────────────────

def office_fields(rows: List[Dict[str, Any]], business_id: str) -> List[Dict[str, Any]]:
    """What the office sees about a request's way through the prayer team:
    shared or not, a call wanted, a pastor needed, who has it, prayed, noted."""
    import church_follow_up as cfu
    import church_roles as cr
    ids = {str(r["leader_contact_id"]) for r in rows if r.get("leader_contact_id")}
    people = cfu._contacts(str(business_id), ids) or {} if ids else {}
    defs = cr.defs(str(business_id)) or [] if ids else []
    out = []
    for r in rows:
        lid = str(r.get("leader_contact_id") or "")
        p = people.get(lid) if lid else None
        out.append({**r,
                    "prayer_team": bool(r.get("prayer_team")), "wants_call": bool(r.get("wants_call")),
                    "needs_pastor": bool(r.get("needs_pastor")),
                    "leader": ({"name": p["name"], "role_title": cr.title_of(r.get("leader_role") or "", defs)} if p else None),
                    "leader_prayed_at": r.get("leader_prayed_at"), "leader_noted_at": r.get("leader_noted_at")})
    return out


# ─── Nobody waits ─────────────────────────────────────────────────────

def late_step(row: Dict[str, Any], now: datetime) -> Optional[tuple]:
    if row.get("leader_prayed_at") or not row.get("leader_contact_id"):
        return None
    due = cfu_parse(row.get("leader_due_at"))
    if not due or now < due:
        return None
    level = int(row.get("leader_late_level") or 0)
    best = None
    for days, lvl, kind in LATE_LADDER:
        if now >= due + timedelta(days=days) and lvl > level:
            best = (lvl, kind)
    return best


def cfu_parse(ts: Any) -> Optional[datetime]:
    import church_follow_up as cfu
    return cfu._parse(ts)


async def sweep(now: Optional[datetime] = None) -> Dict[str, int]:
    """Across churches: tell a prayer leader once that a request is theirs,
    remind them on the day, and climb their chain when it waits. Emails
    carry a first name, never the request."""
    import asyncio
    now = now or _now()
    stats = {"told": 0, "nudged": 0, "overseer_told": 0, "next_up": 0}
    rows = await asyncio.to_thread(
        _rows, "/ministry_care_requests?leader_contact_id=not.is.null&leader_prayed_at=is.null&leader_late_level=lt.3"
               f"&or=(leader_told_at.is.null,leader_due_at.lt.{_q(_iso(now))})&select=business_id,{_SEL}"
               "&order=leader_due_at.asc&limit=500")
    if not rows:
        return stats
    by_biz: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_biz.setdefault(str(r["business_id"]), []).append(r)
    for biz_id, items in by_biz.items():
        try:
            await _sweep_church(biz_id, items, now, stats)
        except Exception:
            logger.warning("prayer sweep failed for business %s", biz_id[:8], exc_info=True)
    return stats


async def _sweep_church(biz_id: str, items: List[Dict[str, Any]], now: datetime, stats: Dict[str, int]) -> None:
    import asyncio
    import church_follow_up as cfu
    import church_roles as cr
    bizs = await asyncio.to_thread(_rows, f"/businesses?id=eq.{_q(biz_id)}&select=id,name,type&limit=1")
    if not bizs:
        return
    biz = bizs[0]
    defs = await asyncio.to_thread(cr.defs, biz_id)
    holders = await asyncio.to_thread(cfu.roles, biz_id)
    if defs is None or holders is None:
        return
    held = cr.active_holders(holders)
    people = {h["contact_id"]: h for h in holders}
    origin = await asyncio.to_thread(cfu.site_origin, biz_id)
    link = f"{origin}/my/lead/prayer" if origin else ""
    church = " ".join(str(biz.get("name") or "Your church").split())
    dmap = cr.by_key(defs)
    for r in items:
        rid, lid = str(r["id"]), str(r["leader_contact_id"])
        leader = people.get(lid)
        who = first_name((r.get("submission") or {}).get("name"))
        if not r.get("leader_told_at"):
            told = False
            if leader and leader.get("email"):
                told = await cfu._email(biz, leader["email"], leader["name"], "A prayer request is waiting for you",
                                        cfu._mail_html([f"Hi {html.escape(first_name(leader['name']))},",
                                                        f"{html.escape(who)} asked {html.escape(church)} for prayer and "
                                                        "agreed to share it with the prayer team. It’s yours to pray over "
                                                        "today."], link, "Open your Lead tab"),
                                        f"prayer-told-{rid}-{r.get('leader_assigned_at')}")
            else:
                told = await cfu._office_alert(biz_id, "A prayer leader has no email",
                                               f"A shared prayer request went to {leader['name'] if leader else 'a prayer leader'}, "
                                               "who has no email on file, so they haven’t been told.",
                                               f"prayer-noemail-{rid}", None)
            if told:
                await asyncio.to_thread(sb_clients.sb_patch_as_service,
                                        f"/ministry_care_requests?id=eq.{_q(rid)}&business_id=eq.{_q(biz_id)}",
                                        {"leader_told_at": _iso(now)})
                stats["told"] += 1
        rung = late_step(r, now)
        if not rung:
            continue
        level, kind = rung
        delivered = False
        role = dmap.get(r.get("leader_role") or "")
        above = cr.chain_above(role, defs, held, skip={lid})
        if kind == "nudged":
            if leader and leader.get("email"):
                delivered = await cfu._email(biz, leader["email"], leader["name"], f"{who}’s prayer request is due today",
                                             cfu._mail_html([f"Hi {html.escape(first_name(leader['name']))},",
                                                             f"{html.escape(who)}’s prayer request is waiting. When you’ve "
                                                             "prayed, tap “I prayed” on your Lead tab."], link, "Open your Lead tab"),
                                             f"prayer-nudge-{rid}-{r.get('leader_due_at')}")
            else:
                delivered = True
        else:
            step = 0 if kind == "overseer_told" else 1
            if len(above) > step:
                target_role, target = above[step]
            elif above:
                target_role, target = above[-1]
            else:
                target_role, target = None, []
            late = "a day" if kind == "overseer_told" else "three days"
            # The rung is climbed only when the person above was told (one
            # email went out, or no one above has an email to send to) and
            # the office's alert stands; otherwise the next sweep tries again.
            mailable = [p for p in target if p.get("email")]
            sent_any = not mailable
            for p in mailable:
                ok = await cfu._email(biz, p["email"], p.get("name") or "",
                                      f"A prayer request has waited {late}",
                                      cfu._mail_html([f"{html.escape(who)}’s prayer request has waited {late} with "
                                                      f"{html.escape(leader['name'] if leader else 'the prayer team')}. "
                                                      + ("Hand it to someone else in Prayer & care?" if kind == "next_up" else
                                                         "They answer to you.")], "", ""),
                                      f"prayer-{kind}-{rid}-{r.get('leader_due_at')}-{p['contact_id']}")
                sent_any = sent_any or ok
            names = ", ".join(p["name"] for p in target) or "no one above them"
            alerted = await cfu._office_alert(
                biz_id, "A prayer request is waiting" if kind == "overseer_told" else "Hand a prayer request to someone else?",
                f"{who}’s request has waited {late} with {leader['name'] if leader else 'the prayer team'}. "
                f"Told: {names}{' (' + target_role['title'] + ')' if target_role else ''}.",
                f"prayer-{kind}-{rid}-{r.get('leader_due_at')}", None)
            delivered = bool(alerted and sent_any)
        if not delivered:
            continue
        await asyncio.to_thread(sb_clients.sb_patch_as_service,
                                f"/ministry_care_requests?id=eq.{_q(rid)}&business_id=eq.{_q(biz_id)}",
                                {"leader_late_level": level})
        stats[kind] += 1
