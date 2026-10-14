"""
church_reads.py — read-only answers about a church's people.

The church tables (attendance, groups, care, live) are written by their
own routers and by the app directly. This module only READS them, with
the service role and always pinned to one business, so that the Home
desk and Chief can ask the same question and get the same answer.

    first_time_guests(business_id)  who came for the first time and has
                                    not been reached since
    group_drift(business_id)        each group's last weeks, and who has
                                    stopped coming
    services(business_id)           who came to each recent service, in
                                    person and online
    care_counts(business_id)        the care inbox and children's check-in
                                    as numbers only (callers gate it)

Every function returns None when a read failed (an outage) and a list
when it worked, so a caller can tell "nobody" from "couldn't look".
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

import sb_clients

logger = logging.getLogger("church_reads")

# How far back a first visit still belongs on the "nobody has called"
# list. A month: past that, the person is on the ordinary care list
# (thirty days quiet already reads as a lapse there), and a list that
# keeps every guest since spring stops being something a pastor acts on.
FIRST_VISIT_WINDOW_DAYS = 30

# What counts as someone from the church reaching out. A check-in is NOT
# one: the attendance screen stamps last_interaction when it checks a
# guest in, which is exactly why the guest vanished from every
# "nobody has reached out" list the moment they were welcomed.
#   activity_logged     a call, text, visit or email logged by hand or by Chief
#   email_sent          an email from the app
#   sms_sent            a text logged as an event
#   agent_message_sent  a message an agent sent on the church's behalf
#   journey_sent        a step of a follow-up journey
REACH_OUT_EVENTS = ("activity_logged", "email_sent", "sms_sent",
                    "agent_message_sent", "journey_sent")


def _iso(dt: datetime) -> str:
    # No "+00:00": a raw "+" in a PostgREST query string reads as a space.
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _in(ids: Iterable[str]) -> str:
    return ",".join(sorted({str(i) for i in ids if i}))


def _get(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def _occasion_title(entry: Dict[str, Any]) -> str:
    data = entry.get("data") or {}
    title = " ".join(str(data.get("title") or data.get("name") or "").split())
    return title or "a service"


def _day_label(dt: datetime) -> str:
    return f"{dt.strftime('%b')} {dt.day}"


def _times(n: int) -> str:
    return "once" if n == 1 else "twice" if n == 2 else f"{n} times"


def first_time_guests(business_id: str, *, days: int = FIRST_VISIT_WINDOW_DAYS,
                      limit: int = 20, now: Optional[datetime] = None
                      ) -> Optional[List[Dict[str, Any]]]:
    """First-time guests nobody has reached out to since their first visit.

    A guest is someone checked in with `first_time` set inside the window.
    They drop off the list the moment anyone reaches out after that visit:
    an outbound text (not a failed one), or a logged call, visit, email or
    message (REACH_OUT_EVENTS). Coming back again does not take them off,
    because coming back is not the same as being called; it is shown.

    Longest waiting first. Each row:
        id              the first-visit attendance row
        contact_id      their record, or None for a name-only check-in
        name
        first_visit_at  ISO timestamp
        occasion        what they came to
        came_back       visits since the first
        has_phone, has_email
        detail          one line for a list ("Sunday Service, Oct 5 · came back once")
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(1, int(days)))
    biz = str(business_id)

    visits = _get(
        f"/attendance?business_id=eq.{biz}&first_time=is.true"
        f"&checked_in_at=gte.{_iso(cutoff)}"
        "&select=id,entry_id,contact_id,name,checked_in_at"
        "&order=checked_in_at.asc&limit=500")
    if visits is None:
        return None

    # One row per person: their EARLIEST first-time check-in. A name-only
    # guest (no record) is one person per name.
    firsts: Dict[str, Dict[str, Any]] = {}
    for v in visits:
        at = _parse(v.get("checked_in_at"))
        if at is None:
            continue
        key = (f"c:{v['contact_id']}" if v.get("contact_id")
               else "n:" + " ".join(str(v.get("name") or "").lower().split()))
        if key == "n:":
            continue
        if key not in firsts:
            firsts[key] = dict(v, _at=at)
    if not firsts:
        return []

    contact_ids = [f["contact_id"] for f in firsts.values() if f.get("contact_id")]
    reached: Dict[str, datetime] = {}
    later: Dict[str, List[datetime]] = {}
    contacts: Dict[str, Dict[str, Any]] = {}

    if contact_ids:
        ids = _in(contact_ids)
        texts = _get(
            f"/sms_messages?business_id=eq.{biz}&contact_id=in.({ids})"
            "&direction=eq.outbound&status=neq.failed"
            "&select=contact_id,created_at&order=created_at.desc&limit=2000")
        logged = _get(
            f"/events?business_id=eq.{biz}&contact_id=in.({ids})"
            f"&event_type=in.({','.join(REACH_OUT_EVENTS)})"
            "&select=contact_id,created_at&order=created_at.desc&limit=2000")
        again = _get(
            f"/attendance?business_id=eq.{biz}&contact_id=in.({ids})"
            "&select=contact_id,checked_in_at&limit=5000")
        people = _get(
            f"/contacts?business_id=eq.{biz}&id=in.({ids})"
            "&select=id,name,phone,email,status&limit=500")
        if texts is None or logged is None or again is None or people is None:
            return None
        for r in texts + logged:
            at = _parse(r.get("created_at"))
            cid = str(r.get("contact_id") or "")
            if at and cid and (cid not in reached or at > reached[cid]):
                reached[cid] = at
        for r in again:
            at = _parse(r.get("checked_in_at"))
            if at:
                later.setdefault(str(r.get("contact_id")), []).append(at)
        contacts = {str(p["id"]): p for p in people if p.get("id")}

    entry_ids = _in(f.get("entry_id") for f in firsts.values())
    entries = _get(f"/module_entries?business_id=eq.{biz}&id=in.({entry_ids})"
                   "&select=id,data&limit=500") if entry_ids else []
    titles = {str(e.get("id")): _occasion_title(e) for e in (entries or [])}

    out: List[Dict[str, Any]] = []
    for f in firsts.values():
        first_at: datetime = f["_at"]
        cid = str(f.get("contact_id") or "") or None
        person = contacts.get(cid) if cid else None
        if cid and person is None:
            continue  # the record was removed; nothing to call
        if person and str(person.get("status") or "") == "inactive":
            continue
        if cid and cid in reached and reached[cid] >= first_at:
            continue
        came_back = len([t for t in later.get(cid or "", []) if t > first_at])
        occasion = titles.get(str(f.get("entry_id")), "a service")
        detail = f"{occasion}, {_day_label(first_at)}"
        if came_back:
            detail += f" · came back {_times(came_back)}"
        if not person:
            detail += " · no phone or email on file"
        out.append({
            "id": f["id"],
            "contact_id": cid,
            "name": " ".join(str((person or {}).get("name") or f.get("name") or "").split()) or "Guest",
            "first_visit_at": first_at.isoformat(),
            "occasion": occasion,
            "came_back": came_back,
            "has_phone": bool((person or {}).get("phone")),
            "has_email": bool((person or {}).get("email")),
            "detail": detail,
        })

    out.sort(key=lambda r: r["first_visit_at"])
    return out[:max(1, int(limit))]


# ─── groups ──────────────────────────────────────────────────────────

# A member has drifted when their group met this many times in a row
# without them. Three is about a month for a weekly group: long enough
# not to flag a holiday, short enough that a call still lands.
DRIFT_MISSED = 3
GROUP_WINDOW_WEEKS = 12
_CHUNK = 100


def _chunks(ids: List[str]) -> List[List[str]]:
    ids = sorted({str(i) for i in ids if i})
    return [ids[i:i + _CHUNK] for i in range(0, len(ids), _CHUNK)]


def _get_in(path: str, column: str, ids: List[str]) -> Optional[List[Dict[str, Any]]]:
    """`path` + `&<column>=in.(...)`, in chunks short enough for a URL."""
    out: List[Dict[str, Any]] = []
    for chunk in _chunks(ids):
        rows = _get(f"{path}&{column}=in.({','.join(chunk)})")
        if rows is None:
            return None
        out += rows
    return out


def _names(biz: str, contact_ids: List[str]) -> Optional[Dict[str, str]]:
    if not contact_ids:
        return {}
    rows = _get_in(f"/contacts?business_id=eq.{biz}&select=id,name", "id", contact_ids)
    if rows is None:
        return None
    return {str(r["id"]): " ".join(str(r.get("name") or "").split()) or "Someone"
            for r in rows if r.get("id")}


def group_drift(business_id: str, *, missed: int = DRIFT_MISSED,
                now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Each active group's last few weeks, and who has stopped coming.

    Drifting = in the group since before its last `missed` meetings and at
    none of them. A group that has met fewer times than that in the window
    says nothing about anyone yet, so it flags nobody.

        {"groups": [{id, name, members, meetings, last_met, average}],
         "drifting": [{contact_id, name, group, last_came, missed}]}
    """
    now = now or datetime.now(timezone.utc)
    biz = str(business_id)
    since = (now - timedelta(weeks=GROUP_WINDOW_WEEKS)).date().isoformat()

    groups = _get(f"/groups?business_id=eq.{biz}&active=is.true"
                  "&select=id,name&order=name.asc&limit=200")
    if groups is None:
        return None
    if not groups:
        return {"groups": [], "drifting": []}
    members = _get(f"/group_members?business_id=eq.{biz}"
                   "&select=group_id,contact_id,joined_on&limit=10000")
    meetings = _get(f"/group_meetings?business_id=eq.{biz}&met_on=gte.{since}"
                    "&select=id,group_id,met_on&order=met_on.desc&limit=2000")
    if members is None or meetings is None:
        return None
    present = _get_in(f"/group_meeting_attendance?business_id=eq.{biz}"
                      "&select=meeting_id,contact_id", "meeting_id",
                      [m["id"] for m in meetings])
    if present is None:
        return None

    came: Dict[str, set] = {}
    for p in present:
        came.setdefault(str(p.get("meeting_id")), set()).add(str(p.get("contact_id")))

    out_groups: List[Dict[str, Any]] = []
    drifting: List[Dict[str, Any]] = []
    for g in groups:
        gid = str(g["id"])
        roster = [m for m in members if str(m.get("group_id")) == gid]
        met = [m for m in meetings if str(m.get("group_id")) == gid]  # newest first
        recent = met[:4]
        average = (round(sum(len(came.get(str(m["id"]), ())) for m in recent) / len(recent), 1)
                   if recent else None)
        out_groups.append({"id": gid, "name": g.get("name") or "A group",
                           "members": len(roster), "meetings": len(met),
                           "last_met": met[0]["met_on"] if met else None,
                           "average": average})
        if len(met) < missed:
            continue
        last = met[:missed]
        oldest = str(last[-1]["met_on"])
        for m in roster:
            cid = str(m.get("contact_id"))
            if str(m.get("joined_on") or "") >= oldest:
                continue  # joined during the run; not drifting yet
            if any(cid in came.get(str(x["id"]), ()) for x in last):
                continue
            last_came = next((x["met_on"] for x in met if cid in came.get(str(x["id"]), ())), None)
            drifting.append({"contact_id": cid, "group": g.get("name") or "A group",
                             "last_came": last_came, "missed": missed})

    names = _names(biz, [d["contact_id"] for d in drifting])
    if names is None:
        return None
    for d in drifting:
        d["name"] = names.get(d["contact_id"], "Someone")
    drifting.sort(key=lambda d: (d["last_came"] or "", d["name"]))
    return {"groups": out_groups, "drifting": drifting}


# ─── services ────────────────────────────────────────────────────────

SERVICE_WINDOW_WEEKS = 8


def services(business_id: str, *, weeks: int = SERVICE_WINDOW_WEEKS,
             now: Optional[datetime] = None) -> Optional[List[Dict[str, Any]]]:
    """Who came to each recent service or event, newest first.

    Named check-ins split in person / online ("I'm here" from the live
    page checks a member in as online), first-timers among them, and the
    headcounts the team counted by area (the people nobody checks in by
    name). Children are NOT here: their check-in is care-level data.

        [{entry_id, title, date, in_person, online, first_time,
          headcount, areas: {area: count}}]
    """
    now = now or datetime.now(timezone.utc)
    biz = str(business_id)
    cutoff = _iso(now - timedelta(weeks=max(1, int(weeks))))
    rows = _get(f"/attendance?business_id=eq.{biz}&checked_in_at=gte.{cutoff}"
                "&select=entry_id,method,first_time,checked_in_at&limit=20000")
    counts = _get(f"/attendance_headcounts?business_id=eq.{biz}&updated_at=gte.{cutoff}"
                  "&select=entry_id,area,count,updated_at&limit=2000")
    if rows is None or counts is None:
        return None
    by: Dict[str, Dict[str, Any]] = {}

    def slot(entry_id: str, at: Optional[datetime]) -> Dict[str, Any]:
        s = by.setdefault(entry_id, {"entry_id": entry_id, "in_person": 0, "online": 0,
                                     "first_time": 0, "headcount": 0, "areas": {},
                                     "_at": at})
        if at and (s["_at"] is None or at < s["_at"]):
            s["_at"] = at
        return s

    for r in rows:
        s = slot(str(r.get("entry_id")), _parse(r.get("checked_in_at")))
        s["online" if r.get("method") == "online" else "in_person"] += 1
        if r.get("first_time"):
            s["first_time"] += 1
    for c in counts:
        s = slot(str(c.get("entry_id")), _parse(c.get("updated_at")))
        n = int(c.get("count") or 0)
        s["areas"][str(c.get("area") or "Counted")] = n
        s["headcount"] += n
    if not by:
        return []
    entries = _get_in(f"/module_entries?business_id=eq.{biz}&select=id,data", "id", list(by))
    titles = {str(e.get("id")): _occasion_title(e) for e in (entries or [])}
    out = []
    for s in by.values():
        at = s.pop("_at")
        s["title"] = titles.get(s["entry_id"], "a service")
        s["date"] = at.date().isoformat() if at else None
        out.append(s)
    out.sort(key=lambda s: s["date"] or "", reverse=True)
    return out


# ─── care and children (counts only) ─────────────────────────────────

def care_counts(business_id: str, *, now: Optional[datetime] = None
                ) -> Optional[Dict[str, Any]]:
    """The Prayer & care inbox and children's check-in as NUMBERS.

    Never a request's words, a requester's name or a child's name: this
    feeds Chief, and Chief writes drafts. The caller decides who may see
    even this much (owner or manager).
    """
    now = now or datetime.now(timezone.utc)
    biz = str(business_id)
    reqs = _get(f"/ministry_care_requests?business_id=eq.{biz}"
                f"&created_at=gte.{_iso(now - timedelta(days=90))}"
                "&select=status,created_at,prayed_at&limit=5000")
    kids = _get(f"/child_checkins?business_id=eq.{biz}"
                f"&checked_in_at=gte.{_iso(now - timedelta(weeks=SERVICE_WINDOW_WEEKS))}"
                "&select=entry_id,checked_in_at&limit=20000")
    if reqs is None or kids is None:
        return None
    by_status = {"new": 0, "reviewed": 0, "closed": 0}
    oldest_new: Optional[datetime] = None
    prayed = 0
    for r in reqs:
        st = str(r.get("status") or "new")
        by_status[st] = by_status.get(st, 0) + 1
        if r.get("prayed_at"):
            prayed += 1
        at = _parse(r.get("created_at"))
        if st == "new" and at and (oldest_new is None or at < oldest_new):
            oldest_new = at
    per_day: Dict[str, int] = {}
    for k in kids:
        at = _parse(k.get("checked_in_at"))
        if at:
            per_day[at.date().isoformat()] = per_day.get(at.date().isoformat(), 0) + 1
    return {
        "care": {**by_status, "prayed": prayed,
                 "oldest_new_days": (now - oldest_new).days if oldest_new else None},
        "children_checked_in": [{"date": d, "children": n}
                                for d, n in sorted(per_day.items(), reverse=True)],
    }
