"""
test_chief_go_ahead_releases_a_hold.py — "go ahead" means go (2026-09-23).

Kevin asked Chief to void three test invoices by voice. The first turn held
them for a spoken yes, as designed. He said "Go ahead." That turn's context
loaded an inbox email with instruction-shaped text, so the taint gate held
all three AGAIN and said "if this was your idea, ask me again" — and every
later turn loaded the same inbox. The explicit yes the taint doctrine asks
for could never be given.

A hold now remembers what it held (chief_holds) and names its target; a
whole-message go-ahead releases that action on that target, and nothing
else. A bare "yes" still releases nothing (Agent Mode safety ruling).
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_holds
import chief_of_staff as cos
from chief_code import turn_scope

_BIZ = {"id": "biz-1", "name": "KMJ", "type": "coach", "owner_id": "user-1", "settings": {}}
INV12 = {"type": "void_invoice", "invoice_id": "i-12", "invoice_number": "INV-2026-012"}
INV13 = {"type": "void_invoice", "invoice_id": "i-13", "invoice_number": "INV-2026-013"}


@pytest.fixture(autouse=True)
def _clean():
    chief_holds.clear()
    cos._UNTRUSTED_TAINT.set(0)
    yield
    chief_holds.clear()
    cos._UNTRUSTED_TAINT.set(0)


def _gate(action, *, voice=False, message="", taint=0, user="user-1"):
    tokens = [
        (cos._TURN_IS_VOICE, cos._TURN_IS_VOICE.set(voice)),
        (cos._TURN_CONFIRMED, cos._TURN_CONFIRMED.set(voice and cos._is_voice_confirmation(message))),
        (cos._TURN_GO_AHEAD, cos._TURN_GO_AHEAD.set(cos._is_voice_confirmation(message))),
        (turn_scope, turn_scope.set({"user_id": user, "words": message})),
    ]
    cos._UNTRUSTED_TAINT.set(taint)
    try:
        return asyncio.run(cos._gate_class_c(None, _BIZ, action["type"], dict(action), 0))
    finally:
        for var, tok in reversed(tokens):
            var.reset(tok)
        cos._UNTRUSTED_TAINT.set(0)


def test_the_live_sequence_voids_after_go_ahead():
    # 18:15 — "delete those invoices", by voice: held for a spoken yes.
    verdict, held = _gate(INV12, voice=True, message="delete those invoices")
    assert verdict == "handled" and held["needs_confirmation"]
    assert "INV-2026-012" in held["label"]
    # 18:16 — "Go ahead.", by voice, on a TAINTED turn: runs.
    verdict, _ = _gate(INV12, voice=True, message="Go ahead.", taint=1)
    assert verdict == "execute"


def test_a_taint_hold_is_released_by_a_typed_go_ahead_and_names_its_target():
    verdict, held = _gate(INV13, message="void INV-2026-013", taint=1)
    assert verdict == "handled" and held["needs_confirmation"]
    assert "INV-2026-013" in held["label"] and "ask me again" not in held["label"]
    verdict, _ = _gate(INV13, message="go ahead", taint=1)
    assert verdict == "execute"


def test_a_go_ahead_releases_only_the_held_target():
    _gate(INV12, message="void INV-2026-012", taint=1)
    verdict, _ = _gate(INV13, message="go ahead", taint=1)
    assert verdict == "handled", "a go-ahead must not release a different invoice"


def test_each_hold_is_released_once():
    _gate(INV12, message="void it", taint=1)
    assert _gate(INV12, message="go ahead", taint=1)[0] == "execute"
    assert _gate(INV12, message="go ahead", taint=1)[0] == "handled"


def test_bare_yes_releases_nothing():
    _gate(INV12, voice=True, message="void INV-2026-012")
    verdict, _ = _gate(INV12, voice=True, message="Yes.", taint=1)
    assert verdict == "handled"


def test_another_practitioner_cannot_release_it():
    _gate(INV12, message="void it", taint=1, user="user-1")
    verdict, _ = _gate(INV12, message="go ahead", taint=1, user="user-2")
    assert verdict == "handled"


def test_a_hold_expires():
    chief_holds.remember("user-1", "biz-1", "void_invoice", INV12, now=0)
    assert not chief_holds.release("user-1", "biz-1", "void_invoice", INV12, now=chief_holds.TTL_S + 1)


def test_a_different_amount_is_not_the_same_action():
    pay = {"type": "record_payment", "invoice_id": "i-12", "amount": 55}
    chief_holds.remember("user-1", "biz-1", "record_payment", pay)
    assert not chief_holds.release("user-1", "biz-1", "record_payment", {**pay, "amount": 550})
    assert chief_holds.release("user-1", "biz-1", "record_payment", pay)


def test_three_holds_are_read_back_as_one_sentence():
    held = [_gate(inv, message="void them", taint=1)[1] for inv in (
        INV12, INV13, {"type": "void_invoice", "invoice_id": "i-14", "invoice_number": "INV-2026-014"})]
    reply = cos._deterministic_fallback_reply(held)
    assert reply.count("I need your go-ahead") == 1
    for n in ("INV-2026-012", "INV-2026-013", "INV-2026-014"):
        assert n in reply
