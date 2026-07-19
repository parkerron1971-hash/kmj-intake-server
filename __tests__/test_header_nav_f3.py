# __tests__/test_header_nav_f3.py
# ─────────────────────────────────────────────────────────────────────
# F3 (2026-07-18) — nav ship-gate fixes from the acceptance run:
#   1. the always-on edge mask clipped the first/last link characters
#      at EVERY viewport (read as a rendering bug, not a fade) — removed
#   2. the single-page anchor nav had no mobile fallback: links
#      overflowed off-canvas at 390px (the broken=y driver). It now
#      gets the same CSS-only hamburger drawer as the multi-page nav.
# ─────────────────────────────────────────────────────────────────────

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from site_modules.header import render_header  # noqa: E402

CTX = {"dna": {"palette": {"mode": "dark"}, "vibe": "warm"},
       "business": {"name": "Test Shop"}, "bundle": {"assets": {}},
       "booking": {}}


class TestAnchorNavDrawer(unittest.TestCase):
    def test_anchor_nav_ships_drawer(self):
        html, _ = render_header(["hero", "about", "offerings", "contact"], CTX)
        self.assertIn('id="sxm-nav-toggle"', html)
        self.assertIn('class="sxm-hamburger"', html)
        self.assertIn("sxm-header-drawer", html)
        # the drawer's links mirror the bar's links
        self.assertEqual(html.count('href="#about"'), 2)
        # 3 = bar nav + drawer + the header CTA (no booking → #contact)
        self.assertEqual(html.count('href="#contact"'), 3)

    def test_no_links_no_drawer(self):
        html, _ = render_header(["hero"], CTX)
        self.assertNotIn("sxm-header-drawer", html)
        self.assertNotIn("sxm-nav-toggle", html)

    def test_page_nav_still_ships_drawer(self):
        ctx = dict(CTX, page_nav={"pages": [
            {"id": "home", "name": "Home", "href": "/"},
            {"id": "work", "name": "Work", "href": "/work"}]})
        html, _ = render_header(["hero"], ctx)
        self.assertIn("sxm-header-drawer", html)
        self.assertIn('href="/work"', html)


class TestNavCss(unittest.TestCase):
    def test_edge_mask_removed(self):
        _, css = render_header(["hero", "about", "contact"], CTX)
        self.assertNotIn("mask-image", css)

    def test_mobile_collapses_bar_nav(self):
        _, css = render_header(["hero", "about", "contact"], CTX)
        self.assertIn(".sxm-header-nav { display: none; }", css)
        self.assertIn(".sxm-hamburger { display: inline-flex", css)

    def test_desktop_nav_unaffected(self):
        _, css = render_header(["hero", "about", "contact"], CTX)
        self.assertIn(".sxm-header-nav { display: flex;", css)


if __name__ == "__main__":
    unittest.main()
