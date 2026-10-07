"""The object library (2026-10-01, the concept-layer plan, step 3).

The same promise as the moves: nothing can be named that has no renderer,
a named object always arrives with its source, and every object keeps the
contract that lets it live on any site (tokens only, a phone version,
motion that never hides content, real text inside)."""
import re
from html.parser import HTMLParser

import pytest

import site_objects as so
from site_objects import OBJECTS, OBJECT_KEYS


# ─── 1. the contract every object keeps ──────────────────────────────

def test_there_are_forty_six_objects_each_with_every_part():
    assert len(OBJECTS) == 46
    for key, o in OBJECTS.items():
        assert o.key == key
        assert o.intent.strip() and o.use_when.strip() and o.phone.strip(), key
        assert o.css.strip() and "{" in o.css, key
        assert f'data-sx-object="{key}"' in o.html, f"{key} root lacks data-sx-object"
        assert re.search(r'class="sxo\b[^"]*\bsxo-', o.html), f"{key} root lacks the sxo classes"


def test_objects_carry_no_colour_literals():
    """Builder rule 7: every colour below :root is a token or a mix of one.
    Neutrals are rgba(0,0,0,x) / rgba(255,255,255,x) only."""
    for key, o in OBJECTS.items():
        css = o.css
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), f"{key}: hex literal"
        assert not re.search(r"\b(?:rgb|hsl|hwb|lab|lch|oklab|oklch)\(", css), f"{key}: colour function"
        for m in re.finditer(r"rgba\([^)]*\)", css):
            assert re.match(r"rgba\(\s*(?:0\s*,\s*0\s*,\s*0|255\s*,\s*255\s*,\s*255)", m.group(0)), \
                f"{key}: non-neutral {m.group(0)}"
        assert "url(" not in css, f"{key}: url() belongs only to the shared grain"


def test_the_only_url_is_the_shared_grain():
    assert so.BASE_CSS.count("url(") == 2          # the data URI and its inner filter ref
    assert "data:image/svg+xml" in so.BASE_CSS
    for tok in ("--obj-paper", "--obj-ink", "--obj-accent", "--obj-line",
                "--obj-display", "--obj-body", "--obj-label"):
        assert tok in so.BASE_CSS, tok


def test_motion_never_ignores_reduced_motion():
    for key, o in OBJECTS.items():
        moves = re.search(r"animation\s*:|transition\s*:", o.css)
        if moves and ("@keyframes" in o.css or "stroke-dashoffset" in o.css):
            assert "prefers-reduced-motion" in o.css, f"{key} animates with no still state"
    typed = OBJECTS["typed-caption"]
    assert "prefers-reduced-motion" in typed.js, "the typing script stays still too"


def test_content_is_visible_at_rest():
    """A marker drawn on reveal is drawn by default: only a reveal that has
    not come in yet may hold it back, so a page without JS still shows it."""
    css = OBJECTS["marker"].css
    assert "stroke-dashoffset:0;" in css
    assert ".js .reveal:not(.in) .sxo-mark-ink path{stroke-dashoffset:1}" in css
    typed = OBJECTS["typed-caption"].html
    assert "sxo-sr" in typed and 'aria-hidden="true"' in typed, \
        "the cycling text is hidden from readers; the full text is not"


class _Balance(HTMLParser):
    VOID = {"img", "br", "input", "meta", "link", "hr", "source", "path", "circle"}

    def __init__(self):
        super().__init__()
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(tag)
        else:
            self.stack.pop()


def test_every_example_is_balanced_html():
    for key, o in OBJECTS.items():
        p = _Balance()
        p.feed(o.html)
        assert not p.errors and not p.stack, f"{key}: unbalanced {p.errors or p.stack}"


def test_every_phone_rule_exists_where_layout_changes():
    for key in ("letter", "card-id", "ticket", "schedule-card", "frame",
                "boarding-pass", "installments", "edge", "index-card", "polaroid",
                "marquee", "times-strip", "hours-card", "panels", "mosaic", "pull-quote",
                "dock", "faq", "stat-strip",
                "notice-bar", "callouts", "device", "plan-cards", "comparison", "laurel", "beam",
                "flow-lines", "photo-words", "word-rail", "bracket-links", "two-doors", "billboard",
                "pattern-band", "book-cover", "leader-spotlight", "creed", "script-cap", "visit-details"):
        assert "@media (max-width:" in OBJECTS[key].css, f"{key} has no phone version"
    # the timeline answers to its own column, so a narrow column anywhere
    # (every phone included) gets the vertical line
    assert "@container (max-width:" in OBJECTS["timeline"].css


# ─── 2. naming: only the concept sheet's OBJECTS line commits ────────

def test_object_names_are_read_from_the_objects_line_only():
    spec = ("0. CONCEPT\nIDEA: The shop is a take-a-number counter.\n"
            "OBJECTS: tear-off tickets, a felt letterboard, ID cards for each barber (metal)\n"
            "3. LAYOUT\nHero: 'Take a ticket and a seat.' Prices on the board.")
    assert so.object_names_in(spec) == ["ticket", "letterboard", "card-id"]
    assert so.object_names_in("Hero copy: grab a ticket, see the seal.") == []
    assert so.object_names_in("- Objects: seal, marker circle\n") == ["seal", "marker"]
    assert so.object_names_in("OBJECTS: none") == []


def test_unknown_objects_are_ignored():
    assert so.object_names_in("OBJECTS: a hologram, a jukebox") == []


def test_page_objects_reads_a_built_page():
    page = ('<div class="sxo sxo-ticket" data-sx-object="ticket"></div>'
            '<div data-sx-object="ticket"></div><span data-sx-object="marker"></span>'
            '<div data-sx-object="jukebox"></div>')
    assert so.page_objects(page) == ["ticket", "marker"]


# ─── 3. the two blocks come from the one registry ────────────────────

def test_the_director_catalog_lists_every_object():
    block = so.director_block()
    for key in OBJECT_KEYS:
        assert f"- {key}:" in block, key
    assert "finish" in block and "metal" in block and "glow" in block


def test_the_builder_gets_exactly_the_named_objects():
    assert so.builder_block([]) == ""
    assert so.builder_block(["jukebox"]) == ""
    block = so.builder_block(["ticket", "typed-caption"])
    assert OBJECTS["ticket"].html in block and OBJECTS["typed-caption"].html in block
    # build cost, step 2: styles and script are the server's, never retyped
    assert so.BASE_CSS not in block and OBJECTS["ticket"].css not in block
    assert OBJECTS["typed-caption"].js not in block
    assert OBJECTS["letter"].html not in block
    assert "REPLACE every word" in block and "--obj-paper" in block
    assert "ADDED TO THE PAGE FOR YOU" in block


def test_the_contact_sheet_renders_every_object_in_every_theme():
    html = so.contact_sheet_html(so.CONTACT_THEMES)
    for key in OBJECT_KEYS:
        assert html.count(f'data-sx-object="{key}"') >= len(so.CONTACT_THEMES), key
    assert html.count('class="cs-theme"') == len(so.CONTACT_THEMES)


# ─── the library never trips the builder's own laws (2026-10-01 bench) ─
# Found by the first zero-spend proof render: the ID card's lanyard hole
# was classed "sxo-card-slot", which the stand-in law reads as a fake
# photo frame, and the examples' serial numbers ("No. 0412") were 3+ digit
# runs the truth law reads as invented claims.

def test_no_example_trips_the_stand_in_law():
    import builder_v2
    for key, o in OBJECTS.items():
        assert builder_v2.check_stand_ins(o.html) == [], key


def test_decorative_numbers_stay_one_or_two_digits():
    for key, o in OBJECTS.items():
        for m in re.finditer(r"No\.\s*(\d+)", o.html):
            assert len(m.group(1)) <= 2, f"{key}: serial {m.group(0)} reads as a claim"


def test_an_id_card_grows_to_its_content():
    css = OBJECTS["card-id"].css
    assert ".sxo-card>*{flex-shrink:0}" in css
    card_rule = css.split(".sxo-card{", 1)[1].split("}", 1)[0]
    assert "overflow:hidden" not in card_rule, "a fixed card height squashes the portrait"


# ─── every object in every design language (2026-10-01) ──────────────

def test_the_contact_sheet_covers_every_language_in_its_finish():
    import design_languages as dl
    names = [t["name"] for t in so.CONTACT_THEMES]
    assert names == list(dl.LANGUAGES), "one theme per language, in registry order"
    for t in so.CONTACT_THEMES:
        assert t["finish"] == dl.OBJECT_FINISH[t["name"]][0], t["name"]
    html = so.contact_sheet_html([so.CONTACT_THEMES[1]])        # monograph, metal
    assert 'data-finish="metal" data-sx-object="ticket"' in html


def test_the_metal_finish_does_more_than_the_seal():
    assert "--_metal" in so.BASE_CSS
    for key in ("ticket", "card-id", "boarding-pass", "installments"):
        assert 'data-finish="metal"' in OBJECTS[key].css and "var(--_metal)" in OBJECTS[key].css, key


def test_the_director_is_told_where_inverse_belongs():
    assert "light ground only" in so.director_block()


# ─── the library grows (2026-10-04): what I reached for by hand ───────
# Kevin: "grow the builder's own layout and object library". Ten objects
# from the sites I built myself (Rivers, MaCnificent, the marketing site),
# and a fifth edge shape.

GROWN = ("marquee", "times-strip", "hours-card", "timeline", "panels", "mosaic",
         "pull-quote", "dock", "faq", "stat-strip")


def test_the_grown_objects_are_in_the_catalog_and_built_from_source():
    block = so.director_block()
    for key in GROWN:
        assert f"- {key}:" in block, key
    css, js = so.library_assets(["times-strip"])
    assert OBJECTS["times-strip"].css in css and js == OBJECTS["times-strip"].js


def test_a_plain_word_on_the_objects_line_never_names_a_grown_object():
    """Keys are names too, so a grown object never takes a word the
    Director uses in passing: 'the hours', 'a quote', 'the stats'."""
    assert so.object_names_in("OBJECTS: a letterboard with the hours, times and stats") == ["letterboard"]
    assert so.object_names_in("OBJECTS: a letter that quotes the owner") == ["letter"]
    assert so.object_names_in("OBJECTS: hours card, times strip, pull quote, stat strip") ==         ["hours-card", "times-strip", "pull-quote", "stat-strip"]
    assert so.object_names_in("OBJECTS: photo panels and a photo mosaic, then a marquee band") ==         ["panels", "mosaic", "marquee"]


def test_the_times_and_the_hours_tell_the_business_s_time_or_nothing():
    for key in ("times-strip", "hours-card"):
        o = OBJECTS[key]
        assert 'data-tz="' in o.html and "timeZone" in o.js, key
        assert "data-day" in o.use_when and "0 Sunday" in o.use_when, key
    # the open-now light starts hidden and only shows once it can tell the truth
    hours = OBJECTS["hours-card"]
    assert '<span class="sxo-hours-now" hidden>' in hours.html
    assert ".sxo-hours-now[hidden]{display:none}" in hours.css
    assert "light.hidden=false" in hours.js and "hasAttribute('data-closed')" in hours.js


def test_motion_in_the_grown_objects_has_a_still_state():
    assert "animation:none" in OBJECTS["marquee"].css.split("prefers-reduced-motion:reduce", 1)[1]
    assert "prefers-reduced-motion: reduce" in OBJECTS["stat-strip"].js
    marquee = OBJECTS["marquee"].html
    assert 'class="sxo-sr"' in marquee and 'aria-hidden="true"' in marquee,         "readers get the list once; the looping copies are hidden from them"


def test_the_page_holds_the_real_figure_before_any_count_up():
    html = OBJECTS["stat-strip"].html
    for m in re.finditer(r'data-count="(\d+)">([^<]+)<', html):
        assert m.group(1) in m.group(2), "the figure at rest is the real one"
    assert "el.textContent=txt" in OBJECTS["stat-strip"].js, "the count-up lands on the original text"


def test_panels_and_the_dock_never_strand_content():
    panels = OBJECTS["panels"]
    # without the page's js class every panel is open; only the script collapses them
    assert ".sxo-panel:not(.is-open) .sxo-panel-body{opacity:0" in panels.css
    assert ".js .sxo-panel:not(.is-open) .sxo-panel-body" in panels.css
    assert "aria-expanded" in panels.html and "setAttribute('aria-expanded'" in panels.js
    dock = OBJECTS["dock"].css
    assert dock.startswith(".sxo-dock{display:none}"), "never on a desktop"
    assert "body:has(.sxo-dock){padding-bottom" in dock, "the dock never covers the footer"
    assert "visibility:hidden" in dock, "a hidden dock is out of the tab order too"


def test_the_edge_has_a_wave():
    edge = OBJECTS["edge"]
    assert '.sxo-edge[data-edge="wave"]' in edge.css and "wave" in edge.intent


# ─── from the sites Kevin sent (2026-10-05) ───────────────────────────
# dimedocs, bridgemind, antwainjackson, 2819church, socialdallas, tradeify:
# twenty parts rebuilt from scratch to this contract.

KEVINS = ("notice-bar", "callouts", "device", "plan-cards", "comparison", "laurel", "beam",
          "flow-lines", "photo-words", "word-rail", "bracket-links", "two-doors", "sign-off",
          "billboard", "pattern-band", "book-cover", "leader-spotlight", "creed", "script-cap",
          "visit-details")


def test_the_twenty_are_catalogued_and_carry_no_one_elses_words():
    block = so.director_block()
    for key in KEVINS:
        assert f"- {key}:" in block, key
    # rebuilt, not copied: none of the studied sites' names or lines appear
    everything = " ".join(OBJECTS[k].html + OBJECTS[k].css + OBJECTS[k].use_when for k in KEVINS).lower()
    for theirs in ("dime docs", "bridgemind", "antwain", "2819", "social dallas", "tradeify",
                   "until all have heard", "god loves dallas", "stop guessing"):
        assert theirs not in everything, theirs


def test_everyday_words_never_name_the_new_objects():
    """'the book', 'the plans', 'the details', 'the leader' and 'an award'
    are ordinary words on an OBJECTS line; only the object names count."""
    line = "OBJECTS: a ticket to book, the plans and details on a letterboard, the leader's certificate award"
    assert so.object_names_in(line) == ["ticket", "letterboard", "certificate"]
    assert so.object_names_in("OBJECTS: plan cards, book cover, leader spotlight, visit details, laurel") == \
        ["plan-cards", "book-cover", "leader-spotlight", "visit-details", "laurel"]


def test_images_keep_their_frame_s_shape():
    """An <img> with width/height attributes keeps the attribute height
    unless the CSS says height:auto, and the frame's aspect-ratio never
    applies (found rendering the callouts and the devices)."""
    import re as _re
    for key in ("callouts", "device"):
        css = OBJECTS[key].css
        img_rules = _re.findall(r"[^{}]*img\{[^}]*\}", css)
        assert any("aspect-ratio" in r for r in img_rules), key
        assert any("height:auto" in r or "height:100%" in r for r in img_rules), key


def test_honest_by_default():
    plans = OBJECTS["plan-cards"]
    assert "BOTH prices" in plans.use_when and "data-month" in plans.html and "data-year" in plans.html
    assert "remove it" in plans.use_when, "no switch without two real prices"
    for key, rule in (("laurel", "Never an invented award"), ("notice-bar", "Never an invented sale"),
                      ("comparison", "Never a named competitor"), ("device", "Never a made-up interface")):
        assert rule.lower() in OBJECTS[key].use_when.lower(), key


def test_the_copy_button_never_dead_ends():
    js = OBJECTS["visit-details"].js
    assert "b.hidden=true" in js and "isSecureContext" in js, "no clipboard, no button"
    assert 'data-copy="' in OBJECTS["visit-details"].html


def test_big_type_sizes_to_its_own_column():
    """Creed lines, the two doors and the photo words overflowed a half-width
    column when they sized to the window; they size to their container."""
    for key in ("creed", "two-doors", "photo-words"):
        css = OBJECTS[key].css
        assert "container-type:inline-size" in css and "cqi" in css, key
    for key in ("sign-off", "billboard"):
        assert "scrollWidth" in OBJECTS[key].js, f"{key} fits the name to the width"


def test_the_rail_makes_room_and_reads_on_the_page_ground():
    rail = OBJECTS["word-rail"]
    assert "body:has(.sxo-rail){padding-left" in rail.css
    assert "color:inherit" in rail.css and "mix-blend-mode" not in rail.css
    assert "direct child of <body>" in rail.use_when


def test_the_edge_steps_down():
    assert '.sxo-edge[data-edge="steps"]' in OBJECTS["edge"].css and "steps" in OBJECTS["edge"].intent
