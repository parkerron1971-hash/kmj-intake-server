"""
test_one_mind_head_and_gate.py — build quality 6/6 (2026-08-28).

Canvas / builder-v2 pages bypass page_shell, so they never carried a
canonical url or a JSON-LD record, and the quality gate graded them with
the module engine's ruler (module DOM ids, DNA fonts) — KMJ's report said
six sections were "missing" from a page that had all of them.
"""
from unittest import mock

import site_composer as sc

_META = {"description": "Braids by hand", "canonical": "https://mac.mysolutionist.app",
         "og_title": "MaCnificent Hair Co — Braids", "og_image": "",
         "jsonld": {"@context": "https://schema.org", "@type": "LocalBusiness",
                    "name": "MaCnificent Hair Co", "url": "https://mac.mysolutionist.app"}}


def test_head_injector_adds_only_what_the_author_left_out():
    html = ('<!DOCTYPE html><html><head><title>T</title>'
            '<meta name="description" content="the author wrote this">'
            '<meta property="og:title" content="T"></head><body></body></html>')
    with mock.patch.object(sc.site_modules, "build_page_meta", return_value=_META):
        out = sc._inject_missing_head_meta(html, {})
    assert out.count('<meta name="description"') == 1          # kept the author's
    assert 'content="the author wrote this"' in out
    assert 'rel="canonical" href="https://mac.mysolutionist.app"' in out
    assert 'property="og:url"' in out and 'property="og:type"' in out
    assert 'application/ld+json' in out and '"@type": "LocalBusiness"' in out
    assert out.count('property="og:title"') == 1
    # idempotent, and a document with no head is left alone
    with mock.patch.object(sc.site_modules, "build_page_meta", return_value=_META):
        assert sc._inject_missing_head_meta(out, {}) == out
        assert sc._inject_missing_head_meta("<p>no head</p>", {}) == "<p>no head</p>"


def test_head_injector_never_raises_when_meta_cannot_be_built():
    with mock.patch.object(sc.site_modules, "build_page_meta",
                           side_effect=RuntimeError("boom")):
        assert sc._inject_missing_head_meta("<html><head></head></html>", {}) \
            == "<html><head></head></html>"


def test_one_mind_checks_restate_the_two_module_rulers():
    names = [c["name"] for c in sc._one_mind_checks()]
    assert names == ["sections_rendered", "fonts_embedded"]
    assert all(c["ok"] for c in sc._one_mind_checks())
    assert "builder's law" in sc._one_mind_checks()[0]["detail"]


def test_gate_grades_a_one_mind_page_with_its_own_ruler():
    """The same spec + document: the module ruler reports the hero
    missing (no module DOM id); the one-mind ruler does not."""
    spec = [{"module": "offerings", "variant": "cards", "content": {}}]
    html = ("<html><head><title>T</title></head><body>"
            '<section id="top"><h1>Braids</h1></section></body></html>')
    ctx = {"dna": {"typography": {"heading": "Anton", "body": "Barlow"}}}
    with mock.patch.object(sc.site_modules, "build_page_meta", return_value={}):
        module_report, _ = sc._run_quality_gate("biz", spec, ctx, html)
        one_mind_report, fixes = sc._run_quality_gate("biz", spec, ctx, html,
                                                      one_mind=True)
    by = {c["name"]: c for c in module_report["checks"]}
    # the module ruler looks for the hero's module DOM id and, not finding
    # it, either calls it missing or renders it to decide it was dropped —
    # either way it is grading a page it did not write
    assert "offerings" in by["sections_rendered"]["detail"]
    assert "one-mind" not in by["sections_rendered"]["detail"]
    assert by["fonts_embedded"]["ok"] is False
    by2 = {c["name"]: c for c in one_mind_report["checks"]}
    assert by2["sections_rendered"]["ok"] is True
    assert by2["fonts_embedded"]["ok"] is True
    assert not any(f.get("fix") == "resanitize" for f in fixes)
