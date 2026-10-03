"""
test_drop_slots.py — art-directed drop slots (the claude.ai Design
Labs move, 2026-07-25): the builder authors fillable frames with shot
direction; the owner clicks and uploads; a deterministic swap fills
the frame on BOTH the served page and the stored canvas.
"""
import site_composer as sc

_PAGE = (
    '<html><head><style>.sx-drop{display:none}'
    'body.sx-studio .sx-drop{display:flex}</style></head><body>'
    '<div class="sx-drop" data-sx-slot="hero_portrait" '
    'data-override-target="v2/drop1">'
    '<span>You at the chair, mid-cut, warm light</span></div>'
    '<div class="sx-drop" data-sx-slot="gallery_3">'
    '<span>Close-up of your tools</span></div>'
    '</body></html>')


def test_fill_swaps_only_the_named_slot():
    out = sc.fill_drop_slot(_PAGE, "hero_portrait", "https://x/photo.jpg")
    assert out is not None
    assert 'src="https://x/photo.jpg"' in out
    assert "sx-filled" in out
    # the brief is no longer visible copy; it describes the photo instead
    # (2026-10-03: a filled photo used to go in with alt="")
    assert "<span>You at the chair" not in out
    assert 'alt="You at the chair, mid-cut, warm light"' in out
    assert "Close-up of your tools" in out         # the other slot stands
    # filled slot forces visibility past the authored display:none
    assert 'style="display:block;padding:0"' in out


def test_fill_unknown_slot_returns_none():
    assert sc.fill_drop_slot(_PAGE, "nope", "https://x/p.jpg") is None


def test_fill_escapes_quotes_in_url():
    out = sc.fill_drop_slot(_PAGE, "gallery_3",
                            'https://x/p.jpg?a="b"')
    assert out is not None and '%22b%22' in out and '?a=%22' in out


def test_builder_prompt_carries_the_drop_slot_law():
    import builder_v2 as v2
    assert "sx-drop" in v2._SYSTEM and "data-sx-slot" in v2._SYSTEM
    assert "body.sx-studio .sx-drop" in v2._SYSTEM
    import spec_author as sa
    assert "DROP SLOT" in sa._SYSTEM


def test_studio_bridge_carries_the_touchable_grammar():
    """The bridge is the page-side half of the touchable preview:
    sx-studio reveals drop slots, edit mode opens words for retyping,
    drop clicks and edits post to the parent (DOM-only, no fetch)."""
    from site_modules._base import STUDIO_BRIDGE as b
    assert "sx-studio" in b
    assert "studio-edit-mode" in b and "studio-edit" in b
    assert "studio-drop" in b
    assert "contenteditable" in b
    assert "studio-select" in b          # select-to-talk survives
    assert "fetch(" not in b             # parent does every network call


def test_bridge_upgrade_replaces_older_generation():
    """A page baked with the select-only bridge must GAIN edit powers
    on re-render — the old presence-check froze pages on generation 1."""
    from site_modules._base import STUDIO_BRIDGE
    old_bridge = ("<script>(function () {\n"
                  "  if (window.parent === window) return;\n"
                  "  /* gen-1 */ parent.postMessage({type:'studio-select'},'*');\n"
                  "})();</script>")
    html = f"<html><body><p>x</p>{old_bridge}\n</body></html>"
    # the seam logic, reproduced: current-generation check + strip + inject
    import re as _re
    assert "studio-edit-mode" not in html
    out = _re.sub(r"<script>\(function \(\) \{\s*"
                  r"if \(window\.parent === window\) return;.*?</script>",
                  "", html, flags=_re.DOTALL)
    out = out.replace("</body>", STUDIO_BRIDGE + "\n</body>", 1)
    assert out.count("window.parent === window") == 1   # old one gone
    assert "studio-edit-mode" in out                     # new powers in
    assert "<p>x</p>" in out


def test_refresh_if_composed_covers_canvas_pages():
    """THE no-op bug: Edit Mode saves persisted but never reached the
    served page of a v2 site because the refresh trigger only knew
    module-composer. Canvas pages re-render (stored-canvas reuse path)
    now."""
    from unittest import mock as m
    cfg = {"html_source": "canvas", "canvas": {"html": "<html>doc</html>"}}
    with m.patch.object(sc, "gather_context",
                        return_value={"site": {"site_config": cfg}}), \
         m.patch.object(sc, "sanitize_spec", return_value=[]), \
         m.patch.object(sc, "render_and_persist") as rp:
        assert sc.refresh_if_composed("b1") is True
        rp.assert_called_once()
    # a canvas row WITHOUT a stored doc still declines
    with m.patch.object(sc, "gather_context",
                        return_value={"site": {"site_config":
                                               {"html_source": "canvas"}}}):
        assert sc.refresh_if_composed("b1") is False


# ─── a filled photo is described and joins the library (2026-10-03) ──

def test_direction_reads_the_slots_own_shot_note():
    assert sc.drop_slot_direction(_PAGE, "gallery_3") == "Close-up of your tools"
    assert sc.drop_slot_direction(_PAGE, "nope") == ""


def test_direction_is_cut_at_a_word_and_unescaped():
    long = ("Your hands at the counter &amp; the steel tray, " * 6).strip()
    page = f'<div class="sx-drop" data-sx-slot="s"><span>{long}</span></div>'
    d = sc.drop_slot_direction(page, "s")
    assert len(d) <= sc._DROP_ALT_MAX + 1 and d.endswith("…")
    assert "&amp;" not in d and "& the steel tray" in d


def test_alt_is_escaped_and_a_refill_keeps_its_description():
    page = '<div class="sx-drop" data-sx-slot="s"><span>The "big" chair</span></div>'
    once = sc.fill_drop_slot(page, "s", "https://x/1.jpg")
    assert 'alt="The &quot;big&quot; chair"' in once
    twice = sc.fill_drop_slot(once, "s", "https://x/2.jpg")
    assert 'src="https://x/2.jpg"' in twice
    assert 'alt="The &quot;big&quot; chair"' in twice


class _Lib:
    """businesses.settings as the service role sees it."""
    def __init__(self, gallery=None, fail_patch=False):
        self.settings = {"media_library": {"gallery": list(gallery or [])},
                         "brand_kit": {"logo_url": "keep-me"}}
        self.patches = []
        self.fail_patch = fail_patch

    def get(self, path):
        if path.startswith("/businesses?"):
            return [{"settings": self.settings}]
        if path.startswith("/business_sites?"):
            return [{"id": "row1", "html_content": _PAGE,
                     "site_config": {"canvas": {"html": _PAGE}}}]
        return []

    def patch(self, path, body):
        if path.startswith("/businesses?") and self.fail_patch:
            raise RuntimeError("settings write failed")
        self.patches.append((path, body))
        if path.startswith("/businesses?"):
            self.settings = body["settings"]
        return [body]


def _wire(monkeypatch, lib):
    monkeypatch.setattr(sc.sb_clients, "sb_get_as_service", lib.get)
    monkeypatch.setattr(sc.sb_clients, "sb_patch_as_service", lib.patch)
    monkeypatch.setattr(sc, "_require_owner", lambda *a, **k: None)


def test_add_photo_to_library_appends_once_and_keeps_the_rest(monkeypatch):
    lib = _Lib(gallery=[{"url": "https://x/old.jpg", "alt": "old"}])
    _wire(monkeypatch, lib)
    assert sc.add_photo_to_library("b1", "https://x/new.jpg", "the chair", "hero") is True
    gal = lib.settings["media_library"]["gallery"]
    assert [g["url"] for g in gal] == ["https://x/old.jpg", "https://x/new.jpg"]
    new = gal[-1]
    assert new["alt"] == "the chair" and new["slot"] == "hero"
    assert new["show_on_website"] is True and new["id"].startswith("gal-")
    assert lib.settings["brand_kit"] == {"logo_url": "keep-me"}
    # the same photo twice is one entry
    assert sc.add_photo_to_library("b1", "https://x/new.jpg", "again", "hero") is False
    assert len(lib.settings["media_library"]["gallery"]) == 2


class _Session:
    user = type("U", (), {"id": "u1"})()


def test_drop_fill_puts_the_photo_in_the_library(monkeypatch):
    lib = _Lib()
    _wire(monkeypatch, lib)
    out = sc.drop_fill(sc.DropFillBody(business_id="b1", slot="hero_portrait",
                                       url="https://x/photo.jpg"), _Session())
    assert out == {"ok": True, "slot": "hero_portrait", "in_library": True}
    site_patch = next(b for p, b in lib.patches if p.startswith("/business_sites?"))
    assert 'alt="You at the chair, mid-cut, warm light"' in site_patch["html_content"]
    assert 'alt="You at the chair' in site_patch["site_config"]["canvas"]["html"]
    gal = lib.settings["media_library"]["gallery"]
    assert gal[-1]["url"] == "https://x/photo.jpg"
    assert gal[-1]["alt"] == "You at the chair, mid-cut, warm light"


def test_a_failed_library_write_never_fails_the_fill(monkeypatch):
    lib = _Lib(fail_patch=True)
    _wire(monkeypatch, lib)
    out = sc.drop_fill(sc.DropFillBody(business_id="b1", slot="gallery_3",
                                       url="https://x/p.jpg"), _Session())
    assert out["ok"] is True and out["in_library"] is False
    assert any(p.startswith("/business_sites?") for p, _ in lib.patches)
