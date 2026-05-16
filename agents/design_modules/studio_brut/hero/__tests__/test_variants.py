"""Pass 4.0g Phase B — Studio Brut variant smoke tests.

Mirror Cathedral's test_variants.py structure: render each variant
with 3 different treatment tiers x 3 content fixtures = 9 renders per
variant; 11 variants total = 99 smoke renders.

Spot-check HTMLs written to %LOCALAPPDATA%/Temp/spike_studio_brut/
per variant for visual review at CHECKPOINT B. Key spot-check: each
variant rendered with RoyalTeez brand fixture (purple #6B46C1 +
amber #F59E0B) since the spike's CONDITIONAL GO verdict was driven
by RoyalTee not feeling distinct under Cathedral.

Run: python -m agents.design_modules.studio_brut.hero.__tests__.test_variants
"""
from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from typing import Dict

from agents.design_modules.studio_brut.hero.types import (
    BrandKitColors,
    HeroContent,
    IMAGE_USING_VARIANTS,
    RenderContext,
    StudioBrutHeroComposition,
    Treatments,
)
from agents.design_modules.studio_brut.hero.variants import VARIANT_REGISTRY
from agents.design_modules.studio_brut.hero.treatments import (
    color_emphasis_vars,
    spacing_density_vars,
    emphasis_weight_vars,
    background_treatment_vars,
    color_depth_vars,
    ornament_treatment_vars,
    typography_personality_vars,
    image_treatment_vars,
)


# ─── Brand fixtures ────────────────────────────────────────────────

# Studio Brut's canonical default palette (deep red + punch yellow)
SB_DEFAULTS = BrandKitColors(
    primary="#DC2626",   # red authority
    secondary="#18181B", # near-black
    accent="#FACC15",    # punch yellow signal
    background="#F4F4F0", # off-white warm-neutral
    text="#09090B",      # near-pure-black text
)

# RoyalTeez brand_kit as seen in production — the test case the
# spike's CONDITIONAL GO verdict turned on. Studio Brut's job is
# to make RoyalTee feel CREATIVE and distinct.
ROYALTEE_BRAND = BrandKitColors(
    primary="#6B46C1",   # royal purple
    secondary="#1F2937",
    accent="#F59E0B",    # amber
    background="#FAFAFA",
    text="#111827",
)

# KMJ Creative Solutions — black + yellow combo. Test Studio Brut on
# a creative-agency archetype that Cathedral handled OK in the spike
# but where Studio Brut might do better.
KMJ_BRAND = BrandKitColors(
    primary="#000000",
    secondary="#2C5282",
    accent="#FFDD00",
    background="#F7FAFC",
    text="#2D3748",
)


# ─── Content fixtures ──────────────────────────────────────────────

CONTENTS = [
    HeroContent(
        eyebrow="THE ROYAL COURT",
        heading="Wear your crown",
        heading_emphasis="crown",
        subtitle="Custom designs that command attention.",
        cta_primary="Start a design",
        cta_target="#design",
        image_slot_ref="hero_main",
    ),
    HeroContent(
        eyebrow="MADE LOUD",
        heading="Cut the noise, keep the signal",
        heading_emphasis="signal",
        subtitle="Branding for brands that mean it.",
        cta_primary="Drop a brief",
        cta_target="#brief",
        image_slot_ref="hero_main",
    ),
    HeroContent(
        eyebrow="STUDIO PRACTICE",
        heading="Work that earns its space",
        heading_emphasis="earns",
        subtitle="Design partnerships built on repeat work, not pitches.",
        cta_primary="Book a chair",
        cta_target="#book",
        image_slot_ref="hero_main",
    ),
]


# ─── Treatment tiers ───────────────────────────────────────────────

TREATMENTS = [
    # Restrained — Studio Brut at its quietest. Still no italic
    # emphasis (that's Cathedral) but minimal ornament, flat color.
    Treatments(
        color_emphasis="signal_dominant", spacing_density="generous", emphasis_weight="heading_dominant",
        background="flat",          color_depth="flat",
        ornament="minimal",         typography="editorial", image_treatment="clean",
    ),
    # Mid — depth-aware, signature ornament density, bold typography
    # (Studio Brut's typography=bold = weight 900 + UPPERCASE).
    Treatments(
        color_emphasis="dual_emphasis", spacing_density="standard", emphasis_weight="balanced",
        background="soft_gradient", color_depth="gradient_accents",
        ornament="signature",        typography="bold", image_treatment="filtered",
    ),
    # Maxed — Studio Brut at its loudest. Heavy ornament density,
    # playful typography (scale + color emphasis combined), dramatic
    # image treatment.
    Treatments(
        color_emphasis="authority_dominant", spacing_density="compact", emphasis_weight="eyebrow_dominant",
        background="textured",       color_depth="radial_glows",
        ornament="heavy",            typography="playful", image_treatment="dramatic",
    ),
]


SLOT_RESOLUTIONS = {
    "hero_main": "https://images.unsplash.com/photo-1521577352947-9bb58764b69a?auto=format&fit=crop&w=1600&q=80",
}


# ─── Validation ────────────────────────────────────────────────────

class HTMLValidator(HTMLParser):
    """Track tag balance + collect override-target paths."""

    def __init__(self):
        super().__init__()
        self.override_targets = []
        self.has_section_root = False
        # Studio Brut anti-pattern detector: no diamond classes should
        # appear in any variant output.
        self.diamond_offenses = []
        # Italic emphasis detector: heading-emphasis spans should
        # NEVER carry font-style: italic at the heading level.
        self.italic_offenses = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "") or ""
        if tag == "section" and attrs_dict.get("data-section") == "hero":
            self.has_section_root = True
        if "data-override-target" in attrs_dict:
            self.override_targets.append(attrs_dict["data-override-target"])
        if "diamond" in cls.lower():
            self.diamond_offenses.append(cls)
        # Italic check: heading element with italic style is a Cathedral
        # signature Studio Brut must never use. Spans WITHIN the heading
        # carry their own check; we only flag the <h1> here.
        if tag == "h1":
            style = (attrs_dict.get("style") or "")
            if "font-style: italic" in style:
                self.italic_offenses.append(f"h1 italic: {style[:80]}")


def assert_variant_output(variant_id: str, html: str):
    v = HTMLValidator()
    v.feed(html)
    assert v.has_section_root, f"{variant_id}: no <section data-section=hero>"
    assert len(v.override_targets) >= 5, (
        f"{variant_id}: only {len(v.override_targets)} override targets, expected >=5"
    )
    required = ["hero.eyebrow", "hero.heading", "hero.heading_emphasis", "hero.subtitle", "hero.cta_primary"]
    for path in required:
        assert path in v.override_targets, f"{variant_id}: missing target {path!r}"
    # Studio Brut DNA gates
    assert not v.diamond_offenses, (
        f"{variant_id}: diamond class found (Cathedral signature, banned): {v.diamond_offenses}"
    )
    assert not v.italic_offenses, (
        f"{variant_id}: italic on <h1> (Cathedral pattern, banned): {v.italic_offenses}"
    )
    assert "var(--brand-" in html, f"{variant_id}: no var(--brand-*) reference"
    # Cross-module gate: no --ca-* vars should leak into Studio Brut output
    assert "--ca-" not in html, f"{variant_id}: Cathedral --ca-* var leaked into Studio Brut output"
    return v


# ─── Spot-check doc shell ──────────────────────────────────────────

DOC_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Studio Brut variant {idx} — {variant_id}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo+Black&family=Bebas+Neue&family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;700&family=Space+Grotesk:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root {{
  --brand-authority: {primary};
  --brand-deep-secondary: {secondary};
  --brand-secondary: {secondary};
  --brand-signal: {accent};
  --brand-warm-neutral: {background};
  --brand-text-primary: {text};
  --brand-text-on-authority: #FFFFFF;
  --brand-text-on-signal: #09090B;
  --sb-display-stack: 'Archivo Black', 'Bebas Neue', 'Space Grotesk', 'Inter', system-ui, sans-serif;
  --sb-sans-stack: 'Inter', 'Space Grotesk', system-ui, -apple-system, sans-serif;
  --sb-mono-stack: 'JetBrains Mono', 'SF Mono', ui-monospace, monospace;
}}
html, body {{ margin: 0; padding: 0; font-family: var(--sb-sans-stack); }}
.spike-label {{
  position: fixed; top: 8px; right: 8px;
  background: rgba(0,0,0,0.82); color: #fff;
  font-family: ui-monospace, monospace; font-size: 11px;
  padding: 6px 10px; border-radius: 3px; z-index: 9999;
  pointer-events: none;
}}
</style>
</head>
<body>
<div class="spike-label">SB #{idx}: {variant_id} | brand: {brand_label}<br>treatment: {treatments_label}</div>
{hero_html}
</body>
</html>"""


def _build_treatment_vars(t: Treatments) -> Dict[str, str]:
    out: Dict[str, str] = {}
    out.update(color_emphasis_vars(t.color_emphasis))
    out.update(spacing_density_vars(t.spacing_density))
    out.update(emphasis_weight_vars(t.emphasis_weight))
    out.update(background_treatment_vars(t.background))
    out.update(color_depth_vars(t.color_depth))
    out.update(ornament_treatment_vars(t.ornament))
    out.update(typography_personality_vars(t.typography))
    out.update(image_treatment_vars(t.image_treatment))
    return out


def _render(variant_id: str, brand: BrandKitColors, content: HeroContent,
            treatments: Treatments) -> str:
    """Render a single (variant, brand, content, treatments) combo."""
    comp = StudioBrutHeroComposition(
        variant=variant_id, treatments=treatments, content=content,
        reasoning="smoke test render",
    )
    if variant_id in IMAGE_USING_VARIANTS:
        comp.content.image_slot_ref = "hero_main"
    else:
        comp.content.image_slot_ref = None
    ctx = RenderContext(
        composition=comp, brand_kit=brand,
        business_id="smoke", slot_resolutions=SLOT_RESOLUTIONS,
    )
    return VARIANT_REGISTRY[variant_id](ctx, {}, _build_treatment_vars(treatments))


def _spot_check(variant_id: str, idx: int, brand: BrandKitColors,
                content: HeroContent, treatments: Treatments,
                brand_label: str, output_path: str):
    hero_html = _render(variant_id, brand, content, treatments)
    treatments_label = (
        f"{treatments.color_emphasis} / {treatments.spacing_density} / "
        f"{treatments.emphasis_weight} | "
        f"bg:{treatments.background} | color:{treatments.color_depth} | "
        f"orn:{treatments.ornament} | type:{treatments.typography} | "
        f"img:{treatments.image_treatment}"
    )
    doc = DOC_TEMPLATE.format(
        idx=idx, variant_id=variant_id,
        primary=brand.primary, secondary=brand.secondary,
        accent=brand.accent, background=brand.background, text=brand.text,
        brand_label=brand_label, treatments_label=treatments_label,
        hero_html=hero_html,
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(doc)


VARIANT_LIST = [
    ("color_block_split",   1),
    ("oversize_statement",  2),
    ("diagonal_band",       3),
    ("stacked_blocks",      4),
    ("edge_bleed_portrait", 5),
    ("type_collage",        6),
    ("layered_card",        7),
    ("stat_strip",          8),
    ("massive_letterform",  9),
    ("double_split",       10),
    ("rotated_anchor",     11),
]


# ─── Phase C per-dimension coverage assertions ──────────────────────

def assert_dimension_coverage(variant_id: str, treatments: Treatments, html: str):
    """Per-dimension coverage check — for each treatment option, the
    distinguishing CSS variable assignment MUST appear in the section's
    inline style. Catches treatment translator regressions where a
    dimension's output silently degrades to the default no-op.

    Strategy: check for the literal CSS variable ASSIGNMENT string
    (e.g. `--sb-bg-image: linear-gradient...`), not the resolved CSS
    property usage. The translator's job is to emit the var; the
    primitive's job is to consume it. This test only verifies the
    translator side. The cross-module isolation gate + DNA gates in
    assert_variant_output verify the primitive side."""

    # ─── background_treatment ───
    if treatments.background == "soft_gradient":
        assert "linear-gradient(135deg" in html, (
            f"{variant_id}: background=soft_gradient missing 135deg gradient assignment"
        )
    if treatments.background == "textured":
        assert "data:image/svg+xml" in html, (
            f"{variant_id}: background=textured missing SVG data URI assignment"
        )
    if treatments.background == "vignette":
        assert "radial-gradient(ellipse at center" in html, (
            f"{variant_id}: background=vignette missing radial-gradient assignment"
        )

    # ─── color_depth ───
    if treatments.color_depth == "gradient_accents":
        # The translator emits `--sb-emphasis-bg-clip: text` AND
        # `--sb-emphasis-bg: linear-gradient(135deg, ...)`. Both must
        # appear in the section style for gradient_accents to fire.
        assert "--sb-emphasis-bg-clip: text" in html, (
            f"{variant_id}: color_depth=gradient_accents missing "
            f"--sb-emphasis-bg-clip: text assignment"
        )
        assert "--sb-emphasis-text-fill: transparent" in html, (
            f"{variant_id}: color_depth=gradient_accents missing "
            f"--sb-emphasis-text-fill: transparent assignment"
        )
    if treatments.color_depth == "radial_glows":
        # `--sb-emphasis-glow` non-`none` value (matches the saturated
        # glow string from the translator).
        assert "--sb-emphasis-glow: 0 0 32px" in html, (
            f"{variant_id}: color_depth=radial_glows missing "
            f"--sb-emphasis-glow saturated assignment"
        )
        assert "--sb-ornament-glow: drop-shadow" in html, (
            f"{variant_id}: color_depth=radial_glows missing "
            f"--sb-ornament-glow drop-shadow assignment"
        )

    # ─── ornament ───
    if treatments.ornament == "heavy":
        sat_count = html.count("hero.sat_")
        assert sat_count == 6, (
            f"{variant_id}: ornament=heavy expected 6 satellites, found {sat_count}"
        )
    if treatments.ornament == "minimal":
        # Multiplier should land at 0.7 / 0.85 (Studio Brut minimal)
        assert "--sb-ornament-opacity-mult: 0.7" in html, (
            f"{variant_id}: ornament=minimal missing 0.7 opacity multiplier"
        )

    # ─── typography → emphasis-mode wiring ───
    expected_mode = {
        "editorial": "color",
        "bold": "weight",
        "refined": "scale",
        "playful": "scale_color",
    }[treatments.typography]
    assert f'data-emphasis-mode="{expected_mode}"' in html, (
        f"{variant_id}: typography={treatments.typography} expected "
        f"emphasis-mode={expected_mode} on heading-emphasis span"
    )
    # Typography also drives heading case for `bold`
    if treatments.typography == "bold":
        assert "--sb-heading-case: uppercase" in html, (
            f"{variant_id}: typography=bold missing uppercase case assignment"
        )

    # ─── image_treatment ─── (only for image-using variants)
    if variant_id in IMAGE_USING_VARIANTS:
        if treatments.image_treatment == "filtered":
            assert "--sb-image-filter: saturate(0.85)" in html, (
                f"{variant_id}: image_treatment=filtered missing saturate(0.85)"
            )
            assert "--sb-image-overlay" in html and "12%" in html, (
                f"{variant_id}: image_treatment=filtered missing 12% signal overlay"
            )
        if treatments.image_treatment == "dramatic":
            assert "--sb-image-filter: saturate(1.2)" in html, (
                f"{variant_id}: image_treatment=dramatic missing saturate(1.2)"
            )
            assert "--sb-image-overlay" in html and "22%" in html, (
                f"{variant_id}: image_treatment=dramatic missing 22% authority overlay"
            )
        if treatments.image_treatment == "soft":
            assert "--sb-image-mask: radial-gradient" in html, (
                f"{variant_id}: image_treatment=soft missing radial mask"
            )


# ─── Three-tier overview page (Phase C CHECKPOINT C surface) ────────

TIER_LABELS = ["restrained", "mid", "rich"]


TIER_OVERVIEW_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Studio Brut — {tier_label} treatment tier</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo+Black&family=Bebas+Neue&family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;700&family=Space+Grotesk:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root {{
  --brand-authority: {primary};
  --brand-deep-secondary: {secondary};
  --brand-secondary: {secondary};
  --brand-signal: {accent};
  --brand-warm-neutral: {background};
  --brand-text-primary: {text};
  --brand-text-on-authority: #FFFFFF;
  --brand-text-on-signal: #09090B;
  --sb-display-stack: 'Archivo Black', 'Bebas Neue', 'Space Grotesk', 'Inter', system-ui, sans-serif;
  --sb-sans-stack: 'Inter', 'Space Grotesk', system-ui, -apple-system, sans-serif;
  --sb-mono-stack: 'JetBrains Mono', 'SF Mono', ui-monospace, monospace;
}}
*, *::before, *::after {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; font-family: var(--sb-sans-stack); background: #0F172A; color: #E2E8F0; }}
.tier-header {{
  position: sticky; top: 0; z-index: 50;
  padding: 22px 32px;
  background: rgba(15, 23, 42, 0.94);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid #1E293B;
}}
.tier-header h1 {{ margin: 0 0 4px; font-size: 20px; font-weight: 700; letter-spacing: -0.3px; }}
.tier-header .meta {{ color: #94A3B8; font-size: 13px; }}
.tier-header code {{ background: #1E293B; padding: 2px 6px; border-radius: 3px; font-family: ui-monospace, monospace; font-size: 12px; }}
.variant-block {{
  border-bottom: 1px solid #1E293B;
  padding: 24px 32px;
  background: #0F172A;
}}
.variant-block h2 {{
  margin: 0 0 12px;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: -0.2px;
  color: #F1F5F9;
}}
.variant-block h2 small {{ color: #94A3B8; font-weight: 400; margin-left: 8px; font-size: 12px; }}
.variant-shell {{
  background: #fff;
  border-radius: 6px;
  overflow: hidden;
  box-shadow: 0 6px 18px rgba(0,0,0,0.4);
}}
.variant-shell iframe {{
  width: 100%;
  border: none;
  display: block;
  background: #fff;
  /* Studio Brut hero minimum-heights run 540-720px; iframe sized
     for the largest. */
  height: 760px;
}}
</style>
</head>
<body>
<header class="tier-header">
  <h1>Studio Brut — <code>{tier_label}</code> treatment tier</h1>
  <p class="meta">All 11 variants rendered with RoyalTeez brand (purple authority + amber signal) at the {tier_label} treatment tier.<br>
  Treatment fingerprint: <code>{tier_fingerprint}</code></p>
</header>

{variant_blocks}

</body>
</html>"""


def _render_tier_overview(tier_idx: int, brand: BrandKitColors,
                         brand_label: str, content: HeroContent,
                         output_path: str):
    """Build a single tier-overview page with all 11 variants stacked
    at the specified treatment tier (0=restrained, 1=mid, 2=rich).
    Each variant renders inside an iframe srcdoc so CSS scopes are
    isolated per variant."""
    treatments = TREATMENTS[tier_idx]
    tier_label = TIER_LABELS[tier_idx]
    tier_fingerprint = (
        f"{treatments.color_emphasis} / {treatments.spacing_density} / "
        f"{treatments.emphasis_weight} | bg:{treatments.background} | "
        f"color:{treatments.color_depth} | orn:{treatments.ornament} | "
        f"type:{treatments.typography} | img:{treatments.image_treatment}"
    )

    blocks = []
    for variant_id, idx in VARIANT_LIST:
        hero_html = _render(variant_id, brand, content, treatments)
        # Wrap each hero in its own minimal doc so the iframe srcdoc
        # carries fonts + CSS vars per variant.
        variant_doc = DOC_TEMPLATE.format(
            idx=idx, variant_id=variant_id,
            primary=brand.primary, secondary=brand.secondary,
            accent=brand.accent, background=brand.background, text=brand.text,
            brand_label=brand_label,
            treatments_label=f"{tier_label} tier",
            hero_html=hero_html,
        )
        # HTML-escape for srcdoc attribute value (need &quot; for inner ")
        import html as html_lib
        srcdoc = html_lib.escape(variant_doc, quote=True)
        blocks.append(
            f'<section class="variant-block" id="v{idx:02d}">'
            f'  <h2>#{idx:02d} {variant_id} <small>({tier_label} tier)</small></h2>'
            f'  <div class="variant-shell">'
            f'    <iframe srcdoc="{srcdoc}" loading="lazy" '
            f'sandbox="allow-same-origin" title="{variant_id} — {tier_label}"></iframe>'
            f'  </div>'
            f'</section>'
        )

    doc = TIER_OVERVIEW_SHELL.format(
        tier_label=tier_label,
        tier_fingerprint=tier_fingerprint,
        primary=brand.primary, secondary=brand.secondary,
        accent=brand.accent, background=brand.background, text=brand.text,
        variant_blocks="\n".join(blocks),
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(doc)


def main():
    print("=== Studio Brut variant smoke tests + Phase C coverage ===")

    # Smoke pass — 11 variants x 3 treatments x 3 contents = 99 renders.
    # Phase C addition: assert_dimension_coverage on each render too.
    total = 0
    for variant_id, _ in VARIANT_LIST:
        for t in TREATMENTS:
            for c in CONTENTS:
                html = _render(variant_id, ROYALTEE_BRAND, c, t)
                assert_variant_output(variant_id, html)
                assert_dimension_coverage(variant_id, t, html)
                total += 1
        print(f"  {variant_id}: 9 renders OK (3 treatments x 3 contents)")
    print(f"\nTotal smoke renders: {total} (each passes assert_variant_output +")
    print(f"assert_dimension_coverage Phase C gates)")

    # Spot-check pass — each variant rendered with RoyalTee brand
    # (the spike's failing case) at the MID treatment tier, plus a
    # few selected variants at the maxed treatment tier with KMJ
    # brand to show range.
    out_dir = os.path.join(
        os.environ.get("LOCALAPPDATA", "/tmp"),
        "Temp" if os.name == "nt" else "",
        "spike_studio_brut",
    )
    os.makedirs(out_dir, exist_ok=True)
    print(f"\n=== Writing spot-check HTML to {out_dir} ===")

    # All 11 variants with RoyalTee brand + mid treatment (depth-aware
    # but not maxed). This is the headline visual review surface for
    # CHECKPOINT B.
    for variant_id, idx in VARIANT_LIST:
        path = os.path.join(out_dir, f"sb_variant_{idx:02d}_{variant_id}_royaltee.html")
        _spot_check(
            variant_id, idx, ROYALTEE_BRAND, CONTENTS[0],
            TREATMENTS[1],  # mid treatment tier
            "RoyalTeez (purple/amber)",
            path,
        )
        print(f"  -> {path}")

    # Bonus: same 11 variants with Studio Brut's CANONICAL DEFAULTS
    # (red + yellow + near-black) so reviewers can see the module's
    # DNA palette without practitioner brand_kit overrides.
    for variant_id, idx in VARIANT_LIST:
        path = os.path.join(out_dir, f"sb_variant_{idx:02d}_{variant_id}_defaults.html")
        _spot_check(
            variant_id, idx, SB_DEFAULTS, CONTENTS[1],
            TREATMENTS[1],  # mid treatment tier
            "SB defaults (red/yellow/near-black)",
            path,
        )
        print(f"  -> {path}")

    # Phase C addition — three tier-overview pages. Each page renders
    # all 11 variants stacked vertically at one treatment tier with
    # the RoyalTee brand. Reviewer scans top-to-bottom to compare
    # treatment impact across the variant family.
    print(f"\n=== Phase C: 3 tier-overview pages ===")
    for tier_idx in (0, 1, 2):
        path = os.path.join(out_dir, f"sb_tier_{TIER_LABELS[tier_idx]}_overview_royaltee.html")
        _render_tier_overview(
            tier_idx, ROYALTEE_BRAND, "RoyalTeez (purple/amber)",
            CONTENTS[0], path,
        )
        print(f"  -> {path}")

    # Also generate one tier-overview at the rich tier with Studio Brut
    # defaults so reviewers can see the module's canonical palette at
    # peak depth.
    path = os.path.join(out_dir, "sb_tier_rich_overview_defaults.html")
    _render_tier_overview(
        2, SB_DEFAULTS, "SB defaults (red/yellow/near-black)",
        CONTENTS[1], path,
    )
    print(f"  -> {path}")

    print(f"\nOpen the *_overview_*.html files to verify treatment dimensions")
    print(f"carry visible weight across the variant family. Compare the same")
    print(f"variant across restrained/mid/rich tiers to see depth-equipped")
    print(f"differentiation in action.")


if __name__ == "__main__":
    main()
