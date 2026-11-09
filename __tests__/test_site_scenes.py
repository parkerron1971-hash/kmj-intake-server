"""A scene holds the page still while the scroll tells something, and a page
without motion still shows every word and photo.

Measured 2026-11-08: both hand-built pages open near 200px with real photos,
both builder pages open under 100px with none, and no library piece could pin
the page. The scenes are written once here, so the model only fills them in.
They stay off until SITE_SCENES=on, and they use no animation library, because
GSAP's license bars competing no-code animation builders.
"""
import re

import builder_v2 as v2
import site_objects as so
import site_scenes as ss


def test_there_is_a_scene_for_every_photo_count():
    assert ss.SCENE_KEYS == ("scene-lines", "scene-reveal", "scene-wall")
    assert "<img" not in so.OBJECTS["scene-lines"].html
    assert so.OBJECTS["scene-reveal"].html.count("<img") == 1
    assert so.OBJECTS["scene-wall"].html.count("<img") >= 6


def test_scenes_stay_out_of_the_catalog_until_switched_on(monkeypatch):
    monkeypatch.delenv("SITE_SCENES", raising=False)
    block = so.director_block()
    assert "scene-" not in block and "SCENES" not in block
    monkeypatch.setenv("SITE_SCENES", "on")
    block = so.director_block()
    for key in ss.SCENE_KEYS:
        assert f"- {key}:" in block
    assert "AT MOST ONE scene" in block and "never on PLAIN" in block


def test_with_the_switch_off_no_blueprint_can_name_a_scene(monkeypatch):
    monkeypatch.delenv("SITE_SCENES", raising=False)
    for phrase in ("scene wall", "wall of photos", "window scene", "pinned lines", "scene lines"):
        assert so.object_names_in(f"OBJECTS: {phrase}, a ticket") == ["ticket"], phrase
    # a page built while it was on keeps working after it goes off
    page = so.inject_library(f"<html><head></head><body>{so.OBJECTS['scene-lines'].html}</body></html>")
    assert ".sxo-scl.sxo-live" in page and "querySelectorAll('.sxo-scl')" in page


def test_the_builder_gets_a_named_scene_and_never_writes_its_code(monkeypatch):
    monkeypatch.setenv("SITE_SCENES", "on")
    keys = so.object_names_in("OBJECTS: scene wall")
    assert keys == ["scene-wall"]
    block = so.builder_block(keys)
    assert "sxo-scw-wall" in block
    assert so.OBJECTS["scene-wall"].js not in block and ".sxo-live" not in block


def test_everyday_words_never_name_a_scene(monkeypatch):
    monkeypatch.setenv("SITE_SCENES", "on")
    line = "OBJECTS: a letter on the wall, a ticket by the window, lines of type"
    assert so.object_names_in(line) == ["letter", "ticket"]


def test_scenes_load_nothing_from_anywhere():
    """Our own script on the browser's own scrolling: no animation library, no
    network, nothing a security pass would strip."""
    for key in ss.SCENE_KEYS:
        o = so.OBJECTS[key]
        code = (o.css + o.js).lower()
        for banned in ("gsap", "scrolltrigger", "lenis", "locomotive", "fetch(", "xmlhttprequest",
                       "eval(", "localstorage", "import(", "http://", "https://", "url("):
            assert banned not in code, f"{key}: {banned}"


def test_poster_lines_fit_the_screen_whatever_the_font():
    """Found on real material: a wide font wrapped the lines, they ran off the
    pinned screen, and the closing line was cut. The script now fits them."""
    o = so.OBJECTS["scene-lines"]
    assert "white-space:nowrap" in o.css and "width:max-content" in o.css
    assert "aw/Math.max(1,wide)" in o.js and "ah/(n*1.02)" in o.js
    # phones are where most visitors are: a line may break so the words go bigger
    assert "sxo-tall" in o.css and "if(vh>vw){el.classList.add('sxo-tall')" in o.js
    # without this a grid quietly widens the line to its longest word, and the
    # overflow check never fires (found by the browser stress test)
    assert ".sxo-tall .sxo-scl-pin{grid-template-columns:minmax(0,1fr)}" in o.css
    # a line too long to be a poster stays the plain stack, never tiny type
    assert "if(fs<28){el.classList.remove('sxo-live')" in o.js


def test_the_script_stands_down_where_a_pin_would_fail():
    for key in ss.SCENE_KEYS:
        js = so.OBJECTS[key].js
        assert "prefers-reduced-motion" in js, key
        assert "innerHeight<420" in js, key
        assert "clipped" in js, key


def test_every_moving_rule_waits_for_the_script():
    """At rest a scene is a plain stack: only a rule behind .sxo-live may hide,
    pin or dim anything, so a failed script still shows every word and photo."""
    for key in ss.SCENE_KEYS:
        for rule in re.findall(r"([^{}]+)\{([^{}]*)\}", so.OBJECTS[key].css):
            selector, body = rule
            if re.search(r"opacity|position:sticky|clip-path|text-fill-color|calc\(100svh", body):
                assert ".sxo-live" in selector, f"{key}: {selector.strip()} moves without the script"


def _doc(extra):
    endpoint = "https://api.example/contact/biz-1"
    return ("<!DOCTYPE html><html><head><title>Studio</title>"
            '<meta name="description" content="A braiding studio by hand">'
            '<meta property="og:title" content="Studio">'
            '<meta property="og:description" content="A braiding studio">'
            '<meta property="og:image" content="https://x/a.jpg">'
            "<style>body{margin:0}</style></head><body>"
            '<nav><a href="#top">Top</a></nav><main id="top"><h1>Braids worn '
            "like their own kind of magnificent.</h1>" + extra + "</main>"
            f'<form method="POST" action="{endpoint}"><input name="name">'
            '<input name="email"><button>Send</button></form>'
            "<footer>Studio</footer></body></html>")


def test_a_page_with_a_scene_passes_the_laws_and_wears_its_code(monkeypatch):
    monkeypatch.setenv("SITE_SCENES", "on")
    calls = []
    scene = so.OBJECTS["scene-lines"].html.replace('<p class="sxo-scl-end">', '<p class="sxo-scl-end">Thank you. ')

    def _fake_call(system, user, business_id, spend=None):
        calls.append(user)
        return _doc(f'<section id="moment">{scene}</section>')

    monkeypatch.setattr(v2, "_call", _fake_call)
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: "BUSINESS: Studio")
    monkeypatch.setattr(v2, "contact_endpoint", lambda b: "https://api.example/contact/biz-1")
    monkeypatch.setattr(v2, "eyes_enabled", lambda: False)
    out = v2.run_builder_v2("SPEC\nOBJECTS: scene lines", {}, "biz-1")
    assert out["html"] and not out["report"]["fallbacks"]
    assert len(calls) == 1 and not out["report"]["violations"]
    assert ".sxo-scl.sxo-live" in out["html"] and "sxo-live" in out["html"].split("<script")[-1]
    assert out["report"]["mechanical"]["scripts_dropped"] == []


def test_the_eyes_are_told_a_scene_part_way_is_not_a_defect(monkeypatch):
    seen = {}

    class _Msg:
        content = []

    class _Client:
        class messages:
            @staticmethod
            def create(**kw):
                seen["content"] = kw["messages"][0]["content"]
                return _Msg()

    import llm_call
    import model_ladder
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(v2, "_screenshot_walk", lambda d: [("1440 top", b"jpg")])
    monkeypatch.setattr(llm_call, "sdk_client", lambda **k: _Client())
    monkeypatch.setattr(model_ladder, "call_with_ladder",
                        lambda fn, **k: (fn(k.get("model"), k.get("max_tokens"), 90.0), k.get("model")))
    for page, told in ((_doc(so.OBJECTS["scene-lines"].html), True), (_doc(""), False)):
        seen.clear()
        v2.inspect_with_eyes(page, "SPEC", "biz-1")
        assert seen["content"], "the eyes were never called"
        text = " ".join(b.get("text", "") for b in seen["content"] if isinstance(b, dict))
        assert ("THIS PAGE HOLDS A SCENE" in text) is told


# ─── found by the first real build (2026-11-09) ───────────────────

_HOSTILE = (".wrap{max-width:900px}\n#people .sxo-scw{height:auto}\n"
            "#people .sxo-scw-wall{display:grid;grid-template-columns:repeat(5,1fr)}\n"
            "@media (max-width:600px){.sxo-scw-line{background:red}}\n"
            ".keep,.sxo-scr-frame{margin:0}\n.sxo-scl-line:hover,.sxo-scl{color:red}")


def _hostile_page():
    return ("<html><head><style>" + _HOSTILE + "</style></head><body>"
            + so.OBJECTS["scene-wall"].html + "</body></html>")


def test_the_server_takes_off_what_a_page_wrote_over_a_scene():
    page, removed = ss.strip_page_overrides(_hostile_page())
    assert removed == 6
    style = page.split("</style>")[0]
    assert ".wrap{max-width:900px}" in style and ".keep{margin:0}" in style
    assert "sxo-sc" not in style


def test_a_page_with_no_scene_is_left_alone():
    page = "<html><head><style>.sxo-scw{color:red}</style></head><body></body></html>"
    assert ss.strip_page_overrides(page) == (page, 0)


def test_the_builder_is_told_and_the_build_removes_it(monkeypatch):
    monkeypatch.setenv("SITE_SCENES", "on")
    assert "A SCENE STYLES ITSELF" in so.builder_block(["scene-wall"])
    assert "A SCENE STYLES ITSELF" not in so.builder_block(["letter"])
    scene = so.OBJECTS["scene-lines"].html
    doc = _doc(f'<section id="moment">{scene}</section>').replace(
        "<style>body{margin:0}", "<style>body{margin:0}#moment .sxo-scl-pin{padding:0}")
    monkeypatch.setattr(v2, "_call", lambda system, user, business_id, spend=None: doc)
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: "BUSINESS: Studio")
    monkeypatch.setattr(v2, "contact_endpoint", lambda b: "https://api.example/contact/biz-1")
    monkeypatch.setattr(v2, "eyes_enabled", lambda: False)
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert "#moment .sxo-scl-pin" not in out["html"]
    assert out["report"]["mechanical"]["scene_rules_removed"] == 1


def test_a_scene_stands_down_rather_than_ever_scroll_blank():
    for key in ss.SCENE_KEYS:
        js = so.OBJECTS[key].js
        assert "position==='sticky'" in js and "classList.remove('sxo-live')" in js, key


def test_the_wall_counts_photos_and_has_no_holes():
    o = so.OBJECTS["scene-wall"]
    assert "querySelectorAll('figure')" in o.js, "a line inside the wall is not a tile"
    assert "pin.appendChild(ln)" in o.js, "a line inside the wall would scale with it"
    assert "flex:1 1 calc(100%/var(--cols,3)" in o.css, "the last row stretches to fill"


def test_the_structure_a_scene_needs_cannot_be_written_over():
    for key in ss.SCENE_KEYS:
        assert "position:sticky!important" in so.OBJECTS[key].css, key


def test_a_pages_fade_in_never_hides_a_scene():
    """The page's own reveal script hid every tile until it reached where the
    tile would sit, which during the pull-back is a screen of black."""
    wall = so.OBJECTS["scene-wall"].css
    rule = next(r for r in wall.split("}") if ".sxo-scw-wall figure{flex" in r)
    assert "opacity:1!important" in rule and "transform:none!important" in rule
    assert "opacity:1!important" in so.OBJECTS["scene-reveal"].css
    assert "opacity:1!important" in so.OBJECTS["scene-lines"].css
