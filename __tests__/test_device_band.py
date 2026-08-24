"""The device band is the home page's closer — pin what it promises.

Added 2026-08-19 with the band itself. Every assertion here corresponds
to something that was decided deliberately or was measured broken during
the build, and would be silently easy to undo later:

  * it REPLACED `.final-cta`; the two are the same job and stacking them
    asks for the same click twice,
  * it is the one section on the page with no `.reveal` — the art has to
    read as already running, not as something that woke up for you,
  * the scene must run off BOTH edges at every width, which on a wide
    monitor is a product of two dials (stage width x scale). The first
    two passes failed exactly here: at 2560 the scene sat politely inside
    the window with 440px of bare ground on each side,
  * the drafted purchase order is the one thing slot C exists to show, so
    it lives on the LEFT of a screen that bleeds off the RIGHT. Anchored
    the other way, 21px of it survived at 2560,
  * nobody real appears in it.
"""
from __future__ import annotations

import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import marketing_pages


def _band(html: str) -> str:
    """Just the band's markup, so page-wide matches can't fake a pass."""
    assert '<section class="dv">' in html, "the device band is gone from home"
    return html.split('<section class="dv">', 1)[1].split("</section>", 1)[0]


def test_band_replaced_the_old_closer():
    html = marketing_pages.render_home()
    assert '<section class="dv">' in html
    # the class may survive in comments; a rendered section must not
    assert 'class="final-cta"' not in html


def test_band_carries_both_ctas_and_says_what_starting_costs():
    """The band inherited a "currently in private beta" line from the
    .final-cta it replaced. The doors opened on 2026-08-24, so the line
    it carries now is the trial — still the same job: the closer states
    the terms, it does not just shout."""
    band = _band(marketing_pages.render_home())
    assert 'href="/start"' in band                # start the trial
    assert 'href="/download"' in band             # get the app — Kevin's pick
    assert "days free" in band                    # the terms, stated
    assert "private beta" not in band


def test_band_never_fades_in():
    """Deliberate exception to the page's own convention."""
    assert "reveal" not in _band(marketing_pages.render_home())


def test_band_shows_two_desktops_and_a_phone():
    band = _band(marketing_pages.render_home())
    for slot in ("dv-slot dv-a", "dv-slot dv-c", "dv-slot dv-b"):
        assert slot in band
    assert "dv-fone" in band                      # the phone is a real frame
    assert band.count('class="app"') == 2         # both desktops are replica kit


def test_every_wide_step_still_bleeds_off_both_edges():
    """stage x scale must stay ahead of the viewport the step serves.

    This is the invariant the first two passes broke. A new monitor size
    added without a matching stage width lands here rather than on the
    live page.
    """
    css = marketing_pages.DEVICE_BAND_CSS
    steps = re.findall(
        r"@media \(min-width:(\d+)px\)\{\s*\.dv\{--dv-stage:(\d+)px;--dv-scale:([\d.]+);\}",
        css,
    )
    assert len(steps) >= 5, "the wide-monitor ladder vanished"
    for width, stage, scale in steps:
        effective = int(stage) * float(scale)
        assert effective > int(width) + 100, (
            f"at {width}px the scene is only {effective:.0f}px wide — "
            "it would sit inside the window instead of running off it"
        )
    # and the ladder has to reach far enough up to cover an ultrawide desk
    assert max(int(w) for w, _, _ in steps) >= 3000


def test_the_drafted_order_is_anchored_away_from_the_cropped_edge():
    """Slot C bleeds off the right, so its payload sits on the left."""
    css = marketing_pages.DEVICE_BAND_CSS
    rule = css.split(".dv-po{", 1)[1].split("}", 1)[0]
    assert "left:9px" in rule
    assert "right:" not in rule, "the PO drawer is back on the cropped edge"


def test_reduced_motion_stops_every_loop():
    css = marketing_pages.DEVICE_BAND_CSS
    block = css.split("@media (prefers-reduced-motion: reduce)", 1)[1]
    for loop in ("dv-drop", "dv-po", "dv-cursor", "dv-say", "dv-tap", "dv-glow i"):
        assert loop in block, f"{loop} keeps moving for someone who asked it not to"


def test_the_order_adds_up():
    """A wrong total on a screenshot that runs forever is a real bug."""
    band = _band(marketing_pages.render_home())
    lines = re.findall(r"<b>(\d+) &times; \$([\d.]+)</b>", band)
    assert lines, "the drafted order lost its line items"
    total = sum(int(qty) * float(price) for qty, price in lines)
    stated = re.search(r"<span>Total</span><span>\$([\d,.]+)</span>", band)
    assert stated, "the drafted order lost its total"
    assert abs(total - float(stated.group(1).replace(",", ""))) < 0.005


def test_nobody_real_is_in_the_shot():
    """The fiction is the page's own — the barber the hero opens on."""
    band = _band(marketing_pages.render_home())
    assert "Andre Whitfield" in band and "Fade &amp; Co." in band
    for real in ("Kevin", "McCloud", "KMJ", "kmjcreativesolution"):
        assert real not in band

def test_nothing_is_painted_over_the_art_at_either_end():
    """No scrim on the band, and none on the scene.

    Three shipped and all three had to come out (Kevin, 2026-08-19/20):

      * `.dv::after`, 150px ramping to solid --bg at the foot,
      * `.dv-scene::after`'s bottom stop at 90% opaque,
      * `.dv-scene::after`'s TOP stop, solid --bg at the top of the scene.

    The first two blacked out the bottom of every screen. The third was
    worse than it looked: the stage is taller than the scene and overflows
    upward, so the screens START ABOVE the scene box, and that scrim's
    solid line landed 137-156px INSIDE their tops and ended in a hard
    horizontal edge across all three. Every one of them was added to
    soften a crop that a later pass had already removed.

    Legibility belongs to the copy, not to a wash over the product: clear
    air below the text, and a soft radial behind it.
    """
    css = marketing_pages.DEVICE_BAND_CSS
    assert ".dv::after{" not in css, "the band's bottom fade is back"
    assert ".dv-scene::after{" not in css, "the scene scrim is back"


def test_the_copy_gets_air_instead_of_a_scrim():
    """The art starts below the text, and the wash sits on the text."""
    css = marketing_pages.DEVICE_BAND_CSS
    scene = css.split(".dv-scene{", 1)[1].split("}", 1)[0]
    gap = int(re.search(r"margin-top:(\d+)px", scene).group(1))
    assert gap >= 80, f"only {gap}px between the copy and the scene"
    shade = css.split(".dv-shade{", 1)[1].split("}", 1)[0]
    top = int(re.search(r"top:-(\d+)px", shade).group(1))
    height = int(re.search(r"height:(\d+)px", shade).group(1))
    assert top >= height - 40, "the shade hangs into the art instead of backing the copy"


def test_the_inventory_list_is_not_hidden_under_the_drawer():
    """The table has its own lane beside the drafted order.

    Underneath it, the only part of the list clearing the drawer was the
    on-hand column, so the screen read as a black panel with loose digits
    in it instead of as an inventory.
    """
    css = marketing_pages.DEVICE_BAND_CSS
    inv = css.split(".dv-inv{", 1)[1].split("}", 1)[0]
    m = re.search(r"margin-left:(\d+)px", inv)
    assert m, "the table is back underneath the drawer"
    po = css.split(".dv-po{", 1)[1].split("}", 1)[0]
    left = int(re.search(r"left:(\d+)px", po).group(1))
    width = int(re.search(r"width:(\d+)px", po).group(1))
    assert int(m.group(1)) >= left + width, "the table still runs under the drawer"


def test_the_list_fills_its_panel():
    """A stretched panel with a handful of rows is the same black box."""
    band = _band(marketing_pages.render_home())
    rows = band.count('<div class="t ') + band.count('<div class="t"')
    assert rows >= 12, f"only {rows} inventory rows — the panel will show bare"
