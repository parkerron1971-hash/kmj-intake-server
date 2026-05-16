"""Pass 4.0f Phase 4 / Pass 4.0g Phase E — module-aware Hero render pipeline.

Takes a Hero composition (Cathedral OR Studio Brut) and emits production-
shaped HTML by reusing the existing render infrastructure:

  1. variant renderer        (module-specific VARIANT_REGISTRY)
  2. brand_kit_renderer      (Pass 4.0d PART 3 — :root --brand-* vars)
  3. slot_resolver           (Pass 4.0b.5 PART 4 — <img data-slot=>)
  4. override_resolver       (Pass 4.0d PART 1 — data-override-target)

The pipeline shape mirrors smart_sites._try_serve_builder_html so the
spike output renders through the same path production sites use. Phase
E generalizes the per-module dispatch (variant registry + treatment
translators selected by module_id).

Public surface:

  render_hero_fragment(composition_dict, business_id, module_id)
    Returns the <section data-section="hero"> ... </section> HTML
    after the four-step pipeline.

  render_hero_standalone(composition_dict, business_id, module_id)
    Same fragment wrapped in <!DOCTYPE html> with module-specific
    font stack pre-loaded (Cathedral = Playfair+Outfit; Studio Brut =
    Druk/Bebas/Space Grotesk/Archivo Black/Inter + JetBrains Mono).

  compose_and_render(business_id, module_id='cathedral', ...)
    Spike-legacy — fires module-specific Composer + renders.
    Preserved for backward compat with the Phase 4/5 spike endpoints.

  compose_and_render_hero(business_id) -> dict   ←   PHASE E END-TO-END
    Full multi-module pipeline:
      1. Module Router decides cathedral vs studio_brut
      2. Module-specific Composer composes within that module
      3. Module-specific render produces HTML
    Returns {business_id, module_id, routing_decision, composition, html}.

NOT WIRED into kmj_intake_automation.py during the spike. Tested via
the standalone agents/composer/_spike_app.py FastAPI or direct Python
invocation.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ─── Module-aware lookup table for renderers + translators ────────

def _cathedral_registry() -> Tuple[Dict[str, Callable], Callable, Any, Any]:
    """Returns (variant_registry, treatment_var_builder, BrandKitColors,
    RenderContext) for Cathedral. Lazy import so cinematic_authority is
    only loaded when actually rendering a Cathedral composition."""
    from agents.design_modules.cinematic_authority.hero.variants import VARIANT_REGISTRY
    from agents.design_modules.cinematic_authority.hero.types import (
        BrandKitColors, RenderContext, CathedralHeroComposition,
    )
    from agents.design_modules.cinematic_authority.hero.treatments import (
        color_emphasis_vars, emphasis_weight_vars, spacing_density_vars,
        background_treatment_vars, color_depth_vars, image_treatment_vars,
        ornament_treatment_vars, typography_personality_vars,
    )

    def build_treatment_vars(composition_dict: Dict[str, Any]) -> Dict[str, str]:
        t = composition_dict.get("treatments") or {}
        out: Dict[str, str] = {}
        out.update(color_emphasis_vars(t.get("color_emphasis", "signal_dominant")))
        out.update(spacing_density_vars(t.get("spacing_density", "standard")))
        out.update(emphasis_weight_vars(t.get("emphasis_weight", "heading_dominant")))
        out.update(background_treatment_vars(t.get("background", "flat")))
        out.update(color_depth_vars(t.get("color_depth", "flat")))
        out.update(ornament_treatment_vars(t.get("ornament", "minimal")))
        out.update(typography_personality_vars(t.get("typography", "editorial")))
        out.update(image_treatment_vars(t.get("image_treatment", "clean")))
        return out

    return VARIANT_REGISTRY, build_treatment_vars, BrandKitColors, RenderContext, CathedralHeroComposition


def _studio_brut_registry() -> Tuple[Dict[str, Callable], Callable, Any, Any]:
    """Returns (variant_registry, treatment_var_builder, BrandKitColors,
    RenderContext) for Studio Brut. Lazy import."""
    from agents.design_modules.studio_brut.hero.variants import VARIANT_REGISTRY
    from agents.design_modules.studio_brut.hero.types import (
        BrandKitColors, RenderContext, StudioBrutHeroComposition,
    )
    from agents.design_modules.studio_brut.hero.treatments import (
        color_emphasis_vars, emphasis_weight_vars, spacing_density_vars,
        background_treatment_vars, color_depth_vars, image_treatment_vars,
        ornament_treatment_vars, typography_personality_vars,
    )

    def build_treatment_vars(composition_dict: Dict[str, Any]) -> Dict[str, str]:
        t = composition_dict.get("treatments") or {}
        out: Dict[str, str] = {}
        out.update(color_emphasis_vars(t.get("color_emphasis", "signal_dominant")))
        out.update(spacing_density_vars(t.get("spacing_density", "standard")))
        out.update(emphasis_weight_vars(t.get("emphasis_weight", "heading_dominant")))
        out.update(background_treatment_vars(t.get("background", "flat")))
        out.update(color_depth_vars(t.get("color_depth", "flat")))
        out.update(ornament_treatment_vars(t.get("ornament", "minimal")))
        out.update(typography_personality_vars(t.get("typography", "editorial")))
        out.update(image_treatment_vars(t.get("image_treatment", "clean")))
        return out

    return VARIANT_REGISTRY, build_treatment_vars, BrandKitColors, RenderContext, StudioBrutHeroComposition


def _get_module_registry(module_id: str):
    """Dispatch to the module-specific render surface."""
    if module_id == "studio_brut":
        return _studio_brut_registry()
    # Cathedral is the default for unknown module_ids (safer fallback —
    # matches the composer's behavior on unknown module_id).
    return _cathedral_registry()


# ─── Module-specific defaults (module-agnostic shape) ──────────────

# Cathedral default palette
_CATHEDRAL_DEFAULT_BRAND = {
    "primary": "#0A1628", "secondary": "#122040",
    "accent": "#C6952F", "background": "#F8F6F1", "text": "#0F172A",
}
# Studio Brut default palette per STUDIO_BRUT_DESIGN.md Section 8
_STUDIO_BRUT_DEFAULT_BRAND = {
    "primary": "#DC2626", "secondary": "#18181B",
    "accent": "#FACC15", "background": "#F4F4F0", "text": "#09090B",
}


def _fetch_brand_kit(business_id: str, module_id: str):
    """Pull businesses.settings.brand_kit.colors as the module's
    BrandKitColors type. Soft-fails to the module's default palette."""
    _, _, BrandKitColors, _, _ = _get_module_registry(module_id)
    defaults = (
        _STUDIO_BRUT_DEFAULT_BRAND if module_id == "studio_brut"
        else _CATHEDRAL_DEFAULT_BRAND
    )
    try:
        from brand_engine import _sb_get as be_get
        rows = be_get(
            f"/businesses?id=eq.{business_id}&select=settings&limit=1"
        ) or []
    except Exception as e:
        logger.warning(f"[render_pipeline] brand_kit fetch failed: {e}")
        return BrandKitColors(**defaults)

    if not rows:
        return BrandKitColors(**defaults)
    settings = rows[0].get("settings") or {}
    bk = settings.get("brand_kit") or {}
    colors = bk.get("colors") or {}
    return BrandKitColors(
        primary=colors.get("primary") or defaults["primary"],
        secondary=colors.get("secondary") or defaults["secondary"],
        accent=colors.get("accent") or defaults["accent"],
        background=colors.get("background") or defaults["background"],
        text=colors.get("text") or defaults["text"],
    )


_SPIKE_PLACEHOLDER_IMAGE = (
    "https://images.unsplash.com/photo-1497366216548-37526070297c"
    "?auto=format&fit=crop&w=1600&q=80"
)


def _resolve_hero_slot(business_id: str) -> Dict[str, str]:
    """Resolve hero_main slot URL. Module-agnostic — slot resolution
    pulls from business_sites.site_config.slots regardless of module."""
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


# ─── Fragment render — variant + production pipeline ───────────────

def render_hero_fragment(
    composition_dict: Dict[str, Any],
    business_id: str,
    module_id: str = "cathedral",
    *,
    apply_overrides: bool = True,
) -> str:
    """Render the Hero section through the canonical four-step pipeline.

    composition_dict: JSON-shaped composition from the module's composer
                      (output of compose_hero(business_id, module_id)).
    module_id: 'cathedral' or 'studio_brut'.

    Returns ONLY the <section> markup (no doctype, no body)."""
    variant_registry, build_treatment_vars, BrandKitColors, RenderContext, CompositionType = (
        _get_module_registry(module_id)
    )

    variant_id = composition_dict.get("variant")
    if variant_id not in variant_registry:
        raise ValueError(
            f"[render_pipeline] module={module_id!r} doesn't know variant "
            f"{variant_id!r}; registry has {sorted(variant_registry.keys())}"
        )

    # Re-validate the composition through the module's Pydantic type.
    # Both modules' composition types accept the same shape (variant +
    # treatments + content + reasoning); Studio Brut has an additional
    # `module` discriminator we set below.
    if module_id == "studio_brut":
        composition_dict.setdefault("module", "studio_brut")
    composition = CompositionType.model_validate(composition_dict)

    brand_kit = _fetch_brand_kit(business_id, module_id)
    slot_resolutions = _resolve_hero_slot(business_id)
    ctx = RenderContext(
        composition=composition,
        brand_kit=brand_kit,
        business_id=business_id,
        slot_resolutions=slot_resolutions,
    )

    treatment_vars = build_treatment_vars(composition_dict)

    # Step 1: variant render. brand_vars left empty; :root --brand-*
    # vars come from brand_kit_renderer in step 2.
    renderer = variant_registry[variant_id]
    hero_html = renderer(ctx, {}, treatment_vars)

    # Step 2: brand_kit_renderer wants a doc with <head>. Wrap, inject,
    # then strip the scaffold.
    scaffolded = f"<html><head></head><body>{hero_html}</body></html>"
    try:
        from agents.design_intelligence.brand_kit_renderer import render_with_brand_kit
        scaffolded = render_with_brand_kit(scaffolded, business_id)
    except Exception as e:
        logger.warning(f"[render_pipeline] brand_kit inject failed: {e}")

    # Step 3: slot resolution.
    try:
        from agents.slot_system.slot_resolver import resolve_html_slots
        synthesized_slots = {
            slot_name: {"default_url": url, "custom_url": None}
            for slot_name, url in slot_resolutions.items()
        }
        scaffolded, _credits, _found = resolve_html_slots(
            scaffolded, synthesized_slots,
        )
    except Exception as e:
        logger.warning(f"[render_pipeline] slot resolve failed: {e}")

    # Step 4: text overrides.
    if apply_overrides:
        try:
            from agents.override_system.override_resolver import resolve_html_overrides
            scaffolded = resolve_html_overrides(scaffolded, business_id)
        except Exception as e:
            logger.warning(f"[render_pipeline] override resolve failed: {e}")

    return scaffolded


# ─── Standalone document wrapper ───────────────────────────────────

# Cathedral doc shell — Playfair Display + Outfit fonts
_CATHEDRAL_DOC_SHELL = """<!DOCTYPE html>
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
<div class="spike-banner">module: cathedral · variant: {variant} · treatments: {treatments}</div>
</body>
</html>"""

# Studio Brut doc shell — Druk/Bebas/Space Grotesk/Archivo Black/Inter
# + JetBrains Mono. Default fonts wired into --sb-display-stack /
# --sb-sans-stack / --sb-mono-stack which Studio Brut primitives read.
_STUDIO_BRUT_DOC_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo+Black&family=Bebas+Neue&family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;700&family=Space+Grotesk:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root {{
  --sb-display-stack: 'Archivo Black', 'Bebas Neue', 'Space Grotesk', 'Inter', system-ui, sans-serif;
  --sb-sans-stack: 'Inter', 'Space Grotesk', system-ui, -apple-system, sans-serif;
  --sb-mono-stack: 'JetBrains Mono', 'SF Mono', ui-monospace, monospace;
}}
html, body {{ margin: 0; padding: 0; font-family: var(--sb-sans-stack); color: var(--brand-text-primary, #09090B); background: var(--brand-warm-neutral, #F4F4F0); }}
.spike-banner {{
  position: fixed; bottom: 10px; right: 10px;
  background: rgba(0,0,0,0.85); color: #fff;
  font-family: ui-monospace, monospace; font-size: 11px;
  padding: 6px 10px; border-radius: 3px; z-index: 9999;
  pointer-events: none;
  letter-spacing: 0.3px;
}}
</style>
</head>
<body>
{hero_html}
<div class="spike-banner">module: studio_brut · variant: {variant} · treatments: {treatments}</div>
</body>
</html>"""


def _doc_shell_for(module_id: str) -> str:
    return (
        _STUDIO_BRUT_DOC_SHELL if module_id == "studio_brut"
        else _CATHEDRAL_DOC_SHELL
    )


def _strip_scaffold(html: str) -> str:
    """Pull the hero <section> back out of the <html><head></head>
    <body>...</body></html> scaffold from render_hero_fragment."""
    body_open = html.find("<body>")
    body_close = html.rfind("</body>")
    if body_open == -1 or body_close == -1 or body_close <= body_open:
        return html
    return html[body_open + len("<body>"):body_close].strip()


def render_hero_standalone(
    composition_dict: Dict[str, Any],
    business_id: str,
    module_id: str = "cathedral",
    *,
    apply_overrides: bool = True,
) -> str:
    """Render a standalone HTML5 document. Module-specific doc shell
    (font stack + spike banner) wraps the section; brand_kit
    injection runs on the final doc."""
    fragment_doc = render_hero_fragment(
        composition_dict, business_id, module_id,
        apply_overrides=apply_overrides,
    )
    hero_section = _strip_scaffold(fragment_doc)

    treatments = composition_dict.get("treatments") or {}
    treatments_label = (
        f"{treatments.get('color_emphasis', '?')} / "
        f"{treatments.get('spacing_density', '?')} / "
        f"{treatments.get('emphasis_weight', '?')}"
    )
    variant_id = composition_dict.get("variant", "?")
    title = f"{module_id} Hero spike — {business_id[:8]} · {variant_id}"

    doc = _doc_shell_for(module_id).format(
        title=title,
        hero_html=hero_section,
        variant=variant_id,
        treatments=treatments_label,
    )

    try:
        from agents.design_intelligence.brand_kit_renderer import render_with_brand_kit
        doc = render_with_brand_kit(doc, business_id)
    except Exception as e:
        logger.warning(f"[render_pipeline] doc-shell brand_kit inject failed: {e}")

    return doc


# ─── Spike-legacy compose_and_render (Cathedral-only) ─────────────

def compose_and_render(
    business_id: str,
    *,
    module_id: str = "cathedral",
    standalone: bool = True,
    apply_overrides: bool = True,
) -> Dict[str, Any]:
    """Phase 4/5 spike-era convenience helper preserved for backward
    compat. Fires the module-specific Composer + renders.

    Returns {business_id, composition, html}.

    Phase E callers should use compose_and_render_hero (which also
    runs the Module Router as the first step)."""
    from agents.composer.hero_composer import compose_hero
    comp_dict = compose_hero(business_id, module_id=module_id)

    renderer = render_hero_standalone if standalone else render_hero_fragment
    html = renderer(comp_dict, business_id, module_id, apply_overrides=apply_overrides)
    return {
        "business_id": business_id,
        "module_id": module_id,
        "composition": comp_dict,
        "html": html,
    }


# ─── Phase E end-to-end pipeline ───────────────────────────────────

def compose_and_render_hero(business_id: str) -> Dict[str, Any]:
    """Phase E full multi-module pipeline:

      1. Module Router decides cathedral vs studio_brut
      2. Module-specific Composer composes within that module
      3. Module-specific render produces HTML

    Returns:
      {
        business_id, module_id, routing_decision (full),
        composition (module-specific shape), html (standalone doc)
      }

    Soft-fails: any step's error propagates via the dict's
    _composer_metadata + _composer_error / _router_error fields rather
    than raising. The pipeline always returns SOMETHING renderable."""
    # Step 1: Module Router decides
    from agents.composer.module_router import route_module
    routing = route_module(business_id)
    module_id = routing.get("module_id", "cathedral")

    # Step 2: module-specific Composer
    from agents.composer.hero_composer import compose_hero
    composition = compose_hero(business_id, module_id=module_id)

    # Step 3: module-specific render (standalone HTML5 doc)
    html = render_hero_standalone(composition, business_id, module_id)

    return {
        "business_id": business_id,
        "module_id": module_id,
        "routing_decision": routing,
        "composition": composition,
        "html": html,
    }
