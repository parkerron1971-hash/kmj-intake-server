# __tests__/test_dro_enums_f5.py
# ─────────────────────────────────────────────────────────────────────
# F5 (2026-07-18) — DRO enum widening. The acceptance run's collision
# regens failed TWICE per leg because the author kept reaching for
# vocabulary the schema didn't have ('editorial_columns' /
# 'modular_blocks' for hierarchy_approach, a quiet grotesque for
# body_personality — the exception register asked for the same words).
# The enums are prompt-facing metadata (validation derives them from
# schema.json automatically), so widening the schema widens both.
# ─────────────────────────────────────────────────────────────────────

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.composer.drl import passes  # noqa: E402


def _dro(hierarchy="guided_descent", body="warm_sans"):
    block = {"because": "x", "from_signals": []}
    return {"decisions": {
        "palette": dict(block),
        "typography": {**block, "body_personality": body},
        "layout": {**block, "hierarchy_approach": hierarchy},
        "motion": dict(block),
        "hero_concept": dict(block),
        "whitespace": dict(block),
        "voice_to_visual": dict(block),
    }}


class TestWidenedEnums(unittest.TestCase):
    def test_editorial_columns_accepted(self):
        self.assertEqual(passes._validate_dro(_dro(hierarchy="editorial_columns")), [])

    def test_modular_blocks_accepted(self):
        self.assertEqual(passes._validate_dro(_dro(hierarchy="modular_blocks")), [])

    def test_plain_grotesque_accepted(self):
        self.assertEqual(passes._validate_dro(_dro(body="plain_grotesque")), [])

    def test_original_values_still_accepted(self):
        self.assertEqual(passes._validate_dro(_dro()), [])

    def test_bogus_values_neutralized_not_fatal(self):
        # Contract changed 2026-07-20 (enum coercion): bogus enum values no
        # longer fail the DRO — that rejection path discarded a well-aligned
        # DRO over one invented value in production and dropped the build to
        # the minimal bland DRO. Now they are fuzzy-snapped or dropped, the
        # DRO validates, and each coercion is logged.
        dro = _dro(hierarchy="swiss_brutalism")
        self.assertEqual(passes._validate_dro(dro), [])
        self.assertNotEqual(dro["decisions"]["layout"].get("hierarchy_approach"),
                            "swiss_brutalism")
        dro = _dro(body="comic_sans_energy")
        self.assertEqual(passes._validate_dro(dro), [])
        self.assertNotEqual(dro["decisions"]["typography"].get("body_personality"),
                            "comic_sans_energy")


if __name__ == "__main__":
    unittest.main()
