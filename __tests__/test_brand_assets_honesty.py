"""
test_brand_assets_honesty.py — the mark plates must not lie.

THE DEFECT (2026-08-10 Brand Studio audit): get_bundle falls
logo_light / logo_dark / square back to `primary`. That fallback is
load-bearing for RENDERING — site_modules/header.py needs a light mark
on a dark ground whether or not one was uploaded — but the Brand Room
read `assets` directly, so those three plates showed the primary logo
with a Replace button and a Remove button that did nothing:
remove_asset deletes a key that was never set, returns ok:true, and the
tile does not change. The practitioner was told they owned three
variants they had never made.

The fix ships the truth alongside the fallback rather than removing it.
"""
import brand_engine


def _bundle(monkeypatch, brand_kit):
    """get_bundle over a stubbed business row, cache disabled."""
    def fake_one(table, col, val):
        if table == "businesses":
            return {"id": "biz-1", "name": "KMJ", "owner_id": "o1",
                    "settings": {"brand_kit": brand_kit}}
        return {}
    monkeypatch.setattr(brand_engine, "_safe_get_one", fake_one)
    return brand_engine.get_bundle("biz-1", use_cache=False)


LOGO = "https://cdn.example.com/brand/primary.png"
LIGHT = "https://cdn.example.com/brand/light.png"


def test_the_fallback_still_renders(monkeypatch):
    """Do not break rendering to fix the UI. A dark page ground still
    gets a mark even when no light variant exists."""
    b = _bundle(monkeypatch, {"assets": {"primary": LOGO}})
    assert b["assets"]["logo_light"] == LOGO
    assert b["assets"]["logo_dark"] == LOGO
    assert b["assets"]["square"] == LOGO


def test_but_the_bundle_says_which_are_real(monkeypatch):
    b = _bundle(monkeypatch, {"assets": {"primary": LOGO}})
    up = b["assets_uploaded"]
    assert up["primary"] is True
    assert up["logo_light"] is False, "an inherited plate must not read as uploaded"
    assert up["logo_dark"] is False
    assert up["square"] is False
    # favicon and social_card never fell back, and must stay honest too.
    assert up["favicon"] is False and up["social_card"] is False


def test_a_real_upload_reads_as_uploaded(monkeypatch):
    b = _bundle(monkeypatch, {"assets": {"primary": LOGO, "logo_light": LIGHT}})
    assert b["assets"]["logo_light"] == LIGHT
    assert b["assets_uploaded"]["logo_light"] is True
    assert b["assets_uploaded"]["logo_dark"] is False


def test_the_legacy_logo_url_counts_as_a_primary(monkeypatch):
    """Kits predating the assets map carry logo_url. Brand Studio saves
    there, so it is a real upload, not an inheritance."""
    b = _bundle(monkeypatch, {"logo_url": LOGO})
    assert b["assets"]["primary"] == LOGO
    assert b["assets_uploaded"]["primary"] is True


def test_blank_strings_are_not_uploads(monkeypatch):
    b = _bundle(monkeypatch, {"assets": {"primary": LOGO, "square": "   "}})
    assert b["assets_uploaded"]["square"] is False


def test_no_kit_at_all(monkeypatch):
    b = _bundle(monkeypatch, {})
    assert b["assets_uploaded"]["primary"] is False
    assert not any(b["assets_uploaded"].values())


def test_the_empty_bundle_carries_the_same_keys():
    """A consumer must never have to guess whether the key exists on one
    bundle shape and not the other."""
    empty = brand_engine._empty_bundle("")
    assert set(empty["assets_uploaded"]) == set(empty["assets"])
    assert not any(empty["assets_uploaded"].values())
