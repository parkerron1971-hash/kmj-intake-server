"""The owner's own tenure is a fact on file (2026-09-04, the barbershop
bench). "I've been cutting 14 years" about a shop founded in 2021 was a
TENURE CLAIM violation, and the repair round stripped it."""
import builder_v2 as v2
import site_facts as sf


def _ctx():
    return {"business": {"name": "Marrow & Steel", "type": "barbershop"},
            "settings": {"founded_year": 2021},
            "owner_brief": "I've been cutting 14 years, opened this shop in 2021.",
            "contact": {}, "offerings": [], "gallery": [], "testimonials": [],
            "site": {"site_config": {"discovery_dossier": {
                "identity": {"team": [{"name": "Tomas", "role": "Barber, 6 yrs behind a chair"}]},
                "truth": {"proven_stats": []}}}}}


def test_stated_years_are_collected_from_the_owners_words_and_dossier(monkeypatch):
    monkeypatch.setattr(v2, "connected_systems_block", lambda b, ctx: "")
    f = sf.build_facts(_ctx(), "b", profile={})
    assert f["founded_year"] == 2021
    assert f["stated_years"] == [14, 6]
    block = sf.facts_block(f)
    assert "Years the owner stated" in block and "14 years" in block and "6 years" in block


def test_the_law_accepts_what_the_owner_said_and_still_catches_inventions():
    facts = {"years_in_business": 5, "stated_years": [14]}
    assert sf.tenure_claims("Cutting for 14 years. 5 years on Detroit Ave.", facts) == []
    bad = sf.tenure_claims("20 years of experience", facts)
    assert bad and bad[0].startswith("TENURE CLAIM: '20 years")


def test_the_builder_reads_the_stated_line(monkeypatch):
    monkeypatch.setattr(v2, "connected_systems_block", lambda b, ctx: "")
    block = sf.facts_block(sf.build_facts(_ctx(), "b", profile={}))
    real = "BUSINESS: x\n\n" + block
    page = "<html><body><p>Deshawn has been cutting for 14 years.</p></body></html>"
    assert v2.check_tenure(page, real) == []
    page2 = "<html><body><p>25 years of fades.</p></body></html>"
    assert any("TENURE CLAIM" in p for p in v2.check_tenure(page2, real))


def test_nothing_stated_changes_nothing():
    assert sf.stated_years({}, {}) == []
    assert "Years the owner stated" not in sf.facts_block({"founded_year": None})
