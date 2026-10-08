"""BLUEPRINT FIRST (2026-10-07, the build-cost plan, step 4).

Kevin: "maintain the quality with decreasing the cost". Every build ran the
design-rationale passes (two to four directions, a signal read and a judge,
about 55c) before the one-mind builder, which authors from the approved
blueprint alone and never read them. Pins: with an approved blueprint and
the builder on, the builder goes first; when it hands back a page the
passes never run, the page is saved with design status "blueprint" and no
failure, and the build is billed exactly as before (the copy spec still
runs, and the price is counted from it). When the builder falls back, the
passes run once and the ladder continues, and the builder is not run a
second time. With no blueprint, or BLUEPRINT_FIRST=off, the old order holds.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_canvas_pass import _ctx, _dro, _spec  # noqa: E402

BLUEPRINT = "0. THE CONCEPT\nINTENSITY: plain\n1. OVERVIEW\nA calm page for a furniture maker."


class _Run:
    def __init__(self, v2_html="<html>one-mind page</html>", spec_text=BLUEPRINT, env=None):
        self.v2_html, self.spec_text, self.env = v2_html, spec_text, env or {}
        self.order, self.rows = [], []

    def go(self):
        import site_composer
        order = self.order

        def _v2(spec, ctx, biz, progress_cb=None):
            order.append("builder")
            return {"html": self.v2_html, "report": {"engine": "builder_v2", "fallbacks": []}}

        def _dro_fn(*a, **k):
            order.append("directions")
            return _dro(), None

        def _copy(ctx, notes, dro=None):
            order.append(("copy", (dro or {}).get("id")))
            return _spec()

        env = {"SITE_BUILDER_V2": "on", **self.env}
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(site_composer, "gather_context", return_value=_ctx()), \
                mock.patch("spec_author.approved_spec_text", return_value=self.spec_text), \
                mock.patch("no_card_trial.check_build", return_value=None), \
                mock.patch("no_card_trial.blocks", return_value=None), \
                mock.patch.object(site_composer, "_maybe_analyze_references", return_value=None), \
                mock.patch("builder_v2.enabled", return_value=True), \
                mock.patch("builder_v2.run_builder_v2", side_effect=_v2), \
                mock.patch("agents.composer.drl.passes.produce_dro", side_effect=_dro_fn), \
                mock.patch.object(site_composer, "compose_spec_llm", side_effect=_copy), \
                mock.patch.object(site_composer, "_ensure_site_row",
                                  return_value={"id": "s1", "site_config": {}}), \
                mock.patch.object(site_composer, "build_offer_page", return_value=False), \
                mock.patch("canvas.run_canvas", return_value={"html": None, "report": {}}), \
                mock.patch("api_usage_logger.log_api_usage_sync",
                           side_effect=lambda **kw: self.rows.append(kw)), \
                mock.patch.object(site_composer, "render_and_persist",
                                  return_value={"vision_verdict": None, "quality_report": {}}) as rp:
            os.environ.pop("SITE_CANVAS", None)
            site_composer.compose_site("biz-canvas")
        self.persist = rp.call_args.kwargs
        self.spec_len = len(rp.call_args.args[1])
        return self


class TestBlueprintFirst(unittest.TestCase):
    def test_the_builder_goes_first_and_the_direction_passes_never_run(self):
        r = _Run().go()
        self.assertEqual(r.order[0], "builder")
        self.assertNotIn("directions", r.order)
        self.assertIn(("copy", None), r.order, "the copy spec still runs, without a rationale")
        self.assertEqual(r.persist["_canvas_html"], "<html>one-mind page</html>")
        self.assertEqual(r.persist["dro_status"], "blueprint")
        self.assertIsNone(r.persist["dro_failure"])

    def test_what_an_owner_pays_is_counted_exactly_as_before(self):
        import pricing_config
        r = _Run().go()
        marker = [row for row in r.rows if row.get("task_type") == "site_build_marker"]
        self.assertEqual(len(marker), 1, "one billable row for the build")
        self.assertEqual(marker[0]["units"], pricing_config.price_for_build(r.spec_len))

    def test_a_fallback_runs_the_passes_once_and_never_builds_twice(self):
        r = _Run(v2_html=None).go()
        self.assertEqual(r.order.count("builder"), 1, "the builder is not run a second time")
        self.assertEqual(r.order[:2], ["builder", "directions"])
        self.assertIn(("copy", "dro-1"), r.order, "the ladder gets its rationale")
        self.assertIsNone(r.persist["_canvas_html"])
        self.assertEqual(r.persist["dro_status"], "applied")

    def test_no_blueprint_keeps_the_old_order(self):
        r = _Run(spec_text="").go()
        self.assertNotIn("builder", r.order)
        self.assertEqual(r.order[0], "directions")

    def test_the_switch_restores_the_old_order(self):
        r = _Run(env={"BLUEPRINT_FIRST": "off"}).go()
        self.assertEqual(r.order[:2], ["directions", ("copy", "dro-1")])
        self.assertEqual(r.order.count("builder"), 1)
        self.assertEqual(r.persist["_canvas_html"], "<html>one-mind page</html>")
        self.assertEqual(r.persist["dro_status"], "applied")


class TestBlueprintStatusIsSaved(unittest.TestCase):
    """The tests above mock render_and_persist, so they see what it is
    handed, not what it saves. These run the real save: a blueprint build
    must not store a design-brief failure, or Chief's site check reads it
    as "last compose ran WITHOUT its design brief" and asks for a paid
    recompose (2026-10-07)."""

    def _saved(self, dro_status, dro_failure=None, stored=None):
        import site_composer
        from test_canvas_pass import _CANVAS_DOC
        saved = {}
        ctx = _ctx()
        ctx["color_source"] = "brand_kit"   # gather_context always sets one
        with mock.patch.object(site_composer, "_ensure_site_row",
                               return_value={"id": "s1", "site_config": dict(stored or {})}), \
                mock.patch.object(site_composer.sb_clients, "sb_get_as_service", return_value=[]), \
                mock.patch.object(site_composer.sb_clients, "sb_patch_as_service",
                                  side_effect=lambda path, payload: saved.update(
                                      payload.get("site_config") or {})), \
                mock.patch("vision_grader.grade", return_value=None), \
                mock.patch("design_register.get_invention_count", return_value=None), \
                mock.patch.object(site_composer, "_verify_inventions", return_value={}):
            site_composer.render_and_persist(
                "biz-canvas", _spec(), ctx, dro=None, full_recompose=True,
                dro_status=dro_status, dro_failure=dro_failure,
                _canvas_html=_CANVAS_DOC,
                _canvas_report={"engine": "builder_v2", "fallbacks": []})
        return saved

    def test_a_blueprint_build_saves_no_failure(self):
        saved = self._saved("blueprint")
        self.assertEqual(saved["dro_status"], "blueprint")
        self.assertNotIn("dro_failure", saved)

    def test_a_blueprint_build_clears_an_old_failure(self):
        saved = self._saved("blueprint", stored={"dro_failure": {"stage": "authoring",
                                                                 "detail": "old"}})
        self.assertNotIn("dro_failure", saved)

    def test_a_real_fallback_still_records_why(self):
        saved = self._saved("fallback", {"stage": "exception", "detail": "boom"})
        self.assertEqual(saved["dro_failure"]["stage"], "exception")
        self.assertEqual(saved["dro_failure"]["detail"], "boom")


if __name__ == "__main__":
    unittest.main()
