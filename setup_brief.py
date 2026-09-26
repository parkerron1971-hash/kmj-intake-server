"""
setup_brief.py — the morning brief a brand-new business actually gets.

THE GAP THIS CLOSES
  notification_engine skips the morning brief when there is nothing to
  report: no drafts, no sessions, no leads. That rule is right for a
  working business and exactly wrong for a new one. In its first week
  there is never anything to report, so the brief was off precisely
  when a new practitioner most needed a nudge, and the push brief told
  someone with nothing plugged in "clear runway — go do the deep work".

WHAT THIS DOES
  During the launch window (days 1 to SETUP_BRIEF_WINDOW_DAYS, counted
  from first_run_arc's day one), while the day-one plug-in list still has
  something undone, a quiet morning gets ONE next setup step: what it
  is, why it matters, and a way to do it (the step's own door, and
  "open Chief and say let's do this one" when Chief can do it in chat).

  Same source as Chief. The list is business_track_router.resolve_plugins,
  the one the SETUP STATUS block in Chief's prompt is built from, and the
  step is picked the same way: first undone, unblocked item. The why is
  the one Chief reads. No model call: the copy is assembled from the
  catalog, so the brief costs a few reads and cannot disagree with the
  list it came from.

WHAT IT RESPECTS
  · The morning-brief opt-out and the once-a-day cap. The caller runs
    them, the same checks the ordinary brief runs, before this module
    is ever asked.
  · A dismissed checklist. That is the practitioner saying "stop the
    setup talk", honored here the way Chief honors it.
  · The business's clock. With a timezone set
    (settings.availability.timezone, the one set_business_timezone
    writes) the brief lands in their local morning, starting at their
    morning_brief_time, and never at night. Without one it rides the
    platform's 13:05 UTC morning tick like every other brief does.
  · The lifecycle emails. On the local day the day-three or day-seven
    email lands, that email is the nudge and the brief holds. Two asks
    in one morning is how a nudge turns into noise.
  · The first hours. A business opened under MIN_AGE_HOURS ago is still
    in its first conversation with Chief; a "good morning" on top of it
    is noise too.

  Outside the window, with the list done, or with the checklist
  dismissed, nothing here applies and the caller does what it always
  did: skip when there is nothing to report.

NOTHING HERE RAISES. Every failure reads as "no setup brief", which is
the old behavior. The failure this module must never have is a wrong
brief.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("setup_brief")

# Days 1..7 are "the first week" in the copy. The window is how long a
# quiet morning keeps getting a setup step while the list is unfinished.
FIRST_WEEK_DAYS = 7
DEFAULT_WINDOW_DAYS = 14

# A business opened this recently is still in its first sit-down with
# Chief; the welcome email and Chief's introduction cover day one.
MIN_AGE_HOURS = 12

# The business's morning, for businesses that told us their timezone:
# from their morning_brief_time (the NotificationCenter setting, default
# 07:30) for this many hours. The hourly tick runs at :35, so a 07:30
# setting lands at 7:35 local. The start is clamped to a real morning:
# a "morning brief" at midnight is a quiet-hours violation whatever the
# setting says.
DEFAULT_LOCAL_HOUR = 7
MORNING_BAND_HOURS = 3
EARLIEST_LOCAL_HOUR = 5
LATEST_LOCAL_HOUR = 11

# When lifecycle_emails.week_beats_tick runs (kmj_intake_automation,
# job id "week_beats"). A test pins this to the registered job, so the
# overlap check cannot drift away from the email it avoids.
WEEK_BEATS_UTC = (14, 45)

# Catalog items a morning brief never leads with. QuickBooks is only for
# people who already keep their books there, and Chief is told never to
# push it on someone without an accountant. A morning push is pushing.
NEVER_LEADS = frozenset({"quickbooks"})


# ─── Switches ────────────────────────────────────────────────────────

def enabled() -> bool:
    """Kill switch: SETUP_BRIEF=off puts every quiet morning back to the
    old skip, with no deploy."""
    return (os.environ.get("SETUP_BRIEF") or "on").strip().lower() != "off"


def window_days() -> int:
    try:
        n = int(os.environ.get("SETUP_BRIEF_WINDOW_DAYS") or DEFAULT_WINDOW_DAYS)
    except ValueError:
        n = DEFAULT_WINDOW_DAYS
    return max(FIRST_WEEK_DAYS, min(n, 60))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: Any) -> Optional[datetime]:
    s = str(ts or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _settings(biz: Dict[str, Any]) -> Dict[str, Any]:
    s = (biz or {}).get("settings")
    return s if isinstance(s, dict) else {}


# ─── The business's clock ────────────────────────────────────────────

def local_tz(biz: Dict[str, Any]):
    """The business's own timezone, or None when it never told us.

    Same field sms_alerts and chief_assignments read. None is not UTC:
    it means "we do not know their clock", and the caller then uses the
    platform's morning tick, as every other brief does."""
    name = str((_settings(biz).get("availability") or {}).get("timezone") or "").strip()
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return None


def _brief_hour(biz: Dict[str, Any]) -> int:
    raw = str((_settings(biz).get("notifications") or {}).get("morning_brief_time") or "")
    try:
        hour = int(raw.split(":", 1)[0])
    except ValueError:
        hour = DEFAULT_LOCAL_HOUR
    return max(EARLIEST_LOCAL_HOUR, min(hour, LATEST_LOCAL_HOUR))


def is_local_morning(biz: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """Is it this business's morning right now?

    No timezone: yes. The only unattended caller for those businesses is
    the 13:05 UTC morning tick (the hourly tick skips them), which is the
    platform's morning compromise for everyone who has not told us their
    clock, and the same moment the ordinary brief lands."""
    tz = local_tz(biz)
    if tz is None:
        return True
    start = _brief_hour(biz)
    hour = (now or _now()).astimezone(tz).hour
    return start <= hour < start + MORNING_BAND_HOURS


# ─── Where they are in their launch ──────────────────────────────────

def _arc(business_id: str) -> Optional[Dict[str, Any]]:
    try:
        import first_run_arc
        return first_run_arc.state(business_id)
    except Exception as e:  # pragma: no cover - state() already never raises
        logger.warning(f"[setup-brief] arc read failed for {business_id}: {e}")
        return None


def launch_day(biz: Dict[str, Any], now: Optional[datetime] = None
               ) -> Tuple[int, Optional[datetime]]:
    """(day, started): which day of its launch this business is on,
    1-based, and the moment day one began. (0, None) for "not launching"
    or "can't tell", which callers treat as outside the window.

    Day one is first_run_arc's, so a business that signed up in March
    and subscribed in April is on day one in April, the same day Chief
    counts from. Without an arc it is the day the business was created.

    The arc read costs a query, so it is only spent on a business that
    could be launching: created inside the window, or trialing now (the
    late subscriber whose day one was re-stamped to their trial)."""
    now = now or _now()
    created = _parse((biz or {}).get("created_at"))
    young = created is not None and now - created <= timedelta(days=window_days())
    trialing = str((biz or {}).get("subscription_status") or "").strip().lower() == "trialing"
    if not (young or trialing) or not (biz or {}).get("id"):
        return 0, None
    arc = _arc(str(biz["id"]))
    started = _parse((arc or {}).get("started_at")) or created
    if started is None:
        return 0, None
    import first_run_arc
    return first_run_arc.day_of({"started_at": started.isoformat()}, now=now), started


def _in_window_day(biz: Dict[str, Any], now: datetime) -> Tuple[int, Optional[datetime], str]:
    """(day, started, reason). day is 0 whenever the setup brief does not
    apply at all, with the reason why."""
    if not enabled():
        return 0, None, "off"
    if _settings(biz).get("checklist_dismissed"):
        return 0, None, "checklist_dismissed"
    day, started = launch_day(biz, now)
    if not day or day > window_days():
        return 0, None, "outside_window"
    return day, started, ""


# ─── The day-three and day-seven emails ──────────────────────────────

def _next_beat_tick(now: datetime) -> datetime:
    hour, minute = WEEK_BEATS_UTC
    at = datetime.combine(now.date(), time(hour, minute), tzinfo=timezone.utc)
    return at if at > now else at + timedelta(days=1)


def week_beat_today(biz: Dict[str, Any], now: Optional[datetime] = None) -> Optional[str]:
    """'day_three' | 'day_seven' when that lifecycle email lands on this
    business's local today, else None.

    "Today" is the business's calendar day (UTC when it has no
    timezone), so the email and the brief are compared on the day the
    practitioner reads them. Two cases:
      · it already went: its stamp falls on today;
      · it is about to: the next week_beats tick falls on today and
        lifecycle_emails' own classifier says that tick will send it.
    The classifier is the email's, not a copy of it, so the two cannot
    disagree about which day is day three."""
    now = now or _now()
    try:
        import lifecycle_emails as le
    except Exception as e:  # pragma: no cover
        logger.warning(f"[setup-brief] lifecycle import failed: {e}")
        return None
    if not le.enabled():
        return None
    tz = local_tz(biz) or timezone.utc
    today = now.astimezone(tz).date()

    stamps = le._stamps(biz)
    for kind in ("day_three", "day_seven"):
        sent = _parse(stamps.get(f"{kind}_at"))
        if sent and sent.astimezone(tz).date() == today:
            return kind

    tick = _next_beat_tick(now)
    if tick.astimezone(tz).date() != today:
        return None
    kind = le._classify_week(biz, tick)
    if not kind:
        return None
    # Grandfathered owners never get the week beats, so there is no
    # email to make room for.
    if le._is_grandfathered(str(biz.get("owner_id") or "")):
        return None
    return kind


# ─── The step ────────────────────────────────────────────────────────

def _plugins(biz: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The live plug-in list, the same call Chief's SETUP STATUS makes.
    [] on any failure: no brief beats a wrong one."""
    try:
        import business_track_router as btr
        items = btr.resolve_plugins(biz)
        return items if isinstance(items, list) else []
    except Exception as e:
        logger.warning(f"[setup-brief] plug-in list failed for {biz.get('id')}: {e}")
        return []


def next_step(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The first undone, unblocked item, which is what Chief names when
    asked what's next. A blocked item is never offered instead: "point
    your domain at your site" before there is a site is a dead end."""
    for p in items or []:
        if p.get("done") or p.get("key") in NEVER_LEADS:
            continue
        if p.get("blocked_by"):
            continue
        return p
    return None


def chief_does_it_here(key: Optional[str]) -> bool:
    """True for the steps Chief finishes in the chat itself (the catalog
    marks them DO IT HERE); the rest are doors Chief can only open."""
    try:
        import business_track_actions as bta
        hint = (bta.PLUGIN_CATALOG.get(key or "") or {}).get("chief") or ""
    except Exception:  # pragma: no cover
        return False
    return hint.startswith("DO IT HERE")


def _clip(text: Any, limit: int) -> str:
    s = " ".join(str(text or "").split())
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(" ", 1)[0].rstrip(",;:-— ")
    return cut + "…"


def _sentence(text: Any, limit: int = 180) -> str:
    s = _clip(text, limit)
    if s and s[-1] not in ".!?…":
        s += "."
    return s


def _push_nav(nav: Dict[str, Any]) -> str:
    """The push deep link, "tab:sub", which the service worker opens as
    /?nav=tab:sub. BUILD pages travel as the sub, as they do everywhere
    the app routes solutionist-nav."""
    tab = str(nav.get("tab") or "home")
    leaf = str(nav.get("page") or nav.get("sub") or "")
    return f"{tab}:{leaf}" if leaf else tab


def compose(*, day: int, step: Dict[str, Any], done: int, total: int,
            now: Optional[datetime] = None) -> Dict[str, Any]:
    """The words. Plain, warm, one step, under about sixty words.

    notification: the chief_notifications columns (title, body,
    priority, suggested_action, action_payload). The action is the
    step's own door through the navigate handler, the destination Chief
    itself would emit; "Open Chief" on the card asks Chief about the
    title, and Chief has the same list in front of it.
    push: what the device shows, deep-linked to the same door."""
    now = now or _now()
    title = str(step.get("title") or "").strip()
    why = _sentence(step.get("why"))
    nav = dict(step.get("nav") or {})

    lead = (f"Day {day} of your first week." if day <= FIRST_WEEK_DAYS
            else "Good morning.")
    progress = ("Nothing is plugged in yet, and one piece today is plenty."
                if done <= 0 else
                f"So far {done} of {total} pieces are plugged in.")
    if chief_does_it_here(step.get("key")):
        how = ('Open Chief and say "let\'s do this one". It does it with you, '
               'right in the chat.')
    else:
        how = ('Tap "Take me there" to open the right page, or open Chief '
               'and it will walk you through it.')

    notification = {
        "title": _clip(f"Today's one step: {title}", 200),
        "body": f"{lead} {progress}\n\nNext: {title}. {why}\n\n{how}"[:2000],
        "priority": "normal",
        "suggested_action": "Take me there",
        "action_payload": {"type": "navigate", **nav,
                           "setup_step": step.get("key")},
    }
    push = {
        "title": "Good morning ✦ Chief here",
        "body": _clip((f"Day {day}. " if day <= FIRST_WEEK_DAYS else "")
                      + f"Next: {title}. {_clip(step.get('why'), 90)}", 170),
        "nav": _push_nav(nav),
        "tag": f"morning-{now.date().isoformat()}",
    }
    return {"notification": notification, "push": push}


# ─── The decision ────────────────────────────────────────────────────

def plan(biz: Dict[str, Any], *, now: Optional[datetime] = None,
         on_demand: bool = False) -> Dict[str, Any]:
    """Should this quiet morning get a setup brief, and what does it say?

    Only asked once the caller has found nothing to report and has
    already run the opt-out and once-a-day checks. Sync (the plug-in
    probes are sync reads); call it off-thread.

    Returns one of:
      {"window": False, "send": False, "reason": ...}
          not this module's morning; the caller skips as it always did.
      {"window": True, "send": False, "reason": ..., "day": n}
          a launching business on a morning the brief holds.
      {"window": True, "send": True, "day", "step", "done", "total",
       "notification", "push"}

    on_demand: someone asked for their brief right now, so the local
    clock is theirs to overrule. Nothing else is."""
    now = now or _now()
    try:
        day, started, reason = _in_window_day(biz, now)
        if not day:
            return {"window": False, "send": False, "reason": reason}
        held = {"window": True, "send": False, "day": day}
        if started is not None and now - started < timedelta(hours=MIN_AGE_HOURS):
            return {**held, "reason": "just_started"}
        if not on_demand and not is_local_morning(biz, now):
            return {**held, "reason": "not_local_morning"}
        beat = week_beat_today(biz, now)
        if beat:
            return {**held, "reason": f"{beat}_email_today"}

        items = _plugins(biz)
        step = next_step(items)
        if not step:
            # Nothing left to plug in (or nothing we can say yet): the
            # business is back on the ordinary rule.
            return {"window": False, "send": False, "reason": "setup_done"}
        done = sum(1 for p in items if p.get("done"))
        out = {"window": True, "send": True, "day": day, "step": step,
               "done": done, "total": len(items)}
        out.update(compose(day=day, step=step, done=done, total=len(items), now=now))
        return out
    except Exception as e:
        logger.warning(f"[setup-brief] plan failed for {biz.get('id')}: {e}")
        return {"window": False, "send": False, "reason": "error"}


def owns_morning(biz: Dict[str, Any], *, now: Optional[datetime] = None) -> bool:
    """Does the setup brief speak for this business's quiet mornings?

    The push tick asks before it sends "clear runway", which is the
    wrong thing to tell someone with nothing plugged in. True for a
    launching business with a step still to take, whatever today's clock
    or email says: on a held morning the practitioner hears nothing from
    the brief, rather than the wrong thing."""
    now = now or _now()
    try:
        day, _started, _reason = _in_window_day(biz, now)
        if not day:
            return False
        return next_step(_plugins(biz)) is not None
    except Exception as e:
        logger.warning(f"[setup-brief] ownership check failed for {biz.get('id')}: {e}")
        return False
