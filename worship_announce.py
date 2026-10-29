# worship_announce.py — the announcements board (ChurchSavvy round 5,
# canvas UZu4VsoY9KemkUGorz234j boards 18-21; Kevin 2026-10-26: "these are a
# go. build it").
#
# An announcement is made once and shows where it belongs until it's over:
# the days it shows (`show_from`..`show_until`; it retires itself the day
# after), the screens it shows on (room, lobby, online, phones), one of six
# designs in the church's own look, and a QR code. A ministry's request
# waits for the office. Sunday's announcement spot and the welcome loop
# fill themselves from what is showing on the service's day
# (worship_show.compile_item `board`).
#
# Pure: no reads, no writes. worship_announce_router.py does those.
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

DESIGNS = ("side", "flyer", "date", "card", "week", "save")
QR_KINDS = ("none", "form", "link", "give", "map")
QR_LABELS = {"form": "Scan to sign up", "link": "Scan for details", "give": "Scan to give", "map": "Scan for directions"}
WHERE = ("room", "lobby", "online", "phones")
STATUSES = ("on", "waiting", "declined")
SOURCES = ("typed", "calendar", "ministry")
TABS = ("now", "soon", "wait", "past")
MAX_PER_CHURCH = 300
WEEK_LIST = 5
_HTTPS = re.compile(r"^https://[^\s\"'<>]{3,590}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _text(raw: Dict[str, Any], key: str, limit: int, label: str) -> str:
    v = raw.get(key)
    if v is None:
        return ""
    if not isinstance(v, str):
        raise ValueError(f"{label} should be words")
    v = " ".join(v.split()) if key != "body" else v.strip()
    if len(v) > limit:
        raise ValueError(f"{label} is at most {limit} letters")
    return v


def day_of(v: Any, label: str) -> Optional[date]:
    """A YYYY-MM-DD day, or None when empty. Raises with words a person can act on."""
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not _DAY.match(v):
        raise ValueError(f"{label} needs a date")
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise ValueError(f"{label} needs a real date")


def clean(raw: Any, partial: bool = False) -> Dict[str, Any]:
    """One announcement, checked: the columns to write. `partial` checks only what's there."""
    if not isinstance(raw, dict):
        raise ValueError("Nothing to save")
    out: Dict[str, Any] = {}

    def has(k: str) -> bool:
        return not partial or k in raw

    if has("title"):
        out["title"] = _text(raw, "title", 80, "The title")
        if not out["title"]:
            raise ValueError("Give the announcement a title")
    if has("when"):
        out["when_text"] = _text(raw, "when", 80, "When it happens")
    if has("where"):
        out["where_text"] = _text(raw, "where", 80, "Where it happens")
    if has("body"):
        out["body"] = _text(raw, "body", 140, "A few words")
    if has("image_url"):
        url = raw.get("image_url") or ""
        if url and (not isinstance(url, str) or not _HTTPS.match(url)):
            raise ValueError("The picture must be an https:// link")
        out["image_url"] = url
    if has("design"):
        d = raw.get("design") or "side"
        if d not in DESIGNS:
            raise ValueError("That isn't one of the designs")
        out["design"] = d
    if has("event_on"):
        ev = day_of(raw.get("event_on"), "The day it happens")
        out["event_on"] = ev.isoformat() if ev else None
    if has("qr"):
        out["qr"] = clean_qr(raw.get("qr"))
    if has("show_from"):
        f = day_of(raw.get("show_from"), "Show it from")
        out["show_from"] = f.isoformat() if f else None
    if has("show_until"):
        u = day_of(raw.get("show_until"), "Show it until")
        out["show_until"] = u.isoformat() if u else None
    f, u = out.get("show_from"), out.get("show_until")
    if f and u and f > u:
        raise ValueError("It can't stop showing before it starts")
    if has("shows"):
        s = raw.get("shows")
        if not isinstance(s, dict):
            raise ValueError("Pick where it shows")
        out["shows"] = {k: bool(s.get(k)) for k in WHERE}
    if has("sort"):
        n = raw.get("sort") or 0
        if not isinstance(n, int) or not 0 <= n <= 10000:
            raise ValueError("That isn't a place in the order")
        out["sort"] = n
    return out


def clean_qr(raw: Any) -> Dict[str, Any]:
    if raw in (None, {}, ""):
        return {}
    if not isinstance(raw, dict):
        raise ValueError("That isn't a QR code")
    kind = raw.get("kind") or "none"
    if kind not in QR_KINDS:
        raise ValueError("A QR code opens a form, a link, giving or directions")
    if kind == "none":
        return {}
    url = raw.get("url") or ""
    if not isinstance(url, str) or not _HTTPS.match(url):
        raise ValueError("The QR code needs an https:// address to open")
    label = _text(raw, "label", 60, "The words beside the QR code") or QR_LABELS[kind]
    return {"kind": kind, "url": url, "label": label}


def state(row: Dict[str, Any], day: date) -> str:
    """Which tab an announcement is in on `day`: now, soon, wait, past (or declined)."""
    if row.get("status") == "waiting":
        return "wait"
    if row.get("status") == "declined":
        return "declined"
    f = day_of(row.get("show_from"), "Show it from")
    u = day_of(row.get("show_until"), "Show it until")
    if u and day > u:
        return "past"
    if f and day < f:
        return "soon"
    return "now"


def _order_key(row: Dict[str, Any]):
    ev = row.get("event_on") or "9999-12-31"
    return (ev, row.get("sort") or 0, row.get("created_at") or "")


def ordered(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Nearest event first; an announcement with no day goes after the dated ones."""
    return sorted(rows, key=_order_key)


def showing(rows: List[Dict[str, Any]], day: date, where: str) -> List[Dict[str, Any]]:
    """What shows on `day` on one kind of screen, in order."""
    return ordered([r for r in rows if not r.get("archived_at") and state(r, day) == "now"
                    and bool((r.get("shows") or {}).get(where))])


def kicker(event_on: Optional[str], day: date) -> str:
    """'This Saturday', 'Tomorrow'… from the screen's day to the event's; '' when it's far or past."""
    ev = day_of(event_on, "The day it happens") if event_on else None
    if not ev:
        return ""
    gap = (ev - day).days
    if gap < 0:
        return ""
    if gap == 0:
        return "Today"
    if gap == 1:
        return "Tomorrow"
    name = _WEEKDAYS[ev.weekday()]
    # A church's week starts on Sunday: on Sunday, the coming Saturday is "This Saturday".
    sun = lambda d: (d.weekday() + 1) % 7  # noqa: E731
    if gap < 7 and sun(ev) > sun(day):
        return f"This {name}"
    if gap < 14:
        return f"Next {name}"
    return ""


def _short_day(ev: date) -> str:
    return f"{_WEEKDAYS[ev.weekday()][:3]} {ev.day}"


def slide(row: Dict[str, Any], day: date, board: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """One announcement as a slide the screens draw (ShowSlideView's announcement)."""
    ev = day_of(row.get("event_on"), "The day it happens") if row.get("event_on") else None
    design = row.get("design") or "side"
    if design == "date" and not ev:
        design = "side"
    out: Dict[str, Any] = {
        "kind": "announcement", "id": row.get("id") or "", "title": row.get("title") or "",
        "when": row.get("when_text") or "", "where": row.get("where_text") or "",
        "body": row.get("body") or "", "image_url": row.get("image_url") or "", "link": "",
        "design": design, "kick": kicker(row.get("event_on"), day),
        "day": str(ev.day) if ev else "", "month": _MONTHS[ev.month - 1] if ev else "",
        "qr": row.get("qr") or None,
    }
    if design in ("flyer", "card") and not out["image_url"]:
        out["design"] = "save" if design == "card" else "side"
    if design == "week":
        # This week, as a list: the nearest few on the board (this one among them).
        near = [r for r in (board or [row]) if r.get("event_on")][:WEEK_LIST]
        out["list"] = [{"day": _short_day(date.fromisoformat(r["event_on"])), "title": r.get("title") or "",
                        "when": r.get("when_text") or ""} for r in near]
    return out


def as_out(row: Dict[str, Any], day: date) -> Dict[str, Any]:
    """An announcement for the board: what the editor shows, and its tab today."""
    return {
        "id": row.get("id"), "title": row.get("title") or "", "when": row.get("when_text") or "",
        "where": row.get("where_text") or "", "body": row.get("body") or "", "image_url": row.get("image_url") or "",
        "design": row.get("design") or "side", "event_on": row.get("event_on"), "qr": row.get("qr") or {},
        "show_from": row.get("show_from"), "show_until": row.get("show_until"),
        "shows": {k: bool((row.get("shows") or {}).get(k)) for k in WHERE},
        "status": row.get("status") or "on", "source": row.get("source") or "typed",
        "sent_by": row.get("sent_by") or {}, "sort": row.get("sort") or 0,
        "created_at": row.get("created_at"), "updated_at": row.get("updated_at"),
        "tab": state(row, day),
    }


def until_default(event_on: Optional[str]) -> Optional[str]:
    """Shows until the day it happens, when nobody said otherwise."""
    return event_on or None


def past_cutoff(day: date) -> str:
    """The Past tab keeps a year."""
    return (day - timedelta(days=366)).isoformat()
