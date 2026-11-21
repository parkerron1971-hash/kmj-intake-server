"""church_tells_sunday.py — Sunday's three tells: the sermon draft is in,
the count isn't, and an event has no flyer.

Love City's connection map (2026-11-21) found three Sunday hand-offs that
waited with nobody told:

  * the stream relay turns the service's recording into a sermon draft
    (stream_relay_router._sermon_draft), and whoever posts sermons never
    heard it was there;
  * Sunday's head count could go unentered all day, and the weekly
    attendance job only said so the next week;
  * an event went up in Services & Events with no flyer, and whoever makes
    the flyers found out when it was too late to share one.

Each is a finder for church_tells' sweep (every 30 minutes on the worker):
finder(church, now) -> [church_tells.Item]. The sweep tells the duty's
people once per key, holds a church's tells through its quiet hours and
never tells the login who did it. Every finder here reads as the server,
only this church's rows, quotes every value it filters on, and gives []
when a read fails (the next sweep tries again).

    sermon_draft .. an unpublished sermon made from a recording in the last
                    3 days (its video_url is our own watch link). A sermon
                    someone is typing by hand is theirs: no tell.
                    -> sermons, key sermon-draft:<id>
    count_missing . on the church's own Sunday (its clock), from 1 PM to the
                    end of the day, when a service was planned today and
                    today has no count. "Counted" is the weekly attendance
                    job's own rule (church_work_checks.sunday_counted), so
                    the tell and My week never disagree.
                    -> attendance, key count-missing:<YYYY-MM-DD>
    flyer_needed .. a public event in Services & Events starting in the next
                    14 days with no flyer (event_volunteers.flyer_of, the one
                    reader), made at least 12 hours ago so its organizer has
                    a moment to add one. A service, a church-only (private)
                    or invite-only occasion needs none. The soonest 3 not
                    told yet, each sweep.
                    -> flyers, key flyer:<entry id>
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import church_tells as ct

DRAFT_DAYS = 3                  # a draft older than this was seen in Sermons by now
COUNT_FROM_HOUR = 13            # 1 PM on the church's clock: the service is over
FLYER_AHEAD_DAYS = 14
FLYER_SETTLE_HOURS = 12         # the organizer's moment to attach one
FLYERS_PER_SWEEP = 3


def _zone(church: Dict[str, Any]):
    """The church's clock (church_leader_tasks.zone, what My week and the
    checks read). None when it can't be read: nothing is judged on a
    guessed clock."""
    try:
        import church_leader_tasks as clt
        return clt.zone(church)
    except Exception:  # noqa: BLE001
        return None


def _day_words(d: date) -> str:
    return f"{d.strftime('%A')}, {d.strftime('%B')} {d.day}"


def _parse_day(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def _at(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ─── The sermon draft ─────────────────────────────────────────────────

def sermon_draft(church: Dict[str, Any], now: datetime) -> List[ct.Item]:
    try:
        import stream_relay_router as srr
    except Exception:  # noqa: BLE001 — no relay on this trunk: nothing makes drafts
        return []
    b = ct.q(church["id"])
    out: List[ct.Item] = []
    for r in ct.rows(f"/sermons?business_id=eq.{b}&published=eq.false&created_at=gte.{ct.since(now, DRAFT_DAYS)}"
                     "&select=id,preached_on,video_url,created_at&order=created_at.asc&limit=20"):
        if not r.get("id") or not srr.watch_session(str(r.get("video_url") or "")):
            continue
        day = _parse_day(r.get("preached_on"))
        whose = f"{day.strftime('%A')}'s" if day else "The"
        out.append(ct.Item(key=f"sermon-draft:{r['id']}", title=f"{whose} sermon is ready to post",
                           line="The recording is in. Add the title and post it.", duty="sermons"))
    return out


# ─── Sunday's count ───────────────────────────────────────────────────

def _service_today(church: Dict[str, Any], day: date, tz) -> bool:
    """A service was planned today: a Sunday plan (worship_services, the
    calendar's own read), else a Services & Events occasion that is a
    service. Raises when it can't be read."""
    import church_leaders_note as cln
    b = str(church["id"])
    lo = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    if cln._plans(b, lo, lo + timedelta(days=1), tz):
        return True
    return any(o.get("kind") == "service" for o in cln._occasions(b, day, day, tz))


def count_missing(church: Dict[str, Any], now: datetime) -> List[ct.Item]:
    tz = _zone(church)
    if tz is None:
        return []
    local = now.astimezone(tz)
    if local.weekday() != 6 or local.hour < COUNT_FROM_HOUR:
        return []
    day = local.date()
    key = f"count-missing:{day.isoformat()}"
    if ct.told(church, key):
        return []                       # told today: nothing more to read
    try:
        import church_work_checks as cw
        if not _service_today(church, day, tz):
            return []
        if cw.sunday_counted(cw.Ctx(church, now, tz), day, now):
            return []
    except Exception:  # noqa: BLE001 — Unread, a 503, a blip: never "missed" on a read that failed
        return []
    return [ct.Item(key=key, title="Sunday's count isn't in yet",
                    line="Enter today's head count before the day is out.", duty="attendance")]


# ─── The flyer ────────────────────────────────────────────────────────

def _events(church: Dict[str, Any], now: datetime, tz) -> List[Tuple[date, datetime, str, str]]:
    """This church's public events in Services & Events starting in the
    next FLYER_AHEAD_DAYS, made FLYER_SETTLE_HOURS ago or more, with no
    flyer: (day, start, title, entry id), soonest first."""
    import church_leaders_note as cln
    import event_volunteers as evv
    import events_rsvp_router as ev
    b = ct.q(church["id"])
    mods = ct.rows(f"/custom_modules?business_id=eq.{b}&archetype=eq.event_roster&is_active=eq.true"
                   "&select=id,archetype_params&limit=50")
    fields = {str(m["id"]): ev.resolve_fields(m.get("archetype_params")) for m in mods if m.get("id")}
    if not fields:
        return []
    today = now.astimezone(tz).date()
    last = today + timedelta(days=FLYER_AHEAD_DAYS)
    settled = ct.q(ct._iso(now - timedelta(hours=FLYER_SETTLE_HOURS)))
    ids = ",".join(ct.q(i) for i in sorted(fields))
    out = []
    for e in ct.rows(f"/module_entries?business_id=eq.{b}&module_id=in.({ids})&status=eq.active"
                     f"&created_at=lte.{settled}&select=id,module_id,data,created_at"
                     "&order=created_at.desc&limit=1000"):
        f = fields.get(str(e.get("module_id")))
        data = e.get("data") if isinstance(e.get("data"), dict) else {}
        if not f or not e.get("id") or ev.occasion_visibility(data) != "public":
            continue
        day, at = cln._when_of(data.get(f["date_field"]), tz)
        if not day or not today <= day <= last or (at is not None and at <= now):
            continue
        if cln._roster_kind(data, day, f["occasion_noun"]) != "event":
            continue
        if evv.flyer_of(data, church["id"], e["id"]):
            continue
        title = cln._plain(data.get(f["title_field"]))
        start = at or datetime.combine(day, datetime.min.time(), tzinfo=tz)
        out.append((day, start, title, str(e["id"])))
    out.sort(key=lambda x: (x[1], x[3]))
    return out


def flyer_needed(church: Dict[str, Any], now: datetime) -> List[ct.Item]:
    import sb_clients
    tz = _zone(church)
    if tz is None or not sb_clients.sb_url():
        return []                       # no clock, or no way to tell a flyer from none
    try:
        events = _events(church, now, tz)
    except Exception:  # noqa: BLE001
        return []
    out: List[ct.Item] = []
    for day, _start, title, eid in events:
        key = f"flyer:{eid}"
        if ct.told(church, key):
            continue                    # told before: the next one gets its turn
        name = (title or "An event")[:60]
        out.append(ct.Item(key=key, title=f"{name} needs a flyer",
                           line=f"It's on {_day_words(day)}. Make its flyer so people can share it.",
                           duty="flyers"))
        if len(out) >= FLYERS_PER_SWEEP:
            break
    return out
