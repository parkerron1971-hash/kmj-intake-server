"""
test_build_readiness.py — the "before you approve" pass (2026-08-28).
"""
import build_readiness as br


def _ctx(**over):
    base = {"gallery": [], "offerings": [], "testimonials": [],
            "settings": {"brand_kit": {}},
            "site": {"site_config": {"discovery_dossier": {
                "gaps": ["brand_mark_missing", "work_missing"],
                "meta": {}}}},
            "store": {"enabled": False, "items": []}}
    base.update(over)
    return base


def test_macnificent_shaped_context_names_every_gap_in_plain_words():
    """Zero photos, no mark, two services, no testimonials, an empty
    shop, an unfinished session — the exact shape that shipped."""
    r = br.spec_readiness(_ctx(offerings=[{"name": "Box braids"},
                                          {"name": "Kids"}]))
    assert r["photos"] == 0 and r["brand_mark"] is False
    assert r["offerings"] == 2 and r["session_done"] is False
    joined = " ".join(r["notes"])
    assert "No photos" in joined and "typographic" in joined
    assert "No logo" in joined and "wordmark" in joined
    assert "2 offerings on file" in joined
    assert "No testimonials" in joined
    assert "Nothing in the shop" in joined
    assert "Design Session was not finished" in joined
    assert len(r["notes"]) <= 6 and 1 <= len(r["chips"]) <= 4
    assert any("typographic" in c for c in r["chips"])


def test_a_kmj_shaped_context_is_mostly_quiet():
    r = br.spec_readiness(_ctx(
        gallery=[{"url": f"https://x/{i}.jpg"} for i in range(7)],
        offerings=[{"name": f"o{i}"} for i in range(8)],
        testimonials=[{"quote": "great"}],
        settings={"brand_kit": {"logo_url": "https://x/mark.png"}},
        site={"site_config": {"discovery_dossier": {
            "gaps": [], "meta": {"coach_session_completed": {"value": True}}}}},
        store={"enabled": True, "items": [{"name": "tee"}]}))
    assert r["photos"] == 7 and r["brand_mark"] and r["session_done"]
    assert r["chips"] == []
    assert r["notes"] == ["7 photos on file — the gallery will be real.",
                          "8 offerings on file."]


def test_readiness_never_raises_on_a_bare_context():
    r = br.spec_readiness({})
    assert r["photos"] == 0 and r["notes"] and r["gaps"] == []
    assert br.spec_readiness(None)["offerings"] == 0
