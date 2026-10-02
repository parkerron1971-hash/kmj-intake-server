"""
test_site_facts.py — ONE SET OF FACTS (2026-08-29).
"""
import builder_v2 as v2
import site_facts as sf
import spec_author


def _ctx(**over):
    base = {"business": {"name": "KMJ Creative Solutions", "type": "consultant"},
            "settings": {}, "contact": {"email": "hi@kmj.example", "phone": ""},
            "offerings": [{"n": 1}] * 8, "gallery": [{"url": "https://x/a.jpg"}] * 7,
            "testimonials": [], "site": {"site_config": {"discovery_dossier": {"truth": {"proven_stats": []}}}}}
    base.update(over)
    return base


def test_kmj_shaped_context_has_no_founding_year_and_the_block_says_so(monkeypatch):
    monkeypatch.setattr(v2, "connected_systems_block",
                        lambda b, ctx: "- BOOKING: ON — every book action links to https://kmjcreate.com/book\n- STORE: OFF — nothing in the shop yet.")
    f = sf.build_facts(_ctx(), "biz-1", profile={})
    assert f["founded_year"] is None and f["years_in_business"] is None
    assert f["offerings"] == 8 and f["photos"] == 7
    block = sf.facts_block(f)
    assert "Founded: NOT ON FILE" in block and "since" in block
    assert "8 offerings, 7 photos, 0 testimonials" in block
    assert "Proven stats: none on file" in block
    assert "BOOKING: ON" in block and "https://kmjcreate.com/book" in block and "STORE: OFF" in block


def test_a_formation_date_on_the_profile_becomes_the_founding_year(monkeypatch):
    monkeypatch.setattr(v2, "connected_systems_block", lambda b, ctx: "")
    f = sf.build_facts(_ctx(), "biz-1", profile={"formed_on": "2022-03-14", "legal_name": "KMJ Creative Solutions LLC",
                                                 "phone": "231-555-0100", "address_city": "Muskegon", "address_state": "MI"})
    assert f["founded_year"] == 2022 and f["years_in_business"] == 4
    block = sf.facts_block(f)
    assert "- Founded: 2022 (4 years in business)" in block
    assert "Legal name: KMJ Creative Solutions LLC" in block and "Muskegon, MI" in block
    # the sticky document default and a dossier stat are also read
    f2 = sf.build_facts(_ctx(settings={"doc_defaults": {"founded": "2019"}}), "biz-1", profile={})
    assert f2["founded_year"] == 2019
    f3 = sf.build_facts(_ctx(site={"site_config": {"discovery_dossier": {"truth": {"proven_stats": [
        {"stat": "Established", "value": "2015"}]}}}}), "biz-1", profile={})
    assert f3["founded_year"] == 2015 and f3["proven_stats"] == ["Established: 2015"]


def test_tenure_claims_are_a_law():
    none = {"years_in_business": None}
    assert sf.tenure_claims("4 years turning stuck into started", none)[0].startswith("TENURE CLAIM: '4 years")
    assert "no founding year" in sf.tenure_claims("12+ yrs experience", none)[0]
    four = {"years_in_business": 4}
    assert sf.tenure_claims("4 years turning stuck into started", four) == []
    assert "has 4 years on file" in sf.tenure_claims("10 years of experience", four)[0]
    assert sf.tenure_claims("Book a session in 2 weeks", none) == []


def test_the_builder_law_reads_the_facts_block(monkeypatch):
    page = "<html><body><p>4 years turning stuck into started</p></body></html>"
    no_year = "BUSINESS: x\n\nTHE FACTS (…):\n- Founded: NOT ON FILE — do not state a founding year"
    assert any("TENURE CLAIM" in p for p in v2.check_tenure(page, no_year))
    four = "BUSINESS: x\n\nTHE FACTS (…):\n- Founded: 2022 (4 years in business)"
    assert v2.check_tenure(page, four) == []
    # and the founding year itself now passes the truth trace
    assert v2.check_truth("<html><body><p>Since 2022</p></body></html>", four) == []
    assert v2.check_tenure(page, "BUSINESS: x") == []          # no facts block → silent


def test_the_director_is_handed_the_facts_and_the_law():
    assert "THE FACTS LAW" in spec_author._SYSTEM
    assert "no \"since 2022\"" in spec_author._SYSTEM or "since 2022" in spec_author._SYSTEM
    p = spec_author.build_user_prompt("DOSSIER", [], facts="- Founded: NOT ON FILE — do not state a founding year")
    assert "== THE FACTS" in p and "NOT ON FILE" in p
    assert "== THE FACTS" not in spec_author.build_user_prompt("DOSSIER", [])
