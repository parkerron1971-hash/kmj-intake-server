"""Class nights after they end (Kevin 2026-10-18, asked whether online class
nights count toward a church's attendance: "Count class nights").

Within ten minutes of a live class ending:

  * at a church, the night becomes its own occasion in Services & Events
    (private: never on the public events page or a member's own) and
    everyone who came is checked in to it: online (they were in the live
    room), or in the room (they tapped "I'm in the room", or the teacher
    marked them). A class never makes anyone a first-time visitor, and a
    class night is never a Sunday to the drifting rule
    (church_shepherd_signals).
  * for any kind of business, when the teacher asked ("Send tonight's
    slides to who wasn't here"), each active student who didn't come gets
    an email with the way into their class, where the slides and the
    lesson are.

Each night is counted once: academy_live_count_night marks it in the same
statement that checks people in (APPLY-2026-10-18-academy-class-nights.sql).
Its emails go out once: academy_live_missed_claim marks them before a word
goes out, and academy_live_missed_release un-marks them when every email
failed, the idempotency keys keeping a retry from reaching anyone twice.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import sb_clients

logger = logging.getLogger(__name__)

LOOK_BACK = timedelta(days=3)       # a night that ended longer ago is left as it is
SEND_WITHIN = timedelta(days=14)    # the teacher can still ask from Course Studio
BATCH = 50
SESSION_FIELDS = ("id,course_id,title,starts_at,started_at,ended_at,send_missed,missed_sent_at,counted_at,"
                  "academy_lessons(title),academy_courses!inner(title,business_id)")


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(v: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def night_name(n: Dict[str, Any]) -> str:
    """'Week 1 · New Life & Identity': the night's own title and its lesson,
    once each."""
    lesson = (n.get("academy_lessons") or {}).get("title") if isinstance(n.get("academy_lessons"), dict) else None
    parts: List[str] = []
    for x in (n.get("title"), lesson):
        x = " ".join(str(x or "").split())
        if x and x.casefold() not in {p.casefold() for p in parts}:
            parts.append(x)
    return " · ".join(parts)


def occasion_title(course_title: str, night: str) -> str:
    """What Services & Events lists: 'The Making: Foundation · Week 1'."""
    return " · ".join(x for x in (course_title.strip(), night) if x)[:120] or "Class night"


def missed_email(course_title: str, night: str, first: str) -> Tuple[str, str, str]:
    """(subject, message, preheader). Plain words; the button opens the class."""
    what = f"{course_title}: {night}" if night else course_title
    subject = f"The slides from {what}"
    lead = f"We missed you at {what}."
    message = ((f"Hi {first},\n\n" if first else "Hi,\n\n") + f"{lead} The slides and the lesson are in your class, "
               "so you can catch up whenever you're ready. See you at the next one.")
    return subject[:200], message, f"{lead} The slides are in your class."


def _sessions(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


async def sweep_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Every ten minutes (kmj_intake_automation, leader only)."""
    now = now or datetime.now(timezone.utc)
    out = {"nights": 0, "counted": 0, "emails": 0}
    to_count = await asyncio.to_thread(
        _sessions, f"/academy_live_sessions?status=eq.ended&counted_at=is.null&ended_at=gt.{_iso(now - LOOK_BACK)}"
                   f"&select={SESSION_FIELDS}&order=ended_at.asc&limit={BATCH}")
    to_send = await asyncio.to_thread(
        _sessions, f"/academy_live_sessions?status=eq.ended&send_missed=is.true&missed_sent_at=is.null"
                   f"&ended_at=gt.{_iso(now - SEND_WITHIN)}&select={SESSION_FIELDS}&order=ended_at.asc&limit={BATCH}")
    nights: Dict[str, Dict[str, Any]] = {}
    for n in (to_count or []) + (to_send or []):
        nights.setdefault(str(n.get("id")), n)
    if not nights:
        return out
    businesses: Dict[str, Optional[Dict[str, Any]]] = {}
    for n in nights.values():
        biz = str((n.get("academy_courses") or {}).get("business_id") or "")
        if biz not in businesses:
            rows = await asyncio.to_thread(sb_clients.sb_get_as_service,
                                           f"/businesses?id=eq.{_q(biz)}&select=id,name,type,settings,owner_id&limit=1")
            businesses[biz] = rows[0] if isinstance(rows, list) and rows else None
        business = businesses[biz]
        if not business:
            continue  # tried again next tick
        out["nights"] += 1
        if not n.get("counted_at"):
            out["counted"] += await asyncio.to_thread(_count, business, n)
        if n.get("send_missed") and not n.get("missed_sent_at"):
            out["emails"] += await _send_missed(business, n)
    if out["counted"] or out["emails"]:
        logger.info(f"[class-nights] {out}")
    return out


def _count(business: Dict[str, Any], n: Dict[str, Any]) -> int:
    """Mark the night counted; at a church, as its own occasion with who
    came. The number checked in (0 when not a church, or none came)."""
    import church_follow_up
    entry: Optional[str] = None
    if church_follow_up.is_church(business):
        ok, entry = _occasion(business, n)
        if not ok:
            return 0  # an unread room or clock: tried again next tick
    got = sb_clients.sb_post_as_service("/rpc/academy_live_count_night", {"p_session": n["id"], "p_entry": entry})
    return int(got.get("counted") or 0) if isinstance(got, dict) else 0


def _occasion(business: Dict[str, Any], n: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """(read ok, the night's occasion id). The occasion is made once in the
    church's Services & Events (the room Sunday check-in uses), private, on
    the business's own clock. (True, None): the church has no such room, so
    there is nothing to count into."""
    import academy_reminders
    import church_checkin
    from events_rsvp_router import resolve_fields
    from zoneinfo import ZoneInfo
    b, sid = str(business["id"]), str(n["id"])
    path = f"/module_entries?business_id=eq.{_q(b)}&data->>_class_session=eq.{_q(sid)}&select=id&limit=1"
    found = sb_clients.sb_get_as_service(path)
    if not isinstance(found, list):
        return False, None
    if found:
        return True, str(found[0]["id"])
    mods = church_checkin._roster(b)
    if mods is None:
        return False, None
    if not mods:
        return True, None
    tz = academy_reminders._zone(business)
    when = _parse(n.get("started_at") or n.get("starts_at"))
    if not tz or not when:
        return False, None
    mod = next((m for m in mods if "service" in str(m.get("name") or "").lower()), mods[0])
    f = resolve_fields(mod.get("archetype_params"))
    course = str((n.get("academy_courses") or {}).get("title") or "")
    data = {
        f["title_field"]: occasion_title(course, night_name(n)),
        f["date_field"]: when.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%dT%H:%M"),
        "type": "class",
        f["location_field"]: "",
        f["signups_field"]: [],
        # A class night is the church's own record, never on the public page.
        "_visibility": "private",
        "notes": "A class night. Who came is counted in its attendance.",
        "_class_session": sid,
    }
    made = sb_clients.sb_post_as_service("/module_entries", {
        "business_id": b, "module_id": str(mod["id"]), "data": data, "status": "active", "created_by": "class_night"})
    if isinstance(made, list) and made:
        return True, str(made[0]["id"])
    # Made by another worker first (the unique index): read it back.
    again = sb_clients.sb_get_as_service(path)
    return (True, str(again[0]["id"])) if isinstance(again, list) and again else (False, None)


async def _send_missed(business: Dict[str, Any], n: Dict[str, Any]) -> int:
    claimed = await asyncio.to_thread(sb_clients.sb_post_as_service, "/rpc/academy_live_missed_claim",
                                      {"p_session": n["id"]})
    if not isinstance(claimed, dict) or not isinstance(claimed.get("students"), list):
        return 0  # already sent, no longer asked for, or the call failed
    course = str((n.get("academy_courses") or {}).get("title") or "your class")
    night = night_name(n)
    sent = failed = 0
    for s in claimed["students"]:
        try:
            if await _email(business, course, night, s, str(n["id"])):
                sent += 1
        except Exception as e:  # noqa: BLE001
            failed += 1
            logger.warning(f"[class-nights] email failed: {type(e).__name__}")
    if failed and not sent:
        await asyncio.to_thread(sb_clients.sb_post_as_service, "/rpc/academy_live_missed_release", {"p_session": n["id"]})
    return sent


async def _email(business: Dict[str, Any], course_title: str, night: str, student: Dict[str, Any],
                 session_id: str) -> bool:
    import academy_join
    import email_layout
    import email_sender
    email = str(student.get("email") or "").strip()
    if not academy_join.valid_email(email) or not student.get("token"):
        return False
    settings = business.get("settings") if isinstance(business.get("settings"), dict) else {}
    biz_name = (business.get("name") or "").strip() or "Your class"
    first = str(student.get("name") or "").strip().split(" ")[0]
    subject, message, preheader = missed_email(course_title, night, first)
    link = f"{academy_join.CLASSROOM_BASE}/classroom/{student['token']}"
    html = email_layout.render_html(
        message, business_name=biz_name, brand=email_layout.brand_of(settings),
        sig=email_layout.signature_of(settings), unsubscribe_url=email_sender._unsubscribe_url(email),
        preheader=preheader, cta=("Open your class", link),
        disclaimer=f"You’re getting this because you’re in {course_title} with {biz_name}.")
    await email_sender.send_via_resend(
        to_email=email, to_name=student.get("name") or None,
        from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
        from_name=biz_name, subject=subject, body=html, reply_to=None, business_id=str(business["id"]),
        idempotency_key=f"class-missed-{session_id}-{student.get('enrollment_id')}")
    return True
