"""Pass 4.0a — Sparse-Input Enrichment.

Closes the 'sparse prompt → premium output' gap that Lovable handles
silently. Given a thin practitioner intake (business name, vague
description, color hints), outputs an enriched brief with vibe
inference, brand metaphor, palette roles, audience profile, and
content archetype.

Fed to the Designer Agent (Pass 4.0b) BEFORE strand selection so it
works with rich input instead of vague input. In Pass 4.0a we only
stand the endpoint up; no existing agent calls it yet.

Project conventions matched here:
  - Direct `anthropic.Anthropic` SDK (no internal helper indirection)
  - Model `claude-sonnet-4-5-20250929` (matches ai_proxy / brand_engine /
    chief_of_staff)
  - API key from `ANTHROPIC_API_KEY` env var
  - Soft-fail on missing key / LLM error → return safe fallback dict
    rather than raising, so the Designer Agent can still proceed
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from anthropic import Anthropic

logger = logging.getLogger(__name__)

ENRICHMENT_MODEL = "claude-sonnet-4-5-20250929"
ENRICHMENT_MAX_TOKENS = 1500
ENRICHMENT_TEMPERATURE = 0.3  # low — consistent inference, not creative variation


ENRICHMENT_SYSTEM_PROMPT = """You are a Sparse-Input Enrichment Agent for a website design system. Your job is to take thin/vague practitioner intake and infer everything a designer would silently fill in before generating a site.

You enrich the brief with:

1. inferred_vibe — 3-5 word description of the emotional feel (e.g. "luxury masculine premium", "warm community-rooted", "editorial counsel quiet authority")

2. brand_metaphor — the conceptual hook hidden in the brand name or description (e.g. "Royal Palace" → royalty/regal/court, "Embrace the Shift" → transformation/movement/pivot, "KMJ & Co." → editorial counsel/cathedral/practice). If no metaphor exists, return null.

3. brand_metaphor_application — concrete instructions for how to extend the metaphor through the site. CTAs, eyebrow labels, section titles, copy voice. Example for Royal Palace: "Reframe CTAs in royal/regal language: 'Book Your Throne' instead of 'Book Now', 'Reserve Your Seat at Court' instead of 'Schedule'. Section eyebrows use court/palace metaphors: 'THE COURT' for testimonials, 'THE CHAMBERS' for services."

4. palette_roles — assign each provided color to a structural role:
   {primary_bg, accent, warm_secondary, text_on_dark, text_on_light, cta_color}

5. audience_profile — 1-sentence description of who the site speaks to

6. content_archetype — pick one: service_business, knowledge_brand, ministry, trading_practice, creative_agency, coaching_practice, product_business, community_platform

7. emotional_progression — for the 5-7 sections of the site, what emotion each should evoke (Authority → Credibility → Trust → Belonging → Clarity → Ease → Urgency)

Return ONLY raw JSON. No markdown. No commentary. No code fences."""


_FALLBACK_KEYS = (
    "inferred_vibe",
    "brand_metaphor",
    "brand_metaphor_application",
    "palette_roles",
    "audience_profile",
    "content_archetype",
    "emotional_progression",
)


def _safe_fallback(reason: str, raw: Optional[str] = None) -> Dict[str, Any]:
    """Return the deterministic fallback shape used when the LLM call
    fails, the key is missing, or JSON parsing breaks. Designer Agent
    callers can detect the failure via `_enrichment_error`."""
    out: Dict[str, Any] = {
        "inferred_vibe": "professional contemporary",
        "brand_metaphor": None,
        "brand_metaphor_application": None,
        "palette_roles": {},
        "audience_profile": "general professional audience",
        "content_archetype": "service_business",
        "emotional_progression": [],
        "_enrichment_error": reason,
    }
    if raw:
        out["_raw_response"] = raw[:500]
    return out


def _strip_code_fence(text: str) -> str:
    """Strip a leading/trailing ```json …``` fence if the model added
    one despite instructions. No-op when no fence present."""
    text = text.strip()
    if text.startswith("```"):
        # Drop the first line (```json or just ```)
        nl = text.find("\n")
        if nl > 0:
            text = text[nl + 1 :]
        # Drop the trailing ``` if present
        if text.endswith("```"):
            text = text[: -3]
    return text.strip()


def enrich_intake(
    business_name: str,
    description: Optional[str] = None,
    colors: Optional[List[str]] = None,
    practitioner_voice: Optional[str] = None,
    strategy_track_summary: Optional[str] = None,
) -> Dict[str, Any]:
    """Enrich a sparse practitioner intake. Returns the enriched brief
    as a dict with the seven keys (inferred_vibe / brand_metaphor /
    brand_metaphor_application / palette_roles / audience_profile /
    content_archetype / emotional_progression).

    Soft-fails on missing API key, LLM error, or JSON parse error —
    returns the deterministic fallback dict with `_enrichment_error`
    populated. Never raises.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _safe_fallback("ANTHROPIC_API_KEY not configured")

    parts: List[str] = [f"Business name: {business_name}"]
    if description:
        parts.append(f"Description: {description}")
    if colors:
        parts.append(f"Colors: {', '.join(colors)}")
    if practitioner_voice:
        parts.append(f"Voice: {practitioner_voice}")
    if strategy_track_summary:
        parts.append(f"Strategy summary: {strategy_track_summary}")
    user_message = "\n".join(parts)

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
        logger.warning(f"[enrichment] Anthropic call failed: {type(e).__name__}: {e}")
        return _safe_fallback(f"Anthropic call failed: {type(e).__name__}")

    text = "".join(
        b.text for b in msg.content if getattr(b, "type", None) == "text"
    )
    text = _strip_code_fence(text)

    if not text:
        return _safe_fallback("Empty model response")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"[enrichment] JSON parse failed: {e}")
        return _safe_fallback(f"JSONDecodeError: {e}", raw=text)

    if not isinstance(parsed, dict):
        return _safe_fallback("Model returned non-object", raw=text)

    # Don't overwrite valid model output with defaults — just ensure all
    # seven canonical keys exist on the returned dict so consumers can
    # destructure without optional-key gymnastics.
    for k in _FALLBACK_KEYS:
        parsed.setdefault(k, None if k != "palette_roles" else {})

    return parsed
