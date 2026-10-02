"""The craft floor, in code (2026-10-01, the concept-layer plan).

Every defect the liaisongraphics.com study found on a hand-made site,
pinned so the builder can never ship it: ten H1s, typos in headline
text, images without alt text, a pile of type families, straight quotes,
spaced ranges, running text too small to read on a phone, centered
paragraphs, controls in the system font, a headline that never reaches
the first screen."""
import pytest

import craft_laws as cl


def _page(body: str, head: str = "") -> str:
    return (f"<!DOCTYPE html><html><head><title>t</title>{head}</head>"
            f"<body>{body}</body></html>")


# ─── headings ────────────────────────────────────────────────────────

def test_one_h1_and_no_skipped_levels():
    assert cl.check_headings(_page("<h1>A</h1><h2>B</h2><h3>C</h3><h2>D</h2>")) == []
    ten = _page("".join(f"<h1>Section {i}</h1>" for i in range(10)))
    found = " ".join(cl.check_headings(ten))
    assert "10 <h1>" in found
    assert "no <h1>" in " ".join(cl.check_headings(_page("<h2>A</h2>")))
    skip = " ".join(cl.check_headings(_page("<h1>A</h1><h2>B</h2><h4>C</h4>")))
    assert "h2 to h4" in skip


def test_headings_inside_scripts_and_styles_do_not_count():
    page = _page("<h1>A</h1><script>const t='<h1>x</h1>'</script>")
    assert cl.check_headings(page) == []


# ─── alt text and families ───────────────────────────────────────────

def test_images_need_an_alt_attribute():
    assert cl.check_alt(_page('<img src="a.jpg" alt="A fade"><img src="b.jpg" alt="">')) == []
    found = cl.check_alt(_page('<img src="a.jpg"><img src="b.jpg">'))
    assert found and "2 image(s)" in found[0]


def test_more_than_three_type_families_is_flagged():
    head = ('<link href="https://fonts.googleapis.com/css2?family=Anton&amp;'
            'family=Barlow:wght@400&amp;family=Barlow+Condensed:wght@600&amp;'
            'family=Material+Symbols+Outlined&display=swap" rel="stylesheet">')
    assert cl.font_families(_page("", head)) == ["Anton", "Barlow", "Barlow Condensed"]
    assert cl.check_families(_page("", head)) == []
    head2 = head.replace("&display", "&amp;family=Lora&amp;family=Inter&display")
    assert "5 families" in cl.check_families(_page("", head2))[0]


# ─── spelling ────────────────────────────────────────────────────────

def test_typos_are_caught_and_the_businesss_own_words_are_not():
    pytest.importorskip("spellchecker")
    page = _page("<h1>2026 FALL SEMSESTER</h1><p>Seats are avaliable now for "
                 "the braidwork intensive at Kinkorama.</p>")
    found = " ".join(cl.check_spelling(page, real_data="BUSINESS: Kinkorama braidwork"))
    assert "semsester" in found and "semester" in found
    assert "avaliable" in found
    assert "braidwork" not in found, "a word from the business's own data"
    assert "kinkorama" not in found.lower(), "a capitalized name"


def test_spelling_fails_open_without_the_library(monkeypatch):
    monkeypatch.setattr(cl, "_speller", lambda: None)
    assert cl.check_spelling(_page("<p>somethhing wrong</p>")) == []


# ─── the typographer ─────────────────────────────────────────────────

def test_the_typographer_sets_quotes_ranges_and_ellipses_in_text_only():
    page = _page('<p class="q" data-x="a \'b\'">"Best fade in town," he said. '
                 "It's open 10am - 7pm, 2021-2024, $35-$45...</p>"
                 '<script>var s = "keep \'this\'";</script>'
                 '<p>Call 216-555-0148.</p>')
    out, n = cl.typographer(page)
    assert n > 0
    assert "“Best fade in town,” he said." in out
    assert "It’s" in out
    assert "10am–7pm" in out and "2021–2024" in out and "$35–$45" in out
    assert "…" in out
    assert 'data-x="a \'b\'"' in out, "attributes are never touched"
    assert "var s = \"keep 'this'\";" in out, "scripts are never touched"
    assert "216-555-0148" in out, "a phone number is not a range"


def test_the_typographer_reads_quotes_across_inline_tags():
    out, _ = cl.typographer(_page('<p>She said <em>"hi"</em> twice.</p>'))
    assert "<em>“hi”</em>" in out


def test_the_typographer_fixes_what_the_dash_law_would_flag():
    import builder_v2
    page = _page("<p>Open Tue to Fri 10am - 7pm.</p>")
    assert builder_v2.check_grammar(page), "the spaced hyphen is a splice today"
    fixed, _ = cl.typographer(page)
    assert builder_v2.check_grammar(fixed) == []


def test_the_typographer_leaves_a_page_without_a_body_alone():
    assert cl.typographer("<p>\"x\"</p>") == ("<p>\"x\"</p>", 0)


# ─── the render ──────────────────────────────────────────────────────

def test_render_findings_in_the_builders_words():
    measures = {
        "390": {"small_text": [{"label": 'p.lede "Over five weeks"', "px": 9}],
                "tiny_text": [{"label": 'span.day "Aug 06"', "px": 6}],
                "centered_long": [],
                "control_font": {"control": 'button "Join"', "family": "arial"},
                "h1": {"visible": False, "top": 0, "vh": 844}},
        "1440": {"small_text": [], "tiny_text": [],
                 "centered_long": [{"label": 'p "At Liaison"', "lines": 8}],
                 "control_font": {"control": 'button "Join"', "family": "arial"},
                 "h1": {"visible": True, "top": 300, "vh": 900}},
    }
    found = cl.render_findings(measures)
    joined = " ".join(found)
    assert "under 14px" in joined and "9px" in joined
    assert "under 11px" in joined and "6px" in joined
    assert "centered" in joined and "8 lines" in joined
    assert joined.count("system font") == 1, "said once, not per width"
    assert "h1 headline is not visible" in joined
    assert cl.render_findings(None) == []


def test_a_headline_far_down_the_phone_screen_is_named():
    found = cl.render_findings({"390": {"h1": {"visible": True, "top": 1500, "vh": 844}}})
    assert found and "1500px down" in found[0]
    assert cl.render_findings({"1440": {"h1": {"visible": True, "top": 3000, "vh": 900}}}) == []


def test_render_js_is_one_function():
    js = cl.RENDER_JS.strip()
    assert js.startswith("() =>") and "small_text" in js and "control_font" in js
