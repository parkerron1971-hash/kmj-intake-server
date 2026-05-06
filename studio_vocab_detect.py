"""Studio Vocabulary Detection: rule-based scoring against existing business data.

Inputs (from existing tables — no new intake forms):
  - business_row (businesses row, for name + type)
  - business_profile (business_profiles row)
  - voice_profile (businesses.voice_profile JSONB)
  - brand_kit (businesses.settings.brand_kit, optional — not load-bearing
    for detection but available for future signal extraction)

Output: top 3 vocabulary candidates with confidence scores + reasons.

Scoring layers (additive):
  1. Archetype affinity boost          (max ~1.0)
  2. Brand voice affinity boost        (max ~0.8)
  3. Signal word matches               (capped at 0.6)
  4. Detection signal matches          (capped at 0.5)

Final confidence = min(score / 3.0, 1.0). The threshold for inclusion in
the top-3 is score > 0.3, which roughly means "at least one strong source
of signal beyond zero."

This is heuristic, not perfect. Session 3 will surface the top-3 in the UI
so users can override when auto-detection misses.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, TypedDict

from studio_data import VOCABULARIES, CulturalVocabulary


class VocabularyMatch(TypedDict):
    vocabulary: CulturalVocabulary
    confidence: float
    reasons: List[str]


# ─── ARCHETYPE → VOCABULARY AFFINITIES ────────────────────────────────
# Position in list = priority. First entry gets the largest boost.

ARCHETYPE_VOCAB_AFFINITY: Dict[str, List[str]] = {
    "consultant": [
        "sovereign-authority", "established-authority", "scholar-educator",
        "universal-premium", "legacy-builder",
    ],
    "coach": [
        "warm-community", "wellness-healing", "rising-entrepreneur",
        "expressive-vibrancy", "scholar-educator",
    ],
    "financial_educator": [
        "scholar-educator", "established-authority", "sovereign-authority",
        "legacy-builder", "faith-ministry",
    ],
    "creative": [
        "creative-artist", "editorial", "expressive-vibrancy", "maximalist",
    ],
    "fitness_wellness": [
        "wellness-healing", "warm-community", "rising-entrepreneur", "organic-natural",
    ],
    "course_creator": [
        "scholar-educator", "rising-entrepreneur", "minimalist", "established-authority",
    ],
    "service_provider": [
        "warm-community", "rising-entrepreneur", "minimalist", "universal-premium",
    ],
    "agency": [
        "creative-artist", "editorial", "established-authority", "minimalist",
    ],
    # custom: no archetype hint — detection relies on text fields + brand voice
    "custom": [],
}


# ─── BRAND VOICE → VOCABULARY AFFINITIES ──────────────────────────────

BRAND_VOICE_VOCAB_AFFINITY: Dict[str, List[str]] = {
    "warm": ["warm-community", "wellness-healing", "expressive-vibrancy", "organic-natural"],
    "formal": ["sovereign-authority", "established-authority", "universal-premium", "scholar-educator"],
    "casual": ["rising-entrepreneur", "creative-artist", "warm-community", "expressive-vibrancy"],
    "ministry": ["faith-ministry", "warm-community", "wellness-healing", "legacy-builder"],
    "corporate": ["sovereign-authority", "established-authority", "universal-premium", "legacy-builder"],
    "direct": ["activist-advocate", "futurist-tech", "minimalist", "street-culture"],
}


# ─── SCORING ──────────────────────────────────────────────────────────


def _score_vocabulary(
    vocab: CulturalVocabulary,
    text_corpus: str,
    archetype: Optional[str],
    brand_voice: Optional[str],
) -> Tuple[float, List[str]]:
    """Score a single vocabulary against business text + archetype + brand voice."""
    score = 0.0
    reasons: List[str] = []

    # 1. Archetype affinity boost
    if archetype and archetype in ARCHETYPE_VOCAB_AFFINITY:
        affinity = ARCHETYPE_VOCAB_AFFINITY[archetype]
        if vocab["id"] in affinity:
            position = affinity.index(vocab["id"])
            boost = 1.0 - (position * 0.1)
            score += boost
            reasons.append(f"archetype '{archetype}' affinity +{boost:.2f}")

    # 2. Brand voice affinity boost
    if brand_voice and brand_voice in BRAND_VOICE_VOCAB_AFFINITY:
        affinity = BRAND_VOICE_VOCAB_AFFINITY[brand_voice]
        if vocab["id"] in affinity:
            position = affinity.index(vocab["id"])
            boost = 0.8 - (position * 0.08)
            score += boost
            reasons.append(f"brand_voice '{brand_voice}' affinity +{boost:.2f}")

    # 3. Signal word matching
    text_lower = text_corpus.lower()
    matched_signals: List[str] = []
    for signal in vocab.get("signal_words", []):
        if signal.lower() in text_lower:
            matched_signals.append(signal)
    if matched_signals:
        boost = min(len(matched_signals) * 0.15, 0.6)
        score += boost
        reasons.append(
            f"signal words [{', '.join(matched_signals[:3])}] +{boost:.2f}"
        )

    # 4. Detection signal matching
    matched_detections: List[str] = []
    for detection in vocab.get("detection_signals", []):
        if detection.lower() in text_lower:
            matched_detections.append(detection)
    if matched_detections:
        boost = min(len(matched_detections) * 0.12, 0.5)
        score += boost
        reasons.append(
            f"detection signals [{', '.join(matched_detections[:3])}] +{boost:.2f}"
        )

    return score, reasons


def detect_vocabularies(
    business_row: Dict[str, Any],
    business_profile: Optional[Dict[str, Any]] = None,
    voice_profile: Optional[Dict[str, Any]] = None,
    brand_kit: Optional[Dict[str, Any]] = None,
    practitioner_intelligence: Optional[Dict[str, Any]] = None,
) -> List[VocabularyMatch]:
    """Detect top 3 vocabulary candidates with confidence + reasons.

    Args:
        business_row: businesses table row (must include name; may include type)
        business_profile: business_profiles row (business_type, brand_voice,
            industry, audience, sensitive_areas, elevator_pitch)
        voice_profile: businesses.voice_profile JSONB (tone, personality,
            communication_style)
        brand_kit: businesses.settings.brand_kit (kept available for future
            signal extraction; currently unused by scoring)
        practitioner_intelligence: bundle.practitioner_intelligence dict
            (Pass 3.8a). Adds signal_words + about_me / about_business /
            strategy_track text to the corpus when present.
    """
    business_row = business_row or {}
    business_profile = business_profile or {}
    voice_profile = voice_profile or {}
    practitioner_intelligence = practitioner_intelligence or {}

    # Build text corpus from all available fields
    sensitive_areas = business_profile.get("sensitive_areas") or []
    if isinstance(sensitive_areas, dict):
        # JSONB sensitive_areas comes back as { 'flag': true } — flatten flags
        sensitive_areas = [k for k, v in sensitive_areas.items() if v]
    elif not isinstance(sensitive_areas, list):
        sensitive_areas = []

    # Pass 3.8a — pull text from practitioner_intelligence if present
    intel_about_me = practitioner_intelligence.get("about_me") or ""
    intel_about_biz = practitioner_intelligence.get("about_business") or ""
    intel_signal_words = practitioner_intelligence.get("signal_words") or []
    intel_strategy = practitioner_intelligence.get("strategy_track") or {}
    if isinstance(intel_strategy, dict):
        intel_strategy_text = " ".join(
            str(v) for v in intel_strategy.values()
            if v and isinstance(v, str)
        )
    else:
        intel_strategy_text = ""

    text_parts = [
        str(business_row.get("name") or ""),
        str(business_row.get("type") or ""),
        str(business_profile.get("industry") or ""),
        str(business_profile.get("audience") or ""),
        str(business_profile.get("elevator_pitch") or ""),
        " ".join(str(s) for s in sensitive_areas),
        str(voice_profile.get("tone") or ""),
        str(voice_profile.get("personality") or ""),
        str(voice_profile.get("communication_style") or ""),
        str(voice_profile.get("audience") or ""),
        # Pass 3.8a additions
        intel_about_me,
        intel_about_biz,
        intel_strategy_text,
        " ".join(intel_signal_words) if isinstance(intel_signal_words, list) else "",
    ]
    text_corpus = " ".join(p for p in text_parts if p)

    archetype = business_profile.get("business_type") or business_row.get("type")
    brand_voice = business_profile.get("brand_voice") or voice_profile.get("tone")

    matches: List[VocabularyMatch] = []
    for vocab in VOCABULARIES.values():
        score, reasons = _score_vocabulary(vocab, text_corpus, archetype, brand_voice)
        if score > 0.3:
            matches.append(VocabularyMatch(
                vocabulary=vocab,
                confidence=min(score / 3.0, 1.0),
                reasons=reasons,
            ))

    matches.sort(key=lambda m: m["confidence"], reverse=True)
    return matches[:3]


def detect_vocabulary_triple(
    business_row: Dict[str, Any],
    business_profile: Optional[Dict[str, Any]] = None,
    voice_profile: Optional[Dict[str, Any]] = None,
    brand_kit: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Return (primary_id, secondary_id, aesthetic_id) ready to feed
    studio_composite.build_composite.

    - primary: top match overall
    - secondary: next best match in a DIFFERENT section than primary
    - aesthetic: best match in section 'aesthetic-movement' that isn't
      already primary or secondary
    Falls back to ('universal-premium', None, 'minimalist') when there
    are no signals at all.
    """
    matches = detect_vocabularies(business_row, business_profile, voice_profile, brand_kit)
    if not matches:
        return ("universal-premium", None, "minimalist")

    primary = matches[0]["vocabulary"]
    primary_id = primary["id"]
    primary_section = primary["section"]

    secondary_id: Optional[str] = None
    for m in matches[1:]:
        if m["vocabulary"]["section"] != primary_section:
            secondary_id = m["vocabulary"]["id"]
            break

    aesthetic_id: Optional[str] = None
    for m in matches:
        v = m["vocabulary"]
        if v["section"] == "aesthetic-movement" and v["id"] not in (primary_id, secondary_id):
            aesthetic_id = v["id"]
            break

    return (primary_id, secondary_id, aesthetic_id)


# ─── Pass 3.8a — meaningful-signal gate for Designer Agent ─────────
#
# Distinct from Pass 3.7c's decoration-generator gate (which is 6-signal).
# This is the 9-signal version used by the Designer Agent endpoint to
# decide between rich-data (LLM call) and cold-start (deterministic
# vocabulary affinity) paths.
#
# Per Pass 3.8a Clarification 2: signals 7-9 require non-auto-seeded
# data. A practitioner_profile that only has audit fields populated
# does NOT count as about_me signal.


def voice_signal_breakdown(
    bundle: Dict[str, Any],
    products: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, bool]:
    """Return the 9-signal breakdown dict.

    Signals 1-6 are simple presence checks. Signals 7-9 (about_me,
    about_business, strategy_track) apply Clarification 2 filters so
    auto-seeded-only profiles do NOT count.
    """
    products = products or []
    bundle = bundle or {}
    business = bundle.get("business") or {}
    voice = bundle.get("voice") or {}
    intel = bundle.get("practitioner_intelligence") or {}
    raw = intel.get("_raw") or {}
    practitioner_row = raw.get("practitioner_profile") or {}
    strategy_row = raw.get("strategy_track") or {}

    # Signal 7: about_me — must have name OR title AND voice_samples OR voice_dos
    has_identity = bool(
        practitioner_row.get("full_legal_name")
        or practitioner_row.get("preferred_title")
    )
    voice_samples = practitioner_row.get("voice_samples") or {}
    voice_dos_pp = practitioner_row.get("voice_dos") or []
    has_voice_depth = bool(
        (isinstance(voice_samples, dict) and len(voice_samples) > 0)
        or (isinstance(voice_dos_pp, list) and len(voice_dos_pp) > 0)
    )
    about_me_truthy = bool(intel.get("about_me")) and has_identity and has_voice_depth

    # Signal 8: about_business — must have tagline OR elevator_pitch AND
    # at least one of (business_type, brand_voice, audience, tone) populated.
    settings = business.get("settings") if isinstance(business, dict) else {}
    brand_kit = (settings or {}).get("brand_kit") if isinstance(settings, dict) else {}
    brand_kit = brand_kit or {}
    business_profile_raw = bundle.get("_business_profile") or {}
    has_brand_kit_text = bool(
        (brand_kit.get("tagline") or business.get("tagline"))
        or (brand_kit.get("elevator_pitch") or business.get("elevator_pitch"))
    )
    has_business_meta = bool(
        business.get("type")
        or business_profile_raw.get("business_type")
        or business_profile_raw.get("brand_voice")
        or voice.get("brand_voice")
        or voice.get("audience")
        or voice.get("tone_original")
        or voice.get("tone")
    )
    about_business_truthy = (
        bool(intel.get("about_business")) and has_brand_kit_text and has_business_meta
    )

    # Signal 9: strategy_track — phases.discovery has >=2 non-empty values
    strategy_dict = intel.get("strategy_track") or {}
    discovery_keys = ("unique_value_proposition", "target_audience", "summary", "practitioner_background")
    discovery_filled = sum(1 for k in discovery_keys if strategy_dict.get(k))
    strategy_truthy = discovery_filled >= 2

    return {
        # 1-6 simple presence
        "tagline": bool(business.get("tagline")),
        "elevator_pitch": bool(business.get("elevator_pitch")),
        "voice_tone": bool(voice.get("tone") or voice.get("tone_original")),
        "voice_dos": bool(voice.get("voice_dos")),
        "voice_donts": bool(voice.get("voice_donts")),
        "products_with_names": bool([p for p in products if isinstance(p, dict) and p.get("name")]),
        # 7-9 filtered per Pass 3.8a Clarification 2
        "about_me": about_me_truthy,
        "about_business": about_business_truthy,
        "strategy_track": strategy_truthy,
    }


def has_meaningful_voice_signal(
    bundle: Dict[str, Any],
    products: Optional[List[Dict[str, Any]]] = None,
    threshold: int = 2,
) -> bool:
    """Pass 3.8a 9-signal threshold gate. Default threshold 2-of-9.

    Below threshold = cold-start path. At/above = rich-data (LLM) path.
    """
    breakdown = voice_signal_breakdown(bundle, products)
    truthy = sum(1 for v in breakdown.values() if v)
    return truthy >= threshold


# Backward-compat alias for callers that prefer the underscore-prefix name
_has_meaningful_voice_signal = has_meaningful_voice_signal
