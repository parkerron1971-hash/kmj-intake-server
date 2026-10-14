"""
chief_church_actions.py — Chief reads a church's people.

Chief could read sermons and giving statements and nothing else a church
records, so "who came for the first time?", "who's drifting from their
group?" and "how many were online Sunday?" had no answer but a guess.
One read verb, `church_people`, answers them from church_reads — the same
functions the Home desk reads, so Chief and the desk never disagree.

    section = first_time | groups | attendance | care   (default: overview)

`care` is the one gated part: the Prayer & care inbox and children's
check-in, as COUNTS only (never a request's words or a child's name), and
only for the owner or a manager. Anywhere the caller isn't known — an
outside agent, a background run — it is refused, not guessed.

Handlers return `result` AND `label` per the house contract.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import church_reads

SECTIONS = ("overview", "first_time", "groups", "attendance", "care")
_CARE_ROLES = {"owner", "admin", "manager"}


def _fail(action_type: str, msg: str) -> Dict[str, Any]:
    return {"type": action_type, "result": f"failed: {msg}", "failed": True,
            "label": msg[:80], "nav": None}


def _caller_role(business_id: str) -> Optional[str]:
    from chief_of_staff import _TURN_USER_ID
    uid = _TURN_USER_ID.get()
    if not uid:
        return None
    from business_users_router import role_of
    return role_of(business_id, uid)


def _first_time_lines(rows: List[Dict[str, Any]]) -> List[str]:
    if not rows:
        return ["First-time guests: nobody waiting. Every first-time guest in the last "
                f"{church_reads.FIRST_VISIT_WINDOW_DAYS} days has been reached (or there were none)."]
    lines = [f"First-time guests nobody has reached since their first visit ({len(rows)}):"]
    for r in rows:
        how = ", ".join(w for w, on in (("phone", r.get("has_phone")),
                                        ("email", r.get("has_email"))) if on)
        lines.append(f"- {r['name']}: {r['detail']}"
                     + (f"; has {how}" if how else "")
                     + (f" (contact_id {r['contact_id']})" if r.get("contact_id") else ""))
    return lines


def _group_lines(g: Dict[str, Any]) -> List[str]:
    if not g["groups"]:
        return ["Groups: none set up yet."]
    lines = [f"Groups ({len(g['groups'])} active, last {church_reads.GROUP_WINDOW_WEEKS} weeks):"]
    for x in g["groups"]:
        lines.append(f"- {x['name']}: {x['members']} members, met {x['meetings']} times"
                     + (f", last on {x['last_met']}" if x.get("last_met") else ", no meetings recorded")
                     + (f", about {x['average']} at each of the last few" if x.get("average") is not None else ""))
    if g["drifting"]:
        lines.append(f"Drifting (missed their group's last {church_reads.DRIFT_MISSED} meetings):")
        for d in g["drifting"]:
            lines.append(f"- {d['name']} ({d['group']}): "
                         + (f"last came {d['last_came']}" if d.get("last_came")
                            else f"not at any meeting in {church_reads.GROUP_WINDOW_WEEKS} weeks")
                         + f" (contact_id {d['contact_id']})")
    else:
        lines.append("Nobody has missed their group's last "
                     f"{church_reads.DRIFT_MISSED} meetings (groups with fewer meetings recorded can't say yet).")
    return lines


def _attendance_lines(rows: List[Dict[str, Any]]) -> List[str]:
    if not rows:
        return [f"Attendance: nothing recorded in the last {church_reads.SERVICE_WINDOW_WEEKS} weeks."]
    lines = [f"Attendance, newest first (last {church_reads.SERVICE_WINDOW_WEEKS} weeks):"]
    for s in rows[:12]:
        parts = [f"{s['in_person']} checked in by name", f"{s['online']} online"]
        if s["first_time"]:
            parts.append(f"{s['first_time']} first-time")
        if s["areas"]:
            parts.append("counted " + ", ".join(f"{a} {n}" for a, n in s["areas"].items()))
        lines.append(f"- {s['title']} ({s['date'] or 'undated'}): " + "; ".join(parts))
    lines.append("Named check-ins and counted heads are separate records; never add them "
                 "together unless the team counted only the people not checked in.")
    return lines


def _care_lines(c: Dict[str, Any]) -> List[str]:
    care = c["care"]
    lines = [f"Prayer & care, last 90 days: {care['new']} new, {care['reviewed']} reviewed, "
             f"{care['closed']} closed, {care['prayed']} marked prayed"
             + (f"; the oldest new one has waited {care['oldest_new_days']} days"
                if care.get("oldest_new_days") is not None else "") + "."]
    kids = c["children_checked_in"]
    if kids:
        lines.append("Children checked in: " + ", ".join(
            f"{k['children']} on {k['date']}" for k in kids[:8]) + ".")
    lines.append("Counts only. The requests themselves are in Prayer & care, for the owner.")
    return lines


async def handle_church_people(client, biz, action) -> Dict[str, Any]:
    business_id = str(biz.get("id") or "")
    if not business_id:
        return _fail("church_people", "no business on record")
    section = str(action.get("section") or "overview").strip().lower()
    if section not in SECTIONS:
        return _fail("church_people", f"section must be one of {', '.join(SECTIONS)}")

    lines: List[str] = []

    if section == "care":
        role = await asyncio.to_thread(_caller_role, business_id)
        if role not in _CARE_ROLES:
            return {"type": "church_people", "section": "care",
                    "result": "refused: care and children's numbers are for the church's owner "
                              "or a manager. Say so plainly; do not estimate them.",
                    "label": "Care numbers are owner or manager only", "nav": None}
        c = await asyncio.to_thread(church_reads.care_counts, business_id)
        if c is None:
            return _fail("church_people", "care numbers couldn't be read right now")
        return {"type": "church_people", "section": "care", "result": "\n".join(_care_lines(c)),
                "label": "Prayer & care numbers"}

    if section in ("overview", "first_time"):
        rows = await asyncio.to_thread(church_reads.first_time_guests, business_id)
        if rows is None:
            return _fail("church_people", "first-time guests couldn't be read right now")
        lines += _first_time_lines(rows)
    if section in ("overview", "groups"):
        g = await asyncio.to_thread(church_reads.group_drift, business_id)
        if g is None:
            return _fail("church_people", "groups couldn't be read right now")
        lines += _group_lines(g)
    if section in ("overview", "attendance"):
        s = await asyncio.to_thread(church_reads.services, business_id)
        if s is None:
            return _fail("church_people", "attendance couldn't be read right now")
        lines += _attendance_lines(s)

    label = {"overview": "Church people", "first_time": "First-time guests",
             "groups": "Groups", "attendance": "Attendance"}[section]
    return {"type": "church_people", "section": section,
            "result": "\n".join(lines), "label": label}
