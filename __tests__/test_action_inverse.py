"""
test_action_inverse.py — undo.

action_registry has classified all 128 verbs by reversibility for a while,
and class A reads "cleanly undoable". The readiness audit found that was a
design judgment with nothing behind it — restore_previous_site was the only
undo a practitioner could actually press.

The safety tests here matter most. An undo that reaches the wrong verb
destroys data while claiming to repair it, so the containment properties are
asserted directly: no inverse may be a class C verb, no inverse may be bulk,
and nothing unlisted is ever guessed at.
"""
from __future__ import annotations

import pytest

import action_inverse as ai
import action_registry


# ─── containment: what undo can never do ─────────────────────────────

def test_no_inverse_is_a_class_c_verb():
    """The load-bearing safety property. undo_last is class A only because
    every inverse it can reach is itself class A — if one were C, undo would
    be a hole straight through the send/money wall."""
    for verb, inv in ai.INVERSES.items():
        assert action_registry.reversibility(inv.verb) != "C", (
            f"undoing {verb} would run the class C verb {inv.verb}")


def test_no_inverse_is_bulk():
    for verb, inv in ai.INVERSES.items():
        assert not action_registry.is_bulk(inv.verb), (
            f"undoing {verb} would run the bulk verb {inv.verb}")


def test_every_inverse_is_a_real_handler():
    """An inverse naming a verb that does not exist fails at the worst
    moment — when someone is trying to take something back."""
    from chief_of_staff import ACTION_HANDLERS
    for verb, inv in ai.INVERSES.items():
        assert inv.verb in ACTION_HANDLERS, (
            f"{verb}'s inverse '{inv.verb}' is not a registered handler")


def test_every_undoable_verb_is_itself_classified():
    for verb in ai.INVERSES:
        assert action_registry.classification(verb) is not None, (
            f"{verb} has an inverse but no registry classification")


def test_nothing_unlisted_is_guessed_at():
    """No fallback that invents an inverse — same discipline as
    action_registry's default-deny."""
    for verb in ("delete_contact", "send_sms", "approve_draft", "create_invoice",
                 "publish_post", "batch_email", "not_a_real_verb"):
        assert ai.can_undo(verb) is False
        assert ai.build_inverse(verb, {}, {}) is None


# ─── the inverses that exist ─────────────────────────────────────────

def test_block_range_round_trips():
    inv = ai.build_inverse("add_block_range",
                           {"start_date": "2026-08-03", "end_date": "2026-08-07"}, {})
    assert inv["type"] == "remove_block_range"
    assert inv["start_date"] == "2026-08-03"

    back = ai.build_inverse("remove_block_range",
                            {"start_date": "2026-08-03", "end_date": "2026-08-07"}, {})
    assert back["type"] == "add_block_range"


def test_remember_inverts_to_forget_using_the_result_id():
    """The reason the log stores the RESULT and not just the payload."""
    inv = ai.build_inverse("remember", {"content": "x"}, {"memory_id": "mem-9"})
    assert inv == {"type": "forget", "memory_id": "mem-9"}


def test_remember_falls_back_to_content_when_no_id_came_back():
    inv = ai.build_inverse("remember", {"content": "prefers mornings"}, {})
    assert inv["type"] == "forget"
    assert inv["content"] == "prefers mornings"


def test_create_module_entry_needs_the_created_id():
    """Not reversible from the request alone — only from what it produced."""
    assert ai.build_inverse("create_module_entry", {"module_id": "m1"}, {}) is None
    inv = ai.build_inverse("create_module_entry", {"module_id": "m1"},
                           {"entry_id": "e7"})
    assert inv == {"type": "delete_module_entry", "module_id": "m1",
                   "entry_id": "e7"}


def test_ledger_undo_is_a_compensating_row_not_a_deletion():
    """customer_ledger is append-only, so its undo writes the opposite row —
    which is how a ledger should reverse."""
    inv = ai.build_inverse("grant_balance",
                           {"contact_id": "c1", "amount": 6,
                            "kind": "package", "unit": "session",
                            "reason": "6-session package"}, {})
    assert inv["type"] == "consume_balance"
    assert inv["amount"] == 6
    # Must be allowed to go negative: the balance may already have been
    # drawn down since, and refusing would leave the grant un-undoable.
    assert inv["allow_overdraw"] is True


def test_consume_undo_gives_the_balance_back():
    inv = ai.build_inverse("consume_balance",
                           {"contact_id": "c1", "amount": 1,
                            "kind": "package", "unit": "session"}, {})
    assert inv["type"] == "grant_balance"
    assert inv["amount"] == 1


def test_partial_payload_refuses_rather_than_targeting_blindly():
    """A swap with none of its identifying arguments would act on the wrong
    row. Refusing is the only safe answer."""
    assert ai.build_inverse("add_block_range", {}, {}) is None


def test_a_build_that_raises_refuses():
    """A build that blows up cannot be trusted to target the right row."""
    bad = ai.Inverse("forget", "x", lambda a, r: 1 / 0)
    ai.INVERSES["_probe"] = bad
    try:
        assert ai.build_inverse("_probe", {}, {}) is None
    finally:
        del ai.INVERSES["_probe"]


# ─── honest refusals ─────────────────────────────────────────────────

@pytest.mark.parametrize("verb", [
    "update_contact", "update_contact_status", "update_module_entry",
    "update_offering", "update_voice_style",
])
def test_update_verbs_are_refused_with_the_actual_reason(verb):
    """Half-reversing an update by guessing a default is worse than
    refusing, because it looks like it worked."""
    assert ai.can_undo(verb) is False
    assert "before" in ai.why_not(verb).lower() or "previous" in ai.why_not(verb).lower()


def test_class_c_refusal_explains_itself():
    reason = ai.why_not("send_sms")
    assert "left the system" in reason or "money" in reason


def test_bulk_refusal_explains_itself():
    assert "set at once" in ai.why_not("batch_email")


def test_read_refusal_explains_itself():
    assert "didn't change anything" in ai.why_not("catch_up")


def test_unknown_verb_gets_a_plain_answer():
    assert ai.why_not("nonsense_verb")


# ─── the NOT_UNDOABLE list stays honest ──────────────────────────────

def test_not_undoable_entries_are_real_verbs():
    """A reason attached to a verb that does not exist is dead text."""
    from chief_of_staff import ACTION_HANDLERS
    for verb in ai.NOT_UNDOABLE_REASON:
        assert verb in ACTION_HANDLERS, f"{verb} has a reason but no handler"


def test_a_verb_in_both_maps_resolves_to_not_undoable():
    """write_off_time is in INVERSES as a placeholder AND in the reason map.
    The reason map must win, or undo would run a placeholder that returns
    None and report a confusing failure."""
    assert "write_off_time" in ai.INVERSES
    assert "write_off_time" in ai.NOT_UNDOABLE_REASON
    assert ai.can_undo("write_off_time") is False
    assert "write_off_time" not in ai.undoable_verbs()


def test_undo_window_is_short():
    """Undo is a short-window affordance, not the audit trail. Reversing
    something from last week should surprise nobody, because it cannot
    happen."""
    assert 1 <= ai.UNDO_WINDOW_HOURS <= 72
