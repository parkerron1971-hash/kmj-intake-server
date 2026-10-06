"""Chief's own notes to itself must never look like an attack to the injection filter.

A tool result passes through untrusted_text.defuse (chief_tool_loop._shrink);
any match raises the turn's taint and holds confirmable sends. The note a
started job carries used to say "Never tell them...", which the concealment
pattern matched, so every turn that started a job was tainted.
"""
import untrusted_text
import chief_build_runtime


def test_the_started_job_note_is_not_instruction_shaped():
    assert untrusted_text.detect_injection(chief_build_runtime.LEFTOVER_NOTE) == []


def test_the_note_still_says_what_it_must():
    note = chief_build_runtime.LEFTOVER_NOTE
    assert 'submit ONE plan' in note and 'Do not promise that the rest will happen later' in note


def test_the_old_wording_would_have_tainted_the_turn():
    """Rehearse the alarm: the filter does catch the old sentence."""
    old = 'Never tell them the rest will happen later or in a next pass.'
    assert untrusted_text.detect_injection(old) == ['concealment']
