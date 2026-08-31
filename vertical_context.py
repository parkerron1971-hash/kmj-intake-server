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
    is_mapped,
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
    # Resolve ALIASES once, here, and use the canonical key for every
    # lookup below. `businesses.type` legitimately holds alias strings —
    # 'agency', 'church', 'plumber' — because several surfaces still write
    # them; keyed raw, all three read the generic block while the
    # practitioner's own screens read the vertical dictionary.
    import vertical_registry
    bt = vertical_registry.resolve(business_type)
    # "Mapped" is a different question from "which profile" now that
    # resolve() answers 'custom' for anything unrecognised: an unknown type
    # still GETS the custom profile, and labelling that block as though it
    # were a deliberate match would be a lie the prompt tells Chief.
    is_known = is_mapped(business_type)
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

    # Out-of-scope block, when the vertical has one. Appended LAST so it is
    # the final instruction Chief reads about this business, and so it cannot
    # be softened by anything above it.
    #
    # This is belt-and-braces, not the enforcement: vertical_scope guards the
    # module-create paths themselves. What this prevents is Chief cheerfully
    # OFFERING to build something it will then be refused, which reads as a
    # broken product rather than a deliberate boundary.
    try:
        import vertical_scope
        scope_block = vertical_scope.prompt_block(business_type)
        if scope_block:
            lines.append("")
            lines.append(scope_block)
    except Exception:
        pass

    return "\n".join(lines)


# Feed 2's block is capped separately from the block above, which promises
# <600 chars median / 1500 ceiling. Learned knowledge is additive, so it
# gets its own budget rather than eating that one.
LEARNED_BLOCK_MAX_CHARS = 700
LEARNED_MAX_ITEMS = 5


def build_vertical_learned_block(business: Optional[Dict[str, Any]],
                                 query_text: str) -> str:
    """Retrieved vertical depth, for the situation at hand.

    Two sources, deliberately kept apart in the output:

      curated  (vertical_playbook)  how this TRADE works — mechanisms,
               seasons, objections. Written by us and reviewed in a diff.
      learned  (vertical_distill)   what businesses in this vertical have
               actually taught the system, behind a k-anonymity floor.

    They are labelled separately because they are different claims. "Several
    businesses like yours do this" is evidence about a population; "this is
    how the trade works" is domain knowledge. Merged under one heading Chief
    would weigh them alike, and the weaker one would borrow the other's
    authority — which matters most right now, when the curated shelf is full
    and the learned one is empty.

    Seed rows are still excluded: they are a projection of the profiles
    already in the static block above, so surfacing them would make the
    prompt say everything twice.

    Separate from `build_vertical_context_block` on purpose, and not merged
    into it, for three reasons: this one does I/O and can be slow, it is
    situation-dependent where the other is constant per business, and it
    must be droppable without touching the block that has worked for a
    year.

    Returns "" — not a placeholder — when there is nothing, so callers can
    concatenate unconditionally and get exactly today's prompt back if
    retrieval is empty, disabled, or broken. Never raises."""
    try:
        bt = ((business or {}).get("type") or "").lower().strip()
        if not bt or not (query_text or "").strip():
            return ""
        # vk.match canonicalises the key itself, so an alias-typed business
        # ('church', 'agency') reaches its vertical's partition instead of
        # querying one that by construction holds nothing.
        import vertical_knowledge as vk
        rows = vk.match(bt, query_text, limit=LEARNED_MAX_ITEMS)
        if not rows:
            return ""

        curated, learned, used = [], [], 0
        for r in rows:
            content = (r.get("content") or "").strip()
            source = r.get("source")
            if not content or source not in ("curated", "learned"):
                continue
            # One budget across both, so adding the curated shelf cannot
            # quietly double what this block costs every turn.
            if used + len(content) > LEARNED_BLOCK_MAX_CHARS:
                break
            (curated if source == "curated" else learned).append(f"- {content}")
            used += len(content)
        if not curated and not learned:
            return ""

        parts = []
        if curated:
            parts.append("=== HOW THIS TRADE WORKS ===\n"
                         "Operating knowledge about this kind of business, "
                         "selected for what was just asked. Apply it as "
                         "judgement, not as facts about THIS business — its "
                         "own numbers and history always win.\n"
                         + "\n".join(curated))
        if learned:
            # The framing matters. These are observed tendencies across a
            # category, not instructions and not facts about THIS business —
            # Chief should weigh them, and the business's own data always wins.
            parts.append("=== WHAT WORKS FOR BUSINESSES LIKE THIS ===\n"
                         "Patterns observed across other businesses of this type. "
                         "Useful priors, not rules — this business's own history and "
                         "stated preferences always win.\n" + "\n".join(learned))
        return "\n\n".join(parts)
    except Exception:
        # Vertical context has worked without this block for a year. It keeps
        # working the moment anything here breaks.
        return ""


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
    if bt == "ecommerce":
        return [
            "Sales tax collected is held for the state, not revenue",
            "Stock and shipping windows are promises — give a window, never a date",
        ]
    if bt == "saas":
        return [
            "An annual plan is cash now, revenue across twelve months",
            "Usage leads, billing lags — a signup without usage is not a customer",
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
    if bt == "therapist":
        return [
            "Clinical records are OUT OF SCOPE — scheduling, billing, admin only",
            "Never summarise or store session content",
            "Confirmations may be read by someone other than the client",
        ]
    if bt == "contractor":
        return [
            "Quote before the work starts, never after",
            "Scope changes are a change order, priced first",
            "No advice that needs a license or permit the practitioner may not hold",
        ]
    return []
