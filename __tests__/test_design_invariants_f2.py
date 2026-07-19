# __tests__/test_design_invariants_f2.py
# ─────────────────────────────────────────────────────────────────────
# F2 (2026-07-18) — RHYTHM-1 checker precision. The acceptance run's
# first live invariant failures were mostly checker artifacts: a CTA
# button's HORIZONTAL padding (18px 44px), scroll-padding anchor math
# (112px), and clamp maxima on token-governed values. The checker now
# skips scroll-padding, reads only the vertical shorthand components,
# and skips var(--sx-*)-governed values. Genuine section offenders
# (hero/seam clamp maxima) were snapped to the scale in the modules.
# ─────────────────────────────────────────────────────────────────────

import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import design_invariants  # noqa: E402

SCALE = {"allowed_px": [32, 64, 128, 192], "tolerance_px": 8}


def _evidence(css):
    f = design_invariants.check_rhythm(css, SCALE)
    return (f or {}).get("evidence")


class TestRhythmCheckerPrecision(unittest.TestCase):
    def test_scroll_padding_ignored(self):
        css = ".sxm-header--banner { scroll-padding-top: 112px; }"
        self.assertIsNone(_evidence(css))

    def test_horizontal_component_ignored(self):
        # 2-value shorthand: vertical is the FIRST (18px, skipped < 40);
        # the 44px is horizontal and must not be read as rhythm.
        css = ".sxm-cta { padding: 18px 44px; }"
        self.assertIsNone(_evidence(css))

    def test_third_component_is_vertical_and_caught(self):
        # 3-value shorthand: top / horizontal / bottom — the bottom
        # clamp max (110px) is a genuine rhythm break.
        css = ".sxm-hero-cine { padding: var(--sx-section-pad) var(--sx-gutter) clamp(56px, 9vh, 110px); }"
        ev = _evidence(css)
        self.assertIsNotNone(ev)
        self.assertIn("110px", ev)

    def test_var_governed_values_skipped(self):
        css = ".sxm-cta-band { padding-top: var(--sx-rhythm-half, clamp(64px, 8vw, 80px)); }"
        self.assertIsNone(_evidence(css))

    def test_bare_offscale_clamp_flagged(self):
        css = ".sxm-int-statement { padding: clamp(56px, 9vh, 96px) var(--sx-gutter); }"
        ev = _evidence(css)
        self.assertIsNotNone(ev)
        self.assertIn("96px", ev)

    def test_on_scale_section_passes(self):
        css = (".sxm-section { padding-top: clamp(64px, 10vh, 128px); }"
               ".sxm-int-statement { padding: clamp(56px, 9vh, 128px) var(--sx-gutter); }")
        self.assertIsNone(_evidence(css))

    def test_missing_scale_is_noop(self):
        self.assertIsNone(design_invariants.check_rhythm(".sxm-section { padding: 999px; }", None))


class TestModuleSourcesOnScale(unittest.TestCase):
    """Static tripwire: every padding declaration in the module library
    must satisfy the checker (catches future off-scale literals before
    the acceptance harness does)."""

    def test_module_library_clean(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = "\n".join(
            open(f, encoding="utf-8").read()
            for f in glob.glob(os.path.join(root, "site_modules", "*.py")))
        self.assertIsNone(_evidence(src))


if __name__ == "__main__":
    unittest.main()
