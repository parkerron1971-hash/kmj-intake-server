"""Pass 4.0h cleanup Item 2 — run_build_loop retry-trigger regression tests.

Locks in the two-branch retry gate that Pass 4.0h.y added to
`run_build_loop`:

  * "critique_failed"   — builder_v1 produced valid html but critique
                          returned verdict="fail". v2 retries with the
                          critique violations as punch_list.
  * "validation_failed" — builder_v1 returned None due to studio_html_validator
                          rejection. v2 retries with a synthesized
                          punch_list derived from builder_v1_warnings.

Without this guard widening, validator rejections (inline event handlers,
external scripts, etc.) killed builds with no retry — see Pass 4.0h.x
verification incident for the originating bug shape.

All upstream LLM/DB dependencies are mocked. Tests run in milliseconds,
no LLM cost, no Supabase access, no Builder Agent invocation.

Run via:
  python -m agents.director_agent.__tests__.test_build_with_loop
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


# ─── Fixtures ──────────────────────────────────────────────────────

# Minimal-shape returns from each upstream dependency so run_build_loop
# progresses past steps 1-3 and into the builder/critique/retry zone.
ENRICHED_BRIEF_FIXTURE = {
    "inferred_vibe": "test vibe",
    "content_archetype": "creative_agency",
    "palette_roles": {"primary_bg": "#FFFFFF"},
}

DESIGNER_REC_FIXTURE = {
    "strand_a_id": "editorial",
    "ratio_a": 60,
    "sub_strand_id": "editorial-magazine",
    "layout_archetype": "editorial-scroll",
}

BRIEF_FIXTURE = {
    "conceptName": "Test Concept",
    "tagline": "Test tagline",
    "blendRatio": "60% Editorial / 40% Luxury",
    "section_names": ["Hero", "About", "Services"],
}

RUBRIC_FIXTURE = {
    "module_id": "cinematic_authority",
    "rubric_version": "test",
    "layer_1_deterministic": [],
    "layer_2_llm_judged": [],
}

VALID_HTML = (
    "<!DOCTYPE html><html><head><title>Test</title>"
    "<style>body{font-family:sans-serif}</style></head>"
    "<body><section data-section='hero'><h1>Hero</h1></section></body></html>"
)

CRITIQUE_PASS = {
    "summary": {
        "verdict": "pass",
        "total": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
    },
    "violations": [],
    "rubric_loaded": True,
    "rubric_version": "test",
}

CRITIQUE_FAIL_VIOLATIONS = [
    {
        "rule_id": "hero_h1_size",
        "severity": "HIGH",
        "description": "h1 too small",
        "fix_hint": "use clamp(3.7rem, 9vw, 5.4rem)",
    },
    {
        "rule_id": "hero_h1_weight",
        "severity": "HIGH",
        "description": "h1 weight too light",
        "fix_hint": "use 900",
    },
]

CRITIQUE_FAIL = {
    "summary": {
        "verdict": "fail",
        "total": 2,
        "high": 2,
        "medium": 0,
        "low": 0,
    },
    "violations": CRITIQUE_FAIL_VIOLATIONS,
    "rubric_loaded": True,
    "rubric_version": "test",
}

CRITIQUE_FAIL_EMPTY_HTML = {
    "summary": {
        "verdict": "fail",
        "total": 1,
        "high": 1,
        "medium": 0,
        "low": 0,
    },
    "violations": [
        {"rule_id": "empty_output", "severity": "HIGH", "description": "no html"},
    ],
    "rubric_loaded": True,
    "rubric_version": "test",
}

VALIDATION_WARNINGS = [
    "Banned pattern: Inline event handlers not allowed",
    "Banned pattern: Inline <script> not allowed",
]


# ─── Test class ────────────────────────────────────────────────────

class RunBuildLoopRetryTriggerTests(unittest.TestCase):
    """The setUp installs happy-path mocks for everything upstream
    of builder_v1 so each test only has to control build_html +
    critique_site. addCleanup ensures patches always tear down even
    on test failure."""

    def setUp(self):
        # Patch in-function imports at their source modules. run_build_loop
        # does `from <module> import <fn>` inside the function body, so
        # patching the source-module attribute is what catches the call.
        self._patch("agents.sparse_input_enrichment.enrich_intake",
                    return_value=ENRICHED_BRIEF_FIXTURE)
        self._patch("studio_designer_agent.generate_design_recommendation",
                    return_value=(DESIGNER_REC_FIXTURE, None))
        self._patch("studio_brief_expander.expand_design_brief",
                    return_value=(BRIEF_FIXTURE, None))
        self._patch("agents.design_intelligence.rubrics.load_rubric",
                    return_value=RUBRIC_FIXTURE)

        # build_html and critique_site are controlled per-test via the
        # `self.build_html` / `self.critique_site` MagicMocks below.
        self.build_html = MagicMock()
        self.critique_site = MagicMock()
        self._patch("studio_builder_agent.build_html",
                    new=self.build_html)
        self._patch("agents.director_agent.critique.critique_site",
                    new=self.critique_site)

    def _patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        patcher.start()
        self.addCleanup(patcher.stop)

    # ── helpers ──────────────────────────────────────────────────

    def _run_loop(self, max_attempts=2):
        # Import inside the test so the patches above are already active
        # when run_build_loop's inside-function `from ... import ...`
        # statements execute.
        from agents.director_agent.build_with_loop import run_build_loop
        return run_build_loop(
            business_name="Test Co",
            module_id="cinematic_authority",
            description="test",
            max_attempts=max_attempts,
            include_html=False,
            business_id=None,  # skip persistence + slot_population
        )

    def _step(self, result, step_name):
        for s in result.get("steps", []):
            if s.get("step") == step_name:
                return s
        return None

    # ── tests ────────────────────────────────────────────────────

    def test_v1_success_no_retry(self):
        """builder_v1 returns valid html + critique passes → no v2 attempt.
        regenerated must be False; builder_v2 must not be called."""
        self.build_html.return_value = (VALID_HTML, None, [])
        self.critique_site.return_value = CRITIQUE_PASS

        result = self._run_loop()

        self.assertEqual(self.build_html.call_count, 1, "v2 must not run")
        self.assertEqual(self.critique_site.call_count, 1, "critique_v2 must not run")
        self.assertFalse(result.get("regenerated"))
        self.assertEqual(result.get("status"), "success")
        self.assertIsNone(self._step(result, "builder_v2"))

    def test_v1_fail_critique_v2_retries_with_critique_punchlist(self):
        """builder_v1 valid html + critique fail → v2 runs via the
        critique_failed path, receives the critique violations as punch_list."""
        self.build_html.side_effect = [
            (VALID_HTML, None, []),         # v1
            (VALID_HTML, None, []),         # v2
        ]
        self.critique_site.side_effect = [
            CRITIQUE_FAIL,                  # critique_v1 → fail
            CRITIQUE_PASS,                  # critique_v2 → pass
        ]

        result = self._run_loop()

        self.assertEqual(self.build_html.call_count, 2, "v2 must run")
        self.assertTrue(result.get("regenerated"))

        # v2 was called with the v1 critique violations as punch_list
        v2_call = self.build_html.call_args_list[1]
        v2_punch_list = v2_call.kwargs.get("punch_list")
        self.assertEqual(v2_punch_list, CRITIQUE_FAIL_VIOLATIONS)

        # Audit step records retry_trigger
        v2_step = self._step(result, "builder_v2")
        self.assertIsNotNone(v2_step)
        self.assertEqual(v2_step["result"]["retry_trigger"], "critique_failed")
        self.assertEqual(v2_step["result"]["punch_list_size"],
                         len(CRITIQUE_FAIL_VIOLATIONS))

    def test_v1_none_validation_v2_retries_with_validation_punchlist(self):
        """builder_v1 returns None with validator warnings → v2 runs via
        the validation_failed path with a synthesized punch_list."""
        self.build_html.side_effect = [
            (None, "HTML failed validation", VALIDATION_WARNINGS),  # v1
            (VALID_HTML, None, []),                                   # v2
        ]
        self.critique_site.side_effect = [
            CRITIQUE_FAIL_EMPTY_HTML,       # critique_v1 on empty html
            CRITIQUE_PASS,                  # critique_v2
        ]

        result = self._run_loop()

        self.assertEqual(self.build_html.call_count, 2, "v2 must run")
        self.assertTrue(result.get("regenerated"))

        # v2's punch_list is synthesized from the VALIDATION warnings,
        # NOT from critique_v1's violations (even though critique ran).
        v2_call = self.build_html.call_args_list[1]
        v2_punch_list = v2_call.kwargs.get("punch_list")
        self.assertEqual(len(v2_punch_list), len(VALIDATION_WARNINGS))
        for item in v2_punch_list:
            self.assertEqual(item["severity"], "HIGH")
            self.assertEqual(item["rule_id"], "html_validation")
            self.assertIn("description", item)
            self.assertIn("fix_hint", item)
        # Each validator warning text appears in one of the descriptions
        for warn in VALIDATION_WARNINGS:
            self.assertTrue(
                any(warn in item["description"] for item in v2_punch_list),
                f"warning {warn!r} missing from synthesized punch_list",
            )

        v2_step = self._step(result, "builder_v2")
        self.assertEqual(v2_step["result"]["retry_trigger"], "validation_failed")

    def test_v1_none_no_warnings_no_retry(self):
        """Edge case: builder_v1 returns None with NO warnings (e.g. the
        builder hard-crashed before validation could produce warnings).
        No synthesized punch_list → no v2 retry; build ends at v1."""
        self.build_html.return_value = (None, "Prompt construction failed", [])
        self.critique_site.return_value = CRITIQUE_FAIL_EMPTY_HTML

        result = self._run_loop()

        self.assertEqual(self.build_html.call_count, 1, "v2 must NOT run")
        self.assertFalse(result.get("regenerated"))
        self.assertIsNone(self._step(result, "builder_v2"))

    def test_max_attempts_1_never_retries(self):
        """max_attempts=1 → v2 never runs even when v1 fails critique.
        Caller asked for one shot; we honor that contract."""
        self.build_html.return_value = (VALID_HTML, None, [])
        self.critique_site.return_value = CRITIQUE_FAIL

        result = self._run_loop(max_attempts=1)

        self.assertEqual(self.build_html.call_count, 1, "v2 must NOT run on max_attempts=1")
        self.assertFalse(result.get("regenerated"))
        self.assertIsNone(self._step(result, "builder_v2"))

    def test_v2_audit_logs_retry_trigger_both_paths(self):
        """retry_trigger value flows accurately into the builder_v2 audit
        step for BOTH paths. Covers the same surface as the two retry
        tests above but asserts only on the audit-trail observable so
        a future refactor that changes punch_list shape can't drift the
        audit log silently."""

        # Path A: critique_failed
        self.build_html.side_effect = [
            (VALID_HTML, None, []),
            (VALID_HTML, None, []),
        ]
        self.critique_site.side_effect = [CRITIQUE_FAIL, CRITIQUE_PASS]
        result_a = self._run_loop()
        self.assertEqual(
            self._step(result_a, "builder_v2")["result"]["retry_trigger"],
            "critique_failed",
        )

        # Reset mocks for path B
        self.build_html.reset_mock()
        self.build_html.side_effect = [
            (None, "HTML failed validation", VALIDATION_WARNINGS),
            (VALID_HTML, None, []),
        ]
        self.critique_site.reset_mock()
        self.critique_site.side_effect = [CRITIQUE_FAIL_EMPTY_HTML, CRITIQUE_PASS]
        result_b = self._run_loop()
        self.assertEqual(
            self._step(result_b, "builder_v2")["result"]["retry_trigger"],
            "validation_failed",
        )


if __name__ == "__main__":
    unittest.main()
