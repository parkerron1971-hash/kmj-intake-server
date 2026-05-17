"""Pass 4.0g Phase D — Module Router Agent.

Sonnet 4.5 router that picks WHICH design module fits a business
before the module-specific Composer runs. First step in the
multi-module composition pipeline:

  Module Router (this file) -> picks 'cathedral' or 'studio_brut'
        v
  Module-specific Composer -> picks variant + treatments + content
        v
  Render pipeline -> emits HTML

The router's job is matching ARCHETYPE to DNA. Brand-kit colors are
supporting evidence, NOT the primary signal — a custom apparel brand
with navy colors still routes to Studio Brut; a law firm with red
colors still routes to Cathedral.

Mirrors the LLM-call pattern from cathedral_hero_composer.py:
  - Lazy Anthropic SDK import
  - _strip_code_fence helper (re-used from composer)
  - explicit JSON schema in the system prompt
  - never raises; soft-fails to a Cathedral default on errors
  - confidence-tiered retry: < 0.5 retries once with "be more decisive"
  - JSON parse retry once on malformed first response

Public surface:
  ModuleRoutingDecision  Pydantic model
  route_module(business_id, available_modules=None) -> Dict
    Fetches business context from Supabase + routes. Returns dict
    matching ModuleRoutingDecision schema with extra _route_metadata
    for diagnostics.
  _route_from_context(ctx, available_modules) -> Dict
    Internal — accepts a pre-built context dict instead of fetching.
    Used by the edge-case test harness with synthetic enriched_brief
    fixtures.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Literal, Optional

from anthropic import Anthropic
from pydantic import BaseModel, Field, ValidationError

# Re-use the strip helper that's already battle-tested in the Composer.
from agents.composer.cathedral_hero_composer import _strip_code_fence

logger = logging.getLogger(__name__)

ROUTER_MODEL = "claude-sonnet-4-5-20250929"
ROUTER_MAX_TOKENS = 700
# 0.3 — lower than Composer's 0.4 because routing should be
# CONSISTENT (same business -> same module across runs) rather than
# creatively varied. Convergence verification expects >0.8 confidence
# AND 3/3 module agreement.
ROUTER_TEMPERATURE = 0.3

ModuleId = Literal["cathedral", "studio_brut"]
DEFAULT_AVAILABLE_MODULES: List[ModuleId] = ["cathedral", "studio_brut"]

# Confidence thresholds — used by the validation + retry logic AND
# named in the system prompt so the LLM calibrates against them.
CONFIDENCE_RETRY_FLOOR = 0.5      # below this triggers a "be more decisive" retry
CONFIDENCE_ALTERNATIVE_THRESHOLD = 0.7  # below this requires alternative_module
CONFIDENCE_HIGH_BAR = 0.9         # at-or-above counts as a "clear match" in calibration


# ─── Pydantic models ────────────────────────────────────────────────

class ModuleRoutingDecision(BaseModel):
    """Output of the Module Router. JSON-serializable; the diagnostic
    endpoint returns this dict directly."""

    module_id: ModuleId
    confidence: float = Field(
        ge=0.0, le=1.0,
        description=(
            "Router's confidence in module_id, 0.0 to 1.0. Calibrate "
            "to: 0.9+ clear archetypal match; 0.7-0.9 good fit with "
            "some ambiguity; below 0.7 genuine ambiguity (must "
            "populate alternative_module)."
        ),
    )
    reasoning: str = Field(
        description=(
            "1-3 sentences: why this module fits this business "
            "archetype. Should reference the business's archetype + "
            "vibe + metaphor, NOT the brand_kit palette as the "
            "primary signal."
        ),
    )
    alternative_module: Optional[ModuleId] = Field(
        default=None,
        description=(
            "Required when confidence < 0.7 — the second-choice "
            "module the business could plausibly route to. Null when "
            "confidence is high."
        ),
    )


# ─── System prompt ──────────────────────────────────────────────────

ROUTER_SYSTEM_PROMPT = """You are a senior design director with deep familiarity with the Solutionist design library. Your job: match a business to the design MODULE whose aesthetic DNA fits the business archetype. You do NOT pick variants or treatments — that's the module's Composer Agent's job. You only pick WHICH module.

═══════════════════════════════════════════════════════════════
THE TWO MODULES
═══════════════════════════════════════════════════════════════

─── CATHEDRAL (cinematic_authority) ───

DNA: editorial restraint, classical authority, refined typography (Playfair Display serif), italic emphasis as signature, diamond motif as decoration, generous whitespace, gold-and-navy default palette, contemplative scroll rhythm.

The Cathedral feel: editorial, considered, monastic, ceremonial, premium-by-restraint, authority-through-quietness. Cathedral pages feel like high-end editorial magazines or premium service brochures. Words carry weight; ornamentation is reserved.

Archetypal Cathedral businesses:
  - Creative agencies that lead with STRATEGIC consultancy framing (not personality-led shops)
  - Technical consultancies, methodology-driven practitioners, process-led businesses
  - Authority experts (financial advisors, legal counsel, established professionals)
  - Pastoral / community / ceremonial leadership (churches, pastoral counselors)
  - Editorial content brands (newsletters, longform publications, opinion practices)
  - Businesses claiming "refinement" or "premium" as a primary value
  - Established medical practices, traditional professional services
  - Wealth managers, private banks, institutional services
  - Classical luxury brands (jewelry, watches, white-glove services)

Cathedral ANTI-archetypes (never serve these — Studio Brut or future modules):
  - Custom apparel designers, streetwear brands
  - Urban photographers, lifestyle photographers with grit
  - Independent makers, artisan craft brands with bold visual identity
  - Music / culture / nightlife brands
  - Design studios that lead with personality rather than process
  - Anyone whose brand identity is "loud" or "expressive" or "rule-breaking"

─── STUDIO BRUT (studio_brut) ───

DNA: bold, urban, graphic, expressive. Color is architecture (full color blocks define layout). Type is graphic material (oversized headlines, weight contrast, type-as-ornament). Asymmetry is baseline. Sharp commits, no soft fades. Density over breathing room. Display sans / brutalist sans / condensed type (NEVER Playfair). Squares, rectangles, circles, bars as ornament (NEVER diamonds). Default palette: red + yellow + near-black.

The Studio Brut feel: poster-graphic, brutalist-web, street-aware, maker-aesthetic, visibly loud, intentionally rule-breaking. Studio Brut pages feel like graphic-design artifacts themselves — risograph posters, streetwear lookbooks, editorial fashion magazines, music label sites.

Archetypal Studio Brut businesses:
  - Custom apparel designers, streetwear brands, t-shirt makers, embroiderers
  - Design studios with edge (branding agencies that lead with personality, illustration/lettering studios, type foundries)
  - Urban photographers (street, fashion, editorial, documentary)
  - Independent makers (print shops, ceramicists with bold visual identity, leather workers, custom furniture)
  - Creative agencies that lead with PERSONALITY (not process / consultancy framing)
  - Lifestyle brands with attitude (apparel-adjacent, accessories, urban culture)
  - Music / culture / nightlife brands (venues, labels, promoters, DJ collectives)
  - Skate / surf / streetwear-adjacent (board shops, custom builders)
  - Independent restaurants and bars with strong visual identity (taco shops with great signage, third-wave coffee with character)

Studio Brut ANTI-archetypes (never serve these — Cathedral or future modules):
  - Law firms (especially traditional / established)
  - Financial advisors, wealth managers, insurance, banking
  - Established medical practices
  - Ceremonial pastoral leadership, traditional religious institutions
  - Classical luxury brands (jewelry, watches, white-glove)
  - Government-adjacent businesses, public sector
  - Academic institutions, research organizations
  - B2B SaaS with corporate buyers (Cathedral until future Field Manual module)
  - Residential real estate (Cathedral)

═══════════════════════════════════════════════════════════════
DECISION CRITERIA
═══════════════════════════════════════════════════════════════

Weight signals in this order:

  1. INFERRED_ARCHETYPE — weighs heaviest. Match the archetype to the module's archetypal list directly. A custom apparel designer is Studio Brut regardless of anything else.

  2. BRAND_METAPHOR + INFERRED_VIBE — supporting evidence. A "courtroom of taste" metaphor leans Cathedral; a "studio floor" metaphor leans Studio Brut. A vibe like "contemplative" leans Cathedral; "loud" or "expressive" leans Studio Brut.

  3. TONE_WORDS — supporting evidence. "Refined", "considered", "premium" suggest Cathedral. "Bold", "raw", "real" suggest Studio Brut.

  4. BUSINESS_DESCRIPTION — context for the above, not a primary signal. A description full of "we elevate" / "world-class" / "trusted partner" leans Cathedral. A description full of "we make" / "bold" / "real" / direct address leans Studio Brut.

NOT a routing signal:
  - BRAND_KIT colors. Brand kit colors do NOT drive routing. A custom apparel brand with navy + gold colors still routes to Studio Brut. A law firm with red + yellow colors still routes to Cathedral. The module is determined by what the business DOES + how it speaks, not by which colors it chose. The module then USES the brand_kit colors through its own DNA interpretation.

═══════════════════════════════════════════════════════════════
CONFIDENCE CALIBRATION
═══════════════════════════════════════════════════════════════

  0.95 — unambiguous archetypal match. "Custom apparel designer" -> studio_brut at 0.95+. "Law firm" -> cathedral at 0.95+. There is no plausible second-choice module.

  0.85 — clear primary fit with minor cross-pull. "Creative agency that does some brand strategy" — Studio Brut probably wins (personality-led) but Cathedral has a foothold (consultancy framing).

  0.75 — good fit with real ambiguity. The business has mixed archetypal signals; one module wins on balance but a thoughtful reviewer might disagree. Set alternative_module.

  0.60 — genuine ambiguity. The business sits at the seam between two modules. Pick the closer fit, set alternative_module, lean toward the safer module (usually Cathedral unless the business is clearly maker/apparel/streetwear).

  Below 0.50 — DO NOT RETURN. You should always be able to pick a module with at least 0.50 confidence. If you genuinely can't decide, default to cathedral (the more conservative aesthetic) and explain the ambiguity in reasoning.

Be honest. Don't manufacture high confidence to look decisive — surfacing real ambiguity is more useful than a confident wrong call.

═══════════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════════

You output ONE JSON object. No markdown fences. No prose outside the JSON. The schema:

{
  \"module_id\": \"<cathedral | studio_brut>\",
  \"confidence\": <float 0.0 to 1.0>,
  \"reasoning\": \"<1-3 sentences referencing archetype + vibe + metaphor (NOT brand_kit colors) — why this module fits this business>\",
  \"alternative_module\": \"<cathedral | studio_brut>\" OR null
}

alternative_module MUST be populated when confidence < 0.7 — it's the second-choice module the business could plausibly route to. Set null when confidence >= 0.7.

Output ONLY the JSON object."""


# ─── Soft-fail fallback ─────────────────────────────────────────────

def _safe_routing_fallback(business_id: str, reason: str) -> Dict[str, Any]:
    """Default to Cathedral when routing fails for any reason. Cathedral
    is the safer aesthetic for unclear cases — it's editorial-restrained
    rather than loud, so a mis-routed business renders professionally
    even if not optimally."""
    return {
        "module_id": "cathedral",
        "confidence": 0.5,
        "reasoning": (
            f"FALLBACK — router failed: {reason}. Defaulted to "
            f"cathedral (safer aesthetic for unclear cases)."
        ),
        "alternative_module": "studio_brut",
        "_router_error": reason,
    }


# ─── Routing context fetch ─────────────────────────────────────────

def fetch_routing_context(business_id: str) -> Dict[str, Any]:
    """Fetch enriched_brief / archetype / vibe / metaphor / tone_words
    + brand_kit for routing. Same surface as Composer's
    fetch_business_context but the router doesn't need available_slots
    (slot resolution is a render-time concern).

    Soft-fails: returns a context dict with defaults if Supabase calls
    fail. Router will return low confidence + log the gap."""
    ctx: Dict[str, Any] = {
        "business_id": business_id,
        "business_name": "Unknown business",
        "business_description": "",
        "inferred_archetype": "service_consultant",
        "inferred_vibe": "",
        "brand_metaphor": "",
        "tone_words": [],
        "brand_kit": {},  # surfaced in prompt for the LLM to dismiss as non-primary
    }
    try:
        from brand_engine import _sb_get as be_get
    except Exception as e:
        logger.warning(f"[module_router] brand_engine import failed: {e}")
        return ctx

    try:
        biz_rows = be_get(
            f"/businesses?id=eq.{business_id}&select=name,settings&limit=1"
        ) or []
        if biz_rows:
            biz = biz_rows[0]
            ctx["business_name"] = biz.get("name") or ctx["business_name"]
            settings = biz.get("settings") or {}
            bk = settings.get("brand_kit") or {}
            ctx["brand_kit"] = bk.get("colors") or {}
            ctx["business_description"] = (
                bk.get("elevator_pitch")
                or settings.get("description")
                or settings.get("about")
                or ""
            )
    except Exception as e:
        logger.warning(f"[module_router] businesses fetch failed for {business_id}: {e}")

    try:
        site_rows = be_get(
            f"/business_sites?business_id=eq.{business_id}&select=site_config&limit=1"
        ) or []
        if site_rows:
            cfg = site_rows[0].get("site_config") or {}
            eb = cfg.get("enriched_brief") or {}
            bi = cfg.get("build_inputs") or {}
            ctx["business_name"] = bi.get("business_name") or ctx["business_name"]
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
            ctx["tone_words"] = eb.get("tone_words") or []
    except Exception as e:
        logger.warning(f"[module_router] site_config fetch failed for {business_id}: {e}")

    return ctx


# ─── User prompt builder ────────────────────────────────────────────

def _build_user_prompt(ctx: Dict[str, Any], available_modules: List[str]) -> str:
    """Format the routing context into a Module Router user prompt."""
    tone_words = ctx.get("tone_words") or []
    tone_str = ", ".join(tone_words) if tone_words else "(none captured)"
    bk = ctx.get("brand_kit") or {}
    palette_str = (
        f"primary={bk.get('primary', '?')}, "
        f"signal/accent={bk.get('accent', '?')}, "
        f"warm-neutral={bk.get('background', '?')}, "
        f"secondary={bk.get('secondary', '?')}, "
        f"text={bk.get('text', '?')}"
        if bk
        else "(brand_kit not populated)"
    )

    return f"""Route the following business to the best-fit design module.

Available modules: {", ".join(available_modules)}

BUSINESS CONTEXT:

  business_name:        {ctx.get('business_name') or '(unknown)'}
  business_description: {(ctx.get('business_description') or '(none)').strip()[:600]}
  inferred_archetype:   {ctx.get('inferred_archetype') or '(unknown)'}
  inferred_vibe:        {ctx.get('inferred_vibe') or '(none)'}
  brand_metaphor:       {ctx.get('brand_metaphor') or '(none)'}
  tone_words:           {tone_str}
  brand_kit_palette:    {palette_str}
    (palette is SUPPORTING evidence only — do not let it drive routing)

Pick ONE module from the available list. Calibrate confidence honestly.
If confidence < 0.7, populate alternative_module. Output only the JSON
object specified in the system prompt."""


# ─── Internal LLM call + validation ────────────────────────────────

def _validate_decision(raw_obj: Any) -> Optional[ModuleRoutingDecision]:
    """Validate a raw response dict against the Pydantic model.
    Returns the model instance on success, None on validation error."""
    if not isinstance(raw_obj, dict):
        return None
    try:
        return ModuleRoutingDecision.model_validate(raw_obj)
    except ValidationError as ve:
        logger.warning(f"[module_router] Pydantic validation failed: {ve}")
        return None


def _enforce_alternative(decision: ModuleRoutingDecision,
                         available_modules: List[str]) -> ModuleRoutingDecision:
    """If confidence < 0.7 and alternative_module is missing/same as
    module_id, fill it deterministically with the other module."""
    if decision.confidence < CONFIDENCE_ALTERNATIVE_THRESHOLD:
        if (decision.alternative_module is None
                or decision.alternative_module == decision.module_id):
            others = [m for m in available_modules if m != decision.module_id]
            if others:
                decision = decision.model_copy(
                    update={"alternative_module": others[0]}
                )
    return decision


def _route_from_context(
    ctx: Dict[str, Any],
    available_modules: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run the router on a pre-built context dict. Used by route_module
    after fetching context, AND by the edge-case test harness with
    synthetic enriched_brief fixtures."""
    available = available_modules or DEFAULT_AVAILABLE_MODULES

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _safe_routing_fallback(
            ctx.get("business_id", "unknown"),
            "ANTHROPIC_API_KEY not configured",
        )

    user_prompt = _build_user_prompt(ctx, available)
    client = Anthropic(api_key=api_key)

    def _call(extra_user: str = "") -> str:
        msg = client.messages.create(
            model=ROUTER_MODEL,
            max_tokens=ROUTER_MAX_TOKENS,
            temperature=ROUTER_TEMPERATURE,
            system=ROUTER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt + extra_user}],
        )
        return "".join(
            b.text for b in msg.content if getattr(b, "type", None) == "text"
        )

    # ── Attempt 1: initial routing call ──
    try:
        raw = _call()
    except Exception as e:
        logger.warning(
            f"[module_router] Anthropic call failed for "
            f"{ctx.get('business_id')}: {type(e).__name__}: {e}"
        )
        return _safe_routing_fallback(
            ctx.get("business_id", "unknown"),
            f"Anthropic call failed: {type(e).__name__}: {e}",
        )

    text = _strip_code_fence(raw)
    parsed: Optional[Dict[str, Any]] = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"[module_router] JSON parse failed (attempt 1): {e}")
        # JSON parse retry
        try:
            retry_msg = (
                f"\n\nYour previous response was not valid JSON. Error: "
                f"{e}\n\nOutput ONLY the JSON object. No markdown fences."
            )
            raw_retry = _call(retry_msg)
            parsed = json.loads(_strip_code_fence(raw_retry))
        except Exception as retry_e:
            logger.warning(f"[module_router] JSON retry also failed: {retry_e}")
            return _safe_routing_fallback(
                ctx.get("business_id", "unknown"),
                f"JSON parse failed after retry: {retry_e}",
            )

    decision = _validate_decision(parsed)
    if decision is None:
        return _safe_routing_fallback(
            ctx.get("business_id", "unknown"),
            "model output failed schema validation",
        )

    # ── Confidence-tiered retry ──
    if decision.confidence < CONFIDENCE_RETRY_FLOOR:
        logger.warning(
            f"[module_router] confidence {decision.confidence} below "
            f"floor {CONFIDENCE_RETRY_FLOOR} — retrying with 'be more decisive'"
        )
        retry_msg = (
            f"\n\nYour previous response had confidence {decision.confidence}, "
            f"which is below the {CONFIDENCE_RETRY_FLOOR} floor. Be more "
            f"decisive — even if the business sits at the seam between "
            f"modules, pick the closer fit and explain the ambiguity in "
            f"reasoning. Output the full JSON again."
        )
        try:
            raw_retry = _call(retry_msg)
            parsed_retry = json.loads(_strip_code_fence(raw_retry))
            retry_decision = _validate_decision(parsed_retry)
            if retry_decision is not None:
                decision = retry_decision
        except Exception as retry_e:
            logger.warning(
                f"[module_router] decisiveness retry failed: {retry_e}"
            )

        # If still below the floor after retry, default to Cathedral
        # (safer aesthetic for unclear cases).
        if decision.confidence < CONFIDENCE_RETRY_FLOOR:
            logger.warning(
                f"[module_router] confidence {decision.confidence} still "
                f"below floor after retry — defaulting to cathedral"
            )
            return _safe_routing_fallback(
                ctx.get("business_id", "unknown"),
                f"persistent low confidence ({decision.confidence})",
            )

    # ── Enforce alternative_module when confidence < 0.7 ──
    decision = _enforce_alternative(decision, available)

    out = decision.model_dump()
    out["_route_metadata"] = {
        "business_id": ctx.get("business_id"),
        "business_name": ctx.get("business_name"),
        "archetype_used": ctx.get("inferred_archetype"),
        "available_modules": available,
    }
    return out


# ─── Public entrypoint ──────────────────────────────────────────────

def route_module(
    business_id: str,
    available_modules: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Decide which design module to use for a business.

    Returns a dict matching ModuleRoutingDecision schema (with
    `_route_metadata` envelope for diagnostics). Soft-fails to
    cathedral on any error.

    Module Router runs BEFORE the module-specific Composer. The full
    composition pipeline:

      route_module(business_id)         -> ModuleRoutingDecision
        v
      <module>_hero_composer.compose(business_id) -> Composition
        v
      render_pipeline.render(composition, business_id) -> HTML
    """
    ctx = fetch_routing_context(business_id)
    return _route_from_context(ctx, available_modules)
