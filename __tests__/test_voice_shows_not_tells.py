"""Agent Mode: a spoken answer that wants a screen must FILL one.

Kevin, 2026-08-18, three reports deep: "still not showing at all."

Every link in the chain was sound — the client dispatches the action,
the stage renders correctly at phone width, and handle_show_view
returns type/columns/rows in exactly the shape the client checks. The
bug was a single prompt bullet telling Chief to NARRATE a screen
instead of emitting the tag that fills one:

    "If the full answer genuinely needs a screen (long lists, tables),
     do the essential part now and say the rest is on their screen."

That was written when the chat transcript sat visibly behind the voice,
so "the rest is on your screen" was true. Agent Mode hides the
transcript, so Chief said it and the screen stayed empty.

These tests pin the fix at the only place it can be enforced — the
prompt IS the capability surface — and keep the old phrasing from
coming back.
"""

import chief_models


def test_voice_block_tells_chief_to_emit_show_view():
    block = chief_models.VOICE_DELIVERY_BLOCK
    assert "show_view" in block, (
        "the voice delivery block must name show_view: a spoken turn is the "
        "ONLY surface with no transcript behind it, so the tag is the only "
        "way anything reaches the screen"
    )


def test_voice_block_no_longer_promises_a_screen_it_does_not_fill():
    """The regression tripwire. This is the exact sentence that shipped
    the bug — if it returns, Chief goes back to pointing at nothing."""
    block = chief_models.VOICE_DELIVERY_BLOCK.lower()
    assert "say the rest is on their screen" not in block
    # The replacement must actively forbid the behaviour, not merely
    # omit the old wording.
    assert "never say it is on their screen" in block


def test_voice_lane_is_chosen_by_surface_not_mode():
    """The frontend contract. ChiefCallMode used to send only
    mode='chief', which selects nothing here, so every spoken turn rode
    the CHAT lane: long markdown written to be read, then chopped to
    four sentences and spoken aloud."""
    assert chief_models.lane_for_chat("", "voice") == "voice"
    assert chief_models.lane_for_chat("chief", "voice") == "voice"
    # mode alone must NOT reach the voice lane — that was the illusion.
    assert chief_models.lane_for_chat("chief", "") == "chat"
    assert chief_models.lane_for_chat("", "") == "chat"
    # Coaches still win over the surface: their turn budget is the point.
    assert chief_models.lane_for_chat("business_coach", "voice") == "deep"
    assert chief_models.lane_for_chat("strategy_coach", "voice") == "deep"


def test_voice_block_is_appended_only_on_voice_turns():
    """A capability that never reaches the prompt does not exist. Pin the
    injection site so the block cannot be silently orphaned."""
    import inspect
    import chief_of_staff
    src = inspect.getsource(chief_of_staff)
    assert 'if lane == "voice":' in src
    assert "system = system + chief_models.VOICE_DELIVERY_BLOCK" in src


def test_voice_block_keeps_its_spoken_delivery_rules():
    """The new bullets must not have displaced what made voice replies
    speakable in the first place."""
    block = chief_models.VOICE_DELIVERY_BLOCK
    assert "110 words" in block
    assert "No markdown" in block
    assert "[ACTION:{...}] tags still work" in block


def test_the_voice_block_explains_the_confirmation_hold():
    """The hold is only safe if Chief knows to ASK. A model that meets an
    unexplained "HELD" is as likely to report success as to ask for a
    yes — and reporting success over a held send is the single worst
    outcome on this surface."""
    block = chief_models.VOICE_DELIVERY_BLOCK
    assert "HELD FOR A SPOKEN YES" in block
    assert '"send it"' in block
    assert "NEVER say it is done" in block
