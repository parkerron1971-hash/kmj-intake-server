# agents/composer/drl/signals.py
# ═══════════════════════════════════════════════════════════════════════
# Design Rationale Layer — Signal Taxonomy (spec §1).
#
# The structured catalog of design-relevant signals Chief detects during
# conversational intake. These constants are the single source of truth
# for the signal-detection pass (PR2) and for validating DRO.signals[].
# Each signal: id, definition, allowed values, and the directional design
# implication. Evidence quotes (verbatim) ARE the audit trail.
#
# Detection contract: each detected signal →
#   {signal_id, value, confidence (0-1), evidence:[quotes], source}
# Signals below CONSUME_THRESHOLD are recorded but NOT consumed by
# translation (shown as "heard but not acted on" in the audit view).
# ═══════════════════════════════════════════════════════════════════════

from typing import Any, Dict, List

# Below this confidence a signal is logged but not fed to DRO authoring.
CONSUME_THRESHOLD: float = 0.5

SIGNAL_SOURCES = ("intake", "inferred", "practitioner_set")

# Ordered taxonomy. `values` lists the allowed normalized values (a spectrum
# signal documents its endpoints + modifier flags in `notes`).
SIGNALS: Dict[str, Dict[str, Any]] = {
    "opening_posture": {
        "name": "Opening Posture",
        "definition": "How the practitioner instinctively opens the conversation about their work — what they lead with reveals what the site should lead with.",
        "values": ["problem_first", "credential_first", "story_first", "vision_first", "craft_first"],
        "design_implication": "Drives hero hierarchy (what the first headline is about) and whether proof elements sit above or below the fold.",
    },
    "communication_temperature": {
        "name": "Communication Temperature",
        "definition": "Where the practitioner sits on direct <-> relational. Not friendliness — information-delivery style.",
        "values": "spectrum:0.0_direct..1.0_relational",
        "modifier_flags": ["analogical", "data_led"],
        "design_implication": "Direct -> tighter copy, higher contrast, fewer decorative moves. Relational -> warmer temperature, generous line-height, transitions. analogical -> visual-metaphor hero over photography.",
    },
    "audience_sophistication": {
        "name": "Audience Sophistication",
        "definition": "How fluent the AUDIENCE is in the practitioner's domain — the site speaks to them, not to peers.",
        "values": ["novice", "practicing", "expert", "mixed"],
        "design_implication": "Novice -> progressive disclosure, explanatory micro-copy. Expert -> density is RESPECT, restrained ornament, proof over promise.",
    },
    "audience_emotional_state": {
        "name": "Audience Emotional State",
        "definition": "The dominant feeling the visitor arrives with. The first screen either meets it or fights it.",
        "values": ["overwhelmed", "ambitious", "skeptical", "vulnerable", "curious", "urgent", "proud"],
        "multi_select_max": 2,
        "design_implication": "Overwhelmed -> radical reduction. Skeptical -> proof-forward, no hype motion. Ambitious -> momentum cues. Vulnerable -> soft contrast, warm temperature, zero aggression.",
    },
    "authority_style": {
        "name": "Authority Style",
        "definition": "The relationship geometry: above (expert prescribes), alongside (guide co-pilots), behind (enabler makes the client the hero).",
        "values": ["expert_above", "guide_alongside", "enabler_behind"],
        "design_implication": "Above -> symmetric/centered/formal contrast. Alongside -> asymmetric (two presences), conversational subheads, accompaniment metaphors. Behind -> audience imagery dominant, practitioner subordinate.",
    },
    "first_five_seconds": {
        "name": "Desired First-Five-Seconds Feeling",
        "definition": "What the practitioner wants a stranger to FEEL before reading anything. Captured close to verbatim.",
        "values": ["legit_intentional", "calm_safe", "serious_gravitas", "energizing", "warm_welcomed", "exclusive_premium", "playful"],
        "free_text": True,
        "design_implication": "The ACCEPTANCE TEST for the whole rationale — every choice must be defensible as serving this feeling. First field shown in the practitioner 'why' view.",
    },
    "vertical_conventions": {
        "name": "Vertical Conventions — Honor vs. Break",
        "definition": "The visual conventions of the industry, and the practitioner's stance toward them. Conventions carry trust; breaking them is a move, not a default.",
        "values": ["honor", "break_deliberately", "no_stance"],
        "note": "Named conventions in play are sourced from vertical_intelligence (fork F2: DRL consumes it as a prior, does not duplicate).",
        "design_implication": "Honor -> keep structural trust cues, differentiate via craft. Break -> invert ONE convention loudly, keep the rest.",
    },
    "brand_maturity": {
        "name": "Brand Maturity",
        "definition": "How much identity already exists and how attached the practitioner is to it.",
        "values": ["established_attached", "established_flexible", "existing_disposable", "blank_slate"],
        "design_implication": "Attached -> rationale works WITHIN given assets (palette derives from them; say so). Blank slate -> full freedom, anti-convergence weighs heavier.",
    },
    "offering_texture": {
        "name": "Offering Texture",
        "definition": "The sensory/temporal character of what's sold: one big transformation vs. ongoing rhythm vs. discrete deliverables vs. moment of need.",
        "values": ["transformation_arc", "steady_rhythm", "discrete_artifacts", "moment_of_need"],
        "multi_select_max": 2,
        "design_implication": "Transformation -> before/after narrative, progress metaphors. Rhythm -> stability cues. Artifacts -> show the work (gallery). Moment-of-need -> zero friction to contact.",
    },
    "energy_signature": {
        "name": "Practitioner Energy Signature",
        "definition": "Pace/intensity of the practitioner's own speech (sentence length, exclamation/hedging density). The site should feel like meeting them.",
        "values": ["high_conviction", "deliberate", "warm_steady", "playful_quick"],
        "design_implication": "Motion temperature and type personality should rhyme with it — a deliberate speaker with bouncing animations is a lie the visitor feels.",
    },
}

# The 8 axes that form a DRO's distinctiveness signature (spec §5.2).
DISTINCTIVENESS_AXES: List[str] = [
    "palette.base",
    "palette.accent_strategy",
    "palette.temperature",
    "typography.display_personality",
    "layout.symmetry",
    "layout.density",
    "motion.temperature",
    "hero_concept.direction",
]

# Sharing >= this many axes with a recent DRO triggers one regeneration.
DISTINCTIVENESS_COLLISION_THRESHOLD: int = 6
# Cohort window for the distinctiveness check (fork F4: platform-wide last-10).
DISTINCTIVENESS_COHORT_N: int = 10


def signals_from_prefs(prefs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """THE INTERVIEW BRIDGE (2026-07-22). detect_signals reads Chief's
    conversational transcript — but the richest design testimony is the
    style interview, which never reached the taxonomy. Result: every
    interview-driven build ran the brain starved (applied_thin) no
    matter how much the owner said. These are deterministic, source=
    practitioner_set, evidence = the owner's own words — the strongest
    class of signal, not an inference."""
    out: List[Dict[str, Any]] = []
    if not isinstance(prefs, dict):
        return out

    def add(sid: str, value: Any, quote: str) -> None:
        if quote:
            out.append({"signal_id": sid, "value": value, "confidence": 0.85,
                        "evidence": [str(quote)[:200]],
                        "source": "practitioner_set"})

    b = str(prefs.get("boldness") or "")
    if b:
        add("energy_signature",
            {"quiet": "deliberate", "bold": "high_conviction",
             "loud": "high_conviction"}.get(b, "warm_steady"),
            f"boldness: {b}")
    creative = prefs.get("creative") if isinstance(prefs.get("creative"), dict) else {}
    if str(creative.get("metaphor") or "").strip():
        add("communication_temperature", 0.6,
            f"their metaphor: {creative.get('metaphor')}")
        out[-1]["modifier_flags"] = ["analogical"]
    if str(prefs.get("avoid") or "").strip():
        add("vertical_conventions", "break_deliberately",
            f"never like: {prefs.get('avoid')}")
    feel = prefs.get("feel_words") or []
    direction = str(((prefs.get("colors") or {}) if isinstance(prefs.get("colors"), dict) else {}).get("direction") or "")
    if feel or direction:
        add("first_five_seconds",
            " ".join([*(str(w) for w in feel[:4]), direction]).strip(),
            f"they want visitors to feel: {' '.join(str(w) for w in feel[:4])} {direction}")
    if prefs.get("wants_gallery") is True:
        add("offering_texture", "discrete_artifacts",
            "they asked for a gallery of real work")
    if str(prefs.get("audience") or "").strip():
        add("audience_emotional_state", "curious",
            f"who it's for, in their words: {prefs.get('audience')}")
    return out


def signal_ids() -> List[str]:
    """The canonical signal_id enum (matches schema.json)."""
    return list(SIGNALS.keys())


def is_consumable(confidence: float) -> bool:
    """Whether a detected signal is strong enough to drive translation."""
    return confidence >= CONSUME_THRESHOLD
