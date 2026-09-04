"""The coach offers more looks and chooses them for the business
(2026-09-04). Eleven looks existed; the prompt's worked example named
three, the server capped at four, and the model copied the example."""
import json

import design_coach as dc
import design_languages as dl


def _turn(**over):
    base = {"reply": "Which of these feels like your shop?", "chips": [],
            "saves": [], "stage": "taste", "done": False}
    base.update(over)
    return json.dumps(base)


def test_the_prompt_no_longer_hands_the_model_a_trio():
    assert '["mural", "monograph", "ledger"]' not in dc._SYSTEM
    assert "never a default trio" in dc._SYSTEM
    assert "LOOKS THAT FIT THIS BUSINESS" in dc._SYSTEM
    assert "ONE more time" in dc._SYSTEM


def test_the_catalog_is_generated_from_the_registry():
    for key, v in dl.LANGUAGES.items():
        assert f"  {key}: " in dc._SYSTEM, key
        assert "Sings for" in dc._SYSTEM
    assert "{LOOKS_CATALOG}" not in dc._SYSTEM


def test_six_looks_survive_parse_and_four_for_the_rest():
    six = ["mural", "neon", "atelier", "hearth", "glass", "arena", "runway"]
    out = dc.parse_turn(_turn(gallery={"kind": "looks", "options": six}))
    assert out["gallery"]["options"] == six[:6]
    lay = ["split-stage", "poster", "editorial", "exhibition", "monument"]
    out = dc.parse_turn(_turn(gallery={"kind": "layouts", "options": lay}))
    assert out["gallery"]["options"] == lay[:4]


def test_the_shortlist_is_chosen_for_the_trade():
    barber = [r["key"] for r in dc.suggest_looks("barbershop", photos=4,
                                                 prefs={"boldness": "bold"})]
    assert barber[0] == "neon", barber
    church = [r["key"] for r in dc.suggest_looks("church", photos=6,
                                                 prefs={"boldness": "calm"})]
    assert church[0] == "hearth", church
    saas = [r["key"] for r in dc.suggest_looks("saas platform", photos=0,
                                               prefs={"type_personality": "modern"})]
    assert saas[0] == "glass", saas
    lash = [r["key"] for r in dc.suggest_looks("lash artist", photos=8,
                                               prefs={"boldness": "calm"})]
    assert lash[0] == "atelier", lash
    assert len(barber) == 6 and len(set(barber)) == 6


def test_the_shortlist_rides_the_known_context_block():
    block = dc.looks_that_fit_block("barbershop", 4, {"boldness": "bold"})
    assert block.startswith("LOOKS THAT FIT THIS BUSINESS")
    assert "- neon:" in block
    assert dc.looks_that_fit_block("", 0, {}) != ""     # a shortlist always exists
