"""
test_builder_v2.py — Revamp Phase 2: one mind, one call, armor after.

Pins the deterministic armor (the annotator, JS/external armor), the
authorship checks (truth + coverage), parsing, and the surgical-repair
prompt shape. The live call itself rides the model_ladder and is
exercised by real builds behind the flag.
"""
import os
from unittest import mock

import builder_v2 as v2


def test_flag_default_off():
    with mock.patch.dict(os.environ, {}, clear=True):
        assert v2.enabled() is False
    with mock.patch.dict(os.environ, {"SITE_BUILDER_V2": "on"}):
        assert v2.enabled() is True


# ─── parsing ─────────────────────────────────────────────────────────

def test_parse_doc_strips_fences_and_bounds():
    raw = "```html\n<!DOCTYPE html><html><head></head><body>x</body></html>\n```"
    doc = v2._parse_doc(raw)
    assert doc.startswith("<!DOCTYPE html>") and doc.endswith("</html>")
    assert v2._parse_doc("no document here") is None


# ─── the annotator (Amendment 1: platform guarantee) ─────────────────

def test_annotator_adds_targets_and_preserves_existing():
    html = ("<html><body><h1 data-override-target='v2/f1'>Hi</h1>"
            "<p>copy one</p><p>copy two</p><li></li></body></html>")
    out, added = v2.annotate_editability(html)
    assert added == 2                       # two unstamped paragraphs
    assert 'data-override-target="v2/auto_1"' in out
    assert "v2/f1" in out                   # existing stamp untouched
    # empty <li> gets nothing
    assert out.count("data-override-target") == 3


# ─── mechanical armor ────────────────────────────────────────────────

def test_script_armor_drops_banned_keeps_clean():
    html = ("<script>fetch('https://evil')</script>"
            "<script>(function(){document.body.classList.add('x')})()</script>")
    out, dropped = v2.armor_scripts(html)
    assert "fetch" not in out and "classList" in out
    assert dropped == ["fetch("]


def test_external_armor_keeps_fonts_strips_rest():
    html = ('<link href="https://fonts.googleapis.com/css2?family=X" rel="stylesheet">'
            '<link href="https://evil.example/steal.css" rel="stylesheet">'
            '<script src="https://cdn.example/x.js"></script>'
            '<iframe src="https://x.example"></iframe><p>hi</p>')
    out, stripped = v2.armor_external(html)
    assert "fonts.googleapis.com" in out
    assert "evil.example" not in out
    assert "cdn.example" not in out and "iframe" not in out
    assert len(stripped) == 3


# ─── authorship checks ───────────────────────────────────────────────

_DATA = """BUSINESS: KMJ — type: consultant
CONTACT FORM ENDPOINT (the form's action): https://api.example/sites/b1/contact-submit
IMAGES (every one appears on the page, exact urls):
- https://x/one.png (tee)
- https://x/two.png (flyer)
[statband]
{"years": "15"}"""


def test_truth_traces_digit_runs():
    ok_html = "<html><body><p>15 years in business</p></body></html>"
    assert v2.check_truth(ok_html, _DATA) == []
    bad_html = "<html><body><p>Trusted by 400 clients</p></body></html>"
    problems = v2.check_truth(bad_html, _DATA)
    assert problems and "400" in problems[0]


def test_coverage_checks_images_nav_form_footer_endpoint():
    html = ("<html><body><nav>x</nav>"
            "<img src='https://x/one.png'><img src='https://x/two.png'>"
            "<form method='POST' action='https://api.example/sites/b1/contact-submit'>"
            "<input name='email'></form><footer>f</footer></body></html>")
    assert v2.check_coverage(html, _DATA) == []
    missing = v2.check_coverage("<html><body><p>bare</p></body></html>", _DATA)
    joined = " | ".join(missing)
    assert "https://x/one.png" in joined
    assert "<nav>" in joined or "no <nav>" in joined
    assert "no <form>" in joined and "no <footer>" in joined


# ─── the surgical repair prompt (never a re-roll) ────────────────────

def test_repair_prompt_is_surgical():
    p = v2.build_user_prompt("SPEC", "DATA",
                             violations=["number '400' untraced"],
                             prior_doc="<html>doc</html>")
    assert "SURGICAL REPAIR" in p
    assert "Fix ONLY what each violation requires" in p
    assert "number '400' untraced" in p
    assert "<html>doc</html>" in p
    # the fresh-build prompt carries the spec as law instead
    p2 = v2.build_user_prompt("SPEC TEXT", "DATA")
    assert "THE APPROVED SPEC" in p2 and "SURGICAL" not in p2
