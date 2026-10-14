"""
church_reads.py — read-only answers about a church's people.

The church tables (attendance, groups, care, live) are written by their
own routers and by the app directly. This module only READS them, with
the service role and always pinned to one business, so that the Home
desk and Chief can ask the same question and get the same answer.

    first_time_guests(business_id)  who came for the first time and has
                                    not been reached since

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
