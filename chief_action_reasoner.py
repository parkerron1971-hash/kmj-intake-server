"""
chief_action_reasoner.py — reason a request into known primitives instead of
dead-ending on a lookup miss.

THE PROBLEM: Chief has ~112 coded actions in ACTION_HANDLERS. When it emits an
action_type that isn't one of them (because the user asked for something the
system was never explicitly coded for), the dispatcher returns
_fail("Unknown action type") — a dead end. Chief's intelligence is right
there; the lookup table just refuses it.

THE PATTERN (same as design_intent.py — "teach the rubric, not the cases"):
on the MISS path only, hand the model the attempted action (its type + payload
carry the INTENT) and a RUBRIC of the SAFE building blocks it can use, and ask
it to REASON whether the intent can be accomplished by composing one or more of
those blocks. It composes known primitives in a new arrangement — doing
something it "wasn't coded for" without any new code.

SAFETY — this executes MUTATIONS, so freedom-in-judgment / determinism-in-
execution is enforced hard:
  - ALLOWLIST only. The reasoner may map ONLY to SAFE_REMAP_ACTIONS —
    reversible, non-sending, non-financial primitives (drafts QUEUE for
    approval, records are editable). It can never remap to send/publish/
    delete/charge. Worst case is an editable record, never an errant email.
  - Every mapped action still runs through its own handler's validation +
    owner checks — this module picks WHICH known action, never bypasses one.
  - Bounded: at most _MAX_PLAN mapped actions.
  - Triggers ONLY when the original action_type has no handler — the 112
    happy paths are untouched.
  - FAILS OPEN: disabled / no key / bad reply / empty plan → None, and the
    dispatcher falls back to today's _fail. Kill switch CHIEF_ACTION_REASONING=off.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

import llm_call

import chief_models

logger = logging.getLogger("chief_action_reasoner")


_MAX_PLAN = 3  # a remap composes at most this many known primitives

# The SAFE building blocks — the ONLY actions a reasoned remap may use.
# Every one is reversible + non-sending + non-financial: a wrong guess makes
# an editable record or a DRAFT (which still needs approval to send), never an
# irreversible external effect. Descriptions ARE the rubric the model reasons
# from. Keep this a strict SUBSET of chief_of_staff.ACTION_HANDLERS (the wiring
# re-validates each type against the live registry too).
SAFE_REMAP_ACTIONS: Dict[str, str] = {
    "create_contact":       "Add a new person (lead/client/etc). Fields: name, email?, phone?, status?",
    "update_contact":       "Update a contact. Fields: contact_id, name?, email?, phone?, notes?",
    "update_contact_status":"Set a contact's status. Fields: contact_id, status",
    "create_note":          "Attach a note to a contact or the business. Fields: text, contact_id?",
    "create_task":          "Create a to-do. Fields: title, due?, contact_id?",
    "complete_task":        "Mark a task done. Fields: task_id",
    "create_goal":          "Set a business goal. Fields: title, description?, target?",
    "add_reminder":         "Remind the practitioner later. Fields: text, when?",
    "capture_idea":         "Save an idea/thought. Fields: text",
    "log_activity":         "Log that something happened. Fields: text, type?",
    "create_session":       "Schedule a session/appointment. Fields: title, scheduled_for, contact_id?",
    "update_session":       "Update a session. Fields: session_id, scheduled_for?, status?",
    "create_project":       "Start a project. Fields: title, client?, scope?",
    "update_project":       "Update a project. Fields: project_id, status?, scope?",
    "create_module_entry":  "Add a row to a custom module. Fields: module (slug or id), values{}",
    "update_module_entry":  "Update a module row. Fields: entry_id, values{}",
    "ensure_module":        "Make sure a custom module exists (creates it if missing). Fields: name, fields?",
    "create_offering":      "Create a service/offering. Fields: name, category?, price?, duration_min?",
    "update_offering":      "Update an offering. Fields: offering_id (or slug), price?, description?",
    "draft_email":          "Draft an email — QUEUED for approval, NOT sent. Fields: contact_id, intent, subject?",
    "draft_nurture":        "Draft a check-in message — QUEUED, NOT sent. Fields: contact_id, intent",
    "set_business_policy":  "Record a business rule/policy so Chief answers clients consistently. Fields: key, value",
    "add_faq":              "Add a client-facing FAQ. Fields: question, answer",
    "remember":             "Store a durable fact/preference about the business. Fields: content",
    "add_testimonial":      "Add a testimonial to the site. Fields: text, author?",
    "update_business_profile_field": "Set a business profile field. Fields: field, value",
}


def _enabled() -> bool:
    if (os.environ.get("CHIEF_ACTION_REASONING") or "on").strip().lower() == "off":
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _rubric() -> str:
    return "\n".join(f"- {name}: {desc}" for name, desc in SAFE_REMAP_ACTIONS.items())


_SYSTEM = """You are the fallback reasoner for Chief, a small-business operating assistant. Chief tried to take an action that has no built-in handler — the practitioner asked for something the system wasn't explicitly coded for. Your job: decide whether that intent can be accomplished by composing one or more of the SAFE building blocks below, and if so, return the exact block calls to run.

You are NOT matching names. Reason about what the practitioner actually wanted (the attempted action's type + fields tell you), then express it using ONLY these building blocks:

SAFE BUILDING BLOCKS (the only actions you may use):
{rubric}

Hard rules:
- Use ONLY the block names above. Never invent a block or use one not listed. Anything involving sending/publishing/deleting/charging is intentionally absent — if the intent truly requires one of those, you CANNOT fulfill it: return an empty plan.
- Prefer the smallest faithful plan. At most 3 blocks.
- Carry over concrete values from the attempted action (names, ids, text) into the block fields.
- If nothing here faithfully accomplishes the intent, return an empty plan — do not force a wrong mapping.

Respond with ONLY this JSON (no prose, no fence):
{"plan":[{"type":"<block name>", ...fields}], "reasoning":"<one sentence>"}"""


def _validate_plan(obj: Any) -> Optional[List[Dict[str, Any]]]:
    """Keep only well-formed calls to allowlisted blocks. None if nothing
    valid survives (→ caller fails open)."""
    if not isinstance(obj, dict):
        return None
    plan = obj.get("plan")
    if not isinstance(plan, list):
        return None
    out: List[Dict[str, Any]] = []
    for step in plan:
        if not isinstance(step, dict):
            continue
        t = str(step.get("type") or "").strip()
        if t in SAFE_REMAP_ACTIONS:          # allowlist enforced here
            out.append({**step, "type": t})
        if len(out) >= _MAX_PLAN:
            break
    return out or None


def reason_unknown_action(action_type: str, payload: Dict[str, Any],
                          business_type: Optional[str] = None
                          ) -> Optional[List[Dict[str, Any]]]:
    """Map an unhandled action to a plan of SAFE known primitives, or None.
    None = fail open (caller keeps today's 'unknown action' failure). The
    returned list contains only allowlisted, validated action dicts ready to
    dispatch through the normal handlers. Best-effort; never raises."""
    if not _enabled() or not (action_type or "").strip():
        return None
    # Don't try to "reinterpret" an action that was already a safe block —
    # that only happens if the registry and allowlist drift; nothing to do.
    if action_type in SAFE_REMAP_ACTIONS:
        return None

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    model = chief_models.model_for("background")
    attempted = {"type": action_type,
                 "fields": {k: v for k, v in (payload or {}).items() if k != "type"}}
    user_msg = (
        f"BUSINESS TYPE: {(business_type or '(unspecified)')}\n"
        f"ATTEMPTED ACTION (no handler exists for this):\n"
        f"{json.dumps(attempted, default=str)[:1200]}\n\n"
        f"Return the JSON now."
    )
    try:
        resp = llm_call.post({
            "model": model, "max_tokens": 500,
            "system": _SYSTEM.replace("{rubric}", _rubric()),
            "messages": [{"role": "user", "content": user_msg}],
        }, timeout=httpx.Timeout(connect=8.0, read=40.0, write=15.0, pool=8.0), key=key)
    except httpx.HTTPError as e:
        logger.info(f"[action_reasoner] call failed: {e}")
        return None
    if resp.status_code >= 400:
        logger.info(f"[action_reasoner] {resp.status_code}: {resp.text[:160]}")
        return None

    try:
        data = resp.json()
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        try:
            from api_usage_logger import log_api_usage_sync
            log_api_usage_sync(endpoint="/chief/action-reasoner",
                               model=data.get("model") or model,
                               input_tokens=int(usage.get("input_tokens") or 0),
                               output_tokens=int(usage.get("output_tokens") or 0))
        except Exception:
            pass
        text = "".join(
            b.get("text", "") for b in data.get("content", [])
            if isinstance(b, dict) and b.get("type") == "text"
        ).strip()
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        parsed = json.loads(text[start:end + 1])
    except (ValueError, TypeError) as e:
        logger.info(f"[action_reasoner] unparseable reply: {e}")
        return None

    plan = _validate_plan(parsed)
    if plan:
        logger.info(f"[action_reasoner] '{action_type}' → "
                    f"{[s['type'] for s in plan]}: {parsed.get('reasoning')}")
    return plan
