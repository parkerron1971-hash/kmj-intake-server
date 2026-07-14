"""
vertical_context.py — Phase VABI v1, the engine.

Returns a standardized vertical context block to inject into Chief
LLM system prompts. Pattern matches the existing NT8f module-spec
generator approach but extends to all Chief surfaces (reply
composition, suggestion generation, draft text, etc.).

Discipline:
  - Block is short (token-budget aware) — under 600 chars for the
    median vertical, never exceeds 1500 chars.
  - When the vertical is unmapped, returns a brief generic block
    (does NOT inject empty / no-op text — caller may rely on
    presence-of-block-shape for downstream parsing).
  - Pure read; no side effects.

Usage:
    from vertical_context import build_vertical_context_block
    block = build_vertical_context_block(business)
    system_prompt = f"{system_prompt}\n\n{block}"
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from vertical_intelligence import (
    get_profile,
    get_voice,
    get_offering_suggestions,
    get_invoice_line_templates,
    list_known_verticals,
)
from vertical_terminology import VERTICAL_TERMS, BASE_TERMS


def build_vertical_context_block(business: Optional[Dict[str, Any]]) -> str:
    """Compose the vertical context block for Chief system prompts.

    `business` is a Supabase businesses row. Reads .type for the
    vertical key. Returns a plain-text block ready for concatenation.
    Always returns a non-empty string — callers can append unconditionally.
    """
    business_type = (business or {}).get("type")
    bt = (business_type or "").lower().strip()
    is_known = bt in VERTICAL_INTELLIGENCE_KEYS
    profile = get_profile(bt)
    voice = get_voice(bt)

    # Terminology snapshot — the practitioner's vocabulary.
    term_overrides = VERTICAL_TERMS.get(bt) or {}
    vocab_pairs = []
    for k in ("customer", "service", "appointment", "booking", "invoice", "offering"):
        v = term_overrides.get(k) or BASE_TERMS.get(k)
        if v:
            vocab_pairs.append(f"{k}={v}")
    vocab = ", ".join(vocab_pairs)

    hallmarks = (voice or {}).get("hallmarks") or []
    taboo = (voice or {}).get("taboo") or []
    register = (voice or {}).get("register") or "professional but warm"
    formality = (voice or {}).get("formality") or "balanced"

    label = "VERTICAL CONTEXT" if is_known else "VERTICAL CONTEXT (generic — vertical not explicitly mapped)"
    lines = [
        f"=== {label} ===",
        f"Business type: {business_type or '(unset)'}",
        f"Voice register: {register}",
        f"Formality: {formality}",
    ]
    if vocab:
        lines.append(f"Vocabulary: {vocab}")
    if hallmarks:
        lines.append("Hallmarks: " + " · ".join(hallmarks[:6]))
    if taboo:
        lines.append("Avoid: " + " · ".join(taboo[:4]))

    # One concrete reminder per known vertical — Chief gets the most
    # actionable signal first.
    reminders = _vertical_specific_reminders(bt, profile)
    if reminders:
        lines.append("Reminders: " + " · ".join(reminders))

    # Offering + invoice shapes typical for this vertical. These are
    # STARTING POINTS for when the practitioner asks Chief to create an
    # offering or draft an invoice — so Chief's create/adjust output fits
    # the vertical instead of inventing generic line items. The business's
    # OWN products/services catalog (elsewhere in the prompt) is always
    # authoritative; adapt these, never blind-copy.
    offerings = get_offering_suggestions(bt) or []
    if offerings:
        parts = []
        for o in offerings[:6]:
            price = o.get("price")
            plabel = f"${price:,}" if isinstance(price, (int, float)) and price else "free"
            parts.append(f"{o.get('name')} ({plabel})")
        lines.append(
            "Typical offerings for this vertical (starting points when creating one — "
            "adapt to the business; its own catalog is authoritative): "
            + " · ".join(parts))
    invoice_lines = get_invoice_line_templates(bt) or []
    if invoice_lines:
        parts = [t.get("description") for t in invoice_lines[:6] if t.get("description")]
        if parts:
            lines.append("Typical invoice lines for this vertical: " + " · ".join(parts))

    lines.append("Apply this voice in every practitioner-facing reply.")
    return "\n".join(lines)


# Local cache of the keys (avoids importing the whole dict twice).
VERTICAL_INTELLIGENCE_KEYS = set(list_known_verticals())


def _vertical_specific_reminders(bt: str, profile: Dict[str, Any]) -> list:
    """Top 1-2 concrete reminders per vertical so Chief's first
    response carries the right shape."""
    if bt == "lawyer":
        return [
            "Conflict checks before engagement",
            "Trust funds (IOLTA) stay separate from operating account",
        ]
    if bt == "ministry":
        return [
            "Giving is access-isolated, not transactional",
            "Children's ministry needs consent + RSVP",
        ]
    if bt == "fitness_wellness":
        return [
            "No clinical claims without licensure",
            "Body autonomy + recovery language",
        ]
    if bt == "financial_educator":
        return [
            "Education, not personalized financial advice",
        ]
    if bt == "coach":
        return [
            "Outcome-focused, not result-promising",
            "Confidentiality is central",
        ]
    if bt == "consultant":
        return [
            "Scope + deliverables + milestones",
        ]
    if bt == "creative":
        return [
            "Scope clarifies revisions + timeline",
        ]
    if bt == "course_creator":
        return [
            "Curriculum is the product",
        ]
    if bt == "personal_services":
        return [
            "Plain talk about price + time",
        ]
    return []
