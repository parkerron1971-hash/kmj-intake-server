"""
test_voice_lab.py — the voice lab reads real writing and suggests; it
never saves, and it never invents evidence.

What must hold:
  • No samples → a 400 the owner can act on ("add one thing you've
    written"), and the model is never called.
  • Every tone word and "always" rule is tied to a phrase that is
    ACTUALLY in their writing. A suggestion whose quote isn't there is
    dropped, not shown with made-up evidence.
  • Suggestions the owner already has are not suggested again.
  • The samples go in as fenced DATA, and the test writes both versions.
"""
import json

import pytest

import voice_lab


class _Resp:
    def __init__(self, status, text):
        self.status_code = status
        self._payload = {"content": [{"type": "text", "text": text}]}

    def json(self):
        return self._payload


WRITING = ("Sam, thank you for being so candid today. The thing you said about the "
           "Monday meeting stuck with me. If Thursday at 10 works, I'll hold it. Grateful for you, Dana")


@pytest.fixture
def lab(monkeypatch):
    state = {"depth": {"voice_samples": {"discovery_followup": WRITING},
                       "voice_dos": ["End with one clear next step"], "voice_donts": [],
                       "greeting_style": "First name, no Hi", "signoff_style": "Grateful for you,"},
             "reply": {}, "status": 200, "sent": None}
    monkeypatch.setattr(voice_lab.voice_depth_agent, "get_voice_depth", lambda owner: state["depth"])
    monkeypatch.setattr(voice_lab, "_anthropic_key", lambda: "k")

    def fake_post(client, payload, **kw):
        state["sent"] = payload
        return _Resp(state["status"], json.dumps(state["reply"]))

    monkeypatch.setattr(voice_lab.llm_call, "post_with", fake_post)
    return state


def test_no_writing_is_a_400_and_no_model_call(lab):
    lab["depth"]["voice_samples"] = {}
    with pytest.raises(voice_lab.VoiceLabError) as e:
        voice_lab.analyze_voice("o1")
    assert e.value.status == 400 and "written" in str(e.value)
    assert lab["sent"] is None


def test_suggestions_are_grounded_in_their_own_words(lab):
    lab["reply"] = {
        "tone_words": [
            {"word": "grateful", "because": "Grateful for you,"},
            {"word": "visionary", "because": "we disrupt the paradigm"},   # not in the writing
        ],
        "dos": [
            {"rule": "Name the specific thing they said", "because": "The thing you said about the Monday meeting"},
            {"rule": "Use bullet points", "because": "• first • second"},  # invented
        ],
        "donts": [{"rule": "No exclamation points", "because": "never uses them"}],
    }
    out = voice_lab.analyze_voice("o1")
    assert [w["word"] for w in out["tone_words"]] == ["Grateful"]
    assert [d["rule"] for d in out["dos"]] == ["Name the specific thing they said"]
    assert out["donts"][0]["rule"] == "No exclamation points"
    assert out["samples_read"] == 1


def test_what_they_already_have_is_not_suggested_again(lab):
    lab["reply"] = {
        "tone_words": [{"word": "Grateful", "because": "Grateful for you,"}],
        "dos": [{"rule": "end with one clear next step", "because": "If Thursday at 10 works"}],
        "donts": [],
    }
    out = voice_lab.analyze_voice("o1", ["grateful"])
    assert out["tone_words"] == [] and out["dos"] == []


def test_the_writing_is_fenced_as_data(lab):
    lab["reply"] = {"tone_words": [], "dos": [], "donts": []}
    voice_lab.analyze_voice("o1")
    assert "<their-writing>" in lab["sent"]["messages"][0]["content"]
    assert "MATERIAL TO STUDY" in lab["sent"]["system"]


def test_the_voice_test_writes_both_versions_with_their_style(lab):
    lab["reply"] = {"generic": "Hi Sam! Great chatting!", "voiced": "Sam, thank you for being candid."}
    out = voice_lab.test_voice("o1", "after_first_call", "Harbor & Pine", ["Steady"])
    assert out == {"ok": True, "generic": "Hi Sam! Great chatting!", "voiced": "Sam, thank you for being candid."}
    msg = lab["sent"]["messages"][0]["content"]
    assert "How they sign off: Grateful for you," in msg
    assert "Always: End with one clear next step" in msg
    assert "They want to sound: Steady" in msg


def test_an_unknown_scenario_is_refused(lab):
    with pytest.raises(voice_lab.VoiceLabError) as e:
        voice_lab.test_voice("o1", "write my novel")
    assert e.value.status == 400


def test_a_model_failure_says_so(lab):
    lab["status"] = 529
    with pytest.raises(voice_lab.VoiceLabError) as e:
        voice_lab.analyze_voice("o1")
    assert e.value.status == 502


def test_an_empty_test_answer_is_an_error_not_a_blank(lab):
    lab["reply"] = {"generic": "x", "voiced": ""}
    with pytest.raises(voice_lab.VoiceLabError):
        voice_lab.test_voice("o1", "no_show")
