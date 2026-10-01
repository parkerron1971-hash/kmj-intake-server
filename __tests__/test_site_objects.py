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

def test_there_are_sixteen_objects_each_with_every_part():
    assert len(OBJECTS) == 16
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
                "boarding-pass", "installments", "edge", "index-card", "polaroid"):
        assert "@media (max-width:" in OBJECTS[key].css, f"{key} has no phone version"


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
    assert block.count(so.BASE_CSS) == 1, "the shared tokens once"
    assert OBJECTS["ticket"].css in block and OBJECTS["typed-caption"].js in block
    assert OBJECTS["letter"].css not in block
    assert "REPLACE every word" in block and "--obj-paper" in block


def test_the_contact_sheet_renders_every_object_in_every_theme():
    html = so.contact_sheet_html(so.CONTACT_THEMES)
    for key in OBJECT_KEYS:
        assert html.count(f'data-sx-object="{key}"') >= len(so.CONTACT_THEMES), key
    assert html.count('class="cs-theme"') == len(so.CONTACT_THEMES)
