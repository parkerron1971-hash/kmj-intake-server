"""
test_brand_print_colors.py — the Brandpad rule: hex is truth, print
values are derived but EDITABLE.

The exported brand book prints a CMYK build for every swatch, converted
arithmetically from hex and labelled an approximation — because a real
conversion needs the press profile and the stock. That label is honest,
but it is also the end of the road: when the practitioner's printer
hands back the actual build, there was nowhere to put it, so the book
kept printing the guess.

What is storable is exactly what cannot be derived:
  • RGB is exact from hex. Never stored.
  • CMYK is an approximation. Storable.
  • Pantone cannot be derived at all — no PMS library ships here.
    Storable.

Free text on purpose: a printer says "C0 M13 Y100 K0, uncoated" or
"PMS 116 C", and four integers would lose the half that matters.
"""
import brand_engine


def _bundle(monkeypatch, brand_kit):
    def fake_one(table, col, val):
        if table == "businesses":
            return {"id": "biz-1", "name": "KMJ", "owner_id": "o1",
                    "settings": {"brand_kit": brand_kit}}
        return {}
    monkeypatch.setattr(brand_engine, "_safe_get_one", fake_one)
    return brand_engine.get_bundle("biz-1", use_cache=False)


def test_stored_values_reach_the_bundle(monkeypatch):
    b = _bundle(monkeypatch, {
        "colors": {"primary": "#2E7DFF"},
        "print_colors": {"primary": {"cmyk": "C82 M51 Y0 K0 uncoated",
                                     "pantone": "PMS 2727 C"}},
    })
    pc = b["design"]["print_colors"]
    assert pc["primary"]["cmyk"] == "C82 M51 Y0 K0 uncoated"
    assert pc["primary"]["pantone"] == "PMS 2727 C"


def test_no_stored_values_is_an_empty_map_not_a_missing_key(monkeypatch):
    b = _bundle(monkeypatch, {"colors": {"primary": "#2E7DFF"}})
    assert b["design"]["print_colors"] == {}


def test_the_empty_bundle_carries_the_key(monkeypatch):
    monkeypatch.setattr(brand_engine, "_safe_get_one", lambda t, c, v: None)
    assert brand_engine.get_bundle("nope", use_cache=False)["design"]["print_colors"] == {}


# ── normalize guards ────────────────────────────────────────────────

def test_unknown_roles_and_fields_are_dropped(monkeypatch):
    out = brand_engine._normalize_brand_kit({"print_colors": {
        "primary": {"cmyk": "C0 M0 Y0 K100", "hex": "#000", "rgb": "0,0,0"},
        "not_a_role": {"cmyk": "C1"},
    }})
    assert out["print_colors"] == {"primary": {"cmyk": "C0 M0 Y0 K100"}}, \
        "only whitelisted roles and fields may be stored"


def test_a_blank_deletes_rather_than_storing_empty(monkeypatch):
    """Clearing must fall back to the derived approximation, not print
    nothing where a CMYK build should be."""
    out = brand_engine._normalize_brand_kit({"print_colors": {
        "primary": {"cmyk": "   ", "pantone": "PMS 116 C"},
    }})
    assert out["print_colors"] == {"primary": {"pantone": "PMS 116 C"}}


def test_clearing_every_field_removes_the_key_entirely(monkeypatch):
    out = brand_engine._normalize_brand_kit({"print_colors": {"primary": {"cmyk": ""}}})
    assert "print_colors" not in out


def test_values_are_length_capped(monkeypatch):
    out = brand_engine._normalize_brand_kit({"print_colors": {
        "primary": {"cmyk": "x" * 500}}})
    assert len(out["print_colors"]["primary"]["cmyk"]) == 60


def test_a_non_dict_is_discarded_not_stored(monkeypatch):
    out = brand_engine._normalize_brand_kit({"print_colors": "PMS 116"})
    assert "print_colors" not in out


def test_normalize_is_idempotent(monkeypatch):
    kit = {"print_colors": {"accent": {"pantone": "PMS 355 C"}}}
    once = brand_engine._normalize_brand_kit(kit)
    twice = brand_engine._normalize_brand_kit(once)
    assert once["print_colors"] == twice["print_colors"]
