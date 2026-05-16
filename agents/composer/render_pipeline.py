"""Pass 4.0f Phase 4 — Cathedral Hero render pipeline.

Takes a CathedralHeroComposition (Composer Agent's Phase 3 output) and
emits production-shaped HTML by reusing the existing render
infrastructure verbatim:

  1. variant renderer        (Phase 2/2.5 — VARIANT_REGISTRY)
  2. brand_kit_renderer      (Pass 4.0d PART 3 — :root --brand-* vars)
  3. slot_resolver           (Pass 4.0b.5 PART 4 — <img data-slot=>)
  4. override_resolver       (Pass 4.0d PART 1 — data-override-target)

The shape of the pipeline mirrors smart_sites._try_serve_builder_html
so the spike output is rendered through the same path that production
sites use. This is the spike thesis: the new variants are drop-in
compatible with the existing render stack.

Two public entry points:

  render_hero_fragment(composition, business_id) -> str
    Returns just the <section data-section="hero"> ... </section>
    after all four pipeline steps. For embedding in an existing page
    or for downstream comparison work.

  render_hero_standalone(composition, business_id) -> str
    Same fragment wrapped in a minimal <!DOCTYPE html> doc with the
    Cathedral fonts pre-loaded. Browser-viewable URL artifact for
    CHECKPOINT 4 + Phase 5 comparison page.

NOT WIRED into kmj_intake_automation.py during the spike. Tested via
the standalone agents/composer/_spike_app.py FastAPI (Phase 4) or
direct Python invocation.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from agents.design_modules.cinematic_authority.hero.types import (
    BrandKitColors,
    CathedralHeroComposition,
    IMAGE_USING_VARIANTS,
    RenderContext,
)
from agents.design_modules.cinematic_authority.hero.variants import VARIANT_REGISTRY
from agents.design_modules.cinematic_authority.hero.treatments import (
    # Phase 2 — structural rhythm
    color_emphasis_vars,
    emphasis_weight_vars,
    spacing_density_vars,
    # Phase 2.6 — visual depth
    background_treatment_vars,
    color_depth_vars,
    image_treatment_vars,
    ornament_treatment_vars,
    typography_personality_vars,
)

logger = logging.getLogger(__name__)


# ─── Brand kit + slot resolution helpers ────────────────────────────

_DEFAULT_BRAND = BrandKitColors(
    primary="#0A1628",
    secondary="#122040",
    accent="#C6952F",
    background="#F8F6F1",
    text="#0F172A",
)


def _fetch_brand_kit(business_id: str) -> BrandKitColors:
    """Pull businesses.settings.brand_kit.colors as BrandKitColors.
    Soft-fails to the Cinematic Authority default palette."""
    try:
        from brand_engine import _sb_get as be_get
        rows = be_get(
            f"/businesses?id=eq.{business_id}&select=settings&limit=1"
        ) or []
    except Exception as e:
        logger.warning(f"[render_pipeline] brand_kit fetch failed: {e}")
        return _DEFAULT_BRAND

    if not rows:
        return _DEFAULT_BRAND
    settings = rows[0].get("settings") or {}
    bk = settings.get("brand_kit") or {}
    colors = bk.get("colors") or {}
    return BrandKitColors(
        primary=colors.get("primary") or _DEFAULT_BRAND.primary,
        secondary=colors.get("secondary") or _DEFAULT_BRAND.secondary,
        accent=colors.get("accent") or _DEFAULT_BRAND.accent,
        background=colors.get("background") or _DEFAULT_BRAND.background,
        text=colors.get("text") or _DEFAULT_BRAND.text,
    )


# Spike-only placeholder so image-using variants display something when
# the business hasn't populated its hero_main slot yet. Unsplash, free
# license, neutral editorial composition.
_SPIKE_PLACEHOLDER_IMAGE = (
    "https://images.unsplash.com/photo-1497366216548-37526070297c"
    "?auto=format&fit=crop&w=1600&q=80"
)


def _resolve_hero_slot(business_id: str) -> Dict[str, str]:
    """Resolve the hero_main slot URL for the business. Returns a
    {slot_name: url} dict ready for RenderContext.slot_resolutions.

    Resolution order:
      1. business_sites.site_config.slots.hero_main (custom_url > default_url)
      2. spike placeholder (so image-using variants always show something)
    """
    try:
        from brand_engine import _sb_get as be_get
        from agents.slot_system.slot_resolver import resolve_slot_url
        rows = be_get(
            f"/business_sites?business_id=eq.{business_id}"
            f"&select=site_config&limit=1"
        ) or []
        site_cfg = (rows[0].get("site_config") if rows else None) or {}
        slots = site_cfg.get("slots") or {}
        record = slots.get("hero_main")
        resolved = resolve_slot_url(record, "hero_main")
        url = resolved.get("url")
        if url:
            return {"hero_main": url}
    except Exception as e:
        logger.warning(f"[render_pipeline] slot resolution failed: {e}")
    return {"hero_main": _SPIKE_PLACEHOLDER_IMAGE}


# ─── Context construction ──────────────────────────────────────────

def build_render_context(
    composition: CathedralHeroComposition,
    business_id: str,
) -> RenderContext:
    """Assemble the RenderContext from a composition + live business state.

    Phase 3 already validated the composition's image_slot_ref against
    IMAGE_USING_VARIANTS. We still pre-fetch slot resolutions so the
    variant's inline `src=` attribute is populated even if the
    downstream slot_resolver step is bypassed (e.g., in unit tests)."""
    brand_kit = _fetch_brand_kit(business_id)
    slot_resolutions = _resolve_hero_slot(business_id)
    return RenderContext(
        composition=composition,
        brand_kit=brand_kit,
        business_id=business_id,
        slot_resolutions=slot_resolutions,
    )


def _build_treatment_vars(composition: CathedralHeroComposition) -> Dict[str, str]:
    """Translate composition.treatments into CSS variable values.

    Merges all 8 dimensions (3 structural + 5 depth, Phase 2.6) into
    one dict. Order doesn't matter — none of the translators emit
    overlapping CSS variable names."""
    t = composition.treatments
    out: Dict[str, str] = {}
    # Structural (Phase 2)
    out.update(color_emphasis_vars(t.color_emphasis))
    out.update(spacing_density_vars(t.spacing_density))
    out.update(emphasis_weight_vars(t.emphasis_weight))
    # Visual depth (Phase 2.6)
    out.update(background_treatment_vars(t.background))
    out.update(color_depth_vars(t.color_depth))
    out.update(ornament_treatment_vars(t.ornament))
    out.update(typography_personality_vars(t.typography))
    out.update(image_treatment_vars(t.image_treatment))
    return out


# ─── Fragment render — variant + production pipeline ───────────────

def render_hero_fragment(
    composition: CathedralHeroComposition,
    business_id: str,
    *,
    apply_overrides: bool = True,
) -> str:
    """Render the Hero section through the canonical four-step pipeline.

    Returns ONLY the <section> markup (no doctype, no body). Useful when
    the caller wants to embed the result into an existing layout.

    apply_overrides=False short-circuits the override_resolver step —
    used by the comparison page when the spike output should match the
    composition verbatim (no practitioner edits applied)."""
    if composition.variant not in VARIANT_REGISTRY:
        raise ValueError(
            f"[render_pipeline] unknown variant {composition.variant!r}; "
            f"VARIANT_REGISTRY has {sorted(VARIANT_REGISTRY.keys())}"
        )

    ctx = build_render_context(composition, business_id)
    treatment_vars = _build_treatment_vars(composition)

    # Step 1: variant render. brand_vars is left empty here — the
    # canonical :root --brand-* vars come from brand_kit_renderer in
    # step 2. The variant emits `var(--brand-*)` references that pick
    # them up.
    renderer = VARIANT_REGISTRY[composition.variant]
    hero_html = renderer(ctx, {}, treatment_vars)

    # Step 2: brand_kit_renderer wants a doc with <head>. Wrap the
    # section in a minimal scaffold so the regex finds the insertion
    # point, then strip the scaffold after. Cleaner than duplicating
    # the renderer's logic.
    scaffolded = f"<html><head></head><body>{hero_html}</body></html>"
    try:
        from agents.design_intelligence.brand_kit_renderer import render_with_brand_kit
        scaffolded = render_with_brand_kit(scaffolded, business_id)
    except Exception as e:
        logger.warning(f"[render_pipeline] brand_kit inject failed: {e}")

    # Step 3: slot resolution. Treats the scaffolded doc as authoritative —
    # the variant emits `<img data-slot="hero_main" src="...">` so the
    # resolver finds and substitutes. Production-identical behavior.
    try:
        from agents.slot_system.slot_resolver import resolve_html_slots
        # We don't have a site_config object here — pass an inline slots
        # dict synthesized from our pre-resolved URL. This matches the
        # production shape that resolve_html_slots expects.
        synthesized_slots = {
            slot_name: {"default_url": url, "custom_url": None}
            for slot_name, url in ctx.slot_resolutions.items()
        }
        scaffolded, _credits, _found = resolve_html_slots(
            scaffolded, synthesized_slots,
        )
    except Exception as e:
        logger.warning(f"[render_pipeline] slot resolve failed: {e}")

    # Step 4: text overrides. Production-shaped — the practitioner's
    # post-Composer edits flow through the same site_content_overrides
    # table that smart_sites.py reads.
    if apply_overrides:
        try:
            from agents.override_system.override_resolver import resolve_html_overrides
            scaffolded = resolve_html_overrides(scaffolded, business_id)
        except Exception as e:
            logger.warning(f"[render_pipeline] override resolve failed: {e}")

    return scaffolded


# ─── Standalone document wrapper ───────────────────────────────────

# Doc shell that wraps a Hero fragment for browser viewing. The
# brand_kit_renderer injects :root --brand-* vars into <head>, so we
# only declare the font + reset variables here.
_DOC_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400;1,700&family=Outfit:wght@200;400;600;700;800&display=swap" rel="stylesheet">
<style>
:root {{
  --ca-serif: 'Playfair Display', Georgia, 'Times New Roman', serif;
  --ca-sans: 'Outfit', system-ui, -apple-system, sans-serif;
}}
html, body {{ margin: 0; padding: 0; font-family: var(--ca-sans); color: var(--brand-text-primary, #0F172A); background: var(--brand-warm-neutral, #F8F6F1); }}
.spike-banner {{
  position: fixed; bottom: 10px; right: 10px;
  background: rgba(0,0,0,0.78); color: #fff;
  font-family: ui-monospace, monospace; font-size: 11px;
  padding: 6px 10px; border-radius: 4px; z-index: 9999;
  pointer-events: none;
  letter-spacing: 0.3px;
}}
</style>
</head>
<body>
{hero_html}
<div class="spike-banner">spike · variant: {variant} · treatments: {treatments}</div>
</body>
</html>"""


def _strip_scaffold(html: str) -> str:
    """Pull the hero <section> back out of the <html><head></head>
    <body>...</body></html> scaffold we wrapped in render_hero_fragment.

    Brand-kit injection mutates the <head>, so we can't just substring
    on body tags blindly; use simple anchor pattern."""
    body_open = html.find("<body>")
    body_close = html.rfind("</body>")
    if body_open == -1 or body_close == -1 or body_close <= body_open:
        return html
    return html[body_open + len("<body>"):body_close].strip()


def render_hero_standalone(
    composition: CathedralHeroComposition,
    business_id: str,
    *,
    apply_overrides: bool = True,
) -> str:
    """Render a standalone HTML5 document containing the hero section.

    Production pipeline runs first (variant + brand-kit + slots +
    overrides). Then we extract the section, drop it inside our
    Cathedral-fonts doc shell, AND re-run brand_kit injection on the
    final doc so :root --brand-* vars land in the doc-shell <head>
    (the scaffold's empty head gets discarded along with the rest of
    the scaffold)."""
    fragment_doc = render_hero_fragment(
        composition, business_id, apply_overrides=apply_overrides,
    )
    hero_section = _strip_scaffold(fragment_doc)

    treatments_label = (
        f"{composition.treatments.color_emphasis} / "
        f"{composition.treatments.spacing_density} / "
        f"{composition.treatments.emphasis_weight}"
    )
    title = f"Cathedral Hero spike — {business_id[:8]} · {composition.variant}"

    doc = _DOC_SHELL.format(
        title=title,
        hero_html=hero_section,
        variant=composition.variant,
        treatments=treatments_label,
    )

    # Re-inject brand-kit :root vars into the doc-shell head. Cheap and
    # idempotent — render_with_brand_kit strips any prior block before
    # inserting the new one.
    try:
        from agents.design_intelligence.brand_kit_renderer import render_with_brand_kit
        doc = render_with_brand_kit(doc, business_id)
    except Exception as e:
        logger.warning(f"[render_pipeline] doc-shell brand_kit inject failed: {e}")

    return doc


# ─── Compose + render one-shot helper ──────────────────────────────

def compose_and_render(
    business_id: str,
    *,
    standalone: bool = True,
    apply_overrides: bool = True,
) -> Dict[str, Any]:
    """Convenience helper used by the spike endpoints: fires Composer
    then renders. Returns {composition, html, business_id}.

    Phase 3's compose_cathedral_hero already returns a dict (not a
    Pydantic model) because that's the JSON shape the spike endpoint
    serializes. Here we re-validate into the Pydantic model before
    handing off to the renderer — same defense pattern Phase 3 uses
    internally."""
    from agents.composer.cathedral_hero_composer import compose_cathedral_hero
    comp_dict = compose_cathedral_hero(business_id)
    composition = CathedralHeroComposition.model_validate(comp_dict)

    renderer = render_hero_standalone if standalone else render_hero_fragment
    html = renderer(composition, business_id, apply_overrides=apply_overrides)
    return {
        "business_id": business_id,
        "composition": comp_dict,
        "html": html,
    }
