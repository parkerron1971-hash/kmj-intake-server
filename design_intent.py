"""
design_intent.py — reason about design intent instead of matching a table.

THE PROBLEM THIS EXISTS FOR: the site engine used to translate a
practitioner's style words into a look with keyword lookups — `_infer_vibe`
("warm" in the words → warm, else default formal), `VIBE_FAMILY_MAP`, the
fuzzy font tables. A lookup only ever "knows" the exact words someone typed
into it. Say "trustworthy", "serene", "high-end but approachable", "a modern
law firm" and the tables shrug and fall through to a default. Every new
concept needs a human to enumerate it. That does not generalize.

THE PATTERN THIS IMPLEMENTS: hand the model a RUBRIC — what each design
primitive *expresses*, as territory, not keywords — plus the practitioner's
ACTUAL words, and ask it to REASON which primitive fits. A descriptor nobody
coded still lands somewhere sensible, with its reasoning attached. The output
is constrained to the exact primitives the deterministic renderer already
knows how to build (the 3 vibe families + intensity) — so it is FREEDOM IN
JUDGMENT, DETERMINISM IN EXECUTION: the model can interpret anything, but can
only ever emit a look the renderer can safely produce.

This is the reference implementation of "teach the rubric, not the cases."
It is the first surface where a request the system was never coded for still
works — and the shape to copy for the next one.

Everything FAILS OPEN: no key, a bad reply, or low confidence → returns None,
and the caller keeps the existing keyword behavior. Kill switch
SITE_DESIGN_REASONING=off. Decided ONCE at compose time and persisted onto
design.vibe_family, so the render hot path never calls a model.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

import llm_call

import chief_models

logger = logging.getLogger("design_intent")


# The safe output primitives — 1:1 with what the renderer can build
# (smart_sites.VIBE_FAMILIES / brand_dna intensity ladder).
VIBE_FAMILIES = ("warm", "formal", "bold")
INTENSITIES = ("restrained", "confident", "bold")

# Below this the model is telling us it's guessing — defer to the keyword
# fallback rather than commit to a shaky read.
_MIN_CONFIDENCE = 0.4

# The rubric: each vibe as an EXPRESSIVE TERRITORY, not a keyword list, so
# the model can map descriptors that were never enumerated.
_SYSTEM = """You are the design-intent interpreter for a small-business website builder. You are given the words a business owner used to describe how they want their site to feel — which may be anything, including words no one anticipated — and you decide which of three build-able looks best serves that intent, and how hard to push it.

You are NOT matching keywords. You are reasoning about what the words MEAN and which territory they belong to.

THE THREE LOOKS (pick exactly one):
- "warm" — approachable, human, soft, organic, welcoming, personal, nurturing, artisanal, boutique, calm, gentle, cozy, serene. Rounded and inviting. (A wellness studio, a family practice, a craft maker, a community org.)
- "formal" — professional, authoritative, trustworthy, refined, corporate, established, credible, precise, serious, discreet, high-end/luxury restraint. Structured and dignified. (A law firm, a financial advisor, a consultancy, a clinic, an executive brand.)
- "bold" — energetic, confident, dramatic, striking, loud, creative, edgy, expressive, modern, high-contrast, daring, vibrant. Big and attention-commanding. (A creative studio, a fitness brand, a launch, a personality-forward founder.)

INTENSITY — how far to push the chosen look:
- "restrained" — quiet, minimal, lots of room; let the content lead.
- "confident" — the default; clearly styled without shouting.
- "bold" — maximal expression of the look.

Rules:
- Weigh ALL the words together. If they conflict ("professional but approachable"), pick the family for the DOMINANT intent and use intensity to honor the secondary one (e.g. formal + restrained for "approachable professional").
- If a business type is given, let it break ties — a law firm leans formal, a coach leans warm, a creative leans bold — but the owner's words win over the type when they clearly point elsewhere.
- Give a ONE-sentence rationale naming which words drove the choice.
- confidence is 0.0–1.0: how clearly the words point to one look. Genuinely vague/empty input → low confidence.

Respond with ONLY this JSON (no prose, no fence):
{"vibe":"warm|formal|bold","intensity":"restrained|confident|bold","rationale":"<one sentence>","confidence":<0.0-1.0>}"""


def _enabled() -> bool:
    if (os.environ.get("SITE_DESIGN_REASONING") or "on").strip().lower() == "off":
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _norm_descriptors(descriptors: Any) -> List[str]:
    if isinstance(descriptors, list):
        raw = descriptors
    elif descriptors:
        raw = [descriptors]
    else:
        raw = []
    out: List[str] = []
    seen = set()
    for d in raw:
        s = str(d or "").strip()
        k = s.lower()
        if s and k not in seen:
            seen.add(k)
            out.append(s[:60])
    return out[:12]


def _validate(obj: Any) -> Optional[Dict[str, Any]]:
    """Accept only a well-formed read that names a build-able look."""
    if not isinstance(obj, dict):
        return None
    vibe = str(obj.get("vibe") or "").strip().lower()
    intensity = str(obj.get("intensity") or "").strip().lower()
    if vibe not in VIBE_FAMILIES:
        return None
    if intensity not in INTENSITIES:
        intensity = "confident"
    try:
        confidence = float(obj.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.5
    return {
        "vibe": vibe,
        "intensity": intensity,
        "rationale": str(obj.get("rationale") or "").strip()[:240],
        "confidence": max(0.0, min(1.0, confidence)),
    }


def _build_user_msg(descriptors: List[str], business_type: Optional[str]) -> str:
    bt = (business_type or "").strip()
    return (
        f"BUSINESS TYPE: {bt or '(unspecified)'}\n"
        f"WORDS THE OWNER USED: {', '.join(descriptors) if descriptors else '(none given)'}\n\n"
        f"Return the JSON now."
    )


def interpret(descriptors: Any, business_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Reason the owner's style words into a build-able look. Returns
    {vibe, intensity, rationale, confidence} or None (fail-open — caller
    falls back to the keyword logic). None when: disabled, no descriptors,
    the model errors, the reply is malformed, or confidence is too low."""
    if not _enabled():
        return None
    words = _norm_descriptors(descriptors)
    if not words:
        return None  # nothing to reason about → keyword fallback / default

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    model = chief_models.model_for("background")
    try:
        resp = llm_call.post({
            "model": model, "max_tokens": 250,
            "system": _SYSTEM,
            "messages": [{"role": "user",
                          "content": _build_user_msg(words, business_type)}],
        }, timeout=httpx.Timeout(connect=8.0, read=30.0, write=15.0, pool=8.0), key=key)
    except httpx.HTTPError as e:
        logger.info(f"[design_intent] call failed: {e}")
        return None
    if resp.status_code >= 400:
        logger.info(f"[design_intent] {resp.status_code}: {resp.text[:160]}")
        return None

    try:
        data = resp.json()
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        try:
            from api_usage_logger import log_api_usage_sync
            log_api_usage_sync(endpoint="/site/design-intent",
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
        read = _validate(json.loads(text[start:end + 1]))
    except (ValueError, TypeError) as e:
        logger.info(f"[design_intent] unparseable reply: {e}")
        return None

    if not read or read["confidence"] < _MIN_CONFIDENCE:
        return None
    logger.info(f"[design_intent] {words} → {read['vibe']}/{read['intensity']} "
                f"({read['confidence']:.2f}): {read['rationale']}")
    return read
