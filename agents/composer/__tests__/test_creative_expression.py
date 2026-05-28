"""Pass 4.0i Phase C — composer.creative_expression unit tests.

Covers inference (word-boundary keyword matching), validation
(per-field vocabulary check with inference fallback), and resolution
(sticky-with-source rule that pins practitioner values across re-runs).

Persistence (load + persist) is integration-tested indirectly via
hero_composer's compose_hero; this file mocks brand_engine for the
persistence path to verify the surgical-PATCH shape without hitting
Supabase.

Run via:
  python -m agents.composer.__tests__.test_creative_expression
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from agents.composer.creative_expression import (
    infer_font_id,
    infer_accent_id,
    infer_intensity,
    infer_all,
    validate_creative_expression,
    resolve_creative_expression,
    load_stored_creative_expression,
    persist_creative_expression,
)


# ─── Inference tests ───────────────────────────────────────────────

class InferenceTests(unittest.TestCase):
    """Token-driven inference. Verifies the heuristic picks the expected
    font / accent / intensity for representative briefs, and that the
    word-boundary fix prevents 'author'-inside-'authority' false positives."""

    KMJ_BRIEF = {
        "content_archetype": "creative_agency",
        "inferred_vibe": "editorial counsel, quiet authority, considered creative",
        "brand_metaphor": "solutions as craft, creative problem-solving",
        "tone_words": ["editorial", "literary", "considered"],
    }

    DIRECTOR_TEST_BRIEF = {
        "content_archetype": "service_consultant",
        "inferred_vibe": "professional authority, established practice",
        "brand_metaphor": "established consultancy with thought leadership",
        "tone_words": ["authority", "established", "professional"],
    }

    ROYALTEE_BRIEF = {
        "content_archetype": "custom_apparel",
        "inferred_vibe": "urban streetwear, custom design with crown energy",
        "brand_metaphor": "wear your crown, identity-forward apparel",
        "tone_words": ["loud", "custom", "streetwear", "identity-forward"],
    }

    def test_kmj_editorial_signals_yield_editorial_font(self):
        font_id, _ = infer_font_id(self.KMJ_BRIEF)
        self.assertEqual(font_id, "brutalist_editorial")

    def test_director_test_authority_does_not_match_author(self):
        """Word-boundary fix: 'authority' must NOT trigger a 'author' hit
        on the editorial font keyword list. Director Loop Test brief
        contains 'authority' multiple times but no 'author' as a word —
        falls through to the default catch-all font."""
        font_id, _ = infer_font_id(self.DIRECTOR_TEST_BRIEF)
        self.assertEqual(font_id, "brutalist_default")

    def test_royaltee_streetwear_yields_default_font(self):
        font_id, _ = infer_font_id(self.ROYALTEE_BRIEF)
        self.assertEqual(font_id, "brutalist_default")

    def test_intensity_authority_yields_restrained(self):
        intensity, _ = infer_intensity(self.DIRECTOR_TEST_BRIEF)
        self.assertEqual(intensity, "restrained")

    def test_intensity_loud_yields_bold(self):
        intensity, _ = infer_intensity(self.ROYALTEE_BRIEF)
        self.assertEqual(intensity, "bold")

    def test_intensity_default_confident_when_no_signal(self):
        intensity, _ = infer_intensity({"inferred_vibe": "a brand"})
        self.assertEqual(intensity, "confident")

    def test_accent_default_no_accent_when_no_signal(self):
        accent_id, _ = infer_accent_id(self.ROYALTEE_BRIEF)
        self.assertEqual(accent_id, "no_accent")

    def test_accent_established_yields_code_label(self):
        accent_id, _ = infer_accent_id(self.DIRECTOR_TEST_BRIEF)
        self.assertEqual(accent_id, "code_label")

    def test_accent_monogram_yields_type_initial(self):
        accent_id, _ = infer_accent_id({"inferred_vibe": "single-initial brand letter monogram"})
        self.assertEqual(accent_id, "type_initial")

    def test_infer_all_returns_complete_dict(self):
        ce = infer_all(self.KMJ_BRIEF)
        self.assertEqual(set(ce.keys()), {"font_id", "accent_id", "intensity"})

    def test_inference_handles_non_dict_brief(self):
        """Defensive: a malformed brief (None, string, etc.) should not crash."""
        font_id, _ = infer_font_id(None)
        self.assertEqual(font_id, "brutalist_default")
        accent_id, _ = infer_accent_id("not a dict")
        self.assertEqual(accent_id, "no_accent")
        intensity, _ = infer_intensity(None)
        self.assertEqual(intensity, "confident")


# ─── Validation tests ──────────────────────────────────────────────

class ValidationTests(unittest.TestCase):
    """Per-field validation against the Studio Brut vocabulary with
    inference fallback. Composer mistakes survive shipping (better
    inferred-fallback than tossing the whole composition)."""

    BRIEF = {
        "inferred_archetype": "creative_agency",
        "inferred_vibe": "streetwear with edge",
    }

    def test_all_valid_passes_through_unchanged(self):
        out, warns = validate_creative_expression(
            {"font_id": "brutalist_sharp", "accent_id": "code_label", "intensity": "bold"},
            brief=self.BRIEF,
        )
        self.assertEqual(out, {
            "font_id": "brutalist_sharp", "accent_id": "code_label", "intensity": "bold",
        })
        self.assertEqual(warns, [])

    def test_invalid_font_id_falls_back_to_inferred(self):
        out, warns = validate_creative_expression(
            {"font_id": "brutalist_nonsense", "accent_id": "code_label", "intensity": "bold"},
            brief=self.BRIEF,
        )
        # falls back to streetwear-inferred default
        self.assertEqual(out["font_id"], "brutalist_default")
        # other fields unaffected
        self.assertEqual(out["accent_id"], "code_label")
        self.assertEqual(out["intensity"], "bold")
        self.assertTrue(any("font_id" in w for w in warns))

    def test_missing_fields_filled_from_inference(self):
        out, warns = validate_creative_expression({}, brief=self.BRIEF)
        self.assertEqual(set(out.keys()), {"font_id", "accent_id", "intensity"})
        # Missing fields without raw values present don't produce per-field
        # warnings (only invalid-value warnings).
        self.assertEqual(warns, [])

    def test_null_raw_yields_full_inference(self):
        out, warns = validate_creative_expression(None, brief=self.BRIEF)
        self.assertEqual(out["font_id"], "brutalist_default")
        self.assertEqual(out["intensity"], "confident")
        self.assertEqual(warns, [])

    def test_no_brief_uses_module_defaults(self):
        out, warns = validate_creative_expression(None, brief=None)
        self.assertEqual(out["font_id"], "brutalist_default")
        self.assertEqual(out["accent_id"], "no_accent")
        self.assertEqual(out["intensity"], "restrained")


# ─── Resolution tests (sticky-with-source) ─────────────────────────

class ResolutionTests(unittest.TestCase):
    """The sticky rule: practitioner-source fields stay; inferred-source
    or missing-source fields take Composer's choice with 'inferred'
    source marker."""

    COMPOSER_FRESH = {
        "font_id": "brutalist_mono",
        "accent_id": "code_label",
        "intensity": "bold",
    }

    def test_no_stored_state_takes_composer_with_inferred_sources(self):
        ce, meta = resolve_creative_expression(None, None, self.COMPOSER_FRESH)
        self.assertEqual(ce, self.COMPOSER_FRESH)
        self.assertEqual(meta, {
            "font_id_source": "inferred",
            "accent_id_source": "inferred",
            "intensity_source": "inferred",
        })

    def test_practitioner_pinned_field_overrides_composer(self):
        ce, meta = resolve_creative_expression(
            stored_ce={"font_id": "brutalist_sharp", "intensity": "restrained"},
            stored_meta={"font_id_source": "practitioner", "intensity_source": "practitioner"},
            composer_ce=self.COMPOSER_FRESH,
        )
        # Practitioner values win for pinned fields
        self.assertEqual(ce["font_id"], "brutalist_sharp")
        self.assertEqual(ce["intensity"], "restrained")
        # Unpinned field takes composer
        self.assertEqual(ce["accent_id"], "code_label")
        self.assertEqual(meta["font_id_source"], "practitioner")
        self.assertEqual(meta["intensity_source"], "practitioner")
        self.assertEqual(meta["accent_id_source"], "inferred")

    def test_inferred_source_does_not_pin(self):
        """A stored value with source='inferred' is treated as suggestion,
        not a pin. Composer's fresh inference wins. This is what enables
        re-inference on every build when archetype context evolves."""
        ce, meta = resolve_creative_expression(
            stored_ce={"font_id": "brutalist_default"},
            stored_meta={"font_id_source": "inferred"},
            composer_ce=self.COMPOSER_FRESH,
        )
        # Composer's fresh value wins (not the stored 'brutalist_default')
        self.assertEqual(ce["font_id"], "brutalist_mono")
        self.assertEqual(meta["font_id_source"], "inferred")

    def test_practitioner_with_no_value_falls_through(self):
        """Edge: meta marks practitioner but the actual value is missing.
        Falls through to composer rather than emitting an empty field."""
        ce, _ = resolve_creative_expression(
            stored_ce={"font_id": None},
            stored_meta={"font_id_source": "practitioner"},
            composer_ce=self.COMPOSER_FRESH,
        )
        self.assertEqual(ce["font_id"], "brutalist_mono")


# ─── Persistence tests (mocked brand_engine) ───────────────────────

class PersistenceTests(unittest.TestCase):
    """persist_creative_expression hits brand_engine.{_sb_get,_sb_patch}.
    These tests mock both to verify the PATCH body shape without
    touching prod Supabase."""

    def test_persist_writes_to_businesses_settings_brand_kit(self):
        fake_sb_get = lambda url, **kw: [{
            "settings": {
                "brand_kit": {"colors": {"primary": "#000000"}, "tagline": "loud"}
            }
        }]
        patches = []
        def fake_sb_patch(url, body):
            patches.append((url, body))

        with patch("brand_engine._sb_get", fake_sb_get), \
             patch("brand_engine._sb_patch", fake_sb_patch):
            ok = persist_creative_expression(
                "biz-1",
                ce={"font_id": "brutalist_sharp", "accent_id": "no_accent", "intensity": "confident"},
                meta={"font_id_source": "practitioner", "accent_id_source": "inferred", "intensity_source": "inferred"},
            )
        self.assertTrue(ok)
        self.assertEqual(len(patches), 1)
        url, body = patches[0]
        # PATCH targets the business row
        self.assertIn("/businesses?id=eq.biz-1", url)
        # PATCH body preserves other brand_kit keys
        bk = body["settings"]["brand_kit"]
        self.assertEqual(bk["colors"]["primary"], "#000000")
        self.assertEqual(bk["tagline"], "loud")
        # creative_expression + meta inserted
        self.assertEqual(bk["creative_expression"]["font_id"], "brutalist_sharp")
        self.assertEqual(bk["creative_expression_meta"]["font_id_source"], "practitioner")
        # Timestamp added by persist
        self.assertIn("updated_at", bk["creative_expression_meta"])

    def test_load_returns_none_none_when_no_business(self):
        with patch("brand_engine._sb_get", lambda url, **kw: []):
            ce, meta = load_stored_creative_expression("missing-biz")
        self.assertIsNone(ce)
        self.assertIsNone(meta)

    def test_load_returns_stored_values(self):
        fake_sb_get = lambda url, **kw: [{
            "settings": {
                "brand_kit": {
                    "creative_expression": {"font_id": "brutalist_sharp"},
                    "creative_expression_meta": {"font_id_source": "practitioner"},
                }
            }
        }]
        with patch("brand_engine._sb_get", fake_sb_get):
            ce, meta = load_stored_creative_expression("biz-1")
        self.assertEqual(ce, {"font_id": "brutalist_sharp"})
        self.assertEqual(meta, {"font_id_source": "practitioner"})

    def test_persist_soft_fails_on_patch_error(self):
        def raise_patch(*a, **kw):
            raise RuntimeError("supabase down")
        fake_sb_get = lambda url, **kw: [{"settings": {"brand_kit": {}}}]
        with patch("brand_engine._sb_get", fake_sb_get), \
             patch("brand_engine._sb_patch", raise_patch):
            ok = persist_creative_expression(
                "biz-1",
                ce={"font_id": "brutalist_default", "accent_id": "no_accent", "intensity": "restrained"},
                meta={"font_id_source": "inferred"},
            )
        self.assertFalse(ok)  # soft-fail, no exception escapes


if __name__ == "__main__":
    unittest.main()
