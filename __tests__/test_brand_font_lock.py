"""
test_brand_font_lock.py — the Type chapter must not promise a face the
composer is going to take away.

THE DEFECT (2026-08-11 Brand Studio close-out): site_composer DEMOTES a
pinned heading face when `brand_dna.is_generic_display(face)` and the kit
does not say `fonts_locked`. Its own comment calls fonts_locked "the
explicit 'yes, I really want Montserrat' escape hatch".

Nothing anywhere set it. Grep across both repos found `fonts_locked`
READ in three places and WRITTEN only by test fixtures — so the escape
hatch was unreachable, and a practitioner who genuinely wanted Montserrat
had no way to say so.

Meanwhile the Brand Room's Type chapter said "what you see here is what
your invoices and your site will set". Five of the eighteen faces its own
picker offers — Inter, Montserrat, Open Sans, Lato, Roboto — are in
GENERIC_DISPLAY_FACES, so for those the promise was false.

The bundle now ships the FACT (`font_heading_generic`), not the list, so
the Brand Room cannot hold a second copy of GENERIC_DISPLAY_FACES that
drifts from the one the composer actually branches on.
"""
import brand_dna
import brand_engine


def _bundle(monkeypatch, brand_kit):
    def fake_one(table, col, val):
        if table == "businesses":
            return {"id": "biz-1", "name": "KMJ", "owner_id": "o1",
                    "settings": {"brand_kit": brand_kit}}
        return {}
    monkeypatch.setattr(brand_engine, "_safe_get_one", fake_one)
    return brand_engine.get_bundle("biz-1", use_cache=False)


def test_a_generic_face_is_flagged(monkeypatch):
    b = _bundle(monkeypatch, {"font_pair": {"heading": "Montserrat", "body": "Inter"}})
    d = b["design"]
    assert d["fonts_owner_set"] is True
    assert d["font_heading_generic"] is True, \
        "Montserrat is demoted by the composer; the room must be able to say so"
    assert d["fonts_locked"] is False


def test_a_distinctive_face_is_not_flagged(monkeypatch):
    b = _bundle(monkeypatch, {"font_pair": {"heading": "Cormorant Garamond", "body": "Inter"}})
    assert b["design"]["font_heading_generic"] is False


def test_locking_is_reported(monkeypatch):
    b = _bundle(monkeypatch, {"font_pair": {"heading": "Montserrat"}, "fonts_locked": True})
    d = b["design"]
    # Still generic — the flag describes the FACE, not the outcome. The
    # room needs both to say "generic, but you have kept it".
    assert d["font_heading_generic"] is True
    assert d["fonts_locked"] is True


def test_the_flag_matches_the_function_the_composer_branches_on(monkeypatch):
    """The whole point of shipping a fact instead of a list."""
    for face in ["Inter", "Montserrat", "Open Sans", "Lato", "Roboto",
                 "Playfair Display", "Cormorant Garamond", "DM Serif Display"]:
        b = _bundle(monkeypatch, {"font_pair": {"heading": face}})
        assert b["design"]["font_heading_generic"] is brand_dna.is_generic_display(face), face


def test_the_lock_survives_a_save(monkeypatch):
    """fonts_locked is not a key _normalize_brand_kit knows about, so this
    pins that it is not dropped on the way through."""
    out = brand_engine._normalize_brand_kit(
        {"font_pair": {"heading": "Montserrat"}, "fonts_locked": True})
    assert out["fonts_locked"] is True


def test_no_kit_reports_no_owner_fonts(monkeypatch):
    b = _bundle(monkeypatch, {})
    d = b["design"]
    assert d["fonts_owner_set"] is False
    assert d["font_heading_generic"] is False, \
        "a DEFAULT_DESIGN fallback face is not an owner choice to warn about"


def test_the_empty_bundle_carries_the_same_keys(monkeypatch):
    """A consumer must never have to guess whether the key exists."""
    monkeypatch.setattr(brand_engine, "_safe_get_one", lambda t, c, v: None)
    d = brand_engine.get_bundle("nope", use_cache=False)["design"]
    assert d["fonts_owner_set"] is False
    assert d["fonts_locked"] is False
    assert d["font_heading_generic"] is False
