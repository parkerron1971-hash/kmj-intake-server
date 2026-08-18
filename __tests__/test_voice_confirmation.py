"""A spoken class-C action holds once and asks for a spoken yes.

Kevin's Agent Mode spec, the safety row: "Consequence — spoken
confirm-back with the value read aloud, then an explicit yes. Never
fires on an ambient 'yeah'."

Class-C doctrine is "never UNPROMPTED, not never" — on a typed turn the
practitioner asking IS the approval, because they wrote the words and
can see the draft. A voice turn is weaker evidence for the same claim,
and for reasons that have nothing to do with trusting the practitioner:
recognition mishears, a room can speak, and there is no draft on screen
to glance at before it goes.

So the action is not refused. It is deferred to a second, deliberate
breath — the same shape as the untrusted-taint hold beside it.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as cos

_BIZ = {"id": "biz-1", "name": "KMJ Creative Solutions", "type": "coach",
        "owner_id": "user-1", "settings": {}}


def _gate(atype, action=None, *, voice=False, confirmed=False, executed_c=0):
    tv = cos._TURN_IS_VOICE.set(voice)
    tc = cos._TURN_CONFIRMED.set(confirmed)
    try:
        return asyncio.run(cos._gate_class_c(None, _BIZ, atype, action or {}, executed_c))
    finally:
        cos._TURN_IS_VOICE.reset(tv)
        cos._TURN_CONFIRMED.reset(tc)


def _a_class_c_verb() -> str:
    import action_registry
    for verb, entry in action_registry.REGISTRY.items():
        if (entry.get("effect") == action_registry.WRITE
                and entry.get("reversibility") == "C"
                and not entry.get("bulk")):
            return verb
    raise AssertionError("no single-target class-C verb in the registry")


# ── the grammar itself ───────────────────────────────────────────────

def test_a_deliberate_phrase_confirms():
    for said in ("send it", "Send it.", "go ahead", "do it", "confirm",
                 "yes send it", "ok go ahead", "approve it", "alright, do it"):
        assert cos._is_voice_confirmation(said), said


def test_bare_assent_never_confirms():
    """The whole point. These are what a person says to someone ELSE in
    the room while the mic is open."""
    for said in ("yes", "yeah", "ok", "okay", "sure", "mhm", "right", "please"):
        assert not cos._is_voice_confirmation(said), said


def test_an_instruction_that_merely_contains_send_it_is_not_a_confirmation():
    """"Send it to Marcus and then check my calendar" is a fresh request
    that must hold on its own merits, not a go-ahead for whatever was
    pending."""
    for said in ("send it to Marcus and then check my calendar",
                 "should I send it?",
                 "send it after you draft the other two as well please",
                 "tell Dana I'll send it next week"):
        assert not cos._is_voice_confirmation(said), said


# ── the gate ─────────────────────────────────────────────────────────

def test_a_typed_class_c_action_still_runs_untouched():
    """Typed turns are unchanged: asking in chat IS the approval."""
    verdict, _ = _gate(_a_class_c_verb(), voice=False)
    assert verdict == "execute"


def test_a_spoken_class_c_action_holds_instead_of_firing():
    verdict, res = _gate(_a_class_c_verb(), voice=True)
    assert verdict == "handled"
    assert res["failed"] is True
    assert "spoken" in res["label"].lower()
    # The model must be told NOT to narrate success — the single worst
    # outcome here is Chief saying "sent" over an action that was held.
    assert "not tell them it is done" in res["result"].lower()
    assert "send it" in res["result"]


def test_the_held_message_reads_back_who_and_how_much():
    """Hands-free means the practitioner may not be looking at the
    screen, so hearing the recipient and the amount IS the review."""
    _, res = _gate(_a_class_c_verb(),
                   {"to": "Marcus Bell", "amount": 520}, voice=True)
    assert "Marcus Bell" in res["result"]
    assert "$520.00" in res["result"]


def test_a_confirmed_spoken_action_runs():
    verdict, _ = _gate(_a_class_c_verb(), voice=True, confirmed=True)
    assert verdict == "execute"


def test_non_class_c_verbs_are_untouched_by_voice():
    """Reads and reversible writes must not grow a confirmation step —
    the mode would be unusable and nothing is at stake."""
    verdict, _ = _gate("show_view", {"view": "invoices"}, voice=True)
    assert verdict == "pass"


def test_the_turn_cap_still_wins_over_the_voice_hold():
    """Two guards, and the stricter one must not be shadowed."""
    verdict, res = _gate(_a_class_c_verb(), voice=True,
                         executed_c=cos.CLASS_C_TURN_CAP)
    assert verdict == "handled"
    assert "cap" in res["label"].lower()
