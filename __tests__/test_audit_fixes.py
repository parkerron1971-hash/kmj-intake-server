"""
test_audit_fixes.py — the builder audit (2026-07-24).

Kevin: "we keep having the same issue with designs." The audit found the
mechanisms that degrade a finished design AFTER the author is done:

  1. color_role overrides had NO reconciliation — tweaks made against an
     OLD design repainted every NEW design (!important, every render,
     v2/auto_N positional key collisions across designs).
  2. the bs4 annotator re-serialized the whole document and lowercased
     case-sensitive SVG attrs (pinned in test_builder_v2).
  3. check_truth attacked design numerals (pinned in test_builder_v2).

These tests pin the color-override half of fix 1: stale rows must never
reach the page.
"""
from unittest import mock

import site_composer as sc

_HTML = "<html><head></head><body><p data-override-target='v2/auto_1'>x</p></body></html>"


def _lookup(rows):
    return mock.patch(
        "agents.override_system.override_storage.overrides_as_lookup",
        return_value=rows)


def test_color_overrides_skip_stale_rows():
    rows = {
        "v2/auto_1": {"override_value": "#ff0000", "status": "stale"},
        "v2/auto_2": {"override_value": "#00ff00", "status": "active"},
        "v2/auto_3": {"override_value": "#0000ff"},   # legacy: no status → active
    }
    with _lookup(rows):
        out = sc._inject_color_overrides(_HTML, "b1")
    assert "#ff0000" not in out                    # stale row never applied
    assert "#00ff00" in out and "#0000ff" in out   # active + legacy still work


def test_color_overrides_all_stale_leaves_document_untouched():
    rows = {"v2/auto_1": {"override_value": "#ff0000", "status": "stale"}}
    with _lookup(rows):
        out = sc._inject_color_overrides(_HTML, "b1")
    assert out == _HTML                            # no style block at all


# ─── canvas protection (the 05:00 incident, 2026-07-25) ─────────────
# A retired Smart Sites banner click rerouted into compose_site(
# use_llm=False) and a sub-second module compose overwrote the paid
# one-mind build, deleting the stored canvas. A no-LLM compose must
# REFUSE to touch a canvas-authored page.

def _canvas_row(cfg):
    return mock.patch.object(
        sc.sb_clients, "sb_get_as_service",
        return_value=[{"site_config": cfg}])


def test_no_llm_compose_refuses_canvas_authored_page():
    with _canvas_row({"html_source": "canvas"}):
        out = sc.compose_site("b1", use_llm=False)
    assert out.get("skipped") == "canvas-protected"


def test_no_llm_compose_refuses_when_canvas_doc_stored():
    with _canvas_row({"html_source": "module-composer",
                      "canvas": {"html": "<html>doc</html>"}}):
        out = sc.compose_site("b1", use_llm=False)
    assert out.get("skipped") == "canvas-protected"
