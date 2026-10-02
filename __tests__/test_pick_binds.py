"""The pick binds (2026-09-04). A tapped look in the Design Coach used
to arrive as a chat line and bind nothing: the coach saved no field,
and the build's language resolver read only the rationale and the
rubric. Now the tap is saved by key, the resolver honors it first, and
the Director's brief speaks it."""
import json

import canvas_brief
import design_coach as dc
import design_languages as dl
import spec_author


def _turn(**over):
    base = {"reply": "Neon it is.", "chips": [], "saves": [],
            "stage": "taste", "done": False}
    base.update(over)
    return json.dumps(base)


def test_the_prompt_tells_the_coach_to_save_the_tap():
    assert "THE PICK BINDS" in dc._SYSTEM
    assert '"field": "look"' in dc._SYSTEM


def test_the_tap_is_saved_by_key_whatever_the_phrasing():
    raw = _turn(saves=[
        {"section": "taste", "field": "look", "value": "Neon, that's the one."},
        {"section": "taste", "field": "look", "value": "neon"},
        {"section": "taste", "field": "hero_shape", "value": "The Poster"},
        {"section": "taste", "field": "motion", "value": "the thread"},
        {"section": "taste", "field": "look", "value": "windows 98"},   # not a look
    ])
    saves = dc.parse_turn(raw)["saves"]
    assert saves == [
        {"section": "taste", "field": "look", "value": "neon"},
        {"section": "taste", "field": "look", "value": "neon"},
        {"section": "taste", "field": "hero_shape", "value": "poster"},
        {"section": "taste", "field": "motion", "value": "the-thread"},
    ]


def _ctx_with_pick(key, source="asked"):
    return {"site": {"site_config": {"discovery_dossier": {
                "taste": {"look": {"value": key, "source": source}}}}},
            "site_prefs": {"boldness": "bold"}, "gallery": [{}] * 4,
            "business": {"type": "creative"}}


def test_the_owners_pick_outranks_the_rationale_and_the_rubric():
    dro = {"decisions": {"language": {"choice": "ledger", "because": "the evidence"}}}
    key, because, by = dl.resolve(_ctx_with_pick("neon"), dro)
    assert (key, by) == ("neon", "owner")
    assert "Design Coach" in because


def test_only_a_practitioner_sourced_pick_binds():
    dro = {"decisions": {"language": {"choice": "ledger", "because": "x"}}}
    assert dl.resolve(_ctx_with_pick("neon", source="recon"), dro)[0] == "ledger"
    assert dl.resolve(_ctx_with_pick("not-a-look"), dro)[0] == "ledger"
    assert dl.owner_pick({}) is None


def test_the_director_brief_speaks_the_language():
    ctx = _ctx_with_pick("neon")
    ctx.update({"business": {"name": "Marrow & Steel", "type": "barbershop"},
                "dna": {}, "bundle": {}, "offerings": [], "testimonials": []})
    assert spec_author.attach_language(ctx, None) == "neon"
    assert ctx["language_by"] == "owner"
    brief = canvas_brief.compile_canvas_brief(ctx, None, [])
    assert "THE DESIGN LANGUAGE" in brief
    assert "language: neon" in brief
    assert "NEON LANGUAGE" in brief
