"""
test_voice_input_metering.py — voice input stops being anonymous.

WHAT WAS WRONG (measured against production, 2026-08-24)

  /ai/whisper wrote its api_usage row with neither a business_id nor a
  user_id. Over 2026-08-10..24 that was 370 calls and $9.12 — 19.8% of
  the platform's entire AI bill, and its second-largest line after Chief
  chat itself.

  Two controls were blind to all of it. spend_guard's per-business daily
  ceiling sums api_usage BY business_id, so spend carrying no business
  can never trip anyone's tenant ceiling (it lands on the platform
  ceiling only). And the Costs view cannot show a practitioner whose
  voice minutes those were.

  It is not an edge path: 370 whisper calls against 394 /chief/backend
  turns in the same window means roughly 94% of Chief turns arrive by
  voice. This is the main interaction, unattributed.

WHAT IS AND IS NOT CHANGED HERE

  Attribution changes. PRICE DOES NOT. voice_input_price() ships at 0 —
  exactly what /ai/whisper charged before — because pricing the input
  half of the main interaction is a ruling, not a cleanup. What changes
  is that 0 is now a dial instead of a literal, so moving it is a
  Railway value change rather than a deploy. That is the rule
  pricing_config exists to enforce.
"""
import importlib
import os

import pytest


# ─── The dial ────────────────────────────────────────────────────────

def test_voice_input_price_defaults_to_zero():
    """The status quo, preserved deliberately. A cleanup that silently
    started charging for voice would be a price change wearing a bug
    fix's clothes."""
    import pricing_config
    importlib.reload(pricing_config)
    assert pricing_config.voice_input_price() == 0


def test_voice_input_price_is_env_overridable_both_names():
    """Namespaced form first (preferred in Railway), bare name as the
    documented alias — same contract as every other dial."""
    import pricing_config
    importlib.reload(pricing_config)
    for name in ("PRICE_VOICE_INPUT_PRICE", "VOICE_INPUT_PRICE"):
        os.environ.pop("PRICE_VOICE_INPUT_PRICE", None)
        os.environ.pop("VOICE_INPUT_PRICE", None)
        os.environ[name] = "3"
        try:
            assert pricing_config.voice_input_price() == 3, name
        finally:
            os.environ.pop(name, None)


def test_whisper_weight_follows_the_dial_not_a_literal():
    """The endpoint→price table must READ the dial. A literal 0 here
    would make the dial decorative — the /director/build weight hole
    that unit_weights()'s own comment was written about."""
    import pricing_config
    importlib.reload(pricing_config)
    assert pricing_config.unit_weights()["/ai/whisper"] == 0

    os.environ["PRICE_VOICE_INPUT_PRICE"] = "3"
    try:
        assert pricing_config.unit_weights()["/ai/whisper"] == 3
    finally:
        os.environ.pop("PRICE_VOICE_INPUT_PRICE", None)


# ─── The attribution ─────────────────────────────────────────────────

def test_transcribe_accepts_an_optional_business_id():
    """Optional, so a caller that never sends one still transcribes —
    the row simply lands with a user_id and no tenant, which is strictly
    better than the nothing it carried before."""
    import inspect
    import whisper_proxy
    sig = inspect.signature(whisper_proxy.transcribe)
    assert "business_id" in sig.parameters
    assert sig.parameters["business_id"].default is not inspect.Parameter.empty


def test_transcribe_attributes_the_usage_row():
    """The row must carry BOTH ids. user_id is always available (the
    endpoint is behind require_user); business_id rides the same
    ownership rail as /ai/tts."""
    import whisper_proxy
    src = inspect_source(whisper_proxy.transcribe)
    assert "user_id=user.id" in src, "usage row must name the caller"
    assert "business_id=metered_biz" in src, "usage row must name the tenant"
    assert "units=pricing_config.voice_input_price()" in src, \
        "price must come from the dial, not a literal"


def test_business_id_is_ownership_checked_never_trusted_bare():
    """A bare body field naming someone else's business would let a
    caller attribute their voice spend to another tenant — and, once the
    dial is non-zero, drain that tenant's credits. Same rail /ai/tts
    already uses."""
    import whisper_proxy
    src = inspect_source(whisper_proxy.transcribe)
    assert "_owns_business(user.id, biz)" in src


def inspect_source(fn):
    import inspect
    return inspect.getsource(fn)


# The other hole this sweep closed — _call_claude's three ERROR paths
# logging without task_type — is asserted in test_chief_prompt_shape.py,
# which owns that invariant. Pinning it in two places would let the two
# copies drift into disagreeing about the same rule.
