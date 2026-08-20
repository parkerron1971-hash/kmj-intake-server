"""The fold — the one screen every visitor is guaranteed to see.

Added 2026-08-20 with the wow-factor pass. Each assertion here is
something that was decided out loud or measured broken during the build,
and that a later edit could undo without anything looking obviously
wrong:

  * the statement the company is named after is set in TITLE CASE, on
    Kevin's call. Sentence case is the shape it will drift back to,
  * `.gradient-text` is flat accent everywhere else on the site by
    design; the statement is the one licensed exception, and its stops
    have to land INSIDE the words. The first pass ran the cyan end to
    92%, past the last glyph, and the line came out flat blue,
  * the panel arrives in perspective and settles level. That transform
    belongs on `.app` and NOT on `.fold-stage`: `.fold-stage::before` is
    the bloom at `z-index:-1`, and transforming its parent traps it in a
    new stacking context, putting the bloom behind the panel it lights,
  * the trace board that used to sit under the fold is gone. It shipped
    ~600 lines of Chromium-only CSS+JS to draw a wireframe directly
    beneath a full-size product screenshot,
  * `.trust` carries no top rule. A hairline plus a flat tint band
    starting on the same pixel drew a hard seam under the fold — the
    exact edge the colour field exists to dissolve.
"""
from __future__ import annotations

import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import marketing_pages


HOME = marketing_pages.render_home()


def _hero(html: str) -> str:
    """Just the hero, so a page-wide match can't fake a pass."""
    start = html.index('<section class="hero">')
    end = html.index("<section", start + 10)
    return html[start:end]


def test_statement_is_title_case():
    hero = _hero(HOME)
    assert "Every Problem" in hero
    assert "Has A Solution." in hero
    # the shape it will drift back to
    assert "Every problem" not in hero
    assert "has a solution" not in hero


def test_statement_carries_the_one_licensed_gradient():
    h1 = re.search(r"<h1[^>]*>.*?</h1>", _hero(HOME), re.S).group(0)
    assert 'class="gradient-text"' in h1, "the statement lost its gradient span"

    rule = re.search(r"\.hero h1 \.gradient-text\{(.*?)\}", HOME, re.S)
    assert rule, "no hero-specific gradient rule — the span is inheriting flat accent"
    body = rule.group(1)
    assert "linear-gradient" in body
    stops = [int(p) for p in re.findall(r"(\d+)%", body)]
    assert stops, "gradient has no explicit stops"
    assert max(stops) <= 85, (
        f"last colour stop at {max(stops)}% lands past the final glyph; "
        "the line reads flat"
    )
    assert len(stops) >= 3, "two stops is a fade, not a gradient"


def test_the_panel_settles_from_perspective():
    assert re.search(r"\.fold-stage \.app\{[^}]*perspective\(", HOME), \
        "the panel lost its entrance and is flat-on again"
    assert re.search(r"\.fold-stage\.visible \.app\{[^}]*rotateY\(0deg\)", HOME), \
        "the panel tilts but never settles level"


def test_the_tilt_is_not_on_the_stage_itself():
    """z-index:-1 bloom + a transformed parent = bloom behind the panel."""
    for rule in re.findall(r"\.fold-stage\{([^}]*)\}", HOME):
        assert "perspective(" not in rule and "rotate" not in rule, (
            "a transform on .fold-stage traps its ::before bloom in a new "
            "stacking context"
        )


def test_the_bloom_still_sits_under_the_panel():
    rule = re.search(r"\.fold-stage::before\{([^}]*)\}", HOME)
    assert rule, "the fold panel lost its bloom"
    assert "z-index:-1" in rule.group(1)


def test_the_trace_board_is_gone():
    for marker in ("bdSec", "board-sec", "board-cap", "bd-node"):
        assert marker not in HOME, f"the trace board is back ({marker})"


def test_the_fold_does_not_close_on_a_ruled_line():
    rule = re.search(r"\.trust\{([^}]*)\}", HOME)
    assert rule, ".trust rule vanished"
    assert "border-top" not in rule.group(1), \
        "a hairline under the hero re-draws the seam"
    assert "linear-gradient" in rule.group(1), \
        "the tint band starts flat again — it has to grow in from nothing"


def test_the_glow_fades_out_instead_of_being_guillotined():
    """.hero is overflow:hidden and the blobs run past its foot."""
    assert re.search(r"\.hero-glow\{[^}]*mask-image:", HOME), \
        "the bloom is clipped at the section edge"


def test_the_caption_reads_as_prose():
    """display:flex put a 9px gutter between fragments of one sentence."""
    rule = re.search(r"\.fold-cap\{([^}]*)\}", HOME)
    assert rule, ".fold-cap rule vanished"
    assert "display:flex" not in rule.group(1)


def test_wide_screens_grow_the_art_and_not_the_prose():
    assert re.search(r"@media \(min-width:2200px\)\{ \.container-xl\{max-width:\d+px", HOME), \
        "the fold panel stopped growing on wide monitors"
    container = re.search(r"[^-]\.container\{max-width:(\d+)px", HOME)
    assert container and int(container.group(1)) <= 1200, \
        "body copy got a line length nobody can read"
