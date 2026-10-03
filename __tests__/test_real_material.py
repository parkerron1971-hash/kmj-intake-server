"""THE REAL MATERIAL (2026-10-03, the hand-build plan, step 2a).

From the first live Chief -> Coach -> build test on Vertical Test Coach:
- "Six years running the practice" was saved by the Coach and then
  deleted from the page by the tenure law, which never read where the
  Coach saved it, nor number words like "six".
- "Before you build" said "no testimonials" over the client story the
  owner had just told the Coach.
- Chief's own notes ("warm, professional, polished"; "no services on
  file") reached the Director as THE OWNER'S WORDS.
"""
import builder_v2
import build_readiness
import canvas_brief
import site_facts

_DOSSIER = {
    "truth": {"proven_stats": [
        {"label": "years in corporate HR", "value": "15", "proof": "owner's own account"},
        {"label": "years running the practice", "value": "6", "proof": "owner's own account"},
        {"label": "people coached through a career change", "value": "about 140"}]},
    "story": {
        "origin": {"value": "I spent 15 years in corporate HR, so six years ago I started this practice.",
                   "source": "asked"},
        "proof": {"value": "Dana left banking and opened a pottery studio.", "source": "asked"}},
}


def _ctx(dossier=None, **over):
    base = {"business": {"name": "Vertical Test Coach", "type": "coach"},
            "site": {"site_config": {"discovery_dossier": dossier or {}}}}
    base.update(over)
    return base


# ─── the years the owner stated ──────────────────────────────────────

def test_a_saved_tenure_stat_counts_as_stated_years():
    assert 6 in site_facts.stated_years({}, {"truth": _DOSSIER["truth"]})
    # a stat that is not about years never becomes a tenure
    assert 140 not in site_facts.stated_years({}, {"truth": _DOSSIER["truth"]})


def test_years_written_out_in_words_count():
    years = site_facts.stated_years({}, {"story": _DOSSIER["story"]})
    assert 15 in years and 6 in years
    assert 25 in site_facts.stated_years({"owner_brief": "twenty-five years behind the chair"}, {})


def test_the_tenure_law_keeps_a_true_six_years(monkeypatch):
    monkeypatch.setattr(builder_v2, "connected_systems_block", lambda b, c: "")
    facts = site_facts.build_facts(_ctx(_DOSSIER), "biz", profile={})
    data = site_facts.facts_block(facts)
    html = "<html><body><p>Six years running the practice, 6 years in.</p></body></html>"
    assert builder_v2.check_tenure(html, data) == []
    invented = "<html><body><p>9 years in business.</p></body></html>"
    assert builder_v2.check_tenure(invented, data), "an invented tenure still fails"


# ─── before you build reads the session ──────────────────────────────

def test_the_card_credits_the_client_story_told_to_the_coach():
    out = build_readiness.spec_readiness(_ctx(_DOSSIER))
    assert any("client story you told the Coach" in n for n in out["notes"])
    assert not any("there will be no proof section" in n for n in out["notes"])


def test_the_card_names_the_offers_told_to_the_coach():
    d = dict(_DOSSIER, truth=dict(_DOSSIER["truth"], offers=[
        {"name": "Next Chapter", "price": "$1,200"}, {"name": "Single session", "price": "$150"}]))
    out = build_readiness.spec_readiness(_ctx(d))
    note = next(n for n in out["notes"] if "Next Chapter" in n)
    assert "Single session" in note
    assert not any("No services or offerings on file" in n for n in out["notes"])


def test_with_nothing_said_the_card_still_says_what_is_missing():
    out = build_readiness.spec_readiness(_ctx({}))
    assert any("No services or offerings on file" in n for n in out["notes"])
    assert any("there will be no proof section" in n for n in out["notes"])


# ─── Chief's notes are Chief's ───────────────────────────────────────

def test_chief_s_notes_reach_the_director_labeled_as_chief_s():
    ctx = _ctx(_DOSSIER, chief_notes="Warm, professional and polished tone. No services on file.")
    brief = canvas_brief.compile_canvas_brief(ctx, None, [])
    assert "CHIEF'S HANDOFF NOTES" in brief and "NOT the owner's words" in brief
    assert "THE OWNER'S WORDS" not in brief
    assert "Warm, professional and polished tone" in brief


def test_the_owner_s_own_words_keep_their_place():
    brief = canvas_brief.compile_canvas_brief(_ctx(_DOSSIER, owner_brief="Make it feel like my study."), None, [])
    assert "THE OWNER'S WORDS" in brief and "CHIEF'S HANDOFF NOTES" not in brief


def test_chief_s_notes_never_reach_the_builder(monkeypatch):
    monkeypatch.setattr(builder_v2, "connected_systems_block", lambda b, c: "")
    data = builder_v2.assemble_real_data(_ctx(_DOSSIER, chief_notes="No services on file."), "biz")
    assert "No services on file" not in data


def test_the_blueprint_job_carries_chief_s_notes_onto_the_context(monkeypatch):
    import site_composer
    import spec_author
    seen = {}
    monkeypatch.setattr(site_composer, "_spec_inputs", lambda b: (_ctx(_DOSSIER), None, []))
    monkeypatch.setattr(spec_author, "author_spec",
                        lambda b, ctx, dro, plan, **kw: seen.setdefault("ctx", ctx) and None)
    site_composer.author_spec_work("biz", notes="", chief_notes="They want warmth.")
    assert seen["ctx"]["chief_notes"] == "They want warmth."
    assert "owner_brief" not in seen["ctx"]


def test_chief_is_told_to_pass_only_the_owner_s_words():
    import chief_of_staff  # noqa: F401  (chief_prompt imports through it)
    import chief_prompt
    src = open(chief_prompt.__file__, encoding="utf-8").read()
    assert "Pass only what THEY told you about their site in this chat" in src
    assert "nothing about what is missing or not on file" in src
