"""
chief_of_staff.py — Solutionist System Chief of Staff

A conversational endpoint the practitioner talks to directly. Unlike the
other agents (which draft silently), this one has full visibility into
the business and can take actions in-flight by emitting [ACTION:{...}]
tags in its response. The server parses, validates, and executes those
actions before returning.

═══════════════════════════════════════════════════════════════════════
DEPLOYMENT
═══════════════════════════════════════════════════════════════════════

1. Drop into Railway alongside the other agent files.

2. In main.py:
       from chief_of_staff import router as chief_router
       app.include_router(chief_router)

3. Env vars:
       SUPABASE_URL, SUPABASE_ANON, ANTHROPIC_API_KEY — already set
       PORT — Railway sets automatically; used for loopback run_agent calls

Action format (JSON inside brackets, not pipe-delimited):
    [ACTION:{"type":"draft_nurture","contact_id":"uuid","reason":"..."}]
    [ACTION:{"type":"run_agent","agent":"nurture"}]
    [ACTION:{"type":"create_session","contact_id":"uuid","title":"...","scheduled_for":"2026-04-20T14:00:00Z"}]
"""

import asyncio
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
CHIEF_MODEL = "claude-sonnet-4-5-20250929"
DRAFT_MODEL = "claude-sonnet-4-5-20250929"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)

# Loopback base for run_agent actions. Prefer localhost + PORT (no TLS, no DNS);
# fall back to the public URL if PORT isn't set.
SELF_BASE = f"http://localhost:{os.environ.get('PORT', '8000')}"
FALLBACK_BASE = os.environ.get(
    "RAILWAY_PUBLIC_URL", "https://kmj-intake-server-production.up.railway.app"
)

MAX_HISTORY = 30
OPENING_SENTINEL = "[SYSTEM:opening_greeting]"
MAX_ACTIONS_PER_TURN = 8  # safety cap in case the AI goes wild

VALID_CONTACT_STATUSES = {"active", "lead", "vip", "inactive", "churned"}

# agent_queue.action_type CHECK constraint
VALID_ACTION_TYPES = {
    "email", "sms", "follow_up", "proposal", "invoice",
    "check_in", "onboarding", "alert", "other",
}

logger = logging.getLogger("chief_of_staff")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] chief: %(message)s"))
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


async def _call_claude(client: httpx.AsyncClient, system: str, messages: List[Dict],
                       max_tokens: int = 1600) -> str:
    key = _anthropic_key()
    if not key:
        return ""
    try:
        resp = await client.post(ANTHROPIC_API_URL, headers={
            "x-api-key": key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json",
        }, json={
            "model": CHIEF_MODEL, "max_tokens": max_tokens, "system": system,
            "messages": messages,
        }, timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as e:
        logger.warning(f"Claude request failed: {e}")
        return ""
    if resp.status_code >= 400:
        logger.warning(f"Claude error: {resp.status_code} {resp.text[:300]}")
        return ""
    data = resp.json()
    return "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict)).strip()


async def _draft_short(client: httpx.AsyncClient, biz: Dict, system: str, user_msg: str) -> str:
    """Use for embedded draft generation inside action handlers (draft_nurture/draft_email)."""
    key = _anthropic_key()
    if not key:
        return ""
    try:
        resp = await client.post(ANTHROPIC_API_URL, headers={
            "x-api-key": key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json",
        }, json={
            "model": DRAFT_MODEL, "max_tokens": 500, "system": system,
            "messages": [{"role": "user", "content": user_msg}],
        }, timeout=HTTP_TIMEOUT)
    except httpx.HTTPError:
        return ""
    if resp.status_code >= 400:
        return ""
    data = resp.json()
    return "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict)).strip()


def _days_since(iso_str: Optional[str]) -> Optional[int]:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except (ValueError, TypeError):
        return None


# ═══════════════════════════════════════════════════════════════════════
# CONTEXT GATHERING
# ═══════════════════════════════════════════════════════════════════════

async def _gather_context(client: httpx.AsyncClient, biz_id: str) -> Dict[str, Any]:
    """Pull a fresh snapshot of the business state in parallel."""
    now = datetime.now(timezone.utc)
    in_7d = (now + timedelta(days=7)).isoformat()

    tasks = [
        _sb(client, "GET", f"/businesses?id=eq.{biz_id}&select=*&limit=1"),
        _sb(client, "GET",
            f"/contacts?business_id=eq.{biz_id}"
            f"&select=id,name,status,health_score,lead_score,role,last_interaction&limit=500"),
        _sb(client, "GET",
            f"/agent_queue?business_id=eq.{biz_id}&status=eq.draft"
            f"&select=id,agent,action_type,subject,priority,contact_id,created_at"
            f"&order=priority.asc,created_at.desc&limit=10"),
        _sb(client, "GET",
            f"/events?business_id=eq.{biz_id}&order=created_at.desc&limit=20"
            f"&select=event_type,data,created_at,contacts(name)"),
        _sb(client, "GET",
            f"/sessions?business_id=eq.{biz_id}&status=eq.scheduled"
            f"&scheduled_for=lte.{in_7d}&order=scheduled_for.asc&limit=10"
            f"&select=id,title,scheduled_for,contact_id,contacts(name)"),
        _sb(client, "GET",
            f"/insights?business_id=eq.{biz_id}&status=eq.unread"
            f"&order=priority.asc,created_at.desc&limit=5"
            f"&select=id,category,title,priority"),
        _sb(client, "GET",
            f"/custom_modules?business_id=eq.{biz_id}&is_active=eq.true"
            f"&select=id,name,description&limit=50"),
    ]
    biz_rows, contacts, queue, events, sessions, insights, modules = await asyncio.gather(*tasks)

    if not biz_rows:
        return {}
    biz = biz_rows[0]

    # Module entry counts — one query per module (parallel)
    module_entries_tasks = [
        _sb(client, "GET",
            f"/module_entries?module_id=eq.{m['id']}&status=eq.active&select=id&limit=500")
        for m in (modules or [])
    ]
    module_entry_rows = await asyncio.gather(*module_entries_tasks) if module_entries_tasks else []
    module_counts = {
        (modules or [])[i]["id"]: len(rows or [])
        for i, rows in enumerate(module_entry_rows)
    }

    # Contact summary
    contacts = contacts or []
    by_status = {"active": 0, "lead": 0, "vip": 0, "inactive": 0, "churned": 0}
    for c in contacts:
        s = c.get("status") or "active"
        if s in by_status:
            by_status[s] += 1
    scores = [c.get("health_score") or 0 for c in contacts]
    avg_health = round(sum(scores) / len(scores), 1) if scores else 0.0
    at_risk = [c for c in contacts if (c.get("health_score") or 0) < 40 and c.get("status") in ("active", "lead", "vip")]
    at_risk.sort(key=lambda c: c.get("health_score") or 0)

    return {
        "business": biz,
        "contacts_total": len(contacts),
        "contacts_by_status": by_status,
        "avg_health": avg_health,
        "at_risk": at_risk[:8],
        "queue": queue or [],
        "events": events or [],
        "sessions": sessions or [],
        "insights": insights or [],
        "modules": modules or [],
        "module_counts": module_counts,
        # Keep the full contact list (IDs + names) so the AI can reference real UUIDs
        "contacts_lookup": [
            {"id": c["id"], "name": c.get("name"), "status": c.get("status"), "health_score": c.get("health_score")}
            for c in contacts[:200]
        ],
    }


def _format_context_for_prompt(ctx: Dict[str, Any]) -> str:
    """Compact text block for the system prompt."""
    if not ctx:
        return "NO BUSINESS DATA AVAILABLE."

    biz = ctx["business"]
    bizname = biz.get("name", "the business")
    biztype = biz.get("type", "general")

    # Queue
    queue_lines = []
    for q in ctx["queue"][:10]:
        contact_name = ""
        if q.get("contact_id"):
            match = next((c for c in ctx["contacts_lookup"] if c["id"] == q["contact_id"]), None)
            contact_name = f" → {match['name']}" if match else ""
        queue_lines.append(
            f"  - [{q.get('priority', '?')}] {q.get('agent')}/{q.get('action_type')}: "
            f"{q.get('subject') or '(no subject)'}{contact_name} [id={q.get('id')}]"
        )

    # Events
    event_lines = []
    for ev in ctx["events"][:20]:
        contact = (ev.get("contacts") or {}).get("name", "") if ev.get("contacts") else ""
        tag = f" — {contact}" if contact else ""
        days = _days_since(ev.get("created_at"))
        event_lines.append(f"  - {days}d ago: {ev.get('event_type')}{tag}")

    # Sessions
    session_lines = []
    for s in ctx["sessions"][:10]:
        contact = (s.get("contacts") or {}).get("name", "") if s.get("contacts") else ""
        when = s.get("scheduled_for", "")[:16]
        session_lines.append(f"  - {when} — {s.get('title')} {('with ' + contact) if contact else ''} [id={s.get('id')}]")

    # Insights
    insight_lines = [
        f"  - [{i.get('priority')}] {i.get('category')}: {i.get('title')}"
        for i in ctx["insights"][:5]
    ]

    # Modules
    module_lines = []
    for m in ctx["modules"][:20]:
        count = ctx["module_counts"].get(m["id"], 0)
        desc = f" — {m.get('description')}" if m.get('description') else ""
        module_lines.append(f"  - {m.get('name')} ({count} entries){desc} [id={m.get('id')}]")

    # At-risk contacts
    at_risk_lines = [
        f"  - {c.get('name')} (health {c.get('health_score')}) [id={c.get('id')}]"
        for c in ctx["at_risk"]
    ]

    # Full contacts reference — ID + name lookup, compact
    contact_ref_lines = [
        f"  - {c['name']} [id={c['id']}] status={c['status']} health={c['health_score']}"
        for c in ctx["contacts_lookup"][:60]
    ]

    return f"""BUSINESS: {bizname} (type: {biztype})
  Practitioner: {(biz.get('settings') or {}).get('practitioner_name', 'the practitioner')}
  Voice profile: {json.dumps(biz.get('voice_profile') or {})[:500]}

CONTACTS: {ctx['contacts_total']} total
  by_status: {json.dumps(ctx['contacts_by_status'])}
  avg_health: {ctx['avg_health']}
  at_risk (health < 40):
{chr(10).join(at_risk_lines) if at_risk_lines else '  (none)'}

QUEUE ({len(ctx['queue'])} drafts pending):
{chr(10).join(queue_lines) if queue_lines else '  (empty)'}

UPCOMING SESSIONS (next 7 days):
{chr(10).join(session_lines) if session_lines else '  (none scheduled)'}

UNREAD INSIGHTS:
{chr(10).join(insight_lines) if insight_lines else '  (none)'}

CUSTOM MODULES:
{chr(10).join(module_lines) if module_lines else '  (none)'}

RECENT EVENTS:
{chr(10).join(event_lines) if event_lines else '  (none)'}

CONTACT LOOKUP (use these exact IDs when referencing contacts in actions):
{chr(10).join(contact_ref_lines) if contact_ref_lines else '  (no contacts)'}
"""


# ═══════════════════════════════════════════════════════════════════════
# ACTION TAG PARSING
# ═══════════════════════════════════════════════════════════════════════

# Non-greedy match, balanced-brace friendly enough for our JSON payloads.
# We use a manual depth scanner for nested braces — regex alone breaks on
# action payloads that contain nested objects.
ACTION_OPEN = "[ACTION:"


def _extract_actions_and_clean(text: str) -> (List[Dict[str, Any]], str):
    """Scan the AI's response for [ACTION:{...}] tags. Returns (actions, cleaned_text)."""
    actions: List[Dict[str, Any]] = []
    out_parts: List[str] = []
    i = 0
    n = len(text)

    while i < n:
        start = text.find(ACTION_OPEN, i)
        if start < 0:
            out_parts.append(text[i:])
            break
        out_parts.append(text[i:start])

        # Find matching closing bracket by tracking brace depth within the JSON
        json_start = start + len(ACTION_OPEN)
        # The JSON block should start with '{'
        if json_start >= n or text[json_start] != "{":
            # Not a well-formed action — emit literal and advance
            out_parts.append(text[start:json_start + 1])
            i = json_start + 1
            continue

        depth = 0
        j = json_start
        in_string = False
        escape = False
        while j < n:
            ch = text[j]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        break
            j += 1

        if depth != 0 or j >= n:
            # Unbalanced — keep literal and move on
            out_parts.append(text[start:json_start + 1])
            i = json_start + 1
            continue

        json_str = text[json_start:j + 1]
        # After the closing brace we expect a ']'
        k = j + 1
        if k < n and text[k] == "]":
            try:
                parsed = json.loads(json_str)
                if isinstance(parsed, dict) and parsed.get("type"):
                    actions.append(parsed)
                # Swallow the entire [ACTION:{...}] and any trailing space
                after = k + 1
                while after < n and text[after] in (" ", "\n", "\r", "\t"):
                    after += 1
                i = after
                continue
            except json.JSONDecodeError:
                pass

        # Parse failed — emit literal
        out_parts.append(text[start:k + 1 if k < n else n])
        i = k + 1 if k < n else n

    cleaned = "".join(out_parts).strip()
    return actions[:MAX_ACTIONS_PER_TURN], cleaned


# ═══════════════════════════════════════════════════════════════════════
# ACTION HANDLERS
# ═══════════════════════════════════════════════════════════════════════

async def _validate_contact(client, biz_id: str, contact_id: str) -> Optional[Dict]:
    if not contact_id:
        return None
    rows = await _sb(client, "GET",
        f"/contacts?id=eq.{contact_id}&business_id=eq.{biz_id}&limit=1&select=*")
    return rows[0] if rows else None


async def _validate_module(client, biz_id: str, module_id: str) -> Optional[Dict]:
    if not module_id:
        return None
    rows = await _sb(client, "GET",
        f"/custom_modules?id=eq.{module_id}&business_id=eq.{biz_id}&limit=1&select=*")
    return rows[0] if rows else None


def _fail(action_type: str, msg: str) -> Dict:
    logger.info(f"Action {action_type} failed: {msg}")
    return {"type": action_type, "result": f"Failed: {msg}", "label": action_type, "nav": None}


def _nav(tab: str, sub: Optional[str] = None, contact_id: Optional[str] = None) -> Dict:
    nav = {"tab": tab}
    if sub:
        nav["sub"] = sub
    if contact_id:
        nav["contactId"] = contact_id
    return nav


async def handle_draft_nurture(client, biz, action) -> Dict:
    contact_id = action.get("contact_id")
    contact = await _validate_contact(client, biz["id"], contact_id)
    if not contact:
        return _fail("draft_nurture", f"Contact {contact_id} not found")

    reason = action.get("reason", "regular check-in")
    voice = biz.get("voice_profile") or {}
    practitioner = (biz.get("settings") or {}).get("practitioner_name", "the team")
    tone = voice.get("tone", "warm and professional")

    system = (f"You are drafting a short, warm check-in from {practitioner} to {contact.get('name')}. "
              f"Voice: {tone}. Under 4 sentences. Sign off as {practitioner}.")
    user = f"Reason for the check-in: {reason}\n\nDraft the message body only (no subject)."
    body = await _draft_short(client, biz, system, user)
    if not body:
        body = f"Hi {contact.get('name')}, just thinking of you. Wanted to check in. — {practitioner}"

    inserted = await _sb(client, "POST", "/agent_queue", {
        "business_id": biz["id"], "contact_id": contact["id"],
        "agent": "nurture", "action_type": "check_in",
        "subject": f"Check-in for {contact.get('name')}",
        "body": body,
        "channel": "email" if contact.get("email") else "in_app",
        "status": "draft", "priority": "medium",
        "ai_reasoning": f"Chief of Staff requested: {reason}",
        "ai_model": DRAFT_MODEL,
    })
    if not inserted:
        return _fail("draft_nurture", "insert failed")

    return {
        "type": "draft_nurture",
        "result": "queued for approval",
        "label": f"Check-in for {contact.get('name')}",
        "nav": _nav("operate", "queue"),
    }


async def handle_draft_email(client, biz, action) -> Dict:
    contact_id = action.get("contact_id")
    contact = await _validate_contact(client, biz["id"], contact_id) if contact_id else None
    subject = action.get("subject") or "Message from your Chief of Staff"
    body_hint = action.get("body") or action.get("message")

    if body_hint and len(body_hint) > 20:
        body = body_hint
    else:
        voice = biz.get("voice_profile") or {}
        practitioner = (biz.get("settings") or {}).get("practitioner_name", "the team")
        tone = voice.get("tone", "warm and professional")
        name = contact.get("name") if contact else "there"
        system = (f"Draft a short email from {practitioner} to {name}. Voice: {tone}. "
                  f"Under 5 sentences. Sign off as {practitioner}.")
        user = f"Subject: {subject}\nContext: {action.get('reason') or body_hint or 'general outreach'}"
        body = await _draft_short(client, biz, system, user)
        if not body:
            body = f"Hi {name},\n\nReaching out from {biz.get('name')}. — {practitioner}"

    inserted = await _sb(client, "POST", "/agent_queue", {
        "business_id": biz["id"],
        "contact_id": contact["id"] if contact else None,
        "agent": "chief", "action_type": "email",
        "subject": subject, "body": body,
        "channel": "email" if (contact and contact.get("email")) else "in_app",
        "status": "draft", "priority": action.get("priority", "medium"),
        "ai_reasoning": f"Chief of Staff drafted: {action.get('reason', 'conversational request')}",
        "ai_model": DRAFT_MODEL,
    })
    if not inserted:
        return _fail("draft_email", "insert failed")

    label = f"Email: {subject}" + (f" → {contact.get('name')}" if contact else "")
    return {
        "type": "draft_email",
        "result": "queued for approval",
        "label": label,
        "nav": _nav("operate", "queue"),
    }


async def handle_create_session(client, biz, action) -> Dict:
    contact_id = action.get("contact_id")
    contact = await _validate_contact(client, biz["id"], contact_id) if contact_id else None
    if contact_id and not contact:
        return _fail("create_session", f"Contact {contact_id} not found")

    title = action.get("title") or "New session"
    scheduled_for = action.get("scheduled_for") or action.get("date")
    if not scheduled_for:
        return _fail("create_session", "scheduled_for is required")

    # Accept plain "2026-04-20" or "2026-04-20T14:00" or full ISO
    if len(scheduled_for) == 10:
        scheduled_for = f"{scheduled_for}T09:00:00Z"
    elif "T" in scheduled_for and not scheduled_for.endswith("Z") and "+" not in scheduled_for:
        scheduled_for = scheduled_for + ":00Z" if len(scheduled_for) == 16 else scheduled_for + "Z"

    session_type = action.get("session_type") or action.get("type_label") or "consultation"
    duration = action.get("duration_minutes") or 60

    inserted = await _sb(client, "POST", "/sessions", {
        "business_id": biz["id"],
        "contact_id": contact["id"] if contact else None,
        "title": title,
        "session_type": session_type,
        "status": "scheduled",
        "scheduled_for": scheduled_for,
        "duration_minutes": duration,
        "notes": action.get("notes"),
    })
    if not inserted:
        return _fail("create_session", "insert failed")

    label = f"Session: {title}" + (f" with {contact.get('name')}" if contact else "")
    try:
        when = datetime.fromisoformat(scheduled_for.replace("Z", "+00:00")).strftime("%b %d, %I:%M %p")
    except (ValueError, TypeError):
        when = scheduled_for
    return {
        "type": "create_session",
        "result": f"scheduled for {when}",
        "label": label,
        "nav": _nav("operate", "sessions"),
    }


async def handle_update_contact_status(client, biz, action) -> Dict:
    contact_id = action.get("contact_id")
    new_status = (action.get("new_status") or action.get("status") or "").lower().strip()
    contact = await _validate_contact(client, biz["id"], contact_id)
    if not contact:
        return _fail("update_contact_status", f"Contact {contact_id} not found")
    if new_status not in VALID_CONTACT_STATUSES:
        return _fail("update_contact_status", f"Invalid status '{new_status}'")

    prev = contact.get("status")
    if prev == new_status:
        return {
            "type": "update_contact_status",
            "result": f"already {new_status}",
            "label": contact.get("name"),
            "nav": _nav("operate", "contacts", contact["id"]),
        }

    await _sb(client, "PATCH", f"/contacts?id=eq.{contact['id']}",
              {"status": new_status})

    # Emit event so contact-linked modules can pick it up
    await _sb(client, "POST", "/events", {
        "business_id": biz["id"],
        "contact_id": contact["id"],
        "event_type": "contact_status_changed",
        "data": {"from": prev, "to": new_status},
        "source": "chief_of_staff",
    })

    return {
        "type": "update_contact_status",
        "result": f"{prev} → {new_status}",
        "label": contact.get("name"),
        "nav": _nav("operate", "contacts", contact["id"]),
    }


async def handle_update_contact_health(client, biz, action) -> Dict:
    contact_id = action.get("contact_id")
    try:
        score = max(0, min(100, int(action.get("health_score", 0))))
    except (TypeError, ValueError):
        return _fail("update_contact_health", "health_score must be a number 0-100")
    contact = await _validate_contact(client, biz["id"], contact_id)
    if not contact:
        return _fail("update_contact_health", f"Contact {contact_id} not found")

    await _sb(client, "PATCH", f"/contacts?id=eq.{contact['id']}",
              {"health_score": score})
    return {
        "type": "update_contact_health",
        "result": f"health = {score}",
        "label": contact.get("name"),
        "nav": _nav("operate", "contacts", contact["id"]),
    }


AGENT_ENDPOINT_MAP = {
    "nurture": "/agents/nurture/run",
    "session_prep": "/agents/session/prep",
    "session_follow": "/agents/session/follow-up",
    "session_no_show": "/agents/session/no-show",
    "contract": "/agents/contract/generate",
    "payment": "/agents/payment/check",
    "module": "/agents/module/check",
    "briefing": "/agents/growth/briefing",
    "insights": "/agents/growth/insights",
}


async def _loopback_post(path: str, body: Dict) -> Optional[Dict]:
    """Try localhost first (fast), fall back to public URL."""
    for base in (SELF_BASE, FALLBACK_BASE):
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
                resp = await c.post(f"{base}{path}", json=body)
                if resp.status_code < 400:
                    return resp.json()
                logger.warning(f"Loopback {base}{path}: {resp.status_code}")
        except httpx.HTTPError as e:
            logger.warning(f"Loopback {base}{path} failed: {e}")
    return None


async def handle_run_agent(client, biz, action) -> Dict:
    agent = (action.get("agent") or "").lower().strip()
    path = AGENT_ENDPOINT_MAP.get(agent)
    if not path:
        return _fail("run_agent", f"Unknown agent '{agent}'. Valid: {', '.join(AGENT_ENDPOINT_MAP)}")

    data = await _loopback_post(path, {"business_id": biz["id"]})
    if not data:
        return _fail("run_agent", f"{agent} endpoint unreachable")

    # Normalize the count across agents
    count = (data.get("drafts_created")
             or data.get("briefs_created")
             or data.get("followups_created")
             or data.get("proposals_drafted")
             or data.get("actions_generated")
             or data.get("generated") or 0)

    summary_map = {
        "nurture": f"Nurture Agent: {count} draft{'' if count == 1 else 's'} created",
        "session_prep": f"Session prep: {count} brief{'' if count == 1 else 's'}",
        "session_follow": f"Session follow-ups: {count} draft{'' if count == 1 else 's'}",
        "session_no_show": f"No-show handling: {count} draft{'' if count == 1 else 's'}",
        "contract": f"Contract Agent: {count} proposal{'' if count == 1 else 's'}",
        "payment": f"Payment Agent: {count} draft{'' if count == 1 else 's'}",
        "module": f"Module Agent: {count} draft{'' if count == 1 else 's'} across custom modules",
        "briefing": "Weekly briefing generated",
        "insights": f"{count} new insight{'' if count == 1 else 's'} generated",
    }
    label = summary_map.get(agent, f"{agent} ran")
    nav = _nav("grow", "briefing") if agent == "briefing" else \
          _nav("grow", "insights") if agent == "insights" else \
          _nav("operate", "queue")

    return {"type": "run_agent", "result": "completed", "label": label, "nav": nav}


async def handle_create_module_entry(client, biz, action) -> Dict:
    module_id = action.get("module_id")
    module = await _validate_module(client, biz["id"], module_id)
    if not module:
        return _fail("create_module_entry", f"Module {module_id} not found")

    data = action.get("data") or {}
    if not isinstance(data, dict):
        return _fail("create_module_entry", "data must be an object")

    inserted = await _sb(client, "POST", "/module_entries", {
        "module_id": module["id"], "business_id": biz["id"],
        "data": data, "status": "active",
        "created_by": "chief_of_staff", "source": "chief_of_staff",
    })
    if not inserted:
        return _fail("create_module_entry", "insert failed")

    title = data.get("title") or data.get("deliverable_name") or "(new entry)"
    return {
        "type": "create_module_entry",
        "result": "entry added",
        "label": f"{module.get('name')}: {title}",
        "nav": _nav("build"),  # module is in build sidebar
    }


async def handle_create_contact(client, biz, action) -> Dict:
    name = (action.get("name") or "").strip()
    if not name:
        return _fail("create_contact", "name is required")

    status = (action.get("status") or "lead").lower()
    if status not in VALID_CONTACT_STATUSES:
        status = "lead"

    payload = {
        "business_id": biz["id"],
        "name": name,
        "email": action.get("email") or None,
        "phone": action.get("phone") or None,
        "role": action.get("role") or None,
        "status": status,
        "source": "chief_of_staff",
        "tags": action.get("tags") or [],
    }
    inserted = await _sb(client, "POST", "/contacts", payload)
    if not inserted:
        return _fail("create_contact", "insert failed")

    created = inserted[0] if isinstance(inserted, list) else inserted
    return {
        "type": "create_contact",
        "result": f"added as {status}",
        "label": name,
        "nav": _nav("operate", "contacts", created.get("id")),
    }


async def handle_generate_briefing(client, biz, action) -> Dict:
    return await handle_run_agent(client, biz, {"agent": "briefing"})


async def handle_generate_insights(client, biz, action) -> Dict:
    return await handle_run_agent(client, biz, {"agent": "insights"})


ACTION_HANDLERS = {
    "draft_nurture":         handle_draft_nurture,
    "draft_email":           handle_draft_email,
    "create_session":        handle_create_session,
    "update_contact_status": handle_update_contact_status,
    "update_contact_health": handle_update_contact_health,
    "run_agent":             handle_run_agent,
    "create_module_entry":   handle_create_module_entry,
    "create_contact":        handle_create_contact,
    "generate_briefing":     handle_generate_briefing,
    "generate_insights":     handle_generate_insights,
}


async def _execute_actions(client, biz, actions: List[Dict]) -> List[Dict]:
    results = []
    for action in actions:
        atype = action.get("type")
        handler = ACTION_HANDLERS.get(atype)
        if not handler:
            results.append(_fail(atype or "unknown", f"Unknown action type '{atype}'"))
            continue
        try:
            res = await handler(client, biz, action)
            results.append(res)
        except Exception as e:
            logger.exception(f"Action {atype} raised: {e}")
            results.append(_fail(atype, str(e)[:200]))
    return results


# ═══════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT
# ═══════════════════════════════════════════════════════════════════════

def _build_system_prompt(ctx: Dict[str, Any], is_greeting: bool) -> str:
    biz = ctx.get("business") or {}
    biz_name = biz.get("name", "the business")
    practitioner = (biz.get("settings") or {}).get("practitioner_name", "the practitioner")
    voice = biz.get("voice_profile") or {}

    context_block = _format_context_for_prompt(ctx)

    greeting_clause = ""
    if is_greeting:
        greeting_clause = """

OPENING GREETING MODE:
This is your first turn in a fresh conversation. Give a concise briefing (2-4 sentences) based on the most important things in the data RIGHT NOW. Lead with what needs attention. If there are pending drafts, mention the count. If there are at-risk contacts, name one. If there's an unread insight worth flagging, reference it. End with ONE question or a specific proactive suggestion. Do NOT just say "how can I help" — give them a real read on their business. Do NOT emit actions in the greeting."""

    return f"""You are the Chief of Staff for {biz_name}. You are {practitioner}'s operational partner — you see everything happening in their business and help them manage it through conversation.

REAL-TIME BUSINESS DATA (fresh every message):

{context_block}

CAPABILITIES:
- ANSWER questions with specific data from above (names, numbers, dates, IDs).
- TAKE ACTIONS by embedding JSON tags in your response.
- SUGGEST proactive next steps based on the data.
- BRIEF the practitioner on what needs attention now.

ACTION FORMAT — embed JSON inside [ACTION:...] tags anywhere in your response. The system strips them before display.

Available action types:
  [ACTION:{{"type":"draft_nurture","contact_id":"<uuid from CONTACT LOOKUP>","reason":"why"}}]
  [ACTION:{{"type":"draft_email","contact_id":"<uuid>","subject":"...","reason":"..."}}]
  [ACTION:{{"type":"create_session","contact_id":"<uuid>","title":"Follow-up","scheduled_for":"2026-04-20T14:00:00Z","duration_minutes":60}}]
  [ACTION:{{"type":"update_contact_status","contact_id":"<uuid>","new_status":"active|lead|vip|inactive|churned"}}]
  [ACTION:{{"type":"update_contact_health","contact_id":"<uuid>","health_score":75}}]
  [ACTION:{{"type":"run_agent","agent":"nurture|session_prep|session_follow|session_no_show|contract|payment|module|briefing|insights"}}]
  [ACTION:{{"type":"create_module_entry","module_id":"<uuid from CUSTOM MODULES>","data":{{...schema-matching keys...}}}}]
  [ACTION:{{"type":"create_contact","name":"...","email":"...","status":"lead"}}]
  [ACTION:{{"type":"generate_briefing"}}]
  [ACTION:{{"type":"generate_insights"}}]

ACTION RULES:
- Use EXACT UUIDs from the CONTACT LOOKUP / CUSTOM MODULES sections. Never invent IDs.
- Don't emit actions unless the practitioner explicitly asks you to do something OR you're taking an obvious next step they've agreed to.
- Emit at most {MAX_ACTIONS_PER_TURN} actions per turn.
- Confirm in plain language what you're doing ("Drafting a check-in for Deacon Harris now.") — the system will show a separate actions card below your message.

VOICE:
Direct, warm, operational. Match {practitioner}'s communication style (voice profile: {json.dumps(voice)[:400]}). Reference specific names and numbers from the data. No generic advice. Lead with the answer, then offer to go deeper if useful.

Keep responses concise unless asked for depth. If the practitioner asks a factual question, answer in one or two sentences. If they want analysis, give the analysis then stop.{greeting_clause}"""


# ═══════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════

router = APIRouter(tags=["chief_of_staff"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    business_id: str
    message: str
    conversation_history: Optional[List[ChatMessage]] = None


@router.post("/agents/chief/chat")
async def chief_chat(req: ChatRequest):
    if not req.message:
        raise HTTPException(400, "message is required")

    async with httpx.AsyncClient() as client:
        ctx = await _gather_context(client, req.business_id)
        if not ctx:
            raise HTTPException(404, "Business not found")
        biz = ctx["business"]

        is_greeting = req.message.strip() == OPENING_SENTINEL
        system = _build_system_prompt(ctx, is_greeting)

        # Build API messages — trim history and drop sentinel from the visible trail
        history = (req.conversation_history or [])[-MAX_HISTORY:]
        api_messages: List[Dict[str, str]] = []
        for m in history:
            role = "assistant" if m.role == "assistant" else "user"
            # Filter out any accidental sentinel echoes in history
            if m.content.strip() == OPENING_SENTINEL:
                continue
            api_messages.append({"role": role, "content": m.content})

        api_messages.append({"role": "user", "content": req.message})

        raw = await _call_claude(client, system, api_messages, max_tokens=1600)
        if not raw:
            return {
                "response": "I can't reach the language model right now — try again in a moment.",
                "actions_taken": [],
            }

        actions, clean = _extract_actions_and_clean(raw)
        taken = await _execute_actions(client, biz, actions) if actions else []

        logger.info(
            f"Chief chat for {biz.get('name')}: message_len={len(req.message)} "
            f"actions={len(taken)} greeting={is_greeting}"
        )

        return {
            "response": clean or raw,
            "actions_taken": taken,
        }


@router.get("/agents/chief/health")
async def chief_health():
    return {
        "status": "ok",
        "supabase_configured": bool(_supabase_url()),
        "anthropic_configured": bool(_anthropic_key()),
        "self_base": SELF_BASE,
        "model": CHIEF_MODEL,
        "max_history": MAX_HISTORY,
        "max_actions_per_turn": MAX_ACTIONS_PER_TURN,
        "action_handlers": list(ACTION_HANDLERS.keys()),
    }
