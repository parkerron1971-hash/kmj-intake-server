"""
chief_strategy_actions.py — the Strategy Track, and the standing handlers
that grew beside it.

Split out of chief_of_staff.py on 2026-09-04 ("split the monolith along
the registry", the Astra brief). This was the largest fully
self-contained family still inside the 19,000-line file: eighteen
verbs, their own constants and private helpers, and no shared turn
state — it reached back into chief_of_staff for exactly four things
(_sb, _fail, _nav, _call_claude) plus the handler registry, all of
which it reaches at call time through chief_host, the way
chief_time_actions and chief_sms_actions already do. Nothing about
any verb's behaviour changed; the bodies are byte-identical.

WHY DELEGATE INSTEAD OF COPY. chief_time_actions carries its own
_fail; that copy has already drifted from chief_of_staff's (which
genericises anything that looks technical before it reaches the
practitioner). Resolving the real helper at call time keeps one
definition, keeps every test that monkeypatches `cos._sb` working for
these handlers, and costs one attribute lookup.

WHAT LIVES HERE
  The Strategy Track (save_phase / advance_phase, the eight phase
  deliverables, session_summary, complete_strategy_track and the site +
  module seeding it triggers), the business picture (set_business_policy,
  add_faq), scheduling (schedule_action, cancel_scheduled,
  list_scheduled, notify_practitioner), and three site/insight reads
  and runs (site_health, restore_previous_site, analyze_trends,
  run_market_research).

REGISTRATION. chief_of_staff imports every handle_* by name, so
`chief_of_staff.handle_save_phase` is still the same function object
this module defines — monkeypatchable and getsource-able through either
name. __tests__/test_action_registry.py pins that every registered
verb has exactly one definition and is reachable as a chief_of_staff
attribute.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import sb_clients
import business_profile_agent

# Same logger name as the file this came from, so nothing about log
# capture or the Railway filters changes.
logger = logging.getLogger("chief_of_staff")


# The host helpers resolve into chief_of_staff at call time — see chief_host.
from chief_host import _sb, _fail, _nav, _call_claude, _handlers


# ═══════════════════════════════════════════════════════════════════════
# STRATEGY TRACK HANDLERS
# ═══════════════════════════════════════════════════════════════════════

STRATEGY_PHASES = [
    "discovery", "market_research", "business_model", "pricing_strategy",
    "service_packages", "financial_projections", "swot", "launch_plan",
]

# Map a phase to the column it lives in (phases is a catch-all for unstructured phases)
STRATEGY_PHASE_COLUMN = {
    "discovery": "phases",
    "market_research": "market_research",
    "business_model": "business_model",
    "pricing_strategy": "pricing_strategy",
    "service_packages": "service_packages",
    "financial_projections": "financial_projections",
    "swot": "swot",
    "launch_plan": "launch_plan",
}


async def _get_or_create_strategy_track(client, biz_id: str) -> Optional[Dict]:
    rows = await _sb(client, "GET",
        f"/strategy_tracks?business_id=eq.{biz_id}&order=created_at.desc&limit=1&select=*")
    if rows:
        return rows[0]
    created = await _sb(client, "POST", "/strategy_tracks", {
        "business_id": biz_id,
        "status": "in_progress",
        "current_phase": "discovery",
        "phases": {},
    })
    return (created or [None])[0] if isinstance(created, list) else created


async def handle_save_phase(client, biz, action) -> Dict:
    """Save a phase deliverable. For structured phases (market_research,
    business_model, etc.) the data lands in the dedicated column. For
    discovery it goes into phases.discovery."""
    phase = (action.get("phase") or "").lower().strip()
    data = action.get("data")
    if phase not in STRATEGY_PHASES:
        return _fail("save_phase", f"unknown phase '{phase}'")
    if data is None:
        return _fail("save_phase", "data required")

    track = await _get_or_create_strategy_track(client, biz["id"])
    if not track:
        return _fail("save_phase", "could not load strategy track")

    column = STRATEGY_PHASE_COLUMN[phase]
    patch: Dict[str, Any] = {}

    if column == "phases":
        phases = dict(track.get("phases") or {})
        phases[phase] = data
        patch["phases"] = phases
    else:
        patch[column] = data

    await _sb(client, "PATCH", f"/strategy_tracks?id=eq.{track['id']}", patch)
    return {
        "type": "save_phase",
        "result": "saved",
        "label": f"Saved {phase.replace('_', ' ')} deliverable",
        "nav": {"tab": "build", "page": "strategy-track"},
    }


async def handle_advance_phase(client, biz, action) -> Dict:
    to_phase = (action.get("to") or "").lower().strip()
    if to_phase not in STRATEGY_PHASES:
        return _fail("advance_phase", f"unknown phase '{to_phase}'")
    track = await _get_or_create_strategy_track(client, biz["id"])
    if not track:
        return _fail("advance_phase", "could not load strategy track")
    await _sb(client, "PATCH", f"/strategy_tracks?id=eq.{track['id']}",
              {"current_phase": to_phase})
    return {
        "type": "advance_phase",
        "result": "advanced",
        "label": f"Now on: {to_phase.replace('_', ' ').title()}",
        "nav": {"tab": "build", "page": "strategy-track"},
    }


async def handle_notify_practitioner(client, biz, action) -> Dict:
    """Adaptive-Chief primitive (2026-07-10): a message to the OWNER —
    in-app notification + push. The 'remind me' verb, and the delivery
    leg of any scheduled action that just needs to say something."""
    title = str(action.get("title") or action.get("message") or "").strip()
    body = str(action.get("body") or "").strip()
    if not title:
        return _fail("notify_practitioner", "title (or message) required")
    await _sb(client, "POST", "/chief_notifications", {
        "business_id": biz["id"], "type": "reminder",
        "title": title[:120], "body": body[:300] or title[:300],
        "priority": "normal",
    })
    owner = biz.get("owner_id")
    if owner:
        try:
            import push_notifications
            await asyncio.to_thread(
                push_notifications.send_to_user, str(owner),
                title=title[:80], body=(body or title)[:160], nav="home")
        except Exception as e:  # push is best-effort
            logger.warning(f"notify push failed (non-fatal): {e}")
    return {"type": "notify_practitioner",
            "result": f"notification sent: {title[:80]}",
            "label": f"🔔 {title[:80]}", "nav": None}


# Verbs that cannot run server-side later (live-client-only) or would
# nest the scheduler into itself.
_UNSCHEDULABLE = {"navigate", "set_timer", "schedule_action",
                  "cancel_scheduled", "list_scheduled", "set_chat_window"}


async def handle_schedule_action(client, biz, action) -> Dict:
    """Adaptive-Chief meta-verb (2026-07-10, Kevin's directive: "Chief
    should do anything within the system, even things never built"):
    schedule ANY toolkit action for later — one-shot or recurring. One
    primitive × the whole verb set = 'remind me tomorrow', 'text Marcus
    Friday 9am', 'send the report every Monday' with zero new code."""
    inner = action.get("action") if isinstance(action.get("action"), dict) else None
    if not inner or not str(inner.get("type") or "").strip():
        return _fail("schedule_action", "an inner action {type: ...} is required")
    itype = str(inner.get("type")).strip()
    if itype in _UNSCHEDULABLE:
        return _fail("schedule_action", f"'{itype}' can't be scheduled "
                     f"(client-only or self-nesting)")
    if itype not in _handlers():
        return _fail("schedule_action", f"unknown action '{itype}'")

    run_at_raw = str(action.get("run_at") or "").strip()
    run_at: Optional[datetime] = None
    if run_at_raw:
        try:
            run_at = datetime.fromisoformat(run_at_raw.replace("Z", "+00:00"))
            if run_at.tzinfo is None:
                run_at = run_at.replace(tzinfo=timezone.utc)
        except ValueError:
            return _fail("schedule_action", f"run_at not ISO-8601: {run_at_raw}")
    elif action.get("in_minutes") is not None:
        try:
            mins = max(1, int(action["in_minutes"]))
        except (TypeError, ValueError):
            return _fail("schedule_action", "in_minutes must be a number")
        run_at = datetime.now(timezone.utc) + timedelta(minutes=mins)
    if not run_at:
        return _fail("schedule_action", "need run_at (ISO) or in_minutes")
    if run_at <= datetime.now(timezone.utc) - timedelta(minutes=1):
        return _fail("schedule_action", "run_at is in the past")

    recurrence = str(action.get("recurrence") or "").strip().lower() or None
    if recurrence and recurrence not in ("daily", "weekdays", "weekly"):
        return _fail("schedule_action",
                     "recurrence must be daily, weekdays, or weekly")
    label = str(action.get("label") or "").strip() or f"Scheduled: {itype}"

    row = await asyncio.to_thread(sb_clients.sb_post_as_service,
        "/chief_scheduled_actions", {
            "business_id": biz["id"], "owner_id": biz.get("owner_id"),
            "label": label[:120], "action": inner,
            "run_at": run_at.isoformat(), "recurrence": recurrence,
        })
    if not row:
        return _fail("schedule_action", "could not save the schedule")
    when = run_at.strftime("%Y-%m-%d %H:%M UTC")
    rec = f", repeating {recurrence}" if recurrence else ""
    return {"type": "schedule_action",
            "result": f"scheduled '{label}' for {when}{rec} — I'll notify "
                      f"you with the outcome when it runs",
            "label": f"⏰ Scheduled: {label[:70]} ({when}{rec})",
            "nav": None}


async def handle_cancel_scheduled(client, biz, action) -> Dict:
    """Cancel a queued scheduled action by id or label match."""
    sid = str(action.get("schedule_id") or "").strip()
    label = str(action.get("label") or "").strip()
    if not sid and not label:
        return _fail("cancel_scheduled", "need schedule_id or label")
    q = f"/chief_scheduled_actions?business_id=eq.{biz['id']}&status=eq.queued"
    if sid:
        q += f"&id=eq.{sid}"
    else:
        safe = label.replace("%", "").replace("*", "")
        q += f"&label=ilike.*{safe}*"
    rows = await asyncio.to_thread(sb_clients.sb_get_as_service,
                                   q + "&select=id,label&limit=5") or []
    if not rows:
        return _fail("cancel_scheduled", "no matching queued schedule")
    for r in rows:
        await asyncio.to_thread(sb_clients.sb_patch_as_service,
            f"/chief_scheduled_actions?id=eq.{r['id']}",
            {"status": "cancelled"})
    names = ", ".join(str(r.get("label") or "")[:40] for r in rows)
    return {"type": "cancel_scheduled",
            "result": f"cancelled {len(rows)} schedule(s): {names}",
            "label": f"🗑 Cancelled: {names[:80]}", "nav": None}


async def handle_list_scheduled(client, biz, action) -> Dict:
    """What's on Chief's calendar for this business."""
    rows = await asyncio.to_thread(sb_clients.sb_get_as_service,
        f"/chief_scheduled_actions?business_id=eq.{biz['id']}"
        "&status=eq.queued&order=run_at.asc&limit=20"
        "&select=id,label,run_at,recurrence") or []
    if not rows:
        return {"type": "list_scheduled", "result": "nothing scheduled",
                "label": "📅 No scheduled actions", "nav": None}
    lines = "; ".join(
        f"{str(r.get('label') or '')[:50]} @ {str(r.get('run_at') or '')[:16]}"
        + (f" ({r['recurrence']})" if r.get("recurrence") else "")
        + f" [id={str(r.get('id'))[:8]}]"
        for r in rows)
    return {"type": "list_scheduled",
            "result": f"{len(rows)} scheduled: {lines}",
            "label": f"📅 {len(rows)} scheduled action(s)", "nav": None}


_VALID_POLICY_KEYS = {"cancellation", "deposit", "lateness", "refunds", "no_show"}


async def _save_business_picture(client, biz, mutate) -> Dict[str, Any]:
    """Read-modify-write settings.business_picture (Arc S). `mutate`
    receives the picture dict and edits in place. Updates biz in-memory
    so same-turn reads see the change."""
    settings = dict(biz.get("settings") or {})
    bp = dict(settings.get("business_picture") or {})
    mutate(bp)
    settings["business_picture"] = bp
    await _sb(client, "PATCH", f"/businesses?id=eq.{biz['id']}",
              {"settings": settings})
    biz["settings"] = settings
    return bp


async def handle_set_business_policy(client, biz, action) -> Dict:
    """Arc S Business Picture — capture a rule of engagement. Feeds the
    website FAQ automatically AND becomes what Chief answers when a
    client asks (including by text)."""
    key = (str(action.get("policy") or "").strip().lower()
           .replace("-", "_").replace(" ", "_"))
    text = str(action.get("text") or action.get("value") or "").strip()
    if key not in _VALID_POLICY_KEYS:
        return _fail("set_business_policy",
                     f"policy must be one of {sorted(_VALID_POLICY_KEYS)}")
    if not text:
        return _fail("set_business_policy", "policy text required")

    def _mut(bp):
        pol = dict(bp.get("policies") or {})
        pol[key] = text[:600]
        bp["policies"] = pol

    await _save_business_picture(client, biz, _mut)
    label_key = key.replace("_", "-")
    return {"type": "set_business_policy",
            "result": (f"{label_key} policy saved — it now appears in the "
                       f"website FAQ and I'll answer clients with it"),
            "label": f"📋 {label_key.title()} policy saved",
            "nav": None}


async def handle_add_faq(client, biz, action) -> Dict:
    """Arc S Business Picture — add an owner-authored Q&A. Renders on
    the website FAQ; Chief answers clients with it."""
    q = str(action.get("question") or "").strip()
    a = str(action.get("answer") or "").strip()
    if not q or not a:
        return _fail("add_faq", "both question and answer are required")

    def _norm(s):
        return " ".join(s.lower().split()).strip("?.! ")

    replaced = {"v": False}

    def _mut(bp):
        rows = [r for r in (bp.get("faq") or []) if isinstance(r, dict)]
        kept = []
        for r in rows:
            if _norm(str(r.get("q") or "")) == _norm(q):
                replaced["v"] = True
                continue   # same question → the new answer replaces it
            kept.append(r)
        kept.append({"q": q[:200], "a": a[:600]})
        bp["faq"] = kept[-12:]   # newest 12 keep their seats

    await _save_business_picture(client, biz, _mut)
    verb = "updated" if replaced["v"] else "added"
    return {"type": "add_faq",
            "result": f"FAQ {verb}: \"{q[:80]}\" — live on the website FAQ "
                      f"and in my answers to clients",
            "label": f"❓ FAQ {verb}: {q[:60]}",
            "nav": None}


async def handle_site_health(client, biz, action) -> Dict:
    """Site self-heal (Kevin's directive, 2026-07-10: "make sure Chief
    can fix the things practitioners run into"): one sweep over
    everything that commonly goes wrong with a composed site, each
    issue named WITH its fix. Read-only — the fixes ride existing verbs
    (refine rebuild, restore_previous_site, availability save)."""
    def _read():
        return sb_clients.sb_get_as_service(
            f"/business_sites?business_id=eq.{biz['id']}"
            "&select=site_config,html_content,status&limit=1") or []
    rows = await asyncio.to_thread(_read)
    if not rows:
        return _fail("site_health", "no site yet — compose one first")
    site = rows[0]
    cfg = site.get("site_config") or {}
    htmlc = site.get("html_content") or ""
    issues: List[str] = []
    healthy: List[str] = []

    for c in ((cfg.get("quality_report") or {}).get("checks") or []):
        if not c.get("ok"):
            issues.append(f"gate '{c.get('name')}': {str(c.get('detail'))[:110]}")
    if not any(i.startswith("gate") for i in issues):
        healthy.append("quality gate clean")

    if cfg.get("dro_failure"):
        issues.append("last compose ran WITHOUT its design brief "
                      f"({str((cfg.get('dro_failure') or {}).get('detail'))[:80]}) "
                      "— fix: run a recompose (refine keeps the current look)")
    if "/public/booking/" in htmlc:
        issues.append("the site carries the OLD booking link — fix: a "
                      "refine recompose re-stamps the current /book link")
    try:
        from booking_widget_router import booking_is_live
        _settings = biz.get("settings") or {}
        _av = (_settings.get("availability")
               if isinstance(_settings.get("availability"), dict) else {})
        if booking_is_live(biz["id"], _settings) and not _av.get("timezone"):
            issues.append("booking hours carry no timezone (slots can show "
                          "shifted times) — fix: open Availability and Save once")
    except Exception:
        pass
    if cfg.get("previous_compose"):
        healthy.append("a previous design is banked (\"go back\" works)")
    if site.get("status") != "published":
        issues.append(f"site status is '{site.get('status')}' — not published")

    if not issues:
        return {"type": "site_health",
                "result": "site healthy — " + "; ".join(healthy or ["no known issues"]),
                "label": "✅ Site health: clean", "nav": _nav("build"),
                "signal": {"issues": 0}}
    listing = " | ".join(issues[:6]) + (f" (+{len(issues) - 6} more)"
                                        if len(issues) > 6 else "")
    return {"type": "site_health",
            "result": f"{len(issues)} issue(s) found: {listing}",
            "label": f"🩺 Site health: {len(issues)} issue(s)",
            "nav": _nav("build"),
            "signal": {"issues": len(issues)}}


async def handle_restore_previous_site(client, biz, action) -> Dict:
    """Compose safety net (2026-07-10) — swap the live site back to the
    previous full-compose design. Trust discipline: owner-scoped, no
    external effects, fully reversible (the swap is symmetric — asking
    again switches back). The undo for a redesign roll the owner hates."""
    import site_composer
    try:
        res = await asyncio.to_thread(
            site_composer.restore_previous_compose, biz["id"])
    except Exception as e:
        return _fail("restore_previous_site", f"restore failed: {e}")
    if not isinstance(res, dict) or not res.get("ok"):
        return _fail("restore_previous_site",
                     (res or {}).get("error") or "restore failed")
    return {"type": "restore_previous_site",
            "result": ("previous design restored and live — ask me again "
                       "any time to swap back"),
            "label": "⏪ Previous site design restored",
            "nav": _nav("build")}


async def handle_analyze_trends(client, biz, action) -> Dict:
    """Chief Layers arc — on-demand longitudinal analysis ("how's my
    business trending?"). Runs the weekly insight engine now, bypassing
    the cadence but never the eligibility gate. Per-business data only;
    writes insight memories + an activity row; nothing external sends."""
    import chief_insights
    try:
        res = await asyncio.to_thread(
            chief_insights.run_for_business, biz["id"], True)
    except Exception as e:
        return _fail("analyze_trends", f"analysis failed: {e}")
    if not isinstance(res, dict) or not res.get("ok"):
        return _fail("analyze_trends",
                     (res or {}).get("error") or "analysis failed")
    if res.get("skipped") == "not_enough_history":
        return {
            "type": "analyze_trends",
            "result": ("not enough history yet — the analysis needs a few "
                       "weeks of sessions or paid invoices to find real patterns"),
            "label": "Trend analysis: not enough history yet",
            "nav": None,
        }
    insights = res.get("insights") or []
    if not insights:
        return {
            "type": "analyze_trends",
            "result": ("analysis ran across the last 12 weeks — no significant "
                       "NEW patterns beyond the longitudinal insights already "
                       "in your context"),
            "label": "Trend analysis: no new patterns",
            "nav": None,
        }
    summary = " | ".join(
        f"{i.get('pattern')} Move: {i.get('move')}" for i in insights)
    return {
        "type": "analyze_trends",
        "result": f"{len(insights)} new insight(s): {summary}",
        "label": f"Analyzed 12 weeks of trends — {len(insights)} new insight(s)",
        "nav": None,
    }


async def handle_run_market_research(client, biz, action) -> Dict:
    """v1: synthesize market analysis from an AI plan. v2 will integrate
    real web search. The Chief passes queries it would run; we use them
    as prompt context so the AI produces realistic, grounded output."""
    queries = action.get("queries") or []
    if isinstance(queries, str):
        queries = [queries]
    if not isinstance(queries, list) or not queries:
        return _fail("run_market_research", "queries array required")

    voice = biz.get("voice_profile") or {}
    audience = voice.get("audience") or "unspecified audience"
    practitioner = (biz.get("settings") or {}).get("practitioner_name", "the practitioner")
    biz_name = biz.get("name", "the business")
    biz_type = biz.get("type", "general")
    custom_type = (biz.get("settings") or {}).get("custom_type") or ""

    system = (
        "You are a market analyst generating a grounded, realistic market-research summary "
        "for a practitioner launching a new business. Use typical knowledge of the industry, "
        "likely competitors in their area, standard pricing ranges, and common gaps. Be honest "
        "about challenges. Return STRICT JSON only, no prose outside JSON."
    )
    user_msg = (
        f"Business: {biz_name}\nType: {biz_type}{f' ({custom_type})' if custom_type else ''}\n"
        f"Practitioner: {practitioner}\nAudience: {audience}\n\n"
        f"Search queries the Chief wanted to run:\n" + "\n".join(f"- {q}" for q in queries) + "\n\n"
        "Produce JSON with this exact shape:\n"
        "{\n"
        "  \"competitors\": [{\"name\": str, \"url\": str, \"pricing\": str, \"offerings\": str, \"strengths\": str, \"weaknesses\": str}, ...],\n"
        "  \"market_trends\": str,\n"
        "  \"gaps\": str,\n"
        "  \"local_demand\": str\n"
        "}\n"
        "Return 3-5 competitors. Keep each string concise."
    )
    raw = await _call_claude(client, system, [{"role": "user", "content": user_msg}], max_tokens=1600)
    if not raw:
        return _fail("run_market_research", "AI synthesis failed")

    parsed: Optional[Dict] = None
    try:
        s = raw.find("{")
        e = raw.rfind("}")
        if s >= 0 and e > s:
            parsed = json.loads(raw[s:e + 1])
    except json.JSONDecodeError:
        parsed = None
    if not parsed:
        return _fail("run_market_research", "AI returned unparseable JSON")

    track = await _get_or_create_strategy_track(client, biz["id"])
    if not track:
        return _fail("run_market_research", "could not load strategy track")
    await _sb(client, "PATCH", f"/strategy_tracks?id=eq.{track['id']}",
              {"market_research": parsed})

    comp_count = len(parsed.get("competitors") or [])
    return {
        "type": "run_market_research",
        "result": f"found {comp_count} competitors",
        "label": "Market research completed",
        "nav": {"tab": "build", "page": "strategy-track"},
        "research": parsed,
    }


async def handle_save_business_model(client, biz, action) -> Dict:
    canvas = action.get("canvas") or action.get("data")
    if not isinstance(canvas, dict):
        return _fail("save_business_model", "canvas object required")
    track = await _get_or_create_strategy_track(client, biz["id"])
    if not track:
        return _fail("save_business_model", "could not load strategy track")
    await _sb(client, "PATCH", f"/strategy_tracks?id=eq.{track['id']}",
              {"business_model": canvas})
    return {
        "type": "save_business_model",
        "result": "saved",
        "label": "Business Model Canvas saved",
        "nav": {"tab": "build", "page": "strategy-track"},
    }


async def handle_save_pricing(client, biz, action) -> Dict:
    payload: Dict[str, Any] = {}
    if "tiers" in action:
        payload["tiers"] = action["tiers"]
    if "rationale" in action:
        payload["rationale"] = action["rationale"]
    if "comparison" in action:
        payload["comparison"] = action["comparison"]
    if not payload:
        payload = action.get("data") or {}
    if not payload:
        return _fail("save_pricing", "pricing payload required")
    track = await _get_or_create_strategy_track(client, biz["id"])
    if not track:
        return _fail("save_pricing", "could not load strategy track")
    # Merge so rationale/comparison can land in separate turns
    merged = {**(track.get("pricing_strategy") or {}), **payload}
    await _sb(client, "PATCH", f"/strategy_tracks?id=eq.{track['id']}",
              {"pricing_strategy": merged})
    return {
        "type": "save_pricing",
        "result": "saved",
        "label": "Pricing strategy saved",
        "nav": {"tab": "build", "page": "strategy-track"},
    }


async def handle_save_packages(client, biz, action) -> Dict:
    packages = action.get("packages") or action.get("data")
    if not isinstance(packages, list):
        return _fail("save_packages", "packages array required")
    track = await _get_or_create_strategy_track(client, biz["id"])
    if not track:
        return _fail("save_packages", "could not load strategy track")
    await _sb(client, "PATCH", f"/strategy_tracks?id=eq.{track['id']}",
              {"service_packages": packages})
    return {
        "type": "save_packages",
        "result": f"{len(packages)} packages saved",
        "label": "Service packages saved",
        "nav": {"tab": "build", "page": "strategy-track"},
    }


async def handle_save_projections(client, biz, action) -> Dict:
    payload: Dict[str, Any] = {}
    for k in ("scenarios", "expenses", "break_even", "monthly_net", "notes"):
        if k in action:
            payload[k] = action[k]
    if not payload:
        payload = action.get("data") or {}
    if not payload:
        return _fail("save_projections", "projections payload required")
    track = await _get_or_create_strategy_track(client, biz["id"])
    if not track:
        return _fail("save_projections", "could not load strategy track")
    merged = {**(track.get("financial_projections") or {}), **payload}
    await _sb(client, "PATCH", f"/strategy_tracks?id=eq.{track['id']}",
              {"financial_projections": merged})
    return {
        "type": "save_projections",
        "result": "saved",
        "label": "Financial projections saved",
        "nav": {"tab": "build", "page": "strategy-track"},
    }


async def handle_save_swot(client, biz, action) -> Dict:
    payload: Dict[str, Any] = {}
    for k in ("strengths", "weaknesses", "opportunities", "threats"):
        if k in action:
            payload[k] = action[k]
    if not payload:
        payload = action.get("data") or {}
    if not payload:
        return _fail("save_swot", "swot payload required")
    track = await _get_or_create_strategy_track(client, biz["id"])
    if not track:
        return _fail("save_swot", "could not load strategy track")
    merged = {**(track.get("swot") or {}), **payload}
    await _sb(client, "PATCH", f"/strategy_tracks?id=eq.{track['id']}",
              {"swot": merged})
    return {
        "type": "save_swot",
        "result": "saved",
        "label": "SWOT analysis saved",
        "nav": {"tab": "build", "page": "strategy-track"},
    }


async def handle_save_launch_plan(client, biz, action) -> Dict:
    weeks = action.get("weeks")
    if not isinstance(weeks, list):
        # Allow a full object that includes weeks
        data = action.get("data") or {}
        weeks = data.get("weeks") if isinstance(data, dict) else None
    if not isinstance(weeks, list):
        return _fail("save_launch_plan", "weeks array required")

    # Normalize — each action gets a `completed: false` default.
    norm_weeks = []
    for w in weeks:
        if not isinstance(w, dict):
            continue
        actions_list = w.get("actions") or []
        norm_actions = []
        for a in actions_list:
            if isinstance(a, str):
                norm_actions.append({"description": a, "completed": False})
            elif isinstance(a, dict):
                na = {"description": a.get("description") or a.get("text") or "",
                      "completed": bool(a.get("completed", False))}
                if a.get("system_link"):
                    na["system_link"] = a["system_link"]
                norm_actions.append(na)
        norm_weeks.append({
            "week": w.get("week") or (len(norm_weeks) + 1),
            "theme": w.get("theme") or "",
            "actions": norm_actions,
        })

    track = await _get_or_create_strategy_track(client, biz["id"])
    if not track:
        return _fail("save_launch_plan", "could not load strategy track")
    await _sb(client, "PATCH", f"/strategy_tracks?id=eq.{track['id']}",
              {"launch_plan": {"weeks": norm_weeks}})
    return {
        "type": "save_launch_plan",
        "result": f"{len(norm_weeks)} weeks saved",
        "label": "Launch plan saved",
        "nav": {"tab": "build", "page": "strategy-track"},
    }


async def _seed_products_module_from_packages(client, biz_id: str, packages: List[Dict]) -> Optional[str]:
    """Create a Products/Services module and entries for each package.
    Returns module_id on success."""
    if not packages:
        return None

    # Reuse if an earlier run created it.
    existing = await _sb(client, "GET",
        f"/custom_modules?business_id=eq.{biz_id}&slug=eq.products-services&limit=1&select=id")
    if existing:
        module_id = existing[0]["id"]
    else:
        created = await _sb(client, "POST", "/custom_modules", {
            "business_id": biz_id,
            "name": "Products & Services",
            "slug": "products-services",
            "description": "Your offerings from The Academy",
            "icon": "💼",
            "schema": {
                "fields": [
                    {"name": "name",        "type": "text",     "label": "Name", "required": True},
                    {"name": "description", "type": "textarea", "label": "Description"},
                    {"name": "price",       "type": "text",     "label": "Price"},
                    {"name": "duration",    "type": "text",     "label": "Duration"},
                    {"name": "delivery_format", "type": "text", "label": "Delivery format"},
                    {"name": "included",    "type": "textarea", "label": "What's included"},
                ],
                "default_sort": "created_at",
                "default_view": "list",
                "views": ["list"],
            },
            "agent_config": {"enabled": True, "triggers": []},
            "public_display": {
                "enabled": True, "display_type": "list",
                "title_override": "Services",
                "visible_fields": ["name", "description", "price"],
                "hidden_fields": [],
                "max_display": 20, "sort_by": "created_at",
            },
            "is_active": True,
        })
        if not created or not isinstance(created, list):
            return None
        module_id = created[0]["id"]

    for p in packages:
        if not isinstance(p, dict):
            continue
        included = p.get("included")
        if isinstance(included, list):
            included = "\n".join(f"• {x}" for x in included)
        await _sb(client, "POST", "/module_entries", {
            "module_id": module_id, "business_id": biz_id,
            "data": {
                "name": p.get("name") or "Package",
                "description": p.get("description") or "",
                "price": str(p.get("price") or ""),
                "duration": p.get("duration") or "",
                "delivery_format": p.get("delivery_format") or "",
                "included": included or "",
            },
            "status": "active",
            "created_by": "strategy_track",
            "source": "strategy_track",
        })
    return module_id


async def _seed_default_intake_form(client, biz_id: str, biz_type: str) -> None:
    # Don't seed if the business already has an active intake form.
    existing = await _sb(client, "GET",
        f"/intake_forms?business_id=eq.{biz_id}&is_active=eq.true&limit=1&select=id")
    if existing:
        return
    form_type_map = {
        "church": "connect_card",
        "coaching": "discovery",
        "agency": "consultation",
        "nonprofit": "volunteer",
        "ecommerce": "general",
    }
    form_type = form_type_map.get(biz_type, "general")
    name_map = {
        "church": "Visitor Connect Card",
        "coaching": "Discovery Call Request",
        "agency": "Consultation Request",
        "nonprofit": "Get Involved",
        "ecommerce": "Contact Form",
    }
    await _sb(client, "POST", "/intake_forms", {
        "business_id": biz_id,
        "name": name_map.get(biz_type, "Contact Form"),
        "form_type": form_type,
        "fields": [
            {"name": "name",  "type": "text",     "label": "Your Name", "required": True},
            {"name": "email", "type": "email",    "label": "Email",     "required": True},
            {"name": "phone", "type": "text",     "label": "Phone"},
            {"name": "message", "type": "textarea", "label": "How can we help?"},
        ],
        "settings": {"confirmation_message": "Thanks — we'll be in touch soon.", "auto_score": True},
        "is_active": True,
    })


async def _generate_strategy_site(client, biz: Dict, track: Dict) -> None:
    """Generate an initial site using strategy track context. Soft-fail."""
    biz_id = biz["id"]
    # Skip if a site already exists
    existing = await _sb(client, "GET",
        f"/business_sites?business_id=eq.{biz_id}&limit=1&select=id")
    if existing:
        return

    # CANONICAL ENGINE (DRL arc): the legacy LLM-writes-HTML generator is
    # retired. The initial strategy-launch site is composed by the Module
    # Composer (DRO-driven). Run in a thread so the event loop isn't blocked.
    try:
        from site_composer import compose_site
        await asyncio.to_thread(compose_site, biz_id, "", True)
    except Exception as e:
        logger.warning(f"[strategy] initial site compose failed (non-fatal): {e}")


async def handle_session_summary(client, biz, action) -> Dict:
    """Append a coaching-session summary onto the strategy track row.
    Stored under phases.session_log for the dashboard's Session History."""
    summary = (action.get("summary") or "").strip()
    if not summary:
        return _fail("session_summary", "summary required")
    phases_progressed = action.get("phases_progressed") or []
    if not isinstance(phases_progressed, list):
        phases_progressed = []

    track = await _get_or_create_strategy_track(client, biz["id"])
    if not track:
        return _fail("session_summary", "could not load strategy track")

    phases = dict(track.get("phases") or {})
    log = list(phases.get("session_log") or [])
    log.append({
        "date": datetime.now(timezone.utc).date().isoformat(),
        "ts": datetime.now(timezone.utc).isoformat(),
        "summary": summary[:1000],
        "phases_progressed": [str(p) for p in phases_progressed][:10],
    })
    # Keep the last 50 — plenty of history without bloating the row.
    phases["session_log"] = log[-50:]
    await _sb(client, "PATCH", f"/strategy_tracks?id=eq.{track['id']}",
              {"phases": phases})

    return {
        "type": "session_summary",
        "result": "logged",
        "label": "Session summary saved",
        "nav": {"tab": "build", "page": "strategy-track"},
    }


async def handle_complete_strategy_track(client, biz, action) -> Dict:
    """Finalize the track: create products module + entries from packages,
    seed an intake form, generate the site, flip settings.track to 'launched',
    and mark the track completed."""
    track = await _get_or_create_strategy_track(client, biz["id"])
    if not track:
        return _fail("complete_strategy_track", "could not load strategy track")

    packages = track.get("service_packages") or []
    module_id = await _seed_products_module_from_packages(client, biz["id"], packages)
    await _seed_default_intake_form(client, biz["id"], biz.get("type", "general"))

    # Phase 1: auto-assemble the business-type core module set (blueprint walk).
    # Converges with the Purpose-track path (business_profile_router.seed_from_onboarding)
    # so no practitioner onboards without module auto-assembly (Fork 5). Non-fatal —
    # a provisioning hiccup must never block strategy-track completion.
    try:
        import module_blueprint_agent
        await asyncio.to_thread(
            module_blueprint_agent.provision_modules, biz["id"], biz.get("type", "custom")
        )
    except Exception as e:
        logger.warning(f"[strategy_complete] blueprint provision failed (non-fatal): {e}")

    # Best-effort site generation
    try:
        await _generate_strategy_site(client, biz, track)
    except Exception as e:
        logger.warning(f"Strategy site generation failed: {e}")

    # Flip business track → "launched"
    settings = dict(biz.get("settings") or {})
    settings["track"] = "launched"
    await _sb(client, "PATCH", f"/businesses?id=eq.{biz['id']}", {"settings": settings})

    # Mark track completed
    await _sb(client, "PATCH", f"/strategy_tracks?id=eq.{track['id']}", {
        "status": "completed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    })

    # Pull service_models / pricing_models into business_profiles from
    # what the Strategy Coach saved. Non-fatal — if the profile import
    # fails for any reason, the track still completes cleanly.
    try:
        await asyncio.to_thread(business_profile_agent.import_from_strategy_track, biz["id"])
    except Exception as e:
        logger.warning(f"[strategy_complete] business_profile import failed (non-fatal): {e}")

    return {
        "type": "complete_strategy_track",
        "result": "launched",
        "label": "The Academy complete — business is live",
        "nav": {"tab": "build", "page": "strategy-track"},
        "products_module_id": module_id,
    }


