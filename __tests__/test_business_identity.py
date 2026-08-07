"""
Pins the consolidation contract for business identity.

The bug this replaces: EIN was captured in three unconnected stores, so a
practitioner who entered it in Foundation Phase 2 still saw
"— add your EIN in the 1099 panel —" on a 1099 draft.
"""

import pytest

import business_identity


# ─── normalize_entity_type ───────────────────────────────────────────
# recommend_entity() asks the model for free text, so everything stored
# has to survive this function first.

@pytest.mark.parametrize("raw,expected", [
    ("Sole Proprietor", "sole_prop"),
    ("sole proprietorship", "sole_prop"),
    ("Single-Member LLC", "single_member_llc"),
    ("single member llc", "single_member_llc"),
    ("SMLLC", "single_member_llc"),
    ("Multi-Member LLC", "multi_member_llc"),
    ("S-Corp", "s_corp"),
    ("S Corporation", "s_corp"),
    ("C-Corp", "c_corp"),
    ("Partnership", "partnership"),
    ("501(c)(3)", "nonprofit"),
])
def test_normalize_maps_the_forms_the_model_actually_returns(raw, expected):
    assert business_identity.normalize_entity_type(raw) == expected


def test_an_s_corp_election_on_an_llc_is_stored_as_s_corp():
    """The election drives the tax treatment, so it wins over the bare LLC."""
    assert business_identity.normalize_entity_type("S-Corp election on LLC") == "s_corp"
    assert business_identity.normalize_entity_type("LLC taxed as an S-Corp") == "s_corp"


def test_a_bare_llc_is_ambiguous_and_is_not_guessed():
    """Guessing single-member is the exact silent assumption this removes."""
    assert business_identity.normalize_entity_type("LLC") is None


def test_a_bare_llc_resolves_when_member_count_disambiguates():
    assert business_identity.normalize_entity_type("LLC", member_count=1) == "single_member_llc"
    assert business_identity.normalize_entity_type("LLC", member_count=3) == "multi_member_llc"


@pytest.mark.parametrize("raw", [None, "", "   ", "something else entirely"])
def test_unrecognized_text_is_never_stored(raw):
    assert business_identity.normalize_entity_type(raw) is None


def test_every_normalized_value_is_allowed_by_the_db_constraint():
    """A value this function emits but the CHECK rejects would 400 at write time."""
    samples = ["Sole Proprietor", "Single-Member LLC", "Multi-Member LLC",
               "Partnership", "S-Corp", "C-Corp", "nonprofit"]
    for raw in samples:
        assert business_identity.normalize_entity_type(raw) in business_identity.ENTITY_TYPES


# ─── get_identity / payer_block ──────────────────────────────────────

BIZ_WITH_LEGACY_PAYER = {
    "id": "biz-1",
    "name": "Clean Quick",
    "settings": {"financial": {"payer": {
        "name": "Clean Quick LLC", "ein": "12-3456789",
        "line1": "500 Main St", "city": "Detroit", "state": "MI", "zip": "48226",
    }}},
}


def test_legacy_payer_blob_still_works_before_the_backfill(monkeypatch):
    """Un-migrated rows must not regress — the profile is empty here."""
    monkeypatch.setattr(business_identity.business_profile_agent,
                        "get_profile", lambda _b: {})
    ident = business_identity.get_identity("biz-1", BIZ_WITH_LEGACY_PAYER)
    assert ident["ein"] == "12-3456789"
    assert ident["legal_name"] == "Clean Quick LLC"
    assert ident["address_city"] == "Detroit"


def test_profile_wins_over_the_legacy_blob(monkeypatch):
    monkeypatch.setattr(business_identity.business_profile_agent, "get_profile",
                        lambda _b: {"ein": "98-7654321", "legal_name": "Clean Quick Holdings LLC"})
    ident = business_identity.get_identity("biz-1", BIZ_WITH_LEGACY_PAYER)
    assert ident["ein"] == "98-7654321"
    assert ident["legal_name"] == "Clean Quick Holdings LLC"
    # Gaps still fall through to the blob.
    assert ident["address_city"] == "Detroit"


def test_an_ein_entered_in_foundation_reaches_the_1099_payer_block(monkeypatch):
    """The whole point of the consolidation, asserted end to end."""
    monkeypatch.setattr(business_identity.business_profile_agent, "get_profile",
                        lambda _b: {"ein": "45-6789012", "legal_name": "Solo Practice LLC",
                                    "address_line1": "9 Elm", "address_city": "Ann Arbor",
                                    "address_state": "MI", "address_zip": "48104"})
    payer = business_identity.payer_block("biz-1", {"id": "biz-1", "name": "Solo Practice"})
    assert payer["ein"] == "45-6789012"
    assert payer["name"] == "Solo Practice LLC"
    assert payer["city_state_zip"] == "Ann Arbor, MI 48104"
    assert payer["complete"] is True


def test_payer_block_is_incomplete_without_an_ein(monkeypatch):
    monkeypatch.setattr(business_identity.business_profile_agent,
                        "get_profile", lambda _b: {"address_line1": "9 Elm"})
    payer = business_identity.payer_block("biz-1", {"id": "biz-1", "name": "Solo"})
    assert payer["complete"] is False
    assert payer["ein"] == ""


def test_display_name_is_a_flagged_last_resort_for_legal_name(monkeypatch):
    """A display name is not a filed legal name; callers must be able to tell."""
    monkeypatch.setattr(business_identity.business_profile_agent,
                        "get_profile", lambda _b: {})
    ident = business_identity.get_identity("biz-1", {"id": "biz-1", "name": "Clean Quick"})
    assert ident["legal_name"] == "Clean Quick"
    assert ident["legal_name_is_fallback"] is True


def test_a_profile_read_failure_does_not_take_down_a_report(monkeypatch):
    def boom(_b):
        raise RuntimeError("supabase down")
    monkeypatch.setattr(business_identity.business_profile_agent, "get_profile", boom)
    payer = business_identity.payer_block("biz-1", BIZ_WITH_LEGACY_PAYER)
    assert payer["ein"] == "12-3456789"   # legacy blob still carries the draft


# ─── set_identity ────────────────────────────────────────────────────

def test_set_identity_drops_unknown_fields_and_normalizes(monkeypatch):
    captured = {}

    def fake_upsert(business_id, payload):
        captured.update(payload)
        return {"business_id": business_id, **payload}

    monkeypatch.setattr(business_identity.business_profile_agent,
                        "upsert_profile", fake_upsert)
    business_identity.set_identity(
        "biz-1",
        ein="12-3456789",
        entity_type="S-Corp election on LLC",
        governing_state="mi",
        favorite_color="blue",          # not an identity field
    )
    assert captured["ein"] == "12-3456789"
    assert captured["entity_type"] == "s_corp"
    assert captured["governing_state"] == "MI"
    assert "favorite_color" not in captured


def test_set_identity_refuses_to_store_an_unrecognized_entity_type(monkeypatch):
    captured = {}
    monkeypatch.setattr(business_identity.business_profile_agent, "upsert_profile",
                        lambda _b, payload: captured.update(payload) or payload)
    business_identity.set_identity("biz-1", ein="12-3456789", entity_type="LLC")
    assert captured["ein"] == "12-3456789"
    assert "entity_type" not in captured   # ambiguous -> omitted, not guessed


def test_set_identity_with_nothing_usable_writes_nothing(monkeypatch):
    def fail(*_a, **_k):
        raise AssertionError("upsert_profile must not be called for an empty payload")
    monkeypatch.setattr(business_identity.business_profile_agent, "upsert_profile", fail)
    assert business_identity.set_identity("biz-1", legal_name=None) is None
