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

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
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
OPENING_SENTINEL_PREFIX = "[SYSTEM:opening_greeting"  # may have :morning/:afternoon/:evening suffix
COACH_OPEN_SENTINEL = "[SYSTEM:strategy_coach_open]"
COACH_PAUSE_SENTINEL = "[SYSTEM:strategy_coach_pause]"
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
        _sb(client, "GET",
            f"/chief_memories?business_id=eq.{biz_id}&is_active=eq.true"
            f"&order=importance.desc,created_at.desc&limit=50"
            f"&select=id,category,content,importance,source,created_at,last_referenced_at"),
        _sb(client, "GET",
            f"/chief_notifications?business_id=eq.{biz_id}&status=eq.unread"
            f"&order=created_at.desc&limit=5"
            f"&select=id,type,title,body,priority,suggested_action,created_at"),
        _sb(client, "GET",
            f"/agent_queue?business_id=eq.{biz_id}"
            f"&created_at=gte.{(datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()}"
            f"&order=created_at.desc&limit=30"
            f"&select=id,agent,action_type,subject,status,priority,contact_id,body,created_at"),
        _sb(client, "GET",
            f"/business_sites?business_id=eq.{biz_id}"
            f"&order=updated_at.desc&limit=1"
            f"&select=slug,status,site_config"),
        _sb(client, "GET",
            f"/strategy_tracks?business_id=eq.{biz_id}"
            f"&order=created_at.desc&limit=1&select=*"),
    ]
    biz_rows, contacts, queue, events, sessions, insights, modules, memories, notifications, recent_queue, site_rows, strategy_rows = await asyncio.gather(*tasks)

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
        "memories": memories or [],
        "notifications": notifications or [],
        "recent_queue_24h": recent_queue or [],
        "site": (site_rows or [{}])[0] if site_rows else None,
        "strategy_track": (strategy_rows or [None])[0] if strategy_rows else None,
        # Keep the full contact list (IDs + names) so the AI can reference real UUIDs
        "contacts_lookup": [
            {"id": c["id"], "name": c.get("name"), "status": c.get("status"), "health_score": c.get("health_score")}
            for c in contacts[:200]
        ],
    }


def _format_site_info(ctx: Dict[str, Any]) -> str:
    site = ctx.get("site")
    if not site or not site.get("slug"):
        return "  (no site generated yet)"
    slug = site["slug"]
    status = site.get("status", "draft")
    custom = (site.get("site_config") or {}).get("custom_domain")
    lines = [f"  Live at: https://{slug}.mysolutionist.app"]
    lines.append(f"  Status: {status}")
    if custom:
        lines.append(f"  Custom domain: {custom}")
    lines.append(f"  Direct link: /public/site/{slug}")
    return "\n".join(lines)


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

    # Practitioner memories — sorted desc by importance (already sorted in query)
    memory_lines = [
        f"  - [{(m.get('category') or 'other').upper()} ★{m.get('importance', 5)}] {m.get('content')}"
        for m in (ctx.get("memories") or [])
    ]

    # Recent agent activity (last 24h queue items, grouped by agent)
    recent_q = ctx.get("recent_queue_24h") or []
    agent_activity: Dict[str, Dict[str, int]] = {}
    for rq in recent_q:
        ag = rq.get("agent") or "unknown"
        st = rq.get("status") or "draft"
        bucket = agent_activity.setdefault(ag, {})
        bucket[st] = bucket.get(st, 0) + 1
    activity_lines = []
    for ag, statuses in agent_activity.items():
        parts = ", ".join(f"{cnt} {st}" for st, cnt in sorted(statuses.items()))
        activity_lines.append(f"  - {ag}: {parts}")

    # Standing instructions (from memories)
    standing = [m for m in (ctx.get("memories") or []) if (m.get("category") or "").lower() == "standing_instruction"]
    standing_lines = [
        f"  - [★{m.get('importance', 5)}] {m.get('content')}"
        for m in standing
    ]

    # Recent unread notifications
    notif_lines = []
    for n in (ctx.get("notifications") or []):
        days = _days_since(n.get("created_at"))
        when = f"{days}d ago" if days and days >= 1 else "today"
        suggestion = f" → suggested: {n['suggested_action']}" if n.get("suggested_action") else ""
        notif_lines.append(
            f"  - [{(n.get('type') or '').upper()} {n.get('priority', 'normal')}] "
            f"\"{n.get('title')}\" ({when}){suggestion}"
        )

    # Email templates + signature snapshot so the Chief uses them when drafting
    et = (biz.get('settings') or {}).get('email_templates') or {}
    et_summary = ""
    if isinstance(et, dict) and (et.get('templates') or et.get('signature') or et.get('global_rules')):
        sig = (et.get('signature') or {})
        rules = (et.get('global_rules') or {})
        tpls = (et.get('templates') or {})
        et_summary = (
            "\n  Email templates: " + ", ".join(sorted(tpls.keys())[:12])
            + f"\n  Signature: {sig.get('name', '(none)')} · {sig.get('title', '')} · {sig.get('business', '')}"
            + f"\n  Closing line: {rules.get('closing_line', '(default)')}"
            + (f"\n  Always mention: {rules.get('always_mention')}" if rules.get('always_mention') else "")
            + (f"\n  Disclaimer: {(rules.get('disclaimer') or '')[:120]}" if rules.get('disclaimer') else "")
        )

    return f"""BUSINESS: {bizname} (type: {biztype})
  Practitioner: {(biz.get('settings') or {}).get('practitioner_name', 'the practitioner')}
  Voice profile: {json.dumps(biz.get('voice_profile') or {})[:500]}{et_summary}

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

PRACTITIONER MEMORIES (ALWAYS honor these — they override defaults):
{chr(10).join(memory_lines) if memory_lines else '  (none stored yet)'}

RECENT AGENT ACTIVITY (last 24 hours):
{chr(10).join(activity_lines) if activity_lines else '  (no agent activity)'}

STANDING INSTRUCTIONS (execute when triggered):
{chr(10).join(standing_lines) if standing_lines else '  (none set)'}

RECENT UNREAD NOTIFICATIONS:
{chr(10).join(notif_lines) if notif_lines else '  (none)'}

PRACTITIONER SITE:
{_format_site_info(ctx)}

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

    subject = f"Check-in for {contact.get('name')}"
    inserted = await _sb(client, "POST", "/agent_queue", {
        "business_id": biz["id"], "contact_id": contact["id"],
        "agent": "nurture", "action_type": "check_in",
        "subject": subject,
        "body": body,
        "channel": "email" if contact.get("email") else "in_app",
        "status": "draft", "priority": "medium",
        "ai_reasoning": f"Chief of Staff requested: {reason}",
        "ai_model": DRAFT_MODEL,
    })
    if not inserted:
        return _fail("draft_nurture", "insert failed")

    queue_id = inserted[0].get("id") if isinstance(inserted, list) and inserted else None
    return {
        "type": "draft_nurture",
        "result": "queued for approval",
        "label": f"Check-in for {contact.get('name')}",
        "nav": _nav("operate", "queue"),
        "queue_id": queue_id,
        "draft_preview": {"subject": subject, "body": (body or "")[:200]},
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

    queue_id = inserted[0].get("id") if isinstance(inserted, list) and inserted else None
    label = f"Email: {subject}" + (f" → {contact.get('name')}" if contact else "")
    return {
        "type": "draft_email",
        "result": "queued for approval",
        "label": label,
        "nav": _nav("operate", "queue"),
        "queue_id": queue_id,
        "draft_preview": {"subject": subject, "body": (body or "")[:200]},
    }


async def handle_draft_and_send(client, biz, action) -> Dict:
    """Draft an email AND immediately approve + send it in a single step.

    Reuses handle_draft_email to build the draft row so the body, signature,
    channel, and reasoning logic stay in sync. Then pulls the freshly-inserted
    row and feeds it to _do_approve_one, which PATCHes status → approved,
    calls Resend via _send_queued_email, and PATCHes status → sent on 2xx.

    Returns the draft_email result merged with the approval's delivery info so
    the Chief can narrate both outcomes (drafted + sent / drafted + no email /
    drafted + delivery failed) in one action card.
    """
    # Step 1 — run the normal draft handler to create the queue row.
    draft_result = await handle_draft_email(client, biz, action)
    if str(draft_result.get("result", "")).startswith("Failed"):
        return {**draft_result, "type": "draft_and_send"}

    queue_id = draft_result.get("queue_id")
    if not queue_id:
        return _fail("draft_and_send", "draft insert succeeded but no queue_id returned")

    # Step 2 — load the freshly-inserted row and approve + send.
    rows = await _sb(client, "GET",
        f"/agent_queue?id=eq.{queue_id}&business_id=eq.{biz['id']}&limit=1&select=*")
    if not rows:
        return _fail("draft_and_send", f"Draft {queue_id} not found after insert")
    item = rows[0]
    delivery = await _do_approve_one(client, biz, item)

    # Step 3 — merge results.
    if delivery.get("sent"):
        result_str = "drafted and sent"
    elif delivery.get("reason") == "no_email":
        result_str = "drafted (no email on file — not sent)"
    elif delivery.get("reason") == "no_contact":
        result_str = "drafted (no contact — not sent)"
    elif (delivery.get("reason") or "").startswith("exception:"):
        result_str = "drafted (send failed)"
    elif delivery.get("reason") == "no_api_key":
        result_str = "drafted (email provider not configured)"
    else:
        result_str = "drafted and approved"

    return {
        "type": "draft_and_send",
        "result": result_str,
        "label": _approve_label(item.get("subject"), delivery),
        "nav": _nav("operate", "queue"),
        "queue_id": queue_id,
        "email_sent": bool(delivery.get("sent")),
        "to_email": delivery.get("to_email"),
        "draft_preview": draft_result.get("draft_preview"),
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
    target_contact = action.get("target_contact_id")
    target_module = action.get("target_module_id")
    sub = action.get("sub")  # for session: prep / follow-up / no-show

    # ── Targeted mode: call preview endpoint → insert draft directly ──
    if target_contact and agent in ("nurture", "contract"):
        contact = await _validate_contact(client, biz["id"], target_contact)
        if not contact:
            return _fail("run_agent", f"Contact {target_contact} not found")

        if agent == "nurture":
            preview_path = "/agents/nurture/preview"
        else:
            preview_path = "/agents/contract/preview"

        data = await _loopback_post(preview_path, {
            "business_id": biz["id"],
            "contact_id": target_contact,
        })
        if not data:
            return _fail("run_agent", f"{agent} preview unreachable")

        # Preview endpoints return draft content — insert into queue
        subject = data.get("subject") or f"{agent.title()} draft for {contact.get('name')}"
        body = data.get("body") or ""
        action_type = "proposal" if agent == "contract" else "check_in"

        inserted = await _sb(client, "POST", "/agent_queue", {
            "business_id": biz["id"],
            "contact_id": target_contact,
            "agent": agent,
            "action_type": action_type,
            "subject": subject,
            "body": body,
            "channel": "email" if contact.get("email") else "in_app",
            "status": "draft",
            "priority": data.get("priority", "medium"),
            "ai_reasoning": data.get("ai_reasoning") or f"Targeted {agent} run via Chief of Staff",
            "ai_model": data.get("ai_model") or CHIEF_MODEL,
        })
        queue_id = inserted[0]["id"] if (inserted and isinstance(inserted, list)) else None

        return {
            "type": "run_agent",
            "result": "drafted",
            "label": f"{agent.title()}: {subject}",
            "nav": _nav("operate", "queue"),
            "draft_preview": {"subject": subject, "body": body[:800], "queue_id": queue_id},
        }

    if target_contact and agent.startswith("session"):
        contact = await _validate_contact(client, biz["id"], target_contact)
        if not contact:
            return _fail("run_agent", f"Contact {target_contact} not found")
        # Session agents work on all matching sessions — pass business_id
        session_sub = sub or "prep"
        session_path = AGENT_ENDPOINT_MAP.get(f"session_{session_sub}") or "/agents/session/prep"
        data = await _loopback_post(session_path, {"business_id": biz["id"]})
        if not data:
            return _fail("run_agent", f"session {session_sub} unreachable")
        count = data.get("briefs_created") or data.get("followups_created") or data.get("drafts_created") or 0
        return {
            "type": "run_agent", "result": "completed",
            "label": f"Session {session_sub}: {count} draft{'s' if count != 1 else ''}",
            "nav": _nav("operate", "queue"),
        }

    # ── Batch mode (existing behavior) ────────────────────────────────
    path = AGENT_ENDPOINT_MAP.get(agent)
    if not path:
        return _fail("run_agent", f"Unknown agent '{agent}'. Valid: {', '.join(AGENT_ENDPOINT_MAP)}")

    body_payload: Dict = {"business_id": biz["id"]}
    data = await _loopback_post(path, body_payload)
    if not data:
        return _fail("run_agent", f"{agent} endpoint unreachable")

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


async def handle_navigate(client, biz, action) -> Dict:
    """Pass-through — the frontend actually performs the navigation.
    We just validate the shape and produce a nice label + nav payload."""
    tab = (action.get("tab") or "").lower().strip()
    if tab not in {"build", "operate", "grow"}:
        return _fail("navigate", f"Unknown tab '{tab}'")

    sub = action.get("sub")
    page = action.get("page")
    contact_id = action.get("contact_id")

    nav = {"tab": tab}
    if sub: nav["sub"] = sub
    if page: nav["page"] = page
    if contact_id: nav["contactId"] = contact_id

    # Build a human label
    label_parts = [tab.upper()]
    if sub: label_parts.append(sub)
    if page: label_parts.append(page)
    label = " → ".join(label_parts)

    if contact_id:
        rows = await _sb(client, "GET",
            f"/contacts?id=eq.{contact_id}&business_id=eq.{biz['id']}&limit=1&select=name")
        if rows:
            label += f" → {rows[0].get('name')}"

    return {
        "type": "navigate",
        "result": "opened",
        "label": f"Opened {label}",
        "nav": nav,
    }


VALID_MEMORY_CATEGORIES = {"preference", "pattern", "context", "decision", "boundary", "goal", "standing_instruction", "other"}

# Stop words excluded from memory dedup signature
_MEMORY_STOPWORDS = {
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "it", "they", "them",
    "the", "a", "an", "and", "or", "but", "to", "of", "for", "in", "on", "at",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "should", "can", "could", "may", "might",
    "this", "that", "these", "those", "with", "as", "from", "by", "into", "about",
    "than", "then", "so", "too", "very", "just", "not", "no",
}


def _memory_signature(content: str) -> set:
    """Lowercase non-stopword tokens of a memory's content."""
    if not content:
        return set()
    cleaned = "".join(c.lower() if c.isalnum() else " " for c in content)
    tokens = [t for t in cleaned.split() if t and t not in _MEMORY_STOPWORDS and len(t) > 1]
    return set(tokens)


async def _find_duplicate_memory(client, biz_id: str, content: str) -> Optional[Dict]:
    """Return an existing memory if 80%+ of `content`'s significant words are
    contained in it. Skips dedup for very short content (<3 sig words)."""
    new_sig = _memory_signature(content)
    if len(new_sig) < 3:
        return None
    existing = await _sb(client, "GET",
        f"/chief_memories?business_id=eq.{biz_id}&is_active=eq.true"
        f"&select=id,content&limit=200")
    if not existing:
        return None
    for row in existing:
        old_sig = _memory_signature(row.get("content") or "")
        if not old_sig:
            continue
        overlap = len(new_sig & old_sig) / len(new_sig)
        if overlap >= 0.80:
            return row
    return None


async def handle_remember(client, biz, action) -> Dict:
    """Store a memory about the practitioner."""
    content = (action.get("content") or "").strip()
    if not content:
        return _fail("remember", "no content provided")
    category = (action.get("category") or "other").lower().strip()
    if category not in VALID_MEMORY_CATEGORIES:
        category = "other"
    try:
        importance = max(1, min(10, int(action.get("importance", 5))))
    except (TypeError, ValueError):
        importance = 5

    # Word-overlap dedup
    dup = await _find_duplicate_memory(client, biz["id"], content)
    if dup:
        return {
            "type": "remember",
            "result": "already remembered",
            "label": f"Memory exists: {(dup.get('content') or '')[:60]}",
            "nav": _nav("operate"),  # no specific destination
        }

    inserted = await _sb(client, "POST", "/chief_memories", {
        "business_id": biz["id"],
        "category": category,
        "content": content[:2000],
        "source": "user_stated",
        "importance": importance,
    })
    if not inserted:
        return _fail("remember", "insert failed")

    label = f"Remembered ({category}): {content[:80]}"
    return {"type": "remember", "result": "stored", "label": label, "nav": None}


async def handle_forget(client, biz, action) -> Dict:
    """Deactivate a memory whose content matches the supplied phrase."""
    target = (action.get("memory_content") or action.get("content") or "").strip()
    if not target:
        return _fail("forget", "no memory_content provided")

    target_sig = _memory_signature(target)
    if not target_sig:
        return _fail("forget", "couldn't parse memory_content")

    existing = await _sb(client, "GET",
        f"/chief_memories?business_id=eq.{biz['id']}&is_active=eq.true"
        f"&select=id,content&limit=200") or []

    best = None
    best_score = 0.0
    for row in existing:
        old_sig = _memory_signature(row.get("content") or "")
        if not old_sig:
            continue
        score = len(target_sig & old_sig) / max(len(target_sig), 1)
        if score > best_score:
            best_score = score
            best = row

    if not best or best_score < 0.5:
        return {"type": "forget", "result": "couldn't find that memory", "label": target[:60], "nav": None}

    await _sb(client, "PATCH", f"/chief_memories?id=eq.{best['id']}",
              {"is_active": False})
    return {
        "type": "forget",
        "result": "forgotten",
        "label": f"Forgot: {(best.get('content') or '')[:60]}",
        "nav": None,
    }


# ═══════════════════════════════════════════════════════════════════════
# QUEUE MANAGEMENT HANDLERS (approve / dismiss / edit / rewrite / bulk)
# ═══════════════════════════════════════════════════════════════════════

BULK_CAP = 20
HEALTH_BUMP_ON_APPROVE = 5


def _format_from_email() -> str:
    return os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app"


def _build_signature_plaintext(sig: Dict[str, Any]) -> str:
    """Mirrors the frontend signature builder — plain text for email bodies."""
    if not isinstance(sig, dict):
        return ""
    lines: List[str] = []
    if sig.get("name"): lines.append(sig["name"])
    title_line = " · ".join([s for s in [sig.get("title"), sig.get("business")] if s])
    if title_line: lines.append(title_line)
    if sig.get("tagline"): lines.append(sig["tagline"])
    contact = " · ".join([s for s in [sig.get("phone"), sig.get("email")] if s])
    if contact: lines.append(contact)
    if sig.get("link_page_url"): lines.append(sig["link_page_url"])
    return "\n".join(lines)


def _compose_body_with_signature(body: str, biz: Dict[str, Any]) -> str:
    """Append the practitioner's closing line + signature + disclaimer to a
    draft body when global_rules say so. Plain-text friendly — the receiving
    client can wrap it however it likes."""
    body = body or ""
    et = (biz.get("settings") or {}).get("email_templates") or {}
    rules = et.get("global_rules") or {}
    sig = et.get("signature") or {}
    out = body.rstrip()

    closing = (rules.get("closing_line") or "").strip()
    if closing and closing not in out:
        out += f"\n\n{closing}"

    if rules.get("always_include_signature", True):
        sig_text = _build_signature_plaintext(sig)
        if sig_text and sig_text not in out:
            out += f"\n{sig_text}" if closing else f"\n\n{sig_text}"

    disclaimer = (rules.get("disclaimer") or "").strip()
    if disclaimer and disclaimer not in out:
        out += f"\n\n--\n{disclaimer}"

    return out


async def _send_queued_email(client, biz: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    """Deliver a queue item via Resend. Returns a dict describing the
    outcome — never raises. Fields:
      sent: bool            — True only if Resend returned 2xx
      reason: str | None    — populated when NOT sent ("no_contact",
                              "no_email", "no_api_key", "exception:<msg>")
      to_email: str | None
      to_name: str | None
      provider_id: str | None   — Resend message id when sent
    """
    out: Dict[str, Any] = {"sent": False, "reason": None, "to_email": None, "to_name": None, "provider_id": None}

    # v1 rule: if the queue item has a contact_id and the contact has an
    # email, send. No channel/action_type gating — the frozen channel value
    # on the draft row does not reflect whether the contact has an email
    # NOW, only at draft time.
    contact_id = item.get("contact_id")
    if not contact_id:
        out["reason"] = "no_contact"
        return out

    rows = await _sb(client, "GET",
        f"/contacts?id=eq.{contact_id}&business_id=eq.{biz['id']}&limit=1&select=id,name,email")
    if not rows:
        out["reason"] = "no_contact"
        return out
    contact = rows[0]
    email = (contact.get("email") or "").strip()
    if not email or "@" not in email:
        out["reason"] = "no_email"
        out["to_name"] = contact.get("name")
        return out

    if not os.environ.get("RESEND_API_KEY"):
        out["reason"] = "no_api_key"
        out["to_email"] = email
        out["to_name"] = contact.get("name")
        return out

    # Build the final body (append closing + signature + disclaimer per rules)
    composed_body = _compose_body_with_signature(item.get("body") or "", biz)

    settings = biz.get("settings") or {}
    et = settings.get("email_templates") or {}
    sig = et.get("signature") or {}
    from_name = (sig.get("name") or settings.get("practitioner_name") or biz.get("name") or "The Solutionist System").strip()
    reply_to = (sig.get("email") or settings.get("contact_email") or "").strip() or None

    # Use the email_sender helper directly — no HTTP hop to ourselves.
    try:
        from email_sender import send_via_resend  # local import: avoid circular + runtime-only
        data = await send_via_resend(
            to_email=email,
            to_name=contact.get("name"),
            from_email=_format_from_email(),
            from_name=from_name,
            subject=item.get("subject") or f"Message from {biz.get('name', '')}",
            body=composed_body,
            reply_to=reply_to,
        )
        out["sent"] = True
        out["to_email"] = email
        out["to_name"] = contact.get("name")
        if isinstance(data, dict):
            out["provider_id"] = data.get("id")
    except Exception as e:
        logger.warning(f"Resend delivery failed for queue {item.get('id')}: {e}")
        out["reason"] = f"exception:{str(e)[:160]}"
        out["to_email"] = email
        out["to_name"] = contact.get("name")

    return out


async def _do_approve_one(client, biz: Dict[str, Any], item: Dict) -> Dict[str, Any]:
    """Approve a single queue item: PATCH status, attempt Resend send,
    emit event, bump health. Returns delivery info for the caller to
    surface in the action's `result`/`label`.
    """
    qid = item.get("id")
    contact_id = item.get("contact_id")
    biz_id = biz["id"]
    result: Dict[str, Any] = {"ok": False, "sent": False, "reason": None, "to_email": None, "to_name": None, "provider_id": None}
    if not qid:
        return result

    now_iso = datetime.now(timezone.utc).isoformat()

    # Step 1: mark approved
    await _sb(client, "PATCH", f"/agent_queue?id=eq.{qid}", {
        "status": "approved",
        "reviewed_at": now_iso,
    })

    # Step 2: attempt delivery
    delivery = await _send_queued_email(client, biz, item)
    result.update(delivery)
    result["ok"] = True

    # Step 3: if sent, flip status to "sent" and timestamp
    if delivery.get("sent"):
        patch: Dict[str, Any] = {"status": "sent", "sent_at": now_iso}
        await _sb(client, "PATCH", f"/agent_queue?id=eq.{qid}", patch)

    # Step 4: emit event (agent_message_sent when delivered, agent_message_approved otherwise)
    await _sb(client, "POST", "/events", {
        "business_id": biz_id,
        "contact_id": contact_id,
        "event_type": "agent_message_sent" if delivery.get("sent") else "agent_message_approved",
        "data": {
            "agent": item.get("agent"),
            "action_type": item.get("action_type"),
            "subject": item.get("subject"),
            "queue_id": qid,
            "email_sent": bool(delivery.get("sent")),
            "reason": delivery.get("reason"),
            "provider_id": delivery.get("provider_id"),
        },
        "source": "chief_of_staff",
    })

    # Step 5: bump contact health
    if contact_id:
        existing = await _sb(client, "GET",
            f"/contacts?id=eq.{contact_id}&select=health_score&limit=1")
        if existing:
            score = min(100, (existing[0].get("health_score") or 50) + HEALTH_BUMP_ON_APPROVE)
            await _sb(client, "PATCH", f"/contacts?id=eq.{contact_id}", {
                "health_score": score,
                "last_interaction": now_iso,
            })
    return result


def _approve_label(subject: Optional[str], delivery: Dict[str, Any]) -> str:
    """Human-readable label for the Chief's action card."""
    subj = subject or "draft"
    if delivery.get("sent"):
        to_parts = []
        if delivery.get("to_name"): to_parts.append(delivery["to_name"])
        if delivery.get("to_email"): to_parts.append(f"({delivery['to_email']})")
        target = " to " + " ".join(to_parts) if to_parts else ""
        return f"📧 Sent: {subj}{target}"
    reason = delivery.get("reason") or ""
    if reason == "no_email":
        return f"✓ Approved (no email on file): {subj} — add an email to send"
    if reason == "no_contact":
        return f"✓ Approved (no contact linked): {subj}"
    if reason == "no_api_key":
        return f"✓ Approved (email provider not configured): {subj}"
    if reason.startswith("exception:"):
        return f"✓ Approved (delivery failed — will retry): {subj}"
    return f"✓ Approved: {subj}"


async def handle_approve_draft(client, biz, action) -> Dict:
    qid = action.get("queue_id")
    if not qid:
        return _fail("approve_draft", "queue_id required")

    # Shortcut: queue_id="latest" resolves to the most recent draft for
    # this business. Lets the Chief chain a draft + "approve it" across
    # turns without needing to know the UUID it just created.
    if qid == "latest":
        latest = await _sb(client, "GET",
            f"/agent_queue?business_id=eq.{biz['id']}&status=eq.draft"
            f"&order=created_at.desc&limit=1&select=id")
        if not latest:
            return {"type": "approve_draft", "result": "no drafts found", "label": "No pending drafts", "nav": _nav("operate", "queue")}
        qid = latest[0]["id"]

    rows = await _sb(client, "GET",
        f"/agent_queue?id=eq.{qid}&business_id=eq.{biz['id']}&limit=1&select=*")
    if not rows:
        return _fail("approve_draft", f"Draft {qid} not found")
    item = rows[0]
    if item.get("status") != "draft":
        return {"type": "approve_draft", "result": f"already {item.get('status')}", "label": item.get("subject") or qid, "nav": None}
    delivery = await _do_approve_one(client, biz, item)

    result_str = "approved and sent" if delivery.get("sent") else \
                 "approved (no email on file)" if delivery.get("reason") == "no_email" else \
                 "approved (no contact)" if delivery.get("reason") == "no_contact" else \
                 "approved (send failed)" if (delivery.get("reason") or "").startswith("exception:") else \
                 "approved (email not configured)" if delivery.get("reason") == "no_api_key" else \
                 "approved"

    return {
        "type": "approve_draft",
        "result": result_str,
        "label": _approve_label(item.get("subject"), delivery),
        "nav": _nav("operate", "queue"),
        "email_sent": bool(delivery.get("sent")),
        "to_email": delivery.get("to_email"),
    }


async def handle_dismiss_draft(client, biz, action) -> Dict:
    qid = action.get("queue_id")
    if not qid:
        return _fail("dismiss_draft", "queue_id required")
    rows = await _sb(client, "GET",
        f"/agent_queue?id=eq.{qid}&business_id=eq.{biz['id']}&limit=1&select=*")
    if not rows:
        return _fail("dismiss_draft", f"Draft {qid} not found")
    item = rows[0]
    await _sb(client, "PATCH", f"/agent_queue?id=eq.{qid}", {
        "status": "dismissed",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    })
    return {
        "type": "dismiss_draft",
        "result": "dismissed",
        "label": f"Dismissed: {item.get('subject') or 'draft'}",
        "nav": _nav("operate", "queue"),
    }


async def handle_edit_draft(client, biz, action) -> Dict:
    qid = action.get("queue_id")
    new_body = (action.get("new_body") or "").strip()
    if not qid:
        return _fail("edit_draft", "queue_id required")
    if not new_body:
        return _fail("edit_draft", "new_body required")
    rows = await _sb(client, "GET",
        f"/agent_queue?id=eq.{qid}&business_id=eq.{biz['id']}&limit=1&select=*")
    if not rows:
        return _fail("edit_draft", f"Draft {qid} not found")
    item = rows[0]
    await _sb(client, "PATCH", f"/agent_queue?id=eq.{qid}", {"body": new_body})
    delivery = await _do_approve_one(client, biz, {**item, "body": new_body})
    result_str = "edited, approved, and sent" if delivery.get("sent") else "edited and approved"
    return {
        "type": "edit_draft",
        "result": result_str,
        "label": f"Edited + {_approve_label(item.get('subject'), delivery).lstrip('📧 ').lstrip('✓ ').strip()}"
                 if delivery.get("sent") or (delivery.get("reason") == "no_email")
                 else f"Edited + approved: {item.get('subject') or 'draft'}",
        "nav": _nav("operate", "queue"),
        "draft_preview": new_body[:300],
        "email_sent": bool(delivery.get("sent")),
        "to_email": delivery.get("to_email"),
    }


async def handle_rewrite_draft(client, biz, action) -> Dict:
    qid = action.get("queue_id")
    instruction = (action.get("instruction") or "").strip()
    if not qid:
        return _fail("rewrite_draft", "queue_id required")
    if not instruction:
        return _fail("rewrite_draft", "instruction required")

    rows = await _sb(client, "GET",
        f"/agent_queue?id=eq.{qid}&business_id=eq.{biz['id']}&limit=1&select=*")
    if not rows:
        return _fail("rewrite_draft", f"Draft {qid} not found")
    item = rows[0]
    old_body = item.get("body") or ""

    voice = biz.get("voice_profile") or {}
    practitioner = (biz.get("settings") or {}).get("practitioner_name", "the team")
    tone = voice.get("tone", "warm and professional")

    system = (f"Rewrite this draft from {practitioner}. Voice: {tone}. "
              f"Keep the same length and intent but apply the requested change. "
              f"Return ONLY the rewritten text — no commentary, no preamble.")
    user_msg = f"CURRENT DRAFT:\n{old_body}\n\nINSTRUCTION: {instruction}"

    rewritten = await _draft_short(client, biz, system, user_msg)
    if not rewritten:
        return _fail("rewrite_draft", "AI rewrite failed")

    await _sb(client, "PATCH", f"/agent_queue?id=eq.{qid}", {"body": rewritten})
    return {
        "type": "rewrite_draft",
        "result": "rewritten (not yet approved)",
        "label": f"Rewrote: {item.get('subject') or 'draft'}",
        "nav": None,
        "draft_preview": rewritten[:600],
        "queue_id": qid,
    }


async def _query_queue_by_filter(client, biz_id: str, filter_str: str) -> List[Dict]:
    """Parse a simple filter and return matching draft queue items."""
    base = f"/agent_queue?business_id=eq.{biz_id}&status=eq.draft"
    f = filter_str.strip().lower()
    if f.startswith("agent:"):
        agent_name = f[6:].strip()
        base += f"&agent=eq.{agent_name}"
    elif f.startswith("priority:"):
        prio = f[9:].strip()
        base += f"&priority=eq.{prio}"
    # "all" uses the base query without extra filters
    base += f"&order=priority.asc,created_at.asc&limit={BULK_CAP}&select=*"
    return await _sb(client, "GET", base) or []


async def handle_bulk_approve(client, biz, action) -> Dict:
    filter_str = action.get("filter", "all")
    items = await _query_queue_by_filter(client, biz["id"], filter_str)
    if not items:
        return {"type": "bulk_approve", "result": "no matching drafts", "label": "Bulk approve", "nav": None}
    approved: List[str] = []
    sent_count = 0
    no_email_count = 0
    failed_send_count = 0
    for item in items:
        delivery = await _do_approve_one(client, biz, item)
        if delivery.get("ok"):
            approved.append(item.get("subject") or item.get("id"))
            if delivery.get("sent"):
                sent_count += 1
            elif delivery.get("reason") == "no_email" or delivery.get("reason") == "no_contact":
                no_email_count += 1
            elif (delivery.get("reason") or "").startswith("exception:"):
                failed_send_count += 1
    total_matching_note = f" (capped at {BULK_CAP})" if len(items) == BULK_CAP else ""
    breakdown = []
    if sent_count:        breakdown.append(f"{sent_count} sent")
    if no_email_count:    breakdown.append(f"{no_email_count} no email")
    if failed_send_count: breakdown.append(f"{failed_send_count} delivery failed")
    breakdown_str = f" — {', '.join(breakdown)}" if breakdown else ""
    return {
        "type": "bulk_approve",
        "result": f"approved {len(approved)} of {len(items)}{total_matching_note}{breakdown_str}",
        "label": f"📧 Bulk approved {len(approved)} draft{'s' if len(approved) != 1 else ''}{breakdown_str}",
        "nav": _nav("operate", "queue"),
        "items": approved[:10],
        "sent_count": sent_count,
    }


async def handle_bulk_dismiss(client, biz, action) -> Dict:
    filter_str = action.get("filter", "all")
    items = await _query_queue_by_filter(client, biz["id"], filter_str)
    if not items:
        return {"type": "bulk_dismiss", "result": "no matching drafts", "label": "Bulk dismiss", "nav": None}
    now_iso = datetime.now(timezone.utc).isoformat()
    dismissed = []
    for item in items:
        qid = item.get("id")
        if qid:
            await _sb(client, "PATCH", f"/agent_queue?id=eq.{qid}", {
                "status": "dismissed", "reviewed_at": now_iso,
            })
            dismissed.append(item.get("subject") or qid)
    return {
        "type": "bulk_dismiss",
        "result": f"dismissed {len(dismissed)} of {len(items)}",
        "label": f"Bulk dismissed {len(dismissed)} draft{'s' if len(dismissed) != 1 else ''}",
        "nav": _nav("operate", "queue"),
    }


# ═══════════════════════════════════════════════════════════════════════
# DEEP CONTACT INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════

async def handle_contact_deep_dive(client, biz, action) -> Dict:
    contact_id = action.get("contact_id")
    contact = await _validate_contact(client, biz["id"], contact_id)
    if not contact:
        return _fail("contact_deep_dive", f"Contact {contact_id} not found")

    # Parallel data pull
    ev_task = _sb(client, "GET",
        f"/events?contact_id=eq.{contact_id}&business_id=eq.{biz['id']}"
        f"&order=created_at.desc&limit=50&select=event_type,data,source,created_at")
    q_task = _sb(client, "GET",
        f"/agent_queue?contact_id=eq.{contact_id}&business_id=eq.{biz['id']}"
        f"&order=created_at.desc&limit=20"
        f"&select=id,agent,action_type,subject,body,status,priority,created_at")
    s_task = _sb(client, "GET",
        f"/sessions?contact_id=eq.{contact_id}&business_id=eq.{biz['id']}"
        f"&order=scheduled_for.desc&limit=10"
        f"&select=id,title,session_type,status,scheduled_for,duration_minutes,notes")
    me_task = _sb(client, "GET",
        f"/module_entries?business_id=eq.{biz['id']}&status=eq.active"
        f"&data->>contact_id=eq.{contact_id}&order=created_at.desc&limit=10"
        f"&select=id,module_id,data,created_at")

    events, queue_history, sessions, module_entries = await asyncio.gather(
        ev_task, q_task, s_task, me_task
    )

    return {
        "type": "contact_deep_dive",
        "result": "data retrieved",
        "label": f"Deep dive: {contact.get('name')}",
        "nav": _nav("operate", "contacts", contact_id),
        "contact": contact,
        "events": (events or [])[:50],
        "queue_history": (queue_history or [])[:20],
        "sessions": (sessions or [])[:10],
        "module_entries": (module_entries or [])[:10],
    }


async def handle_ensure_module(client, biz, action) -> Dict:
    """Find or create a module by name. Used for auto-creating Blog, Testimonials, etc."""
    name = (action.get("module_name") or "").strip()
    if not name:
        return _fail("ensure_module", "module_name required")

    existing = await _sb(client, "GET",
        f"/custom_modules?business_id=eq.{biz['id']}&name=eq.{name}&is_active=eq.true&limit=1&select=id,name")
    if existing:
        return {
            "type": "ensure_module",
            "result": "already exists",
            "label": f"Module: {name}",
            "module_id": existing[0]["id"],
            "nav": None,
        }

    # Build a minimal schema
    schema = action.get("schema") or {
        "fields": [
            {"name": "title", "type": "text", "label": "Title", "required": True},
            {"name": "body", "type": "textarea", "label": "Content"},
            {"name": "status", "type": "select", "label": "Status", "options": ["draft", "published", "archived"]},
            {"name": "featured", "type": "checkbox", "label": "Featured"},
            {"name": "contact_id", "type": "contact_link", "label": "Related Contact"},
        ],
        "default_sort": "created_at",
        "default_view": "list",
        "views": ["list"],
    }

    icon = action.get("icon") or "📝"
    slug = name.lower().replace(" ", "-").replace("'", "")[:60]
    enable_public = action.get("public_display_enabled", False)
    display_type = action.get("display_type", "list")

    inserted = await _sb(client, "POST", "/custom_modules", {
        "business_id": biz["id"],
        "name": name,
        "slug": slug,
        "description": action.get("description") or f"Auto-created {name} module",
        "icon": icon,
        "schema": schema,
        "agent_config": {"enabled": True, "triggers": []},
        "public_display": {
            "enabled": enable_public,
            "display_type": display_type,
            "title_override": name,
            "visible_fields": ["title", "body", "status"],
            "hidden_fields": ["contact_id"],
            "max_display": 20,
            "sort_by": "created_at",
        },
        "is_active": True,
    })
    if not inserted or not isinstance(inserted, list):
        return _fail("ensure_module", "creation failed")

    return {
        "type": "ensure_module",
        "result": "created",
        "label": f"Created module: {name}",
        "module_id": inserted[0]["id"],
        "nav": None,
    }


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
            "description": "Your offerings from the Strategy Track",
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

    biz_name = biz.get("name", "")
    biz_type = biz.get("type", "general")
    practitioner = (biz.get("settings") or {}).get("practitioner_name", "")
    voice = biz.get("voice_profile") or {}
    bm = track.get("business_model") or {}
    pricing = track.get("pricing_strategy") or {}
    packages = track.get("service_packages") or []

    system = (
        f"You are the Website Generator. Create a complete, professional single-page website "
        f"for \"{biz_name}\". Practitioner: {practitioner}. Type: {biz_type}. "
        f"Use the strategy-track data below to populate sections. Generate ONLY HTML with "
        f"embedded CSS — no markdown, no commentary. Mobile-responsive, modern, clean. "
        f"Google Fonts allowed."
    )
    user = json.dumps({
        "voice": voice,
        "value_proposition": bm.get("value_proposition"),
        "customer_segments": bm.get("customer_segments"),
        "pricing_tiers": pricing.get("tiers"),
        "service_packages": packages,
    })[:4000]

    html = await _call_claude(client, system, [{"role": "user", "content": f"Generate the site. Context:\n{user}"}], max_tokens=4096)
    if not html or "<html" not in html.lower():
        return
    # Strip fences if present
    if "```" in html:
        parts = html.split("```")
        for part in parts:
            if "<html" in part.lower():
                html = part.replace("html\n", "", 1).replace("html", "", 1) if part.lower().strip().startswith("html") else part
                break
    slug = "".join(c.lower() if c.isalnum() else "-" for c in biz_name).strip("-")[:60] or "site"
    await _sb(client, "POST", "/business_sites", {
        "business_id": biz_id, "html_content": html, "slug": slug, "status": "published",
    })


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

    return {
        "type": "complete_strategy_track",
        "result": "launched",
        "label": "Strategy Track complete — business is live",
        "nav": {"tab": "build", "page": "strategy-track"},
        "products_module_id": module_id,
    }


# ═══════════════════════════════════════════════════════════════════════
# PHASE-2 HANDLERS — tasks, notes, activity log, invoices
# ═══════════════════════════════════════════════════════════════════════


async def handle_create_task(client, biz, action) -> Dict:
    title = (action.get("title") or "").strip()
    if not title:
        return _fail("create_task", "title required")
    priority = (action.get("priority") or "medium").lower()
    if priority not in ("urgent", "high", "medium", "low"):
        priority = "medium"
    due_date = action.get("due_date") or None
    if due_date and len(str(due_date)) > 10:
        due_date = str(due_date)[:10]  # YYYY-MM-DD

    payload = {
        "business_id": biz["id"],
        "title": title,
        "description": action.get("description") or None,
        "status": "todo",
        "priority": priority,
        "due_date": due_date,
    }
    # Optional contact link — validate when provided so we don't poison the FK
    contact_id = action.get("contact_id")
    if contact_id:
        contact = await _validate_contact(client, biz["id"], contact_id)
        if contact:
            payload["contact_id"] = contact["id"]
    if action.get("project_id"):
        payload["project_id"] = action["project_id"]

    inserted = await _sb(client, "POST", "/tasks", payload)
    if not inserted:
        return _fail("create_task", "insert failed")
    row = inserted[0] if isinstance(inserted, list) else inserted
    return {
        "type": "create_task",
        "result": "added",
        "label": f"✅ Task: {title}" + (f" — due {due_date}" if due_date else ""),
        "nav": {"tab": "operate", "sub": "tasks"},
        "task_id": row.get("id") if isinstance(row, dict) else None,
    }


async def handle_complete_task(client, biz, action) -> Dict:
    task_id = action.get("task_id")
    title_hint = (action.get("title") or "").strip()

    if not task_id and title_hint:
        # Fuzzy match on title within this business's open tasks
        rows = await _sb(client, "GET",
            f"/tasks?business_id=eq.{biz['id']}&status=neq.done"
            f"&select=id,title&limit=50") or []
        hint = title_hint.lower()
        best = next((r for r in rows if hint in (r.get("title") or "").lower()), None)
        if not best:
            return _fail("complete_task", f"no open task matches '{title_hint}'")
        task_id = best["id"]

    if not task_id:
        return _fail("complete_task", "task_id or title required")

    await _sb(client, "PATCH", f"/tasks?id=eq.{task_id}&business_id=eq.{biz['id']}", {
        "status": "done",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    })
    return {
        "type": "complete_task",
        "result": "completed",
        "label": f"✓ Task completed",
        "nav": {"tab": "operate", "sub": "tasks"},
    }


async def handle_create_note(client, biz, action) -> Dict:
    note = (action.get("note") or action.get("content") or "").strip()
    contact_id = action.get("contact_id")
    if not note:
        return _fail("create_note", "note text required")
    if not contact_id:
        return _fail("create_note", "contact_id required")
    contact = await _validate_contact(client, biz["id"], contact_id)
    if not contact:
        return _fail("create_note", f"Contact {contact_id} not found")

    await _sb(client, "POST", "/events", {
        "business_id": biz["id"],
        "contact_id": contact["id"],
        "event_type": "contact_note",
        "data": {"note": note[:5000]},
        "source": "chief_of_staff",
    })
    return {
        "type": "create_note",
        "result": "saved",
        "label": f"📝 Note on {contact.get('name')}: {note[:60]}",
        "nav": _nav("operate", "contacts", contact["id"]),
    }


VALID_ACTIVITY_TYPES = {"call", "text", "meeting", "email", "other"}


async def handle_log_activity(client, biz, action) -> Dict:
    contact_id = action.get("contact_id")
    activity_type = (action.get("activity_type") or "other").lower()
    if activity_type not in VALID_ACTIVITY_TYPES:
        activity_type = "other"
    notes = (action.get("notes") or "").strip()
    if not contact_id:
        return _fail("log_activity", "contact_id required")
    contact = await _validate_contact(client, biz["id"], contact_id)
    if not contact:
        return _fail("log_activity", f"Contact {contact_id} not found")

    occurred_at = action.get("occurred_at") or datetime.now(timezone.utc).date().isoformat()
    await _sb(client, "POST", "/events", {
        "business_id": biz["id"],
        "contact_id": contact["id"],
        "event_type": "activity_logged",
        "data": {
            "activity_type": activity_type,
            "notes": notes[:5000],
            "occurred_at": occurred_at,
        },
        "source": "chief_of_staff",
    })
    # Bump last_interaction on the contact
    await _sb(client, "PATCH", f"/contacts?id=eq.{contact['id']}", {
        "last_interaction": datetime.now(timezone.utc).isoformat(),
    })
    label_map = {"call": "📞 Call", "text": "💬 Text", "meeting": "🤝 Meeting", "email": "✉ Email", "other": "• Activity"}
    return {
        "type": "log_activity",
        "result": "logged",
        "label": f"{label_map[activity_type]} with {contact.get('name')}",
        "nav": _nav("operate", "contacts", contact["id"]),
    }


async def _next_invoice_number(client, biz_id: str) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"INV-{year}-"
    # Ascii-percent-encoded wildcard for PostgREST
    rows = await _sb(client, "GET",
        f"/invoices?business_id=eq.{biz_id}&invoice_number=like.{prefix}%25"
        f"&select=invoice_number&order=invoice_number.desc&limit=1") or []
    if rows and rows[0].get("invoice_number"):
        try:
            n = int(str(rows[0]["invoice_number"]).split("-")[-1]) + 1
        except (ValueError, IndexError):
            n = 1
    else:
        n = 1
    return f"{prefix}{n:03d}"


async def handle_create_invoice(client, biz, action) -> Dict:
    contact_id = action.get("contact_id")
    if not contact_id:
        return _fail("create_invoice", "contact_id required")
    contact = await _validate_contact(client, biz["id"], contact_id)
    if not contact:
        return _fail("create_invoice", f"Contact {contact_id} not found")

    items_in = action.get("items") or []
    if not isinstance(items_in, list) or not items_in:
        return _fail("create_invoice", "items (list) required")

    norm_items: List[Dict[str, Any]] = []
    subtotal = 0.0
    for raw in items_in:
        if not isinstance(raw, dict):
            continue
        desc = str(raw.get("description") or "").strip()
        qty = float(raw.get("quantity") or 1)
        price = float(raw.get("unit_price") or raw.get("price") or 0)
        total = round(qty * price, 2)
        subtotal += total
        norm_items.append({
            "description": desc or "Line item",
            "quantity": qty,
            "unit_price": price,
            "total": total,
        })
    subtotal = round(subtotal, 2)
    tax_rate = float(action.get("tax_rate") or 0)
    tax_amount = round(subtotal * tax_rate / 100, 2)
    total = round(subtotal + tax_amount, 2)

    settings = biz.get("settings") or {}
    stripe_link = (settings.get("payments") or {}).get("stripe_link")

    invoice_number = action.get("invoice_number") or await _next_invoice_number(client, biz["id"])
    due_date = action.get("due_date")
    if not due_date:
        due_date = (datetime.now(timezone.utc).date() + timedelta(days=14)).isoformat()

    inserted = await _sb(client, "POST", "/invoices", {
        "business_id": biz["id"],
        "contact_id": contact["id"],
        "invoice_number": invoice_number,
        "status": "draft",
        "items": norm_items,
        "subtotal": subtotal,
        "tax_rate": tax_rate,
        "tax_amount": tax_amount,
        "total": total,
        "currency": action.get("currency") or "USD",
        "due_date": due_date,
        "notes": action.get("notes") or None,
        "stripe_payment_url": stripe_link,
    })
    if not inserted:
        return _fail("create_invoice", "insert failed")
    row = inserted[0] if isinstance(inserted, list) else inserted

    return {
        "type": "create_invoice",
        "result": "drafted",
        "label": f"💰 Invoice {invoice_number} · {contact.get('name')} · ${total:,.2f}",
        "nav": {"tab": "operate", "sub": "invoices"},
        "invoice_id": row.get("id") if isinstance(row, dict) else None,
        "invoice_number": invoice_number,
        "total": total,
    }


async def _send_invoice_email(
    client, biz: Dict, invoice: Dict, contact: Dict
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Compose an invoice HTML email and ship it via Resend.

    Returns (ok, error_detail, provider_id).
    - ok = True only when Resend returned 2xx
    - error_detail is populated on failure so the caller can surface WHY
    - provider_id is the Resend message id on success
    """
    if not contact.get("email"):
        return False, "contact has no email on file", None

    settings = biz.get("settings") or {}
    brand = (settings.get("brand_kit") or {})
    sig = ((settings.get("email_templates") or {}).get("signature") or {})
    primary = (brand.get("colors") or {}).get("primary") or "#C8973E"
    biz_name = biz.get("name") or "your business"
    stripe_link = invoice.get("stripe_payment_url") or (settings.get("payments") or {}).get("stripe_link")
    total = float(invoice.get("total") or 0)
    total_fmt = f"${total:,.2f}"

    line_rows = "".join(
        f'<tr><td style="padding:10px 0;border-bottom:1px solid #eee;">{it.get("description","")}</td>'
        f'<td style="padding:10px 0;border-bottom:1px solid #eee;text-align:right;color:#666;">× {it.get("quantity",0)}</td>'
        f'<td style="padding:10px 0;border-bottom:1px solid #eee;text-align:right;color:#666;">${it.get("unit_price",0):.2f}</td>'
        f'<td style="padding:10px 0;border-bottom:1px solid #eee;text-align:right;font-weight:600;">${it.get("total",0):.2f}</td></tr>'
        for it in (invoice.get("items") or [])
    )

    # Payment CTA — prominent Pay Now button when Stripe is configured,
    # else a fallback note so the contact knows what to do.
    if stripe_link:
        payment_block = (
            f'<div style="text-align:center;margin:28px 0;">'
            f'<a href="{stripe_link}" '
            f'style="display:inline-block;padding:14px 32px;background:{primary};'
            f'color:#fff;text-decoration:none;border-radius:8px;font-size:16px;'
            f'font-weight:bold;margin-top:20px;">Pay Now — {total_fmt}</a>'
            f'</div>'
        )
    else:
        payment_block = (
            f'<div style="margin:24px 0;padding:14px 16px;background:#f9f7f2;'
            f'border-left:3px solid {primary};border-radius:0 6px 6px 0;'
            f'font-size:13px;color:#666;line-height:1.6;">'
            f'Please reply to this email for payment arrangements.'
            f'</div>'
        )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f5f3ef;font-family:Arial,sans-serif;color:#333;">
<div style="max-width:600px;margin:0 auto;background:#fff;padding:32px;">
  <div style="display:flex;justify-content:space-between;margin-bottom:24px;">
    <div style="font-size:20px;font-weight:700;color:{primary};">{biz_name}</div>
    <div style="text-align:right;">
      <div style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#999;">INVOICE</div>
      <div style="font-size:16px;font-weight:700;color:{primary};">{invoice.get("invoice_number","")}</div>
    </div>
  </div>
  <p style="font-size:14px;line-height:1.6;color:#333;">Hi {contact.get("name") or "there"},</p>
  <p style="font-size:14px;line-height:1.6;color:#333;">Please find your invoice below.
  {f'Payment is due by <strong>{invoice.get("due_date")}</strong>.' if invoice.get("due_date") else ''}</p>
  <table style="width:100%;border-collapse:collapse;margin:20px 0;font-size:14px;">
    <thead><tr style="border-bottom:2px solid {primary};">
      <th style="text-align:left;padding:10px 0;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#999;">Item</th>
      <th style="text-align:right;padding:10px 0;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#999;">Qty</th>
      <th style="text-align:right;padding:10px 0;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#999;">Price</th>
      <th style="text-align:right;padding:10px 0;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#999;">Total</th>
    </tr></thead>
    <tbody>{line_rows}</tbody>
    <tfoot>
      <tr><td colspan="3" style="text-align:right;padding:12px;font-weight:700;font-size:16px;">TOTAL</td>
          <td style="text-align:right;padding:12px 0;font-weight:700;font-size:18px;color:{primary};">{total_fmt}</td></tr>
    </tfoot>
  </table>
  {payment_block}
  {f'<p style="margin-top:24px;padding:14px;background:#f9f7f2;border-left:3px solid {primary};font-size:13px;color:#666;line-height:1.6;font-style:italic;">{invoice.get("notes","")}</p>' if invoice.get("notes") else ''}
  <p style="font-size:13px;color:#666;margin-top:24px;">Thank you,<br/><strong>{sig.get("name") or biz_name}</strong></p>
</div>
</body></html>"""

    # Actual delivery. Keep try/except narrow — we want Resend's real error
    # surfaced, not replaced with a generic "delivery failed".
    try:
        from email_sender import send_via_resend
        data = await send_via_resend(
            to_email=contact["email"],
            to_name=contact.get("name"),
            from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
            from_name=sig.get("name") or biz_name,
            subject=f"Invoice {invoice.get('invoice_number')} from {biz_name}",
            body=html,
            reply_to=sig.get("email"),
        )
        provider_id = data.get("id") if isinstance(data, dict) else None
        return True, None, provider_id
    except RuntimeError as e:
        # send_via_resend raises RuntimeError on non-2xx with the Resend
        # response body attached — propagate the full message.
        return False, f"Resend refused: {e}", None
    except Exception as e:  # pragma: no cover
        return False, f"unexpected error: {type(e).__name__}: {e}", None


async def handle_send_invoice(client, biz, action) -> Dict:
    invoice_id = action.get("invoice_id")
    if not invoice_id:
        return _fail("send_invoice", "invoice_id required")
    rows = await _sb(client, "GET",
        f"/invoices?id=eq.{invoice_id}&business_id=eq.{biz['id']}&limit=1&select=*")
    if not rows:
        return _fail("send_invoice", f"Invoice {invoice_id} not found")
    invoice = rows[0]
    if not invoice.get("contact_id"):
        return _fail("send_invoice", "invoice has no linked contact")
    contact = await _validate_contact(client, biz["id"], invoice["contact_id"])
    if not contact:
        return _fail("send_invoice", "contact not found")
    if not contact.get("email"):
        return _fail("send_invoice", f"{contact.get('name')} has no email on file")

    # Backfill the invoice's stripe_payment_url from settings on the fly
    # in case the invoice was created before the link was configured.
    settings = biz.get("settings") or {}
    current_stripe_on_invoice = invoice.get("stripe_payment_url")
    stripe_from_settings = (settings.get("payments") or {}).get("stripe_link")
    if not current_stripe_on_invoice and stripe_from_settings:
        await _sb(client, "PATCH", f"/invoices?id=eq.{invoice_id}", {
            "stripe_payment_url": stripe_from_settings,
        })
        invoice["stripe_payment_url"] = stripe_from_settings

    ok, error_detail, provider_id = await _send_invoice_email(client, biz, invoice, contact)
    print(f"[Chief] Invoice send result: ok={ok} invoice={invoice.get('invoice_number')} "
          f"to={contact.get('email')} provider_id={provider_id} error={error_detail}", flush=True)
    logger.info(
        f"invoice send → ok={ok} invoice={invoice.get('invoice_number')} "
        f"to={contact.get('email')} provider_id={provider_id} error={error_detail}"
    )

    if not ok:
        # Log the failure event so it shows on the contact timeline instead
        # of silently disappearing.
        await _sb(client, "POST", "/events", {
            "business_id": biz["id"],
            "contact_id": contact["id"],
            "event_type": "invoice_send_failed",
            "data": {
                "invoice_id": invoice_id,
                "invoice_number": invoice.get("invoice_number"),
                "total": invoice.get("total"),
                "to_email": contact.get("email"),
                "error": error_detail or "unknown",
            },
            "source": "chief_of_staff",
        })
        return _fail(
            "send_invoice",
            f"Invoice {invoice.get('invoice_number')} send failed — {error_detail or 'unknown error'}",
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    await _sb(client, "PATCH", f"/invoices?id=eq.{invoice_id}", {
        "status": "sent", "sent_at": now_iso,
    })
    await _sb(client, "POST", "/events", {
        "business_id": biz["id"],
        "contact_id": contact["id"],
        "event_type": "invoice_sent",
        "data": {
            "invoice_id": invoice_id,
            "invoice_number": invoice.get("invoice_number"),
            "total": invoice.get("total"),
            "to_email": contact.get("email"),
            "provider_id": provider_id,
            "has_stripe_link": bool(invoice.get("stripe_payment_url")),
        },
        "source": "chief_of_staff",
    })
    return {
        "type": "send_invoice",
        "result": "sent",
        "label": f"📧 Invoice {invoice.get('invoice_number')} sent to {contact.get('name')} ({contact.get('email')})",
        "nav": {"tab": "operate", "sub": "invoices"},
        "email_sent": True,
        "provider_id": provider_id,
    }


async def handle_mark_invoice_paid(client, biz, action) -> Dict:
    invoice_id = action.get("invoice_id")
    if not invoice_id:
        return _fail("mark_invoice_paid", "invoice_id required")
    rows = await _sb(client, "GET",
        f"/invoices?id=eq.{invoice_id}&business_id=eq.{biz['id']}&limit=1&select=*")
    if not rows:
        return _fail("mark_invoice_paid", f"Invoice {invoice_id} not found")
    invoice = rows[0]
    now_iso = datetime.now(timezone.utc).isoformat()
    await _sb(client, "PATCH", f"/invoices?id=eq.{invoice_id}", {
        "status": "paid",
        "paid_at": now_iso,
        "payment_method": action.get("payment_method") or None,
    })
    if invoice.get("contact_id"):
        await _sb(client, "POST", "/events", {
            "business_id": biz["id"],
            "contact_id": invoice["contact_id"],
            "event_type": "invoice_paid",
            "data": {
                "invoice_id": invoice_id,
                "invoice_number": invoice.get("invoice_number"),
                "total": invoice.get("total"),
            },
            "source": "chief_of_staff",
        })
    return {
        "type": "mark_invoice_paid",
        "result": "marked paid",
        "label": f"💵 Invoice {invoice.get('invoice_number')} marked paid — ${float(invoice.get('total') or 0):,.2f}",
        "nav": {"tab": "operate", "sub": "invoices"},
    }


ACTION_HANDLERS = {
    "draft_nurture":         handle_draft_nurture,
    "draft_email":           handle_draft_email,
    "draft_and_send":        handle_draft_and_send,
    "create_session":        handle_create_session,
    "update_contact_status": handle_update_contact_status,
    "update_contact_health": handle_update_contact_health,
    "run_agent":             handle_run_agent,
    "create_module_entry":   handle_create_module_entry,
    "create_contact":        handle_create_contact,
    "generate_briefing":     handle_generate_briefing,
    "generate_insights":     handle_generate_insights,
    "navigate":              handle_navigate,
    "remember":              handle_remember,
    "forget":                handle_forget,
    "approve_draft":         handle_approve_draft,
    "dismiss_draft":         handle_dismiss_draft,
    "edit_draft":            handle_edit_draft,
    "rewrite_draft":         handle_rewrite_draft,
    "bulk_approve":          handle_bulk_approve,
    "bulk_dismiss":          handle_bulk_dismiss,
    "contact_deep_dive":     handle_contact_deep_dive,
    "ensure_module":         handle_ensure_module,
    # Strategy Track
    "save_phase":                 handle_save_phase,
    "advance_phase":              handle_advance_phase,
    "run_market_research":        handle_run_market_research,
    "save_business_model":        handle_save_business_model,
    "save_pricing":               handle_save_pricing,
    "save_packages":              handle_save_packages,
    "save_projections":           handle_save_projections,
    "save_swot":                  handle_save_swot,
    "save_launch_plan":           handle_save_launch_plan,
    "session_summary":            handle_session_summary,
    "complete_strategy_track":    handle_complete_strategy_track,
    # Phase-2 operations
    "create_task":                handle_create_task,
    "complete_task":              handle_complete_task,
    "create_note":                handle_create_note,
    "log_activity":               handle_log_activity,
    "create_invoice":             handle_create_invoice,
    "send_invoice":               handle_send_invoice,
    "mark_invoice_paid":          handle_mark_invoice_paid,
}


async def _mark_referenced_memories(client, biz_id: str, memories: List[Dict], response_text: str) -> None:
    """Best-effort: PATCH last_referenced_at for memories whose distinctive
    words appear in the AI response. Runs after the response — non-blocking."""
    if not memories or not response_text:
        return
    response_lower = response_text.lower()
    referenced_ids: List[str] = []
    for m in memories:
        sig = _memory_signature(m.get("content") or "")
        if len(sig) < 2:
            continue
        # Pick the 3 longest tokens (most distinctive)
        top = sorted(sig, key=len, reverse=True)[:3]
        if all(tok in response_lower for tok in top):
            referenced_ids.append(m["id"])
    if not referenced_ids:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    # PATCH each — small batch, fire-and-forget
    await asyncio.gather(*[
        _sb(client, "PATCH", f"/chief_memories?id=eq.{mid}", {"last_referenced_at": now_iso})
        for mid in referenced_ids
    ], return_exceptions=True)


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
# CURRENT-VIEW DETAIL FETCH
# ═══════════════════════════════════════════════════════════════════════

async def _fetch_view_detail(client, biz_id: str, view: Optional[CurrentContext]) -> Dict[str, Any]:
    """Pull the specific entity the practitioner is looking at, plus recent
    related rows. Returns an empty dict when nothing is being viewed."""
    if not view:
        return {}

    out: Dict[str, Any] = {"tab": view.tab, "sub_tab": view.sub_tab}
    tasks = []

    if view.viewing_contact_id:
        tasks.append(("contact", _sb(client, "GET",
            f"/contacts?id=eq.{view.viewing_contact_id}&business_id=eq.{biz_id}"
            f"&limit=1&select=*")))
        tasks.append(("contact_queue", _sb(client, "GET",
            f"/agent_queue?contact_id=eq.{view.viewing_contact_id}&business_id=eq.{biz_id}"
            f"&order=created_at.desc&limit=5"
            f"&select=agent,action_type,subject,status,priority,created_at")))
        tasks.append(("contact_events", _sb(client, "GET",
            f"/events?contact_id=eq.{view.viewing_contact_id}&business_id=eq.{biz_id}"
            f"&order=created_at.desc&limit=5&select=event_type,data,created_at")))

    if view.viewing_module_id:
        tasks.append(("module", _sb(client, "GET",
            f"/custom_modules?id=eq.{view.viewing_module_id}&business_id=eq.{biz_id}"
            f"&limit=1&select=*")))
        tasks.append(("module_entries", _sb(client, "GET",
            f"/module_entries?module_id=eq.{view.viewing_module_id}&status=eq.active"
            f"&order=updated_at.desc&limit=10&select=id,data,updated_at")))

    if view.viewing_session_id:
        tasks.append(("session", _sb(client, "GET",
            f"/sessions?id=eq.{view.viewing_session_id}&business_id=eq.{biz_id}"
            f"&limit=1&select=*,contacts(name)")))

    if not tasks:
        return out

    keys = [k for k, _ in tasks]
    results = await asyncio.gather(*[t for _, t in tasks])
    for k, v in zip(keys, results):
        out[k] = v

    return out


def _format_view_block(view: Optional[CurrentContext], detail: Dict[str, Any]) -> str:
    """Prominent 'CURRENTLY VIEWING' section for the system prompt."""
    if not view:
        return ""

    path_parts = []
    if view.tab: path_parts.append(view.tab.upper())
    if view.sub_tab: path_parts.append(view.sub_tab)
    path = " → ".join(path_parts) if path_parts else "(unknown)"

    lines = [f"CURRENTLY VIEWING: {path}"]

    contact_rows = detail.get("contact") or []
    if contact_rows:
        c = contact_rows[0]
        days = _days_since(c.get("last_interaction"))
        lines.append(
            f"  CONTACT: {c.get('name')} [id={c.get('id')}]"
            f" · status={c.get('status')} · health={c.get('health_score')}"
            f" · lead_score={c.get('lead_score')}"
            f" · last_interaction={f'{days}d ago' if days is not None else 'never'}"
        )
        if c.get("role"):
            lines.append(f"    role: {c.get('role')}")
        if c.get("email"):
            lines.append(f"    email: {c.get('email')}")

        queue = detail.get("contact_queue") or []
        if queue:
            lines.append(f"    Recent queue items ({len(queue)}):")
            for q in queue[:5]:
                lines.append(
                    f"      - [{q.get('priority')}] {q.get('agent')}/{q.get('action_type')}: "
                    f"{q.get('subject') or '(no subject)'} · {q.get('status')}"
                )

        events = detail.get("contact_events") or []
        if events:
            lines.append(f"    Recent events ({len(events)}):")
            for ev in events[:5]:
                d = _days_since(ev.get("created_at"))
                lines.append(f"      - {d}d ago: {ev.get('event_type')}")

    module_rows = detail.get("module") or []
    if module_rows:
        m = module_rows[0]
        entries = detail.get("module_entries") or []
        lines.append(
            f"  MODULE: {m.get('name')} [id={m.get('id')}]"
            f" · {len(entries)} recent active entries"
        )
        if m.get("description"):
            lines.append(f"    description: {m.get('description')}")
        for e in entries[:5]:
            d = (e.get("data") or {})
            title = d.get("title") or d.get("deliverable_name") or d.get("name") or "(untitled)"
            status = d.get("status") or d.get((m.get("schema") or {}).get("board_column") or "") or ""
            lines.append(f"      - {title} [id={e.get('id')}]{f' · {status}' if status else ''}")

    session_rows = detail.get("session") or []
    if session_rows:
        s = session_rows[0]
        cname = (s.get("contacts") or {}).get("name") or ""
        lines.append(
            f"  SESSION: {s.get('title')} [id={s.get('id')}]"
            f" · {s.get('status')} · scheduled {s.get('scheduled_for', '')[:16]}"
            + (f" · with {cname}" if cname else "")
        )
        if s.get("notes"):
            lines.append(f"    notes: {str(s['notes'])[:200]}")

    lines.append("")
    lines.append("When the practitioner says 'him'/'her'/'this one'/'it'/'this contact'/'this entry',")
    lines.append("they are referring to the entity in CURRENTLY VIEWING above.")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT
# ═══════════════════════════════════════════════════════════════════════

STRATEGY_PHASE_LABELS = {
    "discovery": "Discovery — surface the idea, target audience, unique value, and practitioner background",
    "market_research": "Market Research — identify competitors, pricing, trends, and gaps",
    "business_model": "Business Model Canvas — nine sections built from discovery + research",
    "pricing_strategy": "Pricing Strategy — 2–3 tiers with rationale and competitor comparison",
    "service_packages": "Service Packages — concrete offerings (name, description, price, duration, format)",
    "financial_projections": "Financial Projections — conservative/realistic/optimistic scenarios + break-even",
    "swot": "SWOT Analysis — strengths, weaknesses, opportunities, threats",
    "launch_plan": "Launch Plan — week-by-week action items for the first 90 days",
}


def _format_strategy_block(biz: Dict[str, Any], track: Optional[Dict[str, Any]], mode: Optional[str] = None) -> str:
    settings = biz.get("settings") or {}
    track_mode = settings.get("track")
    if track_mode not in ("strategy", "launched"):
        return ""

    is_coach = mode == "strategy_coach"

    # Non-coach (normal Chief): stay in your lane and defer strategy questions.
    if not is_coach:
        hint = (
            "STRATEGY TRACK AWARENESS:\n"
            f"  The practitioner is on the Strategy Track (mode={track_mode})."
        )
        if track:
            current = track.get("current_phase") or "discovery"
            status = track.get("status", "in_progress")
            hint += f" Current phase: {current}. Status: {status}."
        hint += (
            "\n  You are the operational Chief of Staff — NOT the Strategy Coach."
            " If they ask deep business-planning questions (business model, pricing,"
            " market research, launch plan), acknowledge briefly and redirect:"
            " 'That's a Strategy Session question — let me open it for you.'"
            " Then emit [ACTION:{\"type\":\"navigate\",\"tab\":\"build\",\"page\":\"strategy-track\"}]"
            " so they land on the Strategy dashboard and can hit Continue Session."
            " Do NOT emit save_phase / save_pricing / save_packages / etc."
            " For operational questions (contacts, queue, agents, modules), answer normally."
        )
        return hint

    # Coach mode is handled by _build_coach_prompt; return empty here so the
    # main chief prompt doesn't double up.
    if not track:
        return "STRATEGY TRACK: practitioner is on the Strategy Track but no track row exists yet. Create one by emitting save_phase with phase=discovery once discovery is captured."

    current = track.get("current_phase") or "discovery"
    phases = track.get("phases") or {}

    # Which phases have deliverables?
    completed: List[str] = []
    for p in STRATEGY_PHASES:
        if p == "discovery":
            if phases.get("discovery"):
                completed.append(p)
        elif p == "service_packages":
            if track.get("service_packages"):
                completed.append(p)
        else:
            if track.get(p):
                completed.append(p)

    discovery = phases.get("discovery") or {}
    summary = discovery.get("summary") or "(not captured yet)"
    audience = discovery.get("target_audience") or "(not captured yet)"
    status_label = track.get("status", "in_progress")

    deliverable_preview = {
        "market_research": (track.get("market_research") or {}).get("gaps")
                            or ("got %d competitors" % len((track.get("market_research") or {}).get("competitors") or []) if (track.get("market_research") or {}).get("competitors") else ""),
        "business_model": (track.get("business_model") or {}).get("value_proposition"),
        "pricing_strategy": "%d tiers" % len((track.get("pricing_strategy") or {}).get("tiers") or []) if (track.get("pricing_strategy") or {}).get("tiers") else "",
        "service_packages": "%d packages" % len(track.get("service_packages") or []) if track.get("service_packages") else "",
        "financial_projections": "break-even @ %s" % ((track.get("financial_projections") or {}).get("break_even") or "?") if track.get("financial_projections") else "",
        "launch_plan": "%d weeks" % len((track.get("launch_plan") or {}).get("weeks") or []) if (track.get("launch_plan") or {}).get("weeks") else "",
    }
    preview_lines = [f"    - {k}: {v}" for k, v in deliverable_preview.items() if v]

    lines = [
        "STRATEGY TRACK STATUS:",
        f"  Track mode: {track_mode}",
        f"  Status: {status_label}",
        f"  Current phase: {current} — {STRATEGY_PHASE_LABELS.get(current, '')}",
        f"  Completed phases: {', '.join(completed) if completed else '(none)'}",
        f"  Business idea: {summary}",
        f"  Target audience: {audience}",
    ]
    if preview_lines:
        lines.append("  Deliverable previews:")
        lines.extend(preview_lines)

    lines.append("")
    lines.append("STRATEGY TRACK RULES:")
    lines.append(f"- You are guiding {biz.get('settings', {}).get('practitioner_name', 'the practitioner')} through launching their business in seven phases.")
    lines.append(f"- Current phase is '{current}'. Focus every turn on finishing this phase's deliverable.")
    lines.append("- Stay conversational — 6-10 exchanges per phase. Ask one focused question at a time, reference what they've already told you.")
    lines.append("- When you have enough for the phase deliverable, emit the corresponding save_* action, summarize what you captured, and ask if they're ready to advance.")
    lines.append("- Only advance the phase with [ACTION:advance_phase] AFTER the practitioner confirms they're ready.")
    lines.append("- Be encouraging but honest — if research or numbers show challenges, say so constructively.")
    lines.append("- Always tie recommendations back to data from earlier phases (reference their audience, their unique value, what the market showed).")
    lines.append("- When you reach launch_plan and they say they're ready to launch, emit [ACTION:complete_strategy_track] to configure the operational system.")
    lines.append("")
    lines.append("STRATEGY ACTIONS:")
    lines.append("  [ACTION:{\"type\":\"save_phase\",\"phase\":\"discovery\",\"data\":{\"summary\":\"...\",\"target_audience\":\"...\",\"unique_value_proposition\":\"...\",\"practitioner_background\":\"...\"}}]")
    lines.append("  [ACTION:{\"type\":\"run_market_research\",\"queries\":[\"<google-style query 1>\",\"<query 2>\",\"...\"]}]  — returns structured competitors/trends/gaps; use 5-10 queries")
    lines.append("  [ACTION:{\"type\":\"save_business_model\",\"canvas\":{\"customer_segments\":\"...\",\"value_proposition\":\"...\",\"channels\":\"...\",\"customer_relationships\":\"...\",\"revenue_streams\":\"...\",\"key_resources\":\"...\",\"key_activities\":\"...\",\"key_partners\":\"...\",\"cost_structure\":\"...\"}}]")
    lines.append("  [ACTION:{\"type\":\"save_pricing\",\"tiers\":[{\"name\":\"Starter\",\"price\":99,\"description\":\"...\",\"included\":[\"...\"]},...],\"rationale\":\"...\",\"comparison\":\"...\"}]")
    lines.append("  [ACTION:{\"type\":\"save_packages\",\"packages\":[{\"name\":\"...\",\"description\":\"...\",\"price\":\"$X\",\"duration\":\"...\",\"delivery_format\":\"...\",\"included\":[\"...\"]},...]}]")
    lines.append("  [ACTION:{\"type\":\"save_projections\",\"scenarios\":{\"conservative\":{\"clients\":X,\"monthly_revenue\":X,\"monthly_net\":X,\"notes\":\"...\"},\"realistic\":{...},\"optimistic\":{...}},\"expenses\":{...},\"break_even\":X}]")
    lines.append("  [ACTION:{\"type\":\"save_swot\",\"strengths\":\"...\",\"weaknesses\":\"...\",\"opportunities\":\"...\",\"threats\":\"...\"}]")
    lines.append("  [ACTION:{\"type\":\"save_launch_plan\",\"weeks\":[{\"week\":1,\"theme\":\"Setup\",\"actions\":[{\"description\":\"Set up your intake form\",\"system_link\":\"intake-forms\"},\"Announce on social\"]},...]}]")
    lines.append("     system_link values: strategy-track, my-site, brand, intake-forms, custom-modules, booking, social-media, link-page, resources, analytics, integrations, settings")
    lines.append("  [ACTION:{\"type\":\"advance_phase\",\"to\":\"market_research|business_model|pricing_strategy|service_packages|financial_projections|swot|launch_plan\"}]")
    lines.append("  [ACTION:{\"type\":\"complete_strategy_track\"}]  — emit ONLY after launch_plan is saved AND the practitioner confirms they want to launch")
    lines.append("")
    lines.append("GREETING (strategy): lead with the current phase. Mention what's left in this phase, offer the next question or suggestion, and ask ONE thing.")
    return "\n".join(lines)


def _build_system_prompt(ctx: Dict[str, Any], is_greeting: bool,
                         view: Optional[CurrentContext] = None,
                         view_detail: Optional[Dict] = None,
                         time_of_day: Optional[str] = None,
                         resume_note: Optional[ResumeNote] = None,
                         mode: Optional[str] = None) -> str:
    # Strategy Coach mode is a different persona entirely.
    if mode == "strategy_coach":
        return _build_coach_prompt(ctx, is_greeting, resume_note=resume_note)

    biz = ctx.get("business") or {}
    biz_name = biz.get("name", "the business")
    practitioner = (biz.get("settings") or {}).get("practitioner_name", "the practitioner")
    voice = biz.get("voice_profile") or {}

    context_block = _format_context_for_prompt(ctx)
    view_block = _format_view_block(view, view_detail or {})
    strategy_block = _format_strategy_block(biz, ctx.get("strategy_track"), mode=mode)

    # Time-of-day tailoring for greeting
    tod_guidance = ""
    if time_of_day == "morning":
        tod_guidance = f" Start with 'Good morning, {practitioner}.' Focus on what to prioritize TODAY."
    elif time_of_day == "afternoon":
        tod_guidance = f" Start with 'Good afternoon.' Focus on what's still pending from the morning."
    elif time_of_day == "evening":
        tod_guidance = f" Start with 'Evening, {practitioner}.' Focus on what happened today and what carries to tomorrow."
    elif time_of_day == "night":
        tod_guidance = f" Start with 'Hey {practitioner}.' Keep it very brief — just the one most important thing."

    # Resumed conversation context
    resume_clause = ""
    if resume_note and resume_note.gap_minutes and resume_note.gap_minutes > 0:
        gap_str = (f"{resume_note.gap_minutes}m" if resume_note.gap_minutes < 60
                   else f"{round(resume_note.gap_minutes / 60, 1)}h")
        changes = resume_note.changes_summary or "nothing notable changed"
        resume_clause = f"""

CONVERSATION RESUMED: The practitioner last spoke with you {gap_str} ago. Since then: {changes}.
Pick up naturally — don't re-introduce yourself. If they reference something from earlier, you have the full conversation history."""

    greeting_clause = ""
    if is_greeting:
        greeting_clause = f"""

OPENING GREETING MODE:
This is your first turn in a fresh conversation. Give a concise briefing (2-4 sentences) based on the most important things in the data RIGHT NOW.{tod_guidance} Lead with what needs attention. If there are pending drafts, mention the count. If there are at-risk contacts, name one. If there's an unread insight worth flagging, reference it. End with ONE question or a specific proactive suggestion. Do NOT just say "how can I help" — give them a real read on their business. Do NOT emit actions in the greeting (including navigate)."""

    return f"""You are the Chief of Staff for {biz_name}. You are {practitioner}'s operational partner — you see everything happening in their business and help them manage it through conversation.

REAL-TIME BUSINESS DATA (fresh every message):

{context_block}
{view_block}
{strategy_block}

YOU ARE THE CENTRAL ORCHESTRATOR. ALL agent operations flow through you. The practitioner never needs to interact with agents directly. When they want something done, you decide which agent handles it and trigger it. When agents create drafts, you show the results. When the practitioner wants to approve, edit, or dismiss, you handle it. You are the single point of contact for the entire system.

ACTION FORMAT — embed JSON inside [ACTION:...] tags. The system strips them before display and executes them.

ACTIONS — AGENTS (batch or targeted):
  [ACTION:{{"type":"run_agent","agent":"nurture|session_prep|session_follow|session_no_show|contract|payment|module|briefing|insights"}}]
  [ACTION:{{"type":"run_agent","agent":"nurture","target_contact_id":"<uuid>"}}]   — targeted, returns draft content
  [ACTION:{{"type":"run_agent","agent":"contract","target_contact_id":"<uuid>"}}]  — targeted proposal
  [ACTION:{{"type":"run_agent","agent":"session","sub":"prep","target_contact_id":"<uuid>"}}]

ACTIONS — QUEUE MANAGEMENT:
  [ACTION:{{"type":"approve_draft","queue_id":"<uuid from QUEUE>"}}]
  [ACTION:{{"type":"approve_draft","queue_id":"latest"}}]  — approves the most recent draft for this business; use when they say "approve it"/"send it" right after you drafted something
  [ACTION:{{"type":"dismiss_draft","queue_id":"<uuid>"}}]
  [ACTION:{{"type":"edit_draft","queue_id":"<uuid>","new_body":"rewritten text"}}]  — edit + approve in one step
  [ACTION:{{"type":"rewrite_draft","queue_id":"<uuid>","instruction":"make it warmer"}}]  — AI rewrites, does NOT auto-approve
  [ACTION:{{"type":"bulk_approve","filter":"all|agent:nurture|priority:low"}}]  — cap 20
  [ACTION:{{"type":"bulk_dismiss","filter":"priority:low"}}]  — cap 20

ACTIONS — CONTACTS + SESSIONS + MODULES:
  [ACTION:{{"type":"draft_nurture","contact_id":"<uuid>","reason":"why"}}]
  [ACTION:{{"type":"draft_email","contact_id":"<uuid>","subject":"...","reason":"..."}}]
  [ACTION:{{"type":"draft_and_send","contact_id":"<uuid>","subject":"...","body":"..."}}]  — Draft an email AND immediately approve + send it. Use when the practitioner wants to send right away without reviewing.
  [ACTION:{{"type":"create_session","contact_id":"<uuid>","title":"...","scheduled_for":"2026-04-20T14:00:00Z"}}]
  [ACTION:{{"type":"update_contact_status","contact_id":"<uuid>","new_status":"active|lead|vip|inactive|churned"}}]
  [ACTION:{{"type":"update_contact_health","contact_id":"<uuid>","health_score":75}}]
  [ACTION:{{"type":"create_contact","name":"...","email":"...","status":"lead"}}]
  [ACTION:{{"type":"create_module_entry","module_id":"<uuid>","data":{{...}}}}]
  [ACTION:{{"type":"contact_deep_dive","contact_id":"<uuid>"}}]  — returns full history/events/sessions/queue

ACTIONS — TASKS + NOTES + ACTIVITY:
  [ACTION:{{"type":"create_task","title":"Call Deacon Harris back","due_date":"2026-04-24","priority":"high","contact_id":"<uuid-optional>"}}]
  [ACTION:{{"type":"complete_task","task_id":"<uuid>"}}]
  [ACTION:{{"type":"complete_task","title":"call deacon"}}]  — fuzzy-matches an open task by title when you don't have the id
  [ACTION:{{"type":"create_note","contact_id":"<uuid>","note":"He's interested in leadership program"}}]
  [ACTION:{{"type":"log_activity","contact_id":"<uuid>","activity_type":"call|text|meeting|email|other","notes":"What happened","occurred_at":"2026-04-23"}}]

ACTIONS — INVOICES:
  [ACTION:{{"type":"create_invoice","contact_id":"<uuid>","items":[{{"description":"Coaching Session (60 min)","quantity":4,"unit_price":150}}],"due_date":"2026-04-30","notes":"Thanks!"}}]  — status='draft'; total auto-computed
  [ACTION:{{"type":"send_invoice","invoice_id":"<uuid from create_invoice>"}}]  — Resend-delivers the HTML invoice and flips status to 'sent'
  [ACTION:{{"type":"mark_invoice_paid","invoice_id":"<uuid>","payment_method":"stripe|check|cash"}}]

ACTIONS — NAVIGATION + MEMORY:
  [ACTION:{{"type":"navigate","tab":"operate|build|grow","sub":"dashboard|queue|contacts|projects|sessions|invoices|tasks|agents|briefing|health|insights","contact_id":"<uuid-optional>","page":"<page-id-optional>"}}]
  [ACTION:{{"type":"remember","category":"preference|pattern|context|decision|boundary|goal|standing_instruction|other","content":"...","importance":1-10}}]
  [ACTION:{{"type":"forget","memory_content":"snippet to deactivate"}}]
  [ACTION:{{"type":"generate_briefing"}}]
  [ACTION:{{"type":"generate_insights"}}]

RULES:
- Use EXACT UUIDs from CONTACT LOOKUP / CUSTOM MODULES / CURRENTLY VIEWING / QUEUE. Never invent IDs.
- Don't emit actions unless the practitioner asks or agrees. Emit at most {MAX_ACTIONS_PER_TURN} per turn.
- Confirm in plain language what you're doing. The system renders a card under your message.

NAVIGATION IS MANDATORY. "show me", "take me to", "open", "go to", "pull up", "let me see", or naming a contact/module/page → ALWAYS emit navigate. Don't describe — take them there. Panel stays open.

AGENT RESULTS — SHOW THE CONTENT:
When you run an agent (targeted) and get a draft_preview back, ALWAYS show the subject and body to the practitioner. Don't just say "I drafted something." Show it. Then ask: "Want to approve this, or should I change something?"
When you run a batch agent, summarize: "Nurture Agent drafted check-ins for 3 contacts: [names]. Want me to show each one, or approve them all?"

QUEUE TRIAGE PROTOCOL:
When the practitioner asks you to triage, walk through items one-by-one — urgent first. For each: show agent badge, contact name, subject, body excerpt, and your recommendation (approve / dismiss / edit). Ask for their decision. If they say "approve the rest," bulk-approve everything remaining.
Recommendations: base on contact health (lower = more urgent), time pending, whether the contact has been responsive, the practitioner's memories, and the priority level. Say things like "I'd send this one — his health is at 30" or "this can wait — she replied two days ago."

CONVERSATIONAL DRAFT EDITING:
When the practitioner says "make it shorter," "more personal," "change the tone" etc., use rewrite_draft with the instruction. Show the rewritten version. Ask if they want to approve. They can keep iterating.

DRAFT + APPROVE IN ONE TURN:
When the practitioner says "draft and send", "draft and approve", "send it now", "just send it", or any variant that signals they want the email to go out without review, use the combined action:
  [ACTION:{{"type":"draft_and_send","contact_id":"<uuid>","subject":"...","body":"..."}}]
This drafts, approves, and delivers via Resend in one step. Do NOT emit a separate draft_email + approve_draft pair in the same turn — you can't reference the draft's queue_id before it exists.

When the practitioner says "approve it", "send it", "looks good, ship it", or similar RIGHT AFTER you drafted something earlier in the conversation, emit:
  [ACTION:{{"type":"approve_draft","queue_id":"latest"}}]
The server resolves "latest" to the most recent draft for this business. Use this INSTEAD of trying to remember a UUID from a previous turn.

If the practitioner reviewed a specific draft in the queue and asks to approve THAT one, use its actual queue_id from the QUEUE block in the context — not "latest".

DEEP CONTACT INTELLIGENCE:
When asked "tell me about [contact]" or "what's the full story," use contact_deep_dive. You'll get their entire history. Narrate it as a RELATIONSHIP STORY, not a data dump. End with your assessment and a recommended next step.

MULTI-STEP WORKFLOWS:
When the practitioner gives a compound instruction ("onboard this person, schedule an intro, draft a welcome"), break it into steps. Emit multiple actions. Report after each step. Finish with a summary of everything done.

STANDING INSTRUCTIONS:
Check the STANDING INSTRUCTIONS section. If one matches the current context (day of week, time of day, recent events), execute it and tell the practitioner. When they set a new one ("from now on, always..."), capture with [ACTION:remember] using category="standing_instruction". Confirm by repeating the trigger and action.

MEMORY:
Always honor PRACTITIONER MEMORIES. If a memory conflicts with a request, point it out. When the practitioner states new preferences/patterns/boundaries/goals/decisions/context, capture with remember. When they retract, use forget. Importance: 9-10 hard rules, 7-8 strong prefs, 4-6 context, 1-3 nice-to-know.

NOTIFICATIONS:
Reference RECENT UNREAD NOTIFICATIONS when relevant. Mention un-read morning briefs, urgent alerts. Don't force it.

CONTENT & SITE INTELLIGENCE:
When the practitioner shares content-worthy information (sermon topic, event recap, fundraiser results, client success story, announcement), offer to publish it:
  - "Want me to create a blog post about that and put it on your site?"
  - Use ensure_module to auto-create a "Blog" module if needed, then create_module_entry with a title and AI-written body
When the practitioner mentions positive feedback from a contact, offer to add it as a testimonial:
  - "Sandra said your coaching changed her approach to leadership. Want me to add that as a testimonial on your site?"
  - Use ensure_module for "Testimonials" module, then create_module_entry
When the practitioner describes a specific event/campaign with dates and details, offer a micro-site:
  - "Want me to create a landing page for the marriage retreat? I'll include registration and all the details."
  - A micro-site is a separate entry in business_sites with site_config.type='micro'
For ensure_module: [ACTION:{{"type":"ensure_module","module_name":"Blog","icon":"📝","public_display_enabled":true,"display_type":"list"}}]
The ensure_module action creates the module if it doesn't exist, returns the module_id either way. Then use create_module_entry to add content.

TESTIMONIAL REQUEST FLOW:
After a session reaches status='completed' AND the follow-up draft for that contact is approved (visible in RECENT AGENT ACTIVITY), proactively offer:
  - "Session with Sarah went well and her follow-up is sent — want me to queue a testimonial ask 3 days out?"
If the practitioner agrees, draft it with the `testimonial_request` email template (under email_templates.templates.testimonial_request). Queue it as a draft in agent_queue with agent='testimonial', action_type='email', priority='low', and set `ai_reasoning` to `"Testimonial ask — post-session follow-up approved on <date>. Suggested send: 3 days from now."` so the practitioner can see the intended delay.
Do NOT auto-send. Leave it in the queue as a draft — the practitioner chooses when to approve.
When a practitioner mentions a contact replied with positive feedback ("Sandra wrote back with an amazing testimonial"), use ensure_module for "Testimonials" and create_module_entry with the quote + attribution. Offer to publish it on the site.

EMAIL TEMPLATES & SIGNATURE:
The practitioner has email templates and a signature saved at businesses.settings.email_templates. When drafting ANY email (draft_email / draft_nurture / proposal / follow-up / testimonial / re-engagement), always:
  - Use the matching template's subject + body as the starting point.
  - Substitute the variables: {{contact_name}}, {{business_name}}, {{practitioner_name}}, {{booking_url}}, {{session_time}}, {{closing_line}}, {{invoice_id}}.
  - End with the closing_line from email_templates.global_rules (e.g., "Blessings,", "Talk soon,").
  - If email_templates.global_rules.always_include_signature is true, append the practitioner's signature block at the end.
  - Honor email_templates.global_rules.always_mention — include that phrase somewhere in the body if set.
  - Append the disclaimer from email_templates.global_rules.disclaimer (plain line or paragraph below the signature) if set.
Never invent a signature. If email_templates isn't set yet, use the practitioner's settings.practitioner_name as a simple sign-off.

TASKS · NOTES · ACTIVITY · INVOICES:
When the practitioner says "remind me to X" or "add a task", emit create_task. Parse natural-language due-dates into YYYY-MM-DD (today is {datetime.now(timezone.utc).date().isoformat()}). Priority defaults to medium — only raise it if they say urgent/high.
When they say "mark the X task as done" / "I finished X" / "check off X", emit complete_task with either the task_id (if known) or title= for fuzzy match.
When they share information ABOUT a contact that should stick ("Marcus is interested in the leadership program"), emit create_note with contact_id + note.
When they report a real-world interaction ("I just called Deacon Harris" / "I met with Sandra yesterday"), emit log_activity with the right activity_type and notes.
For invoices: create_invoice with a list of {{description, quantity, unit_price}} line items. After creating, SHOW the total and ask "send now?" — only emit send_invoice after they confirm. "Has Sandra paid?" → look at the QUEUE / recent events, or ask; "mark Sandra paid" → mark_invoice_paid with the invoice_id. Always echo the invoice number and total in your response.

AGENT ACTIVITY AWARENESS:
Reference RECENT AGENT ACTIVITY. If an agent created drafts the practitioner hasn't reviewed, mention it: "The nurture agent drafted a check-in for Deacon Harris earlier — still in your queue. Want me to show it?"

SMART NEXT STEPS:
After every answer or action (except purely factual or greeting), propose 1-2 natural next steps as yes/no questions. Build on what just happened.

VOICE:
Direct, warm, operational. Match {practitioner}'s voice (profile: {json.dumps(voice)[:400]}). Reference specific names and numbers. No generic advice. Lead with the answer.

Keep responses concise unless asked for depth.{greeting_clause}{resume_clause}"""


# ═══════════════════════════════════════════════════════════════════════
# STRATEGY COACH PROMPT
# ═══════════════════════════════════════════════════════════════════════

def _build_coach_prompt(ctx: Dict[str, Any], is_greeting: bool,
                        resume_note: Optional[ResumeNote] = None) -> str:
    biz = ctx.get("business") or {}
    biz_name = biz.get("name", "the business")
    biz_type = biz.get("type", "general")
    practitioner = (biz.get("settings") or {}).get("practitioner_name", "the practitioner")
    voice = biz.get("voice_profile") or {}
    track = ctx.get("strategy_track") or {}

    current_phase = track.get("current_phase") or "discovery"
    status = track.get("status") or "in_progress"
    phases_data = track.get("phases") or {}

    # Completed phases
    completed: List[str] = []
    for p in STRATEGY_PHASES:
        if p == "discovery":
            if phases_data.get("discovery"):
                completed.append(p)
        elif p == "service_packages":
            if track.get("service_packages"):
                completed.append(p)
        else:
            if track.get(p):
                completed.append(p)

    discovery = phases_data.get("discovery") or {}
    summary = discovery.get("summary") or "(not yet captured)"
    audience = discovery.get("target_audience") or "(not yet identified)"
    uvp = discovery.get("unique_value_proposition") or discovery.get("value_proposition") or ""

    session_log = (phases_data.get("session_log") or [])[-3:]
    session_history = "\n".join(
        f"  - {s.get('date')}: {s.get('summary')} [covered: {', '.join(s.get('phases_progressed') or [])}]"
        for s in session_log
    ) or "  (this is the first session)"

    # Condensed deliverable snapshot so the coach can reference prior work
    market = track.get("market_research") or {}
    bm = track.get("business_model") or {}
    pricing = track.get("pricing_strategy") or {}
    packages = track.get("service_packages") or []
    projections = track.get("financial_projections") or {}
    swot = track.get("swot") or {}
    launch = track.get("launch_plan") or {}

    deliverables_snapshot = {
        "market_research_competitors": len(market.get("competitors") or []),
        "market_research_gaps": bool(market.get("gaps")),
        "business_model_value_prop": bm.get("value_proposition") or "",
        "pricing_tiers": len(pricing.get("tiers") or []),
        "service_packages": len(packages or []),
        "projections": bool(projections),
        "swot": bool(swot),
        "launch_plan_weeks": len((launch or {}).get("weeks") or []),
    }

    # Greeting context
    greeting_clause = ""
    if is_greeting:
        if session_log:
            last = session_log[-1]
            greeting_clause = (
                "\n\nOPENING (SESSION RESUME):\n"
                f"The practitioner is coming back after a break. Last session ({last.get('date')}) covered: "
                f"{last.get('summary')}. Phases touched: {', '.join(last.get('phases_progressed') or []) or 'none'}.\n"
                "Give a warm welcome-back (1-2 sentences) that names what you worked on last time, "
                "mentions the completed phases, and asks ONE concrete question that moves the CURRENT phase forward. "
                "Don't summarize everything — just enough that they feel you remember them. "
                "Do NOT emit actions in the opening message. No phase announcements."
            )
        else:
            greeting_clause = (
                "\n\nOPENING (FIRST SESSION):\n"
                f"Warm, grounded welcome. Introduce yourself as {practitioner}'s Strategy Coach. "
                "Tell them the goal: turn their idea into a real, running business, together. "
                "Then open Discovery with ONE real question — something like 'What's the idea you're sitting with?' "
                "Keep it to 3-4 sentences total. Don't emit actions in the opening."
            )

    # Resume clause if the Chief-style gap detector tells us there was a gap
    resume_clause = ""
    if resume_note and resume_note.gap_minutes and resume_note.gap_minutes > 0:
        gap = resume_note.gap_minutes
        gap_str = f"{gap}m" if gap < 60 else f"{round(gap / 60, 1)}h"
        resume_clause = f"\n\nGAP: {gap_str} since last message in this conversation. Acknowledge the return briefly if it feels natural; otherwise keep rolling."

    return f"""You are the Strategy Coach in The Solutionist System. You help people turn ideas into real, running businesses through deep conversation.

Your name and role: Strategy Coach for {practitioner}, who is launching {biz_name} ({biz_type}).

YOUR STYLE:
- Exploratory and thoughtful — ask deeper questions, challenge assumptions gently.
- Encouraging but honest — if something won't work, say so constructively with alternatives.
- Conversational — this feels like sitting with a business mentor, not filling out a form.
- Build on previous answers — reference what they've said to show you're listening.
- Never robotic — no "Great! Now let's move to Phase 2." The phases are INVISIBLE to the practitioner. You flow naturally.
- Use real numbers when discussing pricing and projections — never vague.

YOUR JOB across the conversation (8 phases, hidden from the practitioner):
1. DISCOVERY — idea, audience, unique value, background, motivation
2. MARKET RESEARCH — competitive landscape, pricing norms, gaps, opportunities
3. BUSINESS MODEL — who pays, how you deliver, what it costs
4. PRICING — specific tiers grounded in research
5. SERVICE PACKAGES — the actual offerings: included, delivery, price
6. FINANCIAL PROJECTIONS — revenue scenarios, expenses, break-even
7. SWOT — from everything discussed so far
8. LAUNCH PLAN — 90-day week-by-week action plan

RULES:
- Flow naturally between phases. NEVER announce phase transitions to the practitioner.
- Ask 4-6 questions per phase before you have enough — adapt to the conversation.
- When you have enough for a phase deliverable, emit the corresponding save_* action SILENTLY (inside the response). Don't narrate saving.
- Advance the phase silently too via advance_phase — don't announce it.
- Offer to pause when it feels natural: "We've covered a lot. Want to keep going or pick this up next time?"
- When they pause or the session is wrapping, emit [ACTION:session_summary] with a 1-2 sentence summary and the phases_progressed list.
- Challenge weak assumptions: "What if a competitor undercuts you? How would you respond?"
- Suggest quick wins when helpful: "You could start taking clients THIS WEEK with just a booking page — want me to set that up while we keep planning?"
- Quick-win actions allowed: navigate to a Build page, ensure_module, create_module_entry. Do NOT run operational agents (nurture/contract/payment) — that's the Chief's job.
- If they ask operational questions (approvals, queue, contacts), answer briefly but steer them back: "Your Chief of Staff handles that — let me know when you want to jump back to your launch plan."
- When all phases are saved AND the practitioner says they're ready to launch, emit [ACTION:complete_strategy_track]. Otherwise don't.

CURRENT STATE:
  Business: {biz_name} ({biz_type})
  Practitioner: {practitioner}
  Voice profile: {json.dumps(voice)[:400]}
  Track status: {status}
  Current phase (hidden from them): {current_phase}
  Completed phases: {', '.join(completed) if completed else '(none)'}
  Idea summary: {summary}
  Target audience: {audience}
  Value proposition: {uvp}
  Deliverable snapshot: {json.dumps(deliverables_snapshot)}

RECENT SESSION HISTORY:
{session_history}

ACTIONS (all emitted silently during conversation):
  [ACTION:{{"type":"save_phase","phase":"discovery","data":{{"summary":"...","target_audience":"...","unique_value_proposition":"...","practitioner_background":"..."}}}}]
  [ACTION:{{"type":"run_market_research","queries":["query1","query2","..."]}}]
  [ACTION:{{"type":"save_business_model","canvas":{{"customer_segments":"...","value_proposition":"...","channels":"...","customer_relationships":"...","revenue_streams":"...","key_resources":"...","key_activities":"...","key_partners":"...","cost_structure":"..."}}}}]
  [ACTION:{{"type":"save_pricing","tiers":[{{"name":"Starter","price":99,"description":"...","included":["..."]}}],"rationale":"...","comparison":"..."}}]
  [ACTION:{{"type":"save_packages","packages":[{{"name":"...","description":"...","price":"$X","duration":"...","delivery_format":"...","included":["..."]}}]}}]
  [ACTION:{{"type":"save_projections","scenarios":{{"conservative":{{...}},"realistic":{{...}},"optimistic":{{...}}}},"expenses":{{...}},"break_even":X}}]
  [ACTION:{{"type":"save_swot","strengths":"...","weaknesses":"...","opportunities":"...","threats":"..."}}]
  [ACTION:{{"type":"save_launch_plan","weeks":[{{"week":1,"theme":"Setup","actions":[{{"description":"...","system_link":"intake-forms"}}]}}]}}]
  [ACTION:{{"type":"advance_phase","to":"market_research|business_model|pricing_strategy|service_packages|financial_projections|swot|launch_plan"}}]
  [ACTION:{{"type":"session_summary","summary":"Covered target audience and pricing bands","phases_progressed":["discovery","pricing_strategy"]}}]
  [ACTION:{{"type":"complete_strategy_track"}}]
  [ACTION:{{"type":"navigate","tab":"build","page":"booking"}}]   — for quick-win navigation
  [ACTION:{{"type":"ensure_module","module_name":"Services","icon":"💼"}}]

RESPONSE SHAPE:
- Plain conversational prose. One focused question at a time.
- 2-5 sentences per turn — this is a real conversation, not a wall of text.
- Emit actions in-line where appropriate. The frontend strips them before display.
- Cap: {MAX_ACTIONS_PER_TURN} actions per turn.

Never break character. Never talk about the underlying system or phases.{greeting_clause}{resume_clause}"""


# ═══════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════

router = APIRouter(tags=["chief_of_staff"])


class ChatMessage(BaseModel):
    role: str
    content: str


class CurrentContext(BaseModel):
    tab: Optional[str] = None
    sub_tab: Optional[str] = None
    viewing_contact_id: Optional[str] = None
    viewing_module_id: Optional[str] = None
    viewing_session_id: Optional[str] = None


class ResumeNote(BaseModel):
    gap_minutes: Optional[int] = None
    changes_summary: Optional[str] = None


class ChatRequest(BaseModel):
    business_id: str
    message: str
    conversation_history: Optional[List[ChatMessage]] = None
    current_context: Optional[CurrentContext] = None
    resume_note: Optional[ResumeNote] = None
    # "strategy_coach" switches the system prompt to the deep-dive coaching
    # persona and hides phase-transition chatter from the practitioner.
    # Default (None/"chief") keeps the existing operational persona.
    mode: Optional[str] = None


def _is_greeting(msg: str) -> bool:
    s = msg.strip()
    return s.startswith(OPENING_SENTINEL_PREFIX) or s.startswith(COACH_OPEN_SENTINEL) or s.startswith(COACH_PAUSE_SENTINEL)


def _is_coach_pause(msg: str) -> bool:
    return msg.strip().startswith(COACH_PAUSE_SENTINEL)


# Phrases that suggest a prior assistant turn described an action. When we
# see these in cleaned history (action tags already stripped), we annotate
# the turn so the model knows actions WERE emitted and not to mimic an
# action-free style. Keep broad — false positives are harmless, false
# negatives let the model drift into pure conversation mode.
_ACTION_HINT_PATTERNS = (
    "drafted", "draft ", "queued", "queue ", "approved", "approving",
    "sent", "sending", "dismissed", "dismissing", "scheduled",
    "navigating", "opening", "took you", "taking you", "let me pull",
    "pulling up", "marked", "updated", "bumped", "saved", "remembered",
    "i'll remember", "i've saved", "i'll save", "running ", "ran the ",
    "set that up", "set up ", "created ", "add that ", "added ",
    "phase", "discovery phase", "strategy", "generated ",
    "rewritten", "rewrote", "edited", "bulk ",
)


def _looks_like_action_description(text: str) -> bool:
    """Heuristic: does this assistant message read like it describes an
    action the system performed? Only called on prior turns AFTER
    [ACTION:] tags have been stripped, to decide whether to re-hint that
    actions were in fact emitted."""
    low = (text or "").lower()
    if not low:
        return False
    return any(p in low for p in _ACTION_HINT_PATTERNS)


def _enrich_history_with_action_hints(history_msgs: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Walk trimmed conversation history and append a short reminder onto
    any prior assistant turn that looks like it described an action.
    Because _extract_actions_and_clean strips [ACTION:{...}] tags from the
    raw model output before the client stores history, the model sees
    assistant turns with no action tags and drifts into action-free
    conversation mode on subsequent turns. This reminder restores the
    grounding that actions ARE the right way to operate."""
    HINT = "\n\n(Actions were emitted via [ACTION:] tags and executed by the system.)"
    out: List[Dict[str, str]] = []
    for m in history_msgs:
        if m.get("role") == "assistant" and m.get("content"):
            content = m["content"]
            if HINT not in content and _looks_like_action_description(content):
                content = content + HINT
            out.append({"role": m["role"], "content": content})
        else:
            out.append(m)
    return out


def _parse_greeting_tod(msg: str) -> Optional[str]:
    """Extract time-of-day suffix from [SYSTEM:opening_greeting:morning] etc."""
    s = msg.strip()
    if not s.startswith(OPENING_SENTINEL_PREFIX):
        return None
    rest = s[len(OPENING_SENTINEL_PREFIX):]
    if rest.startswith(":") and rest.endswith("]"):
        return rest[1:-1].strip().lower() or None
    return None


@router.post("/agents/chief/chat")
async def chief_chat(req: ChatRequest):
    try:
        if not req.message:
            raise HTTPException(400, "message is required")

        async with httpx.AsyncClient() as client:
            # Gather global context + view-specific detail in parallel
            ctx_task = _gather_context(client, req.business_id)
            view_task = _fetch_view_detail(client, req.business_id, req.current_context)
            ctx, view_detail = await asyncio.gather(ctx_task, view_task)

            if not ctx:
                raise HTTPException(404, "Business not found")
            biz = ctx["business"]

            is_greeting = _is_greeting(req.message)
            tod = _parse_greeting_tod(req.message) if is_greeting else None
            is_coach_pause = _is_coach_pause(req.message)
            system = _build_system_prompt(
                ctx, is_greeting, req.current_context, view_detail,
                time_of_day=tod, resume_note=req.resume_note,
                mode=req.mode,
            )
            effective_message = req.message
            if req.mode == "strategy_coach" and is_coach_pause:
                effective_message = (
                    "The practitioner is pausing the session now. Write 1-2 warm parting sentences "
                    "that reflect what you covered together and hint at what's next when they return. "
                    "Then emit a [ACTION:session_summary] with a concise summary and the phases_progressed list. "
                    "Do not ask a new question."
                )
            elif req.mode == "strategy_coach" and is_greeting:
                effective_message = (
                    "This is the start of a session. Respond using the OPENING guidance in the system prompt."
                )

            # Build API messages — trim history and drop sentinel from the visible trail
            history = (req.conversation_history or [])[-MAX_HISTORY:]
            api_messages: List[Dict[str, str]] = []
            for m in history:
                role = "assistant" if m.role == "assistant" else "user"
                # Filter out any sentinel echoes in history
                if _is_greeting(m.content):
                    continue
                api_messages.append({"role": role, "content": m.content})

            # Fix 1: re-hint prior assistant turns that described actions.
            # The raw output had [ACTION:{...}] tags; _extract_actions_and_clean
            # stripped them before the client stored history. Without this
            # hint the model sees clean prose and mimics it — responding
            # conversationally on the next turn instead of emitting new tags.
            api_messages = _enrich_history_with_action_hints(api_messages)

            # Fix 2: per-turn system reminder prepended to the user message.
            # Skipped for the opening greeting (the greeting clause explicitly
            # says "Do NOT emit actions in the greeting") and for strategy-
            # coach sentinels which already carry their own guidance.
            if not is_greeting and not is_coach_pause:
                augmented_message = (
                    "(System reminder: emit [ACTION:{...}] tags for every operation.)\n\n"
                    + effective_message
                )
            else:
                augmented_message = effective_message

            api_messages.append({"role": "user", "content": augmented_message})

            # Coach mode gets a bigger token budget — responses are conversational
            # but deliverables (save_packages, save_launch_plan) can be large.
            coach_tokens = 2400 if req.mode == "strategy_coach" else 1600
            raw = await _call_claude(client, system, api_messages, max_tokens=coach_tokens)
            if not raw:
                return {
                    "response": "I can't reach the language model right now — try again in a moment.",
                    "actions_taken": [],
                }

            actions, clean = _extract_actions_and_clean(raw)
            taken = await _execute_actions(client, biz, actions) if actions else []

            # Best-effort: mark memories referenced in the response
            await _mark_referenced_memories(client, biz["id"], ctx.get("memories") or [], clean or raw)

            logger.info(
                f"Chief chat for {biz.get('name')}: message_len={len(req.message)} "
                f"actions={len(taken)} greeting={is_greeting} memories={len(ctx.get('memories') or [])}"
            )

            return {
                "response": clean or raw,
                "actions_taken": taken,
            }
    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[CHIEF ERROR] {tb}")
        logger.exception("chief_chat failed")
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "traceback": tb},
        )


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
