"""Pass 4.0c PART 2 — Feedback Enrichment.

Mirrors Sparse-Input Enrichment (Pass 4.0a) but for refine-time
feedback. Vague request from a practitioner ("more bold", "the
gallery feels empty") → specific punch list of design moves anchored
to the active Design Intelligence Module's rubric.

Used by /director/refine (PART 3) to pre-process feedback before
calling build_with_loop with the resulting moves as the punch_list.

Soft-fails on missing API key, LLM error, or non-JSON model output —
returns a structured fallback dict with `_enrichment_error` populated.
Caller treats failure as "use raw user_text as the punch list" (the
Builder's prompt can interpret natural language too, just less
precisely).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from anthropic import Anthropic

logger = logging.getLogger(__name__)

ENRICHMENT_MODEL = "claude-sonnet-4-5-20250929"
ENRICHMENT_MAX_TOKENS = 2000
ENRICHMENT_TEMPERATURE = 0.3
# Cap module text size so we don't blow the context window. Cinematic
# Authority is ~25K chars; 30K leaves room for the brief + design pick
# + system prompt without crowding the response budget.
MODULE_TEXT_CAP = 30_000


ENRICHMENT_SYSTEM_PROMPT = """You are a Design Feedback Enrichment Agent for the Solutionist Design System. Your job: take vague design feedback ("more bold", "the gallery feels empty", "stronger CTAs") and expand it into a specific punch list of design moves grounded in the site's active Design Intelligence Module.

You receive:
- The user's feedback text
- The active Design Intelligence Module (full markdown text)
- The current site's enriched_brief (vibe, brand_metaphor, etc.)
- The current site's design_pick (strand_a, strand_b, ratio, sub_strand)

You output strict JSON:
{
  "inferred_intent": "1 sentence describing what the user actually wants",
  "expanded_moves": [
    {
      "rule_id": "matches a rubric rule_id when possible, otherwise descriptive",
      "severity": "HIGH" | "MEDIUM",
      "description": "specific change to make",
      "fix_hint": "actionable instruction the Builder can follow"
    }
  ],
  "scope": "global" | "single_section" | "single_element",
  "estimated_regenerate_needed": true | false
}

Match user intent to module-specific moves. For Cinematic Authority, "more bold" means heavier weights + bigger scale + tighter letter-spacing + more saturated gold + larger CTA bands — NOT generic "make it pop."

If the user's feedback is already specific (e.g. "change the hero photo"), expanded_moves can be a single targeted instruction. estimated_regenerate_needed=false for slot-only changes (those go through slot management, not Builder regenerate). estimated_regenerate_needed=true for any change that requires re-rendering HTML (typography, layout, copy, color, structure).

Aim for 3-7 specific moves on broad feedback ("more bold"), 1-3 on narrow feedback ("change the headline color").

Output ONLY raw JSON. No markdown fences. No commentary."""


def _safe_fallback(reason: str, raw: Optional[str] = None) -> Dict[str, Any]:
    """Structured fallback when the LLM call or parse fails. Caller can
    detect via the `_enrichment_error` key — when present, /director/
    refine can either retry or fall back to using user_text as the
    punch list directly."""
    out: Dict[str, Any] = {
        "inferred_intent": "Unable to enrich feedback",
        "expanded_moves": [],
        "scope": "global",
        "estimated_regenerate_needed": True,  # safer default — let Builder try
        "_enrichment_error": reason,
    }
    if raw:
        out["_raw_response"] = raw[:500]
    return out


def _strip_code_fence(text: str) -> str:
    """Remove leading ```json … ``` if the model added one despite
    the system prompt instructions. Mirrors the helper in llm_judge.py
    and sparse_input_enrichment.py."""
    text = (text or "").strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl > 0:
            text = text[nl + 1:]
        if text.endswith("```"):
            text = text[: -3]
    return text.strip()


def enrich_feedback(
    user_text: str,
    module_id: str,
    enriched_brief: Optional[Dict[str, Any]],
    design_pick: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Enrich vague refine-time feedback into specific design moves.

    Returns:
      {
        "inferred_intent": str,
        "expanded_moves": [{rule_id, severity, description, fix_hint}, ...],
        "scope": "global" | "single_section" | "single_element",
        "estimated_regenerate_needed": bool,
        "_enrichment_error"?: str,
        "_raw_response"?: str,
      }

    Never raises — soft-fails to a structured fallback dict.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _safe_fallback("ANTHROPIC_API_KEY not configured")

    if not (user_text or "").strip():
        return _safe_fallback("empty user_text")

    # Lazy import keeps this module testable without the Design
    # Intelligence package on the path (e.g. unit tests).
    try:
        from agents.design_intelligence import load_module
        module_text = load_module(module_id) or ""
    except Exception as e:
        logger.warning(f"[feedback_enrichment] load_module failed: {e}")
        module_text = ""

    enriched_brief = enriched_brief or {}
    design_pick = design_pick or {}

    user_message_parts: List[str] = [
        f"USER FEEDBACK:\n{user_text}",
        f"\nENRICHED BRIEF:\n{json.dumps(enriched_brief, indent=2, ensure_ascii=False)}",
        f"\nDESIGN PICK:\n{json.dumps(design_pick, indent=2, ensure_ascii=False)}",
    ]
    if module_text:
        user_message_parts.append(
            f"\nDESIGN INTELLIGENCE MODULE ({module_id}):\n"
            f"{module_text[:MODULE_TEXT_CAP]}"
        )
    user_message = "\n".join(user_message_parts)

    try:
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=ENRICHMENT_MODEL,
            max_tokens=ENRICHMENT_MAX_TOKENS,
            temperature=ENRICHMENT_TEMPERATURE,
            system=ENRICHMENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        logger.warning(
            f"[feedback_enrichment] Anthropic call failed: {type(e).__name__}: {e}"
        )
        return _safe_fallback(
            f"Anthropic call failed: {type(e).__name__}: {e}"
        )

    text = "".join(
        b.text for b in msg.content if getattr(b, "type", None) == "text"
    )
    text = _strip_code_fence(text)
    if not text:
        return _safe_fallback("Empty model response")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"[feedback_enrichment] JSON parse failed: {e}")
        return _safe_fallback(f"JSONDecodeError: {e}", raw=text)

    if not isinstance(parsed, dict):
        return _safe_fallback("Model returned non-object", raw=text)

    # Ensure all canonical keys exist so consumers can destructure
    # without optional-key gymnastics.
    parsed.setdefault("inferred_intent", "")
    parsed.setdefault("expanded_moves", [])
    parsed.setdefault("scope", "global")
    parsed.setdefault("estimated_regenerate_needed", True)

    # Type guards on expanded_moves — drop entries that aren't dicts
    # with the four required keys, so downstream Builder code can
    # consume the list without per-entry validation.
    moves_raw = parsed.get("expanded_moves") or []
    if not isinstance(moves_raw, list):
        moves_raw = []
    cleaned_moves: List[Dict[str, Any]] = []
    for m in moves_raw:
        if not isinstance(m, dict):
            continue
        cleaned_moves.append({
            "rule_id": str(m.get("rule_id") or "unspecified"),
            "severity": (
                str(m.get("severity") or "MEDIUM").upper()
                if str(m.get("severity") or "").upper() in ("HIGH", "MEDIUM", "LOW")
                else "MEDIUM"
            ),
            "description": str(m.get("description") or "").strip(),
            "fix_hint": str(m.get("fix_hint") or "").strip(),
        })
    parsed["expanded_moves"] = cleaned_moves

    return parsed
