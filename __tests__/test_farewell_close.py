"""
test_farewell_close.py — a goodbye closes the room, deterministically.

Kevin, 8/15: "when i did the goodbye's chief never closed out the chat."

The GOODBYES CLOSE THE ROOM prompt rule (#592) shipped the night before
and is real — but advisory. The model said its warm goodbye and skipped
the tag, which is the documented failure mode of prompt-only rules in
this file (the propose-framing rule earned deterministic enforcement for
exactly this, "empirically ignored — verified iteration #8"). Now the
server enforces it: a clear farewell appends set_chat_window
visible:false keep_talking:false whether or not the model remembered.

What must hold:

  1. THE DETECTOR IS NARROW. A farewell is a whole message, not a word
     in one. Kevin's own bug report contains "goodbyes" and must never
     end a session. Questions never match.
  2. ENFORCEMENT FILLS THE GAP, NEVER DOUBLES. Model forgot the tag →
     appended. Model emitted it → left alone. Coach modes → untouched
     (they have their own pause choreography).
  3. The appended action is the REAL handler's result — frontend_event
     and all — so the client closes the window through the same door
     the model's own tag would have used.

House rules: sync tests + asyncio.run (this repo has no pytest-asyncio;
CI errors on pytest.mark.asyncio).
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import chief_of_staff as cos


_BIZ = {"id": "biz-1", "name": "KMJ Creative Solutions", "type": "coach",
        "owner_id": "user-1", "settings": {}, "created_at": "2026-01-01T00:00:00Z"}


# ─────────────────────────────────────────────────────────────────────
# 1. The detector
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("msg", [
    "goodbye", "Goodbye!", "bye", "thanks, bye!", "bye bye",
    "goodnight", "good night", "ok goodnight chief thanks for everything",
    "that's all for now", "thats all", "that is all for now",
    "we're done here", "we're done", "that'll do it",
    "talk tomorrow", "talk to you later", "see you tomorrow",
    "have a good night", "signing off", "i'm heading out",
    "alright thanks so much, talk soon",
])
def test_clear_farewells_match(msg):
    assert cos._is_farewell(msg), msg


@pytest.mark.parametrize("msg", [
    # Kevin's actual bug report — contains "goodbye's", must not match.
    "when i did the goodbye's chief never closed out the chat",
    "can you say goodbye in spanish",
    "write a goodbye note to Sandra",
    "the goodbye email never sent",
    "is it a good night for a launch?",
    "we're done here?",                      # a question is never an exit
    "maybe later",                           # 'bye' inside a word
    "draft the goodbye section of the newsletter and talk tomorrow's plan",
    "",
    "how's the business doing?",
])
def test_sentences_about_goodbyes_do_not_match(msg):
    assert not cos._is_farewell(msg), msg


def test_long_messages_never_match():
    msg = "goodbye " + "and one more thing " * 10
    assert not cos._is_farewell(msg)


# ─────────────────────────────────────────────────────────────────────
# 2 + 3. Enforcement through a real turn
# ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def run_turn(monkeypatch):
    """Drive chief_chat with all I/O stubbed; the model's reply text is
    scripted per call so tests control whether it emitted the tag."""
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow", lambda *a, **k: True)

    async def _instant(value=None):
        return value

    async def _fake_sb(client, method, path, body=None):
        return [_BIZ]
    monkeypatch.setattr(cos, "_sb", _fake_sb)
    monkeypatch.setattr(cos, "_generate_missing_recurring_instances", lambda *a, **k: _instant(0))
    monkeypatch.setattr(cos, "_autopilot_sweep", lambda *a, **k: _instant(0))
    monkeypatch.setattr(cos, "_evaluate_escalations", lambda *a, **k: _instant(0))
    monkeypatch.setattr(cos, "_gather_context",
                        lambda *a, **k: _instant({"business": _BIZ, "contacts": []}))
    monkeypatch.setattr(cos, "_fetch_view_detail", lambda *a, **k: _instant(""))
    for name in ["_get_voice_examples", "_get_session_context",
                 "_get_time_context", "_get_habit_insights"]:
        monkeypatch.setattr(cos, name, lambda *a, **k: _instant(""))
    monkeypatch.setattr(cos, "_should_show_mentor_tip", lambda *a, **k: _instant(False))
    monkeypatch.setattr(cos, "_forecast_revenue", lambda *a, **k: _instant(None))
    monkeypatch.setattr(cos, "_analyze_relationships", lambda *a, **k: _instant([]))
    monkeypatch.setattr(cos, "_build_system_prompt", lambda *a, **k: "SYSTEM")
    monkeypatch.setattr(cos, "_log_chief_activity", lambda *a, **k: _instant(None))
    monkeypatch.setattr(cos, "_learn_patterns_async", lambda *a, **k: _instant(None))
    # The two-pass composer would need its own model call; pass through.
    monkeypatch.setattr(cos, "_compose_post_action_reply",
                        lambda *a, **k: _instant(""))

    import chief_bookkeeping
    import chief_proactive_suggestions
    import vertical_context
    monkeypatch.setattr(chief_bookkeeping, "gather_and_format", lambda *a, **k: "")
    monkeypatch.setattr(vertical_context, "build_vertical_learned_block", lambda *a, **k: "")
    monkeypatch.setattr(chief_proactive_suggestions,
                        "maybe_emit_proactive_suggestions", lambda *a, **k: None)

    class _Session:
        class _User:
            id = "user-1"
        user = _User()
        token = "test-jwt"

    def run(message, model_reply):
        async def fake_claude(*a, **k):
            return model_reply
        monkeypatch.setattr(cos, "_call_claude", fake_claude)
        out = asyncio.run(cos.chief_chat(
            cos.ChatRequest(business_id="biz-1", message=message), _Session()))
        return out

    return run


def _window_actions(out):
    return [a for a in out.get("actions_taken", [])
            if a.get("type") == "set_chat_window"]


def test_a_forgotten_tag_is_enforced(run_turn):
    out = run_turn("goodnight chief", "Goodnight, Kevin. Rest well.")
    wins = _window_actions(out)
    assert len(wins) == 1, "the model forgot the tag — the server must not"
    fe = wins[0].get("frontend_event") or {}
    assert fe.get("name") == "solutionist-chat-window"
    assert fe["detail"] == {"visible": False, "keep_talking": False}, (
        "the client closes the window through the same door the model's "
        "own tag would have used"
    )


def test_a_remembered_tag_is_not_doubled(run_turn):
    out = run_turn(
        "goodnight chief",
        'Goodnight! [ACTION:{"type":"set_chat_window","visible":false,"keep_talking":false}]')
    assert len(_window_actions(out)) == 1, "enforcement fills gaps, never doubles"


def test_a_normal_message_is_never_closed_on(run_turn):
    out = run_turn("when i did the goodbye's chief never closed out the chat",
                   "Let me look into that for you.")
    assert not _window_actions(out), (
        "a bug report about goodbyes must not end the session"
    )


def test_coach_pauses_keep_their_own_choreography(run_turn, monkeypatch):
    monkeypatch.setattr(cos, "_is_farewell", lambda m: True)  # force-match
    out = None
    async def go():
        return None
    # coach mode: the request carries mode; enforcement must skip
    class _Session:
        class _User:
            id = "user-1"
        user = _User()
        token = "test-jwt"
    async def fake_claude(*a, **k):
        return "Warm parting words."
    monkeypatch.setattr(cos, "_call_claude", fake_claude)
    out = asyncio.run(cos.chief_chat(
        cos.ChatRequest(business_id="biz-1", message="that's all for now",
                        mode="strategy_coach"), _Session()))
    assert not _window_actions(out)
