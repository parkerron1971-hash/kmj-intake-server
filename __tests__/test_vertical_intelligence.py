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
    assert get_profile("florist") is GENERIC
    assert get_profile(None) is GENERIC
    assert get_profile("") is GENERIC
    assert get_profile("  agency  ") is GENERIC   # not in v1 dictionary


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
