"""A class on the student's own calendar (step 2 of the Class Schedule).

GET /academy-calendar/<class link>.ics: every live class, homework due date
and gathering of the student's class, as a calendar their phone subscribes
to (webcal://) or imports once. The class link is the key, the same link
that opens their classroom; a link that isn't active is a bare 404. It is
built fresh on each read, so a class that moves, moves on their phone too.

The two reads are the classroom's own (academy_student_live and
academy_classroom_schedule), so the calendar never shows what the
classroom wouldn't: a draft item, or the details of a week not open yet.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

logger = logging.getLogger(__name__)
router = APIRouter()

CLASSROOM_BASE = "https://system.mysolutionist.app"
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _esc(text: Any) -> str:
    """RFC 5545 TEXT escaping."""
    s = str(text or "")
    return (s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
             .replace("\r\n", "\\n").replace("\n", "\\n"))


def _when(value: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _stamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fold(line: str) -> str:
    """Lines longer than 75 octets continue on the next line after a space."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts: List[str] = []
    while raw:
        cut = min(len(raw), 75 if not parts else 74)
        while cut < len(raw) and (raw[cut] & 0xC0) == 0x80:  # never split a character
            cut -= 1
        parts.append(raw[:cut].decode("utf-8"))
        raw = raw[cut:]
    return "\r\n ".join(parts)


def _event(uid: str, start: datetime, end: datetime, summary: str, now: datetime,
           description: str = "", location: str = "", url: str = "") -> List[str]:
    lines = ["BEGIN:VEVENT", f"UID:{uid}@mysolutionist.app", f"DTSTAMP:{_stamp(now)}",
             f"DTSTART:{_stamp(start)}", f"DTEND:{_stamp(end)}", f"SUMMARY:{_esc(summary)}"]
    if description:
        lines.append(f"DESCRIPTION:{_esc(description)}")
    if location:
        lines.append(f"LOCATION:{_esc(location)}")
    if url:
        lines.append(f"URL:{url}")
    lines.append("END:VEVENT")
    return lines


def build_ics(title: str, token: str, sessions: List[Dict[str, Any]], items: List[Dict[str, Any]],
              now: Optional[datetime] = None) -> str:
    """The calendar text: live classes, homework due dates, gatherings."""
    now = now or datetime.now(timezone.utc)
    link = f"{CLASSROOM_BASE}/classroom/{token}"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//The Solutionist System//Classes//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_esc(title)}",
             "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"]
    for s in sessions:
        start = _when(s.get("starts_at"))
        if not start or s.get("status") not in ("scheduled", "live"):
            continue
        minutes = int(s.get("duration_minutes") or 60)
        lines += _event(f"live-{s.get('id')}", start, start + timedelta(minutes=max(15, minutes)),
                        s.get("title") or f"{title}: class", now,
                        description=f"Join from your classroom: {link}", url=link)
    for it in items:
        if it.get("kind") == "gathering":
            start = _when(it.get("starts_at"))
            if not start:
                continue
            lines += _event(f"gathering-{it.get('id')}", start, start + timedelta(hours=2), it.get("title") or "Gathering",
                            now, description=it.get("details") or "", location=it.get("place") or "", url=link)
        else:
            due = _when(it.get("due_at"))
            if not due:
                continue
            lines += _event(f"due-{it.get('id')}", due - timedelta(minutes=30), due, f"Due: {it.get('title') or 'Homework'}",
                            now, description=(it.get("details") or "") + ("\n\n" if it.get("details") else "") + link, url=link)
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def _load(token: str) -> Optional[Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]]:
    """(class title, live classes, schedule items) for an active class link, else None."""
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/academy_enrollments?portal_token=eq.{token}&status=in.(active,completed)&limit=1"
        f"&select=academy_courses(title,status)", redact=True) or []
    course = (rows[0].get("academy_courses") or {}) if rows else {}
    if course.get("status") != "published":
        return None
    sessions = sb_clients.sb_post_as_service("/rpc/academy_student_live", {"p_token": token}, redact=True)
    schedule = sb_clients.sb_post_as_service("/rpc/academy_classroom_schedule", {"p_token": token}, redact=True)
    if sessions is None or schedule is None:
        return None
    return course.get("title") or "My class", list(sessions or []), list((schedule or {}).get("items") or [])


@router.get("/academy-calendar/{token}.ics", include_in_schema=False)
def class_calendar(token: str) -> Response:
    if not _UUID.match(token or ""):
        raise HTTPException(404, "Not found")
    loaded = _load(token)
    if not loaded:
        raise HTTPException(404, "Not found")
    title, sessions, items = loaded
    return Response(build_ics(title, token, sessions, items), media_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "no-store", "Content-Disposition": 'inline; filename="class.ics"',
                             "Referrer-Policy": "no-referrer"})
