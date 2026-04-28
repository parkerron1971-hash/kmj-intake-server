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
from datetime import datetime, timedelta, timezone, date
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

# Platform owner — only businesses owned by this UID get auto-generated
# Stripe payment links using the server-side STRIPE_SECRET_KEY. All other
# practitioners paste their own Stripe Payment Link manually into
# businesses.settings.payments.stripe_link.
PLATFORM_OWNER_ID = "d820593c-9cf8-45b7-a703-89fe49efb6a4"

# ─── Team personas (mirror of src/core/lib/teamPersonas.ts) ──────────
# Keep the labels/descriptions in sync with the TS file so the Chief
# uses the same words the practitioner sees in the UI.

TEAM_PERSONAS = {
    "church": {
        "nurture": {"label": "Congregational Care", "description": "follows up with your members and visitors"},
        "session_prep": {"label": "Meeting Prep", "description": "prepares you for counseling and ministry meetings"},
        "contract": {"label": "Ministry Proposals", "description": "drafts partnership and program proposals"},
        "payment": {"label": "Tithes & Payments", "description": "tracks giving, invoices, and payment follow-ups"},
        "module": {"label": "Ministry Tracker", "description": "manages prayer requests, events, and follow-ups"},
        "growth": {"label": "Ministry Insights", "description": "spots trends in attendance, engagement, and growth"},
    },
    "coaching": {
        "nurture": {"label": "Client Care", "description": "nurtures your client relationships"},
        "session_prep": {"label": "Session Prep", "description": "gets you ready for coaching sessions"},
        "contract": {"label": "Proposals", "description": "drafts coaching packages and agreements"},
        "payment": {"label": "Billing", "description": "tracks invoices and follows up on payments"},
        "module": {"label": "Progress Tracker", "description": "manages client milestones and goals"},
        "growth": {"label": "Growth Advisor", "description": "analyzes your practice and spots opportunities"},
    },
    "consulting": {
        "nurture": {"label": "Client Relations", "description": "maintains engagement with prospects and clients"},
        "session_prep": {"label": "Engagement Prep", "description": "prepares briefs for client meetings"},
        "contract": {"label": "Proposals & Contracts", "description": "drafts SOWs and project proposals"},
        "payment": {"label": "Accounts Receivable", "description": "tracks invoices and collections"},
        "module": {"label": "Project Tracker", "description": "manages deliverables and timelines"},
        "growth": {"label": "Business Intelligence", "description": "analyzes pipeline and revenue trends"},
    },
    "nonprofit": {
        "nurture": {"label": "Donor Relations", "description": "nurtures relationships with donors and supporters"},
        "session_prep": {"label": "Meeting Prep", "description": "prepares for board meetings and donor calls"},
        "contract": {"label": "Grant Writer", "description": "drafts proposals and funding applications"},
        "payment": {"label": "Donations & Pledges", "description": "tracks contributions and pledge follow-ups"},
        "module": {"label": "Program Tracker", "description": "manages programs, volunteers, and impact metrics"},
        "growth": {"label": "Impact Advisor", "description": "analyzes outcomes and growth opportunities"},
    },
    "freelance": {
        "nurture": {"label": "Client Outreach", "description": "keeps in touch with clients and prospects"},
        "session_prep": {"label": "Project Prep", "description": "briefs you before client calls and reviews"},
        "contract": {"label": "Estimates & Contracts", "description": "drafts quotes and service agreements"},
        "payment": {"label": "Invoicing", "description": "tracks payments and follows up on late invoices"},
        "module": {"label": "Work Tracker", "description": "manages projects, deadlines, and deliverables"},
        "growth": {"label": "Business Coach", "description": "analyzes your freelance business and spots growth"},
    },
    "real_estate": {
        "nurture": {"label": "Client Nurture", "description": "follows up with buyers, sellers, and leads"},
        "session_prep": {"label": "Showing Prep", "description": "prepares you for showings and client meetings"},
        "contract": {"label": "Listing Proposals", "description": "drafts listing presentations and agreements"},
        "payment": {"label": "Commission Tracking", "description": "tracks closings, invoices, and payments"},
        "module": {"label": "Pipeline Tracker", "description": "manages active listings and buyer pipeline"},
        "growth": {"label": "Market Advisor", "description": "analyzes your deals and market trends"},
    },
    "health_wellness": {
        "nurture": {"label": "Patient Care", "description": "follows up with clients between appointments"},
        "session_prep": {"label": "Appointment Prep", "description": "prepares notes before each session"},
        "contract": {"label": "Treatment Plans", "description": "drafts care plans and service proposals"},
        "payment": {"label": "Billing", "description": "tracks payments and insurance follow-ups"},
        "module": {"label": "Client Tracker", "description": "manages treatment progress and outcomes"},
        "growth": {"label": "Practice Advisor", "description": "analyzes your practice health and growth"},
    },
    "default": {
        "nurture": {"label": "Outreach", "description": "follows up with your contacts"},
        "session_prep": {"label": "Session Prep", "description": "prepares you for meetings"},
        "contract": {"label": "Proposals", "description": "drafts proposals and agreements"},
        "payment": {"label": "Billing", "description": "tracks invoices and payments"},
        "module": {"label": "Tracker", "description": "manages your custom lists and modules"},
        "growth": {"label": "Advisor", "description": "analyzes your business and spots opportunities"},
    },
}


def get_team_label(biz_type: Optional[str], agent_key: str) -> str:
    bt = (biz_type or "default").lower()
    persona = TEAM_PERSONAS.get(bt, TEAM_PERSONAS["default"]).get(agent_key)
    if persona:
        return persona["label"]
    return agent_key.replace("_", " ").title()


def get_team_description(biz_type: Optional[str], agent_key: str) -> str:
    bt = (biz_type or "default").lower()
    persona = TEAM_PERSONAS.get(bt, TEAM_PERSONAS["default"]).get(agent_key)
    return persona["description"] if persona else ""

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

    # Recent autopilot auto-actions (chief_auto_approved events) — used
    # by the Chief to give the practitioner a "while you were away" recap.
    auto_recent = [ev for ev in (events or []) if ev.get("event_type") == "chief_auto_approved"]

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
        "auto_recent": auto_recent,
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

    # Autopilot summary — what's been auto-handled lately + per-team levels
    autopilot_cfg = (biz.get("settings") or {}).get("autopilot") or DEFAULT_AUTOPILOT
    overall_level = autopilot_cfg.get("overall", "manual")
    per_team = autopilot_cfg.get("per_team") or {}
    team_levels: List[str] = []
    for k in ("nurture", "session_prep", "contract", "payment", "module", "growth"):
        lvl = per_team.get(k, overall_level)
        team_levels.append(f"  - {get_team_label(biztype, k)}: {lvl}")
    auto_recent = ctx.get("auto_recent") or []
    auto_recent_lines = []
    for ev in auto_recent[:6]:
        d = ev.get("data") or {}
        auto_recent_lines.append(
            f"  - {d.get('reason', 'auto')}: {get_team_label(biztype, d.get('agent') or 'default')} "
            f"sent \"{(d.get('subject') or '')[:60]}\""
        )

    autopilot_block = (
        f"\nAUTOPILOT (overall: {overall_level}):\n"
        + "\n".join(team_levels)
        + ("\n  Recent auto-actions:\n" + "\n".join(auto_recent_lines) if auto_recent_lines else "")
    )

    return f"""BUSINESS: {bizname} (type: {biztype})
  Practitioner: {(biz.get('settings') or {}).get('practitioner_name', 'the practitioner')}
  Voice profile: {json.dumps(biz.get('voice_profile') or {})[:500]}{et_summary}{autopilot_block}

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


def _sanitize_action_json(raw: str) -> str:
    """Fix common JSON malformations that LLMs produce.

    Real-world example we've seen the model emit:
        {"type":"draft_and_send","body":"...gmail.com";}
    The trailing `;` before `}` makes it invalid JSON. Same shape shows
    up with stray trailing commas. Strip those before json.loads."""
    import re
    s = raw.strip()
    s = re.sub(r';(\s*[}\]])', r'\1', s)   # ; before } or ]
    s = re.sub(r',(\s*[}\]])', r'\1', s)   # trailing , before } or ]
    return s


def _strip_control_chars(s: str) -> str:
    """Remove ASCII control bytes (except \\t, \\n, \\r) that occasionally
    sneak into model output and trip json.loads. Used as a last-ditch
    fallback after the structural sanitizer didn't help."""
    return "".join(ch for ch in s if ch in "\t\n\r" or ord(ch) >= 0x20)


def _try_parse_action_json(raw: str) -> Optional[Dict[str, Any]]:
    """Parse the JSON body of an [ACTION:{...}] tag, applying tolerant
    recovery passes when the model emits something almost-valid.
    Returns the parsed dict on success, None on irrecoverable failure.

    `strict=False` lets json.loads keep going when a string contains
    raw \\n / \\t bytes — another shape we see in model output."""
    # Pass 1 — straight parse with relaxed strictness
    try:
        return json.loads(raw, strict=False)
    except json.JSONDecodeError:
        pass
    # Pass 2 — strip stray separators ( ;}  ,}  ,] )
    cleaned = _sanitize_action_json(raw)
    try:
        return json.loads(cleaned, strict=False)
    except json.JSONDecodeError:
        pass
    # Pass 3 — strip control chars and retry on the sanitized version
    final = _strip_control_chars(cleaned)
    try:
        return json.loads(final, strict=False)
    except json.JSONDecodeError as e:
        preview = raw[:240].replace("\n", "\\n")
        print(f"[Chief] action JSON parse failed after sanitize+strip: {e}\n  raw={preview}", flush=True)
        return None


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
        # After the closing brace we expect a ']' — but the AI sometimes
        # emits whitespace between them ("} ]"), so skip past it before
        # checking. Also handle stray ; or , the model occasionally
        # inserts before the closing bracket.
        k = j + 1
        while k < n and text[k] in (" ", "\n", "\r", "\t", ";", ","):
            k += 1
        bracket_found = k < n and text[k] == "]"

        # Aggressive logging — every tag we find, regardless of outcome,
        # so Railway logs make production parser issues debuggable.
        print(
            f"[Chief Parser] Found tag at position {start} | "
            f"raw len={len(json_str)} | "
            f"head={json_str[:100]!r} | tail={json_str[-50:]!r} | "
            f"bracket_found={bracket_found}",
            flush=True,
        )

        if bracket_found:
            parsed = _try_parse_action_json(json_str)
            print(
                f"[Chief Parser] Parse result: "
                f"{'SUCCESS type=' + str(parsed.get('type')) if isinstance(parsed, dict) else 'FAILED'}",
                flush=True,
            )
            if isinstance(parsed, dict) and parsed.get("type"):
                actions.append(parsed)
                # Swallow the entire [ACTION:{...}] and any trailing space
                after = k + 1
                while after < n and text[after] in (" ", "\n", "\r", "\t"):
                    after += 1
                i = after
                continue
            # Structural shape was [ACTION:{...}] but JSON was too broken
            # to recover. Drop the tag so the malformed marker doesn't
            # leak into the user-facing text.
            after = k + 1
            while after < n and text[after] in (" ", "\n", "\r", "\t"):
                after += 1
            i = after
            continue

        # No closing ']' located — emit the original literal and move on.
        print(
            f"[Chief Parser] No closing bracket found within {k - (j + 1)} chars after }} — emitting literal",
            flush=True,
        )
        out_parts.append(text[start:k + 1 if k < n else n])
        i = k + 1 if k < n else n

    cleaned = "".join(out_parts).strip()
    cleaned = _scrub_response_text(cleaned)
    return actions[:MAX_ACTIONS_PER_TURN], cleaned


# Internal hint markers we inject into prior assistant turns so the
# model recognizes that actions WERE emitted (and not to drift into
# action-free conversation). Some models copy these markers forward
# into NEW responses — strip them from anything the practitioner sees.
_HINT_LITERALS = (
    "[Note: In this response, I used [ACTION:{...}] tags to execute all operations. Every action I described had a corresponding tag.]",
    "[Note: In this response, I used tags to execute all operations. Every action I described had a corresponding tag.]",
    "(Actions were emitted via [ACTION:] tags and executed by the system.)",
)
_HINT_BRACKETED = re.compile(r"\[Note:[^\]]*?corresponding tag\.\s*\]", re.IGNORECASE | re.DOTALL)
_HINT_PARENS = re.compile(r"\(Actions were emitted[^\)]*?by the system\.\s*\)", re.IGNORECASE | re.DOTALL)
_BLANK_LINES_3PLUS = re.compile(r"\n{3,}")


def _scrub_response_text(text: str) -> str:
    """Remove internal hint markers + extra blank lines from text the
    practitioner is about to see. Belt-and-suspenders: literal
    replacement first (handles the exact marker), then regex (handles
    paraphrased variants), then blank-line collapse."""
    if not text:
        return text
    s = text
    for lit in _HINT_LITERALS:
        if lit in s:
            s = s.replace(lit, "")
    s = _HINT_BRACKETED.sub("", s)
    s = _HINT_PARENS.sub("", s)
    s = _BLANK_LINES_3PLUS.sub("\n\n", s)
    return s.strip()


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
    draft_row = inserted[0] if isinstance(inserted, list) and inserted else None

    # Autopilot: if Smart/Full + routine, auto-approve right now.
    auto_label_suffix = ""
    if draft_row:
        ap_result = await _process_autopilot_for_draft(client, biz, draft_row, contact)
        if ap_result and ap_result.get("ok"):
            auto_label_suffix = " (auto-sent)" if ap_result.get("sent") else " (auto-approved)"

    return {
        "type": "draft_nurture",
        "result": "auto_approved" if auto_label_suffix else "queued for approval",
        "label": f"Check-in for {contact.get('name')}{auto_label_suffix}",
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
    contact_name = action.get("contact_name")
    contact = await _validate_contact(client, biz["id"], contact_id) if contact_id else None
    if contact_id and not contact:
        return _fail("create_session", f"Contact {contact_id} not found")

    # Fall back to fuzzy name lookup when no id (or it didn't validate)
    if not contact and contact_name:
        try:
            rows = await _sb(
                client, "GET",
                f"/contacts?business_id=eq.{biz['id']}&name=ilike.*{contact_name}*&select=id,name,email&limit=2",
            ) or []
        except Exception:
            rows = []
        if isinstance(rows, list) and len(rows) == 1:
            contact = rows[0]
        elif isinstance(rows, list) and len(rows) > 1:
            options = ", ".join(r.get("name", "") for r in rows[:5])
            return _fail("create_session", f"Multiple contacts match '{contact_name}': {options}. Specify contact_id.")

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
    # Accept "duration" as an alias for "duration_minutes" — common short form
    duration = action.get("duration_minutes") or action.get("duration") or 60

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

    session_id = (inserted[0].get("id") if isinstance(inserted, list) and inserted else None)
    label = f"Session: {title}" + (f" with {contact.get('name')}" if contact else "")
    try:
        when = datetime.fromisoformat(scheduled_for.replace("Z", "+00:00")).strftime("%b %d, %I:%M %p")
    except (ValueError, TypeError):
        when = scheduled_for
    return {
        "type": "create_session",
        "result": f"scheduled for {when}",
        "label": label,
        "session_id": session_id,
        "contact_id": contact["id"] if contact else None,
        "nav": _nav("operate", "calendar"),
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


# General-purpose contact field updater. Existing
# update_contact_status / update_contact_health remain (they emit
# typed timeline events); this one covers everything else — email,
# phone, name, role, tags, notes, lead_score — and falls back to
# fuzzy name lookup when the model didn't supply a contact_id.
UPDATABLE_CONTACT_FIELDS = (
    "email", "phone", "name", "role", "tags", "notes",
    "status", "health_score", "lead_score",
)


async def handle_update_contact(client, biz, action) -> Dict:
    """Update any field on a contact — email/phone/name/tags/notes/etc.

    Resolution order for the target contact:
      1. action["contact_id"] — preferred, validated against business.
      2. action["name"] / action["contact_name"] — case-insensitive
         fuzzy match (ilike) within this business.
    """
    biz_id = biz["id"]
    contact_id = action.get("contact_id")
    name_query = action.get("name") or action.get("contact_name")
    contact: Optional[Dict[str, Any]] = None

    if contact_id:
        contact = await _validate_contact(client, biz_id, contact_id)

    # Fall back to a name search when no id (or id didn't validate)
    if not contact and name_query:
        try:
            rows = await _sb(
                client, "GET",
                f"/contacts?business_id=eq.{biz_id}&name=ilike.*{name_query}*"
                f"&select=id,name,email&limit=2",
            ) or []
        except Exception:
            rows = []
        if isinstance(rows, list) and len(rows) == 1:
            contact = rows[0]
        elif isinstance(rows, list) and len(rows) > 1:
            options = ", ".join(f"{r.get('name')} ({(r.get('email') or 'no email')})" for r in rows[:5])
            return _fail(
                "update_contact",
                f"Multiple contacts match '{name_query}': {options}. "
                "Please specify contact_id or use a more unique name.",
            )

    if not contact:
        return _fail("update_contact", f"Contact not found ({contact_id or name_query or '—'})")

    # Build the patch from the allowed fields. Validate status the same
    # way handle_update_contact_status does so a generic update can't
    # write a bogus status. health_score / lead_score get clamped 0..100.
    patch: Dict[str, Any] = {}
    for field in UPDATABLE_CONTACT_FIELDS:
        if field not in action:
            continue
        value = action[field]
        if value is None:
            continue
        if field == "status":
            v = str(value).lower().strip()
            if v not in VALID_CONTACT_STATUSES:
                return _fail("update_contact", f"Invalid status '{v}'")
            patch["status"] = v
        elif field in ("health_score", "lead_score"):
            try:
                patch[field] = max(0, min(100, int(value)))
            except (TypeError, ValueError):
                return _fail("update_contact", f"{field} must be a number 0-100")
        elif field == "tags":
            if isinstance(value, list):
                patch["tags"] = [str(t).strip() for t in value if str(t).strip()]
            elif isinstance(value, str) and value.strip():
                patch["tags"] = [t.strip() for t in value.split(",") if t.strip()]
        else:
            # email / phone / name / role / notes — just store the string.
            patch[field] = str(value).strip() or None

    # Ignore name when the practitioner used `name` purely to look up
    # the contact and didn't actually want to rename them. Heuristic:
    # if the only patch field is `name` and it matches the resolved
    # contact's current name, treat as no-op.
    if patch.get("name") and patch["name"] == contact.get("name") and len(patch) == 1:
        del patch["name"]

    if not patch:
        return _fail("update_contact", "no fields to update")

    try:
        await _sb(client, "PATCH", f"/contacts?id=eq.{contact['id']}", patch)
    except Exception as e:
        return _fail("update_contact", f"patch failed: {e}")

    # Emit a status_changed event for downstream listeners (contact-linked
    # modules etc.) so the generic updater stays consistent with the
    # specialized handler. Only fires when status actually moved.
    if "status" in patch and patch["status"] != contact.get("status"):
        await _sb(client, "POST", "/events", {
            "business_id": biz_id,
            "contact_id": contact["id"],
            "event_type": "contact_status_changed",
            "data": {"from": contact.get("status"), "to": patch["status"]},
            "source": "chief_of_staff",
        })

    contact_label = contact.get("name") or "contact"
    changes = ", ".join(f"{k}={v}" for k, v in patch.items())
    return {
        "type": "update_contact",
        "result": "updated",
        "label": f"✏️ Updated {contact_label}: {changes}",
        "contact_id": contact["id"],
        "nav": _nav("operate", "contacts", contact["id"]),
    }


# Delete a contact by id, with name-based fallback. Cascades on the
# DB side handle related events/sessions/etc; we just DELETE the row.
async def handle_delete_contact(client, biz, action) -> Dict:
    biz_id = biz["id"]
    contact_id = action.get("contact_id")
    name = action.get("name") or action.get("contact_name")
    contact: Optional[Dict[str, Any]] = None

    if contact_id:
        contact = await _validate_contact(client, biz_id, contact_id)

    if not contact and name:
        try:
            rows = await _sb(
                client, "GET",
                f"/contacts?business_id=eq.{biz_id}&name=ilike.*{name}*&select=id,name&limit=2",
            ) or []
        except Exception:
            rows = []
        if isinstance(rows, list) and len(rows) == 1:
            contact = rows[0]
        elif isinstance(rows, list) and len(rows) > 1:
            options = ", ".join(r.get("name", "") for r in rows[:5])
            return _fail("delete_contact", f"Multiple contacts match '{name}': {options}. Specify contact_id.")

    if not contact:
        return _fail("delete_contact", f"contact not found ({contact_id or name or '—'})")

    try:
        await _sb(client, "DELETE", f"/contacts?id=eq.{contact['id']}", None)
    except Exception as e:
        return _fail("delete_contact", f"delete failed: {e}")

    return {
        "type": "delete_contact",
        "result": "deleted",
        "label": f"🗑️ Deleted: {contact.get('name') or 'contact'}",
        "nav": _nav("operate", "contacts"),
    }


# Update an existing session — reschedule, change status, edit notes,
# or swap session_type. Resolves by session_id, falling back to the
# most-recent session for a named contact.
async def handle_update_session(client, biz, action) -> Dict:
    biz_id = biz["id"]
    session_id = action.get("session_id")

    # Resolution: id wins, otherwise most-recent session for contact
    if not session_id:
        contact_id = action.get("contact_id")
        contact_name = action.get("contact_name")
        target_contact_id = contact_id
        if not target_contact_id and contact_name:
            try:
                rows = await _sb(
                    client, "GET",
                    f"/contacts?business_id=eq.{biz_id}&name=ilike.*{contact_name}*&select=id,name&limit=1",
                ) or []
            except Exception:
                rows = []
            if rows:
                target_contact_id = rows[0].get("id")
        if target_contact_id:
            try:
                sess = await _sb(
                    client, "GET",
                    f"/sessions?business_id=eq.{biz_id}&contact_id=eq.{target_contact_id}"
                    f"&order=scheduled_for.desc&limit=1&select=id",
                ) or []
            except Exception:
                sess = []
            if sess:
                session_id = sess[0].get("id")

    if not session_id:
        return _fail("update_session", "session not found (provide session_id or contact_name)")

    patch: Dict[str, Any] = {}

    # Reschedule
    new_when = action.get("scheduled_for") or action.get("date")
    if new_when:
        if len(new_when) == 10:
            new_when = f"{new_when}T09:00:00Z"
        elif "T" in new_when and not new_when.endswith("Z") and "+" not in new_when:
            new_when = new_when + ":00Z" if len(new_when) == 16 else new_when + "Z"
        patch["scheduled_for"] = new_when

    # Status — accept the standard set
    if "status" in action and action["status"]:
        v = str(action["status"]).lower().strip()
        if v not in ("scheduled", "completed", "no_show", "cancelled", "in_progress"):
            return _fail("update_session", f"invalid session status '{v}'")
        patch["status"] = v

    # Notes / type / duration / title
    if "notes" in action and action["notes"] is not None:
        patch["notes"] = (action["notes"] or "").strip() or None
    if "session_type" in action and action["session_type"]:
        patch["session_type"] = action["session_type"]
    if "duration_minutes" in action or "duration" in action:
        try:
            patch["duration_minutes"] = int(action.get("duration_minutes") or action.get("duration") or 0) or 60
        except (TypeError, ValueError):
            pass
    if "title" in action and action["title"]:
        patch["title"] = str(action["title"]).strip()

    if not patch:
        return _fail("update_session", "no fields to update")

    try:
        await _sb(client, "PATCH", f"/sessions?id=eq.{session_id}", patch)
    except Exception as e:
        return _fail("update_session", f"patch failed: {e}")

    # Friendly label
    bits: List[str] = []
    if "status" in patch:
        bits.append(f"status={patch['status']}")
    if "scheduled_for" in patch:
        try:
            when = datetime.fromisoformat(patch["scheduled_for"].replace("Z", "+00:00")).strftime("%b %d, %I:%M %p")
            bits.append(f"rescheduled→{when}")
        except (ValueError, TypeError):
            bits.append(f"rescheduled→{patch['scheduled_for']}")
    if "notes" in patch:
        bits.append("notes")
    if "session_type" in patch:
        bits.append(f"type={patch['session_type']}")

    return {
        "type": "update_session",
        "result": "updated",
        "label": f"📅 Session updated: {', '.join(bits) or 'fields'}",
        "session_id": session_id,
        "nav": _nav("operate", "calendar"),
    }


# ─── Navigation shortcut handlers ────────────────────────────────────
#
# Tiny wrappers that dispatch a nav payload — they exist so the Chief
# can emit a clear named action when the practitioner asks "open my
# documents" / "show my calendar" / "show me revenue", instead of
# falling back to the generic `navigate` action and getting the sub
# wrong.

async def handle_open_documents(client, biz, action) -> Dict:
    return {
        "type": "open_documents",
        "result": "navigating",
        "label": "📄 Opening Documents",
        "nav": _nav("operate", "documents"),
    }


async def handle_open_calendar(client, biz, action) -> Dict:
    return {
        "type": "open_calendar",
        "result": "navigating",
        "label": "📅 Opening Calendar",
        "nav": _nav("operate", "calendar"),
    }


async def handle_show_revenue(client, biz, action) -> Dict:
    nav = _nav("operate", "invoices")
    if isinstance(nav, dict):
        nav = {**nav, "view": "revenue"}
    return {
        "type": "show_revenue",
        "result": "navigating",
        "label": "💰 Opening Revenue Dashboard",
        "nav": nav,
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
    contact_id = created.get("id") if isinstance(created, dict) else None
    return {
        "type": "create_contact",
        "result": f"added as {status}",
        "label": name,
        # Expose contact_id at the top level so chained actions can
        # resolve "@create_contact.contact_id" via _resolve_action_references.
        "contact_id": contact_id,
        "nav": _nav("operate", "contacts", contact_id),
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


# ─── Autopilot — auto-approval gating ────────────────────────────────
#
# The practitioner sets per-team autonomy in businesses.settings.autopilot.
# When an agent inserts a draft into agent_queue, the Chief consults
# this config (along with situational context — VIP, at-risk, recent
# contact, escalating reminders) to decide whether to auto-approve and
# send, or hold for review.
#
# Mirror of the TS-side defaults in src/core/lib/teamPersonas.ts, kept
# minimal here — Python only needs to know the levels.

DEFAULT_AUTOPILOT = {
    "overall": "manual",
    "per_team": {
        "nurture": "manual", "session_prep": "manual", "contract": "manual",
        "payment": "manual", "module": "manual", "growth": "manual",
    },
}


def _autopilot_level(biz: Dict[str, Any], agent_name: str) -> str:
    ap = (biz.get("settings") or {}).get("autopilot") or {}
    per = ap.get("per_team") or {}
    if agent_name in per and per[agent_name] in ("manual", "smart", "full"):
        return per[agent_name]
    overall = ap.get("overall")
    return overall if overall in ("manual", "smart", "full") else "manual"


async def _count_payment_reminders(client, biz_id: str, invoice_id: Optional[str]) -> int:
    """How many payment reminder events have we logged for this invoice?
    Used by smart-mode to escalate after the second reminder."""
    if not invoice_id:
        return 0
    try:
        rows = await _sb(
            client, "GET",
            f"/agent_queue?business_id=eq.{biz_id}&agent=eq.payment&data->>invoice_id=eq.{invoice_id}&status=eq.sent&select=id",
        ) or []
        return len(rows) if isinstance(rows, list) else 0
    except Exception:
        return 0


async def _should_auto_approve(
    client,
    biz: Dict[str, Any],
    agent_name: str,
    draft: Dict[str, Any],
    contact: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """Return (should_auto_approve, reason_code)."""
    level = _autopilot_level(biz, agent_name)
    if level == "manual":
        return False, "manual_mode"
    if level == "full":
        return True, "full_auto"

    # Smart mode — apply contextual rules
    if agent_name == "nurture":
        if contact and (contact.get("status") or "").lower() == "vip":
            return False, "vip_contact_review"
        health = contact.get("health_score") if contact else None
        if isinstance(health, (int, float)) and health < 30:
            return False, "at_risk_review"
        last = (contact or {}).get("last_interaction")
        if last:
            try:
                last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - last_dt).total_seconds() < 48 * 3600:
                    return False, "recent_contact_cooldown"
            except Exception:
                pass
        return True, "routine_checkin"

    if agent_name == "session_prep":
        if (draft.get("action_type") or "") == "session_prep":
            return True, "routine_prep"
        return False, "followup_review"

    if agent_name == "payment":
        invoice_id = (draft.get("data") or {}).get("invoice_id") if isinstance(draft.get("data"), dict) else None
        reminders = await _count_payment_reminders(client, biz["id"], invoice_id)
        if reminders < 2:
            return True, "routine_reminder"
        return False, "escalated_reminder"

    if agent_name == "growth":
        if (draft.get("action_type") or "") == "briefing":
            return True, "routine_briefing"
        return False, "insight_review"

    # contract / module — default to manual under smart mode
    return False, "default_manual"


async def _process_autopilot_for_draft(
    client,
    biz: Dict[str, Any],
    draft_row: Dict[str, Any],
    contact: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Run the autopilot decision against a freshly-inserted draft row.
    If it auto-approves, kicks off the standard approval pipeline and
    emits a chief_auto_approved event. Returns the delivery result for
    callers to inspect, or None when held for review."""
    agent_name = (draft_row.get("agent") or "").strip().lower()
    if not agent_name:
        return None
    should_auto, reason = await _should_auto_approve(client, biz, agent_name, draft_row, contact)
    if not should_auto:
        print(f"[Chief Autopilot] Queued for review: {agent_name} -- {reason}", flush=True)
        return None
    try:
        result = await _do_approve_one(client, biz, draft_row)
    except Exception as e:
        print(f"[Chief Autopilot] auto-approve failed for {agent_name}: {e}", flush=True)
        return None
    await _sb(client, "POST", "/events", {
        "business_id": biz["id"],
        "contact_id": draft_row.get("contact_id"),
        "event_type": "chief_auto_approved",
        "data": {
            "queue_id": draft_row.get("id"),
            "agent": agent_name,
            "reason": reason,
            "subject": draft_row.get("subject"),
            "sent": bool(result.get("sent")),
        },
        "source": "chief_autopilot",
    })
    print(f"[Chief Autopilot] Auto-approved {agent_name} draft: {reason}", flush=True)
    return result


async def _autopilot_sweep(client, biz: Dict[str, Any], lookback_minutes: int = 15) -> int:
    """At the top of each chief_chat, look at drafts created in the last
    few minutes and auto-process whatever the autopilot config allows.
    This catches drafts created by external agents (nurture_agent.py
    etc) without having to instrument every insertion site.
    Returns the number of drafts auto-approved."""
    biz_id = biz["id"]
    since = (datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)).isoformat()
    try:
        drafts = await _sb(
            client, "GET",
            f"/agent_queue?business_id=eq.{biz_id}&status=eq.draft&created_at=gte.{since}"
            f"&select=id,agent,action_type,subject,body,channel,contact_id,data,priority,created_at"
            f"&limit=20",
        ) or []
    except Exception as e:
        print(f"[Chief Autopilot] sweep load failed: {e}", flush=True)
        return 0
    if not drafts:
        return 0

    approved_count = 0
    for d in drafts:
        contact = None
        cid = d.get("contact_id")
        if cid:
            try:
                rows = await _sb(client, "GET", f"/contacts?id=eq.{cid}&select=id,name,email,status,health_score,last_interaction")
                contact = (rows or [None])[0]
            except Exception:
                contact = None
        result = await _process_autopilot_for_draft(client, biz, d, contact)
        if result and result.get("ok"):
            approved_count += 1
    return approved_count


# ─── Escalation generator ────────────────────────────────────────────
#
# When the Chief evaluates business state, it should surface anything
# requiring a human decision. Escalations are chief_notifications with
# type="escalation" — the Autopilot UI renders the options and routes
# the practitioner's choice back through the Chief or direct PATCHes.

async def _create_escalation(
    client,
    biz: Dict[str, Any],
    agent_key: str,
    title: str,
    body: str,
    options: List[Dict[str, str]],
    contact_id: Optional[str] = None,
    invoice_id: Optional[str] = None,
) -> None:
    """Idempotent create — de-duped by agent + title within unread escalations."""
    biz_id = biz["id"]
    biz_type = biz.get("type")
    try:
        existing = await _sb(
            client, "GET",
            f"/chief_notifications?business_id=eq.{biz_id}&status=eq.unread&type=eq.escalation"
            f"&data->>agent=eq.{agent_key}&select=id,title&limit=50",
        ) or []
    except Exception:
        existing = []
    # Python-side title match — PostgREST URL-encoding of title with
    # special chars is unreliable, so we filter after the fact.
    if isinstance(existing, list) and any((row.get("title") == title) for row in existing):
        return
    agent_label = get_team_label(biz_type, agent_key)
    await _sb(client, "POST", "/chief_notifications", {
        "business_id": biz_id,
        "type": "escalation",
        "title": title,
        "body": body,
        "suggested_action": (options[0]["label"] if options else ""),
        "status": "unread",
        "data": {
            "agent": agent_key,
            "agent_label": agent_label,
            "contact_id": contact_id,
            "contact_name": None,  # caller can pass via body for display
            "invoice_id": invoice_id,
            "options": options,
        },
    })


async def _evaluate_escalations(client, biz: Dict[str, Any]) -> int:
    """Inspect business state and create deduped escalation notifications
    where the practitioner needs to make a call. Conservative — only
    surfaces situations the system can't resolve on autopilot."""
    biz_id = biz["id"]
    biz_type = biz.get("type")
    created = 0
    today = datetime.now(timezone.utc).date()

    # ── Nurture: critically low health
    try:
        rows = await _sb(
            client, "GET",
            f"/contacts?business_id=eq.{biz_id}&health_score=lt.20&status=neq.inactive"
            f"&select=id,name,health_score,last_interaction&limit=5",
        ) or []
    except Exception:
        rows = []
    for c in rows:
        name = c.get("name") or "this contact"
        title = f"{name}'s engagement is critically low"
        body = f"{name} is at health {c.get('health_score')}. Time to intervene?"
        await _create_escalation(
            client, biz, "nurture", title, body,
            options=[
                {"label": "Reach Out Personally", "style": "primary"},
                {"label": "Give Space", "style": "secondary"},
                {"label": "Mark Inactive", "style": "secondary"},
            ],
            contact_id=c.get("id"),
        )
        created += 1

    # ── Payment: 30+ and 60+ day overdue
    try:
        thirty = (today - timedelta(days=30)).isoformat()
        sixty = (today - timedelta(days=60)).isoformat()
        overdue = await _sb(
            client, "GET",
            f"/invoices?business_id=eq.{biz_id}&status=in.(sent,viewed,overdue)"
            f"&due_date=lt.{thirty}&select=id,invoice_number,total,due_date,contact_id,contacts(name)"
            f"&order=due_date.asc&limit=10",
        ) or []
    except Exception:
        overdue = []
    for inv in overdue:
        try:
            due = date.fromisoformat(str(inv.get("due_date"))) if inv.get("due_date") else today
        except Exception:
            due = today
        days = (today - due).days
        amount = float(inv.get("total") or 0)
        contact_name = (inv.get("contacts") or {}).get("name") if isinstance(inv.get("contacts"), dict) else None
        invoice_number = inv.get("invoice_number") or "(no number)"
        if days >= 60:
            title = f"{invoice_number} is critically overdue"
            body = f"{invoice_number} is {days} days past due (${amount:,.2f}). Time to make a call."
            opts = [
                {"label": "Final Notice", "style": "primary"},
                {"label": "Write Off", "style": "secondary"},
                {"label": "Ask Chief", "style": "secondary"},
            ]
        else:
            title = f"{invoice_number} is {days} days overdue"
            body = f"{invoice_number} is {days} days past due (${amount:,.2f}). Two reminders already sent."
            opts = [
                {"label": "Send Final Notice", "style": "primary"},
                {"label": "Offer Payment Plan", "style": "secondary"},
                {"label": "Write Off", "style": "secondary"},
            ]
        await _create_escalation(
            client, biz, "payment", title, body, opts,
            contact_id=inv.get("contact_id"),
            invoice_id=inv.get("id"),
        )
        created += 1

    # ── Session Prep: tomorrow with no prep_brief
    try:
        tomorrow_start = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        tomorrow_end = tomorrow_start + timedelta(hours=24)
        sessions = await _sb(
            client, "GET",
            f"/sessions?business_id=eq.{biz_id}&status=eq.scheduled"
            f"&scheduled_for=gte.{tomorrow_start.isoformat()}&scheduled_for=lt.{tomorrow_end.isoformat()}"
            f"&select=id,title,scheduled_for,prep_brief,contact_id,contacts(name)&limit=10",
        ) or []
    except Exception:
        sessions = []
    for s in sessions:
        if s.get("prep_brief"):
            continue
        contact_name = (s.get("contacts") or {}).get("name") if isinstance(s.get("contacts"), dict) else None
        title = f"Tomorrow's session with {contact_name or 'a contact'} has no prep brief"
        body = f"{s.get('title') or 'Session'} is scheduled tomorrow. Want me to prep now?"
        await _create_escalation(
            client, biz, "session_prep", title, body,
            options=[
                {"label": "Prep Now", "style": "primary"},
                {"label": "Skip Prep", "style": "secondary"},
            ],
            contact_id=s.get("contact_id"),
        )
        created += 1

    return created


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
# PROJECT HANDLERS
# ═══════════════════════════════════════════════════════════════════════
#
# Projects live as module_entries on a "Projects" custom_module that
# the Chief auto-creates the first time it's needed. The schema mirrors
# what the ProjectsPanel UI expects: title, client, status, dates,
# description, value, notes.

PROJECT_STATUSES = ("planning", "active", "on_hold", "completed", "cancelled")


async def _ensure_projects_module(client, biz_id: str) -> Optional[str]:
    """Find the Projects module (slug=projects) for this business, or
    create it. Returns the module id, or None on failure."""
    try:
        rows = await _sb(
            client, "GET",
            f"/custom_modules?business_id=eq.{biz_id}&slug=eq.projects&is_active=eq.true&limit=1&select=id",
        ) or []
    except Exception:
        rows = []
    if isinstance(rows, list) and rows:
        return rows[0].get("id")

    schema = {"fields": [
        {"name": "title", "type": "text"},
        {"name": "client", "type": "text"},
        {"name": "contact_id", "type": "contact_link"},
        {"name": "status", "type": "select", "options": list(PROJECT_STATUSES)},
        {"name": "start_date", "type": "date"},
        {"name": "target_date", "type": "date"},
        {"name": "description", "type": "textarea"},
        {"name": "tasks", "type": "textarea"},
        {"name": "milestones", "type": "textarea"},
        {"name": "notes", "type": "textarea"},
        {"name": "value", "type": "number"},
    ]}
    try:
        inserted = await _sb(client, "POST", "/custom_modules", {
            "business_id": biz_id,
            "name": "Projects",
            "slug": "projects",
            "description": "Auto-created Projects module",
            "icon": "📁",
            "schema": schema,
            "agent_config": {"enabled": True, "triggers": []},
            "public_display": {
                "enabled": False, "display_type": "list",
                "title_override": "Projects", "visible_fields": ["title", "client", "status"],
                "hidden_fields": ["contact_id", "notes"], "max_display": 20, "sort_by": "created_at",
            },
            "is_active": True,
        })
    except Exception as e:
        print(f"[Chief] Projects module create failed: {e}", flush=True)
        return None
    if not inserted or not isinstance(inserted, list):
        return None
    return inserted[0].get("id")


async def _resolve_project_contact(client, biz_id: str, action: Dict) -> Tuple[Optional[str], Optional[str]]:
    """Resolve (contact_id, contact_name) from a project action.
    Accepts contact_id directly, otherwise fuzzy-matches contact_name."""
    contact_id = action.get("contact_id")
    contact_name = action.get("contact_name") or action.get("client") or ""
    if contact_id:
        try:
            rows = await _sb(client, "GET", f"/contacts?id=eq.{contact_id}&business_id=eq.{biz_id}&select=id,name") or []
            if rows:
                return rows[0].get("id"), rows[0].get("name") or contact_name
        except Exception:
            pass
    if contact_name:
        try:
            rows = await _sb(
                client, "GET",
                f"/contacts?business_id=eq.{biz_id}&name=ilike.*{contact_name}*&select=id,name&limit=1",
            ) or []
            if rows:
                return rows[0].get("id"), rows[0].get("name")
        except Exception:
            pass
    return None, contact_name or None


async def handle_create_project(client, biz, action) -> Dict:
    """Create a project as a module_entry on the Projects module."""
    biz_id = biz["id"]
    title = (action.get("title") or "Untitled Project").strip()
    status = (action.get("status") or "planning").lower()
    if status not in PROJECT_STATUSES:
        status = "planning"

    module_id = await _ensure_projects_module(client, biz_id)
    if not module_id:
        return _fail("create_project", "could not find or create Projects module")

    contact_id, contact_name = await _resolve_project_contact(client, biz_id, action)

    try:
        value = float(action.get("value") or 0)
    except (TypeError, ValueError):
        value = 0.0

    payload = {
        "module_id": module_id,
        "business_id": biz_id,
        "status": "active",
        "data": {
            "title": title,
            "client": contact_name or "",
            "contact_id": contact_id,
            "status": status,
            "start_date": action.get("start_date") or "",
            "target_date": action.get("target_date") or "",
            "description": action.get("description") or "",
            "tasks": action.get("tasks") or "",
            "milestones": action.get("milestones") or "",
            "notes": action.get("notes") or "",
            "value": value,
        },
    }
    inserted = await _sb(client, "POST", "/module_entries", payload)
    if not inserted:
        return _fail("create_project", "insert failed")

    project_id = (inserted[0].get("id") if isinstance(inserted, list) and inserted else None)
    label = f"📁 Project: {title}"
    if contact_name:
        label += f" — {contact_name}"
    if value > 0:
        label += f" · ${value:,.0f}"
    return {
        "type": "create_project",
        "result": "created",
        "label": label,
        "project_id": project_id,
        "contact_id": contact_id,
        "nav": _nav("operate", "projects"),
    }


async def _find_project_by_title(client, biz_id: str, title: str) -> Optional[Dict]:
    """Fuzzy-find a project module_entry by title. Returns the row or None."""
    module_id = await _ensure_projects_module(client, biz_id)
    if not module_id:
        return None
    try:
        rows = await _sb(
            client, "GET",
            f"/module_entries?module_id=eq.{module_id}&select=id,data&limit=200",
        ) or []
    except Exception:
        return None
    needle = title.lower()
    matches = [r for r in (rows or []) if needle in (((r.get("data") or {}).get("title") or "").lower())]
    return matches[0] if matches else None


async def handle_update_project(client, biz, action) -> Dict:
    """Update a project's fields. Resolves by project_id or fuzzy title."""
    biz_id = biz["id"]
    project_id = action.get("project_id")
    title_query = action.get("title_query") or (action.get("title") if not project_id and not action.get("status_change_only") else None)

    project: Optional[Dict[str, Any]] = None
    if project_id:
        try:
            rows = await _sb(client, "GET", f"/module_entries?id=eq.{project_id}&select=id,data&limit=1") or []
            if rows:
                project = rows[0]
        except Exception:
            project = None
    if not project and title_query:
        project = await _find_project_by_title(client, biz_id, title_query)

    if not project:
        return _fail("update_project", "project not found (provide project_id or a unique title)")

    data = dict(project.get("data") or {})
    changes: List[str] = []

    # Allow renaming if explicit title change requested AND the title field
    # was used as the lookup key (be conservative — don't rename when the
    # `title` field was just a search term).
    if "title" in action and action.get("project_id"):
        new_title = str(action["title"]).strip()
        if new_title and new_title != data.get("title"):
            data["title"] = new_title
            changes.append(f"title='{new_title}'")

    for field in ("status", "start_date", "target_date", "description", "tasks", "milestones", "notes"):
        if field in action and action[field] is not None:
            v = action[field]
            if field == "status":
                v = str(v).lower()
                if v not in PROJECT_STATUSES:
                    return _fail("update_project", f"invalid status '{v}'")
            data[field] = v
            changes.append(f"{field}={v}")

    if "value" in action and action["value"] is not None:
        try:
            data["value"] = float(action["value"])
            changes.append(f"value={data['value']}")
        except (TypeError, ValueError):
            pass

    # Re-link contact when contact_name supplied
    if action.get("contact_name") or action.get("contact_id"):
        cid, cname = await _resolve_project_contact(client, biz_id, action)
        if cid or cname:
            data["contact_id"] = cid
            data["client"] = cname or data.get("client") or ""
            changes.append(f"client={cname}")

    if not changes:
        return _fail("update_project", "no fields to update")

    try:
        await _sb(client, "PATCH", f"/module_entries?id=eq.{project['id']}", {"data": data})
    except Exception as e:
        return _fail("update_project", f"patch failed: {e}")

    return {
        "type": "update_project",
        "result": "updated",
        "label": f"📁 Updated: {data.get('title', 'project')} — {', '.join(changes)}",
        "project_id": project["id"],
        "nav": _nav("operate", "projects"),
    }


async def handle_list_projects(client, biz, action) -> Dict:
    """Return the project list, optionally filtered by status."""
    biz_id = biz["id"]
    module_id = await _ensure_projects_module(client, biz_id)
    if not module_id:
        return {
            "type": "list_projects",
            "result": "no projects yet",
            "label": "📁 0 projects",
            "projects": [],
            "summary": "(no projects)",
            "nav": _nav("operate", "projects"),
        }

    try:
        rows = await _sb(
            client, "GET",
            f"/module_entries?module_id=eq.{module_id}&order=created_at.desc&select=id,data&limit=200",
        ) or []
    except Exception:
        rows = []

    status_filter = (action.get("status") or "").lower() or None
    projects = []
    for r in rows:
        d = r.get("data") or {}
        if status_filter and (d.get("status") or "").lower() != status_filter:
            continue
        projects.append({
            "id": r.get("id"),
            "title": d.get("title") or "Untitled",
            "client": d.get("client") or "",
            "status": d.get("status") or "planning",
            "value": d.get("value") or 0,
            "target_date": d.get("target_date") or "",
        })

    summary_lines = []
    for p in projects[:20]:
        line = f"- {p['title']} ({p['status']})"
        if p["client"]:
            line += f" — {p['client']}"
        if p["value"]:
            try:
                line += f" · ${float(p['value']):,.0f}"
            except (TypeError, ValueError):
                pass
        summary_lines.append(line)
    summary = "\n".join(summary_lines) if summary_lines else "(no matching projects)"

    return {
        "type": "list_projects",
        "result": f"{len(projects)} project{'s' if len(projects) != 1 else ''} found",
        "label": f"📁 {len(projects)} projects" + (f" ({status_filter})" if status_filter else ""),
        "projects": projects,
        "summary": summary,
        "nav": _nav("operate", "projects"),
    }


# ═══════════════════════════════════════════════════════════════════════
# GROW HANDLERS — goals + content
# ═══════════════════════════════════════════════════════════════════════
#
# Goals live in businesses.settings.goals.active_goals (list of objects)
# and businesses.settings.goals.completed_goals. Content posts live at
# businesses.settings.content_calendar.planned_posts. Both are JSONB
# blobs that the corresponding GROW UI panels render.

VALID_GOAL_CATEGORIES = ("contacts", "revenue", "sessions", "engagement", "custom")
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

    new_goal = {
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
    return {
        "type": "create_goal",
        "result": "created",
        "label": f"🎯 New goal: {title} — {label_target} by {end}",
        "goal_id": new_goal["id"],
        "nav": _nav("grow", "goals"),
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
    }


VALID_PLATFORMS = ("instagram", "linkedin", "twitter", "facebook", "tiktok", "youtube", "blog", "other")


async def handle_plan_content(client, biz, action) -> Dict:
    """Add a planned post to settings.content_calendar.planned_posts."""
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

    body = action.get("body") or None

    new_post = {
        "id": f"post-{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        "title": title,
        "body": body,
        "platform": platform,
        "scheduled_date": scheduled_date,
        "status": status_v,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    _, settings = await _fetch_business_settings(client, biz_id)
    cal = settings.get("content_calendar") if isinstance(settings.get("content_calendar"), dict) else {}
    planned = list(cal.get("planned_posts") or [])
    posted = list(cal.get("posted") or [])
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
        await _sb(client, "PATCH", f"/businesses?id=eq.{biz_id}", {"settings": next_settings})
    except Exception as e:
        return _fail("plan_content", f"save failed: {e}")

    return {
        "type": "plan_content",
        "result": "scheduled",
        "label": f"📱 Planned {platform} post: {title} — {scheduled_date}",
        "post_id": new_post["id"],
        "nav": _nav("grow", "content"),
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
    manual_stripe_link = (settings.get("payments") or {}).get("stripe_link") or None
    fin = (settings.get("financial") or {}) if isinstance(settings.get("financial"), dict) else {}
    fin_currency = fin.get("currency")
    fin_categories = fin.get("categories") if isinstance(fin.get("categories"), list) else None
    currency = (action.get("currency") or fin_currency or "USD")

    # Category — practitioner-supplied first, otherwise infer from line
    # items, otherwise fall back to "Other" (or first configured category).
    valid_cats = fin_categories or ["Coaching", "Consulting", "Speaking", "Workshop", "Product", "Other"]
    category = (action.get("category") or "").strip()
    if not category:
        # crude keyword inference from descriptions
        joined = " ".join((it.get("description") or "").lower() for it in norm_items)
        if "coach" in joined:
            category = "Coaching"
        elif "consult" in joined:
            category = "Consulting"
        elif "speak" in joined or "keynote" in joined:
            category = "Speaking"
        elif "workshop" in joined or "training" in joined or "cohort" in joined:
            category = "Workshop"
        elif any(k in joined for k in ("product", "course", "book", "template", "kit")):
            category = "Product"
    if category not in valid_cats:
        category = "Other" if "Other" in valid_cats else valid_cats[0]

    invoice_number = action.get("invoice_number") or await _next_invoice_number(client, biz["id"])
    due_date = action.get("due_date")
    if not due_date:
        due_date = (datetime.now(timezone.utc).date() + timedelta(days=14)).isoformat()

    # Recurrence — when is_recurring=true the row becomes a template.
    # The next instance is generated lazily by the server (on context load)
    # or the client (on InvoicesPanel mount).
    is_recurring = bool(action.get("is_recurring"))
    rec_freq = action.get("recurrence_frequency")
    if rec_freq and rec_freq not in ("weekly", "biweekly", "monthly", "quarterly", "annually"):
        rec_freq = None
    rec_start = action.get("recurrence_start") or due_date
    rec_end_type = action.get("recurrence_end_type") or "never"
    if rec_end_type not in ("never", "after_count", "on_date"):
        rec_end_type = "never"
    rec_end_value = action.get("recurrence_end_value")
    rec_auto_send = bool(action.get("auto_send") or action.get("recurrence_auto_send"))

    # Create the invoice row first with whatever manual link exists.
    # Auto-generation runs AFTER insert so the PATCH carries the new URL
    # onto the row — this also keeps a single source of truth for the URL.
    payload = {
        "business_id": biz["id"],
        "contact_id": contact["id"],
        "invoice_number": invoice_number,
        "status": "draft",
        "items": norm_items,
        "subtotal": subtotal,
        "tax_rate": tax_rate,
        "tax_amount": tax_amount,
        "total": total,
        "currency": currency,
        "category": category,
        "due_date": due_date,
        "notes": action.get("notes") or None,
        "stripe_payment_url": manual_stripe_link,
        "is_recurring": is_recurring and bool(rec_freq),
    }
    if is_recurring and rec_freq:
        payload.update({
            "recurrence_frequency": rec_freq,
            "recurrence_start": rec_start,
            "recurrence_end_type": rec_end_type,
            "recurrence_end_value": rec_end_value,
            "recurrence_auto_send": rec_auto_send,
            "recurrence_paused": False,
            "recurrence_index": 0,
        })
    inserted = await _sb(client, "POST", "/invoices", payload)
    if not inserted:
        return _fail("create_invoice", "insert failed")
    row = inserted[0] if isinstance(inserted, list) else inserted
    invoice_id = row.get("id") if isinstance(row, dict) else None

    # ── Auto-generate a per-invoice Stripe Payment Link for the platform owner ──
    # Other practitioners keep using their own manually-pasted link. The
    # server-side STRIPE_SECRET_KEY is only used for owner businesses —
    # this limits blast radius if the key ever leaks.
    stripe_url = manual_stripe_link
    is_owner = biz.get("owner_id") == PLATFORM_OWNER_ID
    stripe_key = os.environ.get("STRIPE_SECRET_KEY")

    if is_owner and stripe_key and total > 0 and invoice_id:
        try:
            from stripe_proxy import _create_stripe_payment_link
            data = await _create_stripe_payment_link(
                amount=float(total),
                currency=(currency or "usd").lower(),
                description=f"Invoice {invoice_number}",
            )
            if data.get("url"):
                stripe_url = data["url"]
                await _sb(client, "PATCH", f"/invoices?id=eq.{invoice_id}", {
                    "stripe_payment_url": stripe_url,
                })
                print(f"[Chief] Auto-generated Stripe link for {invoice_number}: {stripe_url}", flush=True)
                logger.info(f"stripe auto-link ok invoice={invoice_number} id={data.get('id')}")
        except HTTPException as e:
            print(f"[Chief] Stripe auto-generate failed for {invoice_number}: {e.detail}", flush=True)
            logger.warning(f"stripe auto-link failed: {e.detail}")
        except Exception as e:  # pragma: no cover
            print(f"[Chief] Stripe auto-generate unexpected error: {e}", flush=True)
            logger.warning(f"stripe auto-link unexpected error: {e}")

    label_suffix = ""
    if payload.get("is_recurring"):
        freq_label = {
            "weekly": "weekly", "biweekly": "every 2 weeks", "monthly": "monthly",
            "quarterly": "quarterly", "annually": "annually",
        }.get(rec_freq or "", rec_freq or "")
        label_suffix = f" · 🔄 recurring {freq_label}"
        if rec_auto_send:
            label_suffix += " (auto-send)"
    elif stripe_url:
        label_suffix = " · pay link ready"

    return {
        "type": "create_invoice",
        "result": "drafted_recurring" if payload.get("is_recurring") else "drafted",
        "label": f"💰 Invoice {invoice_number} · {contact.get('name')} · ${total:,.2f}{label_suffix}",
        "nav": {"tab": "operate", "sub": "invoices"},
        "invoice_id": invoice_id,
        "invoice_number": invoice_number,
        "total": total,
        "is_recurring": payload.get("is_recurring", False),
        "stripe_payment_url": stripe_url,
        "stripe_auto_generated": bool(is_owner and stripe_url and stripe_url != manual_stripe_link),
    }


# ─── Cancel / pause recurring invoice ─────────────────────────────────

async def handle_batch_email(client, biz, action) -> Dict:
    """Send the same email body to a list of contacts, replacing
    {contact_name} and {business_name} per recipient. Logs a
    batch_email_sent event for each successful delivery.

    action shape:
        contact_ids:  ["uuid", ...]   (required, max 50)
        subject:      str             (required)
        body:         str             (required, supports {contact_name}/{business_name})
        personalize:  bool            (default true — when false, strip {contact_name})
    """
    contact_ids = action.get("contact_ids") or []
    subject_tpl = (action.get("subject") or "").strip()
    body_tpl = (action.get("body") or "").strip()
    personalize = bool(action.get("personalize", True))

    if not isinstance(contact_ids, list) or not contact_ids:
        return _fail("batch_email", "contact_ids (list) required")
    if len(contact_ids) > 50:
        contact_ids = contact_ids[:50]
    if not subject_tpl or not body_tpl:
        return _fail("batch_email", "subject and body required")

    # Bulk-fetch the contacts
    id_filter = ",".join([f'"{cid}"' for cid in contact_ids])
    try:
        contacts = await _sb(
            client, "GET",
            f"/contacts?id=in.({id_filter})&business_id=eq.{biz['id']}&select=id,name,email"
        ) or []
    except Exception as e:
        return _fail("batch_email", f"contact lookup failed: {e}")

    settings = biz.get("settings") or {}
    et = (settings.get("email_templates") or {}) if isinstance(settings.get("email_templates"), dict) else {}
    sig = et.get("signature") or {}
    from_name = (sig.get("name") or settings.get("practitioner_name") or biz.get("name") or "The Solutionist System").strip()
    reply_to = (sig.get("email") or settings.get("contact_email") or "").strip() or None
    biz_name = biz.get("name") or ""

    sent = 0
    skipped: List[str] = []
    failures: List[str] = []
    sample_subject = subject_tpl

    for c in contacts:
        cid = c.get("id")
        email = (c.get("email") or "").strip()
        name = c.get("name") or "there"
        if not email:
            skipped.append(cid)
            continue
        subj = subject_tpl.replace("{contact_name}", name).replace("{business_name}", biz_name)
        body_personal = body_tpl.replace("{business_name}", biz_name)
        if personalize:
            body_personal = body_personal.replace("{contact_name}", name)
        else:
            body_personal = body_personal.replace("{contact_name}", "").strip()
        # Convert plain newlines to <br> so the practitioner's draft renders
        body_html = body_personal.replace("\r\n", "\n").replace("\n", "<br/>")
        try:
            from email_sender import send_via_resend
            await send_via_resend(
                to_email=email,
                to_name=name,
                from_email=_format_from_email(),
                from_name=from_name,
                subject=subj,
                body=body_html,
                reply_to=reply_to,
            )
            sent += 1
            sample_subject = subj
            await _sb(client, "POST", "/events", {
                "business_id": biz["id"],
                "contact_id": cid,
                "event_type": "batch_email_sent",
                "data": {
                    "subject": subj,
                    "to_email": email,
                    "batch_size": len(contacts),
                },
                "source": "chief_batch_email",
            })
        except Exception as e:
            failures.append(f"{name}:{str(e)[:60]}")

    parts = [f"📧 Batch email: {sent}/{len(contacts)} delivered"]
    if skipped:
        parts.append(f"{len(skipped)} skipped (no email)")
    if failures:
        parts.append(f"{len(failures)} failed")

    return {
        "type": "batch_email",
        "result": f"sent {sent} of {len(contacts)}",
        "label": " · ".join(parts),
        "subject": sample_subject,
        "sent_count": sent,
        "skipped_count": len(skipped),
        "failure_count": len(failures),
    }


async def handle_cancel_recurring_invoice(client, biz, action) -> Dict:
    """Stop a recurring invoice — by default pauses (still visible in
    history); pass mode='cancel' to mark the template cancelled."""
    invoice_id = action.get("invoice_id")
    if not invoice_id:
        return _fail("cancel_recurring_invoice", "invoice_id required")
    mode = action.get("mode") or "pause"
    patch: Dict[str, Any] = {}
    if mode == "cancel":
        patch = {"status": "cancelled", "recurrence_paused": True}
    else:
        patch = {"recurrence_paused": True}
    try:
        await _sb(client, "PATCH", f"/invoices?id=eq.{invoice_id}&business_id=eq.{biz['id']}", patch)
    except Exception as e:
        return _fail("cancel_recurring_invoice", f"patch failed: {e}")
    return {
        "type": "cancel_recurring_invoice",
        "result": "cancelled" if mode == "cancel" else "paused",
        "label": f"🔄 Recurring invoice {'cancelled' if mode == 'cancel' else 'paused'}",
    }


# ─── Server-side recurrence generator ─────────────────────────────────

def _add_freq_step(d: date, freq: str) -> date:
    if freq == "weekly":
        return d + timedelta(days=7)
    if freq == "biweekly":
        return d + timedelta(days=14)
    if freq == "monthly":
        m = d.month + 1
        y = d.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        try:
            return date(y, m, d.day)
        except ValueError:
            # day overflow — clamp to last day of new month
            from calendar import monthrange
            return date(y, m, monthrange(y, m)[1])
    if freq == "quarterly":
        m = d.month + 3
        y = d.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        try:
            return date(y, m, d.day)
        except ValueError:
            from calendar import monthrange
            return date(y, m, monthrange(y, m)[1])
    if freq == "annually":
        try:
            return date(d.year + 1, d.month, d.day)
        except ValueError:
            return date(d.year + 1, d.month, 28)
    return d


async def _generate_missing_recurring_instances(client, biz_id: str) -> int:
    """Server-side counterpart to the client cron. Idempotent — checks
    for an existing child by parent_id+due_date before inserting."""
    try:
        templates = await _sb(
            client, "GET",
            f"/invoices?business_id=eq.{biz_id}&is_recurring=eq.true"
            f"&recurrence_paused=eq.false&status=neq.cancelled&select=*&limit=200",
        ) or []
    except Exception as e:
        print(f"[Chief] recurrence load failed: {e}", flush=True)
        return 0

    today = datetime.now(timezone.utc).date()
    created = 0
    for tpl in templates:
        freq = tpl.get("recurrence_frequency")
        start = tpl.get("recurrence_start")
        if not freq or not start:
            continue
        try:
            start_d = datetime.fromisoformat(start).date() if "T" in start else date.fromisoformat(start)
        except Exception:
            continue

        # how many child instances already exist?
        try:
            children = await _sb(
                client, "GET",
                f"/invoices?recurrence_parent_id=eq.{tpl['id']}&select=id,due_date,recurrence_index",
            ) or []
        except Exception:
            children = []
        child_count = len(children) if isinstance(children, list) else 0

        # cap by after_count
        end_type = tpl.get("recurrence_end_type") or "never"
        end_value = tpl.get("recurrence_end_value")
        if end_type == "after_count":
            try:
                cap = int(end_value or 0)
                if cap > 0 and child_count >= cap:
                    continue
            except ValueError:
                pass

        # next due
        next_due = start_d
        for _ in range(child_count):
            next_due = _add_freq_step(next_due, freq)

        if next_due > today:
            continue

        if end_type == "on_date" and end_value:
            try:
                end_d = date.fromisoformat(end_value)
                if next_due > end_d:
                    continue
            except Exception:
                pass

        # avoid duplicate
        due_iso = next_due.isoformat()
        if any((c.get("due_date") == due_iso) for c in (children or [])):
            continue

        # generate
        try:
            child_number = await _next_invoice_number(client, biz_id)
            await _sb(client, "POST", "/invoices", {
                "business_id": biz_id,
                "contact_id": tpl.get("contact_id"),
                "invoice_number": child_number,
                "status": "draft",
                "items": tpl.get("items") or [],
                "subtotal": tpl.get("subtotal"),
                "tax_rate": tpl.get("tax_rate"),
                "tax_amount": tpl.get("tax_amount"),
                "total": tpl.get("total"),
                "currency": tpl.get("currency") or "USD",
                "category": tpl.get("category") or "Other",
                "due_date": due_iso,
                "notes": tpl.get("notes"),
                "stripe_payment_url": tpl.get("stripe_payment_url"),
                "is_recurring": False,
                "recurrence_parent_id": tpl["id"],
                "recurrence_index": child_count + 1,
            })
            created += 1
            await _sb(client, "POST", "/events", {
                "business_id": biz_id,
                "contact_id": tpl.get("contact_id"),
                "event_type": "recurring_invoice_generated",
                "data": {
                    "template_id": tpl["id"],
                    "template_number": tpl.get("invoice_number"),
                    "child_number": child_number,
                    "due_date": due_iso,
                    "occurrence": child_count + 1,
                    "auto_send": bool(tpl.get("recurrence_auto_send")),
                },
                "source": "chief_recurrence_cron",
            })
        except Exception as e:
            print(f"[Chief] recurrence generation failed for {tpl.get('invoice_number')}: {e}", flush=True)
    return created


# ─── Multi-provider payment config ──────────────────────────────────
# Mirrors src/core/lib/paymentProviders.ts. Reads new
# settings.payment_providers shape and falls back to legacy
# settings.payments.stripe_link so existing businesses don't lose
# config when the multi-provider UI is introduced.

PROVIDER_DEFAULT_LABELS = {
    "stripe": "Pay with Card",
    "square": "Pay with Square",
    "paypal": "Pay with PayPal",
}
PROVIDER_BUTTON_COLORS = {
    "stripe": "#635BFF",
    "square": "#006AFF",
    "paypal": "#0070BA",
}
PROVIDER_ICONS = {
    "stripe": "💳",
    "square": "◻️",
    "paypal": "🅿️",
}

# Inline brand-mark SVGs for the email payment buttons. Email clients
# strip <svg> from many sources but Resend / Gmail / Outlook desktop
# all render inline SVG fine. Sized to 18px white-fill so they sit on
# the colored buttons. Kept in sync with src/core/lib/paymentProviders.ts.
def _brand_icon_svg(provider: str, size: int = 18, fill: str = "#ffffff") -> str:
    if provider == "stripe":
        return (
            f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="{fill}" '
            f'xmlns="http://www.w3.org/2000/svg" aria-label="Stripe">'
            f'<path d="M13.976 9.15c-2.172-.806-3.356-1.426-3.356-2.409 0-.831.683-1.305 1.901-1.305 '
            f'2.227 0 4.515.858 6.09 1.631l.89-5.494C18.252.975 15.697 0 12.165 0 9.667 0 7.589.654 '
            f'6.104 1.872 4.56 3.147 3.757 4.992 3.757 7.218c0 4.039 2.467 5.76 6.476 7.219 2.585.92 '
            f'3.445 1.574 3.445 2.583 0 .98-.84 1.545-2.354 1.545-1.875 0-4.965-.921-6.99-2.109l-.9 '
            f'5.555C5.175 22.99 8.385 24 11.714 24c2.641 0 4.843-.624 6.328-1.813 1.664-1.305 '
            f'2.525-3.236 2.525-5.732 0-4.128-2.524-5.851-6.591-7.305z"/></svg>'
        )
    if provider == "square":
        return (
            f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="{fill}" '
            f'xmlns="http://www.w3.org/2000/svg" aria-label="Square">'
            f'<path d="M4.01 0C1.795 0 0 1.795 0 4.01v15.98C0 22.205 1.795 24 4.01 24h15.98C22.205 24 '
            f'24 22.205 24 19.99V4.01C24 1.795 22.205 0 19.99 0H4.01zm2.751 5.394h10.478c.744 0 '
            f'1.349.605 1.349 1.349v10.514c0 .744-.605 1.349-1.349 1.349H6.761c-.744 0-1.349-.605-1.349-1.349V6.743'
            f'c0-.744.605-1.349 1.349-1.349zm1.493 2.76a.468.468 0 00-.468.468v6.756c0 .259.21.468.468.468h6.756'
            f'a.468.468 0 00.468-.468V8.622a.468.468 0 00-.468-.468H8.254z"/></svg>'
        )
    # paypal — solid (white) on the colored button
    return (
        f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" '
        f'xmlns="http://www.w3.org/2000/svg" aria-label="PayPal">'
        f'<path d="M7.076 21.337H2.47a.641.641 0 01-.633-.74L4.944.901C5.026.382 5.474 0 5.998 0h7.46c2.57 0 '
        f'4.578.543 5.69 1.81 1.01 1.15 1.304 2.42 1.012 4.287-.023.143-.047.288-.077.437-.983 5.05-4.349 '
        f'6.797-8.647 6.797h-2.19c-.524 0-.968.382-1.05.9l-1.12 7.106z" fill="{fill}"/>'
        f'<path d="M23.048 7.667c-.028.179-.06.362-.096.55-1.237 6.351-5.469 8.545-10.874 8.545H9.326c-.661 0-1.218.48-1.321 '
        f'1.132l-.942 5.976-.267 1.693a.696.696 0 00.687.804h4.821c.578 0 1.069-.42 1.159-.99l.048-.248.919-5.832.059-.32'
        f'c.09-.572.582-.992 1.16-.992h.73c4.729 0 8.431-1.92 9.513-7.476.452-2.321.218-4.259-.978-5.622a4.667 4.667 0 '
        f'00-1.336-1.06z" fill="{fill}" opacity="0.85"/></svg>'
    )


def _get_payment_providers(settings: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Read payment_providers with legacy migration. Always returns all
    three slots so callers can iterate without optional handling."""
    incoming = (settings or {}).get("payment_providers") or {}
    if not isinstance(incoming, dict):
        incoming = {}

    def merged(pid: str) -> Dict[str, Any]:
        base = {
            "enabled": False,
            "type": "manual",
            "manual_link": "",
            "label": PROVIDER_DEFAULT_LABELS[pid],
        }
        base.update(incoming.get(pid) or {})
        return base

    out = {pid: merged(pid) for pid in ("stripe", "square", "paypal")}

    # Legacy migration: settings.payments.stripe_link → stripe slot
    legacy_link = ((settings or {}).get("payments") or {}).get("stripe_link") or ""
    if legacy_link and not out["stripe"].get("manual_link"):
        out["stripe"]["enabled"] = True
        out["stripe"]["manual_link"] = legacy_link
        if not out["stripe"].get("label"):
            out["stripe"]["label"] = PROVIDER_DEFAULT_LABELS["stripe"]
    return out


def _enabled_provider_names(providers: Dict[str, Dict[str, Any]], invoice_stripe_url: str) -> List[str]:
    """Return the human-readable list of providers actually rendered into
    an invoice email (Stripe falls back on the auto-generated invoice
    link even if the slot is disabled)."""
    names: List[str] = []
    s = providers.get("stripe", {})
    if invoice_stripe_url or (s.get("enabled") and s.get("manual_link")):
        names.append("Stripe")
    sq = providers.get("square", {})
    if sq.get("enabled") and sq.get("manual_link"):
        names.append("Square")
    pp = providers.get("paypal", {})
    if pp.get("enabled") and pp.get("manual_link"):
        names.append("PayPal")
    return names


def _paypal_url_with_amount(url: str, total: float) -> str:
    """paypal.me supports /<handle>/<amount> deep linking. Append the
    amount when the link is a bare paypal.me URL so the client lands
    on a pre-filled checkout."""
    if not url:
        return ""
    if "paypal.me/" not in url.lower():
        return url
    if total <= 0:
        return url
    if url.endswith("/"):
        return f"{url}{total:.2f}"
    # If a path segment that looks like an amount is already there, keep it.
    tail = url.rsplit("/", 1)[-1]
    try:
        float(tail)
        return url  # already has an amount
    except ValueError:
        return f"{url}/{total:.2f}"


def _build_payment_buttons(biz: Dict[str, Any], invoice: Dict[str, Any], brand_primary: str) -> str:
    """Build the email payment block — one button per enabled provider.
    Falls back to a 'contact us' note when no providers are wired up.

    Stripe gets special handling: the invoice's auto-generated
    stripe_payment_url (if present) takes precedence over the manual
    link, so the platform-owner auto-gen flow keeps working. Other
    providers always use their manual link.
    """
    settings = biz.get("settings") or {}
    providers = _get_payment_providers(settings)
    invoice_stripe = (invoice.get("stripe_payment_url") or "").strip()
    total = float(invoice.get("total") or 0)
    total_fmt = f"${total:,.2f}"

    btn_base = (
        "display:block;padding:14px 32px;color:#fff;text-decoration:none;"
        "border-radius:8px;font-size:16px;font-weight:bold;text-align:center;"
        "margin-bottom:10px;line-height:1;"
    )
    icon_wrap = (
        'display:inline-block;vertical-align:middle;margin-right:8px;'
    )
    label_wrap = 'display:inline-block;vertical-align:middle;'

    buttons: List[str] = []

    def _btn(provider: str, url: str, label: str) -> str:
        return (
            f'<a href="{url}" style="{btn_base}background:{PROVIDER_BUTTON_COLORS[provider]};">'
            f'<span style="{icon_wrap}">{_brand_icon_svg(provider)}</span>'
            f'<span style="{label_wrap}">{label}</span></a>'
        )

    # Stripe — auto-gen link wins over manual
    stripe = providers.get("stripe", {})
    stripe_url = invoice_stripe or (stripe.get("manual_link") if stripe.get("enabled") else "")
    if stripe_url:
        label = stripe.get("label") or PROVIDER_DEFAULT_LABELS["stripe"]
        buttons.append(_btn("stripe", stripe_url, label))

    # Square
    square = providers.get("square", {})
    if square.get("enabled") and square.get("manual_link"):
        label = square.get("label") or PROVIDER_DEFAULT_LABELS["square"]
        buttons.append(_btn("square", square["manual_link"], label))

    # PayPal
    paypal = providers.get("paypal", {})
    if paypal.get("enabled") and paypal.get("manual_link"):
        label = paypal.get("label") or PROVIDER_DEFAULT_LABELS["paypal"]
        pp_url = _paypal_url_with_amount(paypal["manual_link"], total)
        buttons.append(_btn("paypal", pp_url, label))

    if not buttons:
        return (
            f'<div style="margin:24px 0;padding:14px 16px;background:#f9f7f2;'
            f'border-left:3px solid {brand_primary};border-radius:0 6px 6px 0;'
            f'font-size:13px;color:#666;line-height:1.6;">'
            f'Please reply to this email for payment arrangements.</div>'
        )

    header = (
        f'<div style="text-align:center;margin-top:24px;margin-bottom:12px;'
        f'font-size:14px;color:#666;font-weight:600;">'
        f'Pay This Invoice — {total_fmt}</div>'
    )
    return header + "\n".join(buttons)


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
    total = float(invoice.get("total") or 0)
    total_fmt = f"${total:,.2f}"

    line_rows = "".join(
        f'<tr><td style="padding:10px 0;border-bottom:1px solid #eee;">{it.get("description","")}</td>'
        f'<td style="padding:10px 0;border-bottom:1px solid #eee;text-align:right;color:#666;">× {it.get("quantity",0)}</td>'
        f'<td style="padding:10px 0;border-bottom:1px solid #eee;text-align:right;color:#666;">${it.get("unit_price",0):.2f}</td>'
        f'<td style="padding:10px 0;border-bottom:1px solid #eee;text-align:right;font-weight:600;">${it.get("total",0):.2f}</td></tr>'
        for it in (invoice.get("items") or [])
    )

    # Multi-provider payment buttons (Stripe / Square / PayPal). The
    # auto-generated invoice-specific Stripe link still wins over the
    # manual link for the Stripe button. Other providers use their
    # manual links. Falls back to "contact us" note when nothing is
    # configured.
    payment_block = _build_payment_buttons(biz, invoice, primary)

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
    print(f"[Chief] send_invoice START — invoice_id={invoice_id!r}", flush=True)

    # Sentinel support: "latest" resolves to the most recent draft/sent
    # invoice for this business. Lets the Chief chain without UUIDs.
    if invoice_id == "latest":
        latest = await _sb(client, "GET",
            f"/invoices?business_id=eq.{biz['id']}&order=created_at.desc&limit=1&select=id")
        if not latest:
            print(f"[Chief] send_invoice — 'latest' but no invoices exist for business", flush=True)
            return _fail("send_invoice", "no invoices found")
        invoice_id = latest[0]["id"]
        print(f"[Chief] send_invoice — 'latest' resolved to {invoice_id}", flush=True)

    if not invoice_id:
        print(f"[Chief] send_invoice ABORT — invoice_id missing. action keys: {list(action.keys())}", flush=True)
        return _fail("send_invoice", "invoice_id required")

    rows = await _sb(client, "GET",
        f"/invoices?id=eq.{invoice_id}&business_id=eq.{biz['id']}&limit=1&select=*")
    print(f"[Chief] send_invoice — invoice found: {bool(rows)}, row_count: {len(rows or [])}", flush=True)
    if not rows:
        return _fail("send_invoice", f"Invoice {invoice_id} not found")

    invoice = rows[0]
    print(f"[Chief] send_invoice — invoice_number: {invoice.get('invoice_number')}, "
          f"status: {invoice.get('status')}, total: {invoice.get('total')}, "
          f"contact_id: {invoice.get('contact_id')}, "
          f"items_count: {len(invoice.get('items') or [])}", flush=True)

    if not invoice.get("contact_id"):
        print(f"[Chief] send_invoice ABORT — invoice {invoice.get('invoice_number')} has no contact_id", flush=True)
        return _fail("send_invoice", "invoice has no linked contact")

    contact = await _validate_contact(client, biz["id"], invoice["contact_id"])
    print(f"[Chief] send_invoice — contact: {contact.get('name') if contact else 'NOT FOUND'}, "
          f"email: {contact.get('email') if contact else '—'}", flush=True)
    if not contact:
        return _fail("send_invoice", "contact not found")
    if not contact.get("email"):
        return _fail("send_invoice", f"{contact.get('name')} has no email on file")

    # Backfill the invoice's stripe_payment_url from settings on the fly
    # in case the invoice was created before the link was configured.
    settings = biz.get("settings") or {}
    current_stripe_on_invoice = invoice.get("stripe_payment_url")
    stripe_from_settings = (settings.get("payments") or {}).get("stripe_link")
    print(f"[Chief] send_invoice — stripe_url on invoice: {current_stripe_on_invoice or 'NONE'}, "
          f"settings fallback: {stripe_from_settings or 'NONE'}", flush=True)
    if not current_stripe_on_invoice and stripe_from_settings:
        await _sb(client, "PATCH", f"/invoices?id=eq.{invoice_id}", {
            "stripe_payment_url": stripe_from_settings,
        })
        invoice["stripe_payment_url"] = stripe_from_settings
        print(f"[Chief] send_invoice — backfilled stripe_payment_url from settings", flush=True)

    # Sanity-check the invoice has enough to render a meaningful email
    if float(invoice.get("total") or 0) <= 0:
        print(f"[Chief] send_invoice WARNING — invoice {invoice.get('invoice_number')} total is 0; sending anyway", flush=True)
    if not (invoice.get("items") or []):
        print(f"[Chief] send_invoice WARNING — invoice {invoice.get('invoice_number')} has no line items", flush=True)

    print(f"[Chief] send_invoice — calling _send_invoice_email…", flush=True)
    ok, error_detail, provider_id = await _send_invoice_email(client, biz, invoice, contact)
    print(f"[Chief] send_invoice — result: ok={ok}, error={error_detail!r}, provider_id={provider_id}", flush=True)
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
    # Snapshot which providers were included in the email so the
    # contact timeline can show them ("Payment options: Stripe, PayPal").
    providers_in_email = _enabled_provider_names(
        _get_payment_providers(biz.get("settings") or {}),
        invoice.get("stripe_payment_url") or "",
    )
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
            "payment_providers": providers_in_email,
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
    # Same "latest" sentinel support as send_invoice — resolves to the
    # most recent invoice for this business.
    if invoice_id == "latest":
        latest = await _sb(client, "GET",
            f"/invoices?business_id=eq.{biz['id']}&order=created_at.desc&limit=1&select=id")
        if not latest:
            return _fail("mark_invoice_paid", "no invoices found")
        invoice_id = latest[0]["id"]
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


# ═══════════════════════════════════════════════════════════════════════
# PRODUCTS & SERVICES
# ═══════════════════════════════════════════════════════════════════════

async def _find_product_by_name(client, biz_id: str, name: str) -> Optional[Dict[str, Any]]:
    if not name:
        return None
    safe = name.replace("%", "")
    rows = await _sb(client, "GET",
        f"/products?business_id=eq.{biz_id}&name=ilike.*{safe}*&select=*&limit=5")
    if not rows:
        return None
    # Exact match wins, otherwise the first ilike hit
    for r in rows:
        if (r.get("name") or "").strip().lower() == name.strip().lower():
            return r
    return rows[0]


async def handle_create_product(client, biz, action) -> Dict:
    name = (action.get("name") or "").strip()
    if not name:
        return _fail("create_product", "name required")

    product_type = (action.get("type") or action.get("product_type") or "service").strip().lower()
    if product_type not in ("service", "digital", "physical", "package"):
        product_type = "service"

    pricing_type = (action.get("pricing_type") or "fixed").strip().lower()
    if pricing_type not in ("fixed", "hourly", "per_session", "subscription", "custom"):
        pricing_type = "fixed"

    settings = biz.get("settings") or {}
    fin = (settings.get("financial") or {}) if isinstance(settings.get("financial"), dict) else {}
    currency = (action.get("currency") or fin.get("currency") or "USD").upper()

    duration = action.get("duration") or action.get("duration_minutes")
    try:
        duration_int = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_int = None

    try:
        price = float(action.get("price") or 0)
    except (TypeError, ValueError):
        price = 0.0

    payload: Dict[str, Any] = {
        "business_id": biz["id"],
        "name": name,
        "description": action.get("description") or None,
        "type": product_type,
        "price": price,
        "currency": currency,
        "pricing_type": pricing_type,
        "duration_minutes": duration_int,
        "auto_deliver": bool(action.get("auto_deliver", False)),
        "status": "active",
        "display_on_website": bool(action.get("display_on_website", True)),
        "includes": action.get("includes") or [],
    }

    rows = await _sb(client, "POST", "/products", payload)
    if not rows:
        return _fail("create_product", "Could not create product")
    product = rows[0]
    product_id = product.get("id")

    # Auto-generate a Stripe Payment Link for digital products with a price,
    # but only for the platform owner (matches invoice behavior above).
    is_owner = biz.get("owner_id") == PLATFORM_OWNER_ID
    if (
        product_type == "digital"
        and price > 0
        and is_owner
        and os.environ.get("STRIPE_SECRET_KEY")
        and product_id
    ):
        try:
            from stripe_proxy import _create_stripe_payment_link
            data = await _create_stripe_payment_link(
                amount=price,
                currency=currency.lower(),
                description=name,
            )
            if data.get("url"):
                await _sb(client, "PATCH", f"/products?id=eq.{product_id}",
                          {"stripe_payment_url": data["url"]})
                product["stripe_payment_url"] = data["url"]
        except Exception as e:
            logger.warning(f"product stripe link failed: {e}")

    price_label = (
        f"${price:,.2f}/session" if pricing_type == "per_session"
        else f"${price:,.2f}/hr" if pricing_type == "hourly"
        else f"${price:,.2f}/mo" if pricing_type == "subscription"
        else f"${price:,.2f}" if price > 0
        else "Contact for pricing"
    )
    return {
        "type": "create_product",
        "result": "created",
        "label": f"🛍️ {name} — {price_label}",
        "product_id": product_id,
        "nav": _nav("build", "products"),
    }


async def handle_update_product(client, biz, action) -> Dict:
    product_id = action.get("product_id")
    if not product_id and action.get("name"):
        match = await _find_product_by_name(client, biz["id"], action["name"])
        if match:
            product_id = match["id"]
    if not product_id:
        return _fail("update_product", "product_id or name required")

    patch: Dict[str, Any] = {}
    for k in ("name", "description", "type", "currency", "pricing_type",
              "image_url", "digital_file_url", "stripe_payment_url",
              "status"):
        if k in action and action[k] is not None:
            patch[k] = action[k]
    if "price" in action:
        try:
            patch["price"] = float(action["price"])
        except (TypeError, ValueError):
            pass
    if "duration_minutes" in action or "duration" in action:
        d = action.get("duration_minutes", action.get("duration"))
        try:
            patch["duration_minutes"] = int(d) if d is not None else None
        except (TypeError, ValueError):
            pass
    if "auto_deliver" in action:
        patch["auto_deliver"] = bool(action["auto_deliver"])
    if "display_on_website" in action:
        patch["display_on_website"] = bool(action["display_on_website"])
    if "includes" in action and isinstance(action["includes"], list):
        patch["includes"] = action["includes"]

    if not patch:
        return _fail("update_product", "no fields to update")

    rows = await _sb(client, "PATCH", f"/products?id=eq.{product_id}", patch)
    if not rows:
        return _fail("update_product", "update failed")
    product = rows[0]
    return {
        "type": "update_product",
        "result": "updated",
        "label": f"🛍️ Updated {product.get('name')}",
        "product_id": product_id,
        "nav": _nav("build", "products"),
    }


async def handle_list_products(client, biz, action) -> Dict:
    status_filter = (action.get("status") or "").strip().lower()
    type_filter = (action.get("type") or action.get("product_type") or "").strip().lower()

    qs = f"business_id=eq.{biz['id']}&select=id,name,type,price,currency,pricing_type,status&order=type.asc,name.asc&limit=100"
    if status_filter in ("active", "draft", "archived"):
        qs += f"&status=eq.{status_filter}"
    if type_filter in ("service", "digital", "physical", "package"):
        qs += f"&type=eq.{type_filter}"

    rows = await _sb(client, "GET", f"/products?{qs}") or []
    if not rows:
        return {
            "type": "list_products",
            "result": "empty",
            "label": "🛍️ No products yet",
            "products": [],
            "nav": _nav("build", "products"),
        }

    summary_lines = [
        f"{r.get('name')} — ${float(r.get('price') or 0):,.2f} ({r.get('type')}, {r.get('status')})"
        for r in rows[:25]
    ]
    label = f"🛍️ {len(rows)} product{'s' if len(rows) != 1 else ''}"
    if len(rows) > 25:
        label += " (showing first 25)"
    return {
        "type": "list_products",
        "result": "ok",
        "label": label,
        "summary": "\n".join(summary_lines),
        "products": rows,
        "nav": _nav("build", "products"),
    }


# ═══════════════════════════════════════════════════════════════════════
# CONVERSATION RECALL — search archived chats
# ═══════════════════════════════════════════════════════════════════════

def _parse_time_range_days(time_range: Optional[str]) -> int:
    """Accept '7d', '30d', '24h', '2w', or a bare number. Default 7 days."""
    s = (time_range or "").strip().lower()
    if not s:
        return 7
    try:
        if s.endswith("h"):
            hours = int(s[:-1])
            return max(1, hours // 24 if hours >= 24 else 1)
        if s.endswith("d"):
            return max(1, int(s[:-1]))
        if s.endswith("w"):
            return max(1, int(s[:-1]) * 7)
        return max(1, int(s))
    except (ValueError, TypeError):
        return 7


async def handle_recall_conversation(client, biz, action) -> Dict:
    """Search archived chief_conversations rows for relevant context.
    Filters by `query` (matches summary or any key_topic) and `time_range`."""
    query = (action.get("query") or "").strip()
    days = _parse_time_range_days(action.get("time_range"))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    rows = await _sb(
        client, "GET",
        f"/chief_conversations?business_id=eq.{biz['id']}&ended_at=gte.{since}"
        f"&order=ended_at.desc&limit=10"
        f"&select=id,summary,key_topics,actions_taken,started_at,ended_at,message_count",
    ) or []

    if not rows:
        return {
            "type": "recall_conversation",
            "result": "no_conversations",
            "label": "📜 No recent conversations to recall",
            "summary": (
                f"I don't have any archived conversations from the last {days} days. "
                "Conversations auto-archive after a few hours of inactivity."
            ),
            "conversations": [],
        }

    if query:
        q = query.lower()
        relevant = [
            c for c in rows
            if q in (c.get("summary") or "").lower()
            or any(q in (t or "").lower() for t in (c.get("key_topics") or []))
        ]
        # Fall back to all matches when nothing scored — gives the AI raw
        # material to answer "anything from last week?" type queries.
        rows = relevant or rows

    summaries: List[str] = []
    for conv in rows[:5]:
        ended = (conv.get("ended_at") or "")[:10]
        summary = conv.get("summary") or "No summary recorded."
        topics = ", ".join(conv.get("key_topics") or []) or "—"
        msg_count = conv.get("message_count") or 0
        summaries.append(
            f"**{ended}** ({msg_count} messages · topics: {topics})\n{summary}"
        )

    return {
        "type": "recall_conversation",
        "result": f"{len(rows)} conversations",
        "label": f"📜 Found {len(rows)} recent conversation{'s' if len(rows) != 1 else ''}",
        "conversations": summaries,
        "summary": "\n\n".join(summaries),
    }


ACTION_HANDLERS = {
    "draft_nurture":         handle_draft_nurture,
    "draft_email":           handle_draft_email,
    "draft_and_send":        handle_draft_and_send,
    "create_session":        handle_create_session,
    "update_contact_status": handle_update_contact_status,
    "update_contact_health": handle_update_contact_health,
    "update_contact":         handle_update_contact,
    "delete_contact":         handle_delete_contact,
    "update_session":         handle_update_session,
    "create_project":         handle_create_project,
    "update_project":         handle_update_project,
    "list_projects":          handle_list_projects,
    "open_documents":         handle_open_documents,
    "open_calendar":          handle_open_calendar,
    "show_revenue":           handle_show_revenue,
    "create_goal":            handle_create_goal,
    "check_goals":            handle_check_goals,
    "plan_content":           handle_plan_content,
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
    "cancel_recurring_invoice":   handle_cancel_recurring_invoice,
    "batch_email":                handle_batch_email,
    # Products & Services
    "create_product":             handle_create_product,
    "update_product":             handle_update_product,
    "list_products":              handle_list_products,
    # Conversation recall
    "recall_conversation":        handle_recall_conversation,
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


def _resolve_action_references(action: Dict[str, Any], prior_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Substitute references to earlier action results inside a later action.

    The Chief often emits a create_X followed by a send_X in the same turn.
    The model can't know the UUID that create_X will mint, so we let it
    reference earlier actions in three ways:

      1. Sentinel "latest" — e.g. {"invoice_id": "latest"} — the handler
         resolves this itself by querying the DB.
      2. Typed reference — e.g. {"invoice_id": "@create_invoice.invoice_id"}
         pulls the field from the most recent matching prior result.
      3. Auto-backfill — if the action is send_invoice / mark_invoice_paid
         and invoice_id is missing, but a prior create_invoice succeeded,
         we copy its invoice_id in automatically.
    """
    resolved = dict(action)
    atype = resolved.get("type")

    def _lookup(ref: str) -> Any:
        # Format: @<action_type>.<field>
        if not ref.startswith("@") or "." not in ref:
            return ref
        spec = ref[1:]
        ref_type, _, ref_field = spec.partition(".")
        for prev in reversed(prior_results):
            if prev.get("type") != ref_type:
                continue
            # Top-level wins; fall back to nav.* (older handlers stash
            # ids inside the nav payload — e.g. nav.contact_id).
            if ref_field in prev and prev[ref_field] is not None:
                return prev[ref_field]
            nav = prev.get("nav") or {}
            if isinstance(nav, dict) and ref_field in nav and nav[ref_field] is not None:
                return nav[ref_field]
        print(f"[Chief] reference unresolved: {ref}", flush=True)
        return ref  # unresolved — let the handler's validation surface it

    # Phase 1: resolve any @type.field references in string values
    for k, v in list(resolved.items()):
        if isinstance(v, str) and v.startswith("@") and "." in v:
            resolved[k] = _lookup(v)

    # Phase 2: auto-backfill invoice_id when missing — a very common
    # multi-action pattern where the Chief emits send_invoice right after
    # create_invoice without an explicit reference.
    if atype in ("send_invoice", "mark_invoice_paid") and not resolved.get("invoice_id"):
        for prev in reversed(prior_results):
            if prev.get("type") == "create_invoice" and prev.get("invoice_id"):
                resolved["invoice_id"] = prev["invoice_id"]
                print(f"[Chief] auto-chained {atype}.invoice_id from create_invoice -> {prev['invoice_id']}", flush=True)
                break

    return resolved


async def _execute_actions(client, biz, actions: List[Dict]) -> List[Dict]:
    results: List[Dict[str, Any]] = []
    for action in actions:
        atype = action.get("type")
        handler = ACTION_HANDLERS.get(atype)
        if not handler:
            results.append(_fail(atype or "unknown", f"Unknown action type '{atype}'"))
            continue
        # Substitute references from earlier results. Lets the Chief do
        # create_invoice → send_invoice in one turn without knowing the
        # freshly-minted UUID.
        resolved = _resolve_action_references(action, results)
        try:
            res = await handler(client, biz, resolved)
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


# ═══════════════════════════════════════════════════════════════════════
# CHIEF INTELLIGENCE — pattern learning, voice examples, daily priorities,
# mentor mode, smart suggestions, session continuity, assistant naming.
# All helpers below are best-effort: if a probe fails, we degrade silently
# rather than poisoning the chat response.
# ═══════════════════════════════════════════════════════════════════════

def _today_utc() -> "date":
    return datetime.now(timezone.utc).date()


def _safe_iso(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _is_today(dt_str: Optional[str]) -> bool:
    dt = _safe_iso(dt_str)
    return bool(dt and dt.date() == _today_utc())


def _is_past_due(dt_str: Optional[str]) -> bool:
    dt = _safe_iso(dt_str)
    return bool(dt and dt.date() < _today_utc())


def _is_recent_event(event: Dict[str, Any], days: int = 1) -> bool:
    dt = _safe_iso(event.get("created_at"))
    if not dt:
        return False
    return (datetime.now(timezone.utc) - dt).days < days


async def _upsert_pattern(client: httpx.AsyncClient, biz_id: str,
                          pattern_type: str, pattern_key: str,
                          value: Dict[str, Any], increment: bool = False) -> None:
    """Insert or merge a chief_patterns row. Confidence ramps with occurrences."""
    try:
        existing = await _sb(
            client, "GET",
            f"/chief_patterns?business_id=eq.{biz_id}"
            f"&pattern_type=eq.{pattern_type}&pattern_key=eq.{pattern_key}"
            f"&select=id,occurrences,pattern_value&limit=1",
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        if existing:
            row = existing[0]
            merged = {**(row.get("pattern_value") or {}), **(value or {})}
            occ = (row.get("occurrences") or 1) + (1 if increment else 0)
            conf = min(0.95, 0.5 + (occ * 0.05))
            await _sb(client, "PATCH", f"/chief_patterns?id=eq.{row['id']}", {
                "pattern_value": merged,
                "occurrences": occ,
                "confidence": conf,
                "last_seen": now_iso,
            })
        else:
            await _sb(client, "POST", "/chief_patterns", {
                "business_id": biz_id,
                "pattern_type": pattern_type,
                "pattern_key": pattern_key,
                "pattern_value": value or {},
                "occurrences": 1,
                "confidence": 0.5,
            })
    except Exception as e:  # pragma: no cover
        logger.warning(f"_upsert_pattern failed: {e}")


async def _learn_patterns(client: httpx.AsyncClient, biz: Dict[str, Any],
                          actions_taken: List[Dict[str, Any]]) -> None:
    """Quietly learn from the practitioner's behavior. Called after each
    Chief turn via asyncio.create_task so it never blocks the response."""
    try:
        if not (biz.get("settings") or {}).get("chief_preferences", {}).get("learn_patterns", True):
            return
        biz_id = biz["id"]

        # Draft approval / dismissal patterns
        for action in actions_taken or []:
            atype = action.get("type")
            qid = action.get("queue_id")
            if not qid or atype not in ("approve_draft", "dismiss_draft", "edit_draft"):
                continue
            drafts = await _sb(
                client, "GET",
                f"/agent_queue?id=eq.{qid}&select=subject,body,agent&limit=1",
            )
            if not drafts:
                continue
            d = drafts[0]
            agent_key = d.get("agent") or "unknown"
            verb = "approved" if atype in ("approve_draft", "edit_draft") else "dismissed"
            await _upsert_pattern(
                client, biz_id, "draft_preference", f"{verb}_{agent_key}",
                {
                    "subject": (d.get("subject") or "")[:140],
                    "body_preview": (d.get("body") or "")[:240],
                    f"{verb}_at": datetime.now(timezone.utc).isoformat(),
                },
                increment=True,
            )

        # Work-schedule activity (when does the practitioner show up?)
        now = datetime.now(timezone.utc)
        await _upsert_pattern(
            client, biz_id, "work_schedule", "activity",
            {
                "last_active": now.isoformat(),
                "day_of_week": now.strftime("%A").lower(),
                "hour": now.hour,
            },
            increment=True,
        )
    except Exception as e:  # pragma: no cover
        logger.warning(f"_learn_patterns failed: {e}")


async def _learn_patterns_async(biz: Dict[str, Any], actions_taken: List[Dict[str, Any]]) -> None:
    """Background task wrapper — owns its own httpx client so it
    survives chief_chat returning."""
    try:
        async with httpx.AsyncClient() as client:
            await _learn_patterns(client, biz, actions_taken)
    except Exception as e:  # pragma: no cover
        logger.warning(f"_learn_patterns_async failed: {e}")


async def _record_mentor_shown_async(biz_id: str) -> None:
    try:
        async with httpx.AsyncClient() as client:
            await _mark_mentor_tip_shown(client, biz_id)
    except Exception as e:  # pragma: no cover
        logger.warning(f"_record_mentor_shown_async failed: {e}")


async def _get_voice_examples(client: httpx.AsyncClient, biz_id: str, limit: int = 5) -> str:
    """Pull recent approved drafts to anchor the AI in the practitioner's voice."""
    try:
        rows = await _sb(
            client, "GET",
            f"/agent_queue?business_id=eq.{biz_id}&status=eq.sent"
            f"&order=reviewed_at.desc.nullslast,created_at.desc&limit={limit}"
            f"&select=subject,body,agent",
        )
    except Exception:
        rows = []
    if not rows:
        return ""
    blocks: List[str] = []
    for d in rows:
        body = (d.get("body") or "").strip()
        if not body:
            continue
        body_preview = body[:280]
        subj = (d.get("subject") or "").strip()
        blocks.append(f"Subject: {subj}\n{body_preview}")
    if not blocks:
        return ""
    return (
        "PRACTITIONER'S APPROVED WRITING STYLE — match this tone and voice.\n"
        "Notice greeting style, sentence length, formality, sign-off, personality.\n"
        "If they write 'Hey' not 'Dear', use 'Hey'. If they keep it short, keep it short.\n"
        "Mirror THEM, not generic business writing.\n\n"
        + "\n---\n".join(blocks)
    )


async def _get_session_context(client: httpx.AsyncClient, biz_id: str) -> str:
    """Recap of what the Chief has done in the last ~2 hours so the AI
    can reference it naturally without re-explaining."""
    try:
        two_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        rows = await _sb(
            client, "GET",
            f"/events?business_id=eq.{biz_id}"
            f"&event_type=like.chief_*&created_at=gte.{two_hours_ago}"
            f"&order=created_at.desc&limit=10"
            f"&select=event_type,data,created_at",
        )
    except Exception:
        rows = []
    if not rows:
        return ""
    parts: List[str] = []
    for e in rows[:5]:
        data = e.get("data") or {}
        label = data.get("label") or data.get("subject") or e.get("event_type", "")
        if label:
            parts.append(f"- {label}")
    if not parts:
        return ""
    return (
        "EARLIER THIS SESSION (reference naturally if relevant — don't re-explain):\n"
        + "\n".join(parts)
    )


def _build_daily_priorities(biz: Dict[str, Any], ctx: Dict[str, Any]) -> List[str]:
    """Top 3 things the practitioner needs to know about TODAY.
    Reads from the same context dict that the prompt is built from."""
    out: List[str] = []

    # Sessions today
    sessions_upcoming = ctx.get("sessions_upcoming") or []
    sessions_today = [
        s for s in sessions_upcoming
        if _is_today(s.get("scheduled_for"))
    ]
    if sessions_today:
        names = ", ".join(
            (s.get("contacts") or {}).get("name") or s.get("contact_name") or "someone"
            for s in sessions_today[:3]
        )
        out.append(
            f"You have {len(sessions_today)} session(s) today with {names}."
        )

    # Overdue invoices
    overdue = [
        i for i in (ctx.get("invoices") or [])
        if i.get("status") in ("sent", "viewed")
        and _is_past_due(i.get("due_date"))
    ]
    if overdue:
        total = sum(float(i.get("total") or 0) for i in overdue)
        out.append(
            f"${total:,.0f} in overdue invoices across {len(overdue)} client(s)."
        )

    # Hot leads
    hot_leads = [
        c for c in (ctx.get("contacts") or [])
        if c.get("status") == "lead" and (c.get("health_score") or 0) > 70
    ]
    if hot_leads:
        out.append(
            f"{len(hot_leads)} warm lead(s) — {hot_leads[0].get('name')} is especially engaged."
        )

    # Recent payments (3 days)
    recent_payments = [
        e for e in (ctx.get("recent_events") or [])
        if e.get("event_type") in ("invoice_paid_auto", "invoice_paid", "product_sold")
        and _is_recent_event(e, days=3)
    ]
    if recent_payments:
        total_paid = sum(float((e.get("data") or {}).get("amount") or 0) for e in recent_payments)
        if total_paid > 0:
            out.append(f"${total_paid:,.0f} received in the last 3 days.")

    # Autopilot report — what got handled vs what's waiting
    auto_actions = [
        e for e in (ctx.get("recent_events") or [])
        if e.get("event_type") == "chief_auto_approved"
        and _is_recent_event(e, days=1)
    ]
    held = ctx.get("queue") or []
    if auto_actions or held:
        text = ""
        if auto_actions:
            text = f"Your team handled {len(auto_actions)} thing(s) automatically."
        if held:
            text += (" " if text else "") + f"{len(held)} waiting for your review."
        if text:
            out.append(text)

    # At-risk contacts
    at_risk = [
        c for c in (ctx.get("contacts") or [])
        if (c.get("health_score") or 50) < 30
        and c.get("status") not in ("inactive", "churned")
    ]
    if at_risk:
        out.append(
            f"{len(at_risk)} contact(s) at risk — {at_risk[0].get('name')} needs attention."
        )

    return out[:3]


def _format_priorities_block(priorities: List[str]) -> str:
    if not priorities:
        return ""
    bullets = "\n".join(f"- {p}" for p in priorities)
    return (
        "TODAY'S PRIORITIES (weave these into your greeting — be specific, "
        "name names, cite numbers):\n" + bullets
    )


async def _should_show_mentor_tip(client: httpx.AsyncClient, biz: Dict[str, Any]) -> bool:
    """Mentor tips run on a cooldown that opens after 24h (new business)
    or 168h (after 60d). Returns False when mentor mode is OFF."""
    prefs = (biz.get("settings") or {}).get("chief_preferences") or {}
    if prefs.get("mentor_mode") is False:
        return False
    biz_id = biz["id"]

    biz_age_days = 999
    created = _safe_iso(biz.get("created_at"))
    if created:
        biz_age_days = (datetime.now(timezone.utc) - created).days

    try:
        rows = await _sb(
            client, "GET",
            f"/chief_patterns?business_id=eq.{biz_id}"
            f"&pattern_type=eq.mentor_tip&pattern_key=eq.last_shown"
            f"&select=last_seen&limit=1",
        )
    except Exception:
        rows = []

    if not rows:
        return True

    last = _safe_iso(rows[0].get("last_seen"))
    if not last:
        return True
    hours_since = (datetime.now(timezone.utc) - last).total_seconds() / 3600
    cooldown = 24 if biz_age_days < 60 else 168
    return hours_since > cooldown


async def _mark_mentor_tip_shown(client: httpx.AsyncClient, biz_id: str) -> None:
    await _upsert_pattern(
        client, biz_id, "mentor_tip", "last_shown",
        {"shown_at": datetime.now(timezone.utc).isoformat()},
        increment=True,
    )


_MENTOR_TIP_MARKERS = (
    "i've noticed", "i have noticed", "quick thought",
    "by the way", "side note",
)


def _looks_like_mentor_tip(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(m in low for m in _MENTOR_TIP_MARKERS)


def _build_assistant_name_block(biz: Dict[str, Any]) -> str:
    prefs = (biz.get("settings") or {}).get("chief_preferences") or {}
    name = (prefs.get("assistant_name") or "").strip()
    practitioner = (biz.get("settings") or {}).get("practitioner_name") or ""
    first_name = practitioner.split()[0] if practitioner else ""
    if name:
        return (
            f"YOUR NAME:\n"
            f"The practitioner named you \"{name}\". Use it naturally — "
            f"once in the greeting is enough, e.g. 'Good morning"
            f"{(', ' + first_name) if first_name else ''}. It\\'s {name}.' "
            f"Don\\'t overuse it. You\\'re still the Chief of Staff — "
            f"the name is personal, the role is the same."
        )
    return (
        "YOUR NAME:\n"
        "You are the Chief of Staff. No personal name has been set. "
        "If asked 'what's your name', let them know they can pick one in "
        "BUILD → Settings → Your Assistant. Don't suggest a name yourself."
    )


def _build_mentor_block(active: bool) -> str:
    if not active:
        return "MENTOR MODE: OFF — never share business observations or tips this turn."
    return (
        "MENTOR MODE: active — you may share AT MOST ONE casual observation, "
        "if directly relevant to what just happened.\n"
        "Voice rules:\n"
        "- Start with what you DID, then add the observation.\n"
        "- Use 'I've noticed', 'quick thought', or 'by the way' — never "
        "'tip', 'lesson', 'best practice', or 'pro tip'.\n"
        "- One sentence maximum. Casual, specific, never preachy.\n"
        "- Skip the observation entirely if nothing notable applies.\n"
        "Examples — RIGHT: 'Invoice sent. By the way — I've noticed the "
        "ones you send same-day tend to get paid about a week faster.' / "
        "WRONG: 'Tip: Same-day invoices increase collection rates by 30%.'"
    )


def _build_suggestions_block(active: bool) -> str:
    if not active:
        return "SMART SUGGESTIONS: OFF — do not append a 'want me to…' next-step suggestion this turn."
    return (
        "SMART SUGGESTIONS: active — after completing an action, OFFER one clear next step.\n"
        "- Don't ask, offer. Keep it to ONE option.\n"
        "- After creating a contact: 'Want me to send a welcome email or schedule an intro call?'\n"
        "- After sending an invoice: 'I can set a payment reminder for 7 days from now if you want.'\n"
        "- After a session is marked completed: 'Want me to draft a follow-up and book the next session?'\n"
        "- After a payment lands: 'Nice. Want me to send a thank-you note?'\n"
        "- After creating a project: 'Should I break this into tasks and add milestones to your calendar?'\n"
        "- After running agents: 'Found N items. Want to review them now or hold them?'\n"
        "Skip suggestions if no action was taken or if the practitioner just asked for information."
    )


def _build_system_prompt(ctx: Dict[str, Any], is_greeting: bool,
                         view: Optional[CurrentContext] = None,
                         view_detail: Optional[Dict] = None,
                         time_of_day: Optional[str] = None,
                         resume_note: Optional[ResumeNote] = None,
                         mode: Optional[str] = None,
                         voice_examples: str = "",
                         session_context: str = "",
                         priorities: Optional[List[str]] = None,
                         mentor_active: bool = False,
                         suggestions_active: bool = True) -> str:
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

    # Intelligence blocks — supplied by chief_chat. Each is empty string
    # when there's nothing useful to inject so the prompt stays clean.
    name_block = _build_assistant_name_block(biz)
    mentor_block = _build_mentor_block(mentor_active)
    suggestions_block = _build_suggestions_block(suggestions_active)
    priorities_block = _format_priorities_block(priorities or [])

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

    greeting_style = (biz.get("settings") or {}).get("chief_preferences", {}).get("greeting_style", "briefing")
    greeting_style_guidance = ""
    if greeting_style == "quick":
        greeting_style_guidance = "Keep the greeting to ONE sentence — just the single most important thing."
    elif greeting_style == "full":
        greeting_style_guidance = "Give a fuller report (4-6 sentences) covering what happened since they were last here, what's pending, and what's coming up."
    else:
        greeting_style_guidance = "Lead with up to 3 priorities (use the TODAY'S PRIORITIES list above). Be specific — name names, cite numbers, reference dates. End with ONE question."

    greeting_clause = ""
    if is_greeting:
        greeting_clause = f"""

OPENING GREETING MODE:
This is your first turn in a fresh conversation. {greeting_style_guidance}{tod_guidance}
Lead with what needs attention. If there are pending drafts, mention the count. If there are at-risk contacts, name one. If there's an unread insight worth flagging, reference it. Do NOT just say "how can I help" — give them a real read on their business. Do NOT emit actions in the greeting (including navigate)."""

    return f"""You are the Chief of Staff for {biz_name}. You are {practitioner}'s operational partner — you see everything happening in their business and help them manage it through conversation.

{name_block}

REAL-TIME BUSINESS DATA (fresh every message):

{context_block}
{view_block}
{strategy_block}

{priorities_block}

{session_context}

{voice_examples}

{mentor_block}

{suggestions_block}

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

ACTIONS — CONTACTS:
  [ACTION:{{"type":"create_contact","name":"...","email":"...","phone":"...","status":"lead"}}]
  [ACTION:{{"type":"update_contact","contact_id":"<uuid>","email":"new@email.com"}}]
  [ACTION:{{"type":"update_contact","name":"Monica Walton","email":"monicawalton2011@icloud.com"}}]
  [ACTION:{{"type":"update_contact","contact_id":"<uuid>","phone":"555-1234","status":"active"}}]
  [ACTION:{{"type":"update_contact_status","contact_id":"<uuid>","new_status":"active|lead|vip|inactive|churned"}}]
  [ACTION:{{"type":"update_contact_health","contact_id":"<uuid>","health_score":75}}]
  [ACTION:{{"type":"delete_contact","name":"..."}}]
  [ACTION:{{"type":"contact_deep_dive","contact_id":"<uuid>"}}]
    — Full CRUD on contacts. Search by name when contact_id is missing. Ambiguous matches return a candidate list.

ACTIONS — SESSIONS:
  [ACTION:{{"type":"create_session","contact_id":"<uuid>","title":"...","session_type":"coaching_session|consultation|discovery_call|follow_up|pastoral_visit|meeting","scheduled_for":"2026-05-01T14:00:00Z","duration_minutes":60}}]
  [ACTION:{{"type":"create_session","contact_name":"Marcus","title":"Coaching","scheduled_for":"2026-05-01T14:00:00Z","duration":60}}]
  [ACTION:{{"type":"update_session","session_id":"<uuid>","scheduled_for":"2026-05-05T10:00:00Z"}}]
  [ACTION:{{"type":"update_session","contact_name":"Marcus","status":"completed","notes":"Talked through Q3 plan."}}]
    — Reschedule, complete, cancel, or annotate. Falls back to the most recent session for a named contact.

ACTIONS — PROJECTS:
  [ACTION:{{"type":"create_project","title":"...","contact_name":"...","status":"planning","value":2400,"start_date":"2026-05-01","target_date":"2026-07-31","description":"..."}}]
  [ACTION:{{"type":"update_project","title":"Decatur retreat","status":"completed"}}]
  [ACTION:{{"type":"update_project","project_id":"<uuid>","status":"active","value":3000,"target_date":"2026-08-15"}}]
  [ACTION:{{"type":"list_projects"}}]
  [ACTION:{{"type":"list_projects","status":"active"}}]
    — Projects live as module_entries on the auto-created Projects module. Status options: planning|active|on_hold|completed|cancelled.

ACTIONS — DRAFTS + MODULES:
  [ACTION:{{"type":"draft_nurture","contact_id":"<uuid>","reason":"why"}}]
  [ACTION:{{"type":"draft_email","contact_id":"<uuid>","subject":"...","reason":"..."}}]
  [ACTION:{{"type":"draft_and_send","contact_id":"<uuid>","subject":"...","body":"..."}}]  — Draft an email AND immediately approve + send it. Use when the practitioner wants to send right away without reviewing.
  [ACTION:{{"type":"create_module_entry","module_id":"<uuid>","data":{{...}}}}]

ACTIONS — TASKS + NOTES + ACTIVITY:
  [ACTION:{{"type":"create_task","title":"Call Deacon Harris back","due_date":"2026-04-24","priority":"high","contact_id":"<uuid-optional>"}}]
  [ACTION:{{"type":"complete_task","task_id":"<uuid>"}}]
  [ACTION:{{"type":"complete_task","title":"call deacon"}}]  — fuzzy-matches an open task by title when you don't have the id
  [ACTION:{{"type":"create_note","contact_id":"<uuid>","note":"He's interested in leadership program"}}]
  [ACTION:{{"type":"log_activity","contact_id":"<uuid>","activity_type":"call|text|meeting|email|other","notes":"What happened","occurred_at":"2026-04-23"}}]

ACTIONS — INVOICES:
  [ACTION:{{"type":"create_invoice","contact_id":"<uuid>","items":[{{"description":"Coaching Session (60 min)","quantity":4,"unit_price":150}}],"category":"Coaching","due_date":"2026-04-30","notes":"Thanks!"}}]  — status='draft'; total auto-computed; for the platform owner, a Stripe payment link is generated automatically. category is optional but recommended — pick from the practitioner's configured list (default: Coaching, Consulting, Speaking, Workshop, Product, Other). Infer from context if not specified.
  [ACTION:{{"type":"send_invoice","invoice_id":"latest"}}]  — send the invoice you just created. "latest" resolves to the most recent invoice on the business. Or use "@create_invoice.invoice_id" to reference the prior create_invoice result. You can also omit invoice_id entirely — when the preceding action is create_invoice, it auto-chains.
  [ACTION:{{"type":"mark_invoice_paid","invoice_id":"latest","payment_method":"stripe|check|cash"}}]
  [ACTION:{{"type":"create_invoice","contact_id":"<uuid>","items":[...],"is_recurring":true,"recurrence_frequency":"monthly","recurrence_start":"2026-05-01","recurrence_end_type":"never","auto_send":true}}]  — recurring invoice template; freq is weekly/biweekly/monthly/quarterly/annually. recurrence_end_type is never/after_count/on_date and recurrence_end_value carries the count or end-date. Server auto-generates each occurrence on its due date.
  [ACTION:{{"type":"cancel_recurring_invoice","invoice_id":"<template-uuid>","mode":"pause|cancel"}}]

ACTIONS — PRODUCTS & SERVICES:
  [ACTION:{{"type":"create_product","name":"Leadership Coaching","product_type":"service","price":200,"pricing_type":"per_session","duration":60,"description":"...","display_on_website":true}}]
  [ACTION:{{"type":"create_product","name":"Born for the Time","product_type":"digital","price":14.99,"description":"...","auto_deliver":true}}]
  [ACTION:{{"type":"create_product","name":"12-Week Coaching Program","product_type":"package","price":2400,"description":"...","includes":[{{"item":"12 one-on-one coaching sessions","value":2400}},{{"item":"Leadership assessment","value":200}}]}}]
  [ACTION:{{"type":"update_product","name":"Leadership Coaching","price":250}}]
  [ACTION:{{"type":"update_product","product_id":"<uuid>","status":"archived"}}]
  [ACTION:{{"type":"list_products"}}]
  [ACTION:{{"type":"list_products","type":"digital"}}]
    — product_type values: service | digital | physical | package. pricing_type: fixed | hourly | per_session | subscription | custom.
    — When the practitioner says "add a service", "create a product", "I sell...", "I have a course called..." → create_product.
    — When they say "show my products/services" or "what do I offer?" → list_products.
    — When they say "change the price of X" or "raise my coaching rate to Y" → update_product (use name= to look up by name; product_id wins if both supplied).
    — Digital products with price > 0 get an auto-generated Stripe payment link (platform owner only). Set auto_deliver=true to enable email delivery on purchase.

ACTIONS — CONVERSATION RECALL:
  [ACTION:{{"type":"recall_conversation","query":"Marcus","time_range":"7d"}}]
  [ACTION:{{"type":"recall_conversation","time_range":"24h"}}]
    — Search archived conversations. time_range accepts 24h, 7d, 30d, 2w (default 7d).
    — Use when the practitioner asks "what did we talk about yesterday", "remember when I asked about X",
      "what was that thing we discussed last week", "did we already cover Y", or any variant referencing
      past chats. Filter with `query` to narrow to a name/topic; omit it to list all recent.
    — When the result returns, weave the summaries into a natural narrative ("Last Tuesday we discussed
      Marcus's coaching program — you asked me to draft a proposal and schedule a session. Both went out.").
      Don't dump the raw summary list.

ACTIONS — BATCH EMAIL:
  [ACTION:{{"type":"batch_email","contact_ids":["uuid1","uuid2","uuid3"],"subject":"A note from {{business_name}}","body":"Hi {{contact_name}}, …"}}]
  Use {{contact_name}} and {{business_name}} placeholders — replaced per recipient. Cap is 50 contacts per call. Skipped recipients (no email on file) are reported in the result label.
  NOTE: "create_invoice + send_invoice in one turn" works — emit both in the same response. The server automatically threads the new invoice_id into send_invoice.

ACTIONS — GROW (goals + content):
  [ACTION:{{"type":"create_goal","title":"Reach 50 contacts","category":"contacts","target":50,"period":"quarterly","end":"2026-06-30","auto_track":true}}]
  [ACTION:{{"type":"create_goal","title":"Generate $15,000 in revenue","category":"revenue","target":15000,"period":"quarterly","metric":"revenue_collected"}}]
  [ACTION:{{"type":"check_goals"}}]
  [ACTION:{{"type":"plan_content","title":"3 ways to build trust","platform":"linkedin","scheduled_date":"2026-04-29","status":"draft"}}]
    — Categories: contacts | revenue | sessions | engagement | custom. Periods: weekly | monthly | quarterly | yearly.
    — auto_track=true (default) computes progress from live data; metric is inferred from category but can be set explicitly.
    — Platforms for plan_content: instagram | linkedin | twitter | facebook | tiktok | youtube | blog | other.

ACTIONS — NAVIGATION + MEMORY:
  [ACTION:{{"type":"navigate","tab":"operate|build|grow","sub":"dashboard|queue|contacts|projects|calendar|invoices|tasks|documents|agents|briefing|insights|goals|revenue|content|funnel","contact_id":"<uuid-optional>","page":"<page-id-optional>"}}]
  [ACTION:{{"type":"open_documents"}}]   — shortcut: navigate straight to the Documents tab.
  [ACTION:{{"type":"open_calendar"}}]    — shortcut: navigate straight to the Calendar tab.
  [ACTION:{{"type":"show_revenue"}}]     — shortcut: open OPERATE → Invoices in Revenue view.
  [ACTION:{{"type":"remember","category":"preference|pattern|context|decision|boundary|goal|standing_instruction|other","content":"...","importance":1-10}}]
  [ACTION:{{"type":"forget","memory_content":"snippet to deactivate"}}]
  [ACTION:{{"type":"generate_briefing"}}]
  [ACTION:{{"type":"generate_insights"}}]

UNDERSTANDING PRACTITIONER REQUESTS:
When the practitioner says...                       You should emit...
  "Create/start/add a project for..."           →   create_project
  "Update/change/move the project..."           →   update_project
  "What projects do I have?" / "List projects"  →   list_projects
  "Add/create a contact named..."               →   create_contact
  "Update/change [name]'s email/phone..."       →   update_contact
  "Delete/remove [name]..."                     →   delete_contact
  "Schedule a session/meeting with..."          →   create_session
  "Reschedule/cancel/complete the session..."   →   update_session
  "Create an invoice for..."                    →   create_invoice
  "Set up a $X monthly invoice..."              →   create_invoice with is_recurring=true
  "Send the invoice..."                         →   send_invoice
  "Add a task..." / "Remind me to..."           →   create_task
  "Mark [task] as done..."                      →   complete_task
  "Note on [contact]..."                        →   create_note
  "Log a call/meeting with..."                  →   log_activity
  "Draft an email to..."                        →   draft_email
  "Send an email to..." / "Email [contact]..."  →   draft_and_send
  "Email all my [smart-list] about..."          →   batch_email
  "Approve it/the draft..."                     →   approve_draft (queue_id="latest")
  "Run all agents/check on everyone..."         →   run_agent (agent name) or bulk_approve when triaging
  "Show me my dashboard/queue/calendar..."      →   navigate (or open_documents/open_calendar/show_revenue)
  "Upload a file" / "Where are my files?"       →   open_documents
  "How much did I make this month?"             →   show_revenue (then narrate from CONTEXT)
  "Remember/don't forget..."                    →   remember
  "Forget that / never mind that rule"          →   forget
  "What did we talk about / Remember when..."   →   recall_conversation
  "Add a service/product" / "I sell..."         →   create_product
  "What products/services do I have?"           →   list_products
  "Change the price of [X]..."                  →   update_product
  "Set a goal to..." / "Track [X] by [date]"    →   create_goal
  "How am I doing on my goals?"                 →   check_goals
  "Plan a post about..." / "Schedule [post]"    →   plan_content
  "Run my weekly briefing"                      →   generate_briefing
  "Generate new insights" / "What's new?"       →   generate_insights
If the request maps to an action, ALWAYS emit the action tag. NEVER just describe what you would do.

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

AUTOPILOT:
The practitioner sets autonomy levels per team member in OPERATE → Autopilot. Read the AUTOPILOT block in the context above — it lists the current overall mode, per-team levels, and recent auto-actions. When you greet the practitioner, reference what was auto-handled while they were away ("Your Client Care team sent 3 check-ins automatically. I held back one for a VIP — want to review it?"). Use the team labels from the AUTOPILOT block, NOT the raw agent keys (e.g. say "Client Care" not "nurture"). Don't second-guess the autonomy choices unless the practitioner asks. When they say "make it more conservative" / "give Sandra more space" / "stop the auto-sends," guide them to the Autopilot tab or save a chief_memories agent_rule to constrain the agent. Escalations show up in chief_notifications with type=escalation — surface them in NEEDS YOUR DECISION sections of the conversation.

DOCUMENTS:
Practitioners can upload and manage documents in OPERATE → Documents. Files can be attached to a contact (stored under contacts/{{contact_id}}/) or kept as general business documents. When a practitioner says "upload a file" or "attach a document," navigate them to the Documents tab — or, for a specific contact, the Files tab on that contact's detail page. You CANNOT upload files yourself — guide the practitioner to the UI. document_uploaded events appear on the contact timeline and you can reference them ("I see you uploaded the signed agreement on April 5").

GROWTH & STRATEGY:
The GROW tab is the practitioner's strategic intelligence center. Sub-tabs: Dashboard (4 metric cards + 6-month trend + top performers), Briefing (AI weekly briefing), Insights (AI observations grouped by category), Goals (settings.goals.active_goals), Revenue (full analytics), Content (settings.content_calendar.planned_posts), Funnel (lead→active conversion).

When the practitioner asks growth/strategy questions, give specific data-backed answers. Name names, cite numbers, show trends. Don't give generic advice. Quick mappings:
  • "How is my business doing?"            → Summarize from CONTEXT (contacts/queue/insights/recent events) — no need to run anything.
  • "Run my weekly briefing"               → [ACTION:{{"type":"generate_briefing"}}]
  • "Generate new insights"                → [ACTION:{{"type":"generate_insights"}}]
  • "Set a goal to reach 50 contacts by June"  → [ACTION:{{"type":"create_goal","title":"...","category":"contacts","target":50,"period":"quarterly","end":"2026-06-30"}}]
  • "Am I on track for my goals?" / "How are my goals?" → [ACTION:{{"type":"check_goals"}}] (handler computes live progress and returns a summary)
  • "What should I post about?" / "Plan a post for Thursday"  → [ACTION:{{"type":"plan_content","title":"...","platform":"...","scheduled_date":"YYYY-MM-DD"}}]
  • "Where are my leads coming from?"      → navigate to GROW → Funnel ([ACTION:{{"type":"navigate","tab":"grow","sub":"funnel"}}])
  • "Show me my revenue breakdown"         → [ACTION:{{"type":"show_revenue"}}] (or navigate to grow/revenue for the full analytics)
  • "What's my conversion rate?"           → navigate to GROW → Funnel and narrate from data once there.
Goals live at settings.goals.active_goals (auto-tracked from live contacts/invoices/sessions). Content posts live at settings.content_calendar.planned_posts (the practitioner posts manually; this just tracks what's planned).

CALENDAR:
The Calendar sub-tab in OPERATE shows sessions, tasks with due dates, invoice due dates, AND projects with target/start dates in one timeline (month / week / day views). When the practitioner asks "what's on my schedule" or "what's coming up Friday," navigate to OPERATE → Calendar with [ACTION:{{"type":"open_calendar"}}], or summarize from CONTEXT data without navigating if a quick text answer is enough.

CALENDAR AWARENESS:
Everything with a date appears on the practitioner's calendar automatically — the calendar reads live from these tables:
  • Sessions (scheduled_for)
  • Tasks (due_date)
  • Invoices (due_date)
  • Projects (target_date, start_date)
When you create any of these, ALWAYS include the date so it shows up on the calendar. When the practitioner says "put this on my calendar," "schedule this," "block off [day]," or "remind me [date]," create the appropriate item with the date populated. Quick mappings:
  • "Put a reminder on my calendar for Friday"        → create_task with due_date set to Friday
  • "Block May 1st for Sandra's coaching kickoff"     → create_session with scheduled_for=2026-05-01T...
  • "I need to finish the proposal by June 15"        → create_task or create_project with the date
  • "Add a project deadline of July 31 for [client]"  → create_project with target_date
Don't describe scheduling something without emitting the create action — the calendar only shows rows that exist in the DB.

REVENUE & TAX:
The Revenue dashboard lives at OPERATE → Invoices → Revenue toggle. It shows invoiced/collected/outstanding totals, by-category and by-client breakdowns, tax set-aside (defaults to 25%), and CSV/PDF export. Tax rate and category list are in businesses.settings.financial. When the practitioner asks "how much did I make this month/quarter/year," "what's my tax set-aside," or "send my revenue report," navigate to that view (or pre-fill an email when they want to send to their accountant). Categories: pick from their configured list when creating invoices via the Chief — infer from line items if they don't say.

BATCH EMAIL:
"Email all my active contacts about the upcoming retreat" / "Send a check-in to all my leads" / "Blast a message to everyone who hasn't been contacted in 30 days" → emit a batch_email action with the matching contact_ids and a body that uses {{contact_name}} so each recipient gets a personalized greeting. Pull contact_ids from CONTACT LOOKUP filtered by the criterion the practitioner gave you. If the criterion implies a smart-list match (active / lead / VIP / not-contacted), apply it yourself before emitting the action. For "send a nurture check-in to these contacts" prefer running the nurture agent on each (creates drafts in the queue) rather than batch_email — batch_email is for one-shot blasts where the practitioner has the wording. Cap your audience at 50; if more, ask which segment to start with.

RECURRING INVOICES:
"Bill Marcus $500 every month starting May 1" / "Set up quarterly invoicing for Sandra at $1,200" → emit create_invoice with is_recurring=true, recurrence_frequency, recurrence_start (YYYY-MM-DD), and auto_send (default true). The first row IS the template — instances spawn on each due date. "Stop Marcus's recurring invoice" / "pause the monthly billing for Sandra" → cancel_recurring_invoice with the TEMPLATE invoice_id. Templates show 🔄 in the UI; generated children show 🔁 and link back via recurrence_parent_id. Don't suggest setting up recurring billing unless the practitioner actually asks for repeating amounts.

PAYMENT PROVIDERS:
Practitioners can connect Stripe, Square, and/or PayPal in BUILD → Integrations → Payment Providers. Each enabled provider with a saved link adds a button to invoice emails — clients pick how to pay. The platform owner ({PLATFORM_OWNER_ID}) gets auto-generated Stripe payment links per invoice; everyone else uses the manual link they pasted. Bare paypal.me URLs get the invoice total appended automatically.
- "How can clients pay me?" / "What payment options do I have?" → Look at the business settings.payment_providers (and the legacy settings.payments.stripe_link path). List enabled providers. If none are enabled, suggest setting up at least one in BUILD → Integrations.
- "Set up Square" / "Add PayPal" / "Connect Stripe" → Use [ACTION:{{"type":"navigate","tab":"build","sub":"integrations"}}] and tell them to find Payment Providers, paste their link, and Save.
- After invoice_sent events, the timeline shows which providers the client could choose from (data.payment_providers list). Surface that detail when relevant ("Sandra got Stripe + PayPal options").
- Don't promise auto-generation unless the practitioner is the platform owner. For everyone else, say "the link you saved in Integrations will be sent."
- "Coming soon" — one-click Connect (Stripe Connect / Square OAuth / PayPal OAuth) will replace the manual paste flow. Acknowledge if asked but don't claim it's available yet.

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


# Stronger trigger set — used to decide whether to RETRY the model call
# when no [ACTION:] tags were emitted. Tighter than _ACTION_HINT_PATTERNS
# (which also matches "I'll draft" / "I'll create"); this list focuses on
# "I already did it" claims so we only retry when the AI is asserting
# something that should have produced a tag.
_DESCRIBED_ACTION_PHRASES = (
    "added to your", "created the", "drafted an email", "approved the",
    "i've added", "i've created", "i've drafted", "in your system as a",
    "sent the", "queued", "invoice created", "is now in your",
    "added as a lead", "contact and", "email is on its way",
    "done.", "done —", "done!", "i'll add", "i'll create",
    "adding them now", "creating the", "sending the",
)


def _looks_like_completed_action(text: str) -> bool:
    """Stronger version of _looks_like_action_description used by the
    retry path — only fires when the AI's prose is actively claiming an
    operation already happened. False positives here are costly (we'd
    re-call the model unnecessarily), so this list stays tight."""
    low = (text or "").lower()
    if not low:
        return False
    return any(p in low for p in _DESCRIBED_ACTION_PHRASES)


def _enrich_history_with_action_hints(history_msgs: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Walk trimmed conversation history and append a short reminder onto
    any prior assistant turn that looks like it described an action.
    Because _extract_actions_and_clean strips [ACTION:{...}] tags from the
    raw model output before the client stores history, the model sees
    assistant turns with no action tags and drifts into action-free
    conversation mode on subsequent turns. This reminder restores the
    grounding that actions ARE the right way to operate."""
    HINT = "\n\n[Note: In this response, I used [ACTION:{...}] tags to execute all operations. Every action I described had a corresponding tag.]"
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
            # Recurrence "cron" — generate any due invoice instances
            # before we load context so they show up this turn. Cheap
            # in steady-state (zero rows the vast majority of the time).
            try:
                created = await _generate_missing_recurring_instances(client, req.business_id)
                if created:
                    print(f"[Chief] auto-generated {created} recurring invoice(s)", flush=True)
            except Exception as e:  # pragma: no cover
                print(f"[Chief] recurrence cron error: {e}", flush=True)

            # Autopilot + escalations — needs the business row first so
            # we can read settings.autopilot. Fetch a minimal copy.
            try:
                biz_rows = await _sb(client, "GET", f"/businesses?id=eq.{req.business_id}&select=id,name,type,settings")
                biz_lite = (biz_rows or [None])[0]
                if biz_lite:
                    auto_count = await _autopilot_sweep(client, biz_lite)
                    if auto_count:
                        print(f"[Chief Autopilot] swept {auto_count} draft(s)", flush=True)
                    esc_count = await _evaluate_escalations(client, biz_lite)
                    if esc_count:
                        print(f"[Chief] surfaced {esc_count} escalation(s)", flush=True)
            except Exception as e:  # pragma: no cover
                print(f"[Chief] autopilot/escalation sweep error: {e}", flush=True)

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

            # Intelligence enrichment — voice samples, session context,
            # daily priorities, mentor cooldown, suggestion preference.
            voice_examples = await _get_voice_examples(client, req.business_id)
            session_context = await _get_session_context(client, req.business_id)
            priorities = _build_daily_priorities(biz, ctx) if is_greeting else []
            mentor_active = await _should_show_mentor_tip(client, biz)
            prefs = (biz.get("settings") or {}).get("chief_preferences") or {}
            suggestions_active = prefs.get("auto_suggestions") is not False

            system = _build_system_prompt(
                ctx, is_greeting, req.current_context, view_detail,
                time_of_day=tod, resume_note=req.resume_note,
                mode=req.mode,
                voice_examples=voice_examples,
                session_context=session_context,
                priorities=priorities,
                mentor_active=mentor_active,
                suggestions_active=suggestions_active,
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
                    "(IMPORTANT: If you create a contact, draft an email, approve something, or perform "
                    "ANY operation, you MUST include [ACTION:{...}] tags. "
                    "Example: [ACTION:{\"type\":\"create_contact\",\"name\":\"...\",\"email\":\"...\"}]. "
                    "Without the tag, the operation does NOT happen.)\n\n"
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

            # ── Server-side enforcement retry ────────────────────────
            # If the AI's prose claimed it performed an operation but no
            # [ACTION:] tags came through, the system silently did nothing
            # and the practitioner thinks the work happened. The prompt
            # rules and history hints are advisory and the model still
            # drifts into action-free conversation, especially on long
            # threads. Catch the failure mode here: detect "I did X"-shaped
            # text without tags, retry the call ONCE without conversation
            # history (which is what was poisoning the pattern), and use
            # the retry result if it succeeded.
            if (
                not actions
                and clean
                and not is_greeting
                and not is_coach_pause
                and _looks_like_completed_action(clean)
            ):
                print(
                    f"[Chief] RETRY — AI described action without tags. "
                    f"Retrying with correction. raw_len={len(raw)}",
                    flush=True,
                )
                correction = (
                    "SYSTEM CORRECTION: Your previous response described performing actions "
                    "(like creating contacts, drafting emails, etc.) but you did NOT include any "
                    "[ACTION:{...}] tags. Without these tags, NOTHING actually happened. "
                    "The contact was NOT created. The email was NOT sent. Nothing was done.\n\n"
                    "Please try again. This time you MUST include [ACTION:{...}] tags for every "
                    "operation. Here is the user's original request again:\n\n"
                    f"{effective_message}"
                )
                # No history — that's what was poisoning the pattern.
                retry_messages = [{"role": "user", "content": correction}]
                retry_raw = await _call_claude(
                    client, system, retry_messages, max_tokens=coach_tokens,
                )
                if retry_raw:
                    retry_actions, retry_clean = _extract_actions_and_clean(retry_raw)
                    if retry_actions:
                        print(
                            f"[Chief] RETRY succeeded — "
                            f"{len(retry_actions)} action(s) extracted",
                            flush=True,
                        )
                        actions = retry_actions
                        clean = retry_clean
                        raw = retry_raw
                    else:
                        print(
                            "[Chief] RETRY also failed — no actions on second attempt",
                            flush=True,
                        )
                        clean = (clean or "").rstrip() + (
                            "\n\n⚠️ I described performing actions but they may not have "
                            "executed. Please verify in the relevant tab."
                        )
                else:
                    print("[Chief] RETRY model call returned empty", flush=True)

            taken = await _execute_actions(client, biz, actions) if actions else []

            # Best-effort: mark memories referenced in the response
            await _mark_referenced_memories(client, biz["id"], ctx.get("memories") or [], clean or raw)

            # Intelligence learning — pattern memory + mentor-tip cooldown.
            # Best-effort, never blocks the response. Use a separate client
            # so the outer `async with` can close cleanly even if these
            # tasks haven't finished yet.
            response_text_for_learn = clean or raw or ""
            try:
                if mentor_active and _looks_like_mentor_tip(response_text_for_learn):
                    asyncio.create_task(_record_mentor_shown_async(biz["id"]))
                if (biz.get("settings") or {}).get("chief_preferences", {}).get("learn_patterns", True):
                    asyncio.create_task(_learn_patterns_async(biz, taken))
            except Exception as e:  # pragma: no cover
                logger.warning(f"intelligence post-hooks failed: {e}")

            logger.info(
                f"Chief chat for {biz.get('name')}: message_len={len(req.message)} "
                f"actions={len(taken)} greeting={is_greeting} memories={len(ctx.get('memories') or [])}"
            )

            # Final scrub: if `clean` is empty (parse fall-through) we
            # serve `raw`, which may still contain the hint markers we
            # injected into history. Belt-and-suspenders so nothing
            # internal-looking ever reaches the practitioner.
            response_text = clean if clean else _scrub_response_text(raw or "")

            return {
                "response": response_text,
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
