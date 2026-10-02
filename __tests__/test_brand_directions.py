"""
test_brand_directions.py — "Rethink my brand" offers three directions.

What must hold:
  • The model is asked ONCE for three contrasting kits, briefed with the
    same business context as the single kit (_brand_context_lines), plus
    whatever the owner just typed (the essence) — which leads.
  • A direction is only shown if it can be shown honestly: five real
    6-digit hex colours and two named faces. A malformed one is dropped,
    not repaired into something the model never proposed.
  • Nothing is saved. Publish stays the only door to live.
"""
import json

import pytest

import brand_engine


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _kit(primary="#1E3A34", heading="Fraunces"):
    return {"tagline": "t", "elevator_pitch": "p",
            "colors": {"primary": primary, "secondary": "#7A8F7E", "accent": "#D9793B",
                       "background": "#F6F1E8", "text": "#1B1F1D"},
            "font_pair": {"heading": heading, "body": "Work Sans"},
            "tone_words": ["steady", "warm"], "visual_style": "calm"}


@pytest.fixture
def model(monkeypatch):
    sent = {}
    reply = {"status": 200, "directions": []}

    def fake_post(client, payload, **kw):
        sent["payload"] = payload
        sent["kw"] = kw
        text = json.dumps({"directions": reply["directions"]})
        return _Resp(reply["status"], {"content": [{"type": "text", "text": text}]})

    monkeypatch.setattr(brand_engine.llm_call, "post_with", fake_post)
    monkeypatch.setattr(brand_engine, "_anthropic_key", lambda: "k")
    monkeypatch.setattr(brand_engine, "_brand_context_lines",
                        lambda biz: ["Business name: Harbor & Pine", "Archetype: coach"])
    monkeypatch.setattr(brand_engine, "save_brand_kit",
                        lambda *a, **k: pytest.fail("directions must never save"))
    return sent, reply


def test_three_clean_directions_come_back(model):
    sent, reply = model
    reply["directions"] = [
        {"name": "Evergreen", "why": "calm", "kit": _kit()},
        {"name": "Tidewater", "why": "clear", "kit": _kit("#16324f", "DM Serif Display")},
        {"name": "Ember", "why": "bold", "kit": _kit("#3B1F2B", "Syne")},
    ]
    out = brand_engine.generate_directions("biz-1")
    assert out["ok"] and len(out["directions"]) == 3
    assert out["directions"][1]["kit"]["colors"]["primary"] == "#16324F", "hex is normalized to upper case"
    assert sent["kw"]["business_id"] == "biz-1"
    assert "THREE clearly different" in sent["payload"]["system"]


def test_a_malformed_direction_is_dropped_not_repaired(model):
    _, reply = model
    bad_hex = _kit(primary="teal")
    no_face = _kit()
    no_face["font_pair"] = {"heading": "", "body": "Work Sans"}
    reply["directions"] = [
        {"name": "Bad colour", "kit": bad_hex},
        {"name": "No face", "kit": no_face},
        {"name": "Good", "kit": _kit()},
        "not even an object",
    ]
    out = brand_engine.generate_directions("biz-1")
    assert [d["name"] for d in out["directions"]] == ["Good"]


def test_nothing_usable_is_an_error(model):
    _, reply = model
    reply["directions"] = [{"name": "Bad", "kit": _kit(primary="#12")}]
    out = brand_engine.generate_directions("biz-1")
    assert out["ok"] is False and "unusable" in out["error"]


def test_the_owners_fresh_words_lead_the_brief(model):
    sent, reply = model
    reply["directions"] = [{"name": "A", "kit": _kit()}]
    brand_engine.generate_directions("biz-1", {
        "tagline": "Lead the next chapter.",
        "elevator_pitch": "I coach new directors.",
        "tone_words": ["steady", "direct"],
    })
    msg = sent["payload"]["messages"][0]["content"]
    assert "Their tagline: Lead the next chapter." in msg
    assert "I coach new directors." in msg
    assert "How they want to sound: steady, direct" in msg


def test_a_model_error_says_so(model):
    _, reply = model
    reply["status"] = 529
    out = brand_engine.generate_directions("biz-1")
    assert out["ok"] is False and "couldn't sketch" in out["error"].lower()
    assert "Kai" not in out["error"], "the assistant's name is per business; the server stays neutral"


def test_the_single_kit_and_the_directions_share_one_brief(monkeypatch):
    """generate_from_context used to build its own context inline; both
    now read _brand_context_lines, so they can't be briefed differently."""
    seen = {}
    monkeypatch.setattr(brand_engine, "_brand_context_lines", lambda biz: ["Business name: X"])
    monkeypatch.setattr(brand_engine, "_call_claude_for_kit",
                        lambda system, user: seen.setdefault("user", user) and {"ok": True})
    brand_engine.generate_from_context("biz-1")
    assert seen["user"] == "Generate a brand kit for:\n\nBusiness name: X"


def test_an_unknown_business_is_refused(monkeypatch):
    monkeypatch.setattr(brand_engine, "_brand_context_lines", lambda biz: None)
    assert brand_engine.generate_directions("nope")["ok"] is False
    assert brand_engine.generate_from_context("nope")["ok"] is False
