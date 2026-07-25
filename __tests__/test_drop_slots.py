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
    assert "mid-cut" not in out                    # the brief is gone
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
