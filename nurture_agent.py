"""
nurture_agent.py — Solutionist System Nurture Agent

Catches relationships slipping through the cracks. Reads the business's
voice_profile to draft re-engagement messages that sound like the
practitioner, not a chatbot.

═══════════════════════════════════════════════════════════════════════
DEPLOYMENT
═══════════════════════════════════════════════════════════════════════

1. Drop into your Railway project alongside ai_proxy.py.

2. In main.py:
       from nurture_agent import router as nurture_router
       app.include_router(nurture_router)

3. Env vars needed (already set from prior steps):
       SUPABASE_URL, SUPABASE_ANON, ANTHROPIC_API_KEY

4. Optional: schedule daily auto-run with APScheduler in main.py:
       from apscheduler.schedulers.asyncio import AsyncIOScheduler
       from nurture_agent import run_nurture_for_all

       scheduler = AsyncIOScheduler()
       scheduler.add_job(run_nurture_for_all, "cron", hour=6, timezone="US/Eastern")

       @app.on_event("startup")
       async def start_scheduler():
           scheduler.start()
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
DRAFT_MODEL = "claude-sonnet-4-5-20250929"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)

DEFAULT_THRESHOLDS = {
    "church": 14,
    "coaching": 7,
    "agency": 21,
    "nonprofit": 14,
    "ecommerce": 14,
    "saas": 21,
    "general": 14,
}

MIN_HEALTH = 5
MAX_HEALTH = 100
HEALTH_DECAY_PER_DAY = 2
HEALTH_BOOST_PER_INTERACTION = 5
RECENT_OUTREACH_COOLDOWN_DAYS = 7

logger = logging.getLogger("nurture_agent")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] nurture: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


def _supabase_url():
    return os.environ.get("SUPABASE_URL", "")

def _supabase_anon():
    return os.environ.get("SUPABASE_ANON", "")

def _anthropic_key():
    return os.environ.get("ANTHROPIC_API_KEY", "")


# ═══════════════════════════════════════════════════════════════════════
# SUPABASE HELPERS
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


async def _call_claude(client: httpx.AsyncClient, system: str, user_msg: str, max_tokens=400) -> str:
    key = _anthropic_key()
    if not key:
        return ""
    resp = await client.post(ANTHROPIC_API_URL, headers={
        "x-api-key": key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json",
    }, json={
        "model": DRAFT_MODEL, "max_tokens": max_tokens, "system": system,
        "messages": [{"role": "user", "content": user_msg}],
    }, timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        logger.warning(f"Claude error: {resp.status_code}")
        return ""
    data = resp.json()
    return "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict)).strip()


# ═══════════════════════════════════════════════════════════════════════
# CORE NURTURE LOGIC
# ═══════════════════════════════════════════════════════════════════════

async def _nurture_one_contact(
    client: httpx.AsyncClient,
    business: Dict,
    contact: Dict,
    events: List[Dict],
    dry_run: bool = False,
) -> Optional[Dict]:
    """Draft a nurture message for one contact. Returns the draft dict or None."""

    name = contact.get("name", "there")
    contact_id = contact["id"]
    biz_id = business["id"]
    biz_name = business.get("name", "")
    biz_type = business.get("type", "general")
    voice = business.get("voice_profile", {})
    practitioner = business.get("settings", {}).get("practitioner_name", "the team")

    last_interaction = contact.get("last_interaction")
    days_ago = 0
    if last_interaction:
        try:
            li = datetime.fromisoformat(last_interaction.replace("Z", "+00:00"))
            days_ago = (datetime.now(timezone.utc) - li).days
        except:
            days_ago = 30

    health = contact.get("health_score", 50)
    role = contact.get("role") or ""
    tags = contact.get("tags") or []
    status = contact.get("status", "active")

    # Build event summary
    event_summary = ""
    if events:
        recent = events[:5]
        event_summary = "\n".join(
            f"- {e.get('event_type', '?')} ({e.get('source', '?')}) — {e.get('created_at', '?')[:10]}"
            for e in recent
        )

    # Build system prompt using voice profile
    tone = voice.get("tone", "warm and professional")
    personality = voice.get("personality", "helpful")
    audience = voice.get("audience", "clients")
    comm_style = voice.get("communication_style", [])
    transcript_hint = ""
    if voice.get("onboarding_transcript"):
        # Include a brief summary, not the whole transcript
        transcript_hint = f"\nFrom the onboarding conversation, the practitioner described their audience as: {voice.get('audience', 'their community')}"

    system_prompt = f"""You are the Nurture Agent for {biz_name}. You write in the voice of {practitioner}.

Voice profile:
- Tone: {tone}
- Personality: {personality}
- Audience: {audience}
- Communication style: {', '.join(comm_style) if comm_style else tone}
{transcript_hint}

This is a {biz_type} business. Adjust your language accordingly:
- Church/ministry: pastoral warmth, community language, genuine care
- Coaching/mentorship: encouragement toward goals, accountability, growth
- Consulting/agency: professional check-in, value-oriented, strategic
- Nonprofit: mission-focused, community impact, appreciation
- Freelance/creative: personal, creative, collaborative

Draft a personal re-engagement message to {name}. Keep it under 4 sentences. Sound genuinely personal — not like a template. Reference something specific about their situation if possible. Sign off as {practitioner}."""

    user_msg = f"""Contact: {name}
Role: {role or "not specified"}
Status: {status}
Tags: {', '.join(tags) if tags else 'none'}
Health score: {health}/100
Last interaction: {days_ago} days ago
Recent events:
{event_summary or "No recent events recorded"}

Draft a warm re-engagement message. This person has been quiet for {days_ago} days."""

    # Determine action type and priority
    action_type = "check_in" if days_ago < 30 else "follow_up"
    priority = "high" if health < 30 else "medium" if health <= 50 else "low"
    channel = "email" if contact.get("email") else "sms" if contact.get("phone") else "in_app"

    # Build reasoning
    reasoning = f"Last interaction {days_ago} days ago. Health score: {health}/100."
    if health < 30:
        reasoning += " Contact is at critical risk of disengagement."
    elif health < 50:
        reasoning += " Contact shows signs of declining engagement."
    if tags:
        reasoning += f" Tags: {', '.join(tags)}."

    # Call AI for the draft
    draft_body = await _call_claude(client, system_prompt, user_msg)
    if not draft_body:
        draft_body = f"Hi {name}, just checking in — it's been a little while. Hope all is well. — {practitioner}"

    subject = f"Checking in, {name}"

    result = {
        "contact_id": contact_id,
        "contact_name": name,
        "agent": "nurture",
        "action_type": action_type,
        "subject": subject,
        "body": draft_body,
        "channel": channel,
        "priority": priority,
        "ai_reasoning": reasoning,
        "ai_model": DRAFT_MODEL,
        "health_score": health,
        "days_since_interaction": days_ago,
    }

    if dry_run:
        return result

    # Insert into agent_queue
    await _sb(client, "POST", "/agent_queue", {
        "business_id": biz_id,
        "contact_id": contact_id,
        "agent": "nurture",
        "action_type": action_type,
        "subject": subject,
        "body": draft_body,
        "channel": channel,
        "status": "draft",
        "priority": priority,
        "ai_reasoning": reasoning,
        "ai_model": DRAFT_MODEL,
    })

    # Log event
    await _sb(client, "POST", "/events", {
        "business_id": biz_id,
        "contact_id": contact_id,
        "event_type": "nurture_draft_created",
        "data": {"days_since_interaction": days_ago, "health_score": health, "priority": priority},
        "source": "nurture_agent",
    })

    return result


async def _run_nurture(client: httpx.AsyncClient, business: Dict) -> Dict:
    """Run the nurture agent for one business. Returns summary."""
    biz_id = business["id"]
    biz_type = business.get("type", "general")
    settings = business.get("settings") or {}

    # Determine threshold
    custom_thresholds = settings.get("nurture_thresholds", {})
    threshold_days = custom_thresholds.get("inactivity_days") or DEFAULT_THRESHOLDS.get(biz_type, 14)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=threshold_days)).isoformat()

    # Debug: fetch ALL contacts for this business (unfiltered) so response shows raw state
    all_contacts = await _sb(client, "GET",
        f"/contacts?business_id=eq.{biz_id}&select=id,name,status,health_score,last_interaction&limit=50"
    ) or []

    # Get contacts needing attention
    contacts = await _sb(client, "GET",
        f"/contacts?business_id=eq.{biz_id}&status=in.(active,lead,vip)"
        f"&or=(last_interaction.is.null,last_interaction.lt.{cutoff})"
        f"&order=health_score.asc&limit=20"
    ) or []

    drafts_created = 0
    flagged = []

    for contact in contacts:
        cid = contact["id"]

        # Check if we already reached out recently
        recent_outreach = await _sb(client, "GET",
            f"/agent_queue?contact_id=eq.{cid}&agent=eq.nurture"
            f"&created_at=gte.{(datetime.now(timezone.utc) - timedelta(days=RECENT_OUTREACH_COOLDOWN_DAYS)).isoformat()}"
            f"&select=id&limit=1"
        )
        if recent_outreach and len(recent_outreach) > 0:
            continue

        # Get recent events
        events = await _sb(client, "GET",
            f"/events?contact_id=eq.{cid}&order=created_at.desc&limit=5"
        ) or []

        result = await _nurture_one_contact(client, business, contact, events)
        if result:
            flagged.append({"contact_id": cid, "name": contact.get("name"), "reason": result["ai_reasoning"]})
            drafts_created += 1

    # Log nurture_triggered event for the batch
    if flagged:
        await _sb(client, "POST", "/events", {
            "business_id": biz_id,
            "event_type": "nurture_triggered",
            "data": {"contacts_flagged": len(flagged), "threshold_days": threshold_days, "contacts": flagged},
            "source": "nurture_agent",
        })

    logger.info(f"Nurture run for {business.get('name')}: {len(contacts)} checked, {drafts_created} drafts created")

    return {
        "business_id": biz_id,
        "contacts_checked": len(contacts),
        "drafts_created": drafts_created,
        "flagged": flagged,
        "debug_cutoff": str(cutoff),
        "debug_business_type": biz_type,
        "debug_threshold_days": threshold_days,
        "debug_all_contacts": all_contacts,
        "debug_filtered_count": len(contacts),
    }


async def _run_health_decay(client: httpx.AsyncClient, business: Dict) -> Dict:
    """Run health score decay/recovery for one business."""
    biz_id = business["id"]
    now = datetime.now(timezone.utc)
    seven_days_ago = (now - timedelta(days=7)).isoformat()

    contacts = await _sb(client, "GET",
        f"/contacts?business_id=eq.{biz_id}&status=in.(active,lead,vip)&select=id,health_score,last_interaction"
    ) or []

    updated = 0
    for contact in contacts:
        cid = contact["id"]
        health = contact.get("health_score", 50)
        last = contact.get("last_interaction")

        if not last:
            # No interaction ever — decay
            new_health = max(MIN_HEALTH, health - HEALTH_DECAY_PER_DAY)
        else:
            try:
                li = datetime.fromisoformat(last.replace("Z", "+00:00"))
                days_inactive = (now - li).days
            except:
                days_inactive = 30

            if days_inactive <= 7:
                continue  # Active recently, no decay

            # Check if we sent them something recently (give time to respond)
            recent_sent = await _sb(client, "GET",
                f"/agent_queue?contact_id=eq.{cid}&status=eq.approved"
                f"&reviewed_at=gte.{seven_days_ago}&select=id&limit=1"
            )
            if recent_sent and len(recent_sent) > 0:
                continue  # Recently contacted, give them time

            decay = min(days_inactive - 7, 10) * HEALTH_DECAY_PER_DAY
            new_health = max(MIN_HEALTH, health - decay)

        if new_health != health:
            await _sb(client, "PATCH", f"/contacts?id=eq.{cid}", {"health_score": new_health})
            updated += 1

    logger.info(f"Health decay for {business.get('name')}: {updated}/{len(contacts)} updated")
    return {"business_id": biz_id, "contacts_checked": len(contacts), "scores_updated": updated}


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC: for APScheduler daily run
# ═══════════════════════════════════════════════════════════════════════

async def run_nurture_for_all():
    """Run nurture + health decay for all businesses with auto-run enabled."""
    async with httpx.AsyncClient() as client:
        businesses = await _sb(client, "GET",
            "/businesses?is_active=eq.true&select=*"
        ) or []
        for biz in businesses:
            settings = biz.get("settings") or {}
            if settings.get("nurture_auto_run", False):
                await _run_health_decay(client, biz)
                await _run_nurture(client, biz)


# ═══════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════

router = APIRouter(tags=["nurture_agent"])


class NurtureRunRequest(BaseModel):
    business_id: str

class NurturePreviewRequest(BaseModel):
    business_id: str
    contact_id: str


@router.post("/agents/nurture/run")
async def nurture_run(req: NurtureRunRequest):
    async with httpx.AsyncClient() as client:
        businesses = await _sb(client, "GET", f"/businesses?id=eq.{req.business_id}&select=*&limit=1")
        if not businesses:
            raise HTTPException(404, "Business not found")
        result = await _run_nurture(client, businesses[0])
        return result


@router.post("/agents/nurture/preview")
async def nurture_preview(req: NurturePreviewRequest):
    async with httpx.AsyncClient() as client:
        businesses = await _sb(client, "GET", f"/businesses?id=eq.{req.business_id}&select=*&limit=1")
        if not businesses:
            raise HTTPException(404, "Business not found")
        contacts = await _sb(client, "GET", f"/contacts?id=eq.{req.contact_id}&select=*&limit=1")
        if not contacts:
            raise HTTPException(404, "Contact not found")
        events = await _sb(client, "GET",
            f"/events?contact_id=eq.{req.contact_id}&order=created_at.desc&limit=5") or []
        result = await _nurture_one_contact(client, businesses[0], contacts[0], events, dry_run=True)
        if not result:
            raise HTTPException(500, "Failed to generate preview")
        return result


@router.post("/agents/health-decay/run")
async def health_decay_run(req: NurtureRunRequest):
    async with httpx.AsyncClient() as client:
        businesses = await _sb(client, "GET", f"/businesses?id=eq.{req.business_id}&select=*&limit=1")
        if not businesses:
            raise HTTPException(404, "Business not found")
        return await _run_health_decay(client, businesses[0])


@router.get("/agents/nurture/health")
async def nurture_health():
    return {
        "status": "ok",
        "supabase_configured": bool(_supabase_url()),
        "anthropic_configured": bool(_anthropic_key()),
        "default_thresholds": DEFAULT_THRESHOLDS,
    }
