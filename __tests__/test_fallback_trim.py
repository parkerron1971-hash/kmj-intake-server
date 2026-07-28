"""
The backup brain's prompt trim.

Forwarding Chief's whole system prompt is what made this feature
impossible: ~33,500 tokens against a 30,000 TPM ceiling, so OpenAI
rejected the request before the model saw a word of it. The backup brain
had never once answered.

These tests defend the trim, and one property that is not about size at
all: the backup brain does not ACT. A degraded model emitting
[ACTION:{...}] tags that create, send, invoice or book is the single
combination worth refusing outright.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import fallback_brain as fb


# Sized to the real thing. OpenAI reported 33,565 tokens for one Chief
# turn; at ~4 chars/token that is ~134k characters, and the manual is the
# overwhelming majority of it. A toy-sized fixture would pass a weaker
# assertion than the bug deserves.
def _prompt(universal="CORE RULES\n" * 150,
            manual="OPERATING MANUAL AND ACTION CATALOGUE LINE\n" * 2600,
            state="LIVE: revenue 4820, 3 sessions today\n" * 300):
    return (universal + "[[CHIEF_GLOBAL_SPLIT]]" + manual
            + "[[CHIEF_CACHE_SPLIT]]" + state)


def test_the_fixture_matches_the_real_failure():
    """Guards the guard: if this fixture drifts small, every size
    assertion below silently weakens."""
    assert len(fb._flatten_system(_prompt())) // 4 > 30_000, (
        "fixture must exceed the 30k TPM ceiling, or it isn't reproducing the bug")


# ─── size: the whole point ───────────────────────────────────────────

def test_trim_makes_the_prompt_fit():
    """A realistically-sized prompt must come out far under the ceiling
    that rejected it. Roughly 4 chars per token."""
    before = fb._flatten_system(_prompt())
    after = fb._fallback_system(_prompt())
    assert len(after) < len(before) / 5, "expected a large reduction"
    assert len(after) // 4 < 30_000, "still would not fit a 30k TPM ceiling"


def test_the_manual_is_what_gets_dropped():
    """Segment 2 is the bulk — the operating manual and the ~128-verb
    action catalogue. It is not needed by something that cannot act."""
    out = fb._fallback_system(_prompt(manual="MANUAL LINE\n" * 2000))
    assert out.count("MANUAL LINE") * len("MANUAL LINE") <= fb.FALLBACK_VOICE_CHARS


def test_live_state_survives():
    """Segment 3 is the part that actually answers 'how did this week go'.
    Trimming everything would be easy and useless."""
    out = fb._fallback_system(_prompt())
    assert "revenue 4820" in out


def test_message_history_is_capped():
    msgs = [{"role": "user", "content": f"m{i}"} for i in range(40)]
    assert len(fb._trim_messages(msgs)) == fb.FALLBACK_MAX_MESSAGES
    assert fb._trim_messages(msgs)[-1]["content"] == "m39", "must keep the RECENT turns"


def test_short_history_is_untouched():
    msgs = [{"role": "user", "content": "only one"}]
    assert fb._trim_messages(msgs) == msgs


# ─── the backup brain does not act ───────────────────────────────────

def test_it_is_told_it_cannot_act():
    out = fb._fallback_system(_prompt())
    assert "CANNOT take actions" in out
    assert "Never emit an [ACTION:...] tag" in out


def test_worked_action_examples_are_scrubbed_from_the_voice_slice():
    """Telling the model 'never emit [ACTION:...]' while handing it worked
    examples of exactly that is an instruction fighting a demonstration.
    Demonstrations usually win, so the examples go."""
    system = _prompt(manual=(
        'Voice: warm and direct.\n'
        '[ACTION:{"type":"send_sms","message":"hi"}]\n'
        'Keep replies short.\n'
        '[ACTION:{"type":"create_invoice","amount":500}]\n'))
    out = fb._fallback_system(system)
    voice = out.split("=== HOW THIS BUSINESS SOUNDS ===")[1].split("=== LIVE")[0]
    assert "send_sms" not in voice
    assert "create_invoice" not in voice
    assert "warm and direct" in voice, "scrubbing must not eat the guidance"
    assert "Keep replies short" in voice


# ─── robustness ──────────────────────────────────────────────────────

def test_handles_a_prompt_with_no_markers():
    """The Strategy Coach prompt carries neither marker."""
    out = fb._fallback_system("just a plain prompt with no markers")
    assert "CANNOT take actions" in out
    assert "plain prompt" in out


def test_handles_block_list_form():
    out = fb._fallback_system([{"type": "text", "text": "block one"},
                               {"type": "text", "text": "block two"}])
    assert "CANNOT take actions" in out


def test_handles_empty_and_none():
    for empty in (None, "", []):
        out = fb._fallback_system(empty)
        assert "CANNOT take actions" in out, "the rules must survive an empty prompt"


# ─── owner notification: two channels that fail differently ──────────

def _reset_window():
    fb._last_notified = 0.0


def test_push_disabled_is_reported_not_swallowed(monkeypatch, caplog):
    """VAPID unset makes send_to_user return 0 with no error and no log —
    which is how the first live test looked like 'the notification never
    fired'. It had fired; only the push half was invisible."""
    import logging
    _reset_window()

    class _WD:
        @staticmethod
        async def _log_finding(c, h, t, d, pending): return None
        @staticmethod
        async def _owner_user_id(c, h): return "owner-1"

    monkeypatch.setitem(sys.modules, "platform_watchdog", _WD)
    monkeypatch.setitem(sys.modules, "lead_admin",
                        type("M", (), {"_service_headers": staticmethod(lambda: {})}))
    pushes = []
    monkeypatch.setitem(sys.modules, "push_notifications", type("P", (), {
        "push_enabled": staticmethod(lambda: False),
        "send_to_user": staticmethod(lambda *a, **k: pushes.append(1) or 0)}))

    import asyncio
    with caplog.at_level(logging.INFO, logger="fallback_brain"):
        asyncio.run(fb._notify_owner("anthropic down"))
    text = caplog.text
    assert "VAPID" in text, "a disabled push must say so"
    assert "Mission Control entry was still written" in text
    assert not pushes, "must not attempt a send when push is disabled"


def test_push_delivery_count_is_logged(monkeypatch, caplog):
    """send_to_user returns a device count. Discarding it is what made
    'did the owner get told?' unanswerable."""
    import logging, asyncio
    _reset_window()

    class _WD:
        @staticmethod
        async def _log_finding(c, h, t, d, pending): return None
        @staticmethod
        async def _owner_user_id(c, h): return "owner-1"

    monkeypatch.setitem(sys.modules, "platform_watchdog", _WD)
    monkeypatch.setitem(sys.modules, "lead_admin",
                        type("M", (), {"_service_headers": staticmethod(lambda: {})}))
    monkeypatch.setitem(sys.modules, "push_notifications", type("P", (), {
        "push_enabled": staticmethod(lambda: True),
        "send_to_user": staticmethod(lambda *a, **k: 2)}))

    with caplog.at_level(logging.INFO, logger="fallback_brain"):
        asyncio.run(fb._notify_owner("anthropic down"))
    assert "delivered to 2 device(s)" in caplog.text


def test_zero_devices_is_a_warning_not_a_success(monkeypatch, caplog):
    import logging, asyncio
    _reset_window()

    class _WD:
        @staticmethod
        async def _log_finding(c, h, t, d, pending): return None
        @staticmethod
        async def _owner_user_id(c, h): return "owner-1"

    monkeypatch.setitem(sys.modules, "platform_watchdog", _WD)
    monkeypatch.setitem(sys.modules, "lead_admin",
                        type("M", (), {"_service_headers": staticmethod(lambda: {})}))
    monkeypatch.setitem(sys.modules, "push_notifications", type("P", (), {
        "push_enabled": staticmethod(lambda: True),
        "send_to_user": staticmethod(lambda *a, **k: 0)}))

    with caplog.at_level(logging.INFO, logger="fallback_brain"):
        asyncio.run(fb._notify_owner("anthropic down"))
    assert "reached 0 devices" in caplog.text


def test_notification_is_once_per_window(monkeypatch, caplog):
    """One push per outage, not one per failed turn."""
    import logging, asyncio
    _reset_window()
    calls = []

    class _WD:
        @staticmethod
        async def _log_finding(c, h, t, d, pending): calls.append(1)
        @staticmethod
        async def _owner_user_id(c, h): return None

    monkeypatch.setitem(sys.modules, "platform_watchdog", _WD)
    monkeypatch.setitem(sys.modules, "lead_admin",
                        type("M", (), {"_service_headers": staticmethod(lambda: {})}))
    monkeypatch.setitem(sys.modules, "push_notifications", type("P", (), {
        "push_enabled": staticmethod(lambda: False),
        "send_to_user": staticmethod(lambda *a, **k: 0)}))

    with caplog.at_level(logging.INFO, logger="fallback_brain"):
        asyncio.run(fb._notify_owner("first"))
        asyncio.run(fb._notify_owner("second"))
    assert len(calls) == 1, "second call within the window must stay quiet"
    assert "already notified this window" in caplog.text
