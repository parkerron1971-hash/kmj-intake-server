"""The home page's spine — what it says once, and where it stops.

Added 2026-08-20 with the tightening pass. Kevin: "the front page is super
long". Measured before the cuts: 9,969px desktop, 13,255px on a phone —
16.6 phone screens — 2,455 words, 11 sections, 8 numbered chapters.

The length was the symptom. The page argued the same points more than
once: three sections told the reader Chief reads their real data, and two
made the vertical-fluency case that the hero already demonstrates live in
the fold. These tests pin what came out so it cannot drift back in.
"""
from __future__ import annotations

import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import marketing_pages


def _home() -> str:
    return marketing_pages.render_home()


def _body(html: str) -> str:
    return html.split("<body>", 1)[1]


def test_the_chief_claim_is_made_once():
    """It was in the trust band, in §02, and again in §07's card."""
    body = _body(_home())
    assert body.count("reads your real") == 1, "the Chief claim is being told twice again"


def test_the_recap_section_is_gone():
    """"Why Solutionist" restated the rooms headline and the Chief claim."""
    body = _body(_home())
    assert "One workspace replacing the chaos of eight" not in body
    assert "why-grid" not in body
    # its one un-said line kept its place, in the rooms intro
    assert "no waiting on a weekly report" in body


def test_language_and_audience_are_one_argument():
    """Argued, then listed, used to be two chapters. Now it is one."""
    body = _body(_home())
    assert body.count("Why it already speaks") == 1
    assert "Built for people who serve people" not in body     # the old second head
    assert body.count("audience-pill") == 7                    # all seven verticals survived
    assert "IOLTA" in body                                     # and the scope note with them


def test_the_engine_argument_moved_to_about():
    """It answers "will you fall behind?" — an about-us question."""
    assert "The AI world moves fast" not in _home()
    assert "The AI world moves fast" in marketing_pages.render_about()


def test_the_chapters_are_no_longer_numbered():
    """01...08 announced the length before the reader scrolled a pixel."""
    body = _body(_home())
    assert 'class="sec-num"' not in body
    assert not re.search(r'sec-num[^"]*">\d+<', body)


def test_the_page_spine_survived_losing_the_numbers():
    """The rail hung off `.sec-num` and would have silently vanished.

    SPINE_SCRIPT bails at `marks.length < 2`, so deleting the numbers
    without re-keying it would have dropped a shipped affordance with no
    error anywhere.
    """
    html = _home()
    assert "querySelectorAll('[data-spine]')" in html, "the spine still hunts for .sec-num"
    assert _body(html).count("data-spine") >= 5, "not enough marks left to thread"


def test_every_price_has_a_door():
    """Three cards, zero buttons — measured on the live page 2026-08-20."""
    body = _body(_home())
    pricing = body.split('<section class="pricing">', 1)[1].split("</section>", 1)[0]
    assert pricing.count('class="price-cta') == 3
    assert pricing.count('href="/get-started"') >= 3


def test_the_page_holds_its_shape():
    """A guard on regrowth, not a style rule."""
    body = _body(_home())
    sections = len(re.findall(r"<section[ >]", body))
    assert sections <= 9, f"{sections} sections — the page is growing back"
    prose = re.sub(r"<style.*?</style>|<script.*?</script>", " ", body, flags=re.S)
    words = len(re.sub(r"<[^>]+>", " ", prose).split())
    assert words <= 2400, f"{words} words on the home page"

def test_the_page_offers_a_door_before_the_price():
    """The rooms section is the only stop between the fold and pricing.

    Measured 2026-08-20: 4,234px of page with nothing to press between
    the hero CTA and the next one. The link that already sat here went
    to /features, which is another page to read, not a way in.
    """
    body = _body(_home())
    rooms = body.split('<section class="rooms"', 1)[1].split("</section>", 1)[0]
    assert "rooms-cta" in rooms
    assert 'href="/get-started"' in rooms
    assert 'href="/features"' in rooms      # the reading door stays too


def test_every_page_that_prints_the_closer_can_style_it():
    """`.final-cta` is printed by three pages and was styled by none.

    Its only rule lived in render_home's extra_css, which no other page
    can reach; when the device band replaced home's closer the rule went
    with it and nothing changed visibly on home — the breakage was on
    /features, /compare and /about, which had never had it.
    """
    for name in ("render_features", "render_compare", "render_about",
                 "render_home", "render_faq", "render_download", "render_get_started"):
        html = getattr(marketing_pages, name)()
        if 'class="final-cta"' in html:
            assert ".final-cta{" in html, f"{name} prints the closer with no rule behind it"
