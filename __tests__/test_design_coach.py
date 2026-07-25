"""
test_design_coach.py — the Design Coach (discovery's conversational
door, 2026-07-25).

Pins the turn contract (strict JSON in/out), the save plumbing into
the ONE dossier with provenance 'asked', the known-context injection
(never re-ask), and the new dossier sections riding the practitioner
door + the Director's digest.
"""
import json
from unittest import mock

import design_coach as dc
import discovery


# ─── parse_turn: the strict-JSON contract ────────────────────────────

def _turn(**over):
    base = {"reply": "Tell me about your shop.", "chips": ["It's cozy"],
            "saves": [], "stage": "world", "done": False}
    base.update(over)
    return json.dumps(base)


def test_parse_turn_happy_path_with_fences():
    out = dc.parse_turn("```json\n" + _turn() + "\n```")
    assert out["reply"].startswith("Tell me")
    assert out["stage"] == "world" and out["done"] is False


def test_parse_turn_rejects_junk_and_empty_reply():
    assert dc.parse_turn("not json at all") is None
    assert dc.parse_turn(_turn(reply="")) is None


def test_parse_turn_sanitizes_saves_and_pair():
    raw = _turn(saves=[
        {"section": "story", "field": "voice", "value": "they say wow"},
        {"section": "hacking", "field": "x", "value": "nope"},   # bad section
        {"section": "taste", "field": "", "value": "x"},         # no field
        {"section": "identity", "field": "one_liner", "value": ""},  # empty
    ], pair={"key": "ground", "a": "Dark", "b": "Light"})
    out = dc.parse_turn(raw)
    assert len(out["saves"]) == 1
    assert out["saves"][0]["section"] == "story"
    assert out["pair"]["a"] == "Dark"
    # bad pair dropped
    assert dc.parse_turn(_turn(pair={"key": "x", "a": "only"}))["pair"] is None


def test_parse_turn_bad_stage_defaults_and_reflect_back_capped():
    out = dc.parse_turn(_turn(stage="nonsense",
                              reflect_back=[f"line {i}" for i in range(20)]))
    assert out["stage"] == "world"
    assert len(out["reflect_back"]) == 12


# ─── apply_saves → the ONE dossier, provenance 'asked' ───────────────

def test_apply_saves_merges_into_dossier_with_asked_provenance():
    store = {"d": discovery._empty_dossier()}

    def _answer(business_id, patch):
        store["d"] = discovery.apply_practitioner_patch(store["d"], patch)
        return store["d"]

    with mock.patch.object(discovery, "answer", side_effect=_answer):
        n = dc.apply_saves("b1", [
            {"section": "story", "field": "voice",
             "value": "clients say it feels like home"},
            {"section": "taste", "field": "ground", "value": "dark"},
            {"section": "signature", "field": "moment",
             "value": "the gold thread walking the page"},
            {"section": "truth", "field": "proven_stats",
             "value": [{"label": "years", "value": "15", "proof": "said so"}]},
        ])
    assert n == 4
    d = store["d"]
    assert d["story"]["voice"]["source"] == "asked"
    assert d["taste"]["ground"]["value"] == "dark"
    assert d["signature"]["moment"]["source"] == "asked"
    assert d["truth"]["proven_stats"][0]["value"] == "15"


def test_new_sections_ride_the_practitioner_door_and_digest():
    d = discovery._empty_dossier()
    merged = discovery.apply_practitioner_patch(d, {
        "world": {"room": {"value": "chrome and leather", "source": "asked"}},
        "story": {"origin": {"value": "started in a garage", "source": "asked"}},
        "signature": {"moment": {"value": "the dots", "source": "asked"}},
    })
    assert merged["world"]["room"]["value"] == "chrome and leather"
    digest = discovery.dossier_digest(merged)
    assert "chrome and leather" in digest and "the dots" in digest


def test_recon_never_overwrites_coach_answers():
    d = discovery._empty_dossier()
    d = discovery.apply_practitioner_patch(d, {
        "identity": {"one_liner": {"value": "the owner's words",
                                   "source": "asked"}}})
    merged = discovery.merge_recon(d, {
        "identity": {"one_liner": {"value": "recon guess",
                                   "source": "recon"}}})
    assert merged["identity"]["one_liner"]["value"] == "the owner's words"


# ─── the prompt: known context rides every turn ──────────────────────

def test_turn_prompt_injects_known_context_first_user_message():
    with mock.patch.object(dc, "_known_context",
                           return_value="BUSINESS: KMJ (consultant)"):
        msgs = dc.build_turn_prompt("b1", [
            {"role": "assistant", "content": "Welcome!"},
            {"role": "user", "content": "hi coach"},
        ])
    assert msgs[0]["role"] == "user"
    joined = " ".join(m["content"] for m in msgs if m["role"] == "user")
    assert "KNOWN CONTEXT" in joined and "BUSINESS: KMJ" in joined
    assert "hi coach" in joined
    # alternation holds for the API
    roles = [m["role"] for m in msgs]
    assert all(a != b for a, b in zip(roles, roles[1:]))


def test_turn_prompt_mirrors_assistant_turns_as_json():
    """The lost-thread bug: prior coach replies fed back as prose made
    the model mirror prose by turn two. Assistant turns must ride the
    transcript in their JSON envelope."""
    with mock.patch.object(dc, "_known_context", return_value="X"):
        msgs = dc.build_turn_prompt("b1", [
            {"role": "assistant", "content": "Welcome to the studio!"},
            {"role": "user", "content": "thanks coach"},
        ])
    assistant = [m for m in msgs if m["role"] == "assistant"]
    assert len(assistant) == 1
    env = json.loads(assistant[0]["content"])
    assert env == {"reply": "Welcome to the studio!"}


def test_parse_turn_sanitizes_gallery():
    good = _turn(gallery={"kind": "looks",
                          "options": ["mural", "monograph", "junk"]})
    out = dc.parse_turn(good)
    assert out["gallery"] == {"kind": "looks",
                              "options": ["mural", "monograph"]}
    # unknown kind or too few valid options → dropped
    assert dc.parse_turn(_turn(gallery={"kind": "vibes",
                                        "options": ["a", "b"]}))["gallery"] is None
    assert dc.parse_turn(_turn(gallery={"kind": "motion",
                                        "options": ["kinetic-hero"]}))["gallery"] is None


def test_prompt_carries_galleries_and_director_carries_motion():
    assert "THE GALLERIES" in dc._SYSTEM
    assert '"kind": "looks"' in dc._SYSTEM
    import spec_author as sa
    assert "THE KINETIC HERO" in sa._SYSTEM
    assert "THE ORBIT" in sa._SYSTEM
    assert "prefers-reduced-motion" in sa._SYSTEM
    # the audited material + modern-motion vocabulary (panels arc)
    assert "THE FOIL" in sa._SYSTEM and "THE EMBOSS" in sa._SYSTEM
    assert "THE TEAR" in sa._SYSTEM and "THE PIN" in sa._SYSTEM
    assert "MICRO-DELIGHT" in sa._SYSTEM


def test_system_prompt_carries_the_standing_rules():
    s = dc._SYSTEM
    assert "ONE question at a time" in s
    assert "NEVER RE-ASK" in s
    assert "dashes" in s            # the dash law reaches the coach too
    assert "screenshots ONE moment" in s
    # THE OPENING (Kevin's study): the coach greets FIRST, by name,
    # and never opens with a menu.
    assert "THE OPENING" in s and "BY NAME" in s
    assert '"how can I help"' in s
    # THE LANE (Kevin: "people must feel the difference"): brand, not
    # business plan — sensory questions only, business facts referenced.
    assert "NOT THE BUSINESS PLAN" in s
    assert "business-plan interview" in s
