"""
practitioner_voice.py — Living Growth System Phase 2: one consistent voice
directive across every practitioner-facing artifact.

Before Phase 2 each generator (contract_agent, payment_agent, ...) read
business.voice_profile ad-hoc. This composes ONE directive from all the voice
signals a business carries — voice_profile + brand_kit tone_words + the Pass
4.0i creative_expression intensity — so a contract, an invoice nudge, and a
hero all sound like the same person.

Pure function over the already-loaded `business` dict — no DB call, no LLM.
Generators inject the returned line into their system prompt as an additional
directive (additive — it doesn't replace their existing voice handling).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# creative_expression.intensity → a plain-language register hint. Mirrors the
# Studio Brut vocabulary (Pass 4.0i) without importing the render layer.
_INTENSITY_REGISTER = {
    "restrained": "measured and understated — let substance carry the weight",
    "confident": "warm and self-assured — personable without being loud",
    "bold": "declarative and energetic — lead with conviction",
}


def _brand_kit(business: Dict[str, Any]) -> Dict[str, Any]:
    settings = business.get("settings") or {}
    bk = settings.get("brand_kit") if isinstance(settings, dict) else None
    return bk if isinstance(bk, dict) else {}


def _tone_words(business: Dict[str, Any]) -> List[str]:
    bk = _brand_kit(business)
    tw = bk.get("tone_words")
    if isinstance(tw, list):
        return [str(w) for w in tw if isinstance(w, str)]
    return []


def _intensity_register(business: Dict[str, Any]) -> Optional[str]:
    ce = _brand_kit(business).get("creative_expression")
    if isinstance(ce, dict):
        return _INTENSITY_REGISTER.get(ce.get("intensity"))
    return None


def compose_voice_directive(business: Dict[str, Any]) -> str:
    """Return a single directive line composing the business's voice signals.
    Empty string when the business carries no usable voice signal (caller's
    existing handling stands)."""
    if not isinstance(business, dict):
        return ""
    voice = business.get("voice_profile") or {}
    if not isinstance(voice, dict):
        voice = {}

    parts: List[str] = []
    tone = voice.get("tone")
    personality = voice.get("personality")
    if tone:
        parts.append(f"tone is \"{tone}\"")
    if personality:
        parts.append(f"personality is \"{personality}\"")

    tone_words = _tone_words(business)
    if tone_words:
        parts.append("brand tone words: " + ", ".join(tone_words[:6]))

    register = _intensity_register(business)
    if register:
        parts.append(f"register: {register}")

    if not parts:
        return ""
    return (
        "Write in this practitioner's established voice — " + "; ".join(parts) +
        ". Keep every artifact sounding like the same person."
    )


def voice_signals(business: Dict[str, Any]) -> Dict[str, Any]:
    """Structured view of the composed signals — handy for tests + debugging."""
    voice = business.get("voice_profile") or {}
    return {
        "tone": voice.get("tone") if isinstance(voice, dict) else None,
        "personality": voice.get("personality") if isinstance(voice, dict) else None,
        "tone_words": _tone_words(business),
        "intensity_register": _intensity_register(business),
    }
