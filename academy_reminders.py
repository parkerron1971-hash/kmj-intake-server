"""Class-night reminders (phase 5 of the approved "Class Experience" design;
Kevin 2026-10-17: reminders, and member notifications, yes).

A few hours before each live class, every active student in it hears:

  * by email, from the business, with the button into their classroom
    (any kind of business: a coach's live class as much as a church's);
  * in a church's member app, as its "Class nights" notification, when the
    church has that kind on and the member allowed notifications
    (member_push; the church's switch, the member's choice).

A class that starts before 10 AM (the business's own clock) is told the
evening before instead, never at dawn. A class starting in under half an
hour isn't told at all: a reminder that late is noise.

Each night is reminded once: academy_live_reminder_claim marks it before a
word goes out (APPLY-2026-10-18-academy-class-reminders.sql). A class whose
owner turned reminders off in Course setup (academy_courses.remind_live) is
never reminded; nor a draft or archived class, a cancelled night, or a
student who was taken off the class.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import sb_clients

logger = logging.getLogger(__name__)

AHEAD = timedelta(hours=3)          # remind within the three hours before
TOO_LATE = timedelta(minutes=30)    # under half an hour away: say nothing
MORNING_BEFORE = 10                 # a class before 10 AM is told the evening before
EVENING = range(17, 21)             # 5 PM to 8:59 PM
LOOK_AHEAD = timedelta(hours=20)    # how far ahead the sweep looks
BATCH = 100


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clock(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    return f"{hour}{f':{dt.minute:02d}' if dt.minute else ''} {'AM' if dt.hour < 12 else 'PM'}"


def due(starts: datetime, now: datetime, tz: str) -> Optional[str]:
    """When it's time to remind, the words for when the class is ('tonight
    at 6 PM', 'today at 1 PM', 'tomorrow at 9 AM'); otherwise None."""
    from zoneinfo import ZoneInfo
    try:
        zone = ZoneInfo(tz or "UTC")
    except Exception:  # noqa: BLE001
        zone = ZoneInfo("UTC")
    start, here = starts.astimezone(zone), now.astimezone(zone)
    left = starts - now
    if left <= TOO_LATE:
        return None
    if start.hour < MORNING_BEFORE:
        if start.date() - here.date() == timedelta(days=1) and here.hour in EVENING:
            return f"tomorrow at {_clock(start)}"
        if start.date() == here.date() and left <= AHEAD and here.hour >= 7:
            return f"today at {_clock(start)}"
        return None
    if left > AHEAD or start.date() != here.date():
        return None
    return f"{'tonight' if start.hour >= 17 else 'today'} at {_clock(start)}"


def reminder_email(biz_name: str, course_title: str, night: str, when: str, first: str) -> Tuple[str, str, str]:
    """(subject, message, preheader). Plain words; the button opens the class."""
    what = f"{course_title}: {night}" if night and night != course_title else course_title
    subject = f"{when[0].upper()}{when[1:]}: {course_title}"
    lead = f"Your class meets {when}."
    message = ((f"Hi {first},\n\n" if first else "Hi,\n\n") + f"{lead} {what}.\n\n"
               f"When it's time, open your class and press Join to be there online. See you soon.")
    return subject, message, f"{lead} {what}."


def _due_nights(now: datetime) -> Optional[List[Dict[str, Any]]]:
    return sb_clients.sb_get_as_service(
        "/academy_live_sessions?status=eq.scheduled&reminded_at=is.null"
        f"&starts_at=gt.{_iso(now + TOO_LATE)}&starts_at=lt.{_iso(now + LOOK_AHEAD)}"
        "&select=id,course_id,title,starts_at,teacher_name,academy_lessons(title),"
        "academy_courses!inner(title,business_id,status,remind_live)"
        "&academy_courses.status=eq.published&academy_courses.remind_live=is.true"
        f"&order=starts_at.asc&limit={BATCH}")


async def sweep_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Every 15 minutes (kmj_intake_automation, leader only)."""
    now = now or datetime.now(timezone.utc)
    out = {"nights": 0, "emails": 0, "phones": 0}
    nights = await asyncio.to_thread(_due_nights, now)
    if not nights:
        return out
    businesses: Dict[str, Optional[Dict[str, Any]]] = {}
    zones: Dict[str, Optional[str]] = {}
    for n in nights:
        course = n.get("academy_courses") or {}
        biz = str(course.get("business_id") or "")
        try:
            starts = datetime.fromisoformat(str(n["starts_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        # The business and its clock before anything is claimed: a night is
        # never marked reminded on a guessed clock or with nobody told; it is
        # simply tried again next tick.
        if biz not in businesses:
            rows = await asyncio.to_thread(sb_clients.sb_get_as_service,
                                           f"/businesses?id=eq.{biz}&select=id,name,type,settings,owner_id&limit=1")
            businesses[biz] = rows[0] if rows else None
            zones[biz] = await asyncio.to_thread(_zone, businesses[biz]) if businesses[biz] else None
        business, tz = businesses[biz], zones[biz]
        if not business or not tz:
            continue
        when = due(starts, now, tz)
        if not when:
            continue
        claimed = await asyncio.to_thread(sb_clients.sb_post_as_service, "/rpc/academy_live_reminder_claim",
                                          {"p_session": n["id"]})
        if not isinstance(claimed, dict) or not isinstance(claimed.get("students"), list):
            continue  # someone else claimed it, it no longer qualifies, or the call failed
        out["nights"] += 1
        lesson = (n.get("academy_lessons") or {}).get("title") if isinstance(n.get("academy_lessons"), dict) else None
        night = " · ".join(x for x in (n.get("title"), lesson) if x)
        students = claimed["students"]
        sent = failed = 0
        for s in students:
            try:
                if await _email(business, str(course.get("title") or "your class"), night, when, s, str(n["id"])):
                    sent += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                logger.warning(f"[class-reminders] email failed: {type(e).__name__}")
        out["emails"] += sent
        if failed and not sent:
            # A send outage (every email failed): un-mark the night so the
            # next tick tries again. The idempotency keys keep a retry from
            # reaching anyone twice; the push has its own once-only key.
            await asyncio.to_thread(sb_clients.sb_post_as_service, "/rpc/academy_live_reminder_release",
                                    {"p_session": n["id"]})
            out["released"] = out.get("released", 0) + 1
        out["phones"] += await asyncio.to_thread(_push, business, str(course.get("title") or "Class"), night, when,
                                                 students, str(n["id"]))
    if out["nights"]:
        logger.info(f"[class-reminders] {out}")
    return out


def _zone(business: Dict[str, Any]) -> Optional[str]:
    """The business's clock, by outside_calendar.business_timezone's chain
    (availability, then the owner's profile, then the platform's), but
    strict: a failed read is None, never a fallback clock."""
    try:
        from availability import BusinessAvailability
        from availability_engine import resolved_tz_name
        av = BusinessAvailability.from_settings_dict(((business.get("settings") or {}) if isinstance(
            business.get("settings"), dict) else {}).get("availability"))
        practitioner_tz = None
        if business.get("owner_id"):
            prof = sb_clients.sb_get_as_service(
                f"/practitioner_profiles?owner_id=eq.{business['owner_id']}&select=timezone&limit=1")
            if prof is None:
                return None
            practitioner_tz = ((prof[0].get("timezone") or "").strip() or None) if prof else None
        return resolved_tz_name(av, practitioner_tz)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[class-reminders] clock unread: {type(e).__name__}")
        return None


async def _email(business: Dict[str, Any], course_title: str, night: str, when: str,
                 student: Dict[str, Any], session_id: str) -> bool:
    import academy_join
    import email_layout
    import email_sender
    email = str(student.get("email") or "").strip()
    if not academy_join.valid_email(email) or not student.get("token"):
        return False
    settings = business.get("settings") if isinstance(business.get("settings"), dict) else {}
    biz_name = (business.get("name") or "").strip() or "Your class"
    first = str(student.get("name") or "").strip().split(" ")[0]
    subject, message, preheader = reminder_email(biz_name, course_title, night, when, first)
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
        idempotency_key=f"class-reminder-{session_id}-{student.get('enrollment_id')}")
    return True


def _push(business: Dict[str, Any], course_title: str, night: str, when: str,
          students: List[Dict[str, Any]], session_id: str) -> int:
    """The church member app's "Class nights" notification (member_push
    decides: the church's switch, each member's choice, push set up)."""
    import member_push
    ids = [str(s["contact_id"]) for s in students if s.get("contact_id")]
    if not ids:
        return 0
    return member_push.send(business, "classes", title=f"Class {when}"[:member_push.TITLE_MAX],
                            body=" · ".join(x for x in (course_title, night) if x)[:member_push.BODY_MAX],
                            url="/my/classes", contact_ids=ids, ref_id=f"class:{session_id}", tag=f"class-{session_id}")
