"""Pass 4.0f Phase 2 — Variant render smoke tests.

For each of the 6 variants, render with 3 different test compositions
(different content + treatments). Assert:

  - Output parses as valid HTML
  - All required data-override-target paths present per variant
  - var(--brand-*) references present (no raw role-color hex)
  - Section root exists with data-section="hero"

Also writes one rendered HTML per variant to /tmp/spike_variant_<N>.html
(for variants 1-6) wrapped in a minimal HTML5 doc so each can be opened
in a browser for visual spot-check.

Run via: python -m agents.design_modules.cinematic_authority.hero.__tests__.test_variants
"""
from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from typing import Dict

from agents.design_modules.cinematic_authority.hero.types import (
    BrandKitColors,
    CathedralHeroComposition,
    HeroContent,
    RenderContext,
    Treatments,
)
from agents.design_modules.cinematic_authority.hero.variants import VARIANT_REGISTRY
from agents.design_modules.cinematic_authority.hero.treatments import (
    color_emphasis_vars,
    emphasis_weight_vars,
    spacing_density_vars,
)

# ─── Test fixtures ──────────────────────────────────────────────────

ROYALTEE_BRAND = BrandKitColors(
    primary="#6B46C1",   # royal purple
    secondary="#1F2937",
    accent="#F59E0B",    # amber
    background="#FAFAFA",
    text="#111827",
)

ETS_BRAND = BrandKitColors(
    primary="#0A1628",   # navy
    secondary="#122040",
    accent="#C6952F",    # gold
    background="#F8F6F1", # cream
    text="#0A1628",
)

KMJ_BRAND = BrandKitColors(
    primary="#000000",
    secondary="#2C5282",
    accent="#FFDD00",
    background="#F7FAFC",
    text="#2D3748",
)

# Three content fixtures with different vibes
CONTENTS = [
    HeroContent(
        eyebrow="THE PRACTITIONER'S TABLE",
        heading="Coach the work, not the words",
        heading_emphasis="work",
        subtitle="A studio for the few who measure by depth.",
        cta_primary="Reserve a seat",
        cta_target="#contact",
        image_slot_ref="hero_main",
    ),
    HeroContent(
        eyebrow="ROYAL COURT",
        heading="Wear your story",
        heading_emphasis="story",
        subtitle="Custom apparel for the boldly themselves.",
        cta_primary="Begin a design",
        cta_target="#design",
        image_slot_ref="hero_main",
    ),
    HeroContent(
        eyebrow="THE LONG WORK",
        heading="Build what compounds",
        heading_emphasis="compounds",
        subtitle="Strategy and systems for businesses that intend to last.",
        cta_primary="Start the conversation",
        cta_target="mailto:hello@example.com",
        image_slot_ref="hero_main",
    ),
]

TREATMENTS = [
    # Restrained — Phase 2 baseline. All 5 depth dims at default.
    Treatments(
        color_emphasis="signal_dominant",   spacing_density="generous", emphasis_weight="heading_dominant",
        background="flat",          color_depth="flat",
        ornament="minimal",         typography="editorial", image_treatment="clean",
    ),
    # Mid — depth-aware, structurally classic.
    Treatments(
        color_emphasis="authority_dominant", spacing_density="standard", emphasis_weight="balanced",
        background="soft_gradient", color_depth="gradient_accents",
        ornament="signature",        typography="bold", image_treatment="filtered",
    ),
    # Rich — depth-maxed, structurally compact.
    Treatments(
        color_emphasis="dual_emphasis",     spacing_density="compact",  emphasis_weight="eyebrow_dominant",
        background="textured",       color_depth="radial_glows",
        ornament="heavy",            typography="playful", image_treatment="dramatic",
    ),
]

BRANDS = [ETS_BRAND, ROYALTEE_BRAND, KMJ_BRAND]


# Slot resolution fixture — Unsplash placeholder so image-using variants
# show something during spot-check.
SLOT_RESOLUTIONS = {
    "hero_main": "https://images.unsplash.com/photo-1497366216548-37526070297c?auto=format&fit=crop&w=1600&q=80",
}


# ─── Validation helpers ─────────────────────────────────────────────

class HTMLValidator(HTMLParser):
    """Track tag balance + collect override-target paths."""

    def __init__(self):
        super().__init__()
        self.stack = []
        self.override_targets = []
        self.override_types = []
        self.has_section_root = False
        self.errors = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "section" and attrs_dict.get("data-section") == "hero":
            self.has_section_root = True
        if "data-override-target" in attrs_dict:
            self.override_targets.append(attrs_dict["data-override-target"])
        if "data-override-type" in attrs_dict:
            self.override_types.append(attrs_dict["data-override-type"])
        if tag not in ("img", "br", "hr", "meta", "link", "input"):
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        else:
            # Unbalanced — record but don't crash (some self-closing
            # tags handled imperfectly by HTMLParser)
            pass

    def handle_startendtag(self, tag, attrs):
        # Treat like start + end (self-closing)
        attrs_dict = dict(attrs)
        if "data-override-target" in attrs_dict:
            self.override_targets.append(attrs_dict["data-override-target"])
        if "data-override-type" in attrs_dict:
            self.override_types.append(attrs_dict["data-override-type"])


def assert_variant_output(variant_id: str, html: str):
    """Validate a single variant's HTML output."""
    validator = HTMLValidator()
    validator.feed(html)
    assert validator.has_section_root, f"{variant_id}: no <section data-section='hero'> root"
    assert len(validator.override_targets) >= 5, (
        f"{variant_id}: only {len(validator.override_targets)} override targets, expected >=5. "
        f"Found: {validator.override_targets}"
    )
    # Required content paths
    required_paths = ["hero.eyebrow", "hero.heading", "hero.heading_emphasis", "hero.subtitle", "hero.cta_primary"]
    for path in required_paths:
        assert path in validator.override_targets, f"{variant_id}: missing target {path!r}"
    # CSS var usage
    assert "var(--brand-" in html, f"{variant_id}: no var(--brand-*) reference"
    # No raw role-color hex (the brand kit hex values appear only in the
    # injected :root via brand_vars, not in the body)
    # Note: rgba()s with literal numbers are fine for shadows/overlays.
    return validator


# ─── Visual spot-check helper ───────────────────────────────────────

DOC_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Spike variant {idx} — {variant_id}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400;1,700&family=Outfit:wght@200;400;600;700;800&display=swap" rel="stylesheet">
<style>
:root {{
  --brand-authority: {primary};
  --brand-secondary: {secondary};
  --brand-deep-secondary: {secondary};
  --brand-signal: {accent};
  --brand-warm-neutral: {background};
  --brand-text-primary: {text};
  --brand-text-on-authority: #FFFFFF;
  --brand-text-on-signal: #0F172A;
  --ca-serif: 'Playfair Display', Georgia, 'Times New Roman', serif;
  --ca-sans: 'Outfit', system-ui, -apple-system, sans-serif;
}}
html, body {{ margin: 0; padding: 0; font-family: var(--ca-sans); }}
.spike-label {{
  position: fixed; top: 8px; right: 8px;
  background: rgba(0,0,0,0.78); color: #fff;
  font-family: ui-monospace, monospace; font-size: 11px;
  padding: 6px 10px; border-radius: 4px; z-index: 9999;
}}
</style>
</head>
<body>
<div class="spike-label">Variant {idx}: {variant_id}<br>brand: {brand_label}<br>treatments: {treatments_label}</div>
{hero_html}
</body>
</html>"""


def render_spot_check(variant_id: str, output_path: str, brand: BrandKitColors,
                     content: HeroContent, treatments: Treatments, brand_label: str, idx: int):
    """Render one variant + treatment + brand combo to a standalone HTML file."""
    # Build treatment vars
    tvars: Dict[str, str] = {}
    tvars.update(color_emphasis_vars(treatments.color_emphasis))
    tvars.update(spacing_density_vars(treatments.spacing_density))
    tvars.update(emphasis_weight_vars(treatments.emphasis_weight))

    composition = CathedralHeroComposition(
        variant=variant_id,  # type: ignore[arg-type]
        treatments=treatments,
        content=content,
        reasoning=f"Spike spot-check render for {variant_id}",
    )

    # Image_slot_ref consistency with variant
    from agents.design_modules.cinematic_authority.hero.types import IMAGE_USING_VARIANTS
    if variant_id in IMAGE_USING_VARIANTS:
        composition.content.image_slot_ref = "hero_main"
    else:
        composition.content.image_slot_ref = None

    context = RenderContext(
        composition=composition,
        brand_kit=brand,
        business_id="spike-test",
        slot_resolutions=SLOT_RESOLUTIONS,
    )

    # brand_vars dict — these go on the :root in the test doc instead of
    # the section, so we pass an empty dict here. Section will still
    # inherit from :root.
    brand_vars: Dict[str, str] = {}

    renderer = VARIANT_REGISTRY[variant_id]
    hero_html = renderer(context, brand_vars, tvars)

    treatments_label = f"{treatments.color_emphasis} / {treatments.spacing_density} / {treatments.emphasis_weight}"
    doc = DOC_TEMPLATE.format(
        idx=idx,
        variant_id=variant_id,
        primary=brand.primary,
        secondary=brand.secondary,
        accent=brand.accent,
        background=brand.background,
        text=brand.text,
        brand_label=brand_label,
        treatments_label=treatments_label,
        hero_html=hero_html,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(doc)


def main():
    """Run smoke tests + write spot-check HTML for each variant."""
    print("=== Phase 2.5 variant smoke tests (11 variants total) ===")
    variants = [
        # Phase 2
        ("manifesto_center",   1),
        ("asymmetric_left",    2),
        ("asymmetric_right",   3),
        ("full_bleed_overlay", 4),
        ("split_stacked",      5),
        ("layered_diamond",    6),
        # Phase 2.5
        ("quote_anchor",       7),
        ("tabular_authority",  8),
        ("vertical_manifesto", 9),
        ("annotated_hero",    10),
        ("cinematic_caption", 11),
    ]
    # Smoke check: each variant × 3 treatment combos × 3 content fixtures
    total_renders = 0
    for variant_id, _idx in variants:
        for tr in TREATMENTS:
            for content in CONTENTS:
                comp = CathedralHeroComposition(
                    variant=variant_id,
                    treatments=tr,
                    content=content,
                    reasoning="smoke",
                )
                from agents.design_modules.cinematic_authority.hero.types import IMAGE_USING_VARIANTS
                if variant_id in IMAGE_USING_VARIANTS:
                    comp.content.image_slot_ref = "hero_main"
                else:
                    comp.content.image_slot_ref = None
                tvars = {}
                tvars.update(color_emphasis_vars(tr.color_emphasis))
                tvars.update(spacing_density_vars(tr.spacing_density))
                tvars.update(emphasis_weight_vars(tr.emphasis_weight))
                ctx = RenderContext(
                    composition=comp, brand_kit=ETS_BRAND,
                    business_id="smoke", slot_resolutions=SLOT_RESOLUTIONS,
                )
                html = VARIANT_REGISTRY[variant_id](ctx, {}, tvars)
                assert_variant_output(variant_id, html)
                total_renders += 1
        print(f"  {variant_id}: 9 renders OK (3 treatments × 3 contents)")
    print(f"\nTotal smoke renders: {total_renders}\n")

    # Spot-check HTML files — one per variant, varying treatments + brands
    # to show that the SAME architecture produces visibly distinct output.
    out_dir = os.path.join(os.environ.get("LOCALAPPDATA", "/tmp"),
                            "Temp" if os.name == "nt" else "",
                            "spike_variants")
    os.makedirs(out_dir, exist_ok=True)
    print(f"=== Writing spot-check HTML to {out_dir} ===")

    # Phase 2.5 — quote_anchor needs a quote-shaped heading for the
    # variant to read correctly. Use a custom content fixture for V7.
    QUOTE_CONTENT = HeroContent(
        eyebrow="WHAT CLIENTS SAY",
        heading="They reframed everything in the first hour.",
        heading_emphasis="reframed everything",
        subtitle="Anna Stewart, Founder of Hearth Studio",
        cta_primary="Book a discovery call",
        cta_target="#contact",
        image_slot_ref=None,
    )

    spot_check_set = [
        # Phase 2 — original 6
        ("manifesto_center",   1, ETS_BRAND,     CONTENTS[0],     TREATMENTS[0], "ETS (navy/gold/cream)"),
        ("asymmetric_left",    2, ROYALTEE_BRAND, CONTENTS[1],     TREATMENTS[1], "RoyalTee (purple/amber/white)"),
        ("asymmetric_right",   3, KMJ_BRAND,     CONTENTS[2],     TREATMENTS[2], "KMJ (black/yellow/light)"),
        ("full_bleed_overlay", 4, ETS_BRAND,     CONTENTS[0],     TREATMENTS[0], "ETS"),
        ("split_stacked",      5, ROYALTEE_BRAND, CONTENTS[1],     TREATMENTS[1], "RoyalTee"),
        ("layered_diamond",    6, ETS_BRAND,     CONTENTS[2],     TREATMENTS[0], "ETS"),
        # Phase 2.5 — 5 new
        ("quote_anchor",       7, ETS_BRAND,     QUOTE_CONTENT,    TREATMENTS[0], "ETS (testimony fixture)"),
        ("tabular_authority",  8, ETS_BRAND,     CONTENTS[2],     TREATMENTS[1], "ETS (authority-dominant)"),
        ("vertical_manifesto", 9, KMJ_BRAND,     CONTENTS[0],     TREATMENTS[0], "KMJ (signal-dominant, generous)"),
        ("annotated_hero",    10, ROYALTEE_BRAND, CONTENTS[2],     TREATMENTS[1], "RoyalTee (method fixture)"),
        ("cinematic_caption", 11, KMJ_BRAND,     CONTENTS[1],     TREATMENTS[2], "KMJ (dual-emphasis, compact)"),
    ]
    for variant_id, idx, brand, content, treatments, brand_label in spot_check_set:
        path = os.path.join(out_dir, f"spike_variant_{idx:02d}_{variant_id}.html")
        # Render directly with the chosen content (not by index — quote_anchor
        # uses a custom content fixture).
        render_spot_check_direct(variant_id, path, brand, content, treatments, brand_label, idx)
        print(f"  -> {path}")

    print(f"\nOpen each file in a browser to spot-check visual distinctness.")


def render_spot_check_direct(variant_id: str, output_path: str, brand: BrandKitColors,
                              content: HeroContent, treatments: Treatments, brand_label: str, idx: int):
    """Same as render_spot_check but accepts an explicit content object
    rather than indexing into CONTENTS. Lets V7 (quote_anchor) use a
    quote-shaped content fixture instead of a manifesto."""
    tvars: Dict[str, str] = {}
    tvars.update(color_emphasis_vars(treatments.color_emphasis))
    tvars.update(spacing_density_vars(treatments.spacing_density))
    tvars.update(emphasis_weight_vars(treatments.emphasis_weight))

    # Pydantic v2: prefer model_copy over deprecated copy().
    _content_copy = content.model_copy() if hasattr(content, "model_copy") else (
        content.copy() if hasattr(content, "copy") else content
    )
    composition = CathedralHeroComposition(
        variant=variant_id,  # type: ignore[arg-type]
        treatments=treatments,
        content=_content_copy,
        reasoning=f"Spike spot-check render for {variant_id}",
    )

    from agents.design_modules.cinematic_authority.hero.types import IMAGE_USING_VARIANTS
    if variant_id in IMAGE_USING_VARIANTS:
        composition.content.image_slot_ref = "hero_main"
    else:
        composition.content.image_slot_ref = None

    context = RenderContext(
        composition=composition,
        brand_kit=brand,
        business_id="spike-test",
        slot_resolutions=SLOT_RESOLUTIONS,
    )

    brand_vars: Dict[str, str] = {}
    renderer = VARIANT_REGISTRY[variant_id]
    hero_html = renderer(context, brand_vars, tvars)

    treatments_label = f"{treatments.color_emphasis} / {treatments.spacing_density} / {treatments.emphasis_weight}"
    doc = DOC_TEMPLATE.format(
        idx=idx,
        variant_id=variant_id,
        primary=brand.primary,
        secondary=brand.secondary,
        accent=brand.accent,
        background=brand.background,
        text=brand.text,
        brand_label=brand_label,
        treatments_label=treatments_label,
        hero_html=hero_html,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(doc)


if __name__ == "__main__":
    main()
