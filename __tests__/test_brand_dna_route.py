"""
test_brand_dna_route.py — the design system gets a door.

brand_dna.py is 1,304 lines that turn a brand kit into a complete token
set — a role palette with derived on-colours, a real type scale, an 8pt
rhythm, a radius language, a motion tier. Until 2026-08-10 it had ZERO
HTTP routes. It materialised only as inline CSS inside a composed site,
so the practitioner whose brand it describes could never see any of it.

These pin the door itself, and the shape behind it, so a refactor can't
quietly narrow what the Brand Room is allowed to show.
"""
import brand_dna
import brand_engine_router


KIT = {"design": {
    "primary_color": "#000000", "accent_color": "#009133",
    "secondary_color": "#FFDD00", "background_color": "#F7FAFC",
    "text_color": "#2D3748", "font_heading": "Montserrat",
    "font_body": "Open Sans",
    "tone_words": ["Confident", "Empowering", "Visionary"]}}


def test_the_route_exists_and_is_a_read():
    """A GET, because nothing here is stored — the system is derived
    from the kit on every call and is therefore always current."""
    routes = {r.path: set(r.methods) for r in brand_engine_router.router.routes}
    assert "/brand/dna/{business_id}" in routes
    assert routes["/brand/dna/{business_id}"] == {"GET"}


def test_seeing_your_own_design_system_is_not_an_admin_act():
    """viewer, not admin. A team member who can read the brand should be
    able to read what the brand renders as."""
    import inspect
    src = inspect.getsource(brand_engine_router.dna)
    assert 'business_access("viewer")' in src


def test_the_derived_system_carries_all_five_layers():
    d = brand_dna.build_brand_dna("biz-1", bundle=KIT)
    for layer in ("palette", "typography", "rhythm", "radius", "motion"):
        assert layer in d, layer
    assert d["vibe"] and d["intensity"]


def test_the_palette_speaks_in_roles_with_derived_on_colours():
    """The Brand Room shows five nameless swatches; the system that
    consumes them thinks in roles and derives the text colour for each
    ground. That vocabulary is the point of surfacing this."""
    p = brand_dna.build_brand_dna("biz-1", bundle=KIT)["palette"]
    for role in ("bg", "surface", "text", "accent", "primary", "border"):
        assert role in p, role
    # a ground and the colour that goes ON it, both present
    assert "accent" in p and any(k.startswith("on_") for k in p), \
        "no derived on-colour — the role palette loses half its value"
    assert len(p) >= 20, f"expected the full role set, got {len(p)}"


def test_typography_is_a_scale_not_two_font_names():
    t = brand_dna.build_brand_dna("biz-1", bundle=KIT)["typography"]
    for step in ("h1", "h2", "h3", "lead", "small"):
        assert step in t, step
    for w in ("heading_weight", "h2_weight", "h3_weight"):
        assert isinstance(t[w], int), w
    assert "letter_tight" in t
    # the owner's own faces survive derivation
    assert t["heading"] == "Montserrat" and t["body"] == "Open Sans"


def test_rhythm_and_radius_are_real_vocabularies():
    d = brand_dna.build_brand_dna("biz-1", bundle=KIT)
    assert {"section_pad", "gutter", "content_max"} <= set(d["rhythm"])
    assert {"card", "button", "image"} <= set(d["radius"])
    # a radius VOCABULARY means the three are allowed to differ
    assert len(set(d["radius"].values())) > 1, \
        "one radius for every role is what makes a UI a soft blob"


def test_deriving_twice_gives_the_same_system():
    """Derived, not random. A practitioner who reloads must not see a
    different design system — _seed_int is keyed on business_id."""
    a = brand_dna.build_brand_dna("biz-1", bundle=KIT)
    b = brand_dna.build_brand_dna("biz-1", bundle=KIT)
    assert a == b


def test_an_empty_kit_still_derives_something_renderable():
    """Every business has a design system whether or not it has a brand
    kit — that is why composed sites work on day one."""
    d = brand_dna.build_brand_dna("biz-2", bundle={"design": {}})
    assert d["palette"].get("bg") and d["typography"].get("heading")
