"""The practitioner's chosen tone has to reach the prompt as an INSTRUCTION.

voice_profile was already in Chief's context as raw JSON, and it changed
nothing: measured on a live account, the same question under "witty and dry"
and under "ministry and faith-led" returned byte-identical text. Two lines in
the personality block were the reason — a hardcoded "warm and efficient" and
a flat "never force humor", which between them overrode whatever the
practitioner had picked.

These tests pin the three things that failure needs: the register is stated
as an instruction, humor is opt-in rather than refused, and a business that
never chose a tone still gets exactly the old prompt.
"""

import re

from chief_of_staff import _build_personality_block


def _block(voice_profile):
    biz = {"created_at": None}
    if voice_profile is not None:
        biz["voice_profile"] = voice_profile
    return _build_personality_block(biz, {})


# ── No tone chosen: byte-for-byte the old behaviour ──────────────────

def test_no_voice_profile_keeps_the_original_defaults():
    out = _block(None)
    assert "Warm and efficient. Not chatty. Not robotic. The sweet spot." in out
    assert "Never force humor." in out
    assert "THE PRACTITIONER CHOSE HOW YOU SOUND" not in out


def test_empty_voice_profile_keeps_the_original_defaults():
    out = _block({})
    assert "Warm and efficient." in out
    assert "THE PRACTITIONER CHOSE HOW YOU SOUND" not in out


# ── A chosen tone becomes an instruction ─────────────────────────────

def test_chosen_tone_is_stated_as_an_instruction():
    out = _block({"tone": "formal and refined",
                  "personality": "composed, deliberate, considered"})
    assert "THE PRACTITIONER CHOSE HOW YOU SOUND: formal and refined" in out
    assert "composed, deliberate, considered" in out
    # The contradicting default must be gone, not merely outvoted.
    assert "Warm and efficient. Not chatty." not in out
    assert "in the register above" in out


def test_the_register_is_bounded_to_phrasing():
    """A tone must not become licence to be vague or long-winded."""
    out = _block({"tone": "playful and fun"})
    assert "never changes what is TRUE" in out
    assert "give the number" in out


def test_tone_without_personality_words_does_not_break():
    out = _block({"tone": "bold and direct"})
    assert "THE PRACTITIONER CHOSE HOW YOU SOUND: bold and direct." in out


# ── Humor is opt-in ──────────────────────────────────────────────────

def test_playful_tone_invites_humor():
    out = _block({"tone": "playful and fun",
                  "personality": "upbeat, lighthearted, quick to celebrate a win"})
    assert "Humor is welcome" in out
    assert "Never force humor." not in out


def test_witty_tone_invites_humor():
    out = _block({"tone": "witty and dry",
                  "personality": "clever, understated, wry but never at your expense"})
    assert "Humor is welcome" in out


def test_humor_stays_bounded_when_invited():
    out = _block({"tone": "playful and fun"})
    assert "Never at their expense" in out
    assert "never at the expense of the answer" in out


def test_serious_tones_still_refuse_humor():
    for tone, persona in [
        ("ministry and faith-led", "pastoral, scripture-aware, hopeful"),
        ("professional and polished", "trustworthy, composed, confident"),
        ("formal and refined", "composed, deliberate, considered"),
        ("warm and conversational", "approachable, empathetic, relatable"),
    ]:
        out = _block({"tone": tone, "personality": persona})
        assert "Never force humor." in out, tone
        assert "Humor is welcome" not in out, tone


def test_substring_words_do_not_trigger_humor():
    """`fun` inside "fundraising" and `dry` inside "laundry" are not jokes.

    tone is free text — Chief writes it, onboarding writes it, the
    practitioner writes it — so an unanchored match would hand a nonprofit
    a joking assistant it never asked for.
    """
    for tone in [
        "fundraising-focused and earnest",
        "laundry-service practical",
        "delightfully thorough",
        "slightly formal",
    ]:
        out = _block({"tone": tone})
        assert "Never force humor." in out, tone
        assert "Humor is welcome" not in out, tone


# ── Shape guards ─────────────────────────────────────────────────────

def test_non_string_voice_fields_do_not_crash():
    out = _block({"tone": 42, "personality": ["a", "b"]})
    assert "PERSONALITY:" in out


def test_block_is_still_one_string_with_the_fixed_rules():
    out = _block({"tone": "witty and dry"})
    for rule in [
        "Never patronize.",
        "Match their energy.",
        "just DO the thing.",
    ]:
        assert rule in out
    assert isinstance(out, str)


def test_voice_line_precedes_the_personality_rules():
    """Order matters: the register has to be read before the rules it colours."""
    out = _block({"tone": "playful and fun"})
    assert out.index("THE PRACTITIONER CHOSE HOW YOU SOUND") < out.index("PERSONALITY:")


def test_no_stray_format_placeholders_leak():
    out = _block({"tone": "witty and dry", "personality": "wry"})
    assert not re.search(r"\{[a-z_]+\}", out)
