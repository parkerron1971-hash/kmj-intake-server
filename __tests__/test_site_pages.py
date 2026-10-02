"""Pages that match (2026-10-01, the concept-layer plan, step 6).

Secondary pages are cut from the builder's own home page (same head,
header, footer and scripts), never module templates with fixed copy; and
a World concept's offer page gets a path that never collides with one the
platform serves."""
import site_pages as sp

HOME = """<!DOCTYPE html><html><head><title>Marrow &amp; Steel</title>
<script>document.documentElement.className+=' js'</script>
<style>.js .reveal{opacity:0}.js .reveal.in{opacity:1}</style></head><body>
<header class="nav"><a href="#top">Marrow &amp; Steel</a>
<nav><a href="#prices">Prices</a><a href="#chairs">The Chairs</a><a href="#book">Book</a><a href="#contact">Contact</a></nav></header>
<main id="top">
<section class="hero" id="hero"><h1 data-override-target="v2/f4">Cut sharp.</h1></section>
<div class="band">Classic cuts · Skin fades</div>
<section class="board station" id="prices"><h2 data-override-target="v2/f8">The Board</h2><ul><li>Classic Cut $35</li></ul></section>
<section class="work" id="work"><h2>The Work</h2><figure><img src="https://x/a.jpg" alt="a fade"></figure></section>
<section class="proof" id="proof"><blockquote>Only person I trust with a fade.</blockquote></section>
<section class="chairs station" id="chairs" data-sx-page="about"><h2>Two Chairs, Two Barbers</h2><p>Deshawn opened in 2021.</p></section>
<section class="book station" id="book"><h2>Book a Chair</h2><a href="https://mysolutionist.app/book/x">Book</a></section>
<section class="contact" id="contact"><h2>Find the Shop</h2><form id="inquiry" method="POST" action="https://e/x"><input name="email"></form></section>
</main>
<footer><a href="#prices">Prices</a> Lakewood, Ohio</footer>
<div id="lightbox" role="dialog"></div>
<script>(function(){var f=document.getElementById('inquiry');f.addEventListener('submit',function(){});})();</script>
</body></html>"""


def test_a_builder_page_is_recognised_by_its_stamps():
    assert sp.is_builder_page(HOME)
    assert not sp.is_builder_page("<html><body><section>x</section></body></html>")


def test_top_sections_are_found_nesting_aware():
    spans = sp.top_sections(HOME)
    assert len(spans) == 7
    nested = "<body><section id='a'><section id='b'>x</section></section><section id='c'></section></body>"
    assert len(sp.top_sections(nested)) == 2


def test_pages_are_cut_from_the_home_page():
    pages = sp.slice_pages(HOME, "Marrow & Steel")
    assert set(pages) == {"about", "services", "contact"}
    about, services, contact = pages["about"], pages["services"], pages["contact"]
    assert "Two Chairs, Two Barbers" in about and "Only person I trust" in about
    assert "The Board" in services and "The Work" in services
    assert "Find the Shop" in contact and "<form" in contact and "Book a Chair" in contact
    for doc in pages.values():
        assert "Cut sharp." not in doc, "the hero stays on the home page"
        assert '<header class="nav">' in doc and "<footer>" in doc
        assert 'id="lightbox"' in doc and "getElementById('inquiry')" in doc
        assert "className+=' js'" not in doc, "sliced pages are still"
        assert doc.count("<h1") == 1, "one h1 per page"
    assert "<title>About · Marrow &amp; Steel</title>" in about


def test_anchors_point_at_the_page_that_holds_them():
    pages = sp.slice_pages(HOME, "Marrow & Steel")
    about = pages["about"]
    assert 'href="/services#prices"' in about
    assert 'href="#chairs"' in about, "an anchor on this page stays an anchor"
    assert 'href="/contact#book"' in about
    services = pages["services"]
    assert 'href="#prices"' in services
    assert 'href="/about#chairs"' in services
    assert 'href="/#top"' not in services and 'href="#top"' in services, \
        "#top lives on the main wrapper, which every page keeps"


def test_a_page_without_sections_is_not_cut():
    assert sp.slice_pages("<html><body><p>no sections</p></body></html>") == {}
    one = "<html><body><section id='hero'><h1>x</h1></section></body></html>"
    assert sp.slice_pages(one) == {}


def test_the_builders_own_tag_wins_over_keywords():
    page = HOME.replace('<section class="work" id="work">',
                        '<section class="work" id="work" data-sx-page="about">')
    pages = sp.slice_pages(page)
    assert "The Work" in pages["about"] and "The Work" not in pages["services"]


# ─── the offer page ──────────────────────────────────────────────────

def test_the_offer_path_comes_from_the_scope_line():
    assert sp.offer_path({"scope_raw": "offer (Saturday Shave Club)"}) == "/saturday-shave-club"
    assert sp.offer_path({"scope_raw": "offer page for the Six-Week Wheel Course"}) == "/the-six-week-wheel-course"
    assert sp.offer_path({"scope_raw": "offer: Scholar by Design"}) == "/scholar-by-design"
    assert sp.offer_path({"scope_raw": "offer"}) == "/offer"
    assert sp.offer_path({}) == "/offer"


def test_the_offer_path_never_takes_a_platform_path():
    assert sp.offer_path({"scope_raw": "offer (Book)"}) == "/offer-book"
    assert sp.offer_path({"scope_raw": "offer (Events)"}) == "/offer-events"


def test_the_home_is_told_where_to_link_and_checked_for_it():
    line = sp.offer_line("/saturday-shave-club", "the Saturday Shave Club")
    assert 'href="/saturday-shave-club"' in line and "navigation" in line
    linked = '<nav><a href="/saturday-shave-club">The Club</a></nav>'
    assert sp.check_offer_link(linked, "/saturday-shave-club") == []
    assert sp.check_offer_link("<nav></nav>", "/saturday-shave-club")
    assert sp.check_offer_link("<nav></nav>", "") == []
