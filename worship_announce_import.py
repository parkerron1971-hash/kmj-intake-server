# worship_announce_import.py — "Bring in from the calendar" (ChurchSavvy
# round 5, canvas UZu4VsoY9KemkUGorz234j board 18; idea A4: "Solutionist
# churches add calendar events ... with one tap. ChurchSavvy-only churches
# paste a Google or Outlook calendar link").
#
# Signed in, the plan's part, behind the screens switch:
#   GET    /worship/announcements/import            what's coming on the church's calendars, ready to bring in
#   PUT    /worship/announcements/import/calendar   the calendar's link: it must open; kept, never shown whole
#   DELETE /worship/announcements/import/calendar   forget it
#   POST   /worship/announcements/import            bring in the ones picked: on the board, from the calendar
#
# Two calendars: the church's own events in Solutionist (its event roster's
# public occasions), and a calendar link the church pastes (Google's public
# or secret iCal address, Outlook's published calendar, iCloud), fetched only
# by outside_calendar.fetch_feed (https only, every address checked, pinned,
# 10 seconds and 5 MB). The link is a secret: it lives in worship_calendar,
# is never returned whole (outside_calendar.mask_url), never logged and never
# exported. Each event keeps a key (the announcement's source_ref), so one
# already on the board says so and can't come in twice. A weekly series
# comes in once, as its next date.
from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
import worship_announce as wa
from auth_supabase import AuthedUser, require_user
from worship_show_router import _q, _read, _staff, _uuid

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/worship", tags=["worship"])

WINDOW_DAYS = 60
MAX_ITEMS = 40
MAX_SCANNED = 2000
SHOW_AHEAD_DAYS = 14          # an event brought in starts showing two weeks before it
CALENDAR_FIELDS = "business_id,url,provider,updated_at"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── reading a calendar link (pure but for the fetch) ────────────────


def _short(text: str, limit: int) -> str:
    """A field's words, on one line, kept whole up to `limit`; longer, left out
    (a description too long for a slide is the office's to write)."""
    words = " ".join(str(text or "").split())
    return words if len(words) <= limit else ""


def _cut(text: str, limit: int) -> str:
    """A field's words, on one line, cut at a word to fit `limit` (a long title still comes in)."""
    words = " ".join(str(text or "").split())
    if len(words) <= limit:
        return words
    head = words[:limit - 1].rsplit(" ", 1)[0] if " " in words[:limit - 1] else words[:limit - 1]
    return head.rstrip(" ,;:-") + "…"


def _clock(t: datetime) -> str:
    h = t.hour % 12 or 12
    return f"{h}{'' if not t.minute else ':%02d' % t.minute} {'AM' if t.hour < 12 else 'PM'}"


def events_from_ics(ics: bytes, zone: Any, today: date, window_days: int = WINDOW_DAYS) -> List[Dict[str, Any]]:
    """The calendar's events from today on, each series once (its next date):
    title, the day on the church's clock, its time in words, where, and a few
    words when the description is short enough to show. Cancelled ones are
    left out. Raises outside_calendar.FeedError on a file that isn't a calendar."""
    import icalendar
    import recurring_ical_events
    import outside_calendar as oc
    start = datetime.combine(today, datetime.min.time(), tzinfo=zone)
    end = start + timedelta(days=window_days)
    try:
        cal = icalendar.Calendar.from_ical(ics)
        occurrences = recurring_ical_events.of(cal, skip_bad_series=True).between(start, end)
    except Exception:
        raise oc.FeedError(oc.MSG_UNREADABLE) from None
    seen: Dict[str, Dict[str, Any]] = {}
    for k, ev in enumerate(occurrences):
        if k >= MAX_SCANNED:
            break
        try:
            if str(ev.get("STATUS") or "").upper() == "CANCELLED":
                continue
            title = _cut(str(ev.get("SUMMARY") or ""), 80)
            raw = ev.decoded("DTSTART")
        except Exception:
            continue
        if not title:
            continue
        if isinstance(raw, datetime):
            local = (raw if raw.tzinfo else raw.replace(tzinfo=zone)).astimezone(zone)
            day, when = local.date(), _clock(local)
        else:
            day, when = raw, ""
        if day < today:
            continue
        uid = str(ev.get("UID") or "").strip() or f"{title}|{day.isoformat()}"
        series = "ics:" + hashlib.sha256(uid.encode("utf-8")).hexdigest()[:24]
        if series in seen and seen[series]["event_on"] <= day.isoformat():
            continue
        # The key names the date too: next week's Bible study is its own announcement.
        seen[series] = {"key": f"{series}:{day.isoformat()}", "source": "calendar", "title": title, "event_on": day.isoformat(), "when": when,
                        "where": _cut(str(ev.get("LOCATION") or ""), 80), "body": _short(str(ev.get("DESCRIPTION") or ""), 140)}
    return sorted(seen.values(), key=lambda e: (e["event_on"], e["title"]))[:MAX_ITEMS]


# ─── the church's own events in Solutionist ──────────────────────────


def solutionist_events(biz: str, today: date) -> Optional[List[Dict[str, Any]]]:
    """The church's event roster: its public, dated occasions from today on.
    None when the church keeps no events in Solutionist (ChurchSavvy on its own)."""
    import events_rsvp_router as er
    mods = er.roster_modules_for(biz)
    if not mods:
        return None
    by_mod: Dict[str, List[Dict[str, Any]]] = {}
    for m in mods:
        rows = sb_clients.sb_get_as_service(
            f"/module_entries?module_id=eq.{_q(m['id'])}&business_id=eq.{_q(biz)}&status=eq.active"
            f"&select=id,module_id,data&order=created_at.desc&limit=200")
        if rows is None:
            raise HTTPException(503, "Your events couldn't be read just now. Try again.")
        by_mod[str(m["id"])] = rows
    out = []
    for o in er.build_occasions(mods, by_mod, today=today):
        if (date.fromisoformat(o["date"]) - today).days > WINDOW_DAYS:
            continue
        out.append({"key": f"ev:{o['entry_id']}", "source": "events", "title": _cut(o["title"], 80),
                    "event_on": o["date"], "when": "", "where": _cut(o.get("location") or "", 80), "body": ""})
    return out[:MAX_ITEMS]


# ─── the link ────────────────────────────────────────────────────────


def _link(biz: str) -> Optional[Dict[str, Any]]:
    # redact: a failure's log line never carries the row (the link is a secret).
    rows = sb_clients.sb_get_as_service(f"/worship_calendar?business_id=eq.{_q(biz)}&select={CALENDAR_FIELDS}&limit=1", redact=True)
    if rows is None:
        raise HTTPException(503, "Your calendar link couldn't be read just now. Try again.")
    return rows[0] if rows else None


def _calendar_events(link: Dict[str, Any], zone: Any, today: date) -> List[Dict[str, Any]]:
    import outside_calendar as oc
    return events_from_ics(oc.fetch_feed(link["url"]), zone, today)


def _items(biz: str) -> Dict[str, Any]:
    """Both calendars' events, each marked when it's already on the board."""
    import outside_calendar as oc
    from worship_announce_router import church_today, church_zone
    zone = church_zone(biz)
    today = church_today(biz)
    link = _link(biz)
    cal_items: List[Dict[str, Any]] = []
    cal_error = ""
    if link:
        try:
            cal_items = _calendar_events(link, zone, today)
        except oc.FeedError as e:
            cal_error = str(e)
    roster = solutionist_events(biz, today)
    events = roster or []
    keys = [i["key"] for i in cal_items + events]
    have = set()
    if keys:
        rows = _read(f"/worship_announcements?business_id=eq.{_q(biz)}&source=eq.calendar&archived_at=is.null"
                     f"&select=source_ref&limit={wa.MAX_PER_CHURCH}", "The announcements")
        have = {r.get("source_ref") for r in rows}
    items = sorted(cal_items + events, key=lambda e: (e["event_on"], e["title"]))
    for i in items:
        i["already"] = i["key"] in have
    return {"items": items, "today": today.isoformat(),
            "calendar": {"connected": bool(link), "shown_as": oc.mask_url(link["url"]) if link else None,
                         "provider": (link or {}).get("provider"), "error": cal_error or None},
            # Whether the church keeps its events in Solutionist (they come in with one tap).
            "events": roster is not None}


@router.get("/announcements/import")
def import_list(business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    _staff(biz, user, "plan")
    return _items(biz)


@router.put("/announcements/import/calendar")
def set_calendar(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """The calendar's link: it must open as a calendar before it's kept."""
    import outside_calendar as oc
    from worship_announce_router import church_today, church_zone
    body = body or {}
    biz = _uuid(body.get("business_id"))
    _staff(biz, user, "plan")
    try:
        url = oc.normalize_feed_url(str(body.get("url") or ""))
        found = events_from_ics(oc.fetch_feed(url), church_zone(biz), church_today(biz))
    except oc.FeedError as e:
        raise HTTPException(400, str(e))
    rows = sb_clients.sb_post_as_service("/worship_calendar?on_conflict=business_id&select=business_id",
                                         {"business_id": biz, "url": url, "provider": oc.detect_provider(url)[:20], "updated_at": _now()},
                                         prefer="resolution=merge-duplicates,return=representation",
                                         # PostgREST's error body quotes the failing row: never into the log.
                                         redact=True)
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "The link wasn't kept. Try again.")
    return {"ok": True, "shown_as": oc.mask_url(url), "found": len(found)}


@router.delete("/announcements/import/calendar")
def forget_calendar(business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    _staff(biz, user, "plan")
    if not sb_clients.sb_delete_as_service(f"/worship_calendar?business_id=eq.{_q(biz)}"):
        raise HTTPException(503, "The link wasn't forgotten. Try again.")
    return {"ok": True}


@router.post("/announcements/import")
def bring_in(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """The events picked go on the board in the church's look (the big date), from
    two weeks before until the day, in the room and the lobby. One already there stays as it is."""
    body = body or {}
    biz = _uuid(body.get("business_id"))
    _staff(biz, user, "plan")
    keys = body.get("keys")
    if not isinstance(keys, list) or not keys or len(keys) > MAX_ITEMS or any(not isinstance(k, str) for k in keys):
        raise HTTPException(400, "Pick the events to bring in")
    got = _items(biz)
    today = date.fromisoformat(got["today"])
    found = {i["key"] for i in got["items"]}
    if got["calendar"]["error"] and any(k.startswith("ics:") and k not in found for k in keys):
        raise HTTPException(502, f"Your calendar didn't open just now: {got['calendar']['error']}")
    picked = [i for i in got["items"] if i["key"] in set(keys) and not i["already"]]
    have = _read(f"/worship_announcements?business_id=eq.{_q(biz)}&archived_at=is.null&select=id&limit={wa.MAX_PER_CHURCH}",
                 "The announcements")
    if len(have) + len(picked) > wa.MAX_PER_CHURCH:
        raise HTTPException(400, f"A church keeps up to {wa.MAX_PER_CHURCH} announcements. Take a few old ones off first.")
    now = _now()
    rows = []
    for i in picked:
        ev = date.fromisoformat(i["event_on"])
        rows.append({"business_id": biz, "title": i["title"], "when_text": i["when"], "where_text": i["where"], "body": i["body"],
                     "image_url": "", "design": "date", "event_on": i["event_on"], "qr": {},
                     "show_from": max(today, ev - timedelta(days=SHOW_AHEAD_DAYS)).isoformat(), "show_until": i["event_on"],
                     "shows": {"room": True, "lobby": True, "online": False, "phones": False},
                     "status": "on", "source": "calendar", "source_ref": i["key"], "sent_by": {}, "sort": 0,
                     "created_at": now, "updated_at": now})
    # One at a time: the database keeps an event to once a board
    # (worship_announcements_calendar_once), so a press that loses a race to
    # another fails that one row, and it counts as already there.
    brought, failed = 0, []
    for row in rows:
        saved = sb_clients.sb_post_as_service("/worship_announcements?select=id", row, prefer="return=representation")
        if isinstance(saved, list) and saved:
            brought += 1
        else:
            failed.append(row["source_ref"])
    if failed:
        there = {r.get("source_ref") for r in _read(
            f"/worship_announcements?business_id=eq.{_q(biz)}&source=eq.calendar&archived_at=is.null&select=source_ref"
            f"&limit={wa.MAX_PER_CHURCH}", "The announcements")}
        if any(k not in there for k in failed):
            raise HTTPException(503, f"{brought} came in, and the rest didn't. Try those again." if brought
                                else "They weren't brought in. Try again.")
    return {"ok": True, "brought": brought, "skipped": len(keys) - brought}
