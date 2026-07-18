# __tests__/test_design_quality_p1.py
# ─────────────────────────────────────────────────────────────────────
# Unit coverage for the 2026-07-18 design-quality arcs:
#   A1 design invariants on the live path · A2 bounded quality regen
#   A3 spec-stage doctrine/ladder        · A4 invention verification
#   B5 fallback-cliff fixes (vibe default palette, stock headlines,
#     ceremony marquee without a DRO)
# In-memory only — no Supabase, no LLM, no playwright.
# ─────────────────────────────────────────────────────────────────────

import os
import unittest


class TestRegenFeedback(unittest.TestCase):
    def test_verdict_and_findings_compose(self):
        import site_composer
        notes = site_composer._regen_feedback(
            {"passes_gate": False, "first_viewport_impact": 5,
             "template_smell": 6, "broken": "n",
             "notes": ["hero is generic", "no motif"]},
            [{"rule_id": "MOTIF-1", "description": "accent only in type",
              "fix_hint": "give the accent a material home"}])
        self.assertIn("FAILED the vision ship-gate", notes)
        self.assertIn("hero is generic", notes)
        self.assertIn("MOTIF-1", notes)
        self.assertIn("material home", notes)

    def test_passing_verdict_omitted(self):
        import site_composer
        notes = site_composer._regen_feedback({"passes_gate": True}, [])
        self.assertEqual(notes, "")


class TestInventionVerification(unittest.TestCase):
    def _ctx(self):
        return {
            "site_prefs": {
                "offer": "We design brand identities for small businesses.",
                "creative": {"metaphor": "a letterpress studio",
                             "tension": {"pole_a": "heritage", "pole_b": "modern"}},
                "story": {"origin": "started at a kitchen table"},
                "feel_words": ["crafted", "editorial"],
            },
            "bundle": {"business": {"tagline": "Hand-made brands",
                                    "elevator_pitch": "We design brands."}},
        }

    def test_restatement_detected(self):
        import site_composer
        from design_register import note_inventions
        note_inventions("biz-a", 3, texts=[
            {"addition": "We design brand identities for small businesses everywhere"},
            {"addition": "oversized ghost numeral watermarking the authority band"},
            {"addition": "a marquee of brass rules separating the chapters"},
        ])
        out = site_composer._verify_inventions("biz-a", self._ctx())
        self.assertIs(out["ok"], False)
        self.assertEqual(out["count"], 3)
        self.assertEqual(len(out["restatements"]), 1)

    def test_genuine_inventions_pass(self):
        import site_composer
        from design_register import note_inventions
        note_inventions("biz-b", 3, texts=[
            {"addition": "oversized ghost numeral watermarking the authority band"},
            {"addition": "a marquee of brass rules separating the chapters"},
            {"addition": "prices right-aligned on a hairline ledger column"},
        ])
        out = site_composer._verify_inventions("biz-b", self._ctx())
        self.assertIs(out["ok"], True)

    def test_unknown_is_not_failure(self):
        import site_composer
        out = site_composer._verify_inventions("biz-never-seen", self._ctx())
        self.assertIs(out["ok"], None)


class TestStockHeadlines(unittest.TestCase):
    def test_vibe_keyed(self):
        import site_composer
        warm = site_composer._stock_headline("cta", {"dna": {"vibe": "warm"}})
        bold = site_composer._stock_headline("cta", {"dna": {"vibe": "bold"}})
        formal = site_composer._stock_headline("cta", {"dna": {"vibe": "formal"}})
        self.assertEqual(len({warm, bold, formal}), 3)
        self.assertTrue(all((warm, bold, formal)))

    def test_unknown_module_empty(self):
        import site_composer
        self.assertEqual(site_composer._stock_headline("nope", {"dna": {}}), "")


class TestVibeDefaultPalette(unittest.TestCase):
    def test_formal_not_cold_blue(self):
        import brand_dna
        formal = brand_dna._VIBE_DEFAULTS["formal"]
        self.assertNotEqual(formal["accent"], "#7fa8d9")
        self.assertNotEqual(formal["bg"], "#0e1217")
        # doctrine D11 guard: the kit-less formal default must not be
        # a blue accent on a blue ground.
        self.assertFalse(formal["bg"].startswith("#0e"))
        self.assertEqual(formal["bg"], "#141210")
        self.assertEqual(formal["accent"], "#c9a96a")


class TestSpecLadderEntry(unittest.TestCase):
    def test_spec_timeouts(self):
        import model_ladder
        self.assertEqual(model_ladder.timeout_for("spec", "claude-sonnet-4-5-20250929"), 75.0)
        self.assertEqual(model_ladder.timeout_for("spec", "claude-opus-4-7"), 120.0)


class TestCeremonyWithoutDro(unittest.TestCase):
    def _ctx(self, tone_words, motion="standard"):
        return {"dna": {"vibe": "warm", "motion": motion},
                "business": {"id": "biz-ceremony"},
                "bundle": {"voice": {"tone_words": tone_words}}}

    def test_marquee_survives_dro_fallback(self):
        import site_composer
        spec = [{"module": m, "variant": "x", "content": {}}
                for m in ("hero", "about", "offerings", "testimonials", "contact")]
        ctx = self._ctx(["crafted", "warm", "honest", "premium", "quiet"])
        out = site_composer._apply_ceremony_pass(spec, ctx, None, seed="s1")
        variants = [s["variant"] for s in out if s["module"] == "interstitial"]
        self.assertEqual(variants, ["marquee"])

    def test_no_tone_words_no_seams(self):
        import site_composer
        spec = [{"module": m, "variant": "x", "content": {}}
                for m in ("hero", "about", "offerings", "testimonials", "contact")]
        out = site_composer._apply_ceremony_pass(spec, self._ctx([]), None, seed="s1")
        self.assertEqual(len(out), len(spec))

    def test_stilled_motion_no_marquee(self):
        import site_composer
        spec = [{"module": m, "variant": "x", "content": {}}
                for m in ("hero", "about", "offerings", "testimonials", "contact")]
        ctx = self._ctx(["crafted", "warm", "honest", "premium"], motion="subtle")
        out = site_composer._apply_ceremony_pass(spec, ctx, None, seed="s1")
        self.assertEqual(len(out), len(spec))


class TestDefaultSpecRotation(unittest.TestCase):
    def _ctx(self, vibe, offerings):
        return {"dna": {"vibe": vibe}, "business": {"name": "Test Biz", "type": "studio"},
                "bundle": {"business": {}}, "offerings": offerings,
                "cta_goal": "", "testimonials": []}

    def test_bold_gets_anchored_not_banner(self):
        import site_composer
        spec = site_composer._default_spec(self._ctx("bold", []))
        self.assertEqual(spec[0]["variant"], "anchored")

    def test_formal_menu_requires_prices(self):
        import site_composer
        with_prices = site_composer._default_spec(self._ctx(
            "formal", [{"name": "Cut", "price": 50}]))
        without = site_composer._default_spec(self._ctx(
            "formal", [{"name": "Cut"}]))
        v = lambda s: [x["variant"] for x in s if x["module"] == "offerings"][0]
        self.assertEqual(v(with_prices), "menu")
        self.assertEqual(v(without), "list")

    def test_warm_featured_needs_three(self):
        import site_composer
        three = site_composer._default_spec(self._ctx(
            "warm", [{"name": "A"}, {"name": "B"}, {"name": "C"}]))
        v = [x["variant"] for x in three if x["module"] == "offerings"][0]
        self.assertEqual(v, "featured")


if __name__ == "__main__":
    unittest.main()
