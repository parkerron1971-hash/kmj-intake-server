"""
session_agent.py — Solutionist System Session Agent

Prepares briefs before sessions, drafts follow-ups after, and handles
no-shows. Uses the business voice_profile so all communications match
the practitioner's natural style.

═══════════════════════════════════════════════════════════════════════
DEPLOYMENT
═══════════════════════════════════════════════════════════════════════

1. Drop into Railway project alongside ai_proxy.py, nurture_agent.py.

2. In main.py:
       from session_agent import router as session_router
       app.include_router(session_router)

3. Env vars needed (already set): SUPABASE_URL, SUPABASE_ANON, ANTHROPIC_API_KEY
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
PLAN_MODEL = "claude-sonnet-4-5-20250929"
DRAFT_MODEL = "claude-sonnet-4-5-20250929"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)

logger = logging.getLogger("session_agent")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] session: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

def _supabase_url(): return os.environ.get("SUPABASE_URL", "")
def _supabase_anon(): return os.environ.get("SUPABASE_ANON", "")
def _anthropic_key(): return os.environ.get("ANTHROPIC_API_KEY", "")

# ═══════════════════════════════════════════════════════════════════════
# HELPERS (same pattern as nurture_agent.py)
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
        logger.error(f"Supabase {method} {path}: {resp.status_code} {resp.text}")
        return None
    text = resp.text
    return json.loads(text) if text else None


async def _call_claude(client: httpx.AsyncClient, system: str, user_msg: str,
                       model: str = DRAFT_MODEL, max_tokens: int = 500) -> str:
    key = _anthropic_key()
    if not key:
        return ""
    resp = await client.post(ANTHROPIC_API_URL, headers={
        "x-api-key": key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json",
    }, json={
        "model": model, "max_tokens": max_tokens, "system": system,
        "messages": [{"role": "user", "content": user_msg}],
    }, timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        logger.warning(f"Claude error: {resp.status_code}")
        return ""
    data = resp.json()
    return "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict)).strip()


def _format_dt(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%A, %B %d at %I:%M %p")
    except:
        return iso_str


def _hours_until(iso_str: str) -> int:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return max(0, int((dt - datetime.now(timezone.utc)).total_seconds() / 3600))
    except:
        return 0


# ═══════════════════════════════════════════════════════════════════════
# MODULE SESSION LINK
# ═══════════════════════════════════════════════════════════════════════
# When a session is completed, create pre-filled entries in any custom
# modules that have agent_config.session_linked = true.
# Dedup key: events.event_type = 'module_session_linked' with
# data.session_id + data.module_id. Both this code AND module_agent.py's
# _handle_session_linked check the same key, so enabling both is safe.

async def _session_linked_modules(client, business_id):
    """Custom modules for this business that want session-linked entries."""
    rows = await _sb(client, "GET",
        f"/custom_modules?business_id=eq.{business_id}"
        f"&is_active=eq.true&select=id,name,schema,agent_config&limit=50"
    ) or []
    return [
        m for m in rows
        if ((m.get("agent_config") or {}).get("enabled", True))
        and ((m.get("agent_config") or {}).get("session_linked") is True)
    ]


async def _link_session_to_modules(client, business_id, session):
    """Call this after a session is marked completed. Creates one pre-filled
    module_entries row per session-linked module, deduping by event."""
    modules = await _session_linked_modules(client, business_id)
    if not modules:
        return

    for m in modules:
        # Dedup -- has this session already been linked to this module?
        existing = await _sb(client, "GET",
            f"/events?business_id=eq.{business_id}&event_type=eq.module_session_linked"
            f"&data->>session_id=eq.{session['id']}&data->>module_id=eq.{m['id']}"
            f"&select=id&limit=1"
        )
        if existing:
            continue

        schema_fields = {f.get("name") for f in (m.get("schema") or {}).get("fields") or [] if isinstance(f, dict)}
        data = {}
        if "title" in schema_fields:
            data["title"] = f"Session: {session.get('title') or 'completed'}"
        if "deliverable_name" in schema_fields:
            data["deliverable_name"] = session.get("title") or "Session notes"
        if "session_id" in schema_fields:
            data["session_id"] = session["id"]
        if "contact_id" in schema_fields and session.get("contact_id"):
            data["contact_id"] = session["contact_id"]
        if "status" in schema_fields:
            data["status"] = "new"
        if "notes" in schema_fields and session.get("notes"):
            data["notes"] = session["notes"]

        inserted = await _sb(client, "POST", "/module_entries", {
            "module_id": m["id"],
            "business_id": business_id,
            "data": data,
            "status": "active",
            "created_by": "session_agent",
            "source": "session_link",
        })
        entry_id = inserted[0]["id"] if (inserted and isinstance(inserted, list)) else None
        if entry_id:
            await _sb(client, "POST", "/events", {
                "business_id": business_id,
                "contact_id": session.get("contact_id"),
                "event_type": "module_session_linked",
                "data": {"module_id": m["id"], "entry_id": entry_id, "session_id": session["id"]},
                "source": "session_agent",
            })
            logger.info(f"Linked session {session['id']} to module {m['name']} (entry {entry_id})")


# ═══════════════════════════════════════════════════════════════════════
# PREP BRIEF
# ═══════════════════════════════════════════════════════════════════════

async def _prep_one_session(client: httpx.AsyncClient, business: Dict, session: Dict) -> Optional[Dict]:
    biz_name = business.get("name", "")
    voice = business.get("voice_profile", {})
    practitioner = business.get("settings", {}).get("practitioner_name", "the team")
    biz_type = business.get("type", "general")

    contact_id = session["contact_id"]
    contacts = await _sb(client, "GET", f"/contacts?id=eq.{contact_id}&select=*&limit=1")
    contact = contacts[0] if contacts else {}
    contact_name = contact.get("name", "the contact")

    # Fetch context
    events = await _sb(client, "GET",
        f"/events?contact_id=eq.{contact_id}&order=created_at.desc&limit=10") or []
    queue_items = await _sb(client, "GET",
        f"/agent_queue?contact_id=eq.{contact_id}&order=created_at.desc&limit=5&select=agent,action_type,subject,status,created_at") or []

    event_summary = "\n".join(
        f"- {e.get('event_type')} ({e.get('source', '?')}) -- {e.get('created_at', '?')[:10]}"
        for e in events[:10]
    ) or "No events recorded"

    outreach_summary = "\n".join(
        f"- [{q.get('status')}] {q.get('agent')}: {q.get('subject', q.get('action_type'))} -- {q.get('created_at', '?')[:10]}"
        for q in queue_items[:5]
    ) or "No prior outreach"

    session_dt = _format_dt(session.get("scheduled_for", ""))
    hours_away = _hours_until(session.get("scheduled_for", ""))

    system_prompt = f"""You are the Session Agent for {biz_name}. Prepare a brief for {practitioner} ahead of their {session.get('session_type', 'session')} with {contact_name} scheduled for {session_dt}.

Include:
1. Quick summary of this person's engagement history and health score
2. Key topics to address based on recent interactions and any outstanding issues
3. One specific question or action that would make this session impactful

Keep the brief under 8 sentences. Write it as a note TO the practitioner, not as a message to the contact. Tone: professional, concise, actionable. This is a {biz_type} business."""

    user_msg = f"""Session: {session.get('title')}
Type: {session.get('session_type')}
Scheduled: {session_dt} ({hours_away} hours from now)
Duration: {session.get('duration_minutes', 60)} minutes

Contact: {contact_name}
Role: {contact.get('role', 'not specified')}
Status: {contact.get('status', '?')}
Health Score: {contact.get('health_score', '?')}/100
Tags: {', '.join(contact.get('tags', [])) or 'none'}

Recent events:
{event_summary}

Prior outreach:
{outreach_summary}"""

    brief_text = await _call_claude(client, system_prompt, user_msg, model=PLAN_MODEL, max_tokens=400)
    if not brief_text:
        brief_text = f"Upcoming {session.get('session_type', 'session')} with {contact_name}. Review their recent activity before the meeting."

    brief_json = {
        "text": brief_text,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contact_health": contact.get("health_score"),
        "hours_until_session": hours_away,
    }

    # Store prep brief on session
    await _sb(client, "PATCH", f"/sessions?id=eq.{session['id']}", {"prep_brief": brief_json})

    # Insert into agent_queue
    await _sb(client, "POST", "/agent_queue", {
        "business_id": business["id"],
        "contact_id": contact_id,
        "agent": "session",
        "action_type": "other",
        "subject": f"Session Prep: {contact_name} -- {session_dt}",
        "body": brief_text,
        "channel": "in_app",
        "status": "draft",
        "priority": "medium",
        "ai_reasoning": f"Upcoming session in {hours_away} hours. Prepared context brief for {practitioner}.",
        "ai_model": PLAN_MODEL,
    })

    # Log event
    await _sb(client, "POST", "/events", {
        "business_id": business["id"],
        "contact_id": contact_id,
        "event_type": "session_prep_created",
        "data": {"session_id": session["id"], "hours_until": hours_away},
        "source": "session_agent",
    })

    logger.info(f"Prep brief created for session {session['id']} ({contact_name})")
    return {"session_id": session["id"], "contact_name": contact_name, "brief_preview": brief_text[:100]}


# ═══════════════════════════════════════════════════════════════════════
# FOLLOW-UP
# ═══════════════════════════════════════════════════════════════════════

async def _followup_one_session(client: httpx.AsyncClient, business: Dict, session: Dict) -> Optional[Dict]:
    biz_name = business.get("name", "")
    voice = business.get("voice_profile", {})
    practitioner = business.get("settings", {}).get("practitioner_name", "the team")
    tone = voice.get("tone", "warm and professional")
    personality = voice.get("personality", "helpful")
    comm_style = voice.get("communication_style", [])

    contact_id = session["contact_id"]
    contacts = await _sb(client, "GET", f"/contacts?id=eq.{contact_id}&select=*&limit=1")
    contact = contacts[0] if contacts else {}
    contact_name = contact.get("name", "there")
    session_dt = _format_dt(session.get("scheduled_for", ""))
    notes = session.get("notes") or "No notes recorded"

    system_prompt = f"""You are the Session Agent for {biz_name}. Draft a follow-up message from {practitioner} to {contact_name} after their {session.get('session_type', 'session')}.

The session was on {session_dt}. Session notes: {notes}

Write a warm, personal follow-up that:
1. Thanks them for their time
2. Recaps one key takeaway or next step from the session
3. Sets expectations for what comes next

Keep it under 5 sentences. Sign off as {practitioner}.

Voice profile: tone is "{tone}", personality is "{personality}", style is "{', '.join(comm_style) if comm_style else tone}"."""

    user_msg = f"""Contact: {contact_name}
Role: {contact.get('role', 'not specified')}
Session: {session.get('title')}
Notes: {notes}

Draft the follow-up message."""

    draft_body = await _call_claude(client, system_prompt, user_msg)
    if not draft_body:
        draft_body = f"Hi {contact_name}, thanks for our session. Looking forward to our next meeting. -- {practitioner}"

    subject = f"Following up on our session, {contact_name}"

    await _sb(client, "POST", "/agent_queue", {
        "business_id": business["id"],
        "contact_id": contact_id,
        "agent": "session",
        "action_type": "follow_up",
        "subject": subject,
        "body": draft_body,
        "channel": "email" if contact.get("email") else "in_app",
        "status": "draft",
        "priority": "medium",
        "ai_reasoning": f"Session '{session.get('title')}' completed on {session_dt}. Follow-up drafted based on session notes.",
        "ai_model": DRAFT_MODEL,
    })

    await _sb(client, "POST", "/events", {
        "business_id": business["id"],
        "contact_id": contact_id,
        "event_type": "session_followup_created",
        "data": {"session_id": session["id"]},
        "source": "session_agent",
    })

    # Link completed session to any session-linked custom modules
    await _link_session_to_modules(client, business["id"], session)

    logger.info(f"Follow-up drafted for session {session['id']} ({contact_name})")
    return {"session_id": session["id"], "contact_name": contact_name, "subject": subject}


# ═══════════════════════════════════════════════════════════════════════
# NO-SHOW
# ═══════════════════════════════════════════════════════════════════════

async def _noshow_one_session(client: httpx.AsyncClient, business: Dict, session: Dict) -> Optional[Dict]:
    biz_name = business.get("name", "")
    voice = business.get("voice_profile", {})
    practitioner = business.get("settings", {}).get("practitioner_name", "the team")
    tone = voice.get("tone", "warm and professional")

    contact_id = session["contact_id"]
    contacts = await _sb(client, "GET", f"/contacts?id=eq.{contact_id}&select=*&limit=1")
    contact = contacts[0] if contacts else {}
    contact_name = contact.get("name", "there")
    session_dt = _format_dt(session.get("scheduled_for", ""))

    system_prompt = f"""You are the Session Agent for {biz_name}. Draft a gentle, non-judgmental reschedule message from {practitioner} to {contact_name} who missed their {session.get('session_type', 'session')} on {session_dt}.

Be understanding -- life happens. Don't guilt them. Offer to reschedule. Keep it under 4 sentences. Sign off as {practitioner}. Tone: "{tone}"."""

    user_msg = f"Contact: {contact_name}\nMissed session: {session.get('title')}\nScheduled for: {session_dt}\n\nDraft a warm reschedule message."

    draft_body = await _call_claude(client, system_prompt, user_msg, max_tokens=300)
    if not draft_body:
        draft_body = f"Hi {contact_name}, I noticed we missed our session. No worries at all -- let's find another time that works. -- {practitioner}"

    await _sb(client, "POST", "/agent_queue", {
        "business_id": business["id"],
        "contact_id": contact_id,
        "agent": "session",
        "action_type": "follow_up",
        "subject": f"Let's reschedule, {contact_name}",
        "body": draft_body,
        "channel": "email" if contact.get("email") else "in_app",
        "status": "draft",
        "priority": "high",
        "ai_reasoning": f"No-show for '{session.get('title')}' on {session_dt}. Gentle reschedule message drafted. Health score decayed by 10.",
        "ai_model": DRAFT_MODEL,
    })

    # Decay health score
    health = contact.get("health_score", 50)
    new_health = max(5, health - 10)
    if new_health != health:
        await _sb(client, "PATCH", f"/contacts?id=eq.{contact_id}", {"health_score": new_health})

    await _sb(client, "POST", "/events", {
        "business_id": business["id"],
        "contact_id": contact_id,
        "event_type": "session_no_show",
        "data": {"session_id": session["id"], "health_decay": health - new_health},
        "source": "session_agent",
    })

    logger.info(f"No-show handled for session {session['id']} ({contact_name}), health {health} -> {new_health}")
    return {"session_id": session["id"], "contact_name": contact_name, "health_before": health, "health_after": new_health}


# ═══════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════

router = APIRouter(tags=["session_agent"])

class SessionRequest(BaseModel):
    business_id: str


@router.post("/agents/session/prep")
async def session_prep(req: SessionRequest):
    async with httpx.AsyncClient() as client:
        businesses = await _sb(client, "GET", f"/businesses?id=eq.{req.business_id}&select=*&limit=1")
        if not businesses:
            raise HTTPException(404, "Business not found")
        biz = businesses[0]

        cutoff = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
        sessions = await _sb(client, "GET",
            f"/sessions?business_id=eq.{req.business_id}&status=eq.scheduled"
            f"&scheduled_for=lte.{cutoff}&prep_brief=is.null"
            f"&order=scheduled_for.asc&limit=10"
        ) or []

        results = []
        for s in sessions:
            r = await _prep_one_session(client, biz, s)
            if r:
                results.append(r)

        return {"sessions_checked": len(sessions), "briefs_created": len(results), "results": results}


@router.post("/agents/session/follow-up")
async def session_followup(req: SessionRequest):
    async with httpx.AsyncClient() as client:
        businesses = await _sb(client, "GET", f"/businesses?id=eq.{req.business_id}&select=*&limit=1")
        if not businesses:
            raise HTTPException(404, "Business not found")
        biz = businesses[0]

        # Completed sessions -- check if follow-up already exists
        completed = await _sb(client, "GET",
            f"/sessions?business_id=eq.{req.business_id}&status=eq.completed"
            f"&order=scheduled_for.desc&limit=10"
        ) or []

        results = []
        for s in completed:
            # Check if follow-up draft already exists for this session
            existing = await _sb(client, "GET",
                f"/agent_queue?business_id=eq.{req.business_id}&agent=eq.session"
                f"&action_type=eq.follow_up&contact_id=eq.{s['contact_id']}"
                f"&select=id&limit=1"
            )
            if existing and len(existing) > 0:
                continue
            r = await _followup_one_session(client, biz, s)
            if r:
                results.append(r)

        return {"sessions_checked": len(completed), "followups_created": len(results), "results": results}


@router.post("/agents/session/no-show")
async def session_noshow(req: SessionRequest):
    async with httpx.AsyncClient() as client:
        businesses = await _sb(client, "GET", f"/businesses?id=eq.{req.business_id}&select=*&limit=1")
        if not businesses:
            raise HTTPException(404, "Business not found")
        biz = businesses[0]

        noshows = await _sb(client, "GET",
            f"/sessions?business_id=eq.{req.business_id}&status=eq.no_show"
            f"&order=scheduled_for.desc&limit=10"
        ) or []

        results = []
        for s in noshows:
            existing = await _sb(client, "GET",
                f"/agent_queue?business_id=eq.{req.business_id}&agent=eq.session"
                f"&contact_id=eq.{s['contact_id']}&action_type=eq.follow_up"
                f"&select=id&limit=1"
            )
            if existing and len(existing) > 0:
                continue
            r = await _noshow_one_session(client, biz, s)
            if r:
                results.append(r)

        return {"noshows_checked": len(noshows), "drafts_created": len(results), "results": results}


@router.get("/agents/session/health")
async def session_health():
    return {
        "status": "ok",
        "supabase_configured": bool(_supabase_url()),
        "anthropic_configured": bool(_anthropic_key()),
    }
