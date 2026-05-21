"""Pass 4.0i Phase B — creative expression smoke tests.

Three test surfaces:

  1. Intensity × variant rubric matrix (the load-bearing test)
     For each (variant, intensity) — 11 × 3 = 33 cases — render and
     parse the rendered --hero-h1-size-rem / --hero-h2-size-rem CSS
     vars. Assert each is within [rubric_floor, sanity_ceiling]. This
     catches a variant author who picks a base value below the rubric
     floor: their restrained render would clamp UP to the floor and
     this test surfaces the author error (the clamp itself prevents
     rubric violation in production — the test surfaces the intent
     mismatch so the variant author can pick a better base).

  2. Font resolver coverage
     Each of 5 font_ids resolves to valid CSS + Google Fonts loading
     HTML. Unknown font_id falls back to default.

  3. Accent renderer coverage
     Each of 6 accent_ids renders (no_accent → empty, others → non-
     empty HTML with brand var refs). Unknown accent_id → empty.

  4. Composition default behavior
     A composition constructed without creative_expression gets the
     CreativeExpression default; render path works end-to-end.

Run via:
  python -m agents.design_modules.studio_brut.hero.__tests__.test_creative_expression
"""
from __future__ import annotations

import re
import unittest
from typing import Tuple

from agents.design_modules.studio_brut.hero.types import (
    BrandKitColors,
    CreativeExpression,
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
from agents.design_modules.studio_brut.hero.creative_expression import (
    HERO_H1_FLOOR_REM,
    HERO_H1_SANITY_CEILING_REM,
    SECTION_H2_FLOOR_REM,
    SECTION_H2_SANITY_CEILING_REM,
    INTENSITY_CONFIG,
    STUDIO_BRUT_FONT_IDS,
    STUDIO_BRUT_FONT_DEFAULT,
    STUDIO_BRUT_ACCENT_IDS,
    font_css_vars,
    font_loading_html,
    intensity_css_vars,
    render_accent,
    render_positioned_accent,
    resolve_font,
)


# ─── Fixtures ──────────────────────────────────────────────────────

BRAND = BrandKitColors(
    primary="#6B46C1",
    secondary="#1F2937",
    accent="#F59E0B",
    background="#FAFAFA",
    text="#111827",
)

CONTENT = HeroContent(
    eyebrow="THE ROYAL COURT",
    heading="Wear your crown loud",
    heading_emphasis="loud",
    subtitle="Custom designs that command attention.",
    cta_primary="Start a design",
    cta_target="#design",
    image_slot_ref="hero_main",
)

# Use a mid-tier treatments set so all dimensions emit non-trivial
# CSS vars (signature ornaments, soft gradient, gradient accents,
# editorial typography). Same shape across the test matrix so the
# only variable being tested is creative_expression.
TREATMENTS = Treatments(
    color_emphasis="dual_emphasis",
    spacing_density="standard",
    emphasis_weight="balanced",
    background="soft_gradient",
    color_depth="gradient_accents",
    ornament="signature",
    typography="bold",
    image_treatment="filtered",
)

SLOT_RESOLUTIONS = {
    "hero_main": (
        "https://images.unsplash.com/photo-1521577352947-9bb58764b69a"
        "?auto=format&fit=crop&w=1600&q=80"
    ),
}


# ─── Helpers ───────────────────────────────────────────────────────

def _build_treatment_vars(t: Treatments) -> dict:
    out = {}
    out.update(color_emphasis_vars(t.color_emphasis))
    out.update(spacing_density_vars(t.spacing_density))
    out.update(emphasis_weight_vars(t.emphasis_weight))
    out.update(background_treatment_vars(t.background))
    out.update(color_depth_vars(t.color_depth))
    out.update(ornament_treatment_vars(t.ornament))
    out.update(typography_personality_vars(t.typography))
    out.update(image_treatment_vars(t.image_treatment))
    return out


def _render(variant_id: str, intensity: str,
            font_id: str = "brutalist_default",
            accent_id: str = "no_accent") -> str:
    """Render one (variant, intensity, font, accent) cell. Returns HTML."""
    ce = CreativeExpression(font_id=font_id, accent_id=accent_id, intensity=intensity)
    content = CONTENT.model_copy()
    content.image_slot_ref = "hero_main" if variant_id in IMAGE_USING_VARIANTS else None
    comp = StudioBrutHeroComposition(
        variant=variant_id,
        treatments=TREATMENTS,
        content=content,
        creative_expression=ce,
        reasoning="creative expression smoke test",
    )
    ctx = RenderContext(
        composition=comp,
        brand_kit=BRAND,
        business_id="ce-smoke",
        slot_resolutions=SLOT_RESOLUTIONS,
    )
    return VARIANT_REGISTRY[variant_id](ctx, {}, _build_treatment_vars(TREATMENTS))


# Pass 4.0i Phase B (post-fix): vars carry CSS units in their values
# (--hero-h1-font-size = "4.000rem", --hero-letter-spacing = "-2.40px").
# Regexes extract the numeric component for arithmetic assertions; the
# string form is also checked when verifying consumption by primitives.
_RE_H1_FONT_SIZE = re.compile(r"--hero-h1-font-size:\s*([0-9.]+)rem")
_RE_H2_FONT_SIZE = re.compile(r"--hero-h2-font-size:\s*([0-9.]+)rem")
_RE_WEIGHT = re.compile(r"--hero-display-weight:\s*(\d+)")
_RE_LETTER_SPACING = re.compile(r"--hero-letter-spacing:\s*(-?[0-9.]+)px")
_RE_FONT_DISPLAY = re.compile(r"--hero-font-display:\s*([^;]+);")
_RE_FONT_BODY = re.compile(r"--hero-font-body:\s*([^;]+);")

# Match the entire <h1> opening tag (the variant's only one). Extract its
# inline style attribute value so we can assert which vars the h1 actually
# consumes — closes the gap that let inert vars ship green in pre-fix.
_RE_H1_TAG = re.compile(
    r'<h1\b[^>]*\bstyle="([^"]*)"[^>]*>',
    re.IGNORECASE | re.DOTALL,
)


def _parse_section_vars(html: str) -> Tuple[float, float, int]:
    """Extract --hero-h1-font-size, --hero-h2-font-size, --hero-display-weight
    from the section's inline style (the SET side). Raises if missing —
    every Pass 4.0i variant MUST emit all three on its section style."""
    m_h1 = _RE_H1_FONT_SIZE.search(html)
    m_h2 = _RE_H2_FONT_SIZE.search(html)
    m_w = _RE_WEIGHT.search(html)
    if not m_h1:
        raise AssertionError("--hero-h1-font-size missing from rendered HTML")
    if not m_h2:
        raise AssertionError("--hero-h2-font-size missing from rendered HTML")
    if not m_w:
        raise AssertionError("--hero-display-weight missing from rendered HTML")
    return float(m_h1.group(1)), float(m_h2.group(1)), int(m_w.group(1))


def _extract_h1_inline_style(html: str) -> str:
    """Return the inline style attribute of the variant's <h1>. Raises if
    no <h1> found. Used to assert the h1 CONSUMES the Pass 4.0i vars,
    not just that the vars are set on the section."""
    m = _RE_H1_TAG.search(html)
    if not m:
        raise AssertionError("no <h1> found in rendered HTML")
    return m.group(1)


# ─── Tests ─────────────────────────────────────────────────────────

class IntensityRubricMatrixTests(unittest.TestCase):
    """The 33-cell matrix: each variant × each intensity must produce
    h1/h2 sizes within rubric floor + sanity ceiling, with valid
    font-weight. Failures name the variant + intensity for fast triage."""

    def test_all_variants_all_intensities_satisfy_rubric(self):
        intensities = list(INTENSITY_CONFIG.keys())
        variant_ids = list(VARIANT_REGISTRY.keys())
        cases = 0
        violations = []

        for vid in variant_ids:
            for intensity in intensities:
                cases += 1
                try:
                    html = _render(vid, intensity)
                    h1_rem, h2_rem, weight = _parse_section_vars(html)
                except Exception as e:
                    violations.append(f"{vid}/{intensity}: render failed - {e}")
                    continue
                if not (HERO_H1_FLOOR_REM <= h1_rem <= HERO_H1_SANITY_CEILING_REM):
                    violations.append(
                        f"{vid}/{intensity}: h1={h1_rem}rem outside "
                        f"[{HERO_H1_FLOOR_REM}, {HERO_H1_SANITY_CEILING_REM}]"
                    )
                if not (SECTION_H2_FLOOR_REM <= h2_rem <= SECTION_H2_SANITY_CEILING_REM):
                    violations.append(
                        f"{vid}/{intensity}: h2={h2_rem}rem outside "
                        f"[{SECTION_H2_FLOOR_REM}, {SECTION_H2_SANITY_CEILING_REM}]"
                    )
                if weight not in (800, 900):
                    violations.append(
                        f"{vid}/{intensity}: weight={weight} not in {{800, 900}}"
                    )

        self.assertEqual(cases, len(variant_ids) * len(intensities),
                         "case count mismatch (expected 11 variants x 3 intensities = 33)")
        self.assertEqual(violations, [], "\n  ".join([""] + violations))

    def test_variant_authors_picked_bases_above_floor(self):
        """Stricter test: at restrained (multiplier=1.0), the rendered h1
        size should NOT have been silently clamped up to the floor. If it
        was, the variant author picked an h1_base below 3rem and the
        intensity translator covered for them. Surface the author error
        even though production rendering is safe.

        Tolerance: 0.05rem above floor counts as 'author intentionally
        chose floor'. Below that we count it as an under-floor pick."""
        flagged = []
        for vid in VARIANT_REGISTRY.keys():
            html = _render(vid, "restrained")
            h1_rem, h2_rem, _ = _parse_section_vars(html)
            # restrained = 1.0x, so the rendered value IS the variant's base
            # (unless clamp intervened). If h1_rem is exactly the floor with
            # no headroom, the variant probably has a base at or below floor.
            if h1_rem < HERO_H1_FLOOR_REM + 0.05:
                flagged.append(
                    f"{vid}: restrained h1={h1_rem}rem at floor — "
                    f"variant author likely picked _H1_BASE_REM <= 3.0"
                )
        # All Pass 4.0i variants picked h1_base >= 3.5, so no flags expected.
        self.assertEqual(flagged, [], "\n  ".join([""] + flagged))


class FontResolverTests(unittest.TestCase):

    def test_all_font_ids_resolve_to_complete_css_vars(self):
        required_keys = {"--hero-font-display", "--hero-font-body", "--hero-font-display-weight"}
        for fid in STUDIO_BRUT_FONT_IDS:
            vars = font_css_vars(fid)
            missing = required_keys - set(vars.keys())
            self.assertEqual(missing, set(), f"{fid} missing CSS vars: {missing}")
            # weight should be numeric string
            self.assertTrue(vars["--hero-font-display-weight"].isdigit(),
                            f"{fid} weight not numeric: {vars['--hero-font-display-weight']}")

    def test_brutalist_geometric_includes_code_font(self):
        """brutalist_geometric is the only font_id that ships a 'code' face
        for the code_label accent (JetBrains Mono). Verify the var is emitted."""
        vars = font_css_vars("brutalist_geometric")
        self.assertIn("--hero-font-code", vars)
        self.assertIn("JetBrains Mono", vars["--hero-font-code"])

    def test_unknown_font_id_falls_back_to_default(self):
        vars = font_css_vars("nonsense_font_id_999")
        default_vars = font_css_vars(STUDIO_BRUT_FONT_DEFAULT)
        self.assertEqual(vars["--hero-font-display"], default_vars["--hero-font-display"])

    def test_font_loading_html_includes_preconnect_and_stylesheet(self):
        for fid in STUDIO_BRUT_FONT_IDS:
            html = font_loading_html(fid)
            self.assertIn('rel="preconnect"', html, f"{fid} missing preconnect")
            self.assertIn('rel="stylesheet"', html, f"{fid} missing stylesheet")
            self.assertIn("fonts.googleapis.com", html, f"{fid} missing GFonts host")
            self.assertIn("display=swap", html, f"{fid} missing display=swap")


class AccentRendererTests(unittest.TestCase):

    def test_no_accent_renders_empty(self):
        self.assertEqual(render_accent("no_accent", {}, "brutalist_default", CONTENT), "")
        self.assertEqual(render_positioned_accent("no_accent", {}, "brutalist_default", CONTENT), "")

    def test_unknown_accent_renders_empty(self):
        self.assertEqual(render_accent("totally_made_up", {}, "brutalist_default", CONTENT), "")
        self.assertEqual(render_positioned_accent("totally_made_up", {}, "brutalist_default", CONTENT), "")

    def test_each_real_accent_renders_non_empty(self):
        real_accents = [a for a in STUDIO_BRUT_ACCENT_IDS if a != "no_accent"]
        for aid in real_accents:
            html = render_accent(aid, {}, "brutalist_default", CONTENT)
            self.assertTrue(html, f"{aid} rendered empty (expected non-empty)")
            self.assertIn("var(--brand-", html,
                          f"{aid} missing var(--brand-*) reference")
            # DNA gates: no diamond, no Cathedral leakage
            self.assertNotIn("diamond", html.lower(),
                             f"{aid} contains 'diamond' (Cathedral signature)")
            self.assertNotIn("--ca-", html,
                             f"{aid} contains --ca-* (Cathedral var leakage)")
            # Accents never emit <h1>
            self.assertNotIn("<h1", html, f"{aid} emits <h1>")

    def test_positioned_accent_wraps_with_position_absolute(self):
        for aid in [a for a in STUDIO_BRUT_ACCENT_IDS if a != "no_accent"]:
            html = render_positioned_accent(aid, {}, "brutalist_default", CONTENT)
            self.assertIn('class="sb-accent-wrap"', html, f"{aid} missing wrapper class")
            self.assertIn("position: absolute", html, f"{aid} wrapper missing absolute pos")


class CompositionDefaultsTests(unittest.TestCase):

    def test_composition_without_ce_uses_defaults(self):
        """A composition constructed without creative_expression should
        get CreativeExpression() defaults (brutalist_default / no_accent /
        restrained) and render valid HTML."""
        content = CONTENT.model_copy()
        content.image_slot_ref = None
        comp = StudioBrutHeroComposition(
            variant="color_block_split",
            treatments=TREATMENTS,
            content=content,
            reasoning="default smoke",
        )
        self.assertEqual(comp.creative_expression.font_id, "brutalist_default")
        self.assertEqual(comp.creative_expression.accent_id, "no_accent")
        self.assertEqual(comp.creative_expression.intensity, "restrained")
        ctx = RenderContext(composition=comp, brand_kit=BRAND, business_id="default-smoke")
        html = VARIANT_REGISTRY["color_block_split"](ctx, {}, _build_treatment_vars(TREATMENTS))
        # Default state still emits all Pass 4.0i CSS vars
        h1_rem, h2_rem, weight = _parse_section_vars(html)
        self.assertGreaterEqual(h1_rem, HERO_H1_FLOOR_REM)
        self.assertGreaterEqual(h2_rem, SECTION_H2_FLOOR_REM)
        self.assertEqual(weight, 800)  # restrained → 800
        # no_accent default → no accent wrapper
        self.assertNotIn('class="sb-accent-wrap"', html)


class IntensityProgressionTests(unittest.TestCase):
    """Sanity: bold should produce a strictly larger h1 than restrained
    for variants whose base sits comfortably between floor and ceiling.
    Catches regressions where intensity multipliers stop mattering."""

    def test_bold_larger_than_restrained_for_mid_variant(self):
        # edge_bleed_portrait has h1_base=4.0 (clear of floor + ceiling)
        h1_r, _, _ = _parse_section_vars(_render("edge_bleed_portrait", "restrained"))
        h1_c, _, _ = _parse_section_vars(_render("edge_bleed_portrait", "confident"))
        h1_b, _, _ = _parse_section_vars(_render("edge_bleed_portrait", "bold"))
        self.assertLess(h1_r, h1_c, "confident should exceed restrained")
        self.assertLess(h1_c, h1_b, "bold should exceed confident")

    def test_bold_caps_at_ceiling_for_high_base_variant(self):
        # oversize_statement has h1_base=7.5. At bold (1.3x) that's 9.75
        # which is under the 10.0 ceiling. So bold should be ~9.75.
        h1_b, _, _ = _parse_section_vars(_render("oversize_statement", "bold"))
        # If the ceiling were too low, this would clamp to ceiling and equal
        # exactly 10.0. We expect 9.75 (no clamp triggered).
        self.assertAlmostEqual(h1_b, 9.75, places=2,
                               msg="oversize_statement bold should be 7.5*1.3=9.75")


class H1VarConsumptionTests(unittest.TestCase):
    """Pass 4.0i Phase B (post-fix) — the load-bearing assertion that
    closes the gap CHECKPOINT B surfaced.

    Pre-fix, --hero-* vars were emitted on the <section> but the primitives
    (heading.py et al.) read --sb-* vars from a parallel namespace and
    NEVER consumed --hero-*. Tests still passed because they only asserted
    the SET side. After-the-fact diagnosis: the rendered h1 looked the
    same across font/intensity choices because the h1's inline style didn't
    reference --hero-* at all.

    These tests verify the h1 ACTUALLY CONSUMES the Pass 4.0i vars by
    parsing the h1's inline style attribute and looking for the var()
    references. They MUST fail if a future primitive change stops
    consuming a --hero-* var (regression protection).

    Sanity-check during dev: temporarily revert heading.py to the
    pre-fix style (drop the var(--hero-*, ...) wrapping). Run this
    test class. Every test in here MUST fail. Restore heading.py.
    Tests MUST pass again. Confirmed during the Phase B fix work."""

    def _h1_style(self, intensity: str = "restrained",
                  font_id: str = "brutalist_default") -> str:
        html = _render("edge_bleed_portrait", intensity, font_id=font_id)
        return _extract_h1_inline_style(html)

    def test_h1_font_family_references_hero_font_display(self):
        """The h1 inline style MUST contain var(--hero-font-display, ...)
        so practitioner font_id flows through. If a primitive change drops
        this reference, font choice goes inert again."""
        h1_style = self._h1_style()
        self.assertIn(
            "var(--hero-font-display",
            h1_style,
            "h1 font-family does NOT reference --hero-font-display — "
            "Pass 4.0i font_id will not flow into the h1",
        )

    def test_h1_font_size_references_hero_h1_font_size(self):
        """The h1 inline style MUST contain var(--hero-h1-font-size, ...)
        so intensity-driven size flows through. Pre-fix the size was
        hardcoded inline from emphasis_weight; intensity had no effect."""
        h1_style = self._h1_style()
        self.assertIn(
            "var(--hero-h1-font-size",
            h1_style,
            "h1 font-size does NOT reference --hero-h1-font-size — "
            "Pass 4.0i intensity will not flow into the h1 size",
        )

    def test_h1_font_weight_references_hero_display_weight(self):
        h1_style = self._h1_style()
        self.assertIn(
            "var(--hero-display-weight",
            h1_style,
            "h1 font-weight does NOT reference --hero-display-weight — "
            "intensity-driven weight (800/900) will not flow into the h1",
        )

    def test_h1_letter_spacing_references_hero_letter_spacing(self):
        h1_style = self._h1_style()
        self.assertIn(
            "var(--hero-letter-spacing",
            h1_style,
            "h1 letter-spacing does NOT reference --hero-letter-spacing — "
            "intensity-driven tracking will not flow into the h1",
        )

    def test_h1_actually_changes_font_across_font_ids(self):
        """Highest-level acceptance: render the same variant with two
        different font_ids and confirm the h1 inline style differs in
        the font-family var resolution path. Pre-fix: the h1 inline
        style was IDENTICAL across all font_ids (because it ignored
        --hero-font-display entirely). Post-fix: the section's
        --hero-font-display value differs and the h1 var() chain
        resolves to it."""
        html_default = _render("edge_bleed_portrait", "restrained",
                               font_id="brutalist_default")
        html_sharp = _render("edge_bleed_portrait", "restrained",
                             font_id="brutalist_sharp")
        # Section-level vars differ
        m_default = _RE_FONT_DISPLAY.search(html_default)
        m_sharp = _RE_FONT_DISPLAY.search(html_sharp)
        self.assertIsNotNone(m_default, "--hero-font-display missing in default")
        self.assertIsNotNone(m_sharp, "--hero-font-display missing in sharp")
        self.assertNotEqual(
            m_default.group(1).strip(),
            m_sharp.group(1).strip(),
            "section --hero-font-display IDENTICAL across font_ids — "
            "font_resolver not differentiating",
        )
        # h1 inline styles both reference --hero-font-display (consumption)
        h1_default = _extract_h1_inline_style(html_default)
        h1_sharp = _extract_h1_inline_style(html_sharp)
        self.assertIn("var(--hero-font-display", h1_default)
        self.assertIn("var(--hero-font-display", h1_sharp)

    def test_h1_actually_changes_size_across_intensities(self):
        """Acceptance for intensity: render the same variant+font at
        restrained vs bold and confirm the SECTION's --hero-h1-font-size
        var value differs. The h1 inline style references the var, so
        a CSS-engine resolution would yield different rendered sizes.
        Pre-fix the section value was set but h1 ignored it; post-fix
        the h1 reads it and the rendered size will differ."""
        html_r = _render("edge_bleed_portrait", "restrained")
        html_b = _render("edge_bleed_portrait", "bold")
        m_r = _RE_H1_FONT_SIZE.search(html_r)
        m_b = _RE_H1_FONT_SIZE.search(html_b)
        self.assertIsNotNone(m_r)
        self.assertIsNotNone(m_b)
        self.assertNotAlmostEqual(
            float(m_r.group(1)), float(m_b.group(1)),
            msg="--hero-h1-font-size identical across restrained vs bold — "
                "intensity multiplier not differentiating",
        )
        # h1 consumes the var
        h1_r = _extract_h1_inline_style(html_r)
        self.assertIn("var(--hero-h1-font-size", h1_r)


class SecondaryPrimitiveVarConsumptionTests(unittest.TestCase):
    """Verify eyebrow / subtitle / cta_button consume --hero-font-body
    so practitioner font_id's body face flows through. These are
    smaller-surface assertions than h1 but the same class of regression
    protection: a primitive change that drops the var ref ships
    inert vars without these tests."""

    def _render_html(self) -> str:
        return _render("edge_bleed_portrait", "restrained",
                       font_id="brutalist_sharp")

    def test_eyebrow_references_hero_font_body(self):
        html = self._render_html()
        m = re.search(r'<div class="sb-hero-eyebrow"[^>]+style="([^"]*)"', html)
        self.assertIsNotNone(m, "eyebrow div not found")
        self.assertIn("var(--hero-font-body", m.group(1))

    def test_subtitle_references_hero_font_body(self):
        html = self._render_html()
        m = re.search(r'<p class="sb-hero-subtitle"[^>]+style="([^"]*)"', html)
        self.assertIsNotNone(m, "subtitle <p> not found")
        self.assertIn("var(--hero-font-body", m.group(1))

    def test_cta_button_references_hero_font_body(self):
        html = self._render_html()
        m = re.search(r'<a class="sb-hero-cta-button"[^>]+style="([^"]*)"', html)
        self.assertIsNotNone(m, "CTA button <a> not found")
        self.assertIn("var(--hero-font-body", m.group(1))


if __name__ == "__main__":
    unittest.main()
