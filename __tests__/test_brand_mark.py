"""
test_brand_mark.py — the owner's logo must reach the page.

KEVIN, 2026-08-09: "my logo for the business doesn't get on the site."

He was right, and the mechanism was a broken middle. `grep -c logo`
returned ZERO in builder_v2.py, canvas.py and atelier.py — every module
that authors a page. Their whole image inventory is `site_config.slots`
plus `ctx["gallery"]`; the brand mark is uploaded to
`businesses.settings.brand_kit` and appears in neither.

The Director COULD see it (spec_author sends it as a vision block) and
wrote specs referencing a mark in the header. The builder, holding only
portfolio pieces, put a 1200x675 campaign flyer in a 59x34 header box and
shipped it as the brand on kmjcreate.com.

Same shape as the moves bug: one half of the system knows something the
other half has never been told.
"""
import brand_mark

LOGO = ("https://brqjgbpzackdihgjsorf.supabase.co/storage/v1/object/public/"
        "business-assets/brand/12773842/primary-20260805135506.png")


def _ctx(settings):
    return {"bundle": {"business": {"settings": settings}}}


# ─── 1. Every real kit shape resolves ────────────────────────────────

def test_resolves_the_shape_kmj_actually_has():
    """KMJ's live kit carries assets.primary AND logo_url, and NO `logos`
    key — the shape the original lookup half-expected."""
    assert brand_mark.mark_url(_ctx({"brand_kit": {
        "assets": {"primary": LOGO}, "logo_url": LOGO}})) == LOGO


def test_resolves_legacy_and_alternate_shapes():
    assert brand_mark.mark_url(_ctx({"brand_kit": {
        "logos": {"primary": LOGO}}})) == LOGO
    assert brand_mark.mark_url(_ctx({"brand_kit": {
        "assets": {"primary": LOGO}}})) == LOGO
    assert brand_mark.mark_url(_ctx({"site_images": {"logo": LOGO}})) == LOGO


def test_http_marks_are_rejected():
    """The page is served over TLS; a mixed-content mark is a broken
    mark, and a broken mark is worse than a wordmark."""
    assert brand_mark.mark_url(_ctx({"brand_kit": {
        "logo_url": LOGO.replace("https://", "http://")}})) is None


def test_no_kit_resolves_to_nothing_rather_than_guessing():
    assert brand_mark.mark_url(_ctx({})) is None
    assert brand_mark.mark_urls(_ctx({"brand_kit": {}})) == []


def test_never_raises_on_junk():
    for bad in (None, {}, {"bundle": None}, _ctx({"brand_kit": "not a dict"}),
                _ctx({"brand_kit": {"logos": ["a"], "assets": 7}})):
        assert brand_mark.mark_url(bad) is None


# ─── 2. The instruction, not just the url ────────────────────────────

def test_present_block_forbids_the_substitution_that_shipped():
    """Naming the url is necessary but not sufficient. The builder did
    not choose badly — it had no logo and used the only images it had.
    So the block has to say a gallery image is never the logo."""
    block = brand_mark.real_data_block(
        _ctx({"brand_kit": {"logo_url": LOGO}}), "", "KMJ Creative Solutions")
    assert LOGO in block
    assert "BRAND MARK" in block
    assert "NEVER use a gallery or portfolio image as the logo" in block
    # And the aspect-ratio instruction, because 1200x675 in a 59x34 box
    # is how it actually shipped.
    assert "object-fit: contain" in block


def test_absent_block_still_forbids_it():
    """A business with no kit is exactly where the temptation to grab a
    portfolio piece is strongest."""
    block = brand_mark.real_data_block(_ctx({}), "", "C13 Test Shop")
    assert "none uploaded" in block
    assert "Do NOT substitute a portfolio" in block
    assert "C13 Test Shop" in block          # so it can set a wordmark
    assert "https://" not in block           # no url invented


# ─── 3. The wiring — every author is handed it ───────────────────────

def test_the_builders_now_receive_the_mark(monkeypatch):
    """The regression guard. builder_v2's real-data block is the page
    author's entire view of the world; the mark must be in it."""
    import builder_v2
    ctx = _ctx({"brand_kit": {"logo_url": LOGO}})
    ctx["business"] = {"name": "KMJ Creative Solutions", "type": "consultant"}
    ctx["gallery"] = [{"url": "https://x/gallery_1.png", "alt": "a campaign"}]
    data = builder_v2.assemble_real_data(ctx, "biz-1")
    assert LOGO in data, "the builder still cannot see the logo"
    assert "NEVER use a gallery or portfolio image as the logo" in data


def test_the_canvas_brief_now_carries_the_mark():
    from canvas_brief import compile_canvas_brief
    ctx = _ctx({"brand_kit": {"logo_url": LOGO}})
    ctx["business"] = {"id": "biz-1", "name": "KMJ Creative Solutions"}
    brief = compile_canvas_brief(ctx, None, [])
    assert LOGO in brief


def test_every_authoring_prompt_states_the_rule():
    """Belt and braces: the url arrives in the data, and the rule that
    stops a portfolio substitution lives in the system prompt."""
    import builder_v2, canvas, atelier
    for label, p in (("builder_v2", builder_v2._SYSTEM),
                     ("canvas", canvas._SYSTEM_PROMPT),
                     ("atelier", atelier._SYSTEM_PROMPT),
                     ("atelier refine", atelier._REFINE_SYSTEM_PROMPT)):
        assert "BRAND MARK IS NOT A PORTFOLIO PIECE" in p, label


# ─── 4. The other thing that shipped: the JS-off blackout ────────────

def test_every_authoring_prompt_forbids_a_bare_reveal():
    """kmjcreate.com ships 14 elements at opacity:0 with no `.js` gate and
    no <noscript>. Any script error, blocked asset, or non-executing
    crawler sees the nav and a black rectangle."""
    import builder_v2, canvas, atelier
    for label, p in (("builder_v2", builder_v2._SYSTEM),
                     ("canvas", canvas._SYSTEM_PROMPT),
                     ("atelier", atelier._SYSTEM_PROMPT)):
        assert "documentElement.className" in p, label   # the .js gate
        assert "<noscript>" in p, label                   # the escape
        assert "Never write a bare" in p, label
        assert "Content is visible by default" in p, label
