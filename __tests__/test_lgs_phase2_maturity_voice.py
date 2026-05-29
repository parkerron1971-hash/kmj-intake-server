"""LGS Phase 2 tests — maturity engine + practitioner voice composer.

Covers the pure logic (band derivation, voice composition) + the cache
freshness gate with sb_clients mocked. No live DB / no LLM.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import maturity_engine
import practitioner_voice


class DeriveStageTests(unittest.TestCase):
    """derive_stage is a pure function: signals -> stage. Walk bands high→low."""

    def test_empty_signals_is_idea(self):
        self.assertEqual(maturity_engine.derive_stage({}), "idea")

    def test_brand_new_with_one_module_is_launching(self):
        s = {"age_days": 2, "module_count": 1, "entry_count": 1, "paid_invoice_count": 0}
        self.assertEqual(maturity_engine.derive_stage(s), "launching")

    def test_steady_activity_is_operating(self):
        s = {"age_days": 45, "module_count": 4, "entry_count": 30, "paid_invoice_count": 5}
        self.assertEqual(maturity_engine.derive_stage(s), "operating")

    def test_high_volume_is_scaling(self):
        s = {"age_days": 200, "module_count": 7, "entry_count": 150, "paid_invoice_count": 40}
        self.assertEqual(maturity_engine.derive_stage(s), "scaling")

    def test_partial_band_falls_to_lower(self):
        # Old + many modules but NO paid invoices → not operating (needs >=3 paid).
        s = {"age_days": 90, "module_count": 4, "entry_count": 30, "paid_invoice_count": 0}
        self.assertEqual(maturity_engine.derive_stage(s), "launching")

    def test_scaling_requires_all_thresholds(self):
        # Old + high entries but only 5 modules / 10 invoices → operating, not scaling.
        s = {"age_days": 200, "module_count": 5, "entry_count": 150, "paid_invoice_count": 10}
        self.assertEqual(maturity_engine.derive_stage(s), "operating")

    def test_stage_at_least(self):
        self.assertTrue(maturity_engine.stage_at_least("operating", "launching"))
        self.assertTrue(maturity_engine.stage_at_least("scaling", "scaling"))
        self.assertFalse(maturity_engine.stage_at_least("idea", "operating"))
        self.assertFalse(maturity_engine.stage_at_least(None, "launching"))


class ComputeMaturityCacheTests(unittest.TestCase):
    """compute_maturity uses the cache when fresh, recomputes when stale/forced."""

    def test_fresh_cache_short_circuits(self):
        fresh = {
            "stage": "operating",
            "signals": {"age_days": 50},
            "computed_at": "2999-01-01T00:00:00Z",  # far future → always fresh
        }
        with patch.object(maturity_engine.sb_clients, "sb_get_as_service", return_value=[{"settings": {"maturity": fresh}}]):
            out = maturity_engine.compute_maturity("biz-1")
        self.assertEqual(out["stage"], "operating")
        self.assertTrue(out["cached"])

    def test_stale_cache_recomputes(self):
        stale = {"stage": "idea", "signals": {}, "computed_at": "2020-01-01T00:00:00Z"}
        # First _read_cache returns stale; then collect_signals reads + cache write.
        calls = {"n": 0}

        def fake_get(path):
            # settings read (cache) → stale; everything else (signals) → empty list
            if "select=settings" in path:
                return [{"settings": {"maturity": stale}}]
            return []

        with patch.object(maturity_engine.sb_clients, "sb_get_as_service", side_effect=fake_get), \
             patch.object(maturity_engine.sb_clients, "sb_patch_as_service", return_value=[{}]):
            out = maturity_engine.compute_maturity("biz-1")
        self.assertFalse(out["cached"])
        self.assertEqual(out["stage"], "idea")  # empty signals → idea
        self.assertIn("computed_at", out)

    def test_force_bypasses_fresh_cache(self):
        fresh = {"stage": "scaling", "signals": {}, "computed_at": "2999-01-01T00:00:00Z"}

        def fake_get(path):
            if "select=settings" in path:
                return [{"settings": {"maturity": fresh}}]
            return []

        with patch.object(maturity_engine.sb_clients, "sb_get_as_service", side_effect=fake_get), \
             patch.object(maturity_engine.sb_clients, "sb_patch_as_service", return_value=[{}]):
            out = maturity_engine.compute_maturity("biz-1", force=True)
        # forced recompute with empty signals → idea, not the cached 'scaling'
        self.assertEqual(out["stage"], "idea")
        self.assertFalse(out["cached"])


class VoiceComposerTests(unittest.TestCase):

    def test_empty_business_no_directive(self):
        self.assertEqual(practitioner_voice.compose_voice_directive({}), "")

    def test_voice_profile_only(self):
        biz = {"voice_profile": {"tone": "warm", "personality": "grounded"}}
        d = practitioner_voice.compose_voice_directive(biz)
        self.assertIn("warm", d)
        self.assertIn("grounded", d)
        self.assertIn("same person", d)

    def test_folds_in_brand_kit_tone_words_and_intensity(self):
        biz = {
            "voice_profile": {"tone": "empowering"},
            "settings": {"brand_kit": {
                "tone_words": ["clear", "courageous", "compassionate"],
                "creative_expression": {"intensity": "bold"},
            }},
        }
        d = practitioner_voice.compose_voice_directive(biz)
        self.assertIn("empowering", d)
        self.assertIn("courageous", d)
        self.assertIn("declarative", d)  # bold → declarative register

    def test_intensity_register_mapping(self):
        for intensity, marker in [
            ("restrained", "understated"),
            ("confident", "self-assured"),
            ("bold", "declarative"),
        ]:
            biz = {"settings": {"brand_kit": {"creative_expression": {"intensity": intensity}}}}
            self.assertIn(marker, practitioner_voice.compose_voice_directive(biz))

    def test_voice_signals_structured(self):
        biz = {
            "voice_profile": {"tone": "warm", "personality": "p"},
            "settings": {"brand_kit": {"tone_words": ["a"], "creative_expression": {"intensity": "confident"}}},
        }
        sig = practitioner_voice.voice_signals(biz)
        self.assertEqual(sig["tone"], "warm")
        self.assertEqual(sig["tone_words"], ["a"])
        self.assertIsNotNone(sig["intensity_register"])

    def test_malformed_inputs_dont_crash(self):
        for bad in [{"voice_profile": "not-a-dict"}, {"settings": "x"}, {"settings": {"brand_kit": []}}]:
            self.assertIsInstance(practitioner_voice.compose_voice_directive(bad), str)


if __name__ == "__main__":
    unittest.main()
