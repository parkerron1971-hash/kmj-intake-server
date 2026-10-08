"""THE DESIGN-BRIEF VERDICT (2026-10-08).

A re-render (shuffle, the catalog/gallery refresh, a one-section rework)
calls render_and_persist with no dro_status. The status itself was left as
it was, but the dro_failure branch below it treated "no status" as a
failure and stamped {"stage": "authoring", "detail": "unknown"} on a page
whose brief ran. Chief's site check then told the owner "last compose ran
WITHOUT its design brief — run a recompose": a paid rebuild for nothing.
On 2026-10-08, 3 of the 5 sites whose brief ran carried one.

Pins: a re-render leaves the stored verdict as it is; a full compose still
records or clears it; Chief's check reads a failure only when the saved
status says the brief did not run.
"""
import asyncio
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_canvas_pass import _CANVAS_DOC, _ctx, _spec  # noqa: E402


def _saved(stored=None, **kw):
    import site_composer
    saved = {}
    ctx = _ctx()
    ctx["color_source"] = "brand_kit"   # gather_context always sets one
    def _get(path):
        # the save starts from the row's site_config as stored
        if path.startswith("/business_sites?id=eq."):
            return [{"site_config": dict(stored or {}), "html_content": ""}]
        return []

    with mock.patch.object(site_composer, "_ensure_site_row",
                           return_value={"id": "s1", "site_config": dict(stored or {})}), \
            mock.patch.object(site_composer.sb_clients, "sb_get_as_service", side_effect=_get), \
            mock.patch.object(site_composer.sb_clients, "sb_patch_as_service",
                              side_effect=lambda path, payload: saved.update(
                                  payload.get("site_config") or {})), \
            mock.patch("vision_grader.grade", return_value=None), \
            mock.patch("design_register.get_invention_count", return_value=None), \
            mock.patch.object(site_composer, "_verify_inventions", return_value={}):
        site_composer.render_and_persist(
            "biz-canvas", _spec(), ctx, dro=None, _canvas_html=_CANVAS_DOC,
            _canvas_report={"engine": "builder_v2", "fallbacks": []}, **kw)
    return saved


def test_a_re_render_stamps_no_failure():
    saved = _saved(stored={"dro_status": "applied"})
    assert saved.get("dro_status") == "applied"
    assert "dro_failure" not in saved


def test_a_re_render_leaves_a_real_failure_standing():
    old = {"stage": "exception", "detail": "boom", "at": "2026-10-01T00:00:00+00:00"}
    saved = _saved(stored={"dro_status": "fallback", "dro_failure": old})
    assert saved["dro_failure"] == old


def test_a_full_compose_still_records_and_clears():
    failed = _saved(full_recompose=True, dro_status="fallback",
                    dro_failure={"stage": "signals", "detail": "thin"})
    assert failed["dro_failure"]["stage"] == "signals"
    cleared = _saved(stored={"dro_failure": {"stage": "authoring", "detail": "old"}},
                     full_recompose=True, dro_status="applied")
    assert "dro_failure" not in cleared


def _health(cfg):
    import chief_of_staff as cos
    import sb_clients
    row = {"site_config": cfg, "html_content": "<html><body>ok</body></html>",
           "status": "published"}
    with mock.patch.object(sb_clients, "sb_get_as_service", lambda p: [row]):
        return asyncio.run(cos.handle_site_health(None, {"id": "biz-1", "settings": {}}, {}))


def test_chief_ignores_a_stale_failure_beside_a_brief_that_ran():
    for status in ("applied", "applied_thin", "blueprint"):
        out = _health({"html_source": "canvas", "dro_status": status,
                       "dro_failure": {"stage": "authoring", "detail": "unknown"}})
        assert "design brief" not in out["result"], status


def test_chief_still_names_a_real_failure():
    out = _health({"html_source": "canvas", "dro_status": "fallback",
                   "dro_failure": {"stage": "exception", "detail": "boom"}})
    assert "ran WITHOUT its design brief (boom)" in out["result"]
