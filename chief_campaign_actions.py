"""
chief_campaign_actions.py — Chief verbs for marketing campaigns.

THE GAP THIS CLOSES (S10)
  campaigns_router.py is a full product surface — plan, launch, pause,
  delete, audience preview, honest results — and until now had ZERO
  Chief-callable actions. A practitioner could say "text my quiet
  clients about the spring special" and Chief could only navigate them
  to the screen. These verbs make the existing engine conversational.

  Nothing here re-derives campaign rules. Every handler calls the cores
  extracted from campaigns_router (plan_campaign_core / launch_campaign_core
  / pause_campaign_core / list_campaigns_core), so the audience query, the
  launch check-list, and the billing gates are the SAME code the HTTP
  endpoints run. Consent, suppression and quiet hours live in the send
  sweep (campaigns_tick) and apply per send regardless of who launched.

CLASSIFICATION (action_registry has the same story, entry by entry)
  plan_campaign    — class A write. Inserts a campaigns row with
                     status='draft'; nothing sends until a launch. Same
                     shape as draft_email: a reviewable artifact, an
                     edit away from right. Model spend (the drafting
                     call), which the registry entry says out loud.
  launch_campaign  — class C, bulk=True. Launching arms sends to the
                     WHOLE audience over the following days. The chat
                     gate holds it under manual/smart autopilot (the
                     campaign stays saved; the Campaigns screen is the
                     review surface) and only runs it under full
                     nurture autopilot.
  pause_campaign   — class C, single-target, immediate. Protective —
                     when the practitioner says stop, it stops NOW; per
                     registry doctrine the explicit ask is the approval.
                     It stays C (not A) because pausing/resuming
                     reshapes the send schedule of an in-flight bulk
                     outreach — the lifecycle of a bulk send stays
                     proposal-only end to end.
  campaign_status  — read. Current campaigns + honest send progress
                     from the campaign_sends ledger.

  House contract: every return carries `result` AND `label` (a missing
  label crashes the client on toLowerCase); failures carry
  `"failed": True`.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

import campaigns_router as cr

logger = logging.getLogger("chief_campaign_actions")


def _fail(action_type: str, msg: str) -> Dict[str, Any]:
    return {"type": action_type, "result": f"failed: {msg}", "label": msg[:80],
            "nav": None, "failed": True}


def _nav_campaigns() -> Optional[Dict[str, Any]]:
    try:
        from chief_of_staff import _nav
        return _nav("grow", "campaigns")
    except Exception:
        return None


def _detail_str(exc: HTTPException) -> str:
    """The cores raise the same HTTPExceptions the endpoints always did;
    their detail is presentable practitioner copy — pass it through."""
    d = exc.detail
    if isinstance(d, dict):
        return str(d.get("message") or d.get("error") or d)
    return str(d)


async def _find_campaign(biz_id: str, action: Dict[str, Any]
                         ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Resolve a campaign by id or (partial, case-insensitive) name.
    Returns (campaign, error). Always business-scoped — _load_campaign
    alone is unscoped, so an id from another business must not resolve."""
    campaign_id = (action.get("campaign_id") or "").strip()
    name = (action.get("name") or action.get("campaign_name") or "").strip()
    rows = await asyncio.to_thread(cr.list_campaigns_core, biz_id)
    if campaign_id:
        for r in rows:
            if r.get("id") == campaign_id:
                return r, None
        return None, f"Campaign {campaign_id} not found"
    if name:
        matches = [r for r in rows if name.lower() in (r.get("name") or "").lower()]
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            opts = ", ".join(f"'{m.get('name')}' ({m.get('status')})" for m in matches[:5])
            return None, f"Several campaigns match '{name}': {opts}. Say which one."
        return None, f"No campaign named '{name}' on file"
    return None, "Name the campaign (campaign_id or name)"


def _reach_phrase(summary: Dict[str, Any]) -> str:
    return (f"{summary['count']} people "
            f"({summary['emailable']} reachable by email, "
            f"{summary['textable']} by text)")


# ─── plan (class A — saves a DRAFT, sends nothing) ───────────────────

async def handle_plan_campaign(client, biz, action) -> Dict[str, Any]:
    goal = (action.get("goal") or "").strip()
    audience: Dict[str, Any] = {}
    kind = (action.get("audience") or action.get("audience_kind") or "").strip().lower()
    if isinstance(action.get("audience"), dict):          # full audience object
        audience = action["audience"]
    elif kind in cr.AUDIENCE_KINDS:
        audience = {"kind": kind}
        if kind == "silent":
            try:
                audience["days_silent"] = int(action.get("days_silent") or 30)
            except (TypeError, ValueError):
                audience["days_silent"] = 30
    try:
        core = await cr.plan_campaign_core(biz, goal, audience)
    except HTTPException as e:
        return _fail("plan_campaign", _detail_str(e))
    camp = core["campaign"]
    summary = core["audience_preview"]
    touches = camp.get("touches") or []
    n = len(touches)
    return {
        "type": "plan_campaign",
        "campaign_id": camp.get("id"),
        "result": (f"drafted campaign '{camp.get('name')}' — {n} "
                   f"touch{'es' if n != 1 else ''} to {_reach_phrase(summary)}. "
                   f"It is a DRAFT: nothing sends until it's launched. "
                   f"Review the messages in GROW → Campaigns, or say "
                   f"'launch it' when it reads right."),
        "label": (f"Drafted '{camp.get('name')}' — {n} touch{'es' if n != 1 else ''}, "
                  f"{summary['count']} people (not sent)"),
        "nav": _nav_campaigns(),
    }


# ─── launch (class C bulk — the chat gate holds this under manual) ───

async def handle_launch_campaign(client, biz, action) -> Dict[str, Any]:
    camp, err = await _find_campaign(biz["id"], action)
    if not camp:
        return _fail("launch_campaign", err or "campaign not found")
    try:
        core = await asyncio.to_thread(
            cr.launch_campaign_core, biz, camp, action.get("start_at"))
    except HTTPException as e:
        return _fail("launch_campaign", _detail_str(e))
    summary = core["audience_preview"]
    launched = core["campaign"]
    return {
        "type": "launch_campaign",
        "campaign_id": launched.get("id"),
        "result": (f"launched '{launched.get('name')}' — first touches go to "
                   f"{_reach_phrase(summary)}. The sweep sends on schedule and "
                   f"honors opt-outs and quiet hours per message."),
        "label": f"Launched '{launched.get('name')}' to {summary['count']} people",
        "nav": _nav_campaigns(),
    }


# ─── pause (class C single-target — protective, immediate) ───────────

async def handle_pause_campaign(client, biz, action) -> Dict[str, Any]:
    camp, err = await _find_campaign(biz["id"], action)
    if not camp:
        return _fail("pause_campaign", err or "campaign not found")
    try:
        paused = await asyncio.to_thread(cr.pause_campaign_core, camp)
    except HTTPException as e:
        return _fail("pause_campaign", _detail_str(e))
    sent = camp.get("sent_total") or 0
    return {
        "type": "pause_campaign",
        "campaign_id": paused.get("id"),
        "result": (f"paused '{paused.get('name')}' — {sent} "
                   f"message{'s' if sent != 1 else ''} had gone out; nothing "
                   f"more sends until you launch it again."),
        "label": f"Paused '{paused.get('name')}'",
        "nav": _nav_campaigns(),
    }


# ─── status (read — the ledger, not a guess) ─────────────────────────

def _one_line(r: Dict[str, Any]) -> str:
    touches = r.get("touches") or []
    done = sum(1 for t in touches if isinstance(t, dict) and t.get("completed_at"))
    bits = [f"'{r.get('name')}'", r.get("status") or "?"]
    if r.get("status") in ("running", "paused", "completed"):
        bits.append(f"{r.get('sent_total') or 0} sent")
    if touches and r.get("status") == "running":
        bits.append(f"touch {min(done + 1, len(touches))}/{len(touches)}")
    return " — ".join(bits)


async def handle_campaign_status(client, biz, action) -> Dict[str, Any]:
    wants_one = bool((action.get("campaign_id") or action.get("name")
                      or action.get("campaign_name") or "").strip())
    if wants_one:
        camp, err = await _find_campaign(biz["id"], action)
        if not camp:
            return _fail("campaign_status", err or "campaign not found")
        results = await asyncio.to_thread(cr._campaign_results, camp)
        return {
            "type": "campaign_status",
            "campaign_id": camp.get("id"),
            "result": (f"'{camp.get('name')}' is {camp.get('status')}: "
                       f"{results['emails_sent']} emails and {results['texts_sent']} "
                       f"texts to {results['people_reached']} people so far; "
                       f"{results['replies_since_launch']} replies and "
                       f"{results['bookings_since_launch']} bookings since launch "
                       f"(activity among the audience, not claimed attribution)."),
            "label": (f"'{camp.get('name')}' — {camp.get('status')}, "
                      f"{results['people_reached']} people reached"),
            "nav": _nav_campaigns(),
        }
    rows = await asyncio.to_thread(cr.list_campaigns_core, biz["id"])
    if not rows:
        return {
            "type": "campaign_status",
            "result": ("no campaigns yet — say what you want to achieve "
                       "(e.g. 'win back clients I haven't seen in 60 days') "
                       "and I'll draft one for review."),
            "label": "No campaigns yet",
            "nav": _nav_campaigns(),
        }
    running = sum(1 for r in rows if r.get("status") == "running")
    lines = "; ".join(_one_line(r) for r in rows[:6])
    more = f" (+{len(rows) - 6} older)" if len(rows) > 6 else ""
    return {
        "type": "campaign_status",
        "result": f"{len(rows)} campaign{'s' if len(rows) != 1 else ''}: {lines}{more}",
        "label": (f"{len(rows)} campaign{'s' if len(rows) != 1 else ''}, "
                  f"{running} running"),
        "nav": _nav_campaigns(),
    }
