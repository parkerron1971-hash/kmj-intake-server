"""
test_brand_override_merge.py — the second override must not delete the first.

THE DEFECT (found 2026-08-11 closing out the Brand Studio arc): chapter
09 "In your name" was built so an override is never a one-way door — the
derived value is kept, an empty string resets, and only fields the owner
disagreed with are stored.

But `save_brand_kit` REPLACES settings.brand_kit wholesale, the Brand
Room sends only the field it just edited, and after each save it
re-hydrates its local kit from the bundle — which exposes WHICH fields
are overridden but not their raw values. So the second edit of a session
arrived carrying only itself, and the first one was silently dropped.

Set the copyright line, then set the signature name: the copyright line
reverts to derived with nothing anywhere saying so.

Worth the guard: a `legal_footer` override quietly reverting changes the
disclaimers on every contract the system drafts.
"""
import brand_engine


def _saved(monkeypatch, prior_kit, new_kit):
    """save_brand_kit over a stubbed row; returns what was PATCHed."""
    captured = {}

    def fake_one(table, col, val):
        return {"id": "biz-1", "name": "KMJ", "owner_id": "o1",
                "settings": {"brand_kit": prior_kit}, "brand_kit_history": []}

    def fake_patch(path, payload):
        captured.update(payload)
        return [{"id": "biz-1"}]

    monkeypatch.setattr(brand_engine, "_safe_get_one", fake_one)
    monkeypatch.setattr(brand_engine, "_sb_patch", fake_patch)
    monkeypatch.setattr(brand_engine, "invalidate_bundle_cache", lambda *a, **k: None)
    monkeypatch.setattr(brand_engine, "get_bundle", lambda *a, **k: {})
    brand_engine.save_brand_kit("biz-1", new_kit)
    return (captured.get("settings") or {}).get("brand_kit") or {}


PRIOR = {"tagline": "t", "published_overrides": {"copyright_line": "© 2026 KMJ"}}


def test_a_second_override_keeps_the_first(monkeypatch):
    out = _saved(monkeypatch, PRIOR,
                 {"tagline": "t", "published_overrides": {"signature_name": "Kevin"}})
    ov = out["published_overrides"]
    assert ov["signature_name"] == "Kevin"
    assert ov["copyright_line"] == "© 2026 KMJ", \
        "the earlier override was silently deleted by the later one"


def test_editing_the_same_field_still_replaces_it(monkeypatch):
    out = _saved(monkeypatch, PRIOR,
                 {"published_overrides": {"copyright_line": "© 2026 KMJ Creative"}})
    assert out["published_overrides"]["copyright_line"] == "© 2026 KMJ Creative"


def test_an_empty_string_still_resets(monkeypatch):
    """The reset mechanism must survive the merge — otherwise a merged
    blank would just be re-added from the prior map every save."""
    out = _saved(monkeypatch, PRIOR, {"published_overrides": {"copyright_line": ""}})
    assert "copyright_line" not in (out.get("published_overrides") or {})


def test_resetting_one_leaves_the_others(monkeypatch):
    prior = {"published_overrides": {"copyright_line": "©", "signature_name": "Kevin"}}
    out = _saved(monkeypatch, prior, {"published_overrides": {"copyright_line": ""}})
    ov = out["published_overrides"]
    assert "copyright_line" not in ov
    assert ov["signature_name"] == "Kevin"


def test_a_save_that_sends_no_overrides_does_not_wipe_them(monkeypatch):
    """"Save brand kit" from the chapters above carries no override map.
    It must not clear what chapter 09 stored."""
    out = _saved(monkeypatch, PRIOR, {"tagline": "new tagline"})
    assert out["published_overrides"]["copyright_line"] == "© 2026 KMJ"


def test_first_ever_override_needs_no_prior(monkeypatch):
    out = _saved(monkeypatch, {"tagline": "t"},
                 {"published_overrides": {"site_url": "https://kmjcreate.com"}})
    assert out["published_overrides"]["site_url"] == "https://kmjcreate.com"


def test_the_blank_legal_footer_guard_still_holds(monkeypatch):
    """A blank stored as an override would strip required disclaimers
    from every contract. It must delete, never persist."""
    prior = {"published_overrides": {"legal_footer": "All rights reserved."}}
    out = _saved(monkeypatch, prior, {"published_overrides": {"legal_footer": "   "}})
    assert "legal_footer" not in (out.get("published_overrides") or {})


def test_fonts_locked_survives_a_save_that_omits_it(monkeypatch):
    """Same class of bug, different key: the lock is set from the Type
    chapter and must not be dropped by the next unrelated save."""
    prior = {"font_pair": {"heading": "Montserrat"}, "fonts_locked": True}
    out = _saved(monkeypatch, prior, {"tagline": "x", "fonts_locked": True})
    assert out["fonts_locked"] is True
