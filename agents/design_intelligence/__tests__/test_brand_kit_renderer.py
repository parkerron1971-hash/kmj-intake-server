"""Pass 4.0h.x — brand_kit_renderer regression tests.

Covers inject_brand_kit_vars positioning, idempotency, and fallbacks.

The critical regression is the --brand-* :root collision: a Builder Agent
build may emit `<style>:root { --brand-authority: #FAKE; }</style>` inside
its HTML. Before Pass 4.0h.x the renderer injected brand-kit-vars just
after <head>, so the Builder's later :root won the CSS cascade and masked
the practitioner's saved brand kit (KMJ production incident, 2026-05-18).

The fix moves injection to just-before-</head> so brand-kit-vars wins the
cascade. TEST_cascade_wins_against_earlier_root is the load-bearing case.

Run via:
  python -m agents.design_intelligence.__tests__.test_brand_kit_renderer
"""
from __future__ import annotations

import unittest

from agents.design_intelligence.brand_kit_renderer import inject_brand_kit_vars


class InjectBrandKitVarsTests(unittest.TestCase):
    def test_cascade_wins_against_earlier_root(self):
        """Critical: when Builder HTML already contains a <style>:root{...}</style>
        block redefining --brand-authority, brand-kit-vars must be inserted
        AFTER it (in document order) so CSS cascade resolves to brand-kit-vars.
        This is the bug Pass 4.0h.x fixes."""
        html_in = (
            '<!DOCTYPE html><html><head><meta charset="utf-8">'
            '<style>:root{--brand-authority:#FAKE}</style>'
            '</head><body>x</body></html>'
        )
        out = inject_brand_kit_vars(html_in, {"authority": "#000000", "signal": "#00ff59"})
        self.assertIn('<style id="brand-kit-vars">', out)
        self.assertGreater(
            out.index("brand-kit-vars"),
            out.index("--brand-authority:#FAKE"),
            "brand-kit-vars must come AFTER Builder block in document order",
        )
        self.assertLess(out.index("brand-kit-vars"), out.index("</head>"), "must stay inside <head>")

    def test_idempotent_on_rerender(self):
        """Re-injecting strips the prior brand-kit-vars block first so values
        don't stack across renders; latest values must win."""
        html_in = "<html><head></head><body>x</body></html>"
        once = inject_brand_kit_vars(html_in, {"authority": "#000000"})
        twice = inject_brand_kit_vars(once, {"authority": "#111111"})
        self.assertEqual(twice.count('id="brand-kit-vars"'), 1)
        self.assertIn("#111111", twice)
        self.assertNotIn("#000000", twice)

    def test_fallback_when_head_close_missing(self):
        """Malformed HTML missing </head> falls back to inserting just after
        the <head> opening tag rather than failing."""
        no_close = '<head><meta charset="utf-8"><body>x</body>'
        out = inject_brand_kit_vars(no_close, {"authority": "#000000"})
        self.assertIn("brand-kit-vars", out)

    def test_fallback_when_fully_headless(self):
        """HTML with neither <head> nor </head> gets the block prepended so
        the variables are at least in scope."""
        no_head = "<body>x</body>"
        out = inject_brand_kit_vars(no_head, {"authority": "#000000"})
        self.assertTrue(out.startswith('<style id="brand-kit-vars">'))

    def test_empty_inputs_no_op(self):
        """Empty html or empty css_vars should pass through unchanged
        rather than raising."""
        self.assertEqual(inject_brand_kit_vars("", {"authority": "#000"}), "")
        self.assertEqual(inject_brand_kit_vars("<html/>", {}), "<html/>")


if __name__ == "__main__":
    unittest.main()
