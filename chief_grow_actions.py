"""
chief_grow_actions.py — the Grow handlers: goals, reminders, content.

Split out of chief_of_staff.py on 2026-09-04, the second slice of
"split the monolith along the registry" (the first was
chief_strategy_actions). Seven verbs, their validation constants and
private helpers, bodies byte-identical to where they were.

WHAT LIVES HERE
  Goals (create_goal, check_goals, add_reminder), the content calendar
  (plan_content, publish_post, publish_to_site) and idea capture
  (capture_idea). Goals live in businesses.settings.goals.active_goals
  and .completed_goals; planned posts in
  businesses.settings.content_calendar.planned_posts. Both are JSONB
  blobs the GROW panels render, which is why every handler here starts
  with _fetch_business_settings.

WHAT STAYED BEHIND. _TurnClock, _context_sources and _resolve_source
sat physically inside this region but belong to the turn (chief_chat
and chief_prewarm consume them, and test_chief_prewarm pins the source
list through `cos.`); they stay in chief_of_staff.

HOST HELPERS. _sb, _fail and _nav resolve into chief_of_staff at call
time through chief_host, so a test that monkeypatches `cos._sb` still
covers these handlers and _fail stays one definition.

REGISTRATION. chief_of_staff imports every handle_* by name, so
`chief_of_staff.handle_plan_content` is the same function object —
test_chief_plan_content calls it and test_post_approval /
test_site_autonomy read its source through that name.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from chief_host import _sb, _fail, _nav

# Same logger name as the file this came from.
logger = logging.getLogger("chief_of_staff")


# ─── Goals + content ───────────────────────────────────────────────────
#
# Goals live in businesses.settings.goals.active_goals (list of objects)
# and businesses.settings.goals.completed_goals. Content posts live at
# businesses.settings.content_calendar.planned_posts. Both are JSONB
# blobs that the corresponding GROW UI panels render.

VALID_GOAL_CATEGORIES = (
    "contacts", "revenue", "sessions", "engagement",
    # 2026-05-23: expanded for the Goals redesign — solo practitioner
    # categories that lensFor() groups into Business / Team Building /
    # Personal in the UI. Auto-track defaults to off for these (no
    # data source); the practitioner enters current_override manually.
    "marketing", "growth", "learning", "wellness",
    "custom",
)
VALID_GOAL_PERIODS = ("weekly", "monthly", "quarterly", "yearly")
VALID_GOAL_METRICS = (
    "total_contacts", "new_contacts",
    "revenue_collected", "revenue_invoiced",
    "sessions_completed", "sessions_scheduled",
    "engagement_rate", "custom",
)


def _default_metric_for_category(cat: str) -> str:
    return {
        "contacts": "new_contacts",
        "revenue": "revenue_collected",
        "sessions": "sessions_completed",
        "engagement": "engagement_rate",
    }.get(cat, "custom")


def _default_period_range(period: str) -> Tuple[str, str]:
    today = datetime.now(timezone.utc).date()
    if period == "weekly":
        start = today - timedelta(days=(today.weekday()))
        return (start.isoformat(), (start + timedelta(days=6)).isoformat())
    if period == "monthly":
        start = today.replace(day=1)
        # last day of month
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = next_month - timedelta(days=1)
        return (start.isoformat(), end.isoformat())
    if period == "quarterly":
        q = (today.month - 1) // 3
        start = today.replace(month=q * 3 + 1, day=1)
        next_q_month = (start.month - 1 + 3) % 12 + 1
        next_q_year = start.year + ((start.month - 1 + 3) // 12)
        next_q = date(next_q_year, next_q_month, 1)
        end = next_q - timedelta(days=1)
        return (start.isoformat(), end.isoformat())
    return (f"{today.year}-01-01", f"{today.year}-12-31")


async def _fetch_business_settings(client, biz_id: str) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    rows = await _sb(client, "GET", f"/businesses?id=eq.{biz_id}&select=id,settings&limit=1") or []
    if not rows:
        return None, {}
    biz = rows[0]
    settings = biz.get("settings") or {}
    if not isinstance(settings, dict):
        settings = {}
    return biz, settings


def _planned_post_present(rows: Any, post_id: str) -> bool:
    """True when `rows` — a PostgREST business payload — carries a planned
    post with this id.

    Exists because `_sb` reports a rejected write the same way it reports
    a successful one that returned no body: it returns None. Any handler
    that wants to tell the practitioner "saved" honestly has to look at
    the row rather than at the absence of an exception.
    """
    if not isinstance(rows, list) or not rows:
        return False
    row = rows[0]
    if not isinstance(row, dict):
        return False
    settings = row.get("settings")
    if not isinstance(settings, dict):
        return False
    cal = settings.get("content_calendar")
    if not isinstance(cal, dict):
        return False
    return any(
        isinstance(p, dict) and p.get("id") == post_id
        for p in (cal.get("planned_posts") or [])
    )


async def handle_create_goal(client, biz, action) -> Dict:
    """Create a strategic goal stored at settings.goals.active_goals.
    Auto-tracked goals don't carry a current value — the UI computes
    progress from live data on every render."""
    biz_id = biz["id"]
    title = (action.get("title") or "").strip()
    if not title:
        return _fail("create_goal", "title is required")

    category = (action.get("category") or "custom").lower()
    if category not in VALID_GOAL_CATEGORIES:
        category = "custom"

    try:
        target = float(action.get("target") or 0)
    except (TypeError, ValueError):
        target = 0.0
    if target <= 0:
        return _fail("create_goal", "target must be > 0")

    period = (action.get("period") or "quarterly").lower()
    if period not in VALID_GOAL_PERIODS:
        period = "quarterly"

    default_start, default_end = _default_period_range(period)
    start = action.get("start") or default_start
    end = action.get("end") or default_end

    metric = action.get("metric") or _default_metric_for_category(category)
    if metric not in VALID_GOAL_METRICS:
        metric = "custom"

    auto_track = bool(action.get("auto_track", True)) and metric != "custom"

    # Optional free-form context from the practitioner. Lands in the
    # goal card UI + the Custom hero scrapbook. JSONB-stored, no
    # schema migration. Trim and drop empties so the goal row stays
    # clean when no description is provided.
    description_raw = action.get("description")
    description = description_raw.strip() if isinstance(description_raw, str) else ""

    # Optional reminders attached to the new goal. Each is
    # {date: YYYY-MM-DD, message?: str}; we coerce loose inputs.
    reminders_raw = action.get("reminders")
    reminders: List[Dict[str, Any]] = []
    if isinstance(reminders_raw, list):
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        for i, r in enumerate(reminders_raw):
            if not isinstance(r, dict):
                continue
            date_val = (r.get("date") or "").strip()
            if not date_val or len(date_val) < 8:
                continue
            msg = r.get("message")
            entry: Dict[str, Any] = {
                "id": f"rem-{now_ms}-{i}",
                "date": date_val[:10],
                "fired": False,
            }
            if isinstance(msg, str) and msg.strip():
                entry["message"] = msg.strip()
            reminders.append(entry)

    new_goal: Dict[str, Any] = {
        "id": f"goal-{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        "title": title,
        "category": category,
        "target": target,
        "period": period,
        "start": start,
        "end": end,
        "auto_track": auto_track,
        "metric": metric,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if description:
        new_goal["description"] = description
    if reminders:
        new_goal["reminders"] = reminders

    _, settings = await _fetch_business_settings(client, biz_id)
    goals = settings.get("goals") if isinstance(settings.get("goals"), dict) else {}
    active = list(goals.get("active_goals") or [])
    completed = list(goals.get("completed_goals") or [])
    active.append(new_goal)
    next_settings = {
        **settings,
        "goals": {
            **goals,
            "active_goals": active,
            "completed_goals": completed,
        },
    }
    try:
        await _sb(client, "PATCH", f"/businesses?id=eq.{biz_id}", {"settings": next_settings})
    except Exception as e:
        return _fail("create_goal", f"save failed: {e}")

    label_target = f"${int(target):,}" if category == "revenue" else f"{int(target)}"
    # Lens label tells the practitioner which bucket the goal landed
    # in (Personal / Business / Team Building / Custom). Matches the
    # frontend's lensFor() mapping.
    if category in ("contacts", "revenue", "sessions", "engagement", "marketing"):
        lens_label = "Business"
    elif category == "growth":
        lens_label = "Team Building"
    elif category in ("learning", "wellness"):
        lens_label = "Personal"
    else:
        lens_label = "Custom"
    return {
        "type": "create_goal",
        "result": f"created in {lens_label}",
        "label": f"🎯 New {lens_label} goal: {title} — {label_target} by {end}",
        "goal_id": new_goal["id"],
        "nav": _nav("grow", "goals"),
        # Frontend hook — ChiefOfStaff dispatches this as a window
        # CustomEvent. GoalsPanel listens for it and triggers a
        # business refetch so the new goal shows up without a reload.
        "frontend_event": {
            "name": "solutionist-business-refetch",
            "detail": {"reason": "goal_created", "goal_id": new_goal["id"], "lens": lens_label.lower().replace(" ", "_")},
        },
    }


async def handle_add_reminder(client, biz, action) -> Dict:
    """Attach a reminder to an existing goal. The practitioner says
    "remind me about my book goal next Friday" → Chief fuzzy-matches
    the goal by title (or accepts goal_id), then appends a reminder
    entry to settings.goals.active_goals[i].reminders.

    Action shape:
      {
        "type":"add_reminder",
        "goal_id":"goal-...",         # OR
        "goal_title":"Read 12 books", # fuzzy match
        "date":"2026-06-15",          # YYYY-MM-DD
        "message":"Check book #6 progress"  # optional
      }
    """
    biz_id = biz["id"]
    date_val = (action.get("date") or "").strip()
    if not date_val or len(date_val) < 8:
        return _fail("add_reminder", "date is required (YYYY-MM-DD)")
    date_val = date_val[:10]

    msg_raw = action.get("message")
    message = msg_raw.strip() if isinstance(msg_raw, str) else ""

    # Resolve goal — id wins; fall back to title fuzzy-match (lowercase
    # substring, then exact). Returns the index in active_goals.
    _, settings = await _fetch_business_settings(client, biz_id)
    goals = settings.get("goals") if isinstance(settings.get("goals"), dict) else {}
    active = list(goals.get("active_goals") or [])
    if not active:
        return _fail("add_reminder", "no active goals to attach a reminder to")

    goal_id = (action.get("goal_id") or "").strip()
    goal_title = (action.get("goal_title") or "").strip().lower()
    target_idx = -1
    if goal_id:
        for i, g in enumerate(active):
            if g.get("id") == goal_id:
                target_idx = i; break
    if target_idx < 0 and goal_title:
        # Exact (case-insensitive) first, then substring
        for i, g in enumerate(active):
            if (g.get("title") or "").strip().lower() == goal_title:
                target_idx = i; break
        if target_idx < 0:
            for i, g in enumerate(active):
                if goal_title in (g.get("title") or "").strip().lower():
                    target_idx = i; break
    if target_idx < 0:
        return _fail("add_reminder", f"could not find goal matching {goal_id or goal_title or '(none)'}")

    target_goal = active[target_idx]
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    new_reminder: Dict[str, Any] = {
        "id": f"rem-{now_ms}",
        "date": date_val,
        "fired": False,
    }
    if message:
        new_reminder["message"] = message

    existing_reminders = list(target_goal.get("reminders") or [])
    existing_reminders.append(new_reminder)
    active[target_idx] = {**target_goal, "reminders": existing_reminders}

    next_settings = {
        **settings,
        "goals": {**goals, "active_goals": active},
    }
    try:
        await _sb(client, "PATCH", f"/businesses?id=eq.{biz_id}", {"settings": next_settings})
    except Exception as e:
        return _fail("add_reminder", f"save failed: {e}")

    pretty_date = ""
    try:
        from datetime import date as _date_cls
        d = _date_cls.fromisoformat(date_val)
        pretty_date = d.strftime("%b %-d") if hasattr(d, "strftime") else date_val
    except Exception:
        pretty_date = date_val

    return {
        "type": "add_reminder",
        "result": f"reminder added for {pretty_date}",
        "label": f"🔔 Reminder set for {pretty_date} on '{target_goal.get('title')}'",
        "goal_id": target_goal.get("id"),
        "reminder_id": new_reminder["id"],
        "nav": _nav("grow", "goals"),
        "frontend_event": {
            "name": "solutionist-business-refetch",
            "detail": {"reason": "reminder_added", "goal_id": target_goal.get("id")},
        },
    }


async def handle_check_goals(client, biz, action) -> Dict:
    """Summarize progress on every active goal. Computes current values
    from live data the same way the UI does so the Chief can answer
    'how am I doing on my goals' with real numbers."""
    biz_id = biz["id"]
    _, settings = await _fetch_business_settings(client, biz_id)
    goals = settings.get("goals") if isinstance(settings.get("goals"), dict) else {}
    active = goals.get("active_goals") or []
    if not active:
        return {
            "type": "check_goals",
            "result": "no active goals",
            "label": "🎯 No active goals yet — set one in GROW → Goals.",
            "summary": "(no goals)",
            "nav": _nav("grow", "goals"),
            "signal": {"behind": 0, "on_track": 0, "hit": 0, "active": 0},
        }

    # Gather data once
    try:
        contacts = await _sb(client, "GET",
            f"/contacts?business_id=eq.{biz_id}&select=id,created_at,status,last_interaction&limit=2000") or []
        paid_invoices = await _sb(client, "GET",
            f"/invoices?business_id=eq.{biz_id}&status=eq.paid&select=paid_at,total&limit=2000") or []
        invoiced = await _sb(client, "GET",
            f"/invoices?business_id=eq.{biz_id}&select=created_at,total,status&limit=2000") or []
        sessions = await _sb(client, "GET",
            f"/sessions?business_id=eq.{biz_id}&select=scheduled_for,status&limit=2000") or []
    except Exception as e:
        return _fail("check_goals", f"data fetch failed: {e}")

    def _in_range(iso: Optional[str], start: str, end: str) -> bool:
        if not iso:
            return False
        d = iso[:10]
        return start <= d <= end

    def _progress(g: Dict) -> float:
        m = g.get("metric")
        s = g.get("start", "")
        e = g.get("end", "")
        if not g.get("auto_track") or m == "custom":
            try:
                return float(g.get("current_override") or 0)
            except (TypeError, ValueError):
                return 0.0
        if m == "total_contacts":
            return float(sum(1 for c in contacts if (c.get("created_at") or "")[:10] <= e))
        if m == "new_contacts":
            return float(sum(1 for c in contacts if _in_range(c.get("created_at"), s, e)))
        if m == "revenue_collected":
            return float(sum(float(i.get("total") or 0) for i in paid_invoices if _in_range(i.get("paid_at"), s, e)))
        if m == "revenue_invoiced":
            return float(sum(
                float(i.get("total") or 0)
                for i in invoiced
                if _in_range(i.get("created_at"), s, e) and i.get("status") not in ("draft", "cancelled")
            ))
        if m == "sessions_completed":
            return float(sum(1 for x in sessions if x.get("status") == "completed" and _in_range(x.get("scheduled_for"), s, e)))
        if m == "sessions_scheduled":
            return float(sum(1 for x in sessions if _in_range(x.get("scheduled_for"), s, e)))
        if m == "engagement_rate":
            actives = [c for c in contacts if (c.get("status") or "") not in ("inactive", "churned")]
            if not actives:
                return 0.0
            engaged = [c for c in actives if _in_range(c.get("last_interaction"), s, e)]
            return round((len(engaged) / len(actives)) * 100, 1)
        return 0.0

    today_iso = datetime.now(timezone.utc).date().isoformat()
    summary_lines: List[str] = []
    on_track_count = 0
    behind_count = 0
    hit_count = 0
    for g in active:
        target = float(g.get("target") or 0) or 1.0
        current = _progress(g)
        pct = min(100, int((current / target) * 100))
        # rough pace: assume linear
        start_iso = g.get("start") or today_iso
        end_iso = g.get("end") or today_iso
        try:
            total_days = max(1, (date.fromisoformat(end_iso) - date.fromisoformat(start_iso)).days)
            elapsed = max(1, (date.fromisoformat(today_iso) - date.fromisoformat(start_iso)).days)
            elapsed = max(1, min(total_days, elapsed))
            projected = (current / elapsed) * total_days
            on_track = projected >= target or current >= target
        except Exception:
            on_track = pct >= 50

        if current >= target:
            hit_count += 1
            status_emoji = "🎉"
        elif on_track:
            on_track_count += 1
            status_emoji = "✅"
        else:
            behind_count += 1
            status_emoji = "⚠"

        cur_str = (f"${int(current):,}" if g.get("category") == "revenue"
                   else f"{int(current)}%" if g.get("category") == "engagement"
                   else f"{int(current)}")
        tgt_str = (f"${int(target):,}" if g.get("category") == "revenue"
                   else f"{int(target)}%" if g.get("category") == "engagement"
                   else f"{int(target)}")
        summary_lines.append(f"{status_emoji} {g.get('title')}: {cur_str} / {tgt_str} ({pct}%)")

    summary = "\n".join(summary_lines)
    headline_bits: List[str] = []
    if hit_count: headline_bits.append(f"{hit_count} hit")
    if on_track_count: headline_bits.append(f"{on_track_count} on track")
    if behind_count: headline_bits.append(f"{behind_count} behind")
    headline = " · ".join(headline_bits) or "no progress yet"

    return {
        "type": "check_goals",
        "result": headline,
        "label": f"🎯 Goals: {headline}",
        "summary": summary,
        "goals": active,
        "nav": _nav("grow", "goals"),
        "signal": {"behind": behind_count, "on_track": on_track_count,
                   "hit": hit_count, "active": len(active)},
    }


VALID_PLATFORMS = ("instagram", "linkedin", "twitter", "facebook", "tiktok", "youtube", "blog", "other")


async def handle_plan_content(client, biz, action) -> Dict:
    """Add a planned post to settings.content_calendar.planned_posts.
    Now supports pillar tagging (pillar_id or pillar_name fuzzy
    match) and optional reminders. Returns a frontend_event so the
    Content page refetches and the new post shows up immediately.
    """
    biz_id = biz["id"]
    title = (action.get("title") or "").strip()
    if not title:
        return _fail("plan_content", "title is required")

    platform = (action.get("platform") or "instagram").lower()
    if platform not in VALID_PLATFORMS:
        platform = "other"

    scheduled_date = action.get("scheduled_date") or action.get("date") or datetime.now(timezone.utc).date().isoformat()
    if len(scheduled_date) > 10:
        scheduled_date = scheduled_date[:10]

    status_v = (action.get("status") or "planned").lower()
    if status_v not in ("planned", "draft", "posted", "cancelled"):
        status_v = "planned"

    body_raw = action.get("body")
    body = body_raw.strip() if isinstance(body_raw, str) else None

    _, settings = await _fetch_business_settings(client, biz_id)
    cal = settings.get("content_calendar") if isinstance(settings.get("content_calendar"), dict) else {}
    pillars = list(cal.get("pillars") or [])

    # Resolve pillar — id wins; fall back to fuzzy title match
    # (case-insensitive exact, then substring). None if neither.
    pillar_id = (action.get("pillar_id") or "").strip() or None
    pillar_name_raw = (action.get("pillar_name") or "").strip().lower()
    if not pillar_id and pillar_name_raw:
        for p in pillars:
            if (p.get("name") or "").strip().lower() == pillar_name_raw:
                pillar_id = p.get("id"); break
        if not pillar_id:
            for p in pillars:
                if pillar_name_raw in (p.get("name") or "").strip().lower():
                    pillar_id = p.get("id"); break
    resolved_pillar_name = ""
    if pillar_id:
        for p in pillars:
            if p.get("id") == pillar_id:
                resolved_pillar_name = p.get("name") or ""
                break

    # Optional reminders — same shape as the goal-reminder parser.
    reminders_raw = action.get("reminders")
    reminders: List[Dict[str, Any]] = []
    if isinstance(reminders_raw, list):
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        for i, r in enumerate(reminders_raw):
            if not isinstance(r, dict):
                continue
            date_val = (r.get("date") or "").strip()
            if not date_val or len(date_val) < 8:
                continue
            msg = r.get("message")
            entry: Dict[str, Any] = {
                "id": f"rem-{now_ms}-{i}",
                "date": date_val[:10],
                "fired": False,
            }
            if isinstance(msg, str) and msg.strip():
                entry["message"] = msg.strip()
            reminders.append(entry)

    new_post: Dict[str, Any] = {
        "id": f"post-{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        "title": title,
        "body": body,
        "platform": platform,
        "scheduled_date": scheduled_date,
        "status": status_v,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if pillar_id:
        new_post["pillar_id"] = pillar_id
    if reminders:
        new_post["reminders"] = reminders

    planned = list(cal.get("planned_posts") or [])
    posted = list(cal.get("posted") or [])

    # Idempotency. Planning the same post twice appends a twin: the
    # calendar ends up carrying two "The Power of Pausing Before You
    # Respond" on LinkedIn for Wed May 27, and the practitioner deletes
    # one by hand. It happens more than you'd think — a re-asked
    # question, or a dropped stream that makes the client replay the
    # turn (chiefStream returns null when a stream ends without a
    # 'final' event, and ChiefOfStaff then re-POSTs the whole turn,
    # re-executing its actions server-side). Same title + platform +
    # date is the same post, so update it in place.
    #
    # Update rather than skip: the second pass is usually the one
    # carrying the drafted body ("plan it" ... "now write it").
    # Returning the bare existing post would throw that draft away.
    existing_idx = next(
        (i for i, p in enumerate(planned)
         if isinstance(p, dict)
         and (p.get("title") or "").strip().lower() == title.lower()
         and (p.get("platform") or "") == platform
         and (p.get("scheduled_date") or "")[:10] == scheduled_date),
        None,
    )
    was_update = existing_idx is not None
    if was_update:
        merged = dict(planned[existing_idx])
        # Only overwrite with something — a re-plan that omits the body
        # must not blank a draft that is already there.
        if body:
            merged["body"] = body
        if pillar_id:
            merged["pillar_id"] = pillar_id
        if reminders:
            merged["reminders"] = reminders
        merged["status"] = status_v
        merged.setdefault("id", new_post["id"])
        merged.setdefault("created_at", new_post["created_at"])
        planned[existing_idx] = merged
        new_post = merged
    else:
        planned.append(new_post)

    next_settings = {
        **settings,
        "content_calendar": {
            **cal,
            "planned_posts": planned,
            "posted": posted,
        },
    }
    try:
        saved = await _sb(client, "PATCH", f"/businesses?id=eq.{biz_id}", {"settings": next_settings})
    except Exception as e:
        return _fail("plan_content", f"save failed: {e}")

    # _sb does not raise on a rejected write — sb_clients._async_request
    # logs the 4xx/5xx (or the transport timeout) and returns None. The
    # try/except above could therefore never fire, and a write PostgREST
    # refused still reported "📱 Planned linkedin post ..." to the
    # practitioner as done. Confirm the post is in the row we wrote.
    if not _planned_post_present(saved, new_post["id"]):
        # PATCH echoes the updated row back (Prefer: return=representation),
        # so the check above is normally free. If it came back empty or
        # shaped differently, read it back before claiming either way — a
        # false "that failed" over a write that landed is its own lie.
        _, after = await _fetch_business_settings(client, biz_id)
        if not _planned_post_present([{"settings": after}], new_post["id"]):
            return _fail(
                "plan_content",
                "the post was not written to the content calendar — nothing was saved",
            )

    pillar_label = f" · {resolved_pillar_name}" if resolved_pillar_name else ""
    body_label = " (drafted)" if body and len(body) > 30 else ""
    verb = "Updated" if was_update else "Planned"
    return {
        "type": "plan_content",
        "result": f"scheduled for {scheduled_date}{pillar_label}",
        "label": f"📱 {verb} {platform} post: {title}{body_label} — {scheduled_date}{pillar_label}",
        "post_id": new_post["id"],
        "nav": _nav("grow", "content"),
        # Refetch business settings so the new post + any reminders
        # appear on the Content page without a reload.
        "frontend_event": {
            "name": "solutionist-business-refetch",
            "detail": {"reason": "content_planned", "post_id": new_post["id"]},
        },
    }


async def handle_publish_post(client, biz, action) -> Dict:
    """Publish an existing planned post (FB + optional IG) via Meta.

    Resolution priority: post_id (preferred), then post_title fuzzy
    match (case-insensitive exact, then substring). Page is the
    connected Meta page — picks the only one if there's exactly one,
    or matches by page_name when given, else fails with a clear
    "which page?" prompt.

    Action shape:
      {
        "type":"publish_post",
        "post_id":"post-...",         # OR
        "post_title":"Why we raised pricing",  # fuzzy match
        "page_name":"KMJ Creative Solutions",  # optional disambiguator
        "to_instagram": false          # optional, defaults false
      }

    Returns the published URL(s). Flips the post from planned →
    posted in settings.content_calendar.
    """
    from meta_oauth import _publish_facebook, _publish_instagram, _fb_post_url

    biz_id = biz["id"]
    _, settings = await _fetch_business_settings(client, biz_id)
    cal = settings.get("content_calendar") if isinstance(settings.get("content_calendar"), dict) else {}
    planned = list(cal.get("planned_posts") or [])
    posted_list = list(cal.get("posted") or [])

    if not planned:
        return _fail("publish_post", "no planned posts to publish")

    # Resolve post — id wins, then fuzzy title match.
    post_id = (action.get("post_id") or "").strip()
    post_title_raw = (action.get("post_title") or "").strip().lower()
    target_idx = -1
    if post_id:
        for i, p in enumerate(planned):
            if p.get("id") == post_id:
                target_idx = i; break
    if target_idx < 0 and post_title_raw:
        for i, p in enumerate(planned):
            if (p.get("title") or "").strip().lower() == post_title_raw:
                target_idx = i; break
        if target_idx < 0:
            for i, p in enumerate(planned):
                if post_title_raw in (p.get("title") or "").strip().lower():
                    target_idx = i; break
    if target_idx < 0:
        return _fail("publish_post", f"could not find planned post matching {post_id or post_title_raw or '(none)'}")
    post = planned[target_idx]

    message = (post.get("body") or post.get("title") or "").strip()
    if not message:
        return _fail("publish_post", "post has no body or title to publish")

    # Resolve target Page — connected accounts table.
    rows = await _sb(client, "GET",
        f"/social_accounts?business_id=eq.{biz_id}&provider=eq.meta&status=eq.connected"
        f"&select=page_id,page_name,page_token,ig_user_id&order=connected_at.desc") or []
    if not rows:
        return _fail("publish_post", "no Facebook page connected — connect one in Build → Integrations")

    requested_page_name = (action.get("page_name") or "").strip().lower()
    page = None
    if requested_page_name:
        for r in rows:
            if (r.get("page_name") or "").strip().lower() == requested_page_name:
                page = r; break
        if not page:
            for r in rows:
                if requested_page_name in (r.get("page_name") or "").strip().lower():
                    page = r; break
        if not page:
            return _fail("publish_post", f"no connected page matches '{action.get('page_name')}'")
    elif len(rows) == 1:
        page = rows[0]
    else:
        names = ", ".join((r.get("page_name") or r.get("page_id")) for r in rows)
        return _fail("publish_post", f"multiple pages connected — specify page_name (options: {names})")

    page_token = page.get("page_token")
    if not page_token:
        return _fail("publish_post", "page token missing — reconnect needed")

    to_instagram = bool(action.get("to_instagram", False))
    ig_user_id = page.get("ig_user_id")
    image_url = post.get("image_url") or None

    # ── The unattended gate ──────────────────────────────────────────
    # Checked AFTER the Page is resolved, because an approval names a
    # Page and there is nothing to compare against until this run has
    # picked one.
    #
    # `_unattended` is set by chief_scheduler on every run it makes, and
    # is overwritten there rather than read from the stored payload — a
    # schedule that could claim to be prompted would be a schedule that
    # approves itself.
    #
    # The prompted path never reaches this. A practitioner asking for
    # the post IS the approval, and this must not stand between them and
    # their own work.
    if action.get("_unattended"):
        import post_approval
        held = post_approval.refusal(post, page_id=page.get("page_id") or "",
                                     to_instagram=to_instagram)
        if held:
            return _fail("publish_post", held)

    if to_instagram and not ig_user_id:
        return _fail("publish_post", "Instagram not linked to that Page — link IG Business account first")
    if to_instagram and not image_url:
        return _fail("publish_post", "Instagram publishing requires an image — add image_url to the post first")

    # ── Facebook publish ──
    try:
        fb_result = await _publish_facebook(client, page["page_id"], page_token, message, image_url)
    except HTTPException as e:
        # Mark connection expired on auth errors.
        if "190" in str(e.detail) or "OAuth" in str(e.detail):
            await _sb(client, "PATCH",
                f"/social_accounts?business_id=eq.{biz_id}&page_id=eq.{page['page_id']}",
                {"status": "expired", "last_error": str(e.detail)[:300]})
        return _fail("publish_post", f"FB publish failed: {e.detail}")
    fb_url = _fb_post_url(page["page_id"], fb_result)

    # ── Instagram publish (optional) ──
    ig_url = None
    if to_instagram:
        try:
            await _publish_instagram(client, ig_user_id, page_token, message, image_url)
        except HTTPException as e:
            # Partial success — FB went, IG didn't. Surface clearly.
            return {
                "type": "publish_post",
                "result": f"published to {page.get('page_name')} (IG failed)",
                "label": f"📱 Posted to Facebook — IG failed: {str(e.detail)[:120]}",
                "ok": False,
                "facebook_url": fb_url,
                "nav": _nav("grow", "content"),
                "frontend_event": {
                    "name": "solutionist-business-refetch",
                    "detail": {"reason": "content_published_partial", "post_id": post.get("id")},
                },
            }

    # ── Move planned → posted, attach URL ──
    posted_post = {
        **post,
        "status": "posted",
        "posted_date": datetime.now(timezone.utc).date().isoformat(),
    }
    if fb_url:
        posted_post["published_url"] = fb_url
    posted_post["published_to_page_id"] = page["page_id"]
    planned.pop(target_idx)
    posted_list.append(posted_post)
    next_settings = {
        **settings,
        "content_calendar": {
            **cal,
            "planned_posts": planned,
            "posted": posted_list,
        },
    }
    try:
        await _sb(client, "PATCH", f"/businesses?id=eq.{biz_id}", {"settings": next_settings})
    except Exception as e:
        logger.warning(f"publish_post: post shipped but local update failed: {e}")

    target_label = f"{page.get('page_name')}"
    if to_instagram:
        target_label += " + Instagram"
    return {
        "type": "publish_post",
        "result": f"published to {target_label}",
        "label": f"📱 Published to {target_label}: {post.get('title')}",
        "ok": True,
        "facebook_url": fb_url,
        "instagram_url": ig_url,
        "nav": _nav("grow", "content"),
        "frontend_event": {
            "name": "solutionist-business-refetch",
            "detail": {"reason": "content_published", "post_id": post.get("id"), "url": fb_url},
        },
    }


async def handle_publish_to_site(client, biz, action) -> Dict:
    """Publish a planned post to the business's OWN news feed.

    The destination nobody can revoke: their domain, our server, no
    third party's terms, no audience pushed at, and removing the post
    removes the page. That is what makes this the one publishing verb
    the autonomy dial may speak for — see site_publish.py.

    Action shape:
      {"type":"publish_to_site", "post_id":"post-..."}   # or post_title
    """
    import site_news
    import site_publish

    biz_id = biz["id"]
    _, settings = await _fetch_business_settings(client, biz_id)
    cal = settings.get("content_calendar") if isinstance(settings.get("content_calendar"), dict) else {}
    planned = list(cal.get("planned_posts") or [])
    posted_list = list(cal.get("posted") or [])
    if not planned:
        return _fail("publish_to_site", "no planned posts to publish")

    post_id = (action.get("post_id") or "").strip()
    title_raw = (action.get("post_title") or "").strip().lower()
    idx = -1
    if post_id:
        idx = next((i for i, p in enumerate(planned) if p.get("id") == post_id), -1)
    if idx < 0 and title_raw:
        idx = next((i for i, p in enumerate(planned)
                    if (p.get("title") or "").strip().lower() == title_raw), -1)
    if idx < 0:
        return _fail("publish_to_site",
                     f"could not find planned post matching {post_id or title_raw or '(none)'}")
    post = planned[idx]

    title = (post.get("title") or "").strip()
    body = (post.get("body") or "").strip()
    if not title or not body:
        # site_news.normalize_posts drops anything missing either, so a
        # half-filled post would publish to a page that renders nothing.
        return _fail("publish_to_site", "a post needs both a headline and a body to go on the site")

    # ── The unattended gate ──
    # Same rule as publish_post, with the one exemption the owner can
    # turn on for their own website. exempt_from_approval checks the
    # verb as well as the dial, so this cannot be reached by passing a
    # social verb through the same door.
    if action.get("_unattended") and not site_publish.exempt_from_approval(
            "publish_to_site", settings):
        import post_approval
        held = post_approval.refusal(post, page_id="", to_instagram=False)
        if held:
            return _fail("publish_to_site", held)

    website_content = settings.get("website_content") if isinstance(settings.get("website_content"), dict) else {}
    news = list(website_content.get("news") or [])
    entry = {
        "id": f"news-{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        "title": title,
        "body": body,
        "image_url": post.get("image_url") or None,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "slug": site_news.slugify(title),
    }
    news.insert(0, entry)

    posted_post = {**post, "status": "posted",
                   "posted_date": datetime.now(timezone.utc).date().isoformat()}
    planned.pop(idx)
    posted_list.append(posted_post)

    next_settings = {
        **settings,
        "website_content": {**website_content, "news": news},
        "content_calendar": {**cal, "planned_posts": planned, "posted": posted_list},
    }
    try:
        await _sb(client, "PATCH", f"/businesses?id=eq.{biz_id}", {"settings": next_settings})
    except Exception as e:
        return _fail("publish_to_site", f"could not save the post: {e}")

    return {
        "type": "publish_to_site",
        "result": f"published '{title}' to the news page on your own site",
        "label": f"🌐 Published to your site: {title[:70]}",
        "ok": True,
        "nav": _nav("grow", "content"),
        "frontend_event": {
            "name": "solutionist-business-refetch",
            "detail": {"reason": "site_news_published", "post_id": post.get("id")},
        },
    }


async def handle_capture_idea(client, biz, action) -> Dict:
    """Drop a half-formed content idea into the Idea Inbox. Lighter
    than plan_content — no scheduled date or platform required, just
    title + optional notes + optional pillar. The practitioner can
    promote it to a scheduled post later from the UI.

    Action shape:
      {
        "type":"capture_idea",
        "title":"5 lessons from the launch",     # required
        "notes":"focus on what we'd do differently", # optional
        "pillar_id":"pillar-...",                # optional
        "pillar_name":"Client Wins"              # optional fuzzy match
      }
    """
    biz_id = biz["id"]
    title = (action.get("title") or "").strip()
    if not title:
        return _fail("capture_idea", "title is required")

    notes_raw = action.get("notes")
    notes = notes_raw.strip() if isinstance(notes_raw, str) else ""

    _, settings = await _fetch_business_settings(client, biz_id)
    cal = settings.get("content_calendar") if isinstance(settings.get("content_calendar"), dict) else {}
    pillars = list(cal.get("pillars") or [])

    pillar_id = (action.get("pillar_id") or "").strip() or None
    pillar_name_raw = (action.get("pillar_name") or "").strip().lower()
    if not pillar_id and pillar_name_raw:
        for p in pillars:
            if (p.get("name") or "").strip().lower() == pillar_name_raw:
                pillar_id = p.get("id"); break
        if not pillar_id:
            for p in pillars:
                if pillar_name_raw in (p.get("name") or "").strip().lower():
                    pillar_id = p.get("id"); break
    resolved_pillar_name = ""
    if pillar_id:
        for p in pillars:
            if p.get("id") == pillar_id:
                resolved_pillar_name = p.get("name") or ""
                break

    new_idea: Dict[str, Any] = {
        "id": f"idea-{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        "title": title,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if notes:
        new_idea["notes"] = notes
    if pillar_id:
        new_idea["pillar_id"] = pillar_id

    idea_inbox = list(cal.get("idea_inbox") or [])
    idea_inbox.append(new_idea)
    next_settings = {
        **settings,
        "content_calendar": {
            **cal,
            "idea_inbox": idea_inbox,
        },
    }
    try:
        await _sb(client, "PATCH", f"/businesses?id=eq.{biz_id}", {"settings": next_settings})
    except Exception as e:
        return _fail("capture_idea", f"save failed: {e}")

    pillar_label = f" · {resolved_pillar_name}" if resolved_pillar_name else ""
    return {
        "type": "capture_idea",
        "result": f"added to Idea Inbox{pillar_label}",
        "label": f"💡 Idea captured: {title}{pillar_label}",
        "idea_id": new_idea["id"],
        "nav": _nav("grow", "content"),
        "frontend_event": {
            "name": "solutionist-business-refetch",
            "detail": {"reason": "content_idea_captured", "idea_id": new_idea["id"]},
        },
    }
