"""Pass 4.0d PART 2 — Intent classifier.

Sonnet pre-processor. Maps a free-text practitioner message to one of
9 intent categories with confidence + extracted parameters.

Soft-fails to a structured fallback dict (intent='ambiguous',
confidence=0.0, _classifier_error populated) so dispatch always has
something to work with.

Mirrors the LLM pattern used in agents.director_agent.feedback_enrichment:
  - lazy Anthropic SDK import
  - _strip_code_fence helper for occasional fence-leakage
  - explicit JSON schema in the system prompt
  - never raises; soft-fail returns the structured fallback

Public API:
  classify_intent(user_text, current_view='mysite') -> Dict[str, Any]
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from anthropic import Anthropic

logger = logging.getLogger(__name__)

CLASSIFIER_MODEL = "claude-sonnet-4-5-20250929"
CLASSIFIER_MAX_TOKENS = 600
CLASSIFIER_TEMPERATURE = 0.2

# Below this, route to 'ambiguous' so Chief asks the user to clarify
# rather than guessing wrong. Tunable; 0.6 is the user's planning-doc
# decision baseline.
CONFIDENCE_THRESHOLD = 0.6


VALID_INTENTS = {
    "design_refine",
    "content_edit",
    "slot_change",
    "color_swap",
    "operational_task",
    "scheduling",
    "briefing_request",
    "multi_intent",
    "ambiguous",
}


CLASSIFIER_SYSTEM_PROMPT = """You are the Chief Intent Classifier for Solutionist Studio. The practitioner sends one message; you decide which backend specialist should handle it.

You output ONE JSON object — no markdown, no prose, no explanation. The schema:

{
  "intent": "<one of: design_refine | content_edit | slot_change | color_swap | operational_task | scheduling | briefing_request | multi_intent | ambiguous>",
  "confidence": <float 0.0–1.0>,
  "reasoning": "<one sentence: why this intent>",
  "params": { ... intent-specific extracted parameters ... },
  "sub_intents": [ ... only when intent=='multi_intent', list of {intent, confidence, params} ... ]
}

INTENT DEFINITIONS:

- design_refine — the user wants a design-level change that requires re-rendering the HTML (typography weight, color temperature, layout, spacing, overall vibe). Examples: "make the gold warmer", "the headlines feel weak", "more breathing room in the hero", "stronger CTAs".
  params: { "feedback_text": "<the user's design ask, copied or lightly paraphrased>" }

- content_edit — the user wants to change SPECIFIC TEXT on the site. Examples: "change the hero headline to Crown Your Closet", "the about paragraph should say X", "update the CTA to Book Now".
  params: { "target_path": "<best-guess semantic path like hero.heading | about.body | services[0].cta_label>", "new_text": "<the replacement copy>" }

- slot_change — the user wants to change a SPECIFIC IMAGE (not all images, not a stylistic image direction). Examples: "swap the hero photo", "the testimonial photo is wrong", "use a different image for the about section".
  params: { "slot_name": "<best-guess slot identifier like hero_image | about_photo | testimonial_1>", "action": "<reroll | upload_prompt | clear>" }

- color_swap — the user wants to change a specific palette ROLE'S color value. Examples: "change the authority color to navy", "the gold is wrong, try purple", "swap the warm neutral to off-white".
  params: { "role": "<authority | signal | warm_neutral | text_dark | text_light>", "new_color": "<7-character hex code like #6B46C1>" }

  COLOR VALUE EXTRACTION (strict):
  - ALWAYS output new_color as a 7-character hex code starting with #
  - NEVER output color names like "deep amber" or "royal purple" — convert to hex
  - "warm gold"        → "#D4A03A" (or similar warm gold hex)
  - "royal purple"     → "#6B46C1" (or similar deep purple)
  - "navy"             → "#0A1628" (or similar deep navy)
  - "off-white"        → "#FAFAFA" (or similar near-white)
  - "deep amber"       → "#D97706" (or similar deep amber)
  - "burgundy"         → "#7C1D2E" or similar
  - If the user gives an exact hex already, use it verbatim
  - If genuinely ambiguous ("make it a different color", no target color given), set confidence below threshold (so the request demotes to ambiguous)
  - Use your color knowledge to pick a sensible hex that matches the descriptive name; the practitioner can always override the exact value later

- operational_task — the user is asking Chief to do business-operational work: tasks, contacts, invoices, contracts, products. Examples: "add a task to follow up with the Davidson lead", "create an invoice for $500".
  params: { "task_description": "<what the user wants done>" }

- scheduling — calendar / time-block related. Examples: "block out Tuesday morning for sermon prep", "what's on my calendar Thursday".
  params: { "schedule_description": "<what the user wants done>" }

- briefing_request — the user wants a status / summary / situation report. Examples: "what's on my plate today", "give me the morning briefing", "where do we stand".
  params: { "briefing_scope": "<daily | weekly | site_status | pipeline | other>" }

- multi_intent — the message bundles 2+ separate asks that map to different intents above. Examples: "change the hero headline to Crown Your Closet AND make the gold warmer" (content_edit + design_refine).
  sub_intents: [ { "intent": ..., "confidence": ..., "params": ... }, ... ] — each item must be a single (non-multi) intent.

- ambiguous — you can't tell what the user wants with confidence ≥ 0.6. Set confidence to the highest single-intent confidence you considered. Set params to { "best_guess_intent": "<intent name>", "needs": "<what clarification would help>" }.

DECISION RULES:
1. If the message has BOTH a specific text-change AND a design refinement, that's multi_intent — not design_refine. Specific text wins over abstract design every time.
2. "Make X bigger / bolder / warmer / more emphatic" → design_refine. NOT content_edit.
3. "Change X to Y" where Y is concrete text → content_edit. "Change the gold to be warmer" → design_refine (no concrete value). "Change the authority color to #5500ff" → color_swap (concrete role + value).
4. Image words ("photo", "image", "picture", specific image references) → slot_change.
5. Single-sentence messages that don't fit any of the above → ambiguous with best_guess_intent populated.
6. confidence should reflect your actual certainty. A clear, unambiguous request → 0.9+. A request that's mostly clear but has a small twist → 0.7–0.85. A request that requires guessing → ≤0.5.

Output ONLY raw JSON. No markdown fences. No commentary outside the JSON. No trailing text."""


def _safe_fallback(reason: str, raw: Optional[str] = None) -> Dict[str, Any]:
    """Structured fallback when classifier fails. Dispatcher treats this
    as the ambiguous intent so it asks the user to clarify."""
    out: Dict[str, Any] = {
        "intent": "ambiguous",
        "confidence": 0.0,
        "reasoning": f"classifier failed: {reason}",
        "params": {
            "best_guess_intent": None,
            "needs": "could not classify — please rephrase your request",
        },
        "sub_intents": [],
        "_classifier_error": reason,
    }
    if raw:
        out["_raw_response"] = raw[:500]
    return out


def _strip_code_fence(text: str) -> str:
    """Remove leading ```json … ``` if the model added one despite the
    system prompt. Same helper as feedback_enrichment / llm_judge /
    sparse_input_enrichment."""
    text = (text or "").strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl > 0:
            text = text[nl + 1:]
        if text.endswith("```"):
            text = text[: -3]
    return text.strip()


def _validate_and_normalize(parsed: Any) -> Dict[str, Any]:
    """Coerce LLM output into the canonical shape. Drops invalid sub_intents,
    forces unknown intents to 'ambiguous', clamps confidence into [0,1]."""
    if not isinstance(parsed, dict):
        return _safe_fallback("non-object response", raw=str(parsed))

    intent = str(parsed.get("intent") or "").strip()
    if intent not in VALID_INTENTS:
        # Unknown intent label → ambiguous. Preserve the raw response
        # so the dispatcher can log it.
        return _safe_fallback(
            f"unknown intent label: {intent!r}", raw=json.dumps(parsed)[:500]
        )

    try:
        confidence = float(parsed.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    reasoning = str(parsed.get("reasoning") or "").strip()
    params = parsed.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    sub_intents_raw = parsed.get("sub_intents") or []
    sub_intents: List[Dict[str, Any]] = []
    if intent == "multi_intent" and isinstance(sub_intents_raw, list):
        for s in sub_intents_raw:
            if not isinstance(s, dict):
                continue
            si_intent = str(s.get("intent") or "").strip()
            if si_intent not in VALID_INTENTS or si_intent == "multi_intent":
                # Skip nested multi_intent (we already flattened).
                continue
            try:
                si_conf = float(s.get("confidence") or 0.0)
            except (TypeError, ValueError):
                si_conf = 0.0
            si_params = s.get("params") or {}
            if not isinstance(si_params, dict):
                si_params = {}
            sub_intents.append(
                {
                    "intent": si_intent,
                    "confidence": max(0.0, min(1.0, si_conf)),
                    "params": si_params,
                }
            )

    # Apply confidence threshold gate. For multi_intent, threshold check
    # uses the WEAKEST sub-intent's confidence — a multi-ask is only as
    # confident as its least-clear component.
    if intent == "multi_intent" and sub_intents:
        min_sub_conf = min(s["confidence"] for s in sub_intents)
        effective_conf = min_sub_conf
    else:
        effective_conf = confidence

    if intent != "ambiguous" and effective_conf < CONFIDENCE_THRESHOLD:
        # Demote to ambiguous so dispatcher asks for clarification.
        return {
            "intent": "ambiguous",
            "confidence": effective_conf,
            "reasoning": (
                f"original={intent} but confidence {effective_conf:.2f} "
                f"below threshold {CONFIDENCE_THRESHOLD}"
            ),
            "params": {
                "best_guess_intent": intent,
                "best_guess_params": params,
                "needs": "rephrase or add detail so the request is unambiguous",
            },
            "sub_intents": sub_intents,
        }

    return {
        "intent": intent,
        "confidence": confidence,
        "reasoning": reasoning,
        "params": params,
        "sub_intents": sub_intents,
    }


def classify_intent(
    user_text: str,
    current_view: str = "mysite",
) -> Dict[str, Any]:
    """Run the Sonnet intent classifier on the practitioner's message.

    Args:
      user_text: the practitioner's message verbatim.
      current_view: which app surface they're typing from (mysite,
        dashboard, etc.). Currently advisory only — included in the
        prompt so the classifier can bias toward likely intents
        (e.g., "change X" on mysite is more likely content_edit;
        on dashboard it's more likely operational_task).

    Returns:
      {
        "intent": str,
        "confidence": float,
        "reasoning": str,
        "params": dict,
        "sub_intents": list,           # populated when intent==multi_intent
        "_classifier_error"?: str,     # present on soft-fail
        "_raw_response"?: str,
      }

    Never raises.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _safe_fallback("ANTHROPIC_API_KEY not configured")

    if not (user_text or "").strip():
        return _safe_fallback("empty user_text")

    user_message = (
        f"CURRENT VIEW: {current_view}\n\n"
        f"PRACTITIONER MESSAGE:\n{user_text}"
    )

    try:
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=CLASSIFIER_MAX_TOKENS,
            temperature=CLASSIFIER_TEMPERATURE,
            system=CLASSIFIER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        logger.warning(
            f"[intent_classifier] Anthropic call failed: {type(e).__name__}: {e}"
        )
        return _safe_fallback(f"Anthropic call failed: {type(e).__name__}: {e}")

    text = "".join(
        b.text for b in msg.content if getattr(b, "type", None) == "text"
    )
    text = _strip_code_fence(text)
    if not text:
        return _safe_fallback("empty model response")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"[intent_classifier] JSON parse failed: {e}")
        return _safe_fallback(f"JSONDecodeError: {e}", raw=text)

    normalized = _validate_and_normalize(parsed)
    return normalized
