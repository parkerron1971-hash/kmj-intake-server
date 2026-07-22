# Authorship pass (instinct arc piece 1) — the sanitizer IS the safety
# contract: the model gets the whole page only because nothing outside
# the scope contract can survive.
import art_direction as ad


def test_scoped_rules_survive():
    css = ".sxm-gallery figure { border: 1px solid var(--sx-border); }"
    assert "sxm-gallery" in ad.sanitize_layer(css)


def test_root_token_retune_survives():
    css = ":root { --sx-accent-soft: color-mix(in srgb, var(--sx-accent) 40%, transparent); }"
    assert "--sx-accent-soft" in ad.sanitize_layer(css)


def test_bare_element_selectors_drop():
    css = "h2 { color: red; }\nbody { background: #000; }\n.sxm-card { padding: 2rem; }"
    out = ad.sanitize_layer(css)
    assert "color: red" not in out and "background: #000" not in out
    assert "sxm-card" in out


def test_forbidden_payloads_drop():
    for bad in (".sxm-a { background: url(http://x/y.png); }",
                "@import 'evil.css';",
                ".sxm-a { position: fixed; top: 0; }",
                "@font-face { font-family: X; }"):
        assert ad.sanitize_layer(bad) == ""


def test_structural_declarations_drop():
    # The live gallery-smash bug: the model re-positioned a figure class
    # it mistook for a caption. Structure changes never survive.
    for bad in (".sxm-gal-fig-over { position: absolute; left: .9rem; }",
                ".sxm-card { display: none; }",
                ".sxm-hero-inner { visibility: hidden; }"):
        assert ad.sanitize_layer(bad) == ""
    # Surface styling on the same class still flows.
    ok = ".sxm-gal-fig-over { border: 1px solid var(--sx-hair); }"
    assert "sxm-gal-fig-over" in ad.sanitize_layer(ok)


def test_media_query_recurses():
    good = "@media (max-width: 768px) { .sxm-gallery { grid-template-columns: 1fr; } }"
    bad = "@media (max-width: 768px) { div { display: none; } }"
    assert "sxm-gallery" in ad.sanitize_layer(good)
    assert ad.sanitize_layer(bad) == ""


def test_keyframes_need_the_prefix():
    assert "sxad-rise" in ad.sanitize_layer(
        "@keyframes sxad-rise { from { opacity: 0; } to { opacity: 1; } }")
    assert ad.sanitize_layer(
        "@keyframes steal { from { opacity: 0; } }") == ""


def test_comments_and_fences_tolerated():
    css = "/* thesis */ .sxm-hero-inner { letter-spacing: -0.02em; }"
    assert "letter-spacing" in ad.sanitize_layer(css)


def test_class_inventory_grounds_selectors():
    html = '<section class="sxm-section sxm-gallery"><div class="atl-ab12 crest"></div></section>'
    inv = ad.class_inventory(html)
    assert "sxm-gallery" in inv and "atl-ab12" in inv
    assert "crest" not in inv  # unprefixed classes are not offered as hooks


def test_size_cap():
    css = "\n".join(f".sxm-x{i} {{ margin: {i}px; }}" for i in range(2000))
    assert len(ad.sanitize_layer(css)) <= ad._MAX_LAYER_CHARS


def test_fail_open_when_disabled(monkeypatch):
    monkeypatch.setenv("ART_DIRECTION", "off")
    assert ad.author_layer({}, "<div class='sxm-a'></div>") == ""
