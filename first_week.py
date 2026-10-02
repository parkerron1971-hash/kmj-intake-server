"""first_week.py — what each new business actually did in its first days.

Until 2026-09-02 nothing answered "how far did the people who signed up
last week get?" The frontend recorded one onboarding event in four
months (a single meet_chief_skipped), the coached session wrote nothing
about being opened or abandoned, and the plug-in list was recomputed
live for the owner and never kept. Mission Control could show signups by
channel and MRR, and nothing in between. When two real strangers both
stopped in phase one of the coached session and never came back, the
only way to learn it was to read four tables by hand.

This module is the read side of that gap. The frontend now records the
moments (onboarding_step, session_opened / _paused / _completed,
plugin_opened, checklist_dismissed, tour_started — see
src/core/lib/telemetry.ts); this joins them, per business, with the
things the server already knows: the plug-in probes (what is actually
connected), the track rows (how far the sit-down with Chief got), and
chief_activity (whether they came back).

WHAT "RETURNED" AND "ACTIVATED" MEAN HERE

  returned   — any Chief activity or product event on a calendar day
               AFTER the day the business was created. Day-one usage,
               however heavy, is not a return.
  activated  — at least ACTIVATION_PLUGINS of the plug-in list are
               probed done. A working business, by the list's own
               definition, not by a proxy.

Both are deliberately blunt. They are meant to be read next to the
per-business rows, not to replace them.

NOTHING HERE RAISES. Every read degrades to an empty list and the row is
still returned with what could be learned; a missing table on a fresh
deploy renders as zeros, not as an error page. The probes are the one
expensive step (several queries per business), so the report is capped
at MAX_BUSINESSES, newest first.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import sb_clients

logger = logging.getLogger("first_week")

MAX_BUSINESSES = 25
ACTIVATION_PLUGINS = 3

# The onboarding flow's screens, in order. The frontend sends the index
# and the name; the name is what the panel shows.
# The three-screen flow (FE Wave B); older rows may carry indexes up to 5
# from the six-screen version, which fall off the end as "unknown".
ONBOARDING_STEPS = ["who_you_are", "your_work", "your_voice"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _window_start_iso(days: int) -> str:
    # Z form, never isoformat's +00:00 — PostgREST silently returns zero
    # rows for the latter in a query string (margin.py learned this).
    return (_now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts: Any) -> Optional[datetime]:
    s = str(ts or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _read(path: str) -> List[Dict[str, Any]]:
    """A service-role read that returns [] on any failure and says so in
    the log. The report renders what it could learn."""
    try:
        rows = sb_clients.sb_get_as_service(path)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("[first_week] read failed %s: %s", path.split("?")[0], e)
        return []
    return rows if isinstance(rows, list) else []


def _plugins_for(biz: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """The probed plug-in list for one business, or None when the probes
    could not run. Imported lazily so this module stays importable in a
    test without the router's dependency tree."""
    try:
        import business_track_router as btr
        items = btr.resolve_plugins(biz)
        return items if isinstance(items, list) else None
    except Exception as e:
        logger.warning("[first_week] plugins failed for %s: %s", biz.get("id"), e)
        return None


def _in_list(ids: List[str]) -> str:
    return "(" + ",".join(ids) + ")"


def _day_key(dt: Optional[datetime]) -> Optional[str]:
    return dt.date().isoformat() if dt else None


def _business_row(biz: Dict[str, Any], events: List[Dict[str, Any]],
                  track: Optional[Dict[str, Any]], strategy: Optional[Dict[str, Any]],
                  activity: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    created = _parse(biz.get("created_at"))
    created_day = _day_key(created)
    age_days = int((now - created).total_seconds() // 86400) + 1 if created else None

    # ── the onboarding flow ──────────────────────────────────────────
    steps_seen = [e for e in events if e.get("event") == "onboarding_step"]
    step_idx = -1
    for e in steps_seen:
        try:
            step_idx = max(step_idx, int((e.get("props") or {}).get("step", -1)))
        except (TypeError, ValueError):
            continue
    # A business row exists, so launch happened; the event just says
    # whether the flow recorded it (older clients did not fire steps).
    launched_recorded = any(e.get("event") == "business_created" for e in events)

    # ── the sit-down with Chief ──────────────────────────────────────
    kinds = {e.get("event") for e in events}
    sess = track or strategy
    session = {
        "kind": "business" if track else ("strategy" if strategy else None),
        "status": (sess or {}).get("status"),
        "phase": (sess or {}).get("current_phase"),
        "opened": "session_opened" in kinds or sess is not None,
        "paused": "session_paused" in kinds,
        "completed": "session_completed" in kinds or (sess or {}).get("status") == "completed",
    }

    # ── the plug-ins ────────────────────────────────────────────────
    items = _plugins_for(biz)
    done = sum(1 for p in (items or []) if p.get("done"))
    total = len(items or [])
    next_move = next((p.get("title") for p in (items or [])
                      if not p.get("done") and not (p.get("blocked_by") or [])), None)
    if next_move is None:
        next_move = next((p.get("title") for p in (items or []) if not p.get("done")), None)
    plugins_opened = sum(1 for e in events if e.get("event") == "plugin_opened")

    # ── did they come back ──────────────────────────────────────────
    stamps: List[datetime] = []
    for r in activity:
        dt = _parse(r.get("created_at"))
        if dt:
            stamps.append(dt)
    for e in events:
        dt = _parse(e.get("created_at"))
        if dt:
            stamps.append(dt)
    days_active = sorted({_day_key(d) for d in stamps if d} - {None})
    returned = any(d != created_day for d in days_active) if created_day else False
    last_seen = max(stamps).isoformat().replace("+00:00", "Z") if stamps else None

    return {
        "business_id": biz.get("id"),
        "name": biz.get("name"),
        "type": biz.get("type"),
        "created_at": biz.get("created_at"),
        "day": age_days,
        "trial_ends_at": biz.get("trial_ends_at"),
        "subscription_status": biz.get("subscription_status"),
        "onboarding": {
            "furthest_step": step_idx,
            "furthest_step_name": ONBOARDING_STEPS[step_idx] if 0 <= step_idx < len(ONBOARDING_STEPS) else None,
            "launch_recorded": launched_recorded,
        },
        "session": session,
        "plugins": {
            "done": done, "total": total, "next": next_move,
            "probed": items is not None, "opened": plugins_opened,
        },
        "chief_actions": len(activity),
        "days_active": len(days_active),
        "returned": returned,
        "activated": done >= ACTIVATION_PLUGINS,
        "checklist_dismissed": "checklist_dismissed" in kinds
                               or bool((biz.get("settings") or {}).get("checklist_dismissed")),
        "tour_started": "tour_started" in kinds,
        "last_seen_at": last_seen,
    }


def first_week_report(days: int = 30, limit: int = MAX_BUSINESSES) -> Dict[str, Any]:
    """Every business created in the window, newest first, with what it
    did; plus the funnel across them and the anonymous Meet-Chief counts
    (those fire before a business exists, so they can only be totals)."""
    days = max(1, min(int(days or 30), 365))
    limit = max(1, min(int(limit or MAX_BUSINESSES), MAX_BUSINESSES))
    since = _window_start_iso(days)
    now = _now()

    businesses = _read(
        f"/businesses?created_at=gte.{since}&is_active=eq.true"
        f"&order=created_at.desc&limit={limit}"
        f"&select=id,name,type,owner_id,created_at,settings,subscription_status,trial_ends_at")
    ids = [str(b.get("id")) for b in businesses if b.get("id")]

    events_by: Dict[str, List[Dict[str, Any]]] = {i: [] for i in ids}
    tracks: Dict[str, Dict[str, Any]] = {}
    strategies: Dict[str, Dict[str, Any]] = {}
    activity_by: Dict[str, List[Dict[str, Any]]] = {i: [] for i in ids}
    if ids:
        inl = _in_list(ids)
        for e in _read(f"/product_events?business_id=in.{inl}"
                       f"&select=business_id,event,props,created_at&order=created_at.asc&limit=20000"):
            events_by.setdefault(str(e.get("business_id")), []).append(e)
        for t in _read(f"/business_tracks?business_id=in.{inl}"
                       f"&select=business_id,status,current_phase,updated_at&order=created_at.desc"):
            tracks.setdefault(str(t.get("business_id")), t)
        for t in _read(f"/strategy_tracks?business_id=in.{inl}"
                       f"&select=business_id,status,current_phase,updated_at&order=created_at.desc"):
            strategies.setdefault(str(t.get("business_id")), t)
        for a in _read(f"/chief_activity?business_id=in.{inl}"
                       f"&select=business_id,created_at&order=created_at.asc&limit=20000"):
            activity_by.setdefault(str(a.get("business_id")), []).append(a)

    rows = [
        _business_row(b, events_by.get(str(b.get("id")), []),
                      tracks.get(str(b.get("id"))), strategies.get(str(b.get("id"))),
                      activity_by.get(str(b.get("id")), []), now)
        for b in businesses
    ]

    # Anonymous intro events — no business yet, so totals only.
    intro = {"started": 0, "completed": 0, "skipped": 0}
    for e in _read(f"/product_events?event=in.(meet_chief_started,meet_chief_completed,meet_chief_skipped)"
                   f"&created_at=gte.{since}&select=event&limit=20000"):
        k = str(e.get("event") or "").replace("meet_chief_", "")
        if k in intro:
            intro[k] += 1

    funnel = {
        "signups": len(rows),
        "session_opened": sum(1 for r in rows if r["session"]["opened"]),
        "session_completed": sum(1 for r in rows if r["session"]["completed"]),
        "plugin_opened": sum(1 for r in rows if r["plugins"]["opened"] > 0),
        "one_plugged_in": sum(1 for r in rows if r["plugins"]["done"] >= 1),
        "activated": sum(1 for r in rows if r["activated"]),
        "returned": sum(1 for r in rows if r["returned"]),
    }
    return {
        "days": days,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "activation_plugins": ACTIVATION_PLUGINS,
        "intro": intro,
        "funnel": funnel,
        "businesses": rows,
    }
