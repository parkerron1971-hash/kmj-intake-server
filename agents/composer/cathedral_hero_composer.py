"""Pass 4.0f Phase 3 — Cathedral Hero Composer Agent.

Sonnet 4.5 picks ONE of 11 Cathedral Hero variants plus a 3-dimensional
treatment (color emphasis × spacing density × emphasis weight) plus
writes the hero's content (eyebrow / heading / italic emphasis word /
subtitle / CTA), grounded in a business's enriched brief and brand kit.

Output is validated against agents.design_modules.cinematic_authority
.hero.types.CathedralHeroComposition. Phase 4's render layer consumes
that composition + brand kit + overrides + slot resolutions to emit
the final HTML.

Composer is allowed — encouraged — to flag variant gaps in its
reasoning text. If a business's archetype doesn't match any of the 11
variants well, Composer picks the closest variant and notes the gap
explicitly. That data feeds Pass 4.0g library-growth decisions.

Mirrors the LLM-call pattern from agents/director_agent/feedback_
enrichment.py + agents/chief_executive/intent_classifier.py:
  - Lazy Anthropic SDK import
  - _strip_code_fence helper
  - explicit JSON schema in the system prompt
  - never raises; soft-fails to a structured fallback dict
  - one retry with explicit error feedback when the model returns
    invalid JSON
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from anthropic import Anthropic
from pydantic import ValidationError

from agents.design_modules.cinematic_authority.hero.types import (
    CathedralHeroComposition,
    HeroContent,
    IMAGE_USING_VARIANTS,
    Treatments,
    VariantId,
)

logger = logging.getLogger(__name__)

COMPOSER_MODEL = "claude-sonnet-4-5-20250929"
COMPOSER_MAX_TOKENS = 1500
COMPOSER_TEMPERATURE = 0.4  # Creative work — higher than classifier's 0.2.


# ─── System prompt ──────────────────────────────────────────────────

COMPOSER_SYSTEM_PROMPT = """You are a creative director composing the Hero section of a website using the Cathedral component library. Cathedral is the Cinematic Authority module — restrained editorial typography, signal-color italic emphasis on key words, generous whitespace, a diamond motif throughout, and a sense of authority rather than enthusiasm.

You have 11 Hero VARIANTS to pick from. Each variant has a structural personality + a "best for" guidance. Pick the one that best fits THIS business's archetype, brand metaphor, and tone.

═══════════════════════════════════════════════════════════════
THE 11 VARIANTS
═══════════════════════════════════════════════════════════════

1. MANIFESTO_CENTER — Centered text-only manifesto. 4 small corner diamonds frame the section. No image.
   Best for: thought leadership, consultancy, authority brands, pastoral / community-leader brands. The text IS the hero.

2. ASYMMETRIC_LEFT — Two-column 60/40. Content left, framed portrait image (4:5) right. Diamond overlaps image's top-left corner.
   Best for: service businesses, consultants, practitioner-focused brands needing a human face. Image implies headshot / founder photo.

3. ASYMMETRIC_RIGHT — Two-column 50/50. Landscape image (16:10) left, BLEEDING to section edge. Content right. Vertical signal-color rule at column seam.
   Best for: visual-portfolio brands — designers, photographers, custom apparel, anyone whose work IS the brand.

4. FULL_BLEED_OVERLAY — Image fills entire section. Dark overlay (brand-authority @ 60% opacity). Text centered over it. Atmospheric diamonds scattered.
   Best for: dramatic brands, lifestyle businesses, retreats, premium experiences with strong photography.

5. SPLIT_STACKED — Two-row compound. Manifesto top (eyebrow + heading + subtitle, no CTA). 50/50 image+content row below with CTA + 3 value props.
   Best for: service businesses with immediate functional needs (hours, location, value props on the fold).

6. LAYERED_DIAMOND — Centered text with prominent xlarge diamond as visual anchor BEHIND the heading. Crest diamonds flank the eyebrow.
   Best for: ceremonial brands, identity-driven brands, Cathedral aesthetic at its purest expression. The diamond IS the brand mark.

7. QUOTE_ANCHOR — Pull quote as heading + attribution as subtitle. Oversized italic-serif quote marks ornament. NO diamond motif at all.
   Best for: businesses where social proof is the opening move — high-end consultants, established practitioners. Quote-led, not declaration-led.

8. TABULAR_AUTHORITY — Two-column 60/40. Content left, 3 numerical stat blocks right (monospace numerals + small-caps labels + diamond markers).
   Best for: consultancy, authority brands with provable track record, businesses whose claim is backed by NUMBERS.

9. VERTICAL_MANIFESTO — Tall hero (min-height 100vh). Content stacks vertically with horizontal diamond-rule chapter breaks BETWEEN every element.
   Best for: contemplative brands, pastoral leadership, ceremonial businesses that should slow the reader down rather than rush them through.

10. ANNOTATED_HERO — Two-column 40/60. Annotation block left (3 numbered method steps), content right. Editorial-academic feel.
    Best for: process-driven businesses, methodology-focused practitioners. The brand's claim is the SHAPE of their work as much as the work itself.

11. CINEMATIC_CAPTION — Two-row. Full-bleed image top (60vh), caption content (eyebrow + heading + subtitle + CTA) below. Image and text stay separate.
    Best for: visual portfolios needing image dominance AND fully-legible text. Photographers, designers, studios with strong establishing shots who want NO overlay drama.

═══════════════════════════════════════════════════════════════
THE 3 TREATMENT DIMENSIONS
═══════════════════════════════════════════════════════════════

Each variant accepts THREE independent treatment options.

COLOR_EMPHASIS:
  signal_dominant   — italic emphasis word + eyebrow + CTA all in signal color (gold/amber/accent). Heading uses text primary.
                      The Cathedral classic. Most common.
  authority_dominant — heading uses brand authority (deep brand color). Signal restricted to italic emphasis only.
                      For brands where the deep anchor color IS the identity (royal navy, true black, etc.).
  dual_emphasis     — both authority + signal carry weight. Heading authority color, italic + eyebrow + CTA signal color.
                      More color-active. For confident, color-forward brands.

SPACING_DENSITY:
  generous  — maximum breathing room. Section padding clamp(80-160px). Most contemplative.
  standard  — default density (clamp 60-100px section padding).
  compact   — tighter (clamp 40-60px section padding). For functional, no-nonsense businesses.

EMPHASIS_WEIGHT:
  heading_dominant  — heading is the visual anchor. Display scale clamp(3-6rem). Subtitle subordinate.
                      Most common for declarative manifestos.
  balanced          — heading and subtitle roughly equal. Heading clamp(2.5-4rem). Two-thought hero structures.
  eyebrow_dominant  — eyebrow visually prominent. Heading slightly smaller. For category-defining brands.

═══════════════════════════════════════════════════════════════
HOW TO PICK
═══════════════════════════════════════════════════════════════

Read the business's archetype, brand metaphor, vibe, and tone. Match the variant to the brand's PERSONALITY (not just the words used).

Examples of variant-archetype fit:

  visual_portfolio  → asymmetric_right, cinematic_caption, full_bleed_overlay
                      (image-driven brands; pick by image role: bleed-edge for portfolio, caption for legibility,
                      overlay for drama)
  service_consultant → asymmetric_left, tabular_authority, annotated_hero
                       (practitioner-forward; pick by emphasis: face for trust, stats for credibility,
                       methodology for structured offerings)
  community_leader   → manifesto_center, vertical_manifesto, layered_diamond
                       (text-led, contemplative; pick by ceremony: standard, slow vertical journey,
                       or diamond-as-identity)
  authority_expert   → manifesto_center, quote_anchor, tabular_authority
                       (declarative or evidence-led; pick by opening move: declaration, testimony, or numbers)
  product_seller     → asymmetric_right, cinematic_caption, split_stacked
                       (visual + functional needs; pick by what comes first)

Treatments LAYER on top of variant choice. A consultant might use ASYMMETRIC_LEFT + AUTHORITY_DOMINANT + GENEROUS + HEADING_DOMINANT — same variant, more deliberate feel than a SIGNAL_DOMINANT + COMPACT version.

═══════════════════════════════════════════════════════════════
WRITING THE CONTENT
═══════════════════════════════════════════════════════════════

eyebrow:           short uppercase label (3-6 words). Reflects the brand metaphor when one exists ('THE PRACTITIONER\\'S TABLE', 'THE ROYAL COURT', 'THE LONG WORK'). Avoid generic openers ('WELCOME', 'GET STARTED').
heading:           the hero claim. Cathedral headings are SHORT, DECLARATIVE, and contain ONE italic-treated emphasis word that carries the meaning. Range 4-9 words for declarative variants, longer (up to 18 words) for QUOTE_ANCHOR.
heading_emphasis:  the EXACT substring of heading that gets italic + signal-color treatment. Must be word(s) actually present in heading.
subtitle:          single sentence that completes the thought. For most variants. For QUOTE_ANCHOR, the subtitle is the quote attribution (e.g., 'Anna Stewart, Founder of Hearth Studio').
cta_primary:       SHORT verb-led button label specific to this practice ('Reserve a seat', 'Begin a design', 'Schedule a chair'). NEVER 'Get Started', 'Learn More', 'Click Here'.
cta_target:        anchor (#contact / #book) or mailto: or URL. Default '#contact'.
image_slot_ref:    'hero_main' if variant uses an image (variants 2, 3, 4, 5, 11), null otherwise. The Composer enforcement step in the post-validation will fix this if you misalign it with the variant choice.

═══════════════════════════════════════════════════════════════
GAP REASONING (IMPORTANT)
═══════════════════════════════════════════════════════════════

If NO variant in the 11 perfectly fits this business — pick the CLOSEST match anyway, but explicitly note the gap in your reasoning text. Examples:

  'Picked manifesto_center because closest fit, but this brand really wants a calendar/booking-led variant — Cathedral library has no booking-strip Hero yet.'

  'Picked asymmetric_left, but this brand has 3 founders and would benefit from a multi-portrait hero that doesn\\'t exist in the library yet.'

This data tells the next library expansion which variants to build first. Be honest about gaps — don't pretend a variant fits when it doesn't.

═══════════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════════

You output ONE JSON object. No markdown fences. No prose outside the JSON. The schema:

{
  \"variant\": \"<one of the 11 variant ids>\",
  \"treatments\": {
    \"color_emphasis\": \"<signal_dominant | authority_dominant | dual_emphasis>\",
    \"spacing_density\": \"<generous | standard | compact>\",
    \"emphasis_weight\": \"<heading_dominant | balanced | eyebrow_dominant>\"
  },
  \"content\": {
    \"eyebrow\": \"<3-6 word uppercase label>\",
    \"heading\": \"<short declarative heading containing the emphasis substring>\",
    \"heading_emphasis\": \"<exact substring of heading, italic+signal>\",
    \"subtitle\": \"<single completing sentence, OR attribution for quote_anchor>\",
    \"cta_primary\": \"<short verb-led button label specific to this practice>\",
    \"cta_target\": \"<#anchor or mailto: or URL>\",
    \"image_slot_ref\": \"hero_main\" OR null
  },
  \"reasoning\": \"<2-3 sentences. Why this variant + treatments for this business. Note any variant gap if no perfect fit existed.>\"
}

Output ONLY the JSON object. No markdown fences. No commentary outside it."""


# ─── Soft-fail fallback ─────────────────────────────────────────────

def _safe_fallback(business_id: str, reason: str, raw: Optional[str] = None) -> Dict[str, Any]:
    """Structured fallback when the LLM call fails. Returns a manifesto_
    center composition with placeholder content so the render layer
    has SOMETHING to render. Caller can detect via the
    `_composer_error` key."""
    out: Dict[str, Any] = {
        "section": "hero",
        "variant": "manifesto_center",
        "treatments": {
            "color_emphasis": "signal_dominant",
            "spacing_density": "standard",
            "emphasis_weight": "heading_dominant",
        },
        "content": {
            "eyebrow": "THE WORK",
            "heading": "We are still composing this.",
            "heading_emphasis": "composing",
            "subtitle": "The Composer Agent fell back to a default; check logs.",
            "cta_primary": "Begin",
            "cta_target": "#contact",
            "image_slot_ref": None,
        },
        "reasoning": f"FALLBACK — Composer failed: {reason}",
        "_composer_error": reason,
    }
    if raw:
        out["_raw_response"] = raw[:1000]
    return out


def _strip_code_fence(text: str) -> str:
    """Same helper used by feedback_enrichment / intent_classifier."""
    text = (text or "").strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl > 0:
            text = text[nl + 1:]
        if text.endswith("```"):
            text = text[: -3]
    return text.strip()


# ─── Business context fetch ─────────────────────────────────────────

def fetch_business_context(business_id: str) -> Dict[str, Any]:
    """Fetch enriched_brief + brand_kit + available_slots for a business.
    Returns a dict ready to drop into the user prompt.

    Soft-fails: returns a context dict with sensible defaults if any
    Supabase call fails. Composer can then operate on the partial
    context (it'll likely flag a gap)."""
    ctx: Dict[str, Any] = {
        "business_name": "Unknown business",
        "business_description": "",
        "inferred_archetype": "service_consultant",
        "inferred_vibe": "",
        "brand_metaphor": "",
        "strand_pair": "",
        "sub_strand_id": "",
        "tone_words": [],
        "brand_kit": {
            "primary": "#0A1628",
            "secondary": "#122040",
            "accent": "#C6952F",
            "background": "#F8F6F1",
            "text": "#0F172A",
        },
        "available_slots": [],
    }
    try:
        from brand_engine import _sb_get as be_get
    except Exception as e:
        logger.warning(f"[composer] brand_engine import failed: {e}")
        return ctx

    # Business row + settings (carries brand_kit).
    try:
        biz_rows = be_get(
            f"/businesses?id=eq.{business_id}&select=name,settings&limit=1"
        ) or []
        if biz_rows:
            biz = biz_rows[0]
            ctx["business_name"] = biz.get("name") or ctx["business_name"]
            settings = biz.get("settings") or {}
            bk = settings.get("brand_kit") or {}
            colors = bk.get("colors") or {}
            for role in ("primary", "secondary", "accent", "background", "text"):
                if colors.get(role):
                    ctx["brand_kit"][role] = colors[role]
                else:
                    flat = "text_color" if role == "text" else f"{role}_color"
                    if bk.get(flat):
                        ctx["brand_kit"][role] = bk[flat]
            # Lift business_description from common settings keys.
            ctx["business_description"] = (
                bk.get("elevator_pitch")
                or settings.get("description")
                or settings.get("about")
                or ""
            )
    except Exception as e:
        logger.warning(f"[composer] business fetch failed for {business_id}: {e}")

    # site_config carries enriched_brief + slots.
    try:
        site_rows = be_get(
            f"/business_sites?business_id=eq.{business_id}&select=site_config&limit=1"
        ) or []
        if site_rows:
            cfg = site_rows[0].get("site_config") or {}
            eb = cfg.get("enriched_brief") or {}
            bi = cfg.get("build_inputs") or {}
            dr = cfg.get("design_recommendation") or {}
            # Pull from enriched_brief / build_inputs / design_recommendation
            # — keys can land in any of those depending on which agent
            # filled the row.
            ctx["business_name"] = (
                bi.get("business_name") or ctx["business_name"]
            )
            if not ctx["business_description"]:
                ctx["business_description"] = (
                    bi.get("description") or eb.get("description") or ""
                )
            ctx["inferred_archetype"] = (
                eb.get("content_archetype")
                or eb.get("inferred_archetype")
                or bi.get("archetype")
                or ctx["inferred_archetype"]
            )
            ctx["inferred_vibe"] = eb.get("inferred_vibe") or ""
            ctx["brand_metaphor"] = eb.get("brand_metaphor") or ""
            ctx["strand_pair"] = (
                f"{dr.get('strand_a_id', '')}/{dr.get('strand_b_id', '')}"
                if dr.get("strand_a_id") else ""
            )
            ctx["sub_strand_id"] = dr.get("sub_strand_id") or ""
            ctx["tone_words"] = eb.get("tone_words") or []
            slots = cfg.get("slots") or {}
            ctx["available_slots"] = sorted(slots.keys())
    except Exception as e:
        logger.warning(f"[composer] site_config fetch failed for {business_id}: {e}")

    return ctx


# ─── User prompt builder ────────────────────────────────────────────

def build_user_prompt(ctx: Dict[str, Any]) -> str:
    """Format the business context into a Composer user prompt."""
    tone_words = ctx.get("tone_words") or []
    tone_str = ", ".join(tone_words) if tone_words else "(none captured)"
    slots = ctx.get("available_slots") or []
    slots_str = ", ".join(slots) if slots else "(none populated yet)"
    bk = ctx.get("brand_kit") or {}

    return f"""Compose a Hero section for the following business.

BUSINESS CONTEXT:

  business_name:        {ctx.get('business_name') or '(unknown)'}
  business_description: {(ctx.get('business_description') or '(none)').strip()[:600]}
  inferred_archetype:   {ctx.get('inferred_archetype') or '(unknown)'}
  inferred_vibe:        {ctx.get('inferred_vibe') or '(none)'}
  brand_metaphor:       {ctx.get('brand_metaphor') or '(none)'}
  strand_pair:          {ctx.get('strand_pair') or '(none)'}
  sub_strand_id:        {ctx.get('sub_strand_id') or '(none)'}
  tone_words:           {tone_str}

BRAND KIT (resolved colors — use the Cathedral palette role names in your
mental model; the render layer maps role to hex via these values):

  authority (primary):   {bk.get('primary')}
  signal (accent):       {bk.get('accent')}
  warm-neutral (background): {bk.get('background')}
  deep_secondary:        {bk.get('secondary')}
  text_primary:          {bk.get('text')}

AVAILABLE IMAGE SLOTS (for variants that use an image):

  {slots_str}

  If no slots are populated yet, you can still pick an image-using variant
  and set image_slot_ref to 'hero_main' — the slot resolver will render a
  placeholder until the practitioner uploads.

Pick ONE variant from the 11. Pick treatments. Write the content. Output
only the JSON object specified in the system prompt."""


# ─── Post-validation ────────────────────────────────────────────────

def _enforce_image_slot_consistency(comp_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Set image_slot_ref to 'hero_main' iff variant uses images; else
    null. The variant choice is the source of truth — the Composer is
    asked to set image_slot_ref correctly but post-validation enforces
    it so the render layer always sees a consistent state."""
    variant = comp_dict.get("variant")
    content = comp_dict.get("content") or {}
    if variant in IMAGE_USING_VARIANTS:
        if not content.get("image_slot_ref"):
            content["image_slot_ref"] = "hero_main"
    else:
        content["image_slot_ref"] = None
    comp_dict["content"] = content
    return comp_dict


# ─── Public entrypoint ──────────────────────────────────────────────

def compose_cathedral_hero(business_id: str) -> Dict[str, Any]:
    """Run the Composer Agent for one business. Returns a JSON-serializable
    dict matching CathedralHeroComposition (validated). Soft-fails on
    any error to a fallback composition with `_composer_error` set.

    Mostly synchronous: one Sonnet call (~5-8 seconds typical), one
    Pydantic validation, one post-validation pass. One retry on JSON
    parse failure.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _safe_fallback(business_id, "ANTHROPIC_API_KEY not configured")

    ctx = fetch_business_context(business_id)
    user_prompt = build_user_prompt(ctx)

    client = Anthropic(api_key=api_key)

    def _call(extra_user: str = "") -> str:
        msg = client.messages.create(
            model=COMPOSER_MODEL,
            max_tokens=COMPOSER_MAX_TOKENS,
            temperature=COMPOSER_TEMPERATURE,
            system=COMPOSER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt + extra_user}],
        )
        return "".join(
            b.text for b in msg.content if getattr(b, "type", None) == "text"
        )

    try:
        raw = _call()
    except Exception as e:
        logger.warning(
            f"[composer] Anthropic call failed for {business_id}: "
            f"{type(e).__name__}: {e}"
        )
        return _safe_fallback(business_id, f"Anthropic call failed: {type(e).__name__}: {e}")

    text = _strip_code_fence(raw)
    parsed: Optional[Dict[str, Any]] = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"[composer] JSON parse failed (attempt 1): {e}")
        # Retry once with explicit error feedback.
        retry_extra = (
            f"\n\nYour previous response was not valid JSON. The error was: "
            f"{e}\n\nTry again. Output ONLY the JSON object, nothing else. "
            f"No markdown fences. No prose."
        )
        try:
            raw_retry = _call(retry_extra)
            text_retry = _strip_code_fence(raw_retry)
            parsed = json.loads(text_retry)
        except Exception as retry_e:
            logger.warning(f"[composer] retry also failed: {retry_e}")
            return _safe_fallback(business_id, f"JSON parse failed (after retry): {retry_e}", raw=text)

    if not isinstance(parsed, dict):
        return _safe_fallback(business_id, "Model returned non-object", raw=text)

    parsed = _enforce_image_slot_consistency(parsed)

    # Ensure 'section' field is present (Literal default).
    parsed.setdefault("section", "hero")

    # Validate against the typed model. If validation fails, log + fallback.
    try:
        composition = CathedralHeroComposition.model_validate(parsed)
    except ValidationError as ve:
        logger.warning(f"[composer] Pydantic validation failed: {ve}")
        return _safe_fallback(business_id, f"Validation failed: {ve}", raw=text)

    # Return as plain dict for JSON serialization. Pydantic v2 uses
    # model_dump; v1 falls back to dict.
    if hasattr(composition, "model_dump"):
        return composition.model_dump()
    return composition.dict()  # type: ignore[attr-defined]


# ─── Diagnostic helper for spike testing ────────────────────────────

def compose_for_spike(business_id: str) -> Dict[str, Any]:
    """Phase 3 testing helper. Same as compose_cathedral_hero but adds
    business_id + Composer cost forecast to the returned dict so the
    test harness can format reports."""
    composition = compose_cathedral_hero(business_id)
    composition["_business_id"] = business_id
    return composition
