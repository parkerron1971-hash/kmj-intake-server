"""THE KIT (2026-11-10, a test): pages assembled from finished sections.

Pins the rules that make an assembled page safe to put a business's name on:
facts only from the data, every ground readable, a custom section that can't
reach outside itself, and the bugs the grader found in the test runs.
"""
import json
import re
from pathlib import Path

import site_kit as kit

FIX = Path(__file__).resolve().parent.parent / "scripts" / "fixtures"


def _fx(name="marrow_and_steel.json"):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


WORDS = {
    "tokens": {"bg": "#121010", "surface": "#1c1816", "deep": "#0f1513", "text": "#ede6da",
               "accent": "#d9a35a", "display_font": "Big Shoulders Display", "display_upper": True},
    "hours_rows": [{"day": 2, "open": "10:00", "close": "19:00"}, {"day": 0, "closed": True}],
    "hero": {"lines": ["Sharp fades.", "Clean lineups.", "Two chairs in Lakewood."], "accent_word": "Sharp"},
    "board": {"headline": "Every price on the wall", "board_title": "Book a chair now"},
    "nav": [{"label": "Prices", "target": "board"}, {"label": "Nowhere", "target": "missing"}],
}


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


# ─── facts come only from the data ───────────────────────────────────

def test_prices_and_people_come_from_the_data_not_the_words():
    fx = _fx()
    words = {**WORDS, "board": {**WORDS["board"], "rows": [["Classic Cut", "$9"]]}}
    html = kit.assemble(fx, words)
    assert not re.search(r"\$9(?!\d)", _text(html))      # a price the data doesn't hold
    for o in fx["offerings"]:
        assert kit.e(o["name"]) in html


def test_board_rows_from_the_blueprint_must_be_facts():
    data = "Tuesday 4 to 9 pm at Ironworks Brewery, 1200 E 6th St."
    assert kit.rows_are_facts([["Tuesday", "4 to 9 pm at Ironworks Brewery"]], data)
    assert not kit.rows_are_facts([["Tuesday", "5 to 10 pm"]], data)        # a time it doesn't hold
    assert not kit.rows_are_facts([["Wednesday", "Riverside Pavilion"]], data)
    menu = '{"name": "Classic Cut", "price": 35} {"name": "Skin Fade", "price": 45} Sat 9am to 4pm'
    assert kit.rows_are_facts([["Classic Cut", "$35"]], menu)
    assert not kit.rows_are_facts([["Classic Cut", "$9"]], menu)       # 9 is only in the hours
    assert not kit.rows_are_facts([["Classic Cut", "$45"]], menu)      # a real price, the wrong service


def test_a_long_fact_is_never_cut_mid_word():
    fx = _fx("smoke_signal_bbq.json")
    row = ["Tuesday", "4 to 9 pm at Ironworks Brewery, 1200 E 6th St"]
    html = kit.assemble(fx, {**WORDS, "board": {"rows": [row]}})
    assert "1200 E 6TH ST" in html
    assert "k-board-sub" in html                            # split onto its own groove, not clipped


def test_hours_rows_are_validated():
    rows = kit.clean_hours([{"day": 9, "open": "10:00", "close": "11:00"},
                            {"day": 1, "open": "19:00", "close": "10:00"},
                            {"day": 2, "open": "10:00", "close": "19:00"}, {"day": 0, "closed": True}])
    assert rows == [{"day": 2, "open": "10:00", "close": "19:00"}, {"day": 0, "closed": True}]


def test_a_section_with_no_data_is_left_out():
    fx = _fx()
    fx["testimonials"] = []
    fx["gallery"] = []
    html = kit.assemble(fx, WORDS)
    assert 'id="proof"' not in html and 'id="work"' not in html
    assert 'href="#missing"' not in html                    # nav never points at nothing


# ─── every ground reads ──────────────────────────────────────────────

def test_a_light_look_gets_light_ink_on_its_dark_chapters():
    t = kit.tokens({"bg": "#f3ece0", "text": "#1e1915", "deep": "#2a211c", "band": "#2a211c",
                    "second": "#6e6258", "accent": "#b4432a", "on_accent": "#1e1915"})
    assert kit.contrast(t["ink_deep"], "#2a211c") >= 4.5
    assert kit.contrast(t["ink_band"], "#2a211c") >= 4.5
    assert kit.contrast(t["second_deep"], "#2a211c") >= 3
    assert kit.contrast(t["on_accent"], "#b4432a") >= 4.5


def test_bad_tokens_fall_back():
    t = kit.tokens({"bg": "red", "display_font": "Comic</style><script>", "display_weight": "x"})
    assert t["bg"] == kit.DEFAULT_TOKENS["bg"]
    assert t["display_font"] == kit.DEFAULT_TOKENS["display_font"]


def test_a_lowercase_display_face_gets_room_between_lines():
    assert "--k-lh2:1.08" in kit.root_css(kit.tokens({"display_upper": False}))
    assert "--k-lh2:.95" in kit.root_css(kit.tokens({"display_upper": True}))


# ─── the page's parts ────────────────────────────────────────────────

def test_a_third_headline_line_is_set_as_its_tail():
    h = kit._headline(["Sharp fades.", "Clean lineups.", "Two chairs in Lakewood."], "Sharp")
    assert '<span class="k-acc">Sharp</span>' in h
    assert '<span class="k-h1-tail">Two chairs in Lakewood.</span>' in h


def test_the_board_title_is_never_a_call_to_action():
    html = kit.assemble(_fx(), WORDS)
    assert "Book a chair now" not in _text(html)


def test_one_hours_card_a_page():
    fx = _fx("smoke_signal_bbq.json")
    html = kit.assemble(fx, {**WORDS, "hours_rows": [{"day": 2, "open": "16:00", "close": "21:00"}]})
    assert html.count('data-sx-object="hours-card"') == 1


def test_the_dock_says_a_fact():
    html = kit.assemble(_fx(), WORDS)
    assert 'class="k-dock"' in html and "From $" in html


def test_the_photo_hero_puts_the_words_before_the_photo():
    html = kit.assemble(_fx(), WORDS)
    hero = html[html.index('class="k-hero'):]
    assert hero.index("k-hero-copy") < hero.index("k-hero-photo")


def test_the_page_wears_the_library_objects_it_uses():
    html = kit.assemble(_fx(), WORDS)
    assert 'data-sx-object="letterboard"' in html
    assert "data-sx-library" in html or "sxo-board" in html


# ─── a custom section stays inside itself ────────────────────────────

def test_a_custom_section_cannot_reach_outside():
    ok, _ = kit.custom_ok('<section class="k-custom k-custom-stops" id="stops"><p>x</p></section>',
                          ".k-custom-stops p{color:var(--k-text)}@media (max-width:760px){.k-custom-stops p{margin:0}}")
    assert ok
    for html, css in (('<section><script>alert(1)</script></section>', ""),
                      ('<section onclick="x()"></section>', ""),
                      ('<section></section>', "body{display:none}"),
                      ('<section></section>', ".k-custom-x{background:url(https://evil.example/a.png)}")):
        assert not kit.custom_ok(html, css)[0], (html, css)


def test_a_custom_section_that_fails_is_left_out():
    bad = {"id": "stops", "after": "board", "html": "<section><script></script></section>", "css": ""}
    html = kit.assemble(_fx(), WORDS, [bad])
    assert "<section><script>" not in html
