"""
notification_engine.py — Solutionist System proactive notifications

Generates ambient notifications the Chief sends throughout the day:
- morning_brief    (cron: ~7:30am local)
- midday_ping      (cron: ~12:30pm local — only if something urgent)
- evening_summary  (cron: ~6:00pm local)
- urgent_alert     (real-time, called from other agents)
- check-urgent     (polling check for time-sensitive events)

Also exposes /agents/notifications/{id}/act which executes the
notification's stored action_payload via the Chief's ACTION_HANDLERS.

═══════════════════════════════════════════════════════════════════════
DEPLOYMENT
═══════════════════════════════════════════════════════════════════════

1. Drop into Railway alongside chief_of_staff.py (it imports from there).
2. In main.py:
       from notification_engine import router as notif_router
       app.include_router(notif_router)
3. For scheduled briefs, see _patches/notification_engine_scheduler.md
4. For real-time urgent triggers from other agents, see
   _patches/notification_urgent_triggers.md
"""

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Reuse the Chief's action handlers for "Yes, do that" execution
from chief_of_staff import ACTION_HANDLERS

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
NOTIF_MODEL = "claude-sonnet-4-5-20250929"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)

MIDDAY_LOOKBACK_HOURS = 4
EVENING_LOOKBACK_HOURS = 12
URGENT_LOOKBACK_MINUTES = 5
URGENT_DEDUP_HOURS = 1
SESSION_IMMINENT_MINUTES = 15

VALID_PRIORITIES = {"urgent", "high", "normal", "low"}

logger = logging.getLogger("notification_engine")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] notif: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


def _supabase_url(): return os.environ.get("SUPABASE_URL", "")
def _supabase_anon(): return os.environ.get("SUPABASE_ANON", "")
def _anthropic_key(): return os.environ.get("ANTHROPIC_API_KEY", "")


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

async def _sb(client: httpx.AsyncClient, method: str, path: str, body=None):
    url = f"{_supabase_url()}/rest/v1{path}"
    headers = {
        "apikey": _supabase_anon(),
        "Authorization": f"Bearer {_supabase_anon()}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    resp = await client.request(method, url, headers=headers,
                                content=json.dumps(body) if body else None,
                                timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        logger.error(f"Supabase {method} {path}: {resp.status_code} {resp.text[:300]}")
        return None
    text = resp.text
    return json.loads(text) if text else None


async def _call_claude(client: httpx.AsyncClient, system: str, user_msg: str,
                       max_tokens: int = 600) -> str:
    key = _anthropic_key()
    if not key:
        return ""
    try:
        resp = await client.post(ANTHROPIC_API_URL, headers={
            "x-api-key": key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json",
        }, json={
            "model": NOTIF_MODEL, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user_msg}],
        }, timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as e:
        logger.warning(f"Claude request failed: {e}")
        return ""
    if resp.status_code >= 400:
        return ""
    data = resp.json()
    return "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict)).strip()


def _extract_json(text: str) -> Optional[Dict]:
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    candidate = fence.group(1) if fence else text
    s = candidate.find("{")
    e = candidate.rfind("}")
    if s < 0 or e <= s:
        return None
    try:
        obj = json.loads(candidate[s:e + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _normalize_priority(p: str) -> str:
    p = (p or "").strip().lower()
    return p if p in VALID_PRIORITIES else "normal"


def _midnight_iso() -> str:
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.isoformat()


async def _settings_allow(client, biz: Dict, key: str, default: bool = True) -> bool:
    """Check businesses.settings.notifications.<key>_enabled."""
    settings = (biz.get("settings") or {}).get("notifications") or {}
    val = settings.get(key)
    if val is None:
        return default
    return bool(val)


async def _existing_today(client, biz_id: str, type_name: str) -> bool:
    rows = await _sb(client, "GET",
        f"/chief_notifications?business_id=eq.{biz_id}&type=eq.{type_name}"
        f"&created_at=gte.{_midnight_iso()}&select=id&limit=1")
    return bool(rows)


async def _existing_within(client, biz_id: str, type_name: str, hours: int) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = await _sb(client, "GET",
        f"/chief_notifications?business_id=eq.{biz_id}&type=eq.{type_name}"
        f"&created_at=gte.{cutoff}&select=id&limit=1")
    return bool(rows)


async def _dedup_key_exists(client, biz_id: str, dedup_key: str, hours: int = URGENT_DEDUP_HOURS) -> bool:
    if not dedup_key:
        return False
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = await _sb(client, "GET",
        f"/chief_notifications?business_id=eq.{biz_id}"
        f"&action_payload->>dedup_key=eq.{dedup_key}"
        f"&created_at=gte.{cutoff}&select=id&limit=1")
    return bool(rows)


async def _insert_notification(client, biz_id: str, payload: Dict) -> Optional[Dict]:
    payload = {**payload, "business_id": biz_id}
    inserted = await _sb(client, "POST", "/chief_notifications", payload)
    if inserted and isinstance(inserted, list) and inserted:
        return inserted[0]
    # Surface the failure so it doesn't silently turn into "created:false"
    logger.error(f"Notification insert failed. Payload keys: {sorted(payload.keys())}")
    return None


# ═══════════════════════════════════════════════════════════════════════
# CORE GENERATORS
# ═══════════════════════════════════════════════════════════════════════

async def _gather_morning_data(client, biz_id: str) -> Dict:
    now = datetime.now(timezone.utc)
    end_of_day = now.replace(hour=23, minute=59, second=59).isoformat()
    morning = now.replace(hour=0, minute=0, second=0).isoformat()

    pending, sessions, at_risk, urgent = await asyncio.gather(
        _sb(client, "GET", f"/agent_queue?business_id=eq.{biz_id}&status=eq.draft&select=id,priority,subject&limit=20"),
        _sb(client, "GET", f"/sessions?business_id=eq.{biz_id}&status=eq.scheduled&scheduled_for=gte.{morning}&scheduled_for=lte.{end_of_day}&order=scheduled_for.asc&limit=10&select=id,title,scheduled_for,contacts(name)"),
        _sb(client, "GET", f"/contacts?business_id=eq.{biz_id}&health_score=lt.40&status=in.(active,lead,vip)&order=health_score.asc&limit=5&select=id,name,health_score"),
        _sb(client, "GET", f"/agent_queue?business_id=eq.{biz_id}&status=eq.draft&priority=eq.urgent&select=id,subject&limit=5"),
    )
    return {
        "pending": pending or [],
        "sessions_today": sessions or [],
        "at_risk": at_risk or [],
        "urgent": urgent or [],
    }


async def _gather_midday_data(client, biz_id: str) -> Dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=MIDDAY_LOOKBACK_HOURS)).isoformat()

    new_drafts, urgent_drafts, no_shows, health_drops = await asyncio.gather(
        _sb(client, "GET", f"/agent_queue?business_id=eq.{biz_id}&created_at=gte.{cutoff}&status=eq.draft&select=id,agent,subject,priority&limit=20"),
        _sb(client, "GET", f"/agent_queue?business_id=eq.{biz_id}&created_at=gte.{cutoff}&status=eq.draft&priority=eq.urgent&select=id,subject&limit=5"),
        _sb(client, "GET", f"/sessions?business_id=eq.{biz_id}&status=eq.no_show&updated_at=gte.{cutoff}&select=id,title,contacts(name)&limit=5"),
        _sb(client, "GET", f"/contacts?business_id=eq.{biz_id}&health_score=lt.30&updated_at=gte.{cutoff}&select=id,name,health_score&limit=5"),
    )
    return {
        "new_drafts": new_drafts or [],
        "urgent_drafts": urgent_drafts or [],
        "no_shows": no_shows or [],
        "health_drops": health_drops or [],
    }


async def _gather_evening_data(client, biz_id: str) -> Dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=EVENING_LOOKBACK_HOURS)).isoformat()
    tomorrow_end = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()

    approved, completed, new_contacts, pending, upcoming = await asyncio.gather(
        _sb(client, "GET", f"/agent_queue?business_id=eq.{biz_id}&status=eq.approved&reviewed_at=gte.{cutoff}&select=id,agent,subject&limit=20"),
        _sb(client, "GET", f"/sessions?business_id=eq.{biz_id}&status=eq.completed&scheduled_for=gte.{cutoff}&select=id,title,contacts(name)&limit=10"),
        _sb(client, "GET", f"/contacts?business_id=eq.{biz_id}&created_at=gte.{cutoff}&select=id,name,status&limit=10"),
        _sb(client, "GET", f"/agent_queue?business_id=eq.{biz_id}&status=eq.draft&select=id,priority&limit=20"),
        _sb(client, "GET", f"/sessions?business_id=eq.{biz_id}&status=eq.scheduled&scheduled_for=gte.{datetime.now(timezone.utc).isoformat()}&scheduled_for=lte.{tomorrow_end}&order=scheduled_for.asc&select=id,title,scheduled_for,contacts(name)&limit=10"),
    )
    return {
        "approved_today": approved or [],
        "completed_sessions": completed or [],
        "new_contacts": new_contacts or [],
        "pending_carryover": pending or [],
        "tomorrow_sessions": upcoming or [],
    }


def _format_data_for_prompt(data: Dict) -> str:
    lines = []
    for key, val in data.items():
        if isinstance(val, list):
            lines.append(f"{key.upper()} ({len(val)}):")
            for item in val[:8]:
                if isinstance(item, dict):
                    summary = item.get("subject") or item.get("title") or item.get("name") or json.dumps(item)[:80]
                    extra = []
                    if item.get("priority"): extra.append(f"[{item['priority']}]")
                    if item.get("health_score") is not None: extra.append(f"health {item['health_score']}")
                    if item.get("contacts") and isinstance(item["contacts"], dict):
                        extra.append(f"with {item['contacts'].get('name', '')}")
                    if item.get("scheduled_for"): extra.append(f"@ {item['scheduled_for'][:16]}")
                    lines.append(f"  - {summary} {' '.join(extra)}".strip())
        else:
            lines.append(f"{key.upper()}: {val}")
    return "\n".join(lines) if lines else "(no recent activity)"


async def _ai_generate_notification(
    client, biz: Dict, system_prompt: str, data_summary: str, fallback_title: str, fallback_body: str
) -> Dict:
    """Returns a dict whose keys match chief_notifications columns:
    {title, body, priority, suggested_action, action_payload}.
    The AI is prompted with 'suggested_action_text' for clarity but we
    map it to the DB column name before returning."""
    user_msg = f"DATA:\n{data_summary}\n\nReturn ONLY JSON inside ```json fences with this shape:\n" + (
        '{"title": "...", "body": "...", "priority": "normal|high|urgent|low", '
        '"suggested_action_text": "Yes, do that" | null, '
        '"action_payload": { ... } | null}'
    )
    raw = await _call_claude(client, system_prompt, user_msg, max_tokens=700)
    parsed = _extract_json(raw)
    if not parsed or not parsed.get("title") or not parsed.get("body"):
        return {
            "title": fallback_title,
            "body": fallback_body,
            "priority": "normal",
            "suggested_action": None,
            "action_payload": None,
        }
    return {
        "title": str(parsed["title"])[:200],
        "body": str(parsed["body"])[:2000],
        "priority": _normalize_priority(parsed.get("priority", "normal")),
        "suggested_action": (str(parsed["suggested_action_text"])[:200] if parsed.get("suggested_action_text") else None),
        "action_payload": parsed.get("action_payload") if isinstance(parsed.get("action_payload"), dict) else None,
    }


async def _generate_morning_brief(client, biz_id: str) -> Dict:
    biz_rows = await _sb(client, "GET", f"/businesses?id=eq.{biz_id}&select=*&limit=1")
    if not biz_rows:
        return {"skipped": "business_not_found"}
    biz = biz_rows[0]

    if not await _settings_allow(client, biz, "morning_brief"):
        return {"skipped": "disabled"}
    if await _existing_today(client, biz_id, "morning_brief"):
        return {"skipped": "already_sent_today"}

    data = await _gather_morning_data(client, biz_id)
    biz_name = biz.get("name", "")
    practitioner = (biz.get("settings") or {}).get("practitioner_name", "the practitioner")
    voice = biz.get("voice_profile") or {}

    system = f"""You are the Chief of Staff for {biz_name}. Write a brief, warm morning notification for {practitioner} in their voice.
Voice profile: {json.dumps(voice)[:400]}

Cover (in this order): (1) ONE specific thing to prioritize today, (2) anything urgent, (3) sessions today if any, (4) one quick stat. Keep under 80 words. End with a clear next step or question.

Set priority='high' if there's anything urgent, otherwise 'normal'. Suggest an action only if there's something obvious to do (run an agent, open a contact, triage queue)."""

    notif = await _ai_generate_notification(
        client, biz, system, _format_data_for_prompt(data),
        fallback_title="Quick morning read",
        fallback_body=f"You have {len(data['pending'])} drafts pending and {len(data['sessions_today'])} sessions today.",
    )

    inserted = await _insert_notification(client, biz_id, {
        "type": "morning_brief", **notif,
    })
    return {"created": bool(inserted), "notification_id": inserted["id"] if inserted else None, "notif": notif}


async def _generate_midday_ping(client, biz_id: str) -> Dict:
    biz_rows = await _sb(client, "GET", f"/businesses?id=eq.{biz_id}&select=*&limit=1")
    if not biz_rows:
        return {"skipped": "business_not_found"}
    biz = biz_rows[0]

    if not await _settings_allow(client, biz, "midday_ping"):
        return {"skipped": "disabled"}
    if await _existing_within(client, biz_id, "midday_ping", MIDDAY_LOOKBACK_HOURS):
        return {"skipped": "recent_ping_exists"}

    data = await _gather_midday_data(client, biz_id)

    # Significance threshold
    significant = (
        len(data["new_drafts"]) >= 3
        or len(data["urgent_drafts"]) >= 1
        or len(data["no_shows"]) >= 1
        or len(data["health_drops"]) >= 1
    )
    if not significant:
        return {"skipped": "nothing_significant"}

    biz_name = biz.get("name", "")
    practitioner = (biz.get("settings") or {}).get("practitioner_name", "the practitioner")
    voice = biz.get("voice_profile") or {}

    system = f"""You are the Chief of Staff for {biz_name}. Write a brief mid-day check-in for {practitioner} in their voice.
Voice profile: {json.dumps(voice)[:400]}

Something happened in the last few hours that they should know. Be specific and actionable. Under 60 words. Set priority='high' if urgent_drafts or no_shows or health_drops, otherwise 'normal'."""

    fallback_count = len(data["new_drafts"])
    notif = await _ai_generate_notification(
        client, biz, system, _format_data_for_prompt(data),
        fallback_title="Mid-day check-in",
        fallback_body=f"{fallback_count} new draft{'s' if fallback_count != 1 else ''} since this morning. Worth a look when you have a minute.",
    )
    inserted = await _insert_notification(client, biz_id, {
        "type": "midday_ping", **notif,
    })
    return {"created": bool(inserted), "notification_id": inserted["id"] if inserted else None, "notif": notif}


async def _generate_evening_summary(client, biz_id: str) -> Dict:
    biz_rows = await _sb(client, "GET", f"/businesses?id=eq.{biz_id}&select=*&limit=1")
    if not biz_rows:
        return {"skipped": "business_not_found"}
    biz = biz_rows[0]

    if not await _settings_allow(client, biz, "evening_summary"):
        return {"skipped": "disabled"}
    if await _existing_today(client, biz_id, "evening_summary"):
        return {"skipped": "already_sent_today"}

    data = await _gather_evening_data(client, biz_id)
    biz_name = biz.get("name", "")
    practitioner = (biz.get("settings") or {}).get("practitioner_name", "the practitioner")
    voice = biz.get("voice_profile") or {}

    system = f"""You are the Chief of Staff for {biz_name}. Write a brief end-of-day summary for {practitioner} in their voice.
Voice profile: {json.dumps(voice)[:400]}

Cover: (1) what was accomplished today, (2) what carries to tomorrow, (3) one thing to look forward to. Warm and reflective. Under 80 words. Set priority='low'. Do NOT suggest actions — this is reflective, not actionable."""

    notif = await _ai_generate_notification(
        client, biz, system, _format_data_for_prompt(data),
        fallback_title="End of day",
        fallback_body=f"{len(data['approved_today'])} drafts approved, {len(data['completed_sessions'])} sessions completed, {len(data['new_contacts'])} new contacts. Good day's work.",
    )
    inserted = await _insert_notification(client, biz_id, {
        "type": "evening_summary", **notif,
    })
    return {"created": bool(inserted), "notification_id": inserted["id"] if inserted else None, "notif": notif}


# ═══════════════════════════════════════════════════════════════════════
# URGENT ALERT HELPER (importable + endpoint)
# ═══════════════════════════════════════════════════════════════════════

async def create_urgent_alert(
    client, business_id: str, title: str, body: str,
    *,
    dedup_key: Optional[str] = None,
    priority: str = "urgent",
    suggested_action: Optional[str] = None,
    action_payload: Optional[Dict] = None,
    related_contact_id: Optional[str] = None,
    related_module_id: Optional[str] = None,
    related_session_id: Optional[str] = None,
) -> Optional[Dict]:
    """Create an urgent_alert notification. Other agents import + call this.
    Honors a per-business urgent_alerts_enabled setting and dedups on
    dedup_key within URGENT_DEDUP_HOURS."""
    biz_rows = await _sb(client, "GET", f"/businesses?id=eq.{business_id}&select=*&limit=1")
    if not biz_rows:
        return None
    if not await _settings_allow(client, biz_rows[0], "urgent_alerts"):
        return None
    if dedup_key and await _dedup_key_exists(client, business_id, dedup_key):
        return None

    payload_extra = dict(action_payload or {})
    if dedup_key:
        payload_extra["dedup_key"] = dedup_key

    return await _insert_notification(client, business_id, {
        "type": "urgent_alert",
        "title": title[:200],
        "body": body[:2000],
        "priority": _normalize_priority(priority),
        "suggested_action": suggested_action,
        "action_payload": payload_extra or None,
        "related_contact_id": related_contact_id,
        "related_module_id": related_module_id,
        "related_session_id": related_session_id,
    })


async def _check_urgent(client, biz_id: str) -> Dict:
    """Polling check: scan recent activity for urgent triggers."""
    biz_rows = await _sb(client, "GET", f"/businesses?id=eq.{biz_id}&select=*&limit=1")
    if not biz_rows:
        return {"created": []}
    biz = biz_rows[0]
    if not await _settings_allow(client, biz, "urgent_alerts"):
        return {"skipped": "disabled"}

    now = datetime.now(timezone.utc)
    recent_cutoff = (now - timedelta(minutes=URGENT_LOOKBACK_MINUTES)).isoformat()
    soon_cutoff = (now + timedelta(minutes=SESSION_IMMINENT_MINUTES)).isoformat()
    created: List[Dict] = []

    # 1. Hot intake leads (form_submit events with high lead_score)
    hot_leads = await _sb(client, "GET",
        f"/events?business_id=eq.{biz_id}&event_type=eq.form_submit"
        f"&created_at=gte.{recent_cutoff}&select=*,contacts(name,lead_score)&limit=10") or []
    for ev in hot_leads:
        contact = ev.get("contacts") or {}
        score = contact.get("lead_score")
        if score is None or score < 70:
            continue
        cid = ev.get("contact_id")
        dedup = f"hot_lead:{cid}"
        alert = await create_urgent_alert(
            client, biz_id,
            title=f"Hot lead: {contact.get('name', 'unknown')}",
            body=f"{contact.get('name', 'New contact')} just submitted an intake form with a lead score of {score}. Worth a same-day reply.",
            dedup_key=dedup,
            suggested_action=f"Open {contact.get('name', 'this contact')}",
            action_payload={"type": "navigate", "tab": "operate", "sub": "contacts", "contact_id": cid},
            related_contact_id=cid,
        )
        if alert:
            created.append({"trigger": "hot_lead", "notification_id": alert["id"]})

    # 2. Imminent sessions (start within 15 minutes, not yet alerted)
    imminent = await _sb(client, "GET",
        f"/sessions?business_id=eq.{biz_id}&status=eq.scheduled"
        f"&scheduled_for=gte.{now.isoformat()}&scheduled_for=lte.{soon_cutoff}"
        f"&select=id,title,scheduled_for,contact_id,contacts(name)&limit=5") or []
    for s in imminent:
        dedup = f"session_imminent:{s['id']}"
        cname = (s.get("contacts") or {}).get("name", "a contact")
        alert = await create_urgent_alert(
            client, biz_id,
            title=f"Session in 15 min: {s.get('title') or 'Upcoming'}",
            body=f"Your session with {cname} starts at {s.get('scheduled_for', '')[11:16]}. Need a quick prep brief?",
            dedup_key=dedup,
            priority="high",
            suggested_action="Prep me now",
            action_payload={"type": "run_agent", "agent": "session_prep"},
            related_contact_id=s.get("contact_id"),
            related_session_id=s["id"],
        )
        if alert:
            created.append({"trigger": "session_imminent", "notification_id": alert["id"]})

    return {"created": created, "checked_at": now.isoformat()}


# ═══════════════════════════════════════════════════════════════════════
# BATCH "FOR ALL" RUNNERS (used by APScheduler)
# ═══════════════════════════════════════════════════════════════════════

async def _all_active_business_ids(client) -> List[str]:
    rows = await _sb(client, "GET", "/businesses?is_active=eq.true&select=id&limit=200") or []
    return [r["id"] for r in rows]


async def generate_morning_brief_for_all() -> Dict:
    async with httpx.AsyncClient() as client:
        ids = await _all_active_business_ids(client)
        results = []
        for bid in ids:
            try: results.append({"business_id": bid, **await _generate_morning_brief(client, bid)})
            except Exception as e: logger.exception(f"morning_brief failed for {bid}: {e}")
        return {"ran": len(ids), "results": results}


async def generate_midday_ping_for_all() -> Dict:
    async with httpx.AsyncClient() as client:
        ids = await _all_active_business_ids(client)
        results = []
        for bid in ids:
            try: results.append({"business_id": bid, **await _generate_midday_ping(client, bid)})
            except Exception as e: logger.exception(f"midday_ping failed for {bid}: {e}")
        return {"ran": len(ids), "results": results}


async def generate_evening_summary_for_all() -> Dict:
    async with httpx.AsyncClient() as client:
        ids = await _all_active_business_ids(client)
        results = []
        for bid in ids:
            try: results.append({"business_id": bid, **await _generate_evening_summary(client, bid)})
            except Exception as e: logger.exception(f"evening_summary failed for {bid}: {e}")
        return {"ran": len(ids), "results": results}


# ═══════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════

router = APIRouter(tags=["notifications"])


class NotifRequest(BaseModel):
    business_id: str


@router.post("/agents/notifications/morning-brief")
async def morning_brief(req: NotifRequest):
    async with httpx.AsyncClient() as client:
        return await _generate_morning_brief(client, req.business_id)


@router.post("/agents/notifications/midday-ping")
async def midday_ping(req: NotifRequest):
    async with httpx.AsyncClient() as client:
        return await _generate_midday_ping(client, req.business_id)


@router.post("/agents/notifications/evening-summary")
async def evening_summary(req: NotifRequest):
    async with httpx.AsyncClient() as client:
        return await _generate_evening_summary(client, req.business_id)


@router.post("/agents/notifications/check-urgent")
async def check_urgent(req: NotifRequest):
    async with httpx.AsyncClient() as client:
        return await _check_urgent(client, req.business_id)


@router.post("/agents/notifications/{notification_id}/act")
async def execute_notification_action(notification_id: str):
    """Execute the notification's stored action_payload via Chief's handlers."""
    async with httpx.AsyncClient() as client:
        rows = await _sb(client, "GET",
            f"/chief_notifications?id=eq.{notification_id}&limit=1&select=*")
        if not rows:
            raise HTTPException(404, "Notification not found")
        notif = rows[0]

        action = notif.get("action_payload") or {}
        if not action.get("type"):
            raise HTTPException(400, "No action to execute")

        biz_rows = await _sb(client, "GET",
            f"/businesses?id=eq.{notif['business_id']}&select=*&limit=1")
        if not biz_rows:
            raise HTTPException(404, "Business not found")
        biz = biz_rows[0]

        handler = ACTION_HANDLERS.get(action["type"])
        if not handler:
            raise HTTPException(400, f"Unknown action type: {action['type']}")

        try:
            result = await handler(client, biz, action)
        except Exception as e:
            logger.exception(f"Action {action['type']} failed: {e}")
            raise HTTPException(500, f"Action failed: {e}")

        await _sb(client, "PATCH", f"/chief_notifications?id=eq.{notification_id}",
                  {"status": "acted_on"})

        return {"executed": True, "result": result}


@router.get("/agents/notifications/health")
async def notif_health():
    return {
        "status": "ok",
        "supabase_configured": bool(_supabase_url()),
        "anthropic_configured": bool(_anthropic_key()),
        "model": NOTIF_MODEL,
        "midday_lookback_hours": MIDDAY_LOOKBACK_HOURS,
        "evening_lookback_hours": EVENING_LOOKBACK_HOURS,
        "urgent_lookback_minutes": URGENT_LOOKBACK_MINUTES,
    }
