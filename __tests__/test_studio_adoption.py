# Studio-IP adoption (2026-07-23): color seeds, zone attributes, prefill.
import brand_dna
from site_modules import hero, gallery, about


def test_named_colors_resolve_with_variant_lens():
    assert brand_dna.interpret_color_words("navy and gold") == ["#1f3a5f", "#c79d26"]
    deep = brand_dna.interpret_color_words("deep luxurious navy and gold")
    assert deep == ["#141f38", "#a67c1a"]      # the luxury navy, not corporate
    bright = brand_dna.interpret_color_words("bright green")
    assert bright == ["#29d665"]


def test_feelings_seed_when_no_names():
    assert brand_dna.interpret_color_words("warm and earthy") == ["#b5541c", "#7a5c3e"]
    assert brand_dna.interpret_color_words("") == []
    assert brand_dna.interpret_color_words("quantum flavor") == []  # fail-open


def test_hero_bg_carries_overlay_zone():
    html, _ = hero.render("banner", {"headline": "H"}, {"dna": brand_dna.build_brand_dna("t", {}), "business": {"name": "B"}, "booking": {}})
    assert 'data-sx-zone="image-overlay"' in html
    assert 'data-sx-bg="true"' in html and 'data-sx-label="Hero background"' in html


def test_gallery_imgs_carry_zone_and_label():
    html, _ = gallery.render("grid", {}, {
        "gallery": [{"url": "https://x/a.jpg", "title": "Legacy Vol I"}],
        "business": {"id": "b", "name": "K"}, "dna": {},
        "site_prefs": {"wants_gallery": False}})
    assert 'data-sx-zone="image"' in html and 'data-sx-label="Legacy Vol I"' in html
