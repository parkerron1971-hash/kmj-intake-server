"""Phase VABI v1 — vertical intelligence + context block tests."""
from __future__ import annotations

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vertical_intelligence import (
    GENERIC,
    VERTICAL_INTELLIGENCE,
    get_email_voice,
    get_empty_state_nudge,
    get_invoice_line_templates,
    get_module_suggestions,
    get_offering_suggestions,
    get_onboarding_questions,
    get_profile,
    get_voice,
    is_mapped,
    list_known_verticals,
)
from vertical_context import build_vertical_context_block


# ─── Profile resolution ─────────────────────────────────────────────


def test_known_verticals_list():
    keys = list_known_verticals()
    assert "lawyer" in keys
    assert "coach" in keys
    assert "ministry" in keys
    assert "fitness_wellness" in keys


def test_get_profile_known_vertical():
    p = get_profile("lawyer")
    assert p is not GENERIC
    assert (p.get("voice") or {}).get("formality") == "formal"


def test_get_profile_unknown_vertical_falls_back():
    # 'florist' is in no alias list, so it resolves to 'custom' — which is
    # itself the deliberate catch-all profile, not GENERIC-the-object.
    assert get_profile("florist") is VERTICAL_INTELLIGENCE["custom"]
    assert get_profile(None) is VERTICAL_INTELLIGENCE["custom"]
    assert get_profile("") is VERTICAL_INTELLIGENCE["custom"]
    # ...and it is not MAPPED, which is the distinction the context block's
    # "(generic — vertical not explicitly mapped)" label rests on.
    assert not is_mapped("florist")
    assert not is_mapped(None)


def test_get_profile_resolves_registry_aliases():
    """The bug this file used to assert as correct.

    The old line here was `assert get_profile("  agency  ") is GENERIC` with
    the comment "not in v1 dictionary". That was true when it was written
    and stopped being true the moment vertical_registry listed 'agency' as
    an alias of 'creative' — but the test kept passing, so it pinned the
    stale side of the drift instead of catching it. 'agency' was the most
    common businesses.type in the live table at the time; every one of
    those businesses was getting a generic Chief.

    Assert the CONTRACT — every alias the registry recognises reaches its
    vertical's profile — rather than any one string, so the next alias
    added to the registry is covered without editing this test."""
    import vertical_registry as reg

    for alias, canonical in reg.alias_to_canonical().items():
        assert get_profile(alias) is VERTICAL_INTELLIGENCE[canonical], (
            f"alias '{alias}' should resolve to the '{canonical}' profile")
        assert is_mapped(alias), f"alias '{alias}' should count as mapped"

    # The specific strings the live table actually held, spelled out so a
    # regression names the business that would break.
    assert get_profile("agency") is VERTICAL_INTELLIGENCE["creative"]
    assert get_profile("church") is VERTICAL_INTELLIGENCE["ministry"]
    assert get_profile("attorney") is VERTICAL_INTELLIGENCE["lawyer"]
    assert get_profile("plumber") is VERTICAL_INTELLIGENCE["contractor"]
    assert get_profile("therapy") is VERTICAL_INTELLIGENCE["therapist"]


def test_alias_gets_the_same_prompt_block_as_its_canonical():
    """The bug's actual cost was in the prompt, so assert it there too.

    A church read 'Member' on its own screens while Chief was told
    'customer=Customer' in the same request. Same business, two
    vocabularies, and only one of them visible to the practitioner."""
    import vertical_registry as reg

    def knowledge(bt):
        # Everything EXCEPT the "Business type:" line, which correctly
        # echoes the stored string — Chief seeing "Business type: coaching"
        # is truthful. It is the vocabulary, voice and reminders under it
        # that have to be the canonical vertical's.
        return [ln for ln in build_vertical_context_block({"type": bt}).split("\n")
                if not ln.startswith("Business type:")]

    for alias, canonical in reg.alias_to_canonical().items():
        if alias == canonical:
            continue
        assert knowledge(alias) == knowledge(canonical), (
            f"'{alias}' gets different knowledge than '{canonical}'")

    church = build_vertical_context_block({"type": "church"})
    assert "customer=Member" in church
    assert "generic" not in church.split("\n")[0]


def test_terminology_resolves_aliases_too():
    """vertical_terminology was keyed raw the same way; the dictionary and
    the profile have to agree or the prompt contradicts itself."""
    import vertical_terminology as vt

    assert vt.get_term("church", "customer") == vt.get_term("ministry", "customer")
    assert vt.get_term("agency", "customer") == vt.get_term("creative", "customer")
    assert vt.get_term("plumber", "service") == vt.get_term("contractor", "service")
    # Unrecognised types still fall through to the base dictionary.
    assert vt.get_term("florist", "customer") == vt.BASE_TERMS["customer"]


def test_bookkeeping_resolves_aliases_too():
    """A firm stamped 'attorney' needs the IOLTA line, not the generic
    'set aside for taxes' one — booking trust-account movement as revenue
    is the specific mistake the lawyer entry exists to prevent."""
    from vertical_intelligence import get_bookkeeping, _BOOKKEEPING_GENERIC

    assert get_bookkeeping("attorney") == get_bookkeeping("lawyer")
    assert "trust" in get_bookkeeping("attorney")["category_note"].lower()
    assert get_bookkeeping("agency") == get_bookkeeping("creative")
    assert get_bookkeeping("coaching") == get_bookkeeping("coach")
    assert get_bookkeeping("plumber") == get_bookkeeping("contractor")
    # A type with no entry still gets the baseline, not a KeyError.
    # 'florist' resolves to 'custom', the one vertical left deliberately
    # without bookkeeping framing.
    assert get_bookkeeping("florist") == _BOOKKEEPING_GENERIC
    assert get_bookkeeping(None) == _BOOKKEEPING_GENERIC


def test_get_profile_case_insensitive():
    assert get_profile("LAWYER") is get_profile("lawyer")
    assert get_profile(" Coach ") is get_profile("coach")


# ─── Onboarding questions ───────────────────────────────────────────


def test_onboarding_questions_lawyer_has_practice_areas():
    qs = get_onboarding_questions("lawyer")
    ids = [q["id"] for q in qs]
    assert "practice_areas" in ids
    assert "trust_account" in ids


def test_onboarding_questions_unknown_falls_back():
    qs = get_onboarding_questions("florist")
    assert qs == GENERIC["onboarding_questions"]


# ─── Offering suggestions ───────────────────────────────────────────


def test_offering_suggestions_lawyer():
    suggestions = get_offering_suggestions("lawyer")
    names = [s["name"] for s in suggestions]
    assert "Initial Consultation" in names
    assert "Retainer Agreement" in names


def test_offering_suggestions_coach():
    suggestions = get_offering_suggestions("coach")
    names = [s["name"] for s in suggestions]
    assert "Discovery Call" in names
    assert any("Coaching" in n or "Session" in n for n in names)


def test_offering_suggestions_unknown_falls_back():
    s = get_offering_suggestions("florist")
    assert s == GENERIC["offering_suggestions"]


# ─── Invoice line templates ─────────────────────────────────────────


def test_invoice_templates_lawyer_mentions_trust_deposit():
    templates = get_invoice_line_templates("lawyer")
    descs = [t["description"] for t in templates]
    assert any("Trust" in d for d in descs)
    assert any("hourly" in t.get("kind", "") for t in templates)


def test_invoice_templates_coach():
    templates = get_invoice_line_templates("coach")
    descs = [t["description"] for t in templates]
    assert any("Coaching" in d or "session" in d.lower() for d in descs)


def test_invoice_templates_unknown_falls_back():
    assert get_invoice_line_templates("florist") == GENERIC["invoice_line_templates"]


# ─── Email voice ────────────────────────────────────────────────────


def test_email_voice_lawyer_mentions_confidentiality():
    voice = get_email_voice("lawyer")
    assert voice.get("tone_note")
    assert any(w in voice["tone_note"].lower()
               for w in ["formal", "confidential", "privilege", "document"])


def test_email_voice_unknown_returns_generic():
    voice = get_email_voice("florist")
    assert voice == GENERIC["email_voice"]["booking_confirmation"]


# ─── Empty-state nudges ─────────────────────────────────────────────


def test_empty_state_nudge_lawyer_bookings():
    text = get_empty_state_nudge("lawyer", "bookings")
    assert "consultation" in text.lower() or "conflict" in text.lower()


def test_empty_state_nudge_unknown_falls_back():
    text = get_empty_state_nudge("florist", "bookings")
    assert text == GENERIC["empty_state_nudges"]["bookings"]


def test_empty_state_nudge_unknown_surface_returns_empty():
    text = get_empty_state_nudge("lawyer", "nonexistent_surface")
    assert text == ""


# ─── Module suggestions ────────────────────────────────────────────


def test_module_suggestions_lawyer_includes_consultation():
    sugg = get_module_suggestions("lawyer")
    slugs = [s["slug"] for s in sugg]
    assert "consultations" in slugs


def test_module_suggestions_coach_includes_discovery():
    sugg = get_module_suggestions("coach")
    slugs = [s["slug"] for s in sugg]
    assert "discovery-calls" in slugs


def test_module_suggestions_unknown_falls_back():
    sugg = get_module_suggestions("florist")
    assert sugg == GENERIC["module_suggestions"]


# ─── Voice ──────────────────────────────────────────────────────────


def test_lawyer_voice_mentions_iolta_or_privilege_taboo():
    voice = get_voice("lawyer")
    text = " ".join((voice.get("hallmarks") or []) + (voice.get("taboo") or []))
    assert "IOLTA" in text or "privilege" in text or "promising results" in text


def test_ministry_voice_taboos_giving_as_sales():
    voice = get_voice("ministry")
    taboo = " ".join(voice.get("taboo") or [])
    assert "tithe" in taboo or "giving" in taboo


# ─── Context block ─────────────────────────────────────────────────


def test_build_context_block_lawyer():
    block = build_vertical_context_block({"type": "lawyer", "name": "Test Law Firm"})
    assert "VERTICAL CONTEXT" in block
    assert "lawyer" in block.lower()
    assert "Client" in block or "Matter" in block
    # Reminder pulls one of the curated reminders
    assert "Conflict" in block or "IOLTA" in block


def test_build_context_block_unknown_marks_generic():
    block = build_vertical_context_block({"type": "florist"})
    assert "generic" in block.lower()
    assert "florist" in block


def test_build_context_block_no_business_safe():
    block = build_vertical_context_block(None)
    assert "VERTICAL CONTEXT" in block
    assert "(unset)" in block


def test_build_context_block_under_token_budget():
    """Brief says block stays under ~1500 chars; verify across all
    known verticals so a future bloat regression is caught."""
    for vertical in list_known_verticals():
        block = build_vertical_context_block({"type": vertical})
        assert len(block) < 1500, f"{vertical} block is {len(block)} chars"


# ─── Bookkeeping coverage ───────────────────────────────────────────


def test_every_vertical_has_bookkeeping_framing_except_custom():
    """Nine of fourteen verticals used to fall to _BOOKKEEPING_GENERIC.

    That single line — "Set aside for taxes as money comes in" — was what
    Chief had to go on when booking a contractor's customer deposit, a
    church's designated gift and a nonprofit's restricted grant. All three
    are money the business holds and does not own, and all three were
    bookable as revenue with nothing in the prompt saying otherwise.

    'custom' is the deliberate exception: the registry marks it
    "intentionally GENERIC — triggers Chief interactive discovery", so
    writing it a bookkeeping note would mean inventing the vertical."""
    import vertical_registry as reg
    from vertical_intelligence import BOOKKEEPING_BY_VERTICAL, get_bookkeeping

    missing = [v for v in reg.canonical_keys()
               if v != "custom" and v not in BOOKKEEPING_BY_VERTICAL]
    assert not missing, f"verticals with no bookkeeping framing: {missing}"

    assert "custom" not in BOOKKEEPING_BY_VERTICAL
    assert get_bookkeeping("custom")["category_note"] == ""

    for vertical, entry in BOOKKEEPING_BY_VERTICAL.items():
        assert entry.get("category_note"), f"{vertical} has an empty note"
        assert entry.get("nudges"), f"{vertical} has no nudges"


def test_restricted_fund_verticals_say_the_money_is_not_available():
    """The specific error each of these exists to prevent: treating money
    held under someone else's conditions as spendable revenue."""
    from vertical_intelligence import get_bookkeeping

    assert "restricted" in get_bookkeeping("nonprofit")["category_note"].lower()
    assert "designated" in get_bookkeeping("ministry")["category_note"].lower()
    assert "trust" in get_bookkeeping("lawyer")["category_note"].lower()
    # A deposit is the same shape of error in a trade.
    assert "deposit" in get_bookkeeping("contractor")["category_note"].lower()


def test_therapist_bookkeeping_stays_out_of_clinical_scope():
    """The therapist vertical launched with clinical records out of scope
    (vertical_scope.py). Bookkeeping framing is admin and billing, and has
    to stay that way — a note that reached for session content would put
    the narrowed launch's whole premise in the prompt."""
    from vertical_intelligence import get_bookkeeping

    entry = get_bookkeeping("therapist")
    blob = (entry["category_note"] + " " + " ".join(entry["nudges"])).lower()
    for forbidden in ("diagnosis", "progress note", "clinical note",
                      "session content", "treatment plan", "symptom"):
        assert forbidden not in blob, (
            f"therapist bookkeeping framing must not mention '{forbidden}'")


def test_bookkeeping_framing_does_not_pose_as_tax_advice():
    """Jurisdiction- and circumstance-dependent claims point at the
    practitioner's accountant instead of answering for them. The module
    comment says so; this asserts the one entry most likely to drift."""
    from vertical_intelligence import get_bookkeeping

    ministry = " ".join(get_bookkeeping("ministry")["nudges"]).lower()
    assert "housing allowance" in ministry
    assert "accountant" in ministry, (
        "the housing-allowance nudge must defer, not rule")
