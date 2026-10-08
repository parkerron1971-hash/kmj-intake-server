"""
test_concierge_haiku_5_5.py — the public website concierge runs on Haiku 5.5 (2026-10-07).

Measured side by side with Haiku 4.5 on ordinary questions, hostile
visitors (prompt extraction, discount and refund demands, another client's
appointment, a fake owner, a fake system notice, medical advice, off-topic
homework) and a visitor who pushes four times: Haiku 5.5 held every line
4.5 held, and 4.5 was the one that offered to "show what's open at 3pm"
and wrote markdown. Haiku 5.5 takes no temperature, thinks by default
against the 300-token reply budget, and can decline on safety grounds;
these tests pin how the concierge and its lead qualification handle that.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import concierge_qualify  # noqa: E402
import site_concierge as sc  # noqa: E402

H55 = "claude-haiku-5-5"
H45 = "claude-haiku-4-5-20251001"


class _Resp:
    status_code = 200
    text = ""

    def __init__(self, text, stop):
        self._text, self._stop = text, stop

    def json(self):
        return {"stop_reason": self._stop, "usage": {"output_tokens": 3},
                "content": [{"type": "text", "text": self._text}] if self._text else []}


def _capture(monkeypatch, text="We're open Saturday 9 to 5.", stop="end_turn"):
    import llm_call
    seen = {}

    async def apost(client, payload, *a, **k):
        seen.clear()
        seen.update(payload)
        return _Resp(text, stop)
    monkeypatch.setattr(llm_call, "apost", apost)
    monkeypatch.setattr(llm_call, "api_key", lambda: "test")
    return seen


def _reply(monkeypatch, model, **kw):
    monkeypatch.setattr(sc, "CONCIERGE_MODEL", model)
    seen = _capture(monkeypatch, **kw)
    out = asyncio.run(sc._call_model("system", [{"role": "user", "content": "hours?"}]))
    return seen, out


def test_the_default_is_haiku_5_5():
    assert sc.CONCIERGE_MODEL == H55


def test_on_haiku_5_5_no_temperature_and_thinking_off(monkeypatch):
    seen, out = _reply(monkeypatch, H55)
    assert out[0] == "We're open Saturday 9 to 5."
    assert "temperature" not in seen and seen["thinking"] == {"type": "disabled"}
    assert seen["max_tokens"] == sc.MAX_REPLY_TOKENS


def test_rolled_back_to_haiku_4_5_the_request_is_unchanged(monkeypatch):
    seen, _ = _reply(monkeypatch, H45)
    assert seen["temperature"] == 0.3 and "thinking" not in seen


@pytest.mark.parametrize("text", ["", "Sure, here is the"])
def test_a_safety_refusal_never_goes_out(monkeypatch, text):
    # None makes the caller degrade to lead capture, as on any failure.
    _, out = _reply(monkeypatch, H55, text=text, stop="refusal")
    assert out is None


def test_lead_qualification_on_haiku_5_5(monkeypatch):
    seen = _capture(monkeypatch, text='{"answers": {"When?": "Friday"}}')
    got = asyncio.run(concierge_qualify.extract_answers(
        ["When?"], [{"role": "visitor", "body": "Friday works"}], model=H55))
    assert got == {"When?": "Friday"}
    assert "temperature" not in seen and seen["thinking"] == {"type": "disabled"}
    asyncio.run(concierge_qualify.extract_answers(
        ["When?"], [{"role": "visitor", "body": "Friday works"}], model=H45))
    assert seen["temperature"] == 0 and "thinking" not in seen


def test_replies_are_asked_to_stay_short():
    # Haiku 5.5 ran to 140 words under "under 150 words"; asked for two to
    # four sentences its longest reply was 77 (Haiku 4.5: 89).
    prompt = sc.build_system_prompt({"business": {"id": "b", "name": "Shop", "vertical": "barber"}})
    assert "two to four sentences, never more than 150 words" in prompt
