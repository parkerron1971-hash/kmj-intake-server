"""Pass 4.0d PART 2 — Per-intent dispatcher.

Takes a normalized intent classification (from intent_classifier) and
calls the right backend specialist. Each handler returns a uniform
result dict so the response composer can stitch them together:

  {
    "intent": str,
    "status": "ok" | "skipped" | "failed" | "dry_run" | "needs_clarification",
    "summary": str,                 # human-readable reply line
    "details": dict,                # specialist-specific payload
    "next_actions": list[str],      # what the practitioner can do next
  }

`dry_run=True` lets the test harness verify dispatch wiring without
firing expensive Builder runs or persisting overrides. When dry_run is
True, every handler returns status='dry_run' with the call payload it
WOULD have made.

In PART 2 the handlers for slot_change / operational_task / scheduling
/ briefing_request return status='skipped' with a stub — those route
to existing systems (slot endpoints, Chief task surfaces) that will
fully integrate in later passes. The intent is classified correctly
today; full execution arrives when those specialists are wired through
Chief.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─── Result helpers ────────────────────────────────────────────────

def _ok(intent: str, summary: str, details: Optional[Dict[str, Any]] = None,
        next_actions: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "intent": intent,
        "status": "ok",
        "summary": summary,
        "details": details or {},
        "next_actions": next_actions or [],
    }


def _failed(intent: str, summary: str, details: Optional[Dict[str, Any]] = None,
            next_actions: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "intent": intent,
        "status": "failed",
        "summary": summary,
        "details": details or {},
        "next_actions": next_actions or [],
    }


def _dry(intent: str, would_call: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "intent": intent,
        "status": "dry_run",
        "summary": f"[dry_run] would call {would_call}",
        "details": {"would_call": would_call, "payload": payload},
        "next_actions": [],
    }


def _skipped(intent: str, summary: str,
             details: Optional[Dict[str, Any]] = None,
             next_actions: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "intent": intent,
        "status": "skipped",
        "summary": summary,
        "details": details or {},
        "next_actions": next_actions or [],
    }


def _clarify(intent: str, summary: str, details: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "intent": intent,
        "status": "needs_clarification",
        "summary": summary,
        "details": details,
        "next_actions": ["rephrase request with more specificity"],
    }


# ─── Handlers ──────────────────────────────────────────────────────

def _handle_content_edit(
    business_id: str,
    params: Dict[str, Any],
    dry_run: bool,
) -> Dict[str, Any]:
    """Persist a text override via the PART 1 override system."""
    target_path = str(params.get("target_path") or "").strip()
    new_text = params.get("new_text")
    if not target_path or new_text is None:
        return _clarify(
            "content_edit",
            "Need to know which text to change and what to change it to.",
            {
                "missing": [
                    k for k, v in [("target_path", target_path), ("new_text", new_text)]
                    if not v
                ],
            },
        )
    payload = {
        "business_id": business_id,
        "override_type": "text",
        "target_path": target_path,
        "override_value": str(new_text),
        "created_via": "chief_command",
    }
    if dry_run:
        return _dry("content_edit", "override_storage.upsert_override", payload)
    try:
        from agents.override_system import override_storage
        row = override_storage.upsert_override(
            business_id=business_id,
            override_type="text",
            target_path=target_path,
            override_value=str(new_text),
            created_via="chief_command",
        )
    except Exception as e:
        logger.warning(f"[dispatcher.content_edit] upsert raised: {e}")
        return _failed(
            "content_edit",
            f"Couldn't save the text change ({type(e).__name__}). The site will keep its previous wording.",
            {"error": str(e)},
            next_actions=["retry the message", "try editing in MySite inline edit mode"],
        )
    if not row:
        return _failed(
            "content_edit",
            "Couldn't save the text change. The site will keep its previous wording.",
            {"persisted_row": None},
            next_actions=["retry the message", "check that the migration has been applied"],
        )
    return _ok(
        "content_edit",
        f"Updated {target_path} to '{new_text}'.",
        {"override_row": row},
        next_actions=["refresh the preview"],
    )


def _handle_color_swap(
    business_id: str,
    params: Dict[str, Any],
    dry_run: bool,
) -> Dict[str, Any]:
    """Persist a color_role override. Render-side application of the
    override lands in PART 3 (brand-kit → CSS-vars rewire). For PART 2
    the row persists so PART 3 can read it immediately on ship."""
    role = str(params.get("role") or "").strip()
    new_color = params.get("new_color")
    if not role or new_color is None:
        return _clarify(
            "color_swap",
            "Need to know which color role and what new value.",
            {
                "missing": [
                    k for k, v in [("role", role), ("new_color", new_color)]
                    if not v
                ],
            },
        )
    payload = {
        "business_id": business_id,
        "override_type": "color_role",
        "target_path": role,
        "override_value": str(new_color),
        "created_via": "chief_command",
    }
    if dry_run:
        return _dry("color_swap", "override_storage.upsert_override", payload)
    try:
        from agents.override_system import override_storage
        row = override_storage.upsert_override(
            business_id=business_id,
            override_type="color_role",
            target_path=role,
            override_value=str(new_color),
            created_via="chief_command",
        )
    except Exception as e:
        logger.warning(f"[dispatcher.color_swap] upsert raised: {e}")
        return _failed(
            "color_swap",
            f"Couldn't save the color change ({type(e).__name__}).",
            {"error": str(e)},
        )
    if not row:
        return _failed(
            "color_swap",
            "Couldn't save the color change.",
            {"persisted_row": None},
        )
    # Pass 4.0d PART 3 wired the render-time injection (brand_kit_renderer
    # picks up color_role overrides from site_content_overrides and writes
    # them into the :root block on every render). Sites whose Builder
    # output uses var(--brand-*) re-theme instantly; pre-PART-3 sites with
    # hardcoded hex need a rebuild to gain re-themability.
    return _ok(
        "color_swap",
        f"Saved color override: {role} → {new_color}. Refresh preview to see the change.",
        {"override_row": row},
        next_actions=["refresh the preview"],
    )


def _handle_design_refine(
    business_id: str,
    params: Dict[str, Any],
    dry_run: bool,
) -> Dict[str, Any]:
    """Delegate to Director's refine endpoint. Synchronous: blocks 3-5
    minutes when executing (full Builder regenerate). Returns
    immediately when dry_run=True with the payload that would be sent."""
    feedback_text = str(params.get("feedback_text") or "").strip()
    if not feedback_text:
        return _clarify(
            "design_refine",
            "Need to know what design change you'd like.",
            {"missing": ["feedback_text"]},
        )
    payload = {
        "business_id": business_id,
        "user_text": feedback_text,
        "quality": "hd",
    }
    if dry_run:
        return _dry("design_refine", "agents.director_agent.refine.run_refine", payload)
    try:
        from agents.director_agent.refine import run_refine
        result = run_refine(
            business_id=business_id,
            user_text=feedback_text,
            quality="hd",
        )
    except Exception as e:
        logger.warning(f"[dispatcher.design_refine] run_refine raised: {e}")
        return _failed(
            "design_refine",
            f"Director couldn't start the refine ({type(e).__name__}).",
            {"error": str(e)},
            next_actions=["retry the message", "try the Director Dock directly"],
        )
    status = (result or {}).get("status")
    if status == "in_flight":
        return _failed(
            "design_refine",
            "A build is already running for this site — wait for it to finish before kicking off another refine.",
            result,
            next_actions=["wait for the current build to finish", "check Director chat for progress"],
        )
    if status == "no_business_state":
        return _failed(
            "design_refine",
            "Director needs the site's persisted state and didn't find it. Generate the site first, then refine.",
            result,
            next_actions=["run Generate Site from MySite"],
        )
    if status == "error":
        return _failed(
            "design_refine",
            "Director hit an error trying to refine.",
            result,
            next_actions=["retry the message"],
        )
    return _ok(
        "design_refine",
        "Director is refining the site — watch Director chat for the progress and the completion notice.",
        result or {},
        next_actions=["watch Director chat for the build to complete"],
    )


def _handle_slot_change(params: Dict[str, Any], dry_run: bool) -> Dict[str, Any]:
    """PART 2 stub: classified, but slot operations stay on the existing
    /slots/{biz}/{slot}/* endpoints. Surfaces what the user wanted so
    the frontend can offer the right slot UI."""
    slot_name = str(params.get("slot_name") or "").strip()
    action = str(params.get("action") or "").strip()
    return _skipped(
        "slot_change",
        (
            f"Classified slot intent: slot={slot_name or '<unknown>'}, "
            f"action={action or '<unknown>'}. Use the Site Images modal "
            f"or call /slots/{{business_id}}/{{slot_name}}/{action or 'reroll'} "
            f"directly."
        ),
        {
            "slot_name": slot_name,
            "action": action,
            "would_dispatch_to": "/slots/{business_id}/{slot_name}/" + (action or "reroll"),
            "deferred_until": "pass-4-0d-part-2-or-later (slot ops keep using direct endpoints)",
        },
        next_actions=["open the Site Images modal", f"or POST /slots/{{biz}}/{slot_name}/{action or 'reroll'}"],
    )


def _handle_operational_task(params: Dict[str, Any]) -> Dict[str, Any]:
    """PART 2 stub. Chief task creation surfaces will route through
    chief_of_staff.py in a later pass; here we just acknowledge the
    classification so the practitioner knows Chief understood."""
    desc = str(params.get("task_description") or "").strip()
    return _skipped(
        "operational_task",
        (
            f"Recognized as operational task: {desc!r}. PART 2 doesn't wire "
            f"task creation through Chief yet — full integration arrives "
            f"in a later 4.0d sub-pass. Add it manually from the Tasks panel for now."
        ),
        {
            "task_description": desc,
            "deferred_until": "later-4-0d-subpass",
        },
        next_actions=["create the task from the Tasks panel"],
    )


def _handle_scheduling(params: Dict[str, Any]) -> Dict[str, Any]:
    desc = str(params.get("schedule_description") or "").strip()
    return _skipped(
        "scheduling",
        (
            f"Recognized as scheduling: {desc!r}. PART 2 doesn't wire "
            f"calendar through Chief yet — use the Calendar view directly."
        ),
        {"schedule_description": desc, "deferred_until": "later-4-0d-subpass"},
        next_actions=["open the Calendar view"],
    )


def _handle_briefing_request(params: Dict[str, Any]) -> Dict[str, Any]:
    scope = str(params.get("briefing_scope") or "").strip()
    return _skipped(
        "briefing_request",
        (
            f"Recognized as briefing request (scope={scope or 'unspecified'}). "
            f"PART 2 doesn't wire briefing through Chief yet — the existing "
            f"WeeklyBriefing dashboard tile is the canonical surface."
        ),
        {"briefing_scope": scope, "deferred_until": "later-4-0d-subpass"},
        next_actions=["open the Weekly Briefing dashboard"],
    )


def _handle_ambiguous(classification: Dict[str, Any]) -> Dict[str, Any]:
    """Confidence too low or unparseable. Ask for clarification."""
    params = classification.get("params") or {}
    best_guess = params.get("best_guess_intent")
    needs = params.get("needs") or "rephrase your request with more specifics"
    summary = (
        f"I'm not sure what you'd like to do. {needs.capitalize()}."
        if best_guess is None
        else f"I'd guess you want a {best_guess} action, but I'm not confident. {needs.capitalize()}."
    )
    return _clarify(
        "ambiguous",
        summary,
        {
            "best_guess_intent": best_guess,
            "best_guess_params": params.get("best_guess_params"),
            "classifier_reasoning": classification.get("reasoning"),
            "confidence": classification.get("confidence"),
        },
    )


# ─── Public entrypoint ─────────────────────────────────────────────

def dispatch(
    classification: Dict[str, Any],
    business_id: str,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """Route a classified intent to its specialist handler. Returns a
    LIST of per-intent results — singletons for single-intent classifications,
    one entry per sub_intent for multi_intent. List shape lets the
    response composer iterate uniformly.

    business_id is required for any handler that touches a per-business
    backend (content_edit, color_swap, design_refine). Stubs that don't
    use business_id (operational_task etc.) still receive it for future
    integration — no harm in passing through.
    """
    intent = classification.get("intent") or "ambiguous"

    if intent == "multi_intent":
        results: List[Dict[str, Any]] = []
        sub_intents = classification.get("sub_intents") or []
        if not sub_intents:
            # Defensive — classifier said multi_intent but didn't expand.
            return [_handle_ambiguous(classification)]
        for sub in sub_intents:
            sub_classification = {
                "intent": sub.get("intent"),
                "confidence": sub.get("confidence", 0.0),
                "reasoning": sub.get("reasoning") or "",
                "params": sub.get("params") or {},
                "sub_intents": [],
            }
            results.extend(dispatch(sub_classification, business_id, dry_run))
        return results

    params = classification.get("params") or {}

    if intent == "content_edit":
        return [_handle_content_edit(business_id, params, dry_run)]
    if intent == "color_swap":
        return [_handle_color_swap(business_id, params, dry_run)]
    if intent == "design_refine":
        return [_handle_design_refine(business_id, params, dry_run)]
    if intent == "slot_change":
        return [_handle_slot_change(params, dry_run)]
    if intent == "operational_task":
        return [_handle_operational_task(params)]
    if intent == "scheduling":
        return [_handle_scheduling(params)]
    if intent == "briefing_request":
        return [_handle_briefing_request(params)]
    # ambiguous + any unmapped value
    return [_handle_ambiguous(classification)]


def compose_response(
    classification: Dict[str, Any],
    results: List[Dict[str, Any]],
    user_text: str,
) -> Dict[str, Any]:
    """Stitch the per-intent results into the Chief reply shape.

    Returns:
      {
        "user_text": <original message>,
        "classification": { ... raw classifier output ... },
        "results": [ ... per-intent dispatch results ... ],
        "overall_status": "ok" | "partial" | "failed" | "needs_clarification" | "dry_run",
        "summary": "<single human-readable Chief reply combining the results>",
        "next_actions": [ ... deduped union of per-result next_actions ... ],
      }

    overall_status rules:
      - all 'ok' → 'ok'
      - all 'dry_run' → 'dry_run'
      - all 'failed' → 'failed'
      - all 'needs_clarification' → 'needs_clarification'
      - mixed but at least one 'ok' → 'partial'
      - else → 'failed' as the conservative default
    """
    statuses = {r.get("status", "failed") for r in results}
    if len(statuses) == 1:
        overall = next(iter(statuses))
    elif "ok" in statuses:
        overall = "partial"
    else:
        # No ok in the mix → conservative 'failed'
        overall = "failed"

    summary_lines = [r.get("summary", "") for r in results if r.get("summary")]
    summary = " ".join(summary_lines) if summary_lines else "No-op."

    seen: set = set()
    next_actions: List[str] = []
    for r in results:
        for a in (r.get("next_actions") or []):
            if a and a not in seen:
                seen.add(a)
                next_actions.append(a)

    return {
        "user_text": user_text,
        "classification": classification,
        "results": results,
        "overall_status": overall,
        "summary": summary,
        "next_actions": next_actions,
    }
