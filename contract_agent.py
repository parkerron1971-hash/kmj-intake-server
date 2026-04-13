"""
contract_agent.py — Solutionist System Contract Agent

Drafts proposals and engagement letters when contacts are ready to
convert. Uses the business voice_profile to adapt: a church gets a
partnership proposal, a coach gets a program outline, a consultant
gets a scope of work.

═══════════════════════════════════════════════════════════════════════
DEPLOYMENT
═══════════════════════════════════════════════════════════════════════

1. Drop into Railway project alongside the other agent files.

2. In main.py:
       from contract_agent import router as contract_router
       app.include_router(contract_router)

3. Env vars needed (already set): SUPABASE_URL, SUPABASE_ANON, ANTHROPIC_API_KEY
"""

import json
import logging
import os
from datetime import datetime, timezone
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
MIN_LEAD_SCORE = 60

logger = logging.getLogger("contract_agent")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] contract: %(message)s"))
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
        logger.error(f"Supabase {method} {path}: {resp.status_code} {resp.text}")
        return None
    text = resp.text
    return json.loads(text) if text else None


async def _call_claude(client: httpx.AsyncClient, system: str, user_msg: str, max_tokens=800) -> str:
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
# CORE LOGIC
# ═══════════════════════════════════════════════════════════════════════

async def _draft_proposal(
    client: httpx.AsyncClient,
    business: Dict,
    contact: Dict,
    events: List[Dict],
    queue_history: List[Dict],
    dry_run: bool = False,
) -> Optional[Dict]:

    biz_id = business["id"]
    biz_name = business.get("name", "")
    biz_type = business.get("type", "general")
    voice = business.get("voice_profile", {})
    practitioner = business.get("settings", {}).get("practitioner_name", "the team")
    tone = voice.get("tone", "professional and warm")
    personality = voice.get("personality", "helpful")
    audience = voice.get("audience", "clients")
    comm_style = voice.get("communication_style", [])

    contact_id = contact["id"]
    name = contact.get("name", "there")
    role = contact.get("role") or ""
    email = contact.get("email") or ""
    tags = contact.get("tags") or []
    lead_score = contact.get("lead_score", 0)
    health = contact.get("health_score", 50)
    metadata = contact.get("metadata") or {}

    # Build context from events and queue history
    event_summary = "\n".join(
        f"- {e.get('event_type')} — {e.get('created_at', '?')[:10]}: {json.dumps(e.get('data', {}))[:100]}"
        for e in events[:8]
    ) or "No events"

    outreach_summary = "\n".join(
        f"- [{q.get('status')}] {q.get('agent')}/{q.get('action_type')}: {q.get('subject', '?')} — {q.get('created_at', '?')[:10]}"
        for q in queue_history[:5]
    ) or "No prior outreach"

    # Submission data from intake (if available)
    submission = metadata.get("submission", {})
    submission_text = "\n".join(f"- {k}: {v}" for k, v in submission.items() if v) if submission else "No intake data"

    # Business-type-specific framing
    type_framing = {
        "church": "a partnership proposal for ministry engagement",
        "coaching": "a coaching program outline with session details and expected outcomes",
        "agency": "a professional scope of work with deliverables and timeline",
        "nonprofit": "a program partnership proposal with impact metrics",
        "ecommerce": "a creative services proposal with project scope",
        "general": "a professional engagement proposal",
    }
    proposal_type = type_framing.get(biz_type, type_framing["general"])

    system_prompt = f"""You are the Contract Agent for {biz_name}. Draft {proposal_type} from {practitioner} to {name}.

Voice profile: tone is "{tone}", personality is "{personality}", audience is "{audience}", style is "{', '.join(comm_style) if comm_style else tone}".

This is a {biz_type} business. Adapt completely:
- Church: partnership language, ministry impact, spiritual alignment
- Coaching: transformation journey, session structure, accountability
- Consulting: scope, deliverables, timeline, ROI
- Nonprofit: mission alignment, community impact, collaboration
- Freelance: creative vision, project milestones, collaboration style

The proposal should include:
1. A personalized opening referencing their specific situation and needs
2. What you're proposing (scope of engagement)
3. Expected outcomes or impact
4. Next steps to get started

Keep it professional but warm. Sign off as {practitioner}. This should feel like a real proposal, not a template."""

    user_msg = f"""Contact: {name}
Role: {role or "not specified"}
Email: {email}
Lead Score: {lead_score}/100
Health Score: {health}/100
Tags: {', '.join(tags) if tags else 'none'}

Intake submission:
{submission_text}

Interaction history:
{event_summary}

Prior outreach:
{outreach_summary}

Draft the proposal."""

    draft_body = await _call_claude(client, system_prompt, user_msg)
    if not draft_body:
        draft_body = f"Hi {name},\n\nThank you for your interest in working with {biz_name}. I'd love to discuss how we can help. Let's schedule a time to talk through the details.\n\nBest,\n{practitioner}"

    subject = f"Proposal for {name} — {biz_name}"
    reasoning = f"Lead score: {lead_score}/100. Contact has been engaged through outreach and shows conversion readiness."
    if submission:
        reasoning += f" Original inquiry mentioned: {list(submission.values())[0][:80] if submission.values() else 'N/A'}."

    result = {
        "contact_id": contact_id,
        "contact_name": name,
        "subject": subject,
        "body": draft_body,
        "priority": "high",
        "ai_reasoning": reasoning,
        "lead_score": lead_score,
    }

    if dry_run:
        return result

    # Insert into agent_queue
    await _sb(client, "POST", "/agent_queue", {
        "business_id": biz_id,
        "contact_id": contact_id,
        "agent": "contract",
        "action_type": "proposal",
        "subject": subject,
        "body": draft_body,
        "channel": "email" if email else "in_app",
        "status": "draft",
        "priority": "high",
        "ai_reasoning": reasoning,
        "ai_model": DRAFT_MODEL,
    })

    # Log event
    await _sb(client, "POST", "/events", {
        "business_id": biz_id,
        "contact_id": contact_id,
        "event_type": "contract_draft_created",
        "data": {"lead_score": lead_score, "proposal_type": biz_type},
        "source": "contract_agent",
    })

    logger.info(f"Proposal drafted for {name} (lead_score={lead_score})")
    return result


# ═══════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════

router = APIRouter(tags=["contract_agent"])

class ContractRequest(BaseModel):
    business_id: str

class ContractPreviewRequest(BaseModel):
    business_id: str
    contact_id: str


@router.post("/agents/contract/generate")
async def contract_generate(req: ContractRequest):
    async with httpx.AsyncClient() as client:
        businesses = await _sb(client, "GET", f"/businesses?id=eq.{req.business_id}&select=*&limit=1")
        if not businesses:
            raise HTTPException(404, "Business not found")
        biz = businesses[0]

        # Find conversion-ready contacts:
        # High lead score OR has been engaged (agent_message_sent event exists)
        contacts = await _sb(client, "GET",
            f"/contacts?business_id=eq.{req.business_id}"
            f"&lead_score=gte.{MIN_LEAD_SCORE}"
            f"&status=in.(lead,active,vip)"
            f"&order=lead_score.desc&limit=15"
        ) or []

        results = []
        for contact in contacts:
            cid = contact["id"]

            # Skip if contract draft already exists
            existing = await _sb(client, "GET",
                f"/agent_queue?contact_id=eq.{cid}&agent=eq.contract"
                f"&action_type=eq.proposal&select=id&limit=1"
            )
            if existing and len(existing) > 0:
                continue

            events = await _sb(client, "GET",
                f"/events?contact_id=eq.{cid}&order=created_at.desc&limit=8") or []
            queue_history = await _sb(client, "GET",
                f"/agent_queue?contact_id=eq.{cid}&order=created_at.desc&limit=5"
                f"&select=agent,action_type,subject,status,created_at") or []

            r = await _draft_proposal(client, biz, contact, events, queue_history)
            if r:
                results.append(r)

        return {
            "business_id": req.business_id,
            "contacts_evaluated": len(contacts),
            "proposals_drafted": len(results),
            "results": results,
        }


@router.post("/agents/contract/preview")
async def contract_preview(req: ContractPreviewRequest):
    async with httpx.AsyncClient() as client:
        businesses = await _sb(client, "GET", f"/businesses?id=eq.{req.business_id}&select=*&limit=1")
        if not businesses:
            raise HTTPException(404, "Business not found")
        contacts = await _sb(client, "GET", f"/contacts?id=eq.{req.contact_id}&select=*&limit=1")
        if not contacts:
            raise HTTPException(404, "Contact not found")
        events = await _sb(client, "GET",
            f"/events?contact_id=eq.{req.contact_id}&order=created_at.desc&limit=8") or []
        queue_history = await _sb(client, "GET",
            f"/agent_queue?contact_id=eq.{req.contact_id}&order=created_at.desc&limit=5"
            f"&select=agent,action_type,subject,status,created_at") or []
        result = await _draft_proposal(client, businesses[0], contacts[0], events, queue_history, dry_run=True)
        if not result:
            raise HTTPException(500, "Failed to generate preview")
        return result


@router.get("/agents/contract/health")
async def contract_health():
    return {
        "status": "ok",
        "supabase_configured": bool(_supabase_url()),
        "anthropic_configured": bool(_anthropic_key()),
        "min_lead_score": MIN_LEAD_SCORE,
    }
