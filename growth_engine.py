"""
growth_engine.py — Solutionist System Growth Engine

Three endpoints feed the GROW tab:
1. /agents/growth/briefing     — AI-generated weekly briefing (stored as insight)
2. /agents/growth/health-report — structured contact-health JSON (no AI)
3. /agents/growth/insights     — AI scans last 30d → 3-5 actionable insights

═══════════════════════════════════════════════════════════════════════
DEPLOYMENT
═══════════════════════════════════════════════════════════════════════

1. Drop into the Railway project alongside the other agent files.

2. In main.py:
       from growth_engine import router as growth_router
       app.include_router(growth_router)

3. Env vars (already set): SUPABASE_URL, SUPABASE_ANON, ANTHROPIC_API_KEY

Briefings are stored in `insights` with insight_type='observation' and
evidence.kind='weekly_briefing' so the client can distinguish them from
the general insights feed (the `insight_type` CHECK constraint does not
allow 'weekly_briefing' directly).
"""

import json
import logging
import os
import re
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
BRIEFING_MODEL = "claude-sonnet-4-5-20250929"
INSIGHTS_MODEL = "claude-sonnet-4-5-20250929"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0)

BRIEFING_WINDOW_DAYS = 7
INSIGHTS_WINDOW_DAYS = 30

# Briefing action-generation caps
ACTION_CAP_AT_RISK = 3
ACTION_CAP_INACTIVE = 2
ACTION_CAP_SESSION_FOLLOWUP = 3
ACTION_TOTAL_CAP = 8
ACTION_DEDUP_DAYS = 7
INACTIVE_THRESHOLD_DAYS = 14
SESSION_LOOKBACK_DAYS = 14

VALID_CATEGORIES = {"revenue", "engagement", "churn", "opportunity", "operations", "content", "growth", "other"}
VALID_TYPES = {"observation", "suggestion", "alert", "milestone"}
VALID_PRIORITIES = {"urgent", "high", "medium", "low"}
VALID_ACTION_TYPES = {"email", "sms", "follow_up", "proposal", "invoice", "check_in", "onboarding", "alert", "other"}

CATEGORY_ALIASES = {"retention": "churn", "growth_ops": "operations", "marketing": "content"}

PAYMENT_EVENT_TYPES = ("payment_received", "giving_received", "donation_received", "deposit_paid", "balance_paid")

logger = logging.getLogger("growth_engine")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] growth: %(message)s"))
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


async def _call_claude(client: httpx.AsyncClient, system: str, user_msg: str,
                       model: str = BRIEFING_MODEL, max_tokens: int = 1200) -> str:
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
        logger.warning(f"Claude error: {resp.status_code} {resp.text[:400]}")
        return ""
    data = resp.json()
    return "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict)).strip()


def _sum_amount(events: List[Dict]) -> float:
    total = 0.0
    for e in events:
        amt = (e.get("data") or {}).get("amount")
        if amt is not None:
            try: total += float(amt)
            except (TypeError, ValueError): pass
    return total


def _normalize_category(cat: str) -> str:
    cat = (cat or "").strip().lower()
    cat = CATEGORY_ALIASES.get(cat, cat)
    return cat if cat in VALID_CATEGORIES else "growth"


def _normalize_type(t: str) -> str:
    t = (t or "").strip().lower()
    return t if t in VALID_TYPES else "observation"


def _normalize_priority(p: str) -> str:
    p = (p or "").strip().lower()
    return p if p in VALID_PRIORITIES else "medium"


def _normalize_action_type(a: str) -> str:
    a = (a or "").strip().lower()
    return a if a in VALID_ACTION_TYPES else "other"


def _extract_json_block(text: str) -> Optional[Any]:
    """Pull the first JSON array or object out of a model response."""
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    candidate = fence.group(1).strip() if fence else text.strip()
    for start_ch, end_ch in (("[", "]"), ("{", "}")):
        s = candidate.find(start_ch)
        e = candidate.rfind(end_ch)
        if s >= 0 and e > s:
            try: return json.loads(candidate[s:e + 1])
            except json.JSONDecodeError: continue
    return None


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINT: WEEKLY BRIEFING
# ═══════════════════════════════════════════════════════════════════════

class GrowthRequest(BaseModel):
    business_id: str


async def _gather_briefing_data(client: httpx.AsyncClient, biz_id: str) -> Dict:
    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(days=BRIEFING_WINDOW_DAYS)).isoformat()
    window_end = now.isoformat()
    upcoming_end = (now + timedelta(days=BRIEFING_WINDOW_DAYS)).isoformat()

    # New contacts in window
    new_contacts = await _sb(client, "GET",
        f"/contacts?business_id=eq.{biz_id}&created_at=gte.{window_start}"
        f"&select=id,name,status,source&limit=50"
    ) or []

    # Contacts at risk / thriving right now
    at_risk = await _sb(client, "GET",
        f"/contacts?business_id=eq.{biz_id}&health_score=lt.40"
        f"&status=in.(active,lead,vip)&select=id,name,health_score&limit=20"
    ) or []
    thriving = await _sb(client, "GET",
        f"/contacts?business_id=eq.{biz_id}&health_score=gt.70"
        f"&select=id,name,health_score&limit=10"
    ) or []

    # Events in window, bucketed by type
    events = await _sb(client, "GET",
        f"/events?business_id=eq.{biz_id}&created_at=gte.{window_start}"
        f"&select=event_type,data,created_at&limit=300"
    ) or []
    event_counts: Dict[str, int] = {}
    for ev in events:
        event_counts[ev["event_type"]] = event_counts.get(ev["event_type"], 0) + 1

    payment_events = [e for e in events if e["event_type"] in PAYMENT_EVENT_TYPES]
    payment_sum = _sum_amount(payment_events)

    # Agent queue activity
    queue_window = await _sb(client, "GET",
        f"/agent_queue?business_id=eq.{biz_id}&created_at=gte.{window_start}"
        f"&select=agent,status&limit=300"
    ) or []
    drafts_by_agent: Dict[str, Dict[str, int]] = {}
    for q in queue_window:
        bucket = drafts_by_agent.setdefault(q["agent"], {"draft": 0, "approved": 0, "dismissed": 0, "sent": 0})
        bucket[q["status"]] = bucket.get(q["status"], 0) + 1

    pending = await _sb(client, "GET",
        f"/agent_queue?business_id=eq.{biz_id}&status=eq.draft"
        f"&select=id,agent,action_type,subject,priority&order=priority.asc&limit=5"
    ) or []

    # Sessions
    sessions_completed = await _sb(client, "GET",
        f"/sessions?business_id=eq.{biz_id}&status=eq.completed"
        f"&scheduled_for=gte.{window_start}&scheduled_for=lte.{window_end}"
        f"&select=id,title,scheduled_for&limit=50"
    ) or []
    sessions_upcoming = await _sb(client, "GET",
        f"/sessions?business_id=eq.{biz_id}&status=eq.scheduled"
        f"&scheduled_for=gte.{window_end}&scheduled_for=lte.{upcoming_end}"
        f"&select=id,title,scheduled_for&limit=50"
    ) or []

    return {
        "window_start": window_start, "window_end": window_end,
        "new_contacts": new_contacts, "new_contact_count": len(new_contacts),
        "at_risk": at_risk, "thriving": thriving,
        "event_counts": event_counts, "total_events": len(events),
        "payment_event_count": len(payment_events), "payment_sum": payment_sum,
        "drafts_by_agent": drafts_by_agent,
        "pending_items": pending,
        "sessions_completed_count": len(sessions_completed),
        "sessions_upcoming_count": len(sessions_upcoming),
        "sessions_upcoming": sessions_upcoming[:5],
    }


def _format_briefing_data_for_ai(stats: Dict) -> str:
    new_names = ", ".join(c["name"] for c in stats["new_contacts"][:5]) or "none"
    at_risk_names = ", ".join(f"{c['name']} ({c['health_score']})" for c in stats["at_risk"][:5]) or "none"
    thriving_names = ", ".join(f"{c['name']} ({c['health_score']})" for c in stats["thriving"][:5]) or "none"

    drafts_lines = []
    for agent, buckets in stats["drafts_by_agent"].items():
        total = sum(buckets.values())
        drafts_lines.append(f"- {agent}: {total} total ({buckets.get('approved',0)} approved, {buckets.get('draft',0)} pending, {buckets.get('dismissed',0)} dismissed)")

    pending_lines = [f"- [{p.get('priority','?')}] {p['agent']}/{p['action_type']}: {p.get('subject') or '(no subject)'}"
                     for p in stats["pending_items"][:5]]

    events_lines = [f"- {t}: {n}" for t, n in sorted(stats["event_counts"].items(), key=lambda kv: -kv[1])]

    return f"""DATA WINDOW: last 7 days (ending {stats['window_end'][:10]})

NEW CONTACTS: {stats['new_contact_count']}
  {new_names}

AT-RISK CONTACTS (health < 40): {len(stats['at_risk'])}
  {at_risk_names}

THRIVING CONTACTS (health > 70): {len(stats['thriving'])}
  {thriving_names}

SESSIONS COMPLETED THIS WEEK: {stats['sessions_completed_count']}
SESSIONS UPCOMING (next 7 days): {stats['sessions_upcoming_count']}

PAYMENT ACTIVITY: {stats['payment_event_count']} events, ${stats['payment_sum']:.2f} total

EVENT BREAKDOWN:
{chr(10).join(events_lines) or '  (no events)'}

AGENT DRAFTS THIS WEEK:
{chr(10).join(drafts_lines) or '  (no draft activity)'}

TOP PENDING ITEMS NEEDING REVIEW:
{chr(10).join(pending_lines) or '  (queue empty)'}
"""


router = APIRouter(tags=["growth_engine"])


# ═══════════════════════════════════════════════════════════════════════
# BRIEFING ACTION GENERATION
# ═══════════════════════════════════════════════════════════════════════
#
# After the AI writes the briefing, this phase turns the data-driven
# problems into actual drafts queued for approval. The practitioner
# reads the letter, then finds the work already waiting for them.

def _money_tone_for(biz_type: str) -> str:
    if biz_type == "church":
        return "Be pastoral, never transactional about money. Frame it as stewardship and partnership."
    if biz_type == "nonprofit":
        return "Be appreciative and mission-focused."
    return "Warm but clear about the business relationship. Professional, not stiff."


def _days_since(iso_str: Optional[str]) -> Optional[int]:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except (ValueError, TypeError):
        return None


async def _existing_draft(client: httpx.AsyncClient, biz_id: str, contact_id: str,
                          agent: str, action_type: str, cutoff_iso: str) -> Optional[Dict]:
    """Return the most recent matching draft/approved row within the window, or None."""
    rows = await _sb(client, "GET",
        f"/agent_queue?business_id=eq.{biz_id}&contact_id=eq.{contact_id}"
        f"&agent=eq.{agent}&action_type=eq.{action_type}"
        f"&status=in.(draft,approved)&created_at=gte.{cutoff_iso}"
        f"&order=created_at.desc&limit=1&select=id,created_at"
    )
    return rows[0] if rows else None


async def _draft_nurture_check_in(client: httpx.AsyncClient, biz: Dict, contact: Dict,
                                  kind: str) -> Optional[Dict]:
    """kind = 'at-risk' or 'inactive'. Returns {subject, body, reasoning} or None."""
    biz_name = biz.get("name", "")
    biz_type = biz.get("type", "general")
    voice = biz.get("voice_profile") or {}
    practitioner = (biz.get("settings") or {}).get("practitioner_name", "the team")
    tone = voice.get("tone", "warm and professional")
    money_tone = _money_tone_for(biz_type)

    name = contact.get("name", "there")
    role = contact.get("role") or ""
    health = contact.get("health_score") or 0
    days = _days_since(contact.get("last_interaction"))
    days_str = f"{days} days ago" if days is not None else "quite some time ago"

    system_prompt = f"""You are the Nurture Agent for {biz_name}. Draft a short re-engagement check-in from {practitioner} to {name}.

{money_tone}

Voice: "{tone}". Keep it under 4 sentences. Don't be aggressive or guilt-inducing. Sign off as {practitioner}."""

    if kind == "at-risk":
        user_msg = (f"Contact: {name}{f' ({role})' if role else ''}\n"
                    f"Health score is {health} (at-risk). Last interaction was {days_str}.\n\n"
                    f"Draft a gentle, low-pressure check-in to re-open the conversation.")
    else:
        user_msg = (f"Contact: {name}{f' ({role})' if role else ''}\n"
                    f"Last interaction was {days_str}. Nothing urgent, but worth staying connected.\n\n"
                    f"Draft a brief, warm check-in.")

    body = await _call_claude(client, system_prompt, user_msg, max_tokens=400)
    if not body:
        return None

    subject = (f"Following up — {name}" if kind == "at-risk"
               else f"Thinking of you, {name}")
    reasoning = (f"{kind} nurture: health={health}, last_interaction={days_str}. "
                 f"Drafted by Growth Engine during weekly briefing.")
    return {"subject": subject, "body": body, "reasoning": reasoning}


async def _draft_session_followup(client: httpx.AsyncClient, biz: Dict, contact: Dict,
                                  session: Dict) -> Optional[Dict]:
    biz_name = biz.get("name", "")
    biz_type = biz.get("type", "general")
    voice = biz.get("voice_profile") or {}
    practitioner = (biz.get("settings") or {}).get("practitioner_name", "the team")
    tone = voice.get("tone", "warm and professional")
    money_tone = _money_tone_for(biz_type)

    name = contact.get("name", "there")
    session_title = session.get("title") or "our recent session"
    session_notes = (session.get("notes") or "")[:400]

    system_prompt = f"""You are the Session Agent for {biz_name}. Draft a follow-up message from {practitioner} to {name} after the session they just completed.

{money_tone}

Voice: "{tone}". Keep it under 5 sentences. Reference the session concretely. Include one specific next step or question. Sign off as {practitioner}."""

    user_msg = (f"Contact: {name}\n"
                f"Session: {session_title}\n"
                f"Session notes: {session_notes or '(none recorded)'}\n\n"
                f"Draft a follow-up message.")

    body = await _call_claude(client, system_prompt, user_msg, max_tokens=400)
    if not body:
        return None

    return {
        "subject": f"Following up on {session_title}",
        "body": body,
        "reasoning": f"Session follow-up generated by Growth Engine during weekly briefing. Session: {session_title}.",
    }


async def _generate_briefing_actions(client: httpx.AsyncClient, biz: Dict) -> Dict:
    """Generate drafts for actionable items. Returns action records + counts."""
    biz_id = biz["id"]
    now = datetime.now(timezone.utc)
    dedup_cutoff = (now - timedelta(days=ACTION_DEDUP_DAYS)).isoformat()

    actions: List[Dict] = []
    total_created = 0
    total_skipped = 0

    def _cap_reached() -> bool:
        return (total_created + total_skipped) >= ACTION_TOTAL_CAP

    # ── 1. At-risk contacts (health < 40) ─────────────────────────────
    at_risk = await _sb(client, "GET",
        f"/contacts?business_id=eq.{biz_id}&health_score=lt.40"
        f"&status=in.(active,lead,vip)&order=health_score.asc&limit={ACTION_CAP_AT_RISK}"
        f"&select=id,name,role,health_score,last_interaction"
    ) or []

    for c in at_risk:
        if _cap_reached(): break
        existing = await _existing_draft(client, biz_id, c["id"], "nurture", "check_in", dedup_cutoff)
        if existing:
            actions.append({
                "kind": "already_queued", "agent": "nurture", "action_type": "check_in",
                "contact_id": c["id"], "contact_name": c["name"],
                "queue_id": existing["id"], "existing_created_at": existing["created_at"],
                "reason": f"health {c.get('health_score')}",
            })
            total_skipped += 1
            continue

        draft = await _draft_nurture_check_in(client, biz, c, kind="at-risk")
        if not draft:
            logger.warning(f"Draft failed for at-risk contact {c.get('name')}")
            continue

        priority = "high" if (c.get("health_score") or 0) < 20 else "medium"
        inserted = await _sb(client, "POST", "/agent_queue", {
            "business_id": biz_id, "contact_id": c["id"],
            "agent": "nurture", "action_type": "check_in",
            "subject": draft["subject"], "body": draft["body"],
            "channel": "email", "status": "draft",
            "priority": priority,
            "ai_reasoning": draft["reasoning"], "ai_model": BRIEFING_MODEL,
        })
        if inserted and isinstance(inserted, list) and inserted:
            actions.append({
                "kind": "created", "agent": "nurture", "action_type": "check_in",
                "contact_id": c["id"], "contact_name": c["name"],
                "queue_id": inserted[0]["id"],
                "reason": f"health {c.get('health_score')}",
            })
            total_created += 1

    # ── 2. Inactive contacts (health >= 40, no contact in 14+ days) ───
    inactive_cutoff = (now - timedelta(days=INACTIVE_THRESHOLD_DAYS)).isoformat()
    inactive = await _sb(client, "GET",
        f"/contacts?business_id=eq.{biz_id}&health_score=gte.40"
        f"&status=in.(active,lead,vip)"
        f"&last_interaction=lt.{inactive_cutoff}"
        f"&order=last_interaction.asc&limit={ACTION_CAP_INACTIVE}"
        f"&select=id,name,role,health_score,last_interaction"
    ) or []

    for c in inactive:
        if _cap_reached(): break
        existing = await _existing_draft(client, biz_id, c["id"], "nurture", "check_in", dedup_cutoff)
        if existing:
            actions.append({
                "kind": "already_queued", "agent": "nurture", "action_type": "check_in",
                "contact_id": c["id"], "contact_name": c["name"],
                "queue_id": existing["id"], "existing_created_at": existing["created_at"],
                "reason": f"{_days_since(c.get('last_interaction'))}d inactive",
            })
            total_skipped += 1
            continue

        draft = await _draft_nurture_check_in(client, biz, c, kind="inactive")
        if not draft:
            logger.warning(f"Draft failed for inactive contact {c.get('name')}")
            continue

        inserted = await _sb(client, "POST", "/agent_queue", {
            "business_id": biz_id, "contact_id": c["id"],
            "agent": "nurture", "action_type": "check_in",
            "subject": draft["subject"], "body": draft["body"],
            "channel": "email", "status": "draft", "priority": "medium",
            "ai_reasoning": draft["reasoning"], "ai_model": BRIEFING_MODEL,
        })
        if inserted and isinstance(inserted, list) and inserted:
            actions.append({
                "kind": "created", "agent": "nurture", "action_type": "check_in",
                "contact_id": c["id"], "contact_name": c["name"],
                "queue_id": inserted[0]["id"],
                "reason": f"{_days_since(c.get('last_interaction'))}d inactive",
            })
            total_created += 1

    # ── 3. Completed sessions needing follow-ups ──────────────────────
    session_cutoff = (now - timedelta(days=SESSION_LOOKBACK_DAYS)).isoformat()
    sessions = await _sb(client, "GET",
        f"/sessions?business_id=eq.{biz_id}&status=eq.completed"
        f"&scheduled_for=gte.{session_cutoff}"
        f"&order=scheduled_for.desc&limit={ACTION_CAP_SESSION_FOLLOWUP}"
        f"&select=id,title,scheduled_for,contact_id,notes"
    ) or []

    for s in sessions:
        if _cap_reached(): break
        cid = s.get("contact_id")
        if not cid:
            continue

        existing = await _existing_draft(client, biz_id, cid, "session", "follow_up", dedup_cutoff)
        if existing:
            # Need the contact name for display
            contact_rows = await _sb(client, "GET",
                f"/contacts?id=eq.{cid}&select=id,name&limit=1") or []
            name = contact_rows[0]["name"] if contact_rows else "a contact"
            actions.append({
                "kind": "already_queued", "agent": "session", "action_type": "follow_up",
                "contact_id": cid, "contact_name": name,
                "queue_id": existing["id"], "existing_created_at": existing["created_at"],
                "reason": s.get("title") or "session",
            })
            total_skipped += 1
            continue

        contact_rows = await _sb(client, "GET",
            f"/contacts?id=eq.{cid}&select=id,name,role&limit=1") or []
        if not contact_rows:
            continue
        contact = contact_rows[0]

        draft = await _draft_session_followup(client, biz, contact, s)
        if not draft:
            logger.warning(f"Session follow-up draft failed for {contact.get('name')}")
            continue

        inserted = await _sb(client, "POST", "/agent_queue", {
            "business_id": biz_id, "contact_id": cid,
            "agent": "session", "action_type": "follow_up",
            "subject": draft["subject"], "body": draft["body"],
            "channel": "email", "status": "draft", "priority": "medium",
            "ai_reasoning": draft["reasoning"], "ai_model": BRIEFING_MODEL,
        })
        if inserted and isinstance(inserted, list) and inserted:
            actions.append({
                "kind": "created", "agent": "session", "action_type": "follow_up",
                "contact_id": cid, "contact_name": contact["name"],
                "queue_id": inserted[0]["id"],
                "reason": s.get("title") or "completed session",
            })
            total_created += 1

    # ── 4. Pending proposals — count only ─────────────────────────────
    pending = await _sb(client, "GET",
        f"/agent_queue?business_id=eq.{biz_id}&agent=eq.contract"
        f"&action_type=eq.proposal&status=eq.draft&select=id&limit=50"
    ) or []

    return {
        "actions": actions,
        "total_created": total_created,
        "total_skipped": total_skipped,
        "pending_proposals_count": len(pending),
    }


def _format_actions_section(actions: List[Dict], pending_proposals_count: int) -> str:
    """Programmatically build the 'Actions I've Queued For You' markdown section.
    Returns '' when there's nothing to show."""
    if not actions and pending_proposals_count == 0:
        return ""

    lines = ["## Actions I've Queued For You"]
    for a in actions:
        name = a.get("contact_name") or "a contact"
        if a["kind"] == "created":
            if a["agent"] == "nurture":
                detail = f" ({a['reason']})" if a.get("reason") else ""
                lines.append(f"- Drafted a check-in email for {name}{detail} → waiting in your Queue")
            elif a["agent"] == "session":
                lines.append(f"- Drafted a follow-up for your session with {name} → waiting in your Queue")
            else:
                lines.append(f"- Drafted a {a.get('action_type', 'message')} for {name} → waiting in your Queue")
        elif a["kind"] == "already_queued":
            existing_days = _days_since(a.get("existing_created_at"))
            when = (f"{existing_days}d ago" if existing_days and existing_days > 0
                    else "earlier today")
            verb = "follow-up" if a.get("action_type") == "follow_up" else "check-in"
            lines.append(f"- A {verb} for {name} is already in your Queue from {when}")

    if pending_proposals_count > 0:
        s = "s" if pending_proposals_count != 1 else ""
        verb = "are" if pending_proposals_count != 1 else "is"
        lines.append(f"- {pending_proposals_count} proposal{s} {verb} already in your Queue from earlier this week")

    lines.append("")
    lines.append("Open your Queue to review and approve these actions.")
    return "\n".join(lines)


@router.post("/agents/growth/briefing")
async def growth_briefing(req: GrowthRequest):
    async with httpx.AsyncClient() as client:
        businesses = await _sb(client, "GET", f"/businesses?id=eq.{req.business_id}&select=*&limit=1")
        if not businesses:
            raise HTTPException(404, "Business not found")
        biz = businesses[0]
        biz_name = biz.get("name", "your business")
        voice = biz.get("voice_profile") or {}
        practitioner = (biz.get("settings") or {}).get("practitioner_name", "the practitioner")
        voice_tone = voice.get("tone", "warm and direct")

        stats = await _gather_briefing_data(client, req.business_id)

        window_end_dt = datetime.fromisoformat(stats["window_end"].replace("Z", "+00:00"))
        window_start_dt = datetime.fromisoformat(stats["window_start"].replace("Z", "+00:00"))
        date_range = (
            f"{window_start_dt.strftime('%B')} {window_start_dt.day} – "
            f"{window_end_dt.strftime('%B')} {window_end_dt.day}, {window_end_dt.year}"
        )

        system_prompt = f"""You are the Growth Intelligence Engine for {biz_name}. Write a weekly briefing TO {practitioner} in their voice.

Voice: {voice_tone}. Voice profile details: {json.dumps(voice)[:600]}

Structure the briefing EXACTLY as five markdown sections with these exact headers:

## The Headline
One sentence capturing the most important thing that happened this week.

## Wins This Week
2-3 specific positive things (new contacts, sessions completed, proposals approved, payments received). Use bullet points.

## Needs Your Attention
2-3 things {practitioner} should focus on (disengaged contacts, pending approvals, overdue follow-ups). Use bullet points. Be specific — name names when possible.

## By The Numbers
Key metrics in a quick scannable format. Use bullet points with bold labels like **New contacts:** N.

## This Week's Focus
One specific recommendation for what to prioritize this week, grounded in the data.

Rules:
- Keep total length under 400 words.
- Warm, direct, actionable. No fluff. No corporate hedging.
- Sound like a trusted advisor over morning coffee, not a software report.
- Do NOT invent data. Only reference facts in the stats below.
- Address {practitioner} by name at least once."""

        user_msg = _format_briefing_data_for_ai(stats)
        body = await _call_claude(client, system_prompt, user_msg, model=BRIEFING_MODEL, max_tokens=1400)

        body_fallback = not body
        if body_fallback:
            body = ("## The Headline\n"
                    "Briefing text unavailable — but here are the actions I've queued based on your data.\n\n"
                    "## By The Numbers\n"
                    f"- **New contacts:** {stats['new_contact_count']}\n"
                    f"- **At-risk contacts:** {len(stats['at_risk'])}\n"
                    f"- **Sessions completed:** {stats['sessions_completed_count']}\n"
                    f"- **Pending drafts:** {len(stats['pending_items'])}\n")

        # ── Action generation phase ───────────────────────────────────
        try:
            action_result = await _generate_briefing_actions(client, biz)
        except Exception as e:
            logger.exception(f"Action generation failed: {e}")
            action_result = {"actions": [], "total_created": 0, "total_skipped": 0, "pending_proposals_count": 0}

        actions_section = _format_actions_section(
            action_result["actions"],
            action_result["pending_proposals_count"],
        )
        if actions_section:
            body = body.rstrip() + "\n\n" + actions_section + "\n"

        title = f"Weekly Briefing — {date_range}"
        insight = await _sb(client, "POST", "/insights", {
            "business_id": req.business_id,
            "category": "growth",
            "insight_type": "observation",
            "title": title,
            "body": body,
            "priority": "medium",
            "evidence": {
                "kind": "weekly_briefing",
                "window_start": stats["window_start"],
                "window_end": stats["window_end"],
                "body_fallback": body_fallback,
                "stats": {
                    "new_contacts": stats["new_contact_count"],
                    "at_risk": len(stats["at_risk"]),
                    "thriving": len(stats["thriving"]),
                    "sessions_completed": stats["sessions_completed_count"],
                    "sessions_upcoming": stats["sessions_upcoming_count"],
                    "payment_sum": stats["payment_sum"],
                    "event_counts": stats["event_counts"],
                    "drafts_by_agent": stats["drafts_by_agent"],
                },
                "actions_generated": action_result["actions"],
                "total_actions_created": action_result["total_created"],
                "total_actions_skipped": action_result["total_skipped"],
                "pending_proposals_count": action_result["pending_proposals_count"],
            },
        })

        stored = insight[0] if isinstance(insight, list) and insight else None
        return {
            "insight_id": stored["id"] if stored else None,
            "title": title,
            "body": body,
            "date_range": date_range,
            "stats": stats,
            "actions_generated": action_result["total_created"],
            "actions_skipped": action_result["total_skipped"],
            "pending_proposals": action_result["pending_proposals_count"],
            "actions": action_result["actions"],
        }


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINT: HEALTH REPORT (structured, no AI)
# ═══════════════════════════════════════════════════════════════════════

def _bucket_of(score: int) -> str:
    if score <= 20: return "0-20"
    if score <= 40: return "21-40"
    if score <= 60: return "41-60"
    if score <= 80: return "61-80"
    return "81-100"


@router.post("/agents/growth/health-report")
async def growth_health_report(req: GrowthRequest):
    async with httpx.AsyncClient() as client:
        contacts = await _sb(client, "GET",
            f"/contacts?business_id=eq.{req.business_id}"
            f"&select=id,name,role,status,health_score,last_interaction&limit=1000"
        ) or []

        by_status = {"active": 0, "lead": 0, "vip": 0, "inactive": 0, "churned": 0}
        distribution = {"0-20": 0, "21-40": 0, "41-60": 0, "61-80": 0, "81-100": 0}
        scores: List[int] = []
        at_risk: List[Dict] = []
        thriving: List[Dict] = []
        now = datetime.now(timezone.utc)

        for c in contacts:
            score = int(c.get("health_score") or 0)
            status = c.get("status") or "active"
            if status in by_status:
                by_status[status] += 1
            distribution[_bucket_of(score)] += 1
            scores.append(score)

            days_since = None
            if c.get("last_interaction"):
                try:
                    dt = datetime.fromisoformat(c["last_interaction"].replace("Z", "+00:00"))
                    days_since = (now - dt).days
                except (ValueError, TypeError):
                    days_since = None

            if score < 40:
                at_risk.append({
                    "contact_id": c["id"], "name": c.get("name"),
                    "health_score": score, "status": status,
                    "days_since_last_interaction": days_since,
                })
            elif score > 80:
                thriving.append({
                    "contact_id": c["id"], "name": c.get("name"),
                    "health_score": score, "status": status,
                })

        at_risk.sort(key=lambda x: x["health_score"])
        thriving.sort(key=lambda x: -x["health_score"])

        avg = round(sum(scores) / len(scores), 1) if scores else 0.0

        return {
            "total_contacts": len(contacts),
            "by_status": by_status,
            "average_health": avg,
            "distribution": distribution,
            "at_risk": at_risk[:15],
            "thriving": thriving[:10],
            "contacts": contacts,
        }


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINT: INSIGHTS (AI pattern/anomaly/opportunity detection)
# ═══════════════════════════════════════════════════════════════════════

async def _gather_insights_data(client: httpx.AsyncClient, biz_id: str) -> Dict:
    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(days=INSIGHTS_WINDOW_DAYS)).isoformat()
    prior_start = (now - timedelta(days=INSIGHTS_WINDOW_DAYS * 2)).isoformat()
    prior_end = window_start

    contacts = await _sb(client, "GET",
        f"/contacts?business_id=eq.{biz_id}&select=id,name,status,health_score,lead_score,created_at,last_interaction&limit=500"
    ) or []

    events_recent = await _sb(client, "GET",
        f"/events?business_id=eq.{biz_id}&created_at=gte.{window_start}"
        f"&select=event_type,data,contact_id,created_at&limit=500"
    ) or []
    events_prior = await _sb(client, "GET",
        f"/events?business_id=eq.{biz_id}&created_at=gte.{prior_start}&created_at=lt.{prior_end}"
        f"&select=event_type,data,contact_id,created_at&limit=500"
    ) or []

    queue_recent = await _sb(client, "GET",
        f"/agent_queue?business_id=eq.{biz_id}&created_at=gte.{window_start}"
        f"&select=agent,status,priority&limit=500"
    ) or []

    def _counts(events):
        out: Dict[str, int] = {}
        for e in events:
            out[e["event_type"]] = out.get(e["event_type"], 0) + 1
        return out

    # Stale leads — status=lead and created >30 days ago, no interaction in 14 days
    stale_leads = []
    for c in contacts:
        if c.get("status") != "lead": continue
        try:
            created = datetime.fromisoformat(c["created_at"].replace("Z", "+00:00"))
            if (now - created).days < 30: continue
        except (ValueError, TypeError, KeyError):
            continue
        last = c.get("last_interaction")
        days_since = None
        if last:
            try:
                days_since = (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).days
            except (ValueError, TypeError):
                days_since = None
        if days_since is None or days_since >= 14:
            stale_leads.append({"id": c["id"], "name": c["name"], "days_since_last": days_since})

    return {
        "window_start": window_start, "window_end": now.isoformat(),
        "total_contacts": len(contacts),
        "events_recent_counts": _counts(events_recent),
        "events_prior_counts": _counts(events_prior),
        "events_recent_total": len(events_recent),
        "events_prior_total": len(events_prior),
        "queue_counts_by_agent": {
            agent: sum(1 for q in queue_recent if q["agent"] == agent)
            for agent in {q["agent"] for q in queue_recent}
        },
        "stale_leads": stale_leads[:10],
        "payment_sum_recent": _sum_amount([e for e in events_recent if e["event_type"] in PAYMENT_EVENT_TYPES]),
        "payment_sum_prior": _sum_amount([e for e in events_prior if e["event_type"] in PAYMENT_EVENT_TYPES]),
    }


def _format_insights_data_for_ai(stats: Dict) -> str:
    recent_lines = [f"- {t}: {n}" for t, n in sorted(stats["events_recent_counts"].items(), key=lambda kv: -kv[1])]
    prior_lines = [f"- {t}: {n}" for t, n in sorted(stats["events_prior_counts"].items(), key=lambda kv: -kv[1])]
    stale = "\n".join(
        f"- {c['name']} ({c['days_since_last']}d since last interaction)" if c["days_since_last"] is not None
        else f"- {c['name']} (no interactions recorded)"
        for c in stats["stale_leads"]
    ) or "  (none)"

    return f"""DATA WINDOW: last 30 days vs prior 30 days.

CONTACTS TOTAL: {stats['total_contacts']}

EVENT COUNTS (last 30d, total {stats['events_recent_total']}):
{chr(10).join(recent_lines) or '  (none)'}

EVENT COUNTS (prior 30d, total {stats['events_prior_total']}):
{chr(10).join(prior_lines) or '  (none)'}

PAYMENT VOLUME: recent ${stats['payment_sum_recent']:.2f} vs prior ${stats['payment_sum_prior']:.2f}

QUEUE ACTIVITY BY AGENT (last 30d):
{chr(10).join(f'- {a}: {n}' for a, n in stats['queue_counts_by_agent'].items()) or '  (none)'}

STALE LEADS (status=lead, 30+ days old, 14+ days no contact):
{stale}
"""


@router.post("/agents/growth/insights")
async def growth_insights(req: GrowthRequest):
    async with httpx.AsyncClient() as client:
        businesses = await _sb(client, "GET", f"/businesses?id=eq.{req.business_id}&select=*&limit=1")
        if not businesses:
            raise HTTPException(404, "Business not found")
        biz = businesses[0]
        biz_name = biz.get("name", "your business")

        stats = await _gather_insights_data(client, req.business_id)

        system_prompt = f"""You are the Growth Intelligence Engine for {biz_name}. Analyze 30 days of business data and return 3-5 actionable insights.

Return a JSON array. No prose, no markdown, just valid JSON. Each element must be an object with these exact keys:

{{
  "category": one of: revenue, engagement, churn, opportunity, operations, content, growth, other
  "insight_type": one of: observation, suggestion, alert, milestone
  "title": short punchy title (under 80 chars)
  "body": 1-3 sentences explaining the insight — reference specific numbers from the data
  "priority": one of: urgent, high, medium, low
  "evidence": object with supporting metrics you drew from (keep small)
  "suggested_action": OPTIONAL object — include when the insight has a clear follow-up. Shape: {{
      "agent": one of: nurture, session, contract, payment, intake
      "action_type": one of: email, sms, follow_up, proposal, invoice, check_in, onboarding, alert, other
      "subject": short subject line
      "body_draft": 1-2 sentence draft the practitioner can approve
      "ai_reasoning": why this action makes sense
  }}
}}

Categories of insights to look for:
- Pattern detection (correlations, cohort behaviors)
- Anomaly detection (sudden drops or spikes vs prior period)
- Opportunity identification (stale leads, upsell moments)
- Performance insights (what's working, what isn't)

Be specific and actionable. Do NOT invent numbers. Only reference data present in the stats below."""

        user_msg = _format_insights_data_for_ai(stats)
        raw = await _call_claude(client, system_prompt, user_msg, model=INSIGHTS_MODEL, max_tokens=2000)
        parsed = _extract_json_block(raw)

        if not isinstance(parsed, list):
            logger.warning(f"Insights AI returned non-list response: {raw[:300]}")
            return {"generated": 0, "insights": [], "error": "AI returned invalid format"}

        generated = []
        for item in parsed[:5]:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            row = {
                "business_id": req.business_id,
                "category": _normalize_category(item.get("category", "")),
                "insight_type": _normalize_type(item.get("insight_type", "")),
                "title": str(item["title"])[:200],
                "body": item.get("body") or "",
                "priority": _normalize_priority(item.get("priority", "")),
                "evidence": item.get("evidence") or {},
                "suggested_action": None,
            }
            sa = item.get("suggested_action")
            if isinstance(sa, dict) and sa.get("subject") and sa.get("body_draft"):
                row["suggested_action"] = {
                    "agent": (sa.get("agent") or "nurture").lower(),
                    "action_type": _normalize_action_type(sa.get("action_type", "")),
                    "subject": str(sa.get("subject"))[:200],
                    "body_draft": str(sa.get("body_draft"))[:4000],
                    "ai_reasoning": str(sa.get("ai_reasoning") or "")[:1000],
                }
            inserted = await _sb(client, "POST", "/insights", row)
            if inserted and isinstance(inserted, list):
                generated.append(inserted[0])

        return {"generated": len(generated), "insights": generated}


# ═══════════════════════════════════════════════════════════════════════
# HEALTH
# ═══════════════════════════════════════════════════════════════════════

@router.get("/agents/growth/health")
async def growth_health():
    return {
        "status": "ok",
        "supabase_configured": bool(_supabase_url()),
        "anthropic_configured": bool(_anthropic_key()),
        "briefing_window_days": BRIEFING_WINDOW_DAYS,
        "insights_window_days": INSIGHTS_WINDOW_DAYS,
    }
