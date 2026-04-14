"""
payment_agent.py — Solutionist System Payment Agent

Three scans on each run:
1. Overdue reminders for contacts whose proposals were approved but
   no payment received within 14 days
2. Personalized thank-yous for recent payments
3. Trend alerts for declining payment/giving volume

═══════════════════════════════════════════════════════════════════════
DEPLOYMENT
═══════════════════════════════════════════════════════════════════════

1. Drop into Railway project alongside the other agent files.

2. In main.py:
       from payment_agent import router as payment_router
       app.include_router(payment_router)

3. Env vars: SUPABASE_URL, SUPABASE_ANON, ANTHROPIC_API_KEY (already set)

Note on event types this agent reads:
- contract_signed — log this event when a contact signs/agrees
- payment_received / giving_received — log when money comes in
- agent_message_sent — already logged by ApprovalQueue on approve
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

OVERDUE_THRESHOLD_DAYS = 14
TRENDS_WINDOW_DAYS = 90
TRENDS_DECLINE_THRESHOLD = 0.15  # 15% drop
THANK_YOU_LOOKBACK_HOURS = 48

PAYMENT_EVENT_TYPES = ("payment_received", "giving_received", "donation_received", "deposit_paid", "balance_paid")

logger = logging.getLogger("payment_agent")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] payment: %(message)s"))
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


def _money_tone_for(biz_type: str) -> str:
    if biz_type == "church":
        return "Be pastoral, never transactional about money. Frame it as stewardship and partnership in ministry."
    if biz_type == "nonprofit":
        return "Be appreciative and mission-focused. Frame it as partnership in impact."
    return "Be warm but clear about the business relationship. Professional, not stiff."


# ═══════════════════════════════════════════════════════════════════════
# SCAN 1: OVERDUE REMINDERS
# ═══════════════════════════════════════════════════════════════════════

async def _scan_overdue(client: httpx.AsyncClient, business: Dict) -> List[Dict]:
    biz_id = business["id"]
    biz_type = business.get("type", "general")
    biz_name = business.get("name", "")
    voice = business.get("voice_profile", {})
    practitioner = business.get("settings", {}).get("practitioner_name", "the team")
    tone = voice.get("tone", "warm and professional")
    money_tone = _money_tone_for(biz_type)

    # Find contacts with contract_signed events older than threshold
    cutoff = (datetime.now(timezone.utc) - timedelta(days=OVERDUE_THRESHOLD_DAYS)).isoformat()
    signed_events = await _sb(client, "GET",
        f"/events?business_id=eq.{biz_id}&event_type=eq.contract_signed"
        f"&created_at=lte.{cutoff}&order=created_at.desc&limit=30"
    ) or []

    # Also look for proposals approved via agent_message_sent
    approved_proposals = await _sb(client, "GET",
        f"/events?business_id=eq.{biz_id}&event_type=eq.agent_message_sent"
        f"&created_at=lte.{cutoff}&order=created_at.desc&limit=30"
    ) or []
    approved_proposals = [e for e in approved_proposals if (e.get("data") or {}).get("action_type") == "proposal"]

    triggers = signed_events + approved_proposals
    results = []

    for ev in triggers:
        contact_id = ev.get("contact_id")
        if not contact_id:
            continue

        # Has a payment event happened since this trigger?
        trigger_dt = ev.get("created_at", "")
        payment_check = await _sb(client, "GET",
            f"/events?contact_id=eq.{contact_id}"
            f"&event_type=in.({','.join(PAYMENT_EVENT_TYPES)})"
            f"&created_at=gte.{trigger_dt}&select=id&limit=1"
        )
        if payment_check and len(payment_check) > 0:
            continue

        # Already drafted a payment reminder for this contact recently?
        existing = await _sb(client, "GET",
            f"/agent_queue?contact_id=eq.{contact_id}&agent=eq.payment&action_type=eq.invoice"
            f"&status=in.(draft,approved)&select=id&limit=1"
        )
        if existing and len(existing) > 0:
            continue

        # Get contact info
        contacts = await _sb(client, "GET", f"/contacts?id=eq.{contact_id}&select=*&limit=1")
        if not contacts:
            continue
        contact = contacts[0]
        name = contact.get("name", "there")

        # Calculate days overdue
        try:
            trigger_time = datetime.fromisoformat(trigger_dt.replace("Z", "+00:00"))
            days_overdue = (datetime.now(timezone.utc) - trigger_time).days
        except:
            days_overdue = OVERDUE_THRESHOLD_DAYS

        priority = "high" if days_overdue >= 21 else "medium"

        system_prompt = f"""You are the Payment Agent for {biz_name}. Draft a gentle payment/contribution reminder from {practitioner} to {name}.

{money_tone}

Voice: tone is "{tone}". Keep it under 4 sentences. Don't be aggressive or guilt-inducing. Sign off as {practitioner}."""

        user_msg = f"""Contact: {name}
{practitioner} agreed to work with this contact {days_overdue} days ago, but no payment has been recorded yet.

Draft a gentle reminder."""

        body = await _call_claude(client, system_prompt, user_msg)
        if not body:
            body = f"Hi {name}, just a friendly check-in on the next steps for our agreement. Let me know if you have any questions. — {practitioner}"

        await _sb(client, "POST", "/agent_queue", {
            "business_id": biz_id,
            "contact_id": contact_id,
            "agent": "payment",
            "action_type": "invoice",
            "subject": f"Following up — {name}",
            "body": body,
            "channel": "email" if contact.get("email") else "in_app",
            "status": "draft",
            "priority": priority,
            "ai_reasoning": f"Agreement reached {days_overdue} days ago — no payment recorded since. Threshold: {OVERDUE_THRESHOLD_DAYS}d.",
            "ai_model": DRAFT_MODEL,
        })

        await _sb(client, "POST", "/events", {
            "business_id": biz_id,
            "contact_id": contact_id,
            "event_type": "payment_reminder_created",
            "data": {"days_overdue": days_overdue, "priority": priority},
            "source": "payment_agent",
        })

        results.append({"contact_id": contact_id, "name": name, "days_overdue": days_overdue, "priority": priority})

    return results


# ═══════════════════════════════════════════════════════════════════════
# SCAN 2: PAYMENT THANK-YOUS
# ═══════════════════════════════════════════════════════════════════════

async def _scan_thank_yous(client: httpx.AsyncClient, business: Dict) -> List[Dict]:
    biz_id = business["id"]
    biz_type = business.get("type", "general")
    biz_name = business.get("name", "")
    voice = business.get("voice_profile", {})
    practitioner = business.get("settings", {}).get("practitioner_name", "the team")
    tone = voice.get("tone", "warm and professional")
    money_tone = _money_tone_for(biz_type)

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=THANK_YOU_LOOKBACK_HOURS)).isoformat()
    payment_events = await _sb(client, "GET",
        f"/events?business_id=eq.{biz_id}"
        f"&event_type=in.({','.join(PAYMENT_EVENT_TYPES)})"
        f"&created_at=gte.{cutoff}&order=created_at.desc&limit=30"
    ) or []

    results = []
    for ev in payment_events:
        contact_id = ev.get("contact_id")
        if not contact_id:
            continue

        # Already thanked?
        existing = await _sb(client, "GET",
            f"/agent_queue?contact_id=eq.{contact_id}&agent=eq.payment"
            f"&action_type=eq.email&status=in.(draft,approved)"
            f"&created_at=gte.{cutoff}&select=id&limit=1"
        )
        if existing and len(existing) > 0:
            continue

        contacts = await _sb(client, "GET", f"/contacts?id=eq.{contact_id}&select=*&limit=1")
        if not contacts:
            continue
        contact = contacts[0]
        name = contact.get("name", "there")
        amount = (ev.get("data") or {}).get("amount", "")

        system_prompt = f"""You are the Payment Agent for {biz_name}. Draft a brief, sincere thank-you from {practitioner} to {name} for their recent {ev.get('event_type', 'payment').replace('_', ' ')}.

{money_tone}

Voice: tone is "{tone}". Keep it to 2-3 sentences. Sign off as {practitioner}."""

        amount_str = f" of ${amount}" if amount else ""
        user_msg = f"{name} just made a {ev.get('event_type', 'payment').replace('_', ' ')}{amount_str}. Draft a short thank-you."

        body = await _call_claude(client, system_prompt, user_msg, max_tokens=250)
        if not body:
            body = f"Hi {name}, just a quick note to say thank you. Truly grateful. — {practitioner}"

        await _sb(client, "POST", "/agent_queue", {
            "business_id": biz_id,
            "contact_id": contact_id,
            "agent": "payment",
            "action_type": "email",
            "subject": f"Thank you, {name}",
            "body": body,
            "channel": "email" if contact.get("email") else "in_app",
            "status": "draft",
            "priority": "medium",
            "ai_reasoning": f"Recent {ev.get('event_type')} from this contact. Drafted a thank-you within {THANK_YOU_LOOKBACK_HOURS}h window.",
            "ai_model": DRAFT_MODEL,
        })

        await _sb(client, "POST", "/events", {
            "business_id": biz_id,
            "contact_id": contact_id,
            "event_type": "payment_thankyou_created",
            "data": {"amount": amount, "trigger_event": ev.get("event_type")},
            "source": "payment_agent",
        })

        results.append({"contact_id": contact_id, "name": name, "amount": amount})

    return results


# ═══════════════════════════════════════════════════════════════════════
# SCAN 3: TREND ALERTS
# ═══════════════════════════════════════════════════════════════════════

async def _scan_trends(client: httpx.AsyncClient, business: Dict) -> Optional[Dict]:
    biz_id = business["id"]
    biz_type = business.get("type", "general")
    biz_name = business.get("name", "")
    practitioner = business.get("settings", {}).get("practitioner_name", "the team")

    now = datetime.now(timezone.utc)
    window_end = now.isoformat()
    window_mid = (now - timedelta(days=TRENDS_WINDOW_DAYS)).isoformat()
    window_start = (now - timedelta(days=TRENDS_WINDOW_DAYS * 2)).isoformat()

    recent = await _sb(client, "GET",
        f"/events?business_id=eq.{biz_id}"
        f"&event_type=in.({','.join(PAYMENT_EVENT_TYPES)})"
        f"&created_at=gte.{window_mid}&created_at=lte.{window_end}"
        f"&select=event_type,data,created_at&limit=500"
    ) or []
    prior = await _sb(client, "GET",
        f"/events?business_id=eq.{biz_id}"
        f"&event_type=in.({','.join(PAYMENT_EVENT_TYPES)})"
        f"&created_at=gte.{window_start}&created_at=lt.{window_mid}"
        f"&select=event_type,data,created_at&limit=500"
    ) or []

    if not prior or len(prior) < 3:
        return None  # Not enough historical data to compare

    def _sum(events):
        total = 0.0
        for e in events:
            amt = (e.get("data") or {}).get("amount")
            if amt is not None:
                try: total += float(amt)
                except: pass
        return total

    recent_sum = _sum(recent)
    prior_sum = _sum(prior)
    recent_count = len(recent)
    prior_count = len(prior)

    if prior_sum == 0 and prior_count == 0:
        return None

    sum_change = (recent_sum - prior_sum) / prior_sum if prior_sum > 0 else 0
    count_change = (recent_count - prior_count) / prior_count if prior_count > 0 else 0

    # Trigger if either metric is down 15%+
    if sum_change > -TRENDS_DECLINE_THRESHOLD and count_change > -TRENDS_DECLINE_THRESHOLD:
        return None

    # Already alerted recently?
    cutoff = (now - timedelta(days=14)).isoformat()
    existing = await _sb(client, "GET",
        f"/agent_queue?business_id=eq.{biz_id}&agent=eq.payment&action_type=eq.alert"
        f"&created_at=gte.{cutoff}&select=id&limit=1"
    )
    if existing and len(existing) > 0:
        return None

    metric_name = "giving" if biz_type in ("church", "nonprofit") else "payments"
    sum_pct = round(sum_change * 100)
    count_pct = round(count_change * 100)

    system_prompt = f"""You are the Payment Agent for {biz_name}. Draft an internal alert TO {practitioner} (not to a contact) about a decline in {metric_name}.

This is a heads-up, not a crisis report. Be perceptive and actionable. Suggest one specific thing to look at. Under 4 sentences."""

    user_msg = f"""{metric_name.title()} comparison:
- Last {TRENDS_WINDOW_DAYS} days: {recent_count} events, ${recent_sum:.2f} total
- Prior {TRENDS_WINDOW_DAYS} days: {prior_count} events, ${prior_sum:.2f} total
- Change: {sum_pct}% in volume, {count_pct}% in frequency

Draft the alert."""

    body = await _call_claude(client, system_prompt, user_msg, max_tokens=400)
    if not body:
        body = f"{metric_name.title()} appear to be down {abs(sum_pct)}% over the last {TRENDS_WINDOW_DAYS} days vs the prior period. Worth a closer look."

    await _sb(client, "POST", "/agent_queue", {
        "business_id": biz_id,
        "contact_id": None,
        "agent": "payment",
        "action_type": "alert",
        "subject": f"⚠ {metric_name.title()} trend alert",
        "body": body,
        "channel": "in_app",
        "status": "draft",
        "priority": "high",
        "ai_reasoning": f"{metric_name.title()} down {abs(sum_pct)}% in volume / {abs(count_pct)}% in frequency over last {TRENDS_WINDOW_DAYS}d vs prior period.",
        "ai_model": DRAFT_MODEL,
    })

    await _sb(client, "POST", "/events", {
        "business_id": biz_id,
        "event_type": "payment_trend_alert",
        "data": {
            "metric": metric_name,
            "recent_sum": recent_sum, "prior_sum": prior_sum,
            "recent_count": recent_count, "prior_count": prior_count,
            "sum_change_pct": sum_pct, "count_change_pct": count_pct,
        },
        "source": "payment_agent",
    })

    return {
        "metric": metric_name,
        "sum_change_pct": sum_pct,
        "count_change_pct": count_pct,
        "recent_count": recent_count,
        "prior_count": prior_count,
    }


# ═══════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════

router = APIRouter(tags=["payment_agent"])

class PaymentRequest(BaseModel):
    business_id: str


@router.post("/agents/payment/check")
async def payment_check(req: PaymentRequest):
    async with httpx.AsyncClient() as client:
        businesses = await _sb(client, "GET", f"/businesses?id=eq.{req.business_id}&select=*&limit=1")
        if not businesses:
            raise HTTPException(404, "Business not found")
        biz = businesses[0]

        overdue = await _scan_overdue(client, biz)
        thank_yous = await _scan_thank_yous(client, biz)
        trend_alert = await _scan_trends(client, biz)

        logger.info(f"Payment scan for {biz.get('name')}: {len(overdue)} overdue, {len(thank_yous)} thank-yous, alert={trend_alert is not None}")

        return {
            "business_id": req.business_id,
            "overdue_reminders": overdue,
            "thank_yous": thank_yous,
            "trend_alert": trend_alert,
            "drafts_created": len(overdue) + len(thank_yous) + (1 if trend_alert else 0),
        }


@router.get("/agents/payment/health")
async def payment_health():
    return {
        "status": "ok",
        "supabase_configured": bool(_supabase_url()),
        "anthropic_configured": bool(_anthropic_key()),
        "overdue_threshold_days": OVERDUE_THRESHOLD_DAYS,
        "trends_window_days": TRENDS_WINDOW_DAYS,
        "trends_decline_threshold": TRENDS_DECLINE_THRESHOLD,
        "payment_event_types": PAYMENT_EVENT_TYPES,
    }
