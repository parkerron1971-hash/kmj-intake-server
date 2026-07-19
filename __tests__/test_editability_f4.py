# __tests__/test_editability_f4.py
# ─────────────────────────────────────────────────────────────────────
# F4 (2026-07-18) — the acceptance run's two gate findings:
#   1. atelier fragments invented display copy (a pull quote, a colophon
#      line) with NO override target — the prompt clause alone didn't
#      hold. The editability census moved to site_modules._base so the
#      atelier validator enforces it at the source (binding), with a
#      verbatim-business-data exemption so record copy isn't flagged.
#   2. cta_link_coherence flagged booking-worded buttons → #contact even
#      when the business has NO booking connected — with no scheduler,
#      the contact form IS the booking path. Carve-out: only flag when
#      booking actually exists.
# ─────────────────────────────────────────────────────────────────────

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from site_modules._base import (data_verbatim_strings,  # noqa: E402
                                editability_coverage)


class TestEditabilityCoverage(unittest.TestCase):
    def test_untargeted_p_flagged(self):
        n, samples = editability_coverage("<body><p>Hello there</p></body>")
        self.assertEqual(n, 1)
        self.assertIn("Hello there", samples[0])

    def test_targeted_p_passes(self):
        n, _ = editability_coverage(
            '<body><p data-override-target="hero/custom_1">Hello</p></body>')
        self.assertEqual(n, 0)

    def test_target_inherited_from_ancestor(self):
        n, _ = editability_coverage(
            '<body><div data-override-target="hero/custom_1"><p>Hello</p></div></body>')
        self.assertEqual(n, 0)

    def test_chrome_prefix_exempt(self):
        n, _ = editability_coverage(
            '<body><p class="sxm-header-note">Chrome copy</p></body>')
        self.assertEqual(n, 0)

    def test_verbatim_data_exempt(self):
        exempt = data_verbatim_strings({"offer": "Hand-set type, pressed slow"})
        n, _ = editability_coverage(
            "<body><p>Hand-set type, pressed slow</p></body>",
            exempt_texts=exempt)
        self.assertEqual(n, 0)

    def test_verbatim_exemption_does_not_cover_inventions(self):
        exempt = data_verbatim_strings({"offer": "Hand-set type"})
        n, _ = editability_coverage(
            "<body><p>Invented tagline</p></body>", exempt_texts=exempt)
        self.assertEqual(n, 1)


class TestDataVerbatimStrings(unittest.TestCase):
    def test_nested_collection(self):
        s = data_verbatim_strings({"a": "one", "b": [{"c": "two"}], "n": 5})
        self.assertIn("one", s)
        self.assertIn("two", s)
        self.assertEqual(len([x for x in s if x == "5"]), 0)  # non-strings skipped


class TestValidatorEditabilityBinding(unittest.TestCase):
    """The atelier validator reports total-editability problems (the
    repair loop gets one shot, then the fragment falls back)."""

    def _problems(self, inner_html):
        import atelier_validator
        html = (f'<section class="atl-abcd1234">{inner_html}</section>')
        css = (".atl-abcd1234 { color: var(--sx-text); }"
               "@media (max-width: 700px) { .atl-abcd1234 { color: var(--sx-text); } }")
        _, problems = atelier_validator.validate_fragment(
            html, css, uid="abcd1234", kind="about",
            data={"copy": {}}, allowed_slots=(), required_targets=(),
            allowed_hrefs=(), allowed_fields=())
        return problems

    def test_invented_untargeted_copy_is_a_problem(self):
        problems = self._problems("<h2>Real heading</h2><p>Invented line</p>")
        self.assertTrue(any(p.startswith("total editability") for p in problems),
                        problems)

    def test_invented_targeted_copy_passes(self):
        problems = self._problems(
            '<h2 data-override-target="about/headline">Real heading</h2>'
            '<p data-override-target="about/custom_1">Invented line</p>')
        self.assertFalse(any(p.startswith("total editability") for p in problems),
                         problems)

    def test_verbatim_business_data_not_flagged(self):
        import atelier_validator
        html = ('<section class="atl-abcd1234">'
                '<h2 data-override-target="about/headline">Our story</h2>'
                "<p>Pressed by hand since the beginning</p></section>")
        css = (".atl-abcd1234 { color: var(--sx-text); }"
               "@media (max-width: 700px) { .atl-abcd1234 { color: var(--sx-text); } }")
        _, problems = atelier_validator.validate_fragment(
            html, css, uid="abcd1234", kind="about",
            data={"copy": {}, "about": "Pressed by hand since the beginning"},
            allowed_slots=(), required_targets=(),
            allowed_hrefs=(), allowed_fields=())
        self.assertFalse(any(p.startswith("total editability") for p in problems),
                         problems)


class TestCtaCoherenceCarveout(unittest.TestCase):
    HTML = ('<html><body><a class="sxm-cta" href="#contact">'
            "<span>Book a Session</span></a></body></html>")

    def _coherence(self, booking):
        import site_composer
        ctx = {"booking": booking, "dna": {}}
        rep, _ = site_composer._run_quality_gate("biz-f4", [], ctx, self.HTML)
        return next(c for c in rep["checks"] if c["name"] == "cta_link_coherence")

    def test_flagged_only_when_booking_exists(self):
        c = self._coherence({"enabled": True, "url": "https://book.example.com"})
        self.assertFalse(c["ok"])

    def test_no_booking_means_contact_is_the_booking_path(self):
        c = self._coherence({"enabled": False, "url": ""})
        self.assertTrue(c["ok"])


if __name__ == "__main__":
    unittest.main()
