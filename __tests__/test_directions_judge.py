"""
test_directions_judge.py — TWO DIRECTIONS + A JUDGE (2026-08-29, step 5).

Off = exactly one author_dro call (today). On = two candidates with
opposite stances (B authored with A in its cohort), one judge call, the
winner returned with the verdict on its meta; every failure past A keeps
A. The judge's prompt carries the acceptance test's inputs and parses
the letter; anything else → default with the reason on the record.
"""
import json

import pytest

import directions_judge as dj
from agents.composer import drl
from agents.composer.drl import passes as drl_passes


def _exemplar(eid):
    return json.loads(json.dumps(next(e for e in drl.load_exemplars()
                                      if e["exemplar_id"] == eid)))


def _wire(monkeypatch, *, dro_by_stance, judge=None, b_raises=False):
    """Fake the LLM-facing seams: author_dro returns a DRO chosen by the
    stance text it was handed; persist/recent/signals are inert."""
    calls = {"author": [], "judge": []}

    def fake_author(business_id, signals, recent, **kw):
        stance = kw.get("stance") or ""
        key = next((k for k in dro_by_stance
                    if k and k.upper().split(" ")[0] in stance), None) if stance else None
        calls["author"].append({"stance": key, "recent_n": len(recent),
                                "recent_ids": [r.get("exemplar_id") for r in recent]})
        if b_raises and len(calls["author"]) == 2:
            raise RuntimeError("boom")
        return dro_by_stance.get(key)

    monkeypatch.setattr(drl_passes, "author_dro", fake_author)
    monkeypatch.setattr(drl_passes, "detect_signals", lambda *a, **k: [])
    monkeypatch.setattr(drl_passes, "fetch_recent_dros", lambda *a, **k: [])
    monkeypatch.setattr(drl_passes, "fetch_own_last_dro", lambda *a, **k: None)
    monkeypatch.setattr(drl_passes, "persist_dro", lambda *a, **k: "rid-1")
    monkeypatch.setattr(drl_passes.model_ladder, "probe_models_once", lambda *a, **k: None)
    if judge is not None:
        def fake_judge(business_id, signals, candidates, **kw):
            calls["judge"].append({"keys": [k for k, _ in candidates], **kw})
            return judge
        monkeypatch.setattr(dj, "judge", fake_judge)
    return calls


def test_off_is_exactly_one_authoring_call(monkeypatch):
    monkeypatch.delenv("DRO_DIRECTIONS", raising=False)
    a = _exemplar("e13_glass")
    calls = _wire(monkeypatch, dro_by_stance={"concept-literal": a, None: a},
                  judge={"winner": 1, "by": "judge", "because": "x"})
    dro, fail = drl_passes.produce_dro("biz", "intake")
    assert fail is None and dro["exemplar_id"] == "e13_glass"
    assert len(calls["author"]) == 1 and calls["author"][0]["stance"] is None
    assert calls["judge"] == []
    assert "directions" not in (dro.get("meta") or {})


def test_on_authors_two_opposite_stances_judges_once_and_returns_the_winner(monkeypatch):
    monkeypatch.setenv("DRO_DIRECTIONS", "on")
    a, b = _exemplar("e13_glass"), _exemplar("e10_atelier")
    calls = _wire(monkeypatch,
                  dro_by_stance={"concept-literal": a, "tension-led": b},
                  judge={"winner": 1, "by": "judge",
                         "because": "B serves exclusive_premium; A's product frame has no product",
                         "loser_weakness": "no screen to show", "detail": ""})
    signals = [{"signal_id": "energy_signature", "value": "high_conviction",
                "confidence": 0.9, "evidence": ["bold"]}]
    monkeypatch.setattr(drl_passes, "detect_signals", lambda *a, **k: signals)
    dro, fail = drl_passes.produce_dro("biz", "intake", facts_text="THE FACTS (x)")
    assert fail is None and dro["exemplar_id"] == "e10_atelier"      # B won
    assert [c["stance"] for c in calls["author"]] == ["concept-literal", "tension-led"]
    assert calls["author"][1]["recent_ids"] == ["e13_glass"]         # A in B's cohort
    assert len(calls["judge"]) == 1
    assert calls["judge"][0]["keys"] == ["concept-literal", "tension-led"]
    assert calls["judge"][0]["facts_text"] == "THE FACTS (x)"
    d = dro["meta"]["directions"]
    assert d["judge"]["winner"] == "tension-led" and d["judge"]["by"] == "judge"
    assert [c["stance"] for c in d["candidates"]] == ["tension-led", "concept-literal"]
    assert d["candidates"][0]["language"] == "atelier"
    assert d["loser_summary"].startswith("Your site shows the thing")


def test_quiet_owner_gets_the_quiet_reading_as_candidate_b(monkeypatch):
    monkeypatch.setenv("DRO_DIRECTIONS", "on")
    a, b = _exemplar("e13_glass"), _exemplar("e10_atelier")
    calls = _wire(monkeypatch,
                  dro_by_stance={"concept-literal": a, "quiet-editorial": b},
                  judge={"winner": 0, "by": "judge", "because": "A", "loser_weakness": ""})
    dro, _ = drl_passes.produce_dro(
        "biz", "intake", owner_direction={"site_prefs": {"boldness": "quiet"}})
    assert [c["stance"] for c in calls["author"]] == ["concept-literal", "quiet-editorial"]
    assert dro["exemplar_id"] == "e13_glass"                          # A kept on A verdict
    assert dro["meta"]["directions"]["judge"]["winner"] == "concept-literal"


def test_pick_pair_rubric():
    assert dj.pick_pair([], None) == ("concept-literal", "tension-led")
    assert dj.pick_pair([], {"site_prefs": {"boldness": "calm"}}) == ("concept-literal", "quiet-editorial")
    assert dj.pick_pair([], {"site_prefs": {"boldness": "bold"}}) == ("concept-literal", "tension-led")
    deliberate = [{"signal_id": "energy_signature", "value": "deliberate"}]
    assert dj.pick_pair(deliberate, None)[1] == "quiet-editorial"
    # the owner's own word beats the inferred energy
    assert dj.pick_pair(deliberate, {"site_prefs": {"boldness": "loud"}})[1] == "tension-led"


def test_second_candidate_failing_keeps_a_and_skips_the_judge(monkeypatch):
    monkeypatch.setenv("DRO_DIRECTIONS", "on")
    a = _exemplar("e13_glass")
    calls = _wire(monkeypatch, dro_by_stance={"concept-literal": a, "tension-led": None},
                  judge={"winner": 1, "by": "judge", "because": "x"})
    dro, fail = drl_passes.produce_dro("biz", "intake")
    assert fail is None and dro["exemplar_id"] == "e13_glass"
    assert calls["judge"] == []
    assert dro["meta"]["directions"]["judge"]["by"] == "default"
    calls = _wire(monkeypatch, dro_by_stance={"concept-literal": _exemplar("e13_glass"),
                                              "tension-led": _exemplar("e10_atelier")},
                  judge={"winner": 1, "by": "judge", "because": "x"}, b_raises=True)
    dro, fail = drl_passes.produce_dro("biz", "intake")
    assert fail is None and dro["exemplar_id"] == "e13_glass" and calls["judge"] == []


def test_a_failing_is_still_a_failure(monkeypatch):
    monkeypatch.setenv("DRO_DIRECTIONS", "on")
    calls = _wire(monkeypatch, dro_by_stance={"concept-literal": None, "tension-led": _exemplar("e10_atelier")},
                  judge={"winner": 1, "by": "judge", "because": "x"})
    dro, fail = drl_passes.produce_dro("biz", "intake")
    assert dro is None and fail["stage"] == "authoring"
    assert len(calls["author"]) == 1 and calls["judge"] == []


# ─── the judge itself ────────────────────────────────────────────────────
def _candidates():
    return [("concept-literal", _exemplar("e13_glass")), ("tension-led", _exemplar("e10_atelier"))]


def test_judge_prompt_carries_the_acceptance_test_inputs():
    signals = [{"signal_id": "first_five_seconds", "value": "exclusive_premium",
                "confidence": 0.9, "evidence": ["hushed"]},
               {"signal_id": "opening_posture", "value": "craft_first",
                "confidence": 0.3, "evidence": ["weak"]}]        # below threshold
    user = dj.build_user_prompt(
        "biz", signals, _candidates(), facts_text="THE FACTS (Founded NOT ON FILE; 2 photos)",
        owner_direction={"site_prefs": {"boldness": "quiet", "avoid": "pink script",
                                        "colors": {"direction": "bone and brass"}}},
        recent_signatures=[["deep_dark", "single_semantic", "neutral_cool", "geometric_precise",
                            "centered_formal", "balanced", "ambient_breathing", "artifact_showcase"]])
    signals_block = user.split("DETECTED SIGNALS")[1].split("THE FACTS")[0]
    assert "exclusive_premium" in signals_block
    assert "craft_first" not in signals_block                           # only consumable signals
    assert "hushed" not in user                                         # never the quotes
    assert "THE FACTS (Founded NOT ON FILE; 2 photos)" in user
    assert '"avoid": "pink script"' in user and "bone and brass" in user
    assert "CANDIDATE A (stance: concept-literal; shares 8/8" in user  # measured vs cohort
    assert "CANDIDATE B (stance: tension-led; shares" in user
    assert "shows the thing" in user and "quiet gallery" in user         # both summaries
    assert "evidence" not in user.split("CANDIDATE A")[1]                # trimmed DROs
    for word in ("FIRST FIVE SECONDS", "MATERIAL TRUTH", "OWNER'S DIRECTION", "ONE ORGANIZING IDEA"):
        assert word in dj._SYSTEM


def test_judge_parses_the_letter_and_defaults_on_anything_else(monkeypatch):
    monkeypatch.setattr(drl_passes, "_client", lambda: object())
    seen = {}

    def fake_call(client, system, user, **kw):
        seen.update(kw)
        return '{"winner": "B", "because": "criterion 3: A shows a product screen the facts do not have", "loser_weakness": "no screen"}'
    monkeypatch.setattr(drl_passes, "_call", fake_call)
    v = dj.judge("biz", [], _candidates())
    assert v["winner"] == 1 and v["by"] == "judge" and "criterion 3" in v["because"]
    assert seen["task"] == "judge" and seen["prefill"] == '{"winner"'

    monkeypatch.setattr(drl_passes, "_call", lambda *a, **k: "I think A is nicer")
    v = dj.judge("biz", [], _candidates())
    assert v["winner"] == 0 and v["by"] == "default" and "unparseable" in v["detail"]

    def boom(*a, **k):
        raise TimeoutError("slow")
    monkeypatch.setattr(drl_passes, "_call", boom)
    v = dj.judge("biz", [], _candidates())
    assert v["winner"] == 0 and v["by"] == "default" and "TimeoutError" in v["detail"]

    monkeypatch.setattr(drl_passes, "_client", lambda: None)
    v = dj.judge("biz", [], _candidates())
    assert v["winner"] == 0 and "ANTHROPIC_API_KEY" in v["detail"]
    assert dj.judge("biz", [], _candidates()[:1])["detail"] == "fewer than two candidates"


def test_stances_come_from_the_gallery_source_of_truth():
    st = dj.stances()
    assert set(st) >= {"concept-literal", "tension-led", "quiet-editorial"}
    assert st["concept-literal"].startswith("CONCEPT-LITERAL")


def test_switch_is_off_by_default(monkeypatch):
    monkeypatch.delenv("DRO_DIRECTIONS", raising=False)
    assert dj.enabled() is False
    monkeypatch.setenv("DRO_DIRECTIONS", "on")
    assert dj.enabled() is True
