"""
test_chief_effort_per_lane.py — Chief thinks in proportion to the lane (2026-09-23).

Live 9/23: "help me think through pricing" -> the main call spent 2,507
output tokens and 46 s for a ~250-token answer. No effort was set, so
Sonnet 5 thought at its default ("high") on every conversational turn.
Chat now answers at "medium", voice at "low"; the deep lane is unchanged.
"""
from __future__ import annotations

import inspect
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_models
import chief_of_staff as cos


def test_lane_defaults(monkeypatch):
    for k in ("CHIEF_EFFORT_CHAT", "CHIEF_EFFORT_VOICE", "CHIEF_EFFORT_DEEP"):
        monkeypatch.delenv(k, raising=False)
    assert chief_models.effort_for("chat") == "medium"
    assert chief_models.effort_for("voice") == "low"
    assert chief_models.effort_for("deep") is None


def test_env_overrides_and_default_means_the_models_own(monkeypatch):
    monkeypatch.setenv("CHIEF_EFFORT_CHAT", "high")
    assert chief_models.effort_for("chat") == "high"
    monkeypatch.setenv("CHIEF_EFFORT_CHAT", "default")
    assert chief_models.effort_for("chat") is None
    monkeypatch.setenv("CHIEF_EFFORT_VOICE", "nonsense")
    assert chief_models.effort_for("voice") is None


def test_the_main_turn_passes_the_lane_effort_and_the_call_sends_it():
    chat_src = inspect.getsource(cos.chief_chat)
    assert "effort=chief_models.effort_for(lane)" in chat_src
    call_src = inspect.getsource(cos._call_claude)
    assert "effort_kwargs(model, effort)" in call_src
